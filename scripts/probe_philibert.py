#!/usr/bin/env python3
"""One-off diagnostic: probe Philibert's real site behavior before building Stage 5 for real.

Round 6. The user supplied a real, working search URL from their own browser:
https://www.philibertnet.com/fr/recherche?search_query=spirit%20island — the param is
`search_query`, not `s` (round 4's guess). Confirms this before Stage 5 is built against it, and
checks the result markup structure (how to reliably find product links + how a no-results page
looks, to distinguish NOT_LISTED from a parsing failure). Not part of the production pipeline;
run manually via the probe-philibert workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

BASE_URL = "https://www.philibertnet.com"
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"

KNOWN_PRODUCT_EAN = "3701551706461"
KNOWN_PRODUCT_TITLE = "Athlètes de Compète"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def search(session: requests.Session, query: str, label: str) -> None:
    url = f"{BASE_URL}/fr/recherche"
    resp = session.get(url, params={"search_query": query}, timeout=30)
    print(f"\n=== [{label}] search_query={query!r} ===", file=sys.stderr)
    print(f"GET {resp.url} -> status={resp.status_code}", file=sys.stderr)
    soup = BeautifulSoup(resp.text, "lxml")

    # Try to find a dedicated product-listing container first (more reliable than "any .html
    # link on the page", which also catches header/footer/nav links).
    product_containers = soup.select(
        '[class*="product" i][class*="miniature" i], article[class*="product" i], '
        '[class*="js-product" i], [data-id-product]'
    )
    print(f"product-ish container count: {len(product_containers)}", file=sys.stderr)

    all_links = [a.get("href") for a in soup.select('a[href*=".html"]') if a.get("href")]
    unique_links = list(dict.fromkeys(all_links))
    print(f"total .html link count: {len(unique_links)}", file=sys.stderr)
    print(f"sample: {unique_links[:8]}", file=sys.stderr)

    # "no results" phrasing, if any.
    text = soup.get_text(" ", strip=True)
    for phrase in ["Aucun résultat", "aucun résultat", "0 résultat", "Aucun produit"]:
        if phrase in text:
            print(f"no-results phrase found: {phrase!r}", file=sys.stderr)


def main() -> int:
    session = make_session()
    search(session, "spirit island", "user-confirmed example")
    search(session, KNOWN_PRODUCT_EAN, "known product's real EAN")
    search(session, KNOWN_PRODUCT_TITLE, "known product's real title")
    search(session, "zzz_definitely_not_a_real_game_zzz", "expected no-results case")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
