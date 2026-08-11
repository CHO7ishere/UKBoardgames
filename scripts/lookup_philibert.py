#!/usr/bin/env python3
"""Stage 5: Philibert lookup + the advantage-verdict filter (docs/spec.md §3 Stage 5, §5.2).

EAN search first (needs Stage 4's real per-product EANs — run scripts/enrich_zatu_ean.py first),
title fallback. Computes the UK-vs-France advantage verdict for every survivor and writes two
files: the full annotated results (data/philibert_results.json) and a shortlist with the NONE
verdict removed (data/shortlist.json) — "available in France at a similar price" is exactly the
NONE case (spec §5.2), the "no genuine UK advantage" one.

Needs real network access to philibertnet.com — run via GitHub Actions, not this coding sandbox.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from advantage import (  # noqa: E402
    VERDICT_EXCLUDED,
    VERDICT_FAMILY_AVAILABLE_FR,
    VERDICT_NONE,
    compute_advantage,
)
from sources.philibert import (  # noqa: E402
    fetch_product_page,
    make_session,
    search_by_ean,
    search_by_title,
    search_family_title,
)


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def lookup_one(session, survivor: dict, rate_limit_sec: float) -> dict:
    """Returns a Philibert-status dict: {status, price_eur, language, url}."""
    ean = survivor.get("zatu_ean")
    url = None

    if ean:
        url = search_by_ean(session, ean)
        time.sleep(rate_limit_sec)

    if not url:
        url = search_by_title(session, survivor["zatu_title"])
        time.sleep(rate_limit_sec)

    matched_family = False
    if not url:
        url = search_family_title(session, survivor["zatu_title"])
        time.sleep(rate_limit_sec)
        matched_family = url is not None

    if not url:
        return {"status": "NOT_LISTED", "price_eur": None, "language": None, "url": None}

    detail = fetch_product_page(session, url)
    time.sleep(rate_limit_sec)

    if matched_family:
        # Never compare this SKU's price against a different edition's listing -- still
        # surface url/price for transparency in the full results file, but the status (and
        # therefore the advantage verdict) reflects "family available", not a real price match.
        status = "FAMILY_LISTED_FR"
    elif detail["stock_status"] == "OUT_OF_STOCK":
        status = "LISTED_OUT_OF_STOCK"
    else:
        # IN_STOCK or UNKNOWN: treat as listed-in-stock if we got a price, since the primary
        # confirmed signal (a price on the page) means it's a real, purchasable listing even
        # when the stock-status container itself couldn't be confidently classified.
        status = "LISTED_IN_STOCK" if detail["price_eur"] else "NOT_LISTED"

    return {
        "status": status,
        "price_eur": detail["price_eur"],
        "language": detail["language"],
        "url": url,
        "stock_status_raw": detail["stock_status"],
    }


# Once a survivor has one of these, the underlying fact ("this product is really listed on
# Philibert at this URL") is durable -- a matching-precision fix to search_by_title/
# search_family_title can only ever find *more* real listings, never make a confirmed one stop
# existing, so it's safe to skip re-fetching these on a re-run. NOT_LISTED is deliberately
# excluded: that's exactly the state a matching-precision fix is meant to change, so it's always
# re-checked live rather than trusted from a stale cache.
_CACHEABLE_STATUSES = {"LISTED_IN_STOCK", "LISTED_OUT_OF_STOCK", "FAMILY_LISTED_FR"}


def _load_cached_results(path: str) -> dict[str, dict]:
    file = Path(path)
    if not file.exists():
        return {}
    try:
        payload = json.loads(file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {r["zatu_handle"]: r for r in payload.get("results", [])}


def _load_fr_editions(path: str) -> dict[str, dict]:
    file = Path(path)
    if not file.exists():
        return {}
    try:
        return json.loads(file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matched", default="data/matched_games.json")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--out", default="data/philibert_results.json")
    parser.add_argument("--shortlist-out", default="data/shortlist.json")
    parser.add_argument("--fr-editions", default="data/bgg_fr_editions.json")
    parser.add_argument("--rate-limit-sec", type=float, default=None)
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch every survivor live even if a durable cached result exists from a prior "
        "run at --out (default: reuse cached LISTED_IN_STOCK/LISTED_OUT_OF_STOCK/"
        "FAMILY_LISTED_FR results, always re-check NOT_LISTED survivors -- a matching fix is "
        "exactly what would change those).",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    rate_limit = args.rate_limit_sec
    if rate_limit is None:
        rate_limit = config.get("rate_limit_sec", {}).get("philibert", 1.0)

    payload = json.loads(Path(args.matched).read_text())
    survivors = payload["survivors"]
    cached_by_handle = {} if args.refresh else _load_cached_results(args.out)
    fr_editions = _load_fr_editions(args.fr_editions)
    print(
        f"Looking up {len(survivors)} survivors on Philibert "
        f"({len(cached_by_handle)} cached results available, "
        f"{len(fr_editions)} BGG French-edition checks available)...",
        file=sys.stderr,
    )

    session = make_session()
    fx = config["fx_gbp_eur"]
    threshold = config["discount_threshold"]
    weights = config["weights"]["advantage"]

    results = []
    verdict_counts: dict[str, int] = {}
    cache_hits = 0

    for i, survivor in enumerate(survivors, start=1):
        cached = cached_by_handle.get(survivor["zatu_handle"])
        if cached and cached.get("philibert_status") in _CACHEABLE_STATUSES:
            cache_hits += 1
            philibert = {
                "status": cached["philibert_status"],
                "price_eur": cached.get("philibert_price_eur"),
                "language": cached.get("philibert_language"),
                "url": cached.get("philibert_url"),
                "stock_status_raw": cached.get("philibert_stock_status_raw"),
            }
        else:
            try:
                philibert = lookup_one(session, survivor, rate_limit)
            except Exception as exc:  # noqa: BLE001 — one bad lookup must not kill the whole run
                print(f"  [{i}/{len(survivors)}] ERROR {survivor['zatu_handle']}: {exc}", file=sys.stderr)
                philibert = {"status": "NOT_LISTED", "price_eur": None, "language": None, "url": None}

        fr_edition_info = fr_editions.get(str(survivor.get("bgg_id")))
        advantage = compute_advantage(
            zatu_in_stock=bool(survivor.get("zatu_in_stock")),
            zatu_price_gbp=survivor.get("zatu_price_gbp"),
            philibert_status=philibert["status"],
            philibert_price_eur=philibert["price_eur"],
            fx_gbp_eur=fx,
            discount_threshold=threshold,
            weights=weights,
            fr_edition_exists=fr_edition_info.get("fr_edition_exists") if fr_edition_info else None,
        )

        record = {
            **survivor,
            "philibert_status": philibert["status"],
            "philibert_price_eur": philibert["price_eur"],
            "philibert_language": philibert["language"],
            "philibert_url": philibert["url"],
            "philibert_stock_status_raw": philibert.get("stock_status_raw"),
            "advantage_verdict": advantage.verdict,
            "advantage_points": advantage.points,
            "discount_pct": advantage.discount_pct,
            "needs_eyeball": advantage.needs_eyeball,
            "advantage_reason": advantage.reason,
        }
        results.append(record)
        verdict_counts[advantage.verdict] = verdict_counts.get(advantage.verdict, 0) + 1

        if i % 50 == 0 or i == len(survivors):
            print(f"  [{i}/{len(survivors)}] {verdict_counts}", file=sys.stderr)

    shortlist = [
        r
        for r in results
        if r["advantage_verdict"] not in (VERDICT_NONE, VERDICT_EXCLUDED, VERDICT_FAMILY_AVAILABLE_FR)
    ]
    print(f"Done: {len(results)} looked up ({cache_hits} from cache, "
          f"{len(results) - cache_hits} fetched live), {len(shortlist)} kept in the shortlist "
          f"({len(results) - len(shortlist)} removed: available in France at a similar price, "
          f"or excluded as UK-out-of-stock). {verdict_counts}", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"results": results}, indent=2))

    shortlist_path = Path(args.shortlist_out)
    shortlist_path.write_text(json.dumps({"shortlist": shortlist}, indent=2))

    print(f"Wrote {out_path} and {shortlist_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
