"""Philibert lookup — Stage 5 (docs/spec.md §3 Stage 5, §0.3, §11.3). PrestaShop, no bulk export
or JSON API — search is the only viable discovery path. A bulk category-page browse (mirroring
Zatu's Stage 0) was tried and ruled out empirically: the board-games category alone has 12,812
products, and its pagination doesn't respond to any guessed query param — likely JS-driven, like
the header search widget itself.

Search endpoint confirmed live via scripts/probe_philibert.py (7 rounds, 2026-08-10):
`GET /fr/recherche?search_query=<query>` — not the guessed `/recherche?s=<query>` from earlier
rounds, and not reachable without the `/fr/` locale prefix every real route on this site uses
(confirmed by a user-supplied working browser URL after rounds 1-5 guessed wrong). EAN search is
precise: a real EAN returns exactly one product link, a garbage EAN-shaped query returns zero.
A garbage TEXT query does NOT reliably return zero, though — Philibert's search falls back to
unrelated "you might like" results rather than a clean empty page, so title-based lookups must
fuzzy-filter results themselves (reusing match.py's normalize_title), not just check "were there
any links".
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from match import normalize_title

BASE_URL = "https://www.philibertnet.com"
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"

_TRAILING_EAN_RE = re.compile(r"-\d{8,14}$")
_LEADING_ID_RE = re.compile(r"^\d+-")

# Confirmed live (spec §11.3, reconfirmed via probe): the primary product's own purchase state.
# "Précommande"/"Précommander" is purchasable (a real order, just delayed shipping) so it's
# treated as available, same spirit as Zatu's own preorder handling (spec §11.1).
_IN_STOCK_RE = re.compile(r"ajouter au panier|pr[ée]command", re.IGNORECASE)
_OUT_OF_STOCK_RE = re.compile(r"rupture de stock|indisponible|[ée]puis[ée]", re.IGNORECASE)

# [VERIFY] No dedicated stock/availability container was confirmed live — only the
# product-features table was. These are best-effort guesses at PrestaShop's usual structure;
# unscoped full-page text search is deliberately NOT used as a fallback, since "Indisponible"
# was confirmed to leak from unrelated cross-sell widgets elsewhere on the very same page
# (spec §0.3's own warning, reconfirmed live). Better to report UNKNOWN than risk a confidently
# wrong answer from a coincidental cross-sell match.
_STOCK_CONTAINER_SELECTORS = [
    "#product-availability",
    ".product-availability",
    ".product-actions",
    ".product-add-to-cart",
    "[data-product-availability]",
]


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _absolute(url: str) -> str:
    return url if url.startswith("http") else f"{BASE_URL}{url}"


def _search_links(session: requests.Session, query: str) -> list[str]:
    resp = session.get(f"{BASE_URL}/fr/recherche", params={"search_query": query}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    links = [a.get("href") for a in soup.select('a[href*=".html"]') if a.get("href")]
    return list(dict.fromkeys(links))  # de-dup, preserve order


def search_by_ean(session: requests.Session, ean: str) -> str | None:
    """Confirmed empirically: a real EAN returns exactly one product link; a garbage
    EAN-shaped query returns zero. Multiple links for a real EAN is unexpected — conservatively
    require the EAN to actually appear in exactly one result URL rather than guess."""
    links = _search_links(session, ean)
    matching = [link for link in links if ean in link]
    if len(matching) == 1:
        return _absolute(matching[0])
    return None


def _slug_to_title(url: str) -> str:
    slug = re.sub(r"\.html$", "", url).rsplit("/", 1)[-1]
    slug = _TRAILING_EAN_RE.sub("", slug)
    slug = _LEADING_ID_RE.sub("", slug)
    return slug.replace("-", " ")


def search_by_title(
    session: requests.Session, title: str, fuzzy_threshold: float = 85.0
) -> str | None:
    """Title search's results aren't reliably filtered by Philibert itself (spec: a garbage
    query can still return unrelated "you might like" links), so candidates are fuzzy-filtered
    by title similarity extracted from the URL slug before one is accepted."""
    links = _search_links(session, title)
    if not links:
        return None
    norm_query = normalize_title(title)
    best_link, best_score = None, 0.0
    for link in links:
        score = fuzz.token_sort_ratio(norm_query, normalize_title(_slug_to_title(link)))
        if score > best_score:
            best_link, best_score = link, score
    if best_link and best_score >= fuzzy_threshold:
        return _absolute(best_link)
    return None


def _extract_features(soup: BeautifulSoup) -> dict[str, str]:
    features: dict[str, str] = {}
    for item in soup.select("li.product-features__item"):
        label_el = item.select_one(".product-features__name")
        if not label_el:
            continue
        label = label_el.get_text(strip=True)
        full_text = item.get_text(" ", strip=True)
        value = full_text.replace(label, "", 1).strip(" :|-")
        features.setdefault(label, value)  # first occurrence wins (page had duplicate tables)
    return features


def _extract_price_eur(soup: BeautifulSoup) -> float | None:
    price_node = soup.find(string=lambda s: s and "€" in s)
    if not price_node:
        return None
    match = re.search(r"([\d]+[.,]\d{2})\s*€", price_node)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _classify_stock(soup: BeautifulSoup) -> str:
    container = None
    for selector in _STOCK_CONTAINER_SELECTORS:
        container = soup.select_one(selector)
        if container:
            break
    if container is None:
        return "UNKNOWN"
    text = container.get_text(" ", strip=True)
    if _IN_STOCK_RE.search(text):
        return "IN_STOCK"
    if _OUT_OF_STOCK_RE.search(text):
        return "OUT_OF_STOCK"
    return "UNKNOWN"


def fetch_product_page(session: requests.Session, url: str) -> dict:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    features = _extract_features(soup)
    return {
        "ean": features.get("EAN"),
        "language": features.get("Langue(s)"),
        "publisher": features.get("Editeur"),
        "price_eur": _extract_price_eur(soup),
        "stock_status": _classify_stock(soup),
    }
