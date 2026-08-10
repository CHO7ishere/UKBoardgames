from pathlib import Path

import pytest

from match import BggIndex, _digits_conflict, normalize_title
from sources.bgg import filter_base_games, load_bg_ranks

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def base_games():
    games = load_bg_ranks(FIXTURES / "bg_ranks_sample.csv")
    return filter_base_games(games)  # drops the Branch & Claw expansion, 6 remain


@pytest.fixture
def index(base_games):
    return BggIndex(base_games)


# --- normalize_title ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Spirit Island", "spirit island"),
        ("Spirit Island (Core Game)", "spirit island"),
        ("Catan 2nd Edition", "catan"),
        ("Catan: Deluxe Edition", "catan"),
        ("The Mind", "mind"),
        ("Sea Salt & Paper", "sea salt and paper"),
        ("Brass: Birmingham", "brass birmingham"),
    ],
)
def test_normalize_title(title, expected):
    assert normalize_title(title) == expected


def test_normalize_title_strips_accents():
    assert normalize_title("Carcassonne: Amigos") == normalize_title("Carcassonné: Amigos")


# --- digit conflict veto ------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("pandemic legacy season 1", "pandemic legacy season 2", True),
        ("spirit island", "spirit island", False),
        ("catan", "catan junior", False),  # no digits on either side
        ("7 wonders duel", "7 wonders duel", False),  # same digit, no conflict
    ],
)
def test_digits_conflict(a, b, expected):
    assert _digits_conflict(a, b) is expected


# --- BggIndex.match: exact tier -----------------------------------------------------------


def test_exact_match_is_high_confidence(index):
    result = index.match("Spirit Island")
    assert result.confidence == "HIGH"
    assert result.bgg_id == 1
    assert result.score == 100.0


def test_exact_match_after_normalization(index):
    # "(Core Game)" gets stripped as noise -> exact match to "Spirit Island"
    result = index.match("Spirit Island (Core Game)")
    assert result.confidence == "HIGH"
    assert result.bgg_id == 1


def test_exact_match_distinguishes_similar_titles(index):
    # "Brass: Birmingham" vs "Brass: Lancashire" must not cross-match
    result = index.match("Brass: Birmingham")
    assert result.bgg_id == 2
    result2 = index.match("Brass: Lancashire")
    assert result2.bgg_id == 3


# --- BggIndex.match: fuzzy tier and the false-positive guards --------------------------------


def test_expansion_title_does_not_falsely_match_base_game(index):
    # "Spirit Island: Branch & Claw" was filtered out of the index (it's an expansion) —
    # must NOT fall through and fuzzy-match the base "Spirit Island" entry.
    result = index.match("Spirit Island: Branch & Claw")
    assert result.confidence == "LOW"
    assert result.bgg_id is None


def test_digit_conflict_blocks_wrong_season_match(index):
    # The index only has "Pandemic Legacy: Season 2" — querying "Season 1" must not be
    # accepted via fuzzy match just because the strings are ~96% similar.
    result = index.match("Pandemic Legacy: Season 1")
    assert result.confidence == "LOW"
    assert result.bgg_id is None
    assert "digit conflict" in result.reason


def test_fuzzy_match_accepts_close_typo(index):
    # rapidfuzz token_sort_ratio("gloomhaven jaws of the lion", "gloomhaven jaws of the lio")
    # should clear the threshold with no other close BGG candidate.
    result = index.match("Gloomhaven Jaws of the Lio")
    assert result.confidence == "MEDIUM"
    assert result.bgg_id == 5


def test_no_match_for_unrelated_title(index):
    result = index.match("Completely Unrelated Game Title")
    assert result.confidence == "LOW"
    assert result.bgg_id is None


def test_ambiguous_exact_match_is_dropped():
    # Two BGG entries that normalize to the same title -> ambiguous, must drop rather than
    # guess (spec P2: precision over recall).
    from sources.bgg import BggRankedGame

    dupes = [
        BggRankedGame(101, "Aftermath", 2020, 100, 7.0, 7.0, 500, False),
        BggRankedGame(102, "AFTERMATH!", 1998, 5000, 6.0, 6.0, 200, False),
    ]
    idx = BggIndex(dupes)
    result = idx.match("Aftermath")
    assert result.confidence == "LOW"
    assert "ambiguous" in result.reason


def test_empty_index_returns_low():
    idx = BggIndex([])
    result = idx.match("Anything")
    assert result.confidence == "LOW"
