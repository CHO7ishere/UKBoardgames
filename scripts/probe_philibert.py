#!/usr/bin/env python3
"""One-off diagnostic: probe Philibert's real site behavior before building Stage 5 for real.

Spec (docs/spec.md §0.3/§11.3) only confirmed ONE direct product-page fetch live — the search
endpoint was never tested, and the exact "out of stock" wording for a primary product was never
observed. Not part of the production pipeline; run manually via the probe-philibert workflow,
read the job log.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

BASE_URL = "https://www.philibertnet.com"
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"

# Known-real product from spec §11.3, captured live in the original investigation.
KNOWN_PRODUCT_URL = f"{BASE_URL}/fr/iello/171597-athletes-de-compete-3701551706461.html"
KNOWN_PRODUCT_EAN = "3701551706461"

# Candidate search URL patterns (PrestaShop's default search controller has taken several
# forms across versions/themes) — try each, report which returns plausible product results.
SEARCH_CANDIDATES = [
    "{base}/recherche?controller=search&s={q}",
    "{base}/recherche?s={q}",
    "{base}/index.php?controller=search&s={q}",
    "{base}/catalogsearch/result/?q={q}",
    "{base}/search?q={q}",
]

# A widely-stocked, evergreen title (unlikely to ever be genuinely unavailable) — used to sanity
# check that whichever search pattern works returns real product links, not an empty/error page.
SEARCH_QUERY = "Catan"

# Titles chosen to have a decent chance of being out of stock/discontinued on a French retailer,
# to help pin down the real out-of-stock wording (spec's one sample only showed a pre-order).
STOCK_PROBE_QUERIES = ["Zombicide", "7 Wonders"]


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def probe_known_product(session: requests.Session) -> None:
    print("\n=== Known product page (spec §11.3 recapture) ===", file=sys.stderr)
    resp = session.get(KNOWN_PRODUCT_URL, timeout=30)
    print(f"status={resp.status_code}", file=sys.stderr)
    if resp.status_code != 200:
        print("Could not refetch the known product — spec's URL may have changed.", file=sys.stderr)
        return
    soup = BeautifulSoup(resp.text, "lxml")
    text = soup.get_text("\n", strip=True)
    # Print the neighbourhood of "Fiche technique" so we can see the real markup/labels.
    idx = text.find("Fiche technique")
    print("Fiche technique context:", file=sys.stderr)
    print(text[idx : idx + 400] if idx >= 0 else "NOT FOUND", file=sys.stderr)
    print(f"\nEAN {KNOWN_PRODUCT_EAN} present in page text: {KNOWN_PRODUCT_EAN in text}", file=sys.stderr)
    # Look for likely stock-status / add-to-cart markers.
    for marker in ["Ajouter au panier", "Précommande", "Précommander", "Rupture", "rupture",
                   "indisponible", "Indisponible", "épuisé", "Épuisé"]:
        print(f'contains {marker!r}: {marker in text}', file=sys.stderr)


def probe_search(session: requests.Session) -> str | None:
    print("\n=== Search endpoint candidates ===", file=sys.stderr)
    working = None
    for pattern in SEARCH_CANDIDATES:
        url = pattern.format(base=BASE_URL, q=SEARCH_QUERY)
        try:
            resp = session.get(url, timeout=30, allow_redirects=True)
        except requests.RequestException as exc:
            print(f"{pattern} -> ERROR {exc}", file=sys.stderr)
            continue
        soup = BeautifulSoup(resp.text, "lxml")
        product_links = soup.select('a[href*=".html"]')
        print(
            f"{pattern} -> status={resp.status_code} final_url={resp.url} "
            f"product_link_count={len(product_links)}",
            file=sys.stderr,
        )
        if resp.status_code == 200 and len(product_links) > 3 and working is None:
            working = url
            print(f"  sample links: {[a.get('href') for a in product_links[:5]]}", file=sys.stderr)
    return working


def probe_stock_wording(session: requests.Session) -> None:
    print("\n=== Hunting for a real out-of-stock product ===", file=sys.stderr)
    for query in STOCK_PROBE_QUERIES:
        for pattern in SEARCH_CANDIDATES[:2]:  # only try the top candidates to limit requests
            url = pattern.format(base=BASE_URL, q=query)
            try:
                resp = session.get(url, timeout=30)
            except requests.RequestException:
                continue
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            links = [a.get("href") for a in soup.select('a[href*=".html"]')][:3]
            for href in links:
                if not href:
                    continue
                product_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                try:
                    presp = session.get(product_url, timeout=30)
                except requests.RequestException:
                    continue
                ptext = BeautifulSoup(presp.text, "lxml").get_text(" ", strip=True)
                for marker in ["Rupture", "rupture", "indisponible", "Indisponible", "épuisé", "Épuisé"]:
                    if marker in ptext:
                        print(f"FOUND marker {marker!r} on {product_url}", file=sys.stderr)
                        idx = ptext.find(marker)
                        print(f"  context: ...{ptext[max(0,idx-60):idx+60]}...", file=sys.stderr)


def main() -> int:
    session = make_session()
    probe_known_product(session)
    working_search = probe_search(session)
    if working_search:
        probe_stock_wording(session)
    else:
        print("\nNo search pattern returned usable results — Stage 5 will need EAN-in-URL or "
              "another discovery path.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
