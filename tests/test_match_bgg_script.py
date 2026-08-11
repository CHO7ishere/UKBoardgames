import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import match_bgg  # noqa: E402

from sources.bgg import filter_base_games, load_bg_ranks  # noqa: E402
from sources.zatu import parse_product  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

TEST_CONFIG = {
    "quality": {"shrink_M": 100, "prior": 6.5, "min_shrunk": 7.2, "min_votes": 30},
    "matching": {"fuzzy_threshold": 90, "min_score_gap": 5},
    "include_expansions": False,
}


def _zatu_products():
    # match_bgg.run() expects harvested-shape dicts (ZatuProduct.to_dict()), not the raw
    # Shopify products.json shape the fixture stores — same transform Stage 0's harvest does.
    payload = json.loads((FIXTURES / "zatu_products_page1.json").read_text())
    return [parse_product(p).to_dict() for p in payload["products"]]


def _bgg_games():
    games = load_bg_ranks(FIXTURES / "bg_ranks_sample.csv")
    return filter_base_games(games, include_expansions=False)


def test_run_produces_expected_survivors_and_drops():
    survivors, dropped, unmatched = match_bgg.run(_zatu_products(), _bgg_games(), TEST_CONFIG)

    survivor_handles = {s["zatu_handle"] for s in survivors}
    assert survivor_handles == {"gloomhaven-jaws-of-the-lion", "brass-birmingham"}

    dropped_handles = {d["zatu_handle"] for d in dropped}
    assert dropped_handles == {
        "manipulate",  # matched fine, failed quality gate
        "the-mind-dice-set",  # no BGG candidate
        "wooden-meeple-set",  # no BGG candidate
    }

    # Both of this fixture's LOW_CONFIDENCE_MATCH drops are themselves real accessories
    # ("the-mind-dice-set" by title keyword, "wooden-meeple-set" by product_type ==
    # "Accessories") -- correctly kept out of the unmatched-games list, which is for real,
    # unscored *games* a human might want to eyeball, not spare parts. See
    # test_run_unmatched_carries_zatu_fields_and_category for a real, non-accessory case.
    unmatched_handles = {u["zatu_handle"] for u in unmatched}
    assert unmatched_handles == set()


def test_run_survivor_carries_zatu_and_bgg_fields():
    survivors, _, _ = match_bgg.run(_zatu_products(), _bgg_games(), TEST_CONFIG)
    brass = next(s for s in survivors if s["zatu_handle"] == "brass-birmingham")
    assert brass["bgg_id"] == 2
    assert brass["bgg_name"] == "Brass: Birmingham"
    assert brass["zatu_price_gbp"] == 54.99
    assert brass["match_confidence"] == "HIGH"
    assert brass["quality_label"] == "EXCELLENT"
    assert brass["zatu_is_coop"] is False
    assert brass["zatu_is_party"] is False
    assert brass["zatu_tags"] == ["Strategy"]


def test_run_derives_coop_from_tags_even_without_is_coop_dict_keys():
    # Regression: the real committed data/zatu_products.json has no "is_coop"/"is_party" keys
    # at all (only "tags") -- product.get("is_coop") used to silently return None for every
    # survivor. Simulate that exact shape here rather than the richer ZatuProduct.to_dict()
    # fixture shape the other tests use.
    products = [
        {
            "handle": "gloomhaven-jaws-of-the-lion",
            "title": "Gloomhaven: Jaws of the Lion",
            "url": "https://zatu.com/products/gloomhaven-jaws-of-the-lion",
            "tags": ["Cooperative Play", "Legacy"],
            "min_price_gbp": 34.99,
            "in_stock": True,
            "ean": None,
        }
    ]
    survivors, _, _ = match_bgg.run(products, _bgg_games(), TEST_CONFIG)
    assert len(survivors) == 1
    assert survivors[0]["zatu_is_coop"] is True
    assert survivors[0]["zatu_is_party"] is False


def test_run_drop_reason_distinguishes_match_vs_quality_failure():
    _, dropped, _ = match_bgg.run(_zatu_products(), _bgg_games(), TEST_CONFIG)
    by_handle = {d["zatu_handle"]: d for d in dropped}
    assert by_handle["manipulate"]["reason"].startswith("QUALITY_GATE")
    assert by_handle["the-mind-dice-set"]["reason"].startswith("LOW_CONFIDENCE_MATCH")


def test_run_unmatched_carries_zatu_fields_and_category():
    # A real, unscored game (unlike this fixture's two accessory drops): no title anywhere near
    # bg_ranks_sample.csv's 7 games, and product_type "Board Games" so it isn't filtered out as
    # an accessory the way the-mind-dice-set/wooden-meeple-set are.
    products = _zatu_products() + [
        {
            "handle": "totally-obscure-game",
            "title": "Totally Obscure Game Nobody Has Heard Of",
            "url": "https://zatu.com/products/totally-obscure-game",
            "product_type": "Board Games",
            "tags": ["Party Games"],
            "min_price_gbp": 12.5,
            "in_stock": True,
            "ean": None,
        }
    ]
    _, _, unmatched = match_bgg.run(products, _bgg_games(), TEST_CONFIG)
    obscure = next(u for u in unmatched if u["zatu_handle"] == "totally-obscure-game")
    assert obscure["zatu_title"] == "Totally Obscure Game Nobody Has Heard Of"
    assert obscure["zatu_price_gbp"] == 12.5
    assert obscure["zatu_is_party"] is True
    assert obscure["match_category"] == "NO_CONFIDENT_MATCH"
    assert isinstance(obscure["bgg_candidates"], list)


def test_main_end_to_end(tmp_path, monkeypatch):
    # match_bgg.py's CLI expects Stage 0's harvested-shape JSON on disk, not the raw
    # products.json fixture -- write a converted copy, same as a real harvest would produce.
    zatu_file = tmp_path / "zatu_products.json"
    zatu_file.write_text(json.dumps({"products": _zatu_products()}))

    out_file = tmp_path / "matched.json"
    dropped_file = tmp_path / "dropped.csv"
    unmatched_file = tmp_path / "unmatched.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "match_bgg.py",
            "--zatu",
            str(zatu_file),
            "--bgg-ranks",
            str(FIXTURES / "bg_ranks_sample.csv"),
            "--config",
            "config.yaml",
            "--out",
            str(out_file),
            "--dropped-out",
            str(dropped_file),
            "--unmatched-out",
            str(unmatched_file),
        ],
    )

    exit_code = match_bgg.main()

    assert exit_code == 0
    payload = json.loads(out_file.read_text())
    assert len(payload["survivors"]) == 2
    assert dropped_file.exists()
    assert "QUALITY_GATE" in dropped_file.read_text()
    unmatched_payload = json.loads(unmatched_file.read_text())
    assert unmatched_payload["unmatched"] == []


def test_main_errors_loudly_when_bg_ranks_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["match_bgg.py", "--bgg-ranks", str(tmp_path / "does-not-exist.csv")],
    )

    exit_code = match_bgg.main()

    assert exit_code == 1
    assert "not found" in capsys.readouterr().err
