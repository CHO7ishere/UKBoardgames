#!/usr/bin/env python3
"""Stage 6: composite scoring (docs/spec.md §5, §5.3-5.4). Pure offline computation over Stage
5's shortlist -- no network needed, unlike Stages 0/3/4/5.

Genre bonus uses Zatu's own coop/party tag signal (`zatu_is_coop`/`zatu_is_party`) as a stand-in
for BGG mechanics data, per CLAUDE.md's build order. **Currently always null** in the committed
data/shortlist.json: the committed data/zatu_products.json harvest predates the is_coop/is_party
fields being added to `ZatuProduct.to_dict()`, so every record scores 0 genre points until Zatu
is re-harvested and Stage 2 re-matched -- `genre_points()` treats None the same as False (no
bonus, not a penalty), so this doesn't block v1, it just means the genre bonus isn't live yet.

Language dependence (`bgg_language_level`) comes from Stage 3's BGG community-poll scrape
(sources/bgg_versions.py's parse_language_dependence, wired in via lookup_philibert.py) when
available; games Stage 3 hasn't checked yet fall back to language_points()'s own conservative
UNKNOWN default (flat -3 penalty, `language_unknown` flag), spec §5.4's default for missing data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from score import composite_score, genre_points, language_points  # noqa: E402


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def score_one(record: dict, weights: dict) -> dict:
    genre_pts = genre_points(record.get("zatu_is_coop"), record.get("zatu_is_party"), weights["genre"])
    language_pts, language_unknown = language_points(
        record.get("bgg_language_level"), weights["language"]
    )
    score = composite_score(
        advantage_pts=record["advantage_points"],
        quality_pts=record["quality_pts"],
        genre_pts=genre_pts,
        language_pts=language_pts,
    )
    return {
        **record,
        "genre_points": genre_pts,
        "language_points": language_pts,
        "language_unknown": language_unknown,
        "composite_score": score,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shortlist", default="data/shortlist.json")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--out", default="data/scored_games.json")
    args = parser.parse_args()

    config = load_config(args.config)
    weights = config["weights"]

    payload = json.loads(Path(args.shortlist).read_text())
    games = [score_one(record, weights) for record in payload["shortlist"]]
    games.sort(key=lambda g: g["composite_score"], reverse=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"games": games}, indent=2))

    print(f"Scored {len(games)} games -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
