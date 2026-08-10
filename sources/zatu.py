"""Zatu catalogue harvest — Stage 0 (docs/spec.md §3). Shopify's public, unauthenticated
storefront JSON: no auth needed.

Currency note: a locale-prefixed URL (e.g. `/en-us/products/<handle>`) is what returned USD in
the spec's original investigation, and a guessed `/en-gb/` prefix turned out to be a 404 — not a
real route on this store. The fix, confirmed against the live site: drop the locale prefix
entirely and hit the **bare** path (`https://zatu.com/products/<handle>`), which returns the
shop's base currency — GBP, since Zatu is a UK store — directly, no forcing needed. Callers should
still run `verify_gbp_currency` once per harvest as a live check, since Shopify Markets behaviour
like this is exactly the kind of thing that can change without notice.
"""

from __future__ import annotations

import dataclasses
import re
import time
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://zatu.com"
COLLECTION_HANDLE = "top-5000-board-games"
PAGE_LIMIT = 250
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"

# EAN-8, UPC-A (12), EAN-13, GTIN-14 — Zatu's `barcode` field, when populated, is one of these.
_EAN_RE = re.compile(r"^\d{8}$|^\d{12,14}$")


def _normalize_ean(code: str) -> str:
    """UPC-A (12 digits) is EAN-13 with the leading zero dropped — zero-pad it back so it
    compares directly against Philibert's 13-digit EAN field. EAN-8/13/14 pass through as-is."""
    return code.zfill(13) if len(code) == 12 else code


@dataclass
class ZatuVariant:
    variant_id: int
    title: str
    sku: str | None
    barcode: str | None
    price_gbp: float | None
    compare_at_price_gbp: float | None
    available: bool
    inventory_quantity: int | None


@dataclass
class ZatuProduct:
    zatu_id: int
    handle: str
    title: str
    url: str
    product_type: str | None
    vendor: str | None
    tags: list[str] = field(default_factory=list)
    variants: list[ZatuVariant] = field(default_factory=list)

    @property
    def in_stock(self) -> bool:
        return any(v.available for v in self.variants)

    @property
    def min_price_gbp(self) -> float | None:
        prices = [v.price_gbp for v in self.variants if v.price_gbp is not None]
        return min(prices) if prices else None

    @property
    def ean(self) -> str | None:
        """First variant barcode that looks like a real EAN/UPC/GTIN — the strongest
        available key for matching this product on BGG/Philibert (spec §0.2, §4.2).
        Normalised to EAN-13 (UPC-A is zero-padded) so it compares directly against
        Philibert's 13-digit EAN field."""
        for v in self.variants:
            if v.barcode and _EAN_RE.match(v.barcode.strip()):
                return _normalize_ean(v.barcode.strip())
        return None

    @property
    def is_coop(self) -> bool:
        return any("cooperat" in t.lower() for t in self.tags)

    @property
    def is_party(self) -> bool:
        return any("party" in t.lower() for t in self.tags)

    def to_dict(self) -> dict:
        """dataclasses.asdict() only serializes fields, not @property methods — use this
        instead so `ean`/`in_stock`/`min_price_gbp` actually make it into saved output."""
        return {
            **dataclasses.asdict(self),
            "ean": self.ean,
            "in_stock": self.in_stock,
            "min_price_gbp": self.min_price_gbp,
            "is_coop": self.is_coop,
            "is_party": self.is_party,
        }


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


def _to_float(value) -> float | None:
    return float(value) if value not in (None, "") else None


def _parse_tags(raw_tags) -> list[str]:
    if isinstance(raw_tags, list):
        return raw_tags
    if isinstance(raw_tags, str):
        return [t.strip() for t in raw_tags.split(",") if t.strip()]
    return []


def _parse_variant(raw: dict) -> ZatuVariant:
    return ZatuVariant(
        variant_id=raw["id"],
        title=raw.get("title", ""),
        sku=raw.get("sku") or None,
        barcode=raw.get("barcode") or None,
        price_gbp=_to_float(raw.get("price")),
        compare_at_price_gbp=_to_float(raw.get("compare_at_price")),
        available=bool(raw.get("available", False)),
        inventory_quantity=raw.get("inventory_quantity"),
    )


def parse_product(raw: dict) -> ZatuProduct:
    handle = raw["handle"]
    return ZatuProduct(
        zatu_id=raw["id"],
        handle=handle,
        title=raw["title"],
        url=f"{BASE_URL}/products/{handle}",
        product_type=raw.get("product_type") or None,
        vendor=raw.get("vendor") or None,
        tags=_parse_tags(raw.get("tags")),
        variants=[_parse_variant(v) for v in raw.get("variants", [])],
    )


def fetch_products_page(session: requests.Session, page: int) -> list[dict]:
    url = f"{BASE_URL}/collections/{COLLECTION_HANDLE}/products.json"
    resp = session.get(url, params={"limit": PAGE_LIMIT, "page": page}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("products", [])


def fetch_product_detail(session: requests.Session, handle: str) -> dict:
    """Per-product JSON (`/products/<handle>.json`, singular `product` key — standard Shopify
    shape). One request per game — a Stage 4 tool for the survivors of Stage 2's match, not
    something to run across the whole catalogue (spec's cheap-wide/expensive-narrow rule).

    Confirmed live 2026-08-10 via `scripts/probe_zatu_detail.py`: unlike the bulk
    `/collections/.../products.json` (which returns `barcode: null` on all 4178 harvested
    products, docs/spec.md §11.1), this endpoint has a real, populated `barcode` — e.g. Brass:
    Birmingham came back `9781988884042` here vs `null` in the bulk harvest for the same product.
    Also carries `price_currency`, which `verify_gbp_currency` uses (confirmed `"GBP"` on all
    three sampled products).
    """
    url = f"{BASE_URL}/products/{handle}.json"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json().get("product", {})


def fetch_product_ean(session: requests.Session, handle: str) -> str | None:
    """Per-product EAN lookup for Stage 4 — confirmed populated (see `fetch_product_detail`)
    where the bulk collection endpoint returns null for the same products."""
    product = fetch_product_detail(session, handle)
    for v in product.get("variants", []):
        barcode = v.get("barcode")
        if barcode and _EAN_RE.match(str(barcode).strip()):
            return _normalize_ean(str(barcode).strip())
    return None


# Stock-status phrases confirmed in Zatu's rendered product-page UI (spec §11.1). The bulk and
# per-product JSON carry no `available`/`inventory_quantity` signal worth trusting (confirmed —
# `available` was `true` for all 4178 harvested products with no inventory number behind it), so
# real stock has to come from this text.
_STOCK_TEXT_PATTERNS = [
    (re.compile(r"\bout of stock\b", re.I), "OUT_OF_STOCK"),
    (re.compile(r"\bback-?order\b", re.I), "BACK_ORDER"),
    (re.compile(r"\border in next\b", re.I), "PREORDER"),
    (re.compile(r"\d+\+?\s*in stock\b", re.I), "IN_STOCK"),
]


def fetch_stock_status(session: requests.Session, handle: str) -> str:
    """Best-effort stock status scraped from the rendered product page text. Returns one of
    OUT_OF_STOCK / BACK_ORDER / PREORDER / IN_STOCK / UNKNOWN. The exact out-of-stock wording
    was never confirmed live (spec §11.3 flags this as the one still-open string) — treat
    UNKNOWN as "couldn't tell", not "definitely in stock"."""
    url = f"{BASE_URL}/products/{handle}"
    resp = session.get(url, headers={"Accept": "text/html"}, timeout=30)
    resp.raise_for_status()
    text = BeautifulSoup(resp.text, "lxml").get_text(" ", strip=True)
    for pattern, status in _STOCK_TEXT_PATTERNS:
        if pattern.search(text):
            return status
    return "UNKNOWN"


def harvest_all(
    session: requests.Session | None = None,
    rate_limit_sec: float = 1.0,
    max_pages: int = 40,
) -> list[ZatuProduct]:
    """Page through the curated board-games collection until an empty page (spec Stage 0)."""
    session = session or make_session()
    products: list[ZatuProduct] = []
    for page in range(1, max_pages + 1):
        raw_page = fetch_products_page(session, page)
        if not raw_page:
            break
        products.extend(parse_product(p) for p in raw_page)
        time.sleep(rate_limit_sec)
    return products


def _currency_from_product_json(session: requests.Session, sample_handle: str) -> str | None:
    """Try the per-product JSON's `price_currency` field — confirmed present and `"GBP"` on all
    three products sampled by `scripts/probe_zatu_detail.py` on 2026-08-10. Still falls back to
    the meta-tag check on a missing/failed response rather than assuming GBP, in case that
    changes on Zatu's end."""
    try:
        product = fetch_product_detail(session, sample_handle)
    except (requests.RequestException, ValueError):
        return None
    for v in product.get("variants", []):
        currency = v.get("price_currency")
        if currency:
            return currency
    return None


def _currency_from_meta_tag(session: requests.Session, sample_handle: str) -> str | None:
    url = f"{BASE_URL}/products/{sample_handle}"
    resp = session.get(url, headers={"Accept": "text/html"}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    tag = soup.find("meta", attrs={"property": "og:price:currency"})
    return tag.get("content") if tag else None


def verify_gbp_currency(
    session: requests.Session | None = None, sample_handle: str = "manipulate"
) -> bool:
    """Check one product's currency is GBP before trusting any harvested price.

    A locale-prefixed URL was confirmed to return USD (spec §11.1); the bare path returns GBP
    directly (module docstring). Call this once per harvest — a silent currency regression must
    fail loudly, not corrupt every discount computation downstream (spec §5.2, §8).

    Tries the per-product JSON's `price_currency` field first (cheaper, no HTML parsing); falls
    back to the `og:price:currency` meta tag, which is the proven method — confirmed GBP against
    the live site on the first successful harvest.
    """
    session = session or make_session()
    currency = _currency_from_product_json(session, sample_handle)
    if currency is None:
        currency = _currency_from_meta_tag(session, sample_handle)
    return currency == "GBP"
