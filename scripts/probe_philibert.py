#!/usr/bin/env python3
"""One-off diagnostic: probe Philibert's real site behavior before building Stage 5 for real.

Round 3. Round 1 (guessed search URLs) all 404/500'd. Round 2 (discover the search <form> from
the homepage) found no form matching a "name/type contains 'search'" heuristic — the header
search may be JS-driven. This round dumps every homepage form unconditionally (so a human/LLM
can pick the right one by eye) and checks two alternative discovery paths: sitemap.xml (would
give a Zatu-Stage-0-style bulk URL list) and the known board-games category page (spec §0.3's
"/fr/50-jeux-de-societe" root), in case search genuinely isn't reachable without a browser.
Not part of the production pipeline; run manually via the probe-philibert workflow.
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


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def probe_known_product_features(session: requests.Session) -> None:
    print("\n=== Known product page: full product-features table ===", file=sys.stderr)
    resp = session.get(KNOWN_PRODUCT_URL, timeout=30)
    print(f"status={resp.status_code}", file=sys.stderr)
    if resp.status_code != 200:
        return
    soup = BeautifulSoup(resp.text, "lxml")
    items = soup.select("li.product-features__item")
    print(f"product-features__item count: {len(items)}", file=sys.stderr)
    for item in items:
        label = item.select_one(".product-features__name")
        label_text = label.get_text(strip=True) if label else None
        full_text = item.get_text(" | ", strip=True)
        print(f"  [{label_text}] -> {full_text}", file=sys.stderr)


def dump_all_homepage_forms(session: requests.Session) -> None:
    print("\n=== Every <form> on the homepage (unfiltered) ===", file=sys.stderr)
    resp = session.get(f"{BASE_URL}/", timeout=30)
    print(f"homepage status={resp.status_code}", file=sys.stderr)
    if resp.status_code != 200:
        return
    soup = BeautifulSoup(resp.text, "lxml")
    forms = soup.find_all("form")
    print(f"form count: {len(forms)}", file=sys.stderr)
    for i, form in enumerate(forms):
        action = form.get("action")
        method = form.get("method")
        inputs = [
            {"name": inp.get("name"), "type": inp.get("type"), "placeholder": inp.get("placeholder")}
            for inp in form.find_all("input")
        ]
        print(f"form[{i}] action={action!r} method={method!r} id={form.get('id')!r} "
              f"class={form.get('class')!r}", file=sys.stderr)
        print(f"  inputs: {inputs}", file=sys.stderr)

    # Also look for any element hinting at a search widget even outside a <form> (JS-driven
    # header search bars often keep a bare <input> the JS wires up on submit/keypress).
    search_inputs = soup.select('input[type="search"], input[placeholder*="ech" i], input[name*="search" i], input[name="s"]')
    print(f"\nstandalone search-like <input> candidates (any container): {len(search_inputs)}", file=sys.stderr)
    for inp in search_inputs[:5]:
        print(f"  {inp}", file=sys.stderr)


def probe_sitemap(session: requests.Session) -> None:
    print("\n=== sitemap.xml ===", file=sys.stderr)
    for path in ["/sitemap.xml", "/sitemap_index.xml", "/modules/prestashopsitemap/sitemap.xml"]:
        resp = session.get(f"{BASE_URL}{path}", timeout=30)
        print(f"{path} -> status={resp.status_code} content-type={resp.headers.get('Content-Type')} "
              f"len={len(resp.content)}", file=sys.stderr)
        if resp.status_code == 200 and len(resp.content) > 0:
            print(f"  first 500 chars: {resp.text[:500]}", file=sys.stderr)


def probe_category_page(session: requests.Session) -> None:
    print("\n=== Known category page (spec §0.3: /fr/50-jeux-de-societe) ===", file=sys.stderr)
    resp = session.get(f"{BASE_URL}/fr/50-jeux-de-societe", timeout=30)
    print(f"status={resp.status_code} final_url={resp.url}", file=sys.stderr)
    if resp.status_code != 200:
        return
    soup = BeautifulSoup(resp.text, "lxml")
    product_links = [a.get("href") for a in soup.select('a[href*=".html"]') if a.get("href")]
    unique_links = list(dict.fromkeys(product_links))
    print(f"product_link_count={len(unique_links)}", file=sys.stderr)
    print(f"sample: {unique_links[:8]}", file=sys.stderr)
    # look for pagination hints
    pagination = soup.select('[class*="pagination" i] a')
    print(f"pagination link count: {len(pagination)}", file=sys.stderr)
    print(f"pagination hrefs: {[a.get('href') for a in pagination[:10]]}", file=sys.stderr)


def main() -> int:
    session = make_session()
    probe_known_product_features(session)
    dump_all_homepage_forms(session)
    probe_sitemap(session)
    probe_category_page(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
