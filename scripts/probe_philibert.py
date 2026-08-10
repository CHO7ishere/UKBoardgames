#!/usr/bin/env python3
"""One-off diagnostic: probe Philibert's real site behavior before building Stage 5 for real.

Spec (docs/spec.md §0.3/§11.3) only confirmed ONE direct product-page fetch live — the search
endpoint was never tested, and the exact "out of stock" wording for a primary product was never
observed. Round 1 (guessed search URL patterns) all 404/500'd — this round discovers the real
search form directly from the homepage HTML instead of guessing further. Not part of the
production pipeline; run manually via the probe-philibert workflow, read the job log.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

BASE_URL = "https://www.philibertnet.com"
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"

KNOWN_PRODUCT_URL = f"{BASE_URL}/fr/iello/171597-athletes-de-compete-3701551706461.html"
KNOWN_PRODUCT_EAN = "3701551706461"
SEARCH_QUERY = "Catan"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def probe_known_product_structure(session: requests.Session) -> None:
    print("\n=== Known product page: real DOM structure around EAN/stock ===", file=sys.stderr)
    resp = session.get(KNOWN_PRODUCT_URL, timeout=30)
    print(f"status={resp.status_code}", file=sys.stderr)
    if resp.status_code != 200:
        return
    soup = BeautifulSoup(resp.text, "lxml")

    # Find whichever element's own text contains "EAN" and print its tag chain, so a real
    # parser can target it structurally instead of via a fragile text-offset guess.
    ean_label = soup.find(string=lambda s: s and s.strip() == "EAN")
    if ean_label:
        parent = ean_label.parent
        print(f"EAN label tag: <{parent.name} class={parent.get('class')}>", file=sys.stderr)
        container = parent.parent
        print(f"EAN container tag: <{container.name} class={container.get('class')}>", file=sys.stderr)
        print(f"EAN container text: {container.get_text(' | ', strip=True)[:300]}", file=sys.stderr)
    else:
        print("No standalone 'EAN' text node found — trying substring search.", file=sys.stderr)
        for tag in soup.find_all(string=lambda s: s and "EAN" in s):
            print(f"  substring hit in <{tag.parent.name}>: {tag.strip()[:100]!r}", file=sys.stderr)

    langue_label = soup.find(string=lambda s: s and "Langue" in s)
    if langue_label:
        print(f"Langue(s) context: {langue_label.parent.get_text(' | ', strip=True)[:200]}", file=sys.stderr)

    # All occurrences of "Indisponible" with surrounding context, to tell a real stock signal
    # from leaked cross-sell-widget template text (spec §0.3 already flags this risk class).
    full_text = soup.get_text(" ", strip=True)
    start = 0
    hits = 0
    while True:
        idx = full_text.find("Indisponible", start)
        if idx == -1 or hits >= 5:
            break
        print(f"'Indisponible' context: ...{full_text[max(0,idx-80):idx+80]}...", file=sys.stderr)
        start = idx + 1
        hits += 1

    price_tag = soup.find(string=lambda s: s and "€" in s)
    print(f"first '€' text node: {price_tag.strip() if price_tag else None!r}", file=sys.stderr)


def discover_search_form(session: requests.Session) -> tuple[str, str, dict] | None:
    """Fetch the homepage and find the real search form: action URL, method, and param names
    (including hidden fields) — more reliable than guessing PrestaShop's route conventions."""
    print("\n=== Discovering the real search form from the homepage ===", file=sys.stderr)
    resp = session.get(f"{BASE_URL}/", timeout=30)
    print(f"homepage status={resp.status_code}", file=sys.stderr)
    if resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "lxml")

    candidates = []
    for form in soup.find_all("form"):
        inputs = form.find_all("input")
        search_input = None
        for inp in inputs:
            name = (inp.get("name") or "").lower()
            itype = (inp.get("type") or "").lower()
            if "search" in name or itype == "search":
                search_input = inp
                break
        if search_input:
            candidates.append((form, search_input))

    if not candidates:
        print("No <form> with a search-like <input> found on the homepage.", file=sys.stderr)
        return None

    form, search_input = candidates[0]
    action = form.get("action") or f"{BASE_URL}/"
    action = urljoin(f"{BASE_URL}/", action)
    method = (form.get("method") or "get").lower()
    params = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        params[name] = inp.get("value", "")
    search_field_name = search_input.get("name")
    print(f"form action={action} method={method} fields={list(params.keys())}", file=sys.stderr)
    print(f"search field name={search_field_name!r}", file=sys.stderr)
    return action, search_field_name, params


def probe_search_with_discovered_form(
    session: requests.Session, action: str, field_name: str, base_params: dict
) -> list[str]:
    print("\n=== Trying discovered search form with a real query ===", file=sys.stderr)
    params = dict(base_params)
    params[field_name] = SEARCH_QUERY
    resp = session.get(action, params=params, timeout=30)
    print(f"GET {resp.url} -> status={resp.status_code}", file=sys.stderr)
    if resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "lxml")
    product_links = [a.get("href") for a in soup.select('a[href*=".html"]') if a.get("href")]
    unique_links = list(dict.fromkeys(product_links))
    print(f"product_link_count={len(unique_links)}", file=sys.stderr)
    print(f"sample: {unique_links[:8]}", file=sys.stderr)
    return unique_links


def main() -> int:
    session = make_session()
    probe_known_product_structure(session)
    form_info = discover_search_form(session)
    if form_info:
        action, field_name, params = form_info
        if field_name:
            probe_search_with_discovered_form(session, action, field_name, params)
        else:
            print("Found a form but couldn't identify the search field name.", file=sys.stderr)
    else:
        print("\nCould not discover a search form — Stage 5 may need a different discovery "
              "path (category browsing, sitemap, or an external aggregator).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
