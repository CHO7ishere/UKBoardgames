import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import enrich_bgg_fr_edition  # noqa: E402

SURVIVOR_A = {"zatu_handle": "game-a", "zatu_title": "Game A", "bgg_id": 1}
SURVIVOR_B = {"zatu_handle": "game-b", "zatu_title": "Game B", "bgg_id": 2}
SURVIVOR_C = {"zatu_handle": "game-c", "zatu_title": "Game C", "bgg_id": 3}


# --- select_survivors_to_check (pure, no browser needed) --------------------------------------


def test_selects_brand_new_survivors_with_no_prior_philibert_record():
    to_check = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A], philibert_results=[], cache={}, refresh=False
    )
    assert to_check == [SURVIVOR_A]


def test_selects_survivors_that_were_not_listed_last_run():
    philibert_results = [{"zatu_handle": "game-a", "philibert_status": "NOT_LISTED"}]
    to_check = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A], philibert_results=philibert_results, cache={}, refresh=False
    )
    assert to_check == [SURVIVOR_A]


def test_skips_survivors_that_were_actually_listed_last_run():
    # fr_edition_exists is only read by compute_advantage's NOT_LISTED branch -- checking a
    # game Philibert already found live would be wasted browser time.
    philibert_results = [{"zatu_handle": "game-a", "philibert_status": "LISTED_IN_STOCK"}]
    to_check = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A], philibert_results=philibert_results, cache={}, refresh=False
    )
    assert to_check == []


def test_skips_survivors_whose_bgg_id_is_already_cached():
    to_check = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A], philibert_results=[], cache={"1": {"fr_edition_exists": True}}, refresh=False
    )
    assert to_check == []


def test_refresh_flag_rechecks_even_cached_survivors():
    to_check = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A], philibert_results=[], cache={"1": {"fr_edition_exists": True}}, refresh=True
    )
    assert to_check == [SURVIVOR_A]


def test_dedupes_multiple_zatu_skus_sharing_the_same_bgg_id():
    survivor_a2 = {"zatu_handle": "game-a-deluxe", "zatu_title": "Game A Deluxe", "bgg_id": 1}
    to_check = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A, survivor_a2], philibert_results=[], cache={}, refresh=False
    )
    assert len(to_check) == 1  # only checked once per bgg_id, not once per Zatu SKU


def test_mixed_selection_across_survivors():
    philibert_results = [
        {"zatu_handle": "game-a", "philibert_status": "LISTED_IN_STOCK"},  # skip
        {"zatu_handle": "game-b", "philibert_status": "NOT_LISTED"},  # check
        # game-c has no prior record at all -- check
    ]
    to_check = enrich_bgg_fr_edition.select_survivors_to_check(
        survivors=[SURVIVOR_A, SURVIVOR_B, SURVIVOR_C],
        philibert_results=philibert_results,
        cache={},
        refresh=False,
    )
    assert to_check == [SURVIVOR_B, SURVIVOR_C]


# --- main() end-to-end, browser mocked out -----------------------------------------------------


class _FakeChromium:
    def launch(self):
        return _FakeBrowser()


class _FakeBrowser:
    def new_context(self, **kwargs):
        return _FakeContext()

    def close(self):
        pass


class _FakeContext:
    def new_page(self):
        return object()  # never touched -- fetch_french_edition_info is monkeypatched


class _FakePlaywright:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def chromium(self):
        return _FakeChromium()


def test_main_writes_fr_edition_cache(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_A, SURVIVOR_B]}))
    philibert_file = tmp_path / "philibert_results.json"
    philibert_file.write_text(json.dumps({"results": []}))
    out_file = tmp_path / "bgg_fr_editions.json"

    def fake_fetch(page, bgg_id):
        return {"fr_edition_exists": bgg_id == 1, "fr_edition_titles": ["Le Jeu"] if bgg_id == 1 else []}

    monkeypatch.setattr(enrich_bgg_fr_edition, "sync_playwright", lambda: _FakePlaywright())
    monkeypatch.setattr(enrich_bgg_fr_edition, "fetch_french_edition_info", fake_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "enrich_bgg_fr_edition.py",
            "--matched", str(matched_file),
            "--philibert-results", str(philibert_file),
            "--out", str(out_file),
            "--rate-limit-sec", "0",
        ],
    )

    exit_code = enrich_bgg_fr_edition.main()

    assert exit_code == 0
    cache = json.loads(out_file.read_text())
    assert cache["1"]["fr_edition_exists"] is True
    assert cache["2"]["fr_edition_exists"] is False


def test_main_survives_a_fetch_error(tmp_path, monkeypatch, capsys):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_A]}))
    philibert_file = tmp_path / "philibert_results.json"
    philibert_file.write_text(json.dumps({"results": []}))
    out_file = tmp_path / "bgg_fr_editions.json"

    def flaky_fetch(page, bgg_id):
        raise RuntimeError("simulated navigation error")

    monkeypatch.setattr(enrich_bgg_fr_edition, "sync_playwright", lambda: _FakePlaywright())
    monkeypatch.setattr(enrich_bgg_fr_edition, "fetch_french_edition_info", flaky_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "enrich_bgg_fr_edition.py",
            "--matched", str(matched_file),
            "--philibert-results", str(philibert_file),
            "--out", str(out_file),
            "--rate-limit-sec", "0",
        ],
    )

    exit_code = enrich_bgg_fr_edition.main()

    assert exit_code == 0  # one bad page must not kill the run
    cache = json.loads(out_file.read_text())
    assert cache == {}
    assert "ERROR bgg_id=1" in capsys.readouterr().err


def test_main_preserves_existing_cache_entries_not_rechecked(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_A, SURVIVOR_B]}))
    philibert_file = tmp_path / "philibert_results.json"
    philibert_file.write_text(json.dumps({"results": [
        {"zatu_handle": "game-a", "philibert_status": "NOT_LISTED"},
        {"zatu_handle": "game-b", "philibert_status": "NOT_LISTED"},
    ]}))
    out_file = tmp_path / "bgg_fr_editions.json"
    out_file.write_text(json.dumps({"1": {"fr_edition_exists": True, "fr_edition_titles": ["Cached"]}}))

    calls = []

    def tracking_fetch(page, bgg_id):
        calls.append(bgg_id)
        return {"fr_edition_exists": False, "fr_edition_titles": []}

    monkeypatch.setattr(enrich_bgg_fr_edition, "sync_playwright", lambda: _FakePlaywright())
    monkeypatch.setattr(enrich_bgg_fr_edition, "fetch_french_edition_info", tracking_fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "enrich_bgg_fr_edition.py",
            "--matched", str(matched_file),
            "--philibert-results", str(philibert_file),
            "--out", str(out_file),
            "--rate-limit-sec", "0",
        ],
    )

    exit_code = enrich_bgg_fr_edition.main()

    assert exit_code == 0
    assert calls == [2]  # bgg_id=1 already cached, only bgg_id=2 gets fetched
    cache = json.loads(out_file.read_text())
    assert cache["1"] == {"fr_edition_exists": True, "fr_edition_titles": ["Cached"]}
    assert cache["2"]["fr_edition_exists"] is False
