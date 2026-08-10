#!/usr/bin/env python3
"""One-off diagnostic (docs/spec.md Stage 3, currently blocked on the BGG API token): can the
public BGG game page be scraped instead, with no auth, for (a) the language-dependence community
poll and (b) whether a French-language edition exists (BGG's "Versions" list)?

Fetches a plain `requests.get` of a few real game pages (no token, no browser/JS execution) and
checks whether the language-dependence poll results and version/language data are present in the
raw server-rendered HTML, or whether the modern BGG site only renders them client-side (in which
case plain requests can't reach them and this fallback isn't viable without a headless browser).
Prints byte-offsets and surrounding context for any hits so the real page shape is visible in the
job log, rather than guessing from memory. Not part of the production pipeline; run manually via
the probe-bgg-page workflow.
"""

from __future__ import annotations

import re
import sys

import requests

USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"

GAMES = [
    (285774, "Marvel Champions: The Card Game"),
    (296345, "Sherlock Holmes Consulting Detective: The Baker Street Irregulars"),
    (30549, "Pandemic"),  # well-known, many language editions -- good control case
]

LANGUAGE_POLL_MARKERS = [
    "Language Dependence",
    "No necessary in-game text",
    "Some necessary text",
    "Moderate in-game text",
    "Extensive use of text",
    "Unplayable in another language",
]

EMBEDDED_JSON_MARKERS = [
    "GEEK.geekitemPreload",
    "__NEXT_DATA__",
    "__INITIAL_STATE__",
    "window.geekitemSSRData",
    "application/json",
]


def _print_context(text: str, needle: str, before: int = 80, after: int = 200) -> None:
    idx = text.find(needle)
    if idx == -1:
        return
    start = max(0, idx - before)
    end = min(len(text), idx + after)
    snippet = text[start:end].replace("\n", " ")
    print(f"    ...{snippet}...", file=sys.stderr)


def probe_page(session: requests.Session, url: str, label: str) -> str:
    resp = session.get(url, timeout=30)
    print(f"\nGET {url} -> {resp.status_code}, {len(resp.text)} bytes", file=sys.stderr)
    if resp.status_code != 200:
        print(f"  non-200 response, first 300 chars: {resp.text[:300]!r}", file=sys.stderr)
        return resp.text

    print(f"  -- {label}: language-dependence poll markers --", file=sys.stderr)
    for marker in LANGUAGE_POLL_MARKERS:
        hit = marker in resp.text
        print(f"    {marker!r}: {'FOUND' if hit else 'not found'}", file=sys.stderr)
        if hit:
            _print_context(resp.text, marker)

    print(f"  -- {label}: embedded JSON / SSR markers --", file=sys.stderr)
    for marker in EMBEDDED_JSON_MARKERS:
        count = resp.text.count(marker)
        print(f"    {marker!r}: {count} occurrence(s)", file=sys.stderr)

    print(f"  -- {label}: French/France mentions (raw count) --", file=sys.stderr)
    for word in ["Français", "French", "France"]:
        count = len(re.findall(re.escape(word), resp.text))
        print(f"    {word!r}: {count} occurrence(s)", file=sys.stderr)

    return resp.text


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})

    for bgg_id, name in GAMES:
        print(f"\n{'=' * 70}\n{name} (bgg_id={bgg_id})", file=sys.stderr)
        probe_page(session, f"https://boardgamegeek.com/boardgame/{bgg_id}", "main page")
        probe_page(session, f"https://boardgamegeek.com/boardgame/{bgg_id}/versions", "versions page")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
