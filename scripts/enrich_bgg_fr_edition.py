#!/usr/bin/env python3
"""Stage 3 (partial): for each Stage 2 survivor not already known to be listed on Philibert,
check BGG's own versions data (via a real headless browser -- BGG is Cloudflare-protected, see
sources/bgg_versions.py) for whether a French edition exists at all, even if it's not currently
purchasable anywhere. Feeds `fr_edition_exists` into Stage 5's advantage verdict (spec §5.2's
UNAVAILABLE_FR vs the weaker UNAVAILABLE_FR? distinction) -- user's explicit ask (2026-08-11):
"I don't want to buy English versions if a French one exists (even if unavailable)". Real case
that prompted this: Gloomhaven: Jaws of the Lion (bgg_id=291457) is NOT_LISTED on Philibert, but
BGG's own versions data confirms a real French edition exists.

Scoped to survivors that are (a) not yet cached in --out, and (b) either brand new or were
NOT_LISTED on Philibert in the last run (per --philibert-results) -- fr_edition_exists is only
ever read by compute_advantage's NOT_LISTED branch, so checking games Philibert already found
live would be wasted browser time. This data is essentially static (BGG's own catalogued
versions), so once a bgg_id is checked it's cached indefinitely; --refresh forces a full re-check.

Needs real network access to boardgamegeek.com and a headless Chromium -- run via GitHub
Actions, not this coding sandbox.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

from sources.bgg_versions import fetch_french_edition_info  # noqa: E402


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
    not_listed_handles = {
        r["zatu_handle"] for r in philibert_results if r.get("philibert_status") == "NOT_LISTED"
    }
    checked_handles = {r["zatu_handle"] for r in philibert_results}

    to_check = []
    seen_bgg_ids = set()
    for survivor in survivors:
        bgg_id = str(survivor["bgg_id"])
        if not refresh and bgg_id in cache:
            continue
        if bgg_id in seen_bgg_ids:  # multiple Zatu SKUs can share a base bgg_id
            continue
        handle = survivor["zatu_handle"]
        if handle not in checked_handles or handle in not_listed_handles:
            to_check.append(survivor)
            seen_bgg_ids.add(bgg_id)
    return to_check


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matched", default="data/matched_games.json")
    parser.add_argument("--philibert-results", default="data/philibert_results.json")
    parser.add_argument("--out", default="data/bgg_fr_editions.json")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--rate-limit-sec", type=float, default=1.0)
    args = parser.parse_args()

    survivors = _load_json_list(args.matched, "survivors")
    philibert_results = _load_json_list(args.philibert_results, "results")
    cache = {} if args.refresh else _load_cache(args.out)

    to_check = select_survivors_to_check(survivors, philibert_results, cache, args.refresh)
    print(
        f"{len(to_check)} survivor(s) need a BGG French-edition check "
        f"({len(cache)} bgg_id(s) already cached).",
        file=sys.stderr,
    )

    checked = 0
    errors = 0

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        for i, survivor in enumerate(to_check, start=1):
            bgg_id = survivor["bgg_id"]
            try:
                info = fetch_french_edition_info(page, bgg_id)
            except Exception as exc:  # noqa: BLE001 -- one bad page must not kill the whole run
                print(f"  [{i}/{len(to_check)}] ERROR bgg_id={bgg_id}: {exc}", file=sys.stderr)
                errors += 1
                time.sleep(args.rate_limit_sec)
                continue
            cache[str(bgg_id)] = info
            checked += 1
            if i % 20 == 0 or i == len(to_check):
                print(f"  [{i}/{len(to_check)}] {checked} checked, {errors} errors", file=sys.stderr)
            time.sleep(args.rate_limit_sec)

        browser.close()

    print(f"Done: {checked} new checks, {errors} errors.", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cache, indent=2))
    print(f"Wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
