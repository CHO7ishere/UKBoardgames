import pytest

from score import evaluate_quality, quality_label, quality_points, shrunk_rating
from sources.bgg import BggRankedGame


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
