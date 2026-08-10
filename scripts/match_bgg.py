#!/usr/bin/env python3
"""Stage 2: offline match of the harvested Zatu catalogue against bg_ranks.csv, then the
quality gate (docs/spec.md §3, §5.1). No network calls — the bg_ranks.csv is a static file
downloaded by hand (spec §0.1), so this is safe to run anywhere, including this coding sandbox.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from match import BggIndex  # noqa: E402
from score import evaluate_quality  # noqa: E402
from sources.bgg import filter_base_games, load_bg_ranks  # noqa: E402
from sources.zatu import is_coop_tag, is_party_tag  # noqa: E402

_DROPPED_FIELDNAMES = ["zatu_handle", "zatu_title", "reason", "bgg_id", "bgg_name", "score"]


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def load_zatu_products(path: str) -> list[dict]:
    payload = json.loads(Path(path).read_text())
    return payload["products"]


def run(zatu_products: list[dict], bgg_games, config: dict) -> tuple[list[dict], list[dict]]:
    index = BggIndex(bgg_games)
    by_id = {g.id: g for g in bgg_games}

    quality_cfg = config.get("quality", {})
    shrink_m = quality_cfg.get("shrink_M", 100)
    prior = quality_cfg.get("prior", 6.5)
    min_shrunk = quality_cfg.get("min_shrunk", 7.2)
    min_votes = quality_cfg.get("min_votes", 30)

    matching_cfg = config.get("matching", {})
    fuzzy_threshold = matching_cfg.get("fuzzy_threshold", 90)
    min_gap = matching_cfg.get("min_score_gap", 5)

    survivors = []
    dropped = []

    for product in zatu_products:
        result = index.match(product["title"], fuzzy_threshold=fuzzy_threshold, min_gap=min_gap)

        if result.confidence == "LOW":
            dropped.append(
                {
                    "zatu_handle": product["handle"],
                    "zatu_title": product["title"],
                    "reason": f"LOW_CONFIDENCE_MATCH: {result.reason}",
                    "bgg_id": result.bgg_id or "",
                    "bgg_name": result.bgg_name or "",
                    "score": result.score if result.score is not None else "",
                }
            )
            continue

        bgg = by_id[result.bgg_id]
        quality = evaluate_quality(bgg, shrink_m, prior, min_shrunk, min_votes)

        if not quality.passes_gate:
            dropped.append(
                {
                    "zatu_handle": product["handle"],
                    "zatu_title": product["title"],
                    "reason": (
                        f"QUALITY_GATE: shrunk={quality.shrunk:.2f}, usersrated={bgg.usersrated}"
                    ),
                    "bgg_id": bgg.id,
                    "bgg_name": bgg.name,
                    "score": result.score if result.score is not None else "",
                }
            )
            continue

        survivors.append(
            {
                "zatu_handle": product["handle"],
                "zatu_title": product["title"],
                "zatu_url": product["url"],
                "zatu_price_gbp": product.get("min_price_gbp"),
                "zatu_in_stock": product.get("in_stock"),
                "zatu_ean": product.get("ean"),
                "zatu_tags": product.get("tags", []),
                # Derived from the raw `tags` list rather than trusting `is_coop`/`is_party`
                # keys on the product dict -- those only exist on a ZatuProduct.to_dict()
                # output, not on the committed data/zatu_products.json's plainer product
                # records, so product.get("is_coop") silently returned None for every survivor
                # until this was traced down (confirmed live: tags are always present, the
                # derived keys never were).
                "zatu_is_coop": is_coop_tag(product.get("tags", [])),
                "zatu_is_party": is_party_tag(product.get("tags", [])),
                "bgg_id": bgg.id,
                "bgg_name": bgg.name,
                "bgg_year": bgg.year,
                "bgg_rank": bgg.rank,
                "bgg_average": bgg.average,
                "bgg_usersrated": bgg.usersrated,
                "match_confidence": result.confidence,
                "match_score": result.score,
                "quality_shrunk": round(quality.shrunk, 3),
                "quality_pts": round(quality.quality_pts, 2),
                "quality_label": quality.label,
            }
        )

    return survivors, dropped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zatu", default="data/zatu_products.json")
    parser.add_argument("--bgg-ranks", default="data/bg_ranks.csv")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--out", default="data/matched_games.json")
    parser.add_argument("--dropped-out", default="data/dropped.csv")
    args = parser.parse_args()

    if not Path(args.bgg_ranks).exists():
        print(
            f"ERROR: {args.bgg_ranks} not found. Download it by hand from "
            "boardgamegeek.com/data_dumps/bg_ranks while logged into a browser (spec §0.1) "
            "and place it there — no BGG token needed for this step.",
            file=sys.stderr,
        )
        return 1

    config = load_config(args.config)
    products = load_zatu_products(args.zatu)
    print(f"Loaded {len(products)} Zatu products.", file=sys.stderr)

    print(f"Loading BGG ranks from {args.bgg_ranks}...", file=sys.stderr)
    bgg_games = load_bg_ranks(args.bgg_ranks)
    bgg_games = filter_base_games(
        bgg_games, include_expansions=config.get("include_expansions", False)
    )
    print(f"{len(bgg_games)} base games in bg_ranks.csv after dropping expansions.", file=sys.stderr)

    survivors, dropped = run(products, bgg_games, config)
    print(
        f"{len(survivors)} survivors (matched + passed quality gate), {len(dropped)} dropped.",
        file=sys.stderr,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"survivors": survivors}, indent=2))

    dropped_path = Path(args.dropped_out)
    with dropped_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_DROPPED_FIELDNAMES)
        writer.writeheader()
        writer.writerows(dropped)

    print(f"Wrote {out_path} and {dropped_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
