#!/usr/bin/env python3
"""One-off diagnostic: why did the real Stage 5 run still mark Slay the Spire NOT_LISTED
after the article-normalization + prefix-match fix?

Zatu's EAN for it (0745808253646) is presumably the English edition's -- Philibert only sells
the French edition under a different EAN (3760372232801), so the EAN tier correctly finding
nothing is expected (same shape as the confirmed-correct Blood on the Clocktower case). The open
question is the title-fallback tier: does Philibert's own search return ANY candidates at all
for the raw Zatu title "Slay the Spire: The Board Game", given its search is known to behave
oddly on verbose/multi-word queries? Prints the raw links search_by_title's `_search_links`
sees for a few query variants, so the real bottleneck (empty search results vs. a filtering bug)
can be told apart. Not part of the production pipeline; run manually via the probe-philibert
workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from match import normalize_title  # noqa: E402
from sources.philibert import _search_links, make_session, search_by_ean, search_by_title  # noqa: E402

QUERIES = [
    "Slay the Spire: The Board Game",  # raw Zatu title (what search_by_title sends today)
    "Slay the Spire",  # normalize_title's noise-stripped core
    "slay spire",  # fully normalized
]


def main() -> int:
    session = make_session()

    print("=== EAN tier ===", file=sys.stderr)
    ean = "0745808253646"
    url = search_by_ean(session, ean)
    print(f"search_by_ean({ean!r}) -> {url!r}", file=sys.stderr)

    print("\n=== raw search_links per query variant ===", file=sys.stderr)
    for query in QUERIES:
        links = _search_links(session, query)
        print(f"\nquery={query!r} -> {len(links)} link(s)", file=sys.stderr)
        for link in links[:10]:
            print(f"  {link}", file=sys.stderr)

    print("\n=== search_by_title() end-to-end per query variant ===", file=sys.stderr)
    for query in QUERIES:
        result = search_by_title(session, query)
        print(f"search_by_title({query!r}) -> {result!r}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
