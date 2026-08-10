#!/usr/bin/env python3
"""One-off diagnostic: why did the real Stage 5 run mark "Marvel Champions: The Card Game" and
the Sherlock Holmes Consulting Detective titles NOT_LISTED, when the user found real Philibert
listings for both by hand (e.g.
https://www.philibertnet.com/fr/boite-de-base-et-extensions/79262-marvel-champions-le-jeu-de-cartes-8435407628465.html)?

Both are the same shape of problem: the real French listing's title diverges from the English
Zatu title (translated subtitle: "The Card Game" -> "Le Jeu de Cartes"), which no fuzzy score can
bridge -- same root cause as the earlier Slay the Spire miss. The open question this time is
whether the *base-title fallback* (`search_family_title`, added for the Everdell/Cthulhu misses)
also fails, and if so why: no candidates at all, or an ambiguous-prefix rejection (Marvel
Champions in particular has dozens of hero/scenario-pack expansions on Philibert that could all
share "marvel champions" as a normalized prefix). Prints raw search links, `search_by_title`, and
`search_family_title` results per query variant so the real bottleneck is visible in the job log.
Not part of the production pipeline; run manually via the probe-philibert workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from match import normalize_title  # noqa: E402
from sources.philibert import (  # noqa: E402
    _base_title_candidates,
    _search_links,
    make_session,
    search_by_title,
    search_family_title,
)

TITLES = [
    "Marvel Champions: The Card Game",
    "Sherlock Holmes Consulting Detective: The Baker Street Irregulars",
    "Sherlock Holmes Consulting Detective: The Thames Murders",
]


def main() -> int:
    session = make_session()

    for title in TITLES:
        print(f"\n{'=' * 70}\nTITLE: {title!r}", file=sys.stderr)
        print(f"normalized: {normalize_title(title)!r}", file=sys.stderr)
        print(f"base-title candidates: {_base_title_candidates(title)!r}", file=sys.stderr)

        print("\n-- raw search links for the full title --", file=sys.stderr)
        links = _search_links(session, title)
        print(f"{len(links)} link(s)", file=sys.stderr)
        for link in links[:15]:
            print(f"  {link}", file=sys.stderr)

        for candidate in _base_title_candidates(title):
            print(f"\n-- raw search links for base-title candidate {candidate!r} --", file=sys.stderr)
            clinks = _search_links(session, candidate)
            print(f"{len(clinks)} link(s)", file=sys.stderr)
            for link in clinks[:20]:
                print(f"  {link}", file=sys.stderr)

        exact = search_by_title(session, title)
        print(f"\nsearch_by_title({title!r}) -> {exact!r}", file=sys.stderr)

        family = search_family_title(session, title)
        print(f"search_family_title({title!r}) -> {family!r}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
