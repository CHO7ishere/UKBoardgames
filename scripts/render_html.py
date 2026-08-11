#!/usr/bin/env python3
"""Stage 7 driver: renders Stage 6's scored games into the static HTML report (docs/spec.md
§6). Pure offline template rendering -- no network needed, unlike Stages 0/3/4/5.

Writes to docs/index.html by default -- GitHub Pages serves straight from a repo's /docs folder
on the default branch with no extra config, a natural fit for a static single-file report.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from render import render_html  # noqa: E402


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def _count_or_none(path: str, key: str) -> int | None:
    file = Path(path)
    if not file.exists():
        return None
    return len(json.loads(file.read_text())[key])


def load_excluded_handles(path: str) -> set[str]:
    """Manually-curated "not interested" list (spec's own plain-JSON-everywhere pattern) --
    unlike everything else in data/, nothing ever regenerates this file; it's edited by hand
    (or via the report's own "Export hidden list" button) and only ever read here."""
    file = Path(path)
    if not file.exists():
        return set()
    return set(json.loads(file.read_text()).get("excluded_handles", []))


def build_run_metadata(config: dict, zatu_products_path: str, matched_path: str) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "fx_gbp_eur": config["fx_gbp_eur"],
        "discount_threshold": config["discount_threshold"],
        "zatu_products_count": _count_or_none(zatu_products_path, "products"),
        "stage2_survivors_count": _count_or_none(matched_path, "survivors"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", default="data/scored_games.json")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--zatu-products", default="data/zatu_products.json")
    parser.add_argument("--matched", default="data/matched_games.json")
    parser.add_argument("--unmatched", default="data/unmatched_games.json")
    parser.add_argument("--excluded", default="data/excluded_games.json")
    parser.add_argument("--out", default="docs/index.html")
    args = parser.parse_args()

    config = load_config(args.config)
    games = json.loads(Path(args.scored).read_text())["games"]
    metadata = build_run_metadata(config, args.zatu_products, args.matched)

    unmatched_path = Path(args.unmatched)
    unmatched_games = (
        json.loads(unmatched_path.read_text())["unmatched"] if unmatched_path.exists() else []
    )
    excluded_handles = load_excluded_handles(args.excluded)

    html = render_html(games, metadata, unmatched_games, excluded_handles)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)

    print(
        f"Rendered {len(games)} scored games + {len(unmatched_games)} unmatched "
        f"({len(excluded_handles)} manually excluded) -> {out_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
