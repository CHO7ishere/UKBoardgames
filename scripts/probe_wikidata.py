#!/usr/bin/env python3
"""One-off diagnostic: can Wikidata serve as a generic, non-hardcoded source of localized
(French) game titles, as an alternative/complement to BGG's own "Alternate Names" data (still
blocked behind Cloudflare -- see scripts/probe_bgg_page.py / probe_bgg_playwright.py)?

Wikidata carries a "BoardGameGeek ID" property (P2339) on many board-game items, cross-
referencing them to BGG -- if a game has both a Wikidata entry and a French label, a reverse
SPARQL lookup by BGG ID gives us the real localized title with zero hardcoding, generalizing to
any game in Wikidata rather than a per-title alias list. Tests against known BGG IDs including
two real misses (Marvel Champions, Sherlock Holmes Consulting Detective) plus two well-known
control cases (Everdell, Gloomhaven) to see real coverage, not just a happy-path single case.
Not part of the production pipeline; run manually via the probe-wikidata workflow.
"""

from __future__ import annotations

import json
import sys

import requests

USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

GAMES = [
    (285774, "Marvel Champions: The Card Game"),
    (296345, "Sherlock Holmes Consulting Detective: The Baker Street Irregulars"),
    (2511, "Sherlock Holmes Consulting Detective: The Thames Murders & Other Cases"),
    (199792, "Everdell"),
    (174430, "Gloomhaven"),
]

QUERY_TEMPLATE = """
SELECT ?item ?itemLabel ?enLabel ?frLabel WHERE {{
  ?item wdt:P2339 "{bgg_id}".
  OPTIONAL {{ ?item rdfs:label ?enLabel . FILTER(LANG(?enLabel) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?frLabel . FILTER(LANG(?frLabel) = "fr") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""


def query_bgg_id(session: requests.Session, bgg_id: int) -> list[dict]:
    resp = session.get(
        SPARQL_ENDPOINT,
        params={"query": QUERY_TEMPLATE.format(bgg_id=bgg_id), "format": "json"},
        timeout=30,
    )
    print(f"  status={resp.status_code}", file=sys.stderr)
    resp.raise_for_status()
    return resp.json().get("results", {}).get("bindings", [])


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})

    for bgg_id, name in GAMES:
        print(f"\n{'=' * 70}\n{name} (bgg_id={bgg_id})", file=sys.stderr)
        try:
            bindings = query_bgg_id(session, bgg_id)
        except requests.RequestException as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            continue

        print(f"  {len(bindings)} Wikidata item(s) with this BGG ID", file=sys.stderr)
        for b in bindings:
            item = b.get("item", {}).get("value")
            en = b.get("enLabel", {}).get("value")
            fr = b.get("frLabel", {}).get("value")
            print(f"    item={item}", file=sys.stderr)
            print(f"    en label={en!r}", file=sys.stderr)
            print(f"    fr label={fr!r}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
