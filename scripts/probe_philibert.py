#!/usr/bin/env python3
"""One-off diagnostic: probe Philibert's real site behavior before building Stage 5 for real.

Round 5. Round 4 confirmed /fr/recherche?s=<query> just redirects to the homepage regardless of
query (all three different queries returned the exact same 26 links, and the final response URL
was /fr/ — search genuinely isn't reachable this way, likely JS/AJAX-driven, possibly a
third-party widget). Pivoting strategy: check whether bulk category-page browsing (mirroring
Stage 0's approach, since Philibert has no JSON API) is viable size-wise — total product count
and real pagination mechanism for the confirmed-working /fr/50-jeux-de-societe category page.
Not part of the production pipeline; run manually via the probe-philibert workflow.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

BASE_URL = "https://www.philibertnet.com"
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"
CATEGORY_URL = f"{BASE_URL}/fr/50-jeux-de-societe"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def probe_category_total_count(session: requests.Session) -> None:
    print("=== Category page: hunting for a total-product-count indicator ===", file=sys.stderr)
    resp = session.get(CATEGORY_URL, timeout=30)
    print(f"status={resp.status_code}", file=sys.stderr)
    text = resp.text
    # Common PrestaShop phrasing: "NNN produits", "NNN résultats", data-total attributes, etc.
    for pattern in [r"[\d\s]{1,7}\s*produits?", r"[\d\s]{1,7}\s*résultats?", r'"total"\s*:\s*"?\d+']:
        hits = re.findall(pattern, text, re.IGNORECASE)
        if hits:
            print(f"  pattern {pattern!r} hits: {hits[:5]}", file=sys.stderr)

    soup = BeautifulSoup(text, "lxml")
    for sel in ['[class*="count" i]', '[class*="total" i]', '[class*="result" i]']:
        for el in soup.select(sel)[:5]:
            t = el.get_text(strip=True)
            if t and any(c.isdigit() for c in t):
                print(f"  {sel} -> {t!r}", file=sys.stderr)


def probe_pagination(session: requests.Session) -> None:
    print("\n=== Category page: pagination mechanism ===", file=sys.stderr)
    for variant in [
        f"{CATEGORY_URL}?page=2",
        f"{CATEGORY_URL}?p=2",
        f"{CATEGORY_URL}#/page-2",
        f"{CATEGORY_URL}?page=1&n=100",
    ]:
        resp = session.get(variant, timeout=30)
        soup = BeautifulSoup(resp.text, "lxml")
        links = list(dict.fromkeys(a.get("href") for a in soup.select('a[href*=".html"]') if a.get("href")))
        print(f"{variant} -> status={resp.status_code} final={resp.url} link_count={len(links)}",
              file=sys.stderr)

    # page=1 vs page=2: are the product sets actually different, confirming real pagination?
    r1 = session.get(f"{CATEGORY_URL}?page=1", timeout=30)
    r2 = session.get(f"{CATEGORY_URL}?page=2", timeout=30)
    links1 = set(a.get("href") for a in BeautifulSoup(r1.text, "lxml").select('a[href*=".html"]'))
    links2 = set(a.get("href") for a in BeautifulSoup(r2.text, "lxml").select('a[href*=".html"]'))
    overlap = links1 & links2
    print(f"\npage=1 links: {len(links1)}, page=2 links: {len(links2)}, overlap: {len(overlap)}",
          file=sys.stderr)


def probe_ean_in_url_direct_guess(session: requests.Session) -> None:
    """If we already know a product's EAN and rough slug (from Zatu's title), can we skip
    discovery entirely and construct the URL? Almost certainly not (internal id + full slug are
    unknown), but confirm the failure mode is a clean 404, not something misleading."""
    print("\n=== Sanity: a guessed (wrong) product URL ===", file=sys.stderr)
    resp = session.get(f"{BASE_URL}/fr/some-publisher/1-fake-slug-1234567890123.html", timeout=30)
    print(f"status={resp.status_code}", file=sys.stderr)


def main() -> int:
    session = make_session()
    probe_category_total_count(session)
    probe_pagination(session)
    probe_ean_in_url_direct_guess(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
