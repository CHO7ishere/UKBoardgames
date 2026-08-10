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
        ("Heroes of Land, Air &amp; Sea", "heroes of land air and sea"),
        ("Pandemic (2013)", "pandemic"),
        ("CATAN 6th Edition (2025)", "catan"),
        ("The Great Fire of London 1666 (2017)", "great fire of london 1666"),
        ("Munchkin Warhammer 40000", "munchkin warhammer 40000"),
        ("Warhammer 40,000: Conquest", "warhammer 40000 conquest"),
        # "core" alone must survive when it's not part of the "core game" phrase — it used to
        # be stripped unconditionally, silently mangling "Core Set" into "set".
        ("Company of Heroes: 2nd Edition Core Set", "company of heroes core set"),
        # Real miss: stripping the noise phrase "board game" out of "...: The Board Game" used
        # to leave a dangling "the" behind that a leading-only article strip couldn't reach.
        ("Slay the Spire: The Board Game", "slay spire"),
    ],
)
def test_normalize_title(title, expected):
    assert normalize_title(title) == expected


def test_normalize_title_strips_accents():
    assert normalize_title("Carcassonne: Amigos") == normalize_title("Carcassonné: Amigos")


def test_normalize_title_does_not_strip_a_year_thats_part_of_the_name():
    # "1666" is the actual game name, not a trailing release-year annotation -> must survive.
    assert "1666" in normalize_title("The Great Fire of London 1666")


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


def test_comma_formatted_number_matches_unpunctuated_zatu_title():
    # Real false-negative found against production data: BGG's "Warhammer 40,000" vs Zatu's
    # "Warhammer 40000" used to trip the digit-conflict veto because the comma split "40,000"
    # into two separate digit tokens ("40", "000") instead of one ("40000").
    from sources.bgg import BggRankedGame

    games = [BggRankedGame(201, "Warhammer 40,000: Conquest", 2017, 300, 6.5, 6.5, 1000, False)]
    idx = BggIndex(games)
    result = idx.match("Warhammer 40000 Conquest")
    assert result.confidence == "HIGH"
    assert result.bgg_id == 201


def test_trailing_release_year_does_not_block_match():
    # Real false-negative: Zatu's "Pandemic (2013)" against BGG's plain "Pandemic" used to
    # trip the digit-conflict veto on the stray "2013".
    from sources.bgg import BggRankedGame

    games = [BggRankedGame(301, "Pandemic", 2008, 10, 7.5, 7.6, 100000, False)]
    idx = BggIndex(games)
    result = idx.match("Pandemic (2013)")
    assert result.confidence == "HIGH"
    assert result.bgg_id == 301


# --- BggIndex.match: prefix tier (fallback after fuzzy fails) ----------------------------------


def test_unique_prefix_match_is_accepted():
    # Real false-negative: Zatu lists this as just "Five Tribes"; BGG's actual title has a
    # subtitle. Fuzzy alone (dropping most of the title) scores too low to accept.
    from sources.bgg import BggRankedGame

    games = [BggRankedGame(401, "Five Tribes: The Djinns of Naqala", 2014, 40, 7.8, 7.9, 40000, False)]
    idx = BggIndex(games)
    result = idx.match("Five Tribes")
    assert result.confidence == "MEDIUM"
    assert result.bgg_id == 401
    assert "prefix" in result.reason


def test_ambiguous_prefix_match_is_dropped():
    # Real case: "Suspects" is a prefix of 14 different "Suspects: <subtitle>" BGG entries —
    # genuinely ambiguous, must not guess one.
    from sources.bgg import BggRankedGame

    games = [
        BggRankedGame(501, "Suspects: Claire Harper Takes the Stage", 2022, 500, 7.0, 7.0, 300, False),
        BggRankedGame(502, "Suspects: Adele and Neville", 2023, 600, 7.0, 7.0, 300, False),
    ]
    idx = BggIndex(games)
    result = idx.match("Suspects")
    assert result.confidence == "LOW"
    assert result.bgg_id is None
    assert "ambiguous" in result.reason


def test_prefix_tier_does_not_override_a_successful_fuzzy_match():
    # If fuzzy already found a confident match, the prefix fallback must never be consulted —
    # confirmed here via a title that both fuzzy-matches one game AND is a substring-prefix of
    # a completely different one; the fuzzy winner must be returned.
    from sources.bgg import BggRankedGame

    games = [
        BggRankedGame(601, "Spirit Islan", 2017, 20, 8.2, 8.4, 60000, False),  # near-typo match
        BggRankedGame(602, "Spirit Island Companion App Guide", 2020, 9000, 6.0, 6.0, 50, False),
    ]
    idx = BggIndex(games)
    result = idx.match("Spirit Island")
    assert result.bgg_id == 601


def test_no_prefix_candidates_still_returns_low():
    from sources.bgg import BggRankedGame

    games = [BggRankedGame(701, "Completely Different Game", 2020, 1, 5.0, 5.0, 100, False)]
    idx = BggIndex(games)
    result = idx.match("Unrelated Title Entirely")
    assert result.confidence == "LOW"
    assert result.bgg_id is None
