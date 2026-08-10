#!/usr/bin/env python3
"""One-off diagnostic: verify sources/philibert.py's `_classify_stock` container selectors
against real product URLs collected by the actual Stage 5 run (data/philibert_results.json).

The real run found ZERO LISTED_OUT_OF_STOCK results out of 381 listed products — either
genuinely true, or the guessed selectors in `_STOCK_CONTAINER_SELECTORS` never match, silently
defaulting everything with a price to "in stock" via the fallback in lookup_philibert.py.
This checks which (if any) guessed selector actually matches on real pages, and dumps the real
markup around the add-to-cart/availability area for manual inspection. Not part of the
production pipeline; run manually via the probe-philibert workflow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sources.philibert import _STOCK_CONTAINER_SELECTORS, make_session  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

# A handful of real URLs from the actual Stage 5 run, spanning different publishers/pages —
# more representative than a single hand-picked example.
SAMPLE_URLS = [
    "https://www.philibertnet.com/fr/zman-games/23050-pandemie-8435407620155.html",
    "https://www.philibertnet.com/fr/matagot/73168-wingspan-3760146644991.html",
    "https://www.philibertnet.com/fr/the-op/160661-flip-7-compact-0700304159960.html",
    "https://www.philibertnet.com/fr/days-of-wonder/56360-ticket-to-ride-europe-824968717929.html",
    "https://www.philibertnet.com/fr/next-move/54391-azul-826956620105.html",
]


def main() -> int:
    session = make_session()
    for url in SAMPLE_URLS:
        print(f"\n=== {url} ===", file=sys.stderr)
        resp = session.get(url, timeout=30)
        print(f"status={resp.status_code}", file=sys.stderr)
        if resp.status_code != 200:
            continue
        soup = BeautifulSoup(resp.text, "lxml")

        matched_any = False
        for selector in _STOCK_CONTAINER_SELECTORS:
            el = soup.select_one(selector)
            if el:
                matched_any = True
                print(f"  MATCHED {selector!r}: {el.get_text(' ', strip=True)[:200]!r}", file=sys.stderr)
        if not matched_any:
            print("  none of the guessed selectors matched", file=sys.stderr)

        # Find the "Ajouter au panier" button/text directly and print its real ancestor chain.
        add_to_cart = soup.find(string=lambda s: s and "panier" in s.lower())
        if add_to_cart:
            chain = []
            el = add_to_cart.parent
            for _ in range(5):
                if el is None:
                    break
                chain.append(f"<{el.name} class={el.get('class')} id={el.get('id')}>")
                el = el.parent
            print(f"  'panier' text ancestor chain: {' < '.join(chain)}", file=sys.stderr)
        else:
            print("  no 'panier' text found on page at all", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
