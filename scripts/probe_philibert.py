#!/usr/bin/env python3
"""One-off diagnostic: probe Philibert's real site behavior before building Stage 5 for real.

Round 7 (final confirmation). Round 6 confirmed /fr/recherche?search_query=<q> is real and
works: EAN search for a real EAN returned exactly 1 correct link; a garbage TEXT query returned
46 unrelated links (query-relaxation fallback, not a clean "no results"), so link-count alone
can't signal NOT_LISTED. This round checks whether a garbage EAN-SHAPED query (13 digits, not a
real EAN) behaves the same way or cleanly returns nothing — needed to design a reliable
NOT_LISTED check for Stage 5. Not part of the production pipeline; run via the probe-philibert
workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

BASE_URL = "https://www.philibertnet.com"
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def search(session: requests.Session, query: str, label: str) -> None:
    url = f"{BASE_URL}/fr/recherche"
    resp = session.get(url, params={"search_query": query}, timeout=30)
    soup = BeautifulSoup(resp.text, "lxml")
    links = list(dict.fromkeys(a.get("href") for a in soup.select('a[href*=".html"]') if a.get("href")))
    text = soup.get_text(" ", strip=True)
    no_results_hit = None
    for phrase in ["Aucun résultat", "aucun résultat", "0 résultat", "Aucun produit",
                   "ne correspond", "n'a donné aucun résultat"]:
        if phrase in text:
            no_results_hit = phrase
            break
    print(f"=== [{label}] search_query={query!r} ===", file=sys.stderr)
    print(f"status={resp.status_code} link_count={len(links)} no_results_phrase={no_results_hit!r}",
          file=sys.stderr)
    if links:
        print(f"  sample: {links[:5]}", file=sys.stderr)
    # Print a chunk of text near any "résultat" mention for exact wording.
    idx = text.lower().find("résultat")
    if idx >= 0:
        print(f"  'résultat' context: ...{text[max(0,idx-100):idx+100]}...", file=sys.stderr)
    print(file=sys.stderr)


def main() -> int:
    session = make_session()
    search(session, "9999999999999", "garbage EAN-shaped query")
    search(session, "1234567890123", "another garbage EAN-shaped query")
    search(session, "3701551706461", "real known EAN (control)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
