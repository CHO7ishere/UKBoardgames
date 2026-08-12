#!/usr/bin/env python3
"""Stage 3: for each Stage 2 survivor, fetch BGG's own data via the real XML API2
(sources/bgg_api.py, `thing?id=...&stats=1&versions=1`, `Authorization: Bearer <token>`) --
supersedes the earlier headless-browser scraper (sources/bgg_versions.py, kept as a documented
fallback, not called here anymore) now that a real BGG API token exists (2026-08-12).

Confirmed live via scripts/probe_bgg_api.py before this was written (see sources/bgg_api.py's
own module docstring for the full probe trail): 401 without the token, 200 with it; stats=1 and
versions=1 combine into one request; the real language_dependence poll and per-version language
link schema, cross-validated against the headless-browser scraper's own prior findings (Marvel
Champions' French edition: same title, same version id, found independently both ways).

Two outputs:
- data/bgg_fr_editions.json -- the narrow fields Stage 5/6 actually read (fr_edition_exists,
  fr_edition_titles, language_level, language_votes), same schema as before this script's
  rewrite, so lookup_philibert.py/score_games.py need zero changes.
- data/bgg_details.json -- the *full* parsed answer for every bgg_id checked (name, alternate
  names, description, mechanics, categories, designers, publishers, artists, statistics), not
  just the two narrow fields above. User's explicit ask (2026-08-12): now that a single batched
  API call returns all of this for free, there's no reason to throw the rest away and have to
  re-fetch it later if it becomes useful (e.g. a real BGG-mechanics-based genre bonus instead of
  Zatu's own tags).

fr_edition_exists feeds Stage 5's advantage verdict (spec §5.2's UNAVAILABLE_FR vs the weaker
UNAVAILABLE_FR? distinction) -- user's explicit ask (2026-08-11): "I don't want to buy English
versions if a French one exists (even if unavailable)".

Both files are essentially static (BGG's own catalogued versions / crowd poll / metadata), so
once a bgg_id is checked it's cached indefinitely; --refresh forces a full re-check.

Needs real network access to boardgamegeek.com and a BGG_TOKEN env var -- run via GitHub
Actions, not this coding sandbox. No headless browser needed anymore (plain `requests`), so the
workflow no longer installs Playwright/Chromium for this stage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sources.bgg_api import fetch_things, make_session  # noqa: E402


def _load_json_list(path: str, key: str) -> list[dict]:
    file = Path(path)
    if not file.exists():
        return []
    return json.loads(file.read_text()).get(key, [])


def _load_cache(path: str) -> dict[str, dict]:
    file = Path(path)
    if not file.exists():
        return {}
    try:
        return json.loads(file.read_text())
    except json.JSONDecodeError:
        return {}


def select_survivors_to_check(
    survivors: list[dict], philibert_results: list[dict], cache: dict[str, dict], refresh: bool
) -> list[dict]:
    """A bgg_id needs a (re-)check when its cache entry is missing `language_level` entirely --
    that field is read for every scored row (unlike fr_edition_exists, only read for NOT_LISTED
    survivors), so a bgg_id is only "fully cached" once both fields are known. `philibert_results`
    is accepted for backward-compatible call signatures but is no longer read."""
    to_check = []
    seen_bgg_ids = set()
    for survivor in survivors:
        bgg_id = str(survivor["bgg_id"])
        if bgg_id in seen_bgg_ids:  # multiple Zatu SKUs can share a base bgg_id
            continue
        cached = None if refresh else cache.get(bgg_id)
        if cached is not None and "language_level" in cached:
            continue
        to_check.append(survivor)
        seen_bgg_ids.add(bgg_id)
    return to_check


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matched", default="data/matched_games.json")
    parser.add_argument("--philibert-results", default="data/philibert_results.json")
    parser.add_argument("--out", default="data/bgg_fr_editions.json")
    parser.add_argument("--details-out", default="data/bgg_details.json")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--rate-limit-sec", type=float, default=5.0)
    args = parser.parse_args()

    token = os.environ.get("BGG_TOKEN")
    if not token:
        print("ERROR: BGG_TOKEN environment variable is not set.", file=sys.stderr)
        return 1

    survivors = _load_json_list(args.matched, "survivors")
    philibert_results = _load_json_list(args.philibert_results, "results")
    fr_editions_cache = {} if args.refresh else _load_cache(args.out)
    details_cache = {} if args.refresh else _load_cache(args.details_out)

    to_check = select_survivors_to_check(survivors, philibert_results, fr_editions_cache, args.refresh)
    bgg_ids = [s["bgg_id"] for s in to_check]
    print(
        f"{len(bgg_ids)} bgg_id(s) need a BGG check "
        f"({len(fr_editions_cache)} already cached).",
        file=sys.stderr,
    )

    session = make_session()
    items, stats = fetch_things(session, bgg_ids, token, rate_limit_sec=args.rate_limit_sec)

    for item in items:
        bgg_id_str = str(item["bgg_id"])
        fr_editions_cache[bgg_id_str] = {
            "fr_edition_exists": item["fr_edition_exists"],
            "fr_edition_titles": item["fr_edition_titles"],
            "language_level": item["language_level"],
            "language_votes": item["language_votes"],
        }
        details_cache[bgg_id_str] = item

    print(
        f"Done: {stats.batches} batch(es), {stats.items_returned} item(s) returned, "
        f"{stats.retries_202} HTTP 202 retries, {len(stats.errors)} error(s).",
        file=sys.stderr,
    )
    for error in stats.errors:
        print(f"  ERROR {error}", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fr_editions_cache, indent=2))
    print(f"Wrote {out_path}", file=sys.stderr)

    details_path = Path(args.details_out)
    details_path.parent.mkdir(parents=True, exist_ok=True)
    details_path.write_text(json.dumps(details_cache, indent=2, ensure_ascii=False))
    print(f"Wrote {details_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
