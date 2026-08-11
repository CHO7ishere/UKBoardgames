#!/usr/bin/env python3
"""Stage 4 (partial): fetch the real per-product EAN for each Stage 2 survivor.

The bulk Zatu harvest has `barcode: null` on every product (docs/spec.md §11.1) — the
per-product `/products/<handle>.json` endpoint has it, confirmed live via
scripts/probe_zatu_detail.py. One HTTP request per survivor (not the whole catalogue), per the
spec's cheap-wide/expensive-narrow rule. Needs real network access to zatu.com — run via
GitHub Actions, not this coding sandbox.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sources.zatu import fetch_product_ean, make_session  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matched", default="data/matched_games.json")
    parser.add_argument("--out", default="data/matched_games.json")
    parser.add_argument("--rate-limit-sec", type=float, default=1.0)
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch every survivor's EAN even if one is already cached from a prior run "
        "(default: skip survivors that already have a real EAN -- Zatu barcodes are static "
        "data, essentially never change, so re-fetching them on every run is pure waste).",
    )
    args = parser.parse_args()

    payload = json.loads(Path(args.matched).read_text())
    survivors = payload["survivors"]
    print(f"Enriching {len(survivors)} survivors with real per-product EANs...", file=sys.stderr)

    session = make_session()
    found = 0
    errors = 0
    cached = 0
    for i, survivor in enumerate(survivors, start=1):
        if not args.refresh and survivor.get("zatu_ean"):
            cached += 1
            continue
        try:
            ean = fetch_product_ean(session, survivor["zatu_handle"])
        except Exception as exc:  # noqa: BLE001 — one bad product must not kill the whole run
            print(f"  [{i}/{len(survivors)}] ERROR {survivor['zatu_handle']}: {exc}", file=sys.stderr)
            ean = None
            errors += 1
        survivor["zatu_ean"] = ean
        if ean:
            found += 1
        if i % 50 == 0 or i == len(survivors):
            print(f"  [{i}/{len(survivors)}] {found} EANs found so far, {errors} errors", file=sys.stderr)
        time.sleep(args.rate_limit_sec)

    print(
        f"Done: {found} new EANs found, {cached} already cached (skipped), {errors} errors, "
        f"out of {len(survivors)} survivors.",
        file=sys.stderr,
    )

    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
