import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import render_html as render_html_script  # noqa: E402

TEST_CONFIG = {"fx_gbp_eur": 1.17, "discount_threshold": 0.40}

GAME = {
    "zatu_handle": "test-game",
    "zatu_title": "Test Game",
    "zatu_url": "https://zatu.com/products/test-game",
    "zatu_price_gbp": 39.99,
    "zatu_is_coop": True,
    "zatu_is_party": False,
    "bgg_id": 1,
    "bgg_year": 2021,
    "bgg_average": 8.2,
    "bgg_usersrated": 3400,
    "quality_shrunk": 8.05,
    "quality_pts": 40.0,
    "quality_label": "EXCELLENT",
    "philibert_status": "NOT_LISTED",
    "philibert_price_eur": None,
    "philibert_url": None,
    "advantage_verdict": "UNAVAILABLE_FR",
    "advantage_reason": "not sold in france",
    "discount_pct": None,
    "match_confidence": "HIGH",
    "needs_eyeball": True,
    "genre_points": 12,
    "language_points": -3,
    "language_unknown": True,
    "composite_score": 77.0,
}


def test_main_renders_html_file(tmp_path, monkeypatch):
    scored_file = tmp_path / "scored.json"
    scored_file.write_text(json.dumps({"games": [GAME]}))
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "index.html"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "render_html.py",
            "--scored",
            str(scored_file),
            "--config",
            str(config_file),
            "--zatu-products",
            str(tmp_path / "missing_zatu.json"),
            "--matched",
            str(tmp_path / "missing_matched.json"),
            "--unmatched",
            str(tmp_path / "missing_unmatched.json"),
            "--out",
            str(out_file),
        ],
    )

    exit_code = render_html_script.main()

    assert exit_code == 0
    html = out_file.read_text()
    assert "Test Game" in html
    assert "1 games matched your criteria" in html
    assert "Not matched to BGG (0 games)" in html


def test_main_includes_unmatched_games_when_file_present(tmp_path, monkeypatch):
    scored_file = tmp_path / "scored.json"
    scored_file.write_text(json.dumps({"games": [GAME]}))
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(TEST_CONFIG))
    unmatched_file = tmp_path / "unmatched.json"
    unmatched_file.write_text(
        json.dumps(
            {
                "unmatched": [
                    {
                        "zatu_handle": "obscure-game",
                        "zatu_title": "Obscure Game",
                        "zatu_url": "https://zatu.com/products/obscure-game",
                        "zatu_price_gbp": 9.99,
                        "zatu_in_stock": True,
                        "zatu_is_coop": False,
                        "zatu_is_party": False,
                        "zatu_tags": [],
                        "match_category": "NO_CONFIDENT_MATCH",
                        "bgg_candidates": [],
                        "match_score": None,
                    }
                ]
            }
        )
    )
    out_file = tmp_path / "index.html"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "render_html.py",
            "--scored",
            str(scored_file),
            "--config",
            str(config_file),
            "--zatu-products",
            str(tmp_path / "missing_zatu.json"),
            "--matched",
            str(tmp_path / "missing_matched.json"),
            "--unmatched",
            str(unmatched_file),
            "--out",
            str(out_file),
        ],
    )

    exit_code = render_html_script.main()

    assert exit_code == 0
    html = out_file.read_text()
    assert "Obscure Game" in html
    assert "Not matched to BGG (1 games)" in html


def test_main_bakes_in_excluded_handles_when_file_present(tmp_path, monkeypatch):
    scored_file = tmp_path / "scored.json"
    scored_file.write_text(json.dumps({"games": [GAME]}))
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(TEST_CONFIG))
    excluded_file = tmp_path / "excluded.json"
    excluded_file.write_text(json.dumps({"excluded_handles": ["test-game"]}))
    out_file = tmp_path / "index.html"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "render_html.py",
            "--scored",
            str(scored_file),
            "--config",
            str(config_file),
            "--zatu-products",
            str(tmp_path / "missing_zatu.json"),
            "--matched",
            str(tmp_path / "missing_matched.json"),
            "--unmatched",
            str(tmp_path / "missing_unmatched.json"),
            "--excluded",
            str(excluded_file),
            "--out",
            str(out_file),
        ],
    )

    exit_code = render_html_script.main()

    assert exit_code == 0
    html = out_file.read_text()
    assert 'data-user_excluded="1"' in html


def test_load_excluded_handles_defaults_to_empty_set_when_file_missing(tmp_path):
    assert render_html_script.load_excluded_handles(str(tmp_path / "missing.json")) == set()


def test_load_excluded_handles_reads_real_file(tmp_path):
    excluded_file = tmp_path / "excluded.json"
    excluded_file.write_text(json.dumps({"excluded_handles": ["a", "b"]}))
    assert render_html_script.load_excluded_handles(str(excluded_file)) == {"a", "b"}


def test_build_run_metadata_counts_are_none_when_files_missing(tmp_path):
    metadata = render_html_script.build_run_metadata(
        TEST_CONFIG, str(tmp_path / "missing1.json"), str(tmp_path / "missing2.json")
    )
    assert metadata["zatu_products_count"] is None
    assert metadata["stage2_survivors_count"] is None
    assert metadata["fx_gbp_eur"] == 1.17


def test_build_run_metadata_counts_real_files(tmp_path):
    zatu_file = tmp_path / "zatu.json"
    zatu_file.write_text(json.dumps({"products": [{}, {}, {}]}))
    matched_file = tmp_path / "matched.json"
    matched_file.write_text(json.dumps({"survivors": [{}, {}]}))

    metadata = render_html_script.build_run_metadata(TEST_CONFIG, str(zatu_file), str(matched_file))
    assert metadata["zatu_products_count"] == 3
    assert metadata["stage2_survivors_count"] == 2
