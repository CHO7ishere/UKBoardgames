import pytest

from score import (
    composite_score,
    evaluate_quality,
    genre_points,
    language_points,
    quality_label,
    quality_points,
    shrunk_rating,
)
from sources.bgg import BggRankedGame

GENRE_WEIGHTS = {"coop": 12, "party": 12}
LANGUAGE_WEIGHTS = {"low": 10, "med": 0, "high": -15, "unknown": -3}


def _game(average, usersrated):
    return BggRankedGame(1, "Test Game", 2020, 100, average, average, usersrated, False)


def test_shrunk_rating_pulls_low_votes_toward_prior():
    # 8.4-rated game with only 60 votes (well under M=100) should land closer to the 6.5
    # prior than to its raw average.
    shrunk = shrunk_rating(average=8.4, usersrated=60, shrink_m=100, prior=6.5)
    assert 6.5 < shrunk < 7.5


def test_shrunk_rating_barely_moves_with_many_votes():
    shrunk = shrunk_rating(average=8.4, usersrated=6000, shrink_m=100, prior=6.5)
    assert shrunk == pytest.approx(8.37, abs=0.01)


def test_shrunk_rating_matches_formula_exactly():
    # spec §5.1's own worked example text ("lands near 7.7") is an imprecise illustration —
    # plugging its own stated numbers into its own stated formula gives 7.2125, confirmed here
    # against the literal formula rather than the prose approximation.
    shrunk = shrunk_rating(average=8.4, usersrated=60, shrink_m=100, prior=6.5)
    assert shrunk == pytest.approx(7.2125, abs=0.0001)


def test_quality_points_clamped_to_zero_below_min_shrunk():
    assert quality_points(shrunk=5.0, min_shrunk=7.2) == 0.0


def test_quality_points_clamped_to_max_at_ceiling():
    assert quality_points(shrunk=9.0, min_shrunk=7.2) == 45.0


def test_quality_points_midpoint():
    # (7.9 - 7.2) / (8.6 - 7.2) = 0.5 -> 22.5 pts
    assert quality_points(shrunk=7.9, min_shrunk=7.2) == pytest.approx(22.5)


def test_evaluate_quality_passes_gate():
    game = _game(average=8.4, usersrated=60000)
    result = evaluate_quality(game)
    assert result.passes_gate is True
    assert result.quality_pts == pytest.approx(38.47, abs=0.1)


def test_evaluate_quality_fails_gate_on_low_shrunk():
    # Manipulate-like: average 6.5, only 45 votes -> shrunk stays near 6.5, well under 7.2
    game = _game(average=6.5, usersrated=45)
    result = evaluate_quality(game)
    assert result.passes_gate is False
    assert result.quality_pts == 0.0


def test_evaluate_quality_fails_gate_on_low_votes_even_with_high_rating():
    # High average but under the 30-vote floor -> gate fails regardless of shrunk value
    game = _game(average=9.0, usersrated=10)
    result = evaluate_quality(game)
    assert result.passes_gate is False


@pytest.mark.parametrize(
    "average,usersrated,expected",
    [
        (8.5, 500, "EXCELLENT"),
        (7.6, 500, "STRONG"),
        (8.5, 50, "UNPROVEN"),
        (7.6, 50, "BORDERLINE"),
        (6.0, 500, "UNLABELED"),
    ],
)
def test_quality_label_bands(average, usersrated, expected):
    assert quality_label(average, usersrated) == expected


# --- genre_points --------------------------------------------------------------------------


def test_genre_points_coop_and_party_stack():
    assert genre_points(is_coop=True, is_party=True, weights=GENRE_WEIGHTS) == 24


def test_genre_points_coop_only():
    assert genre_points(is_coop=True, is_party=False, weights=GENRE_WEIGHTS) == 12


def test_genre_points_neither():
    assert genre_points(is_coop=False, is_party=False, weights=GENRE_WEIGHTS) == 0


def test_genre_points_unknown_is_not_a_penalty():
    # None (signal unavailable) must score the same as False, not a negative.
    assert genre_points(is_coop=None, is_party=None, weights=GENRE_WEIGHTS) == 0


# --- language_points ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "level,expected_pts,expected_unknown",
    [
        ("LOW", 10, False),
        ("MED", 0, False),
        ("HIGH", -15, False),
        (None, -3, True),
    ],
)
def test_language_points(level, expected_pts, expected_unknown):
    pts, is_unknown = language_points(level, weights=LANGUAGE_WEIGHTS)
    assert pts == expected_pts
    assert is_unknown is expected_unknown


# --- composite_score -------------------------------------------------------------------------


def test_composite_score_sums_all_four_components():
    assert composite_score(advantage_pts=40, quality_pts=45, genre_pts=24, language_pts=10) == 119


def test_composite_score_handles_negative_language_penalty():
    assert composite_score(advantage_pts=28, quality_pts=18.38, genre_pts=0, language_pts=-3) == pytest.approx(43.38)
