import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import score_games  # noqa: E402

TEST_CONFIG = {
    "weights": {
        "genre": {"coop": 12, "party": 12},
        "language": {"low": 10, "med": 0, "high": -15, "unknown": -3},
    }
}

GAME_HIGH_SCORE = {
    "zatu_handle": "high-score-game",
    "advantage_points": 40,
    "quality_pts": 45,
    "zatu_is_coop": True,
    "zatu_is_party": False,
}
GAME_LOW_SCORE = {
    "zatu_handle": "low-score-game",
    "advantage_points": 15,
    "quality_pts": 5,
    "zatu_is_coop": None,
    "zatu_is_party": None,
}


def test_score_one_computes_genre_and_language_and_composite():
    scored = score_games.score_one(GAME_HIGH_SCORE, TEST_CONFIG["weights"])
    assert scored["genre_points"] == 12  # coop only
    assert scored["language_points"] == -3  # unknown, no Stage 3 data yet
    assert scored["language_unknown"] is True
    assert scored["composite_score"] == 40 + 45 + 12 - 3


def test_score_one_treats_unset_genre_signal_as_no_bonus_not_a_penalty():
    scored = score_games.score_one(GAME_LOW_SCORE, TEST_CONFIG["weights"])
    assert scored["genre_points"] == 0
    assert scored["composite_score"] == 15 + 5 + 0 - 3


def test_main_sorts_by_composite_score_descending(tmp_path, monkeypatch):
    shortlist_file = tmp_path / "shortlist.json"
    shortlist_file.write_text(json.dumps({"shortlist": [GAME_LOW_SCORE, GAME_HIGH_SCORE]}))
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(TEST_CONFIG))
    out_file = tmp_path / "scored.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "score_games.py",
            "--shortlist",
            str(shortlist_file),
            "--config",
            str(config_file),
            "--out",
            str(out_file),
        ],
    )

    exit_code = score_games.main()

    assert exit_code == 0
    games = json.loads(out_file.read_text())["games"]
    assert [g["zatu_handle"] for g in games] == ["high-score-game", "low-score-game"]
