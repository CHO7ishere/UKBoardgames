#!/usr/bin/env python3
"""Run Stage 0 (Zatu harvest) + Stage 1 (light filter) and write the result to a JSON file.

Needs real network access to zatu.com — run this from an environment whose network policy
allows it (GitHub Actions, or a developer machine), not from a sandboxed coding environment
that blocks the site outright (see CLAUDE.md "Network reality in this coding environment").
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filters import filter_board_games  # noqa: E402
from sources.zatu import harvest_all, make_session, verify_gbp_currency  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/zatu_products.json", help="Output JSON path")
    parser.add_argument("--rate-limit-sec", type=float, default=1.0)
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument(
        "--skip-currency-check",
        action="store_true",
        help="Skip the GBP verification fetch (debugging only — never use for a real run)",
    )
    args = parser.parse_args()

    session = make_session()

    if not args.skip_currency_check:
        print("Verifying Zatu returns GBP pricing before trusting any price...", file=sys.stderr)
        if not verify_gbp_currency(session):
            print(
                "ERROR: Zatu did not return GBP currency metadata for the sample product. "
                "Every price in this harvest would be wrong — aborting rather than silently "
                "corrupting downstream discount calculations (spec §0.2, §8).",
                file=sys.stderr,
            )
            return 1
        print("Confirmed GBP.", file=sys.stderr)

    print("Harvesting Zatu's top-5000-board-games collection...", file=sys.stderr)
    products = harvest_all(
        session=session, rate_limit_sec=args.rate_limit_sec, max_pages=args.max_pages
    )
    print(f"Harvested {len(products)} raw listings.", file=sys.stderr)

    games = filter_board_games(products)
    dropped = len(products) - len(games)
    print(f"Kept {len(games)} board games, dropped {dropped} likely accessories.", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_metadata": {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "currency_verified": not args.skip_currency_check,
            "raw_count": len(products),
            "kept_count": len(games),
            "dropped_accessory_count": dropped,
        },
        "products": [dataclasses.asdict(p) for p in games],
    }
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
