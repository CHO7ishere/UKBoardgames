"""Zatu catalogue harvest — Stage 0 (docs/spec.md §3). Shopify's public, unauthenticated
storefront JSON: no auth needed, but currency is locale-dependent and known to default to USD
on an unforced request (spec §0.2/§11.1) even though Zatu is a UK retailer. Callers must run
`verify_gbp_currency` before trusting any harvested price.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://zatu.com"
LOCALE_PREFIX = "/en-gb"
COLLECTION_HANDLE = "top-5000-board-games"
PAGE_LIMIT = 250
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"

# EAN-8, UPC-A (12), EAN-13, GTIN-14 — Zatu's `barcode` field, when populated, is one of these.
_EAN_RE = re.compile(r"^\d{8}$|^\d{12,14}$")


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
        available key for matching this product on BGG/Philibert (spec §0.2, §4.2)."""
        for v in self.variants:
            if v.barcode and _EAN_RE.match(v.barcode.strip()):
                return v.barcode.strip()
        return None


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
        url=f"{BASE_URL}{LOCALE_PREFIX}/products/{handle}",
        product_type=raw.get("product_type") or None,
        vendor=raw.get("vendor") or None,
        tags=_parse_tags(raw.get("tags")),
        variants=[_parse_variant(v) for v in raw.get("variants", [])],
    )


def fetch_products_page(session: requests.Session, page: int) -> list[dict]:
    url = f"{BASE_URL}{LOCALE_PREFIX}/collections/{COLLECTION_HANDLE}/products.json"
    resp = session.get(url, params={"limit": PAGE_LIMIT, "page": page}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("products", [])


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


def verify_gbp_currency(
    session: requests.Session | None = None, sample_handle: str = "manipulate"
) -> bool:
    """Fetch one product page and check its `og:price:currency` meta tag is GBP.

    Confirmed live (spec §11.1): an unforced request to this same site returned USD in that
    metadata despite Zatu being a UK retailer. Call this once per harvest before trusting any
    price — a silent locale failure must fail loudly, not corrupt every discount computation
    downstream (spec §5.2, §8).
    """
    session = session or make_session()
    url = f"{BASE_URL}{LOCALE_PREFIX}/products/{sample_handle}"
    resp = session.get(url, headers={"Accept": "text/html"}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    tag = soup.find("meta", attrs={"property": "og:price:currency"})
    currency = tag.get("content") if tag else None
    return currency == "GBP"
