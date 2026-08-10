#!/usr/bin/env python3
"""One-off diagnostic: probe Philibert's real site behavior before building Stage 5 for real.

Round 4. Round 3 found the search <input> is JS-driven (no <form>) but carries
data-url="/fr/recherche" — and every confirmed-working route on this site (the known product
page, the category page) uses a "/fr/" locale prefix that rounds 1-2's guesses never included.
This round tests that endpoint directly, by title AND by the known product's real EAN, to
confirm it before Stage 5 is built against it. Not part of the production pipeline; run
manually via the probe-philibert workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

BASE_URL = "https://www.philibertnet.com"
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"

KNOWN_PRODUCT_URL = f"{BASE_URL}/fr/iello/171597-athletes-de-compete-3701551706461.html"
KNOWN_PRODUCT_EAN = "3701551706461"
KNOWN_PRODUCT_TITLE = "Athlètes de Compète"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def try_search(session: requests.Session, query: str, label: str) -> list[str]:
    url = f"{BASE_URL}/fr/recherche"
    resp = session.get(url, params={"s": query}, timeout=30)
    soup = BeautifulSoup(resp.text, "lxml")
    product_links = [a.get("href") for a in soup.select('a[href*=".html"]') if a.get("href")]
    unique_links = list(dict.fromkeys(product_links))
    print(
        f"[{label}] GET {resp.url} -> status={resp.status_code} "
        f"product_link_count={len(unique_links)}",
        file=sys.stderr,
    )
    if unique_links:
        print(f"  sample: {unique_links[:8]}", file=sys.stderr)
    return unique_links


def main() -> int:
    session = make_session()

    print("=== /fr/recherche?s=<EAN> (known product's real EAN) ===", file=sys.stderr)
    ean_links = try_search(session, KNOWN_PRODUCT_EAN, "EAN search")
    ean_found_known = any(KNOWN_PRODUCT_EAN in link for link in ean_links)
    print(f"known product URL's EAN present in a result link: {ean_found_known}", file=sys.stderr)

    print("\n=== /fr/recherche?s=<title> (known product's real title) ===", file=sys.stderr)
    title_links = try_search(session, KNOWN_PRODUCT_TITLE, "title search")

    print("\n=== /fr/recherche?s=Catan (generic sanity query) ===", file=sys.stderr)
    try_search(session, "Catan", "generic search")

    print("\n=== /fr/recherche with no query (baseline) ===", file=sys.stderr)
    resp = session.get(f"{BASE_URL}/fr/recherche", timeout=30)
    print(f"status={resp.status_code} len={len(resp.content)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
