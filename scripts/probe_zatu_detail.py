#!/usr/bin/env python3
"""One-off diagnostic: print the raw per-product JSON for a few known handles so we can see,
from a network that can actually reach zatu.com, whether `/products/<handle>.json` carries
fields the bulk `/collections/.../products.json` doesn't (barcode, price_currency) — see the
[VERIFY] notes on `fetch_product_detail`/`verify_gbp_currency` in sources/zatu.py. Not part of
the production pipeline; run manually via the probe-zatu-detail workflow, read the job log.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sources.zatu import fetch_product_detail, make_session  # noqa: E402

SAMPLE_HANDLES = [
    "manipulate",
    "spirit-island-core-game",
    "brass-birmingham",
]


def main() -> int:
    session = make_session()
    for handle in SAMPLE_HANDLES:
        print(f"\n=== {handle} ===", file=sys.stderr)
        try:
            detail = fetch_product_detail(session, handle)
        except Exception as exc:  # noqa: BLE001 — diagnostic script, print and move on
            print(f"ERROR fetching {handle}: {exc}", file=sys.stderr)
            continue
        variants = detail.get("variants", [])
        print(f"top-level keys: {sorted(detail.keys())}", file=sys.stderr)
        if variants:
            print(f"variant[0] keys: {sorted(variants[0].keys())}", file=sys.stderr)
            print(f"variant[0]: {json.dumps(variants[0], indent=2)}", file=sys.stderr)
        else:
            print("no variants in response", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
