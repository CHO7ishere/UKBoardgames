import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import enrich_bgg_fr_edition  # noqa: E402

SURVIVOR_A = {"zatu_handle": "game-a", "zatu_title": "Game A", "bgg_id": 1}
SURVIVOR_B = {"zatu_handle": "game-b", "zatu_title": "Game B", "bgg_id": 2}
SURVIVOR_C = {"zatu_handle": "game-c", "zatu_title": "Game C", "bgg_id": 3}


# --- select_survivors_to_check (pure, no network needed) --------------------------------------
#
# language_level is read for every scored row (unlike fr_edition_exists, only read for
# NOT_LISTED-on-Philibert survivors) -- 2026-08-11: selection scope widened from "NOT_LISTED or
# brand new" to "any bgg_id not yet fully cached" (i.e. missing language_level), since both
# fields come from the same batched API request and there's no cost reason to gate on Philibert
# status.


def test_selects_brand_new_survivors_with_no_prior_cache_entry():
    to_check, unmatched_ids = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A], philibert_results=[], cache={}, refresh=False
    )
    assert to_check == [SURVIVOR_A]
    assert unmatched_ids == []


def test_skips_survivors_whose_bgg_id_is_fully_cached():
    to_check, _ = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A], philibert_results=[],
        cache={"1": {"fr_edition_exists": True, "language_level": "LOW"}}, refresh=False,
    )
    assert to_check == []


def test_rechecks_a_cached_bgg_id_missing_language_level():
    # An entry cached before language-dependence scraping landed (or one that hasn't been
    # backfilled yet) has fr_edition_exists but no language_level key at all -- still needs a
    # visit, even though fr_edition_exists is already known.
    to_check, _ = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A], philibert_results=[],
        cache={"1": {"fr_edition_exists": True, "fr_edition_titles": []}}, refresh=False,
    )
    assert to_check == [SURVIVOR_A]


def test_refresh_flag_rechecks_even_fully_cached_survivors():
    to_check, _ = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A], philibert_results=[],
        cache={"1": {"fr_edition_exists": True, "language_level": "LOW"}}, refresh=True,
    )
    assert to_check == [SURVIVOR_A]


def test_dedupes_multiple_zatu_skus_sharing_the_same_bgg_id():
    survivor_a2 = {"zatu_handle": "game-a-deluxe", "zatu_title": "Game A Deluxe", "bgg_id": 1}
    to_check, _ = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A, survivor_a2], philibert_results=[], cache={}, refresh=False
    )
    assert len(to_check) == 1  # only checked once per bgg_id, not once per Zatu SKU


def test_mixed_selection_across_survivors():
    to_check, _ = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A, SURVIVOR_B, SURVIVOR_C],
        philibert_results=[],
        cache={"1": {"fr_edition_exists": True, "language_level": "LOW"}},  # fully cached, skip
        refresh=False,
    )
    assert to_check == [SURVIVOR_B, SURVIVOR_C]


# --- main() end-to-end, sources.bgg_api.fetch_things mocked out -------------------------------


def _item(bgg_id, fr_exists=False, fr_titles=None, language_level=None, language_votes=None, **extra):
    return {
        "bgg_id": bgg_id,
        "name": f"Game {bgg_id}",
        "fr_edition_exists": fr_exists,
        "fr_edition_titles": fr_titles or [],
        "language_level": language_level,
        "language_votes": language_votes or {},
        **extra,
    }


def _fake_stats(batches=1, items_returned=0, retries_202=0, errors=None):
    from sources.bgg_api import FetchStats

    return FetchStats(
        batches=batches, items_returned=items_returned, retries_202=retries_202,
        errors=errors or [],
    )


def test_main_requires_bgg_token(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": []}))
    monkeypatch.delenv("BGG_TOKEN", raising=False)
    monkeypatch.setattr(
        sys, "argv",
        ["enrich_bgg_fr_edition.py", "--matched", str(matched_file), "--rate-limit-sec", "0"],
    )

    exit_code = enrich_bgg_fr_edition.main()

    assert exit_code == 1


def test_main_writes_fr_edition_cache_and_full_details(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_A, SURVIVOR_B]}))
    philibert_file = tmp_path / "philibert_results.json"
    philibert_file.write_text(json.dumps({"results": []}))
    out_file = tmp_path / "bgg_fr_editions.json"
    details_file = tmp_path / "bgg_details.json"

    def fake_fetch_things(session, ids, token, rate_limit_sec=5.0, **kw):
        assert token == "fake-token"
        items = [
            _item(1, fr_exists=True, fr_titles=["Le Jeu"], language_level="LOW", mechanics=["X"]),
            _item(2, fr_exists=False),
        ]
        return items, _fake_stats(items_returned=len(items))

    monkeypatch.setenv("BGG_TOKEN", "fake-token")
    monkeypatch.setattr(enrich_bgg_fr_edition, "fetch_things", fake_fetch_things)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "enrich_bgg_fr_edition.py",
            "--matched", str(matched_file),
            "--philibert-results", str(philibert_file),
            "--out", str(out_file),
            "--details-out", str(details_file),
            "--rate-limit-sec", "0",
        ],
    )

    exit_code = enrich_bgg_fr_edition.main()

    assert exit_code == 0
    cache = json.loads(out_file.read_text())
    assert cache["1"]["fr_edition_exists"] is True
    assert cache["1"]["language_level"] == "LOW"
    assert cache["2"]["fr_edition_exists"] is False
    # the narrow cache only carries the four fields lookup_philibert.py/score_games.py read
    assert set(cache["1"].keys()) == {
        "fr_edition_exists", "fr_edition_titles", "language_level", "language_votes",
    }

    details = json.loads(details_file.read_text())
    assert details["1"]["name"] == "Game 1"
    assert details["1"]["mechanics"] == ["X"]  # the "full answer" survives, not just the narrow fields


def test_main_survives_errors_reported_by_fetch_things(tmp_path, monkeypatch, capsys):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_A]}))
    philibert_file = tmp_path / "philibert_results.json"
    philibert_file.write_text(json.dumps({"results": []}))
    out_file = tmp_path / "bgg_fr_editions.json"
    details_file = tmp_path / "bgg_details.json"

    def fake_fetch_things(session, ids, token, rate_limit_sec=5.0, **kw):
        return [], _fake_stats(items_returned=0, errors=["ids=[1]: simulated network error"])

    monkeypatch.setenv("BGG_TOKEN", "fake-token")
    monkeypatch.setattr(enrich_bgg_fr_edition, "fetch_things", fake_fetch_things)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "enrich_bgg_fr_edition.py",
            "--matched", str(matched_file),
            "--philibert-results", str(philibert_file),
            "--out", str(out_file),
            "--details-out", str(details_file),
            "--rate-limit-sec", "0",
        ],
    )

    exit_code = enrich_bgg_fr_edition.main()

    assert exit_code == 0  # one bad batch must not kill the run
    cache = json.loads(out_file.read_text())
    assert cache == {}
    assert "simulated network error" in capsys.readouterr().err


def test_main_preserves_existing_cache_entries_not_rechecked(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_A, SURVIVOR_B]}))
    philibert_file = tmp_path / "philibert_results.json"
    philibert_file.write_text(json.dumps({"results": [
        {"zatu_handle": "game-a", "philibert_status": "NOT_LISTED"},
        {"zatu_handle": "game-b", "philibert_status": "NOT_LISTED"},
    ]}))
    out_file = tmp_path / "bgg_fr_editions.json"
    out_file.write_text(json.dumps({
        "1": {"fr_edition_exists": True, "fr_edition_titles": ["Cached"], "language_level": "MED", "language_votes": {}},
    }))
    details_file = tmp_path / "bgg_details.json"

    calls = []

    def fake_fetch_things(session, ids, token, rate_limit_sec=5.0, **kw):
        calls.extend(ids)
        items = [_item(bgg_id, fr_exists=False) for bgg_id in ids]
        return items, _fake_stats(items_returned=len(items))

    monkeypatch.setenv("BGG_TOKEN", "fake-token")
    monkeypatch.setattr(enrich_bgg_fr_edition, "fetch_things", fake_fetch_things)
    unmatched_file = tmp_path / "unmatched_bgg_ids.json"
    unmatched_file.write_text(json.dumps({"unmatched_mappings": {}}))  # Empty, no unmatched games

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "enrich_bgg_fr_edition.py",
            "--matched", str(matched_file),
            "--philibert-results", str(philibert_file),
            "--out", str(out_file),
            "--details-out", str(details_file),
            "--unmatched-bgg-ids", str(unmatched_file),
            "--rate-limit-sec", "0",
        ],
    )

    exit_code = enrich_bgg_fr_edition.main()

    assert exit_code == 0
    assert calls == [2]  # bgg_id=1 is fully cached (has language_level), only bgg_id=2 gets fetched
    cache = json.loads(out_file.read_text())
    assert cache["1"] == {"fr_edition_exists": True, "fr_edition_titles": ["Cached"], "language_level": "MED", "language_votes": {}}
    assert cache["2"]["fr_edition_exists"] is False


def test_main_refresh_flag_rechecks_everything(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_A]}))
    philibert_file = tmp_path / "philibert_results.json"
    philibert_file.write_text(json.dumps({"results": []}))
    out_file = tmp_path / "bgg_fr_editions.json"
    out_file.write_text(json.dumps({
        "1": {"fr_edition_exists": True, "fr_edition_titles": ["Stale"], "language_level": "MED", "language_votes": {}},
    }))
    details_file = tmp_path / "bgg_details.json"

    calls = []

    def fake_fetch_things(session, ids, token, rate_limit_sec=5.0, **kw):
        calls.extend(ids)
        items = [_item(1, fr_exists=False, language_level="LOW")]
        return items, _fake_stats(items_returned=1)

    unmatched_file = tmp_path / "unmatched_bgg_ids.json"
    unmatched_file.write_text(json.dumps({"unmatched_mappings": {}}))  # Empty, no unmatched games

    monkeypatch.setenv("BGG_TOKEN", "fake-token")
    monkeypatch.setattr(enrich_bgg_fr_edition, "fetch_things", fake_fetch_things)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "enrich_bgg_fr_edition.py",
            "--matched", str(matched_file),
            "--philibert-results", str(philibert_file),
            "--out", str(out_file),
            "--details-out", str(details_file),
            "--unmatched-bgg-ids", str(unmatched_file),
            "--rate-limit-sec", "0",
            "--refresh",
        ],
    )

    exit_code = enrich_bgg_fr_edition.main()

    assert exit_code == 0
    assert calls == [1]  # --refresh forces a re-check despite the existing cache entry
    cache = json.loads(out_file.read_text())
    assert cache["1"]["fr_edition_exists"] is False  # fresh value, not the stale cached one
