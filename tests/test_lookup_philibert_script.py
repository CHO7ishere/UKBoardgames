import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import lookup_philibert  # noqa: E402

SURVIVOR_LISTED_CHEAPER = {
    "zatu_handle": "cheap-in-uk",
    "zatu_title": "Cheap In UK",
    "zatu_ean": "1111111111111",
    "zatu_price_gbp": 20.0,
    "zatu_in_stock": True,
}
SURVIVOR_SIMILAR_PRICE = {
    "zatu_handle": "similar-price",
    "zatu_title": "Similar Price Game",
    "zatu_ean": "2222222222222",
    "zatu_price_gbp": 45.0,
    "zatu_in_stock": True,
}
SURVIVOR_NOT_LISTED = {
    "zatu_handle": "not-listed",
    "zatu_title": "Not Listed Game",
    "zatu_ean": None,
    "zatu_price_gbp": 30.0,
    "zatu_in_stock": True,
}
SURVIVOR_UK_OUT_OF_STOCK = {
    "zatu_handle": "uk-oos",
    "zatu_title": "UK Out Of Stock Game",
    "zatu_ean": "3333333333333",
    "zatu_price_gbp": 25.0,
    "zatu_in_stock": False,
}

TEST_CONFIG = {
    "fx_gbp_eur": 1.0,
    "discount_threshold": 0.40,
    "weights": {
        "advantage": {
            "unavailable_fr": 40,
            "unavailable_fr_weak": 28,
            "out_of_stock_fr": 30,
            "cheaper_uk_base": 15,
        }
    },
    "rate_limit_sec": {"philibert": 0},
}


def fake_lookup_one(session, survivor, rate_limit_sec):
    if survivor["zatu_handle"] == "cheap-in-uk":
        return {"status": "LISTED_IN_STOCK", "price_eur": 100.0, "language": "Français", "url": "u1"}
    if survivor["zatu_handle"] == "similar-price":
        return {"status": "LISTED_IN_STOCK", "price_eur": 50.0, "language": "Français", "url": "u2"}
    if survivor["zatu_handle"] == "uk-oos":
        return {"status": "LISTED_IN_STOCK", "price_eur": 50.0, "language": "Français", "url": "u3"}
    return {"status": "NOT_LISTED", "price_eur": None, "language": None, "url": None}


def test_main_removes_similar_price_games_keeps_cheaper_and_not_listed(tmp_path, monkeypatch):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({
        "survivors": [
            SURVIVOR_LISTED_CHEAPER,
            SURVIVOR_SIMILAR_PRICE,
            SURVIVOR_NOT_LISTED,
            SURVIVOR_UK_OUT_OF_STOCK,
        ]
    }))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))

    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"

    monkeypatch.setattr(lookup_philibert, "lookup_one", fake_lookup_one)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lookup_philibert.py",
            "--matched",
            str(matched_file),
            "--config",
            str(config_file),
            "--out",
            str(out_file),
            "--shortlist-out",
            str(shortlist_file),
        ],
    )

    exit_code = lookup_philibert.main()

    assert exit_code == 0
    results = json.loads(out_file.read_text())["results"]
    shortlist = json.loads(shortlist_file.read_text())["shortlist"]

    by_handle = {r["zatu_handle"]: r for r in results}
    assert by_handle["cheap-in-uk"]["advantage_verdict"] == "CHEAPER_UK"
    assert by_handle["similar-price"]["advantage_verdict"] == "NONE"
    assert by_handle["not-listed"]["advantage_verdict"] == "UNAVAILABLE_FR"
    assert by_handle["uk-oos"]["advantage_verdict"] == "EXCLUDED"

    shortlist_handles = {r["zatu_handle"] for r in shortlist}
    assert shortlist_handles == {"cheap-in-uk", "not-listed"}
    assert "similar-price" not in shortlist_handles  # the actual removal the user asked for
    assert "uk-oos" not in shortlist_handles


def test_main_survives_a_lookup_error(tmp_path, monkeypatch, capsys):
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [SURVIVOR_LISTED_CHEAPER]}))
    config_file = tmp_path / "config.yaml"
    import yaml
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "results.json"
    shortlist_file = tmp_path / "shortlist.json"

    def flaky_lookup(session, survivor, rate_limit_sec):
        raise RuntimeError("simulated network error")

    monkeypatch.setattr(lookup_philibert, "lookup_one", flaky_lookup)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lookup_philibert.py",
            "--matched",
            str(matched_file),
            "--config",
            str(config_file),
            "--out",
            str(out_file),
            "--shortlist-out",
            str(shortlist_file),
        ],
    )

    exit_code = lookup_philibert.main()

    assert exit_code == 0
    results = json.loads(out_file.read_text())["results"]
    assert results[0]["philibert_status"] == "NOT_LISTED"  # safe fallback, not a crash
    assert "ERROR cheap-in-uk" in capsys.readouterr().err
