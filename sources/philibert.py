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
_CATEGORY_RE = re.compile(r"(?:https?://[^/]+)?/fr/([^/]+)/")

# Component/accessory SKUs (spare player boards, upgrade-token sets, expansion component sets)
# share a handful of generic French category slugs across many different games, confirmed live
# 2026-08-10 via a real Slay the Spire search: 4 accessory listings all normalized to
# "slay spire <something>", breaking the unique-prefix check below (5 candidates, not 1) even
# though the real base-game listing was Philibert's own top search result throughout. In every
# confirmed real sample so far the primary board-game listing's category slug is a publisher
# name (matagot, zman-games, next-move, days-of-wonder, the-op, intrafin, iello, ...); these
# generic component-taxonomy slugs are never used for a primary listing, so filtering them out
# can only help, never wrongly reject the real game.
_ACCESSORY_CATEGORY_SLUGS = frozenset({
    "pions",
    "pions-pour-jeux-specifiques",
    "plateau-de-jeu-individuel",
})


def _is_accessory_link(link: str) -> bool:
    match = _CATEGORY_RE.match(link)
    return bool(match) and match.group(1) in _ACCESSORY_CATEGORY_SLUGS

# Confirmed live (spec §11.3, reconfirmed via probe): the primary product's own purchase state.
# "Précommande"/"Précommander" is purchasable (a real order, just delayed shipping) so it's
# treated as available, same spirit as Zatu's own preorder handling (spec §11.1).
_IN_STOCK_RE = re.compile(r"ajouter au panier|pr[ée]command", re.IGNORECASE)
_OUT_OF_STOCK_RE = re.compile(r"rupture de stock|indisponible|[ée]puis[ée]", re.IGNORECASE)

# `.product-actions` confirmed live against 5 real product pages from the actual Stage 5 run
# (scripts/probe_philibert.py) — reliably contains the primary product's own "Ajouter au
# panier" text, not cross-sell noise. The other entries are untested fallbacks kept for
# resilience if the theme changes; unscoped full-page text search is deliberately NOT used,
# since "Indisponible" was confirmed to leak from unrelated cross-sell widgets elsewhere on the
# very same page (spec §0.3's own warning, reconfirmed live). Better to report UNKNOWN than risk
# a confidently wrong answer from a coincidental cross-sell match. Still open: a genuinely
# out-of-stock primary product was never observed live (the real Stage 5 run found 0 of 381
# listed products out of stock — plausible on its own, given Philibert's stock depth, but not
# yet confirmed against a real example).
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
    by title similarity extracted from the URL slug before one is accepted.

    Falls back to a unique-prefix match (same rationale as Stage 2's `BggIndex`) when fuzzy
    finds nothing — confirmed necessary by a real miss: Philibert listed "Slay the Spire" under
    its French subtitle ("...Le Jeu de Plateau"), which no fuzzy score could bridge no matter
    the threshold, but the English title is a clean prefix of it. Accessory/component SKUs are
    dropped before either tier runs — confirmed live the same game can have several (a spare
    player board, upgrade tokens, an expansion's component set) that also share the base title
    as a normalized prefix, which would otherwise make a genuinely unique game match look
    ambiguous.
    """
    links = _search_links(session, title)
    if not links:
        return None
    links = [link for link in links if not _is_accessory_link(link)]
    if not links:
        return None
    norm_query = normalize_title(title)
    candidates = [(link, normalize_title(_slug_to_title(link))) for link in links]

    best_link, best_score = None, 0.0
    for link, norm_candidate in candidates:
        score = fuzz.token_sort_ratio(norm_query, norm_candidate)
        if score > best_score:
            best_link, best_score = link, score
    if best_link and best_score >= fuzzy_threshold:
        return _absolute(best_link)

    prefix_links = list(
        dict.fromkeys(
            link for link, norm_candidate in candidates
            if norm_candidate.startswith(norm_query + " ")
        )
    )
    if len(prefix_links) == 1:
        return _absolute(prefix_links[0])

    return None


# Marketing/edition/expansion qualifiers that mark a specific SKU rather than the base-game
# family. User-confirmed real misses: Zatu sells "Everdell Complete Collection" and "Gloomhaven
# 2nd Edition" as distinct products from Philibert's plain "Everdell"/"Gloomhaven" listings, and
# "Cthulhu: Death May Die - Fear of the Unknown" (an expansion, separated by " - ") isn't listed
# even though the base "Cthulhu: Death May Die" is. `search_by_title` genuinely finds nothing
# for these -- not a fuzzy-threshold or prefix-tier problem, the exact SKU just isn't listed --
# so this is a deliberate widen-the-net fallback tried only once the exact title has already
# failed, not a matching-precision fix. A caller must treat a hit here as weaker evidence (the
# family exists in France, not necessarily this edition) rather than a confirmed exact match.
_EXPANSION_SUFFIX_RE = re.compile(r"\s+-\s+.+$")
_EDITION_SUFFIX_NOISE_RE = re.compile(
    r"\b(\d+(st|nd|rd|th)\s+edition|deluxe edition|collector'?s edition|complete collection|"
    r"anniversary edition|definitive edition|big box)\b",
    re.IGNORECASE,
)
_SUBTITLE_COLON_RE = re.compile(r"\s*:\s*")


def _base_title_candidates(title: str) -> list[str]:
    """Progressively broader fallback titles, most-specific first, deduplicated, never
    including the original title itself (callers already tried that)."""
    seen = {title.strip().lower()}
    candidates = []

    def _add(candidate: str) -> None:
        candidate = re.sub(r"\s+", " ", candidate).strip()
        key = candidate.lower()
        if candidate and key not in seen:
            seen.add(key)
            candidates.append(candidate)

    _add(_EXPANSION_SUFFIX_RE.sub("", title))
    _add(_EDITION_SUFFIX_NOISE_RE.sub("", title))
    # Last resort: just the part before the first colon (e.g. "Gloomhaven: Buttons & Bugs" ->
    # "Gloomhaven") -- broadest tier, tried last since it discards the most information.
    head = _SUBTITLE_COLON_RE.split(title, maxsplit=1)[0]
    _add(head)

    return candidates


def search_family_title(
    session: requests.Session, title: str, fuzzy_threshold: float = 85.0
) -> str | None:
    """Fallback for when `search_by_title(session, title)` already returned nothing: tries
    `_base_title_candidates(title)` in order (most-specific first) and returns the first hit.
    Reuses `search_by_title`'s own fuzzy/prefix matching and accessory-SKU filtering for each
    candidate, so a base-title hit still has to clear the same bar as a normal title search --
    only the search *query* is broadened, not the acceptance criteria."""
    for candidate in _base_title_candidates(title):
        url = search_by_title(session, candidate, fuzzy_threshold=fuzzy_threshold)
        if url:
            return url
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
