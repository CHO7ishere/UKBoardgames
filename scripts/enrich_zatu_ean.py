#!/usr/bin/env python3
"""Stage 4 (partial): fetch the real per-product EAN and image URL for each Stage 2 survivor.

The bulk Zatu harvest has `barcode: null` on every product (docs/spec.md §11.1) and never
captured an image URL at all (parse_product only reads handle/title/tags/variants) — the
per-product `/products/<handle>.json` endpoint has both, confirmed live via
scripts/probe_zatu_detail.py for the EAN case. One HTTP request per survivor (not the whole
catalogue), per the spec's cheap-wide/expensive-narrow rule -- EAN and image both come from the
same request, so adding image capture costs nothing extra. Needs real network access to
zatu.com — run via GitHub Actions, not this coding sandbox.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sources.zatu import extract_ean, extract_image_url, fetch_product_detail, make_session  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matched", default="data/matched_games.json")
    parser.add_argument("--out", default="data/matched_games.json")
    parser.add_argument("--rate-limit-sec", type=float, default=1.0)
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch every survivor's EAN/image even if already cached from a prior run "
        "(default: skip survivors that already have both a real EAN and an image URL -- this "
        "is static per-product data, essentially never changes, so re-fetching it on every run "
        "is pure waste).",
    )
    args = parser.parse_args()

    payload = json.loads(Path(args.matched).read_text())
    survivors = payload["survivors"]
    print(f"Enriching {len(survivors)} survivors with real per-product EANs/images...", file=sys.stderr)

    session = make_session()
    found = 0
    errors = 0
    cached = 0
    for i, survivor in enumerate(survivors, start=1):
        if not args.refresh and survivor.get("zatu_ean") and survivor.get("zatu_image_url"):
            cached += 1
            continue
        try:
            detail = fetch_product_detail(session, survivor["zatu_handle"])
            ean = extract_ean(detail)
            image_url = extract_image_url(detail)
        except Exception as exc:  # noqa: BLE001 — one bad product must not kill the whole run
            print(f"  [{i}/{len(survivors)}] ERROR {survivor['zatu_handle']}: {exc}", file=sys.stderr)
            ean = None
            image_url = None
            errors += 1
        survivor["zatu_ean"] = ean
        survivor["zatu_image_url"] = image_url
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
