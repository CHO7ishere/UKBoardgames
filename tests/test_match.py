from pathlib import Path

import pytest

from match import BggIndex, _digits_conflict, normalize_title
from sources.bgg import BggRankedGame, filter_base_games, load_bg_ranks

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
        # Real misses found while widening matching coverage: "Kickstarter Edition"/"Special
        # Edition"/"Base Game" are generic retailer/BGG suffixes, not part of a game's identity
        # -- and were actively harmful unstripped (fuzzy-scoring two unrelated games together
        # purely off the shared suffix, e.g. "Calico Kickstarter Edition" vs BGG's unrelated
        # "Autobahn: Kickstarter Edition").
        ("Calico Kickstarter Edition", "calico"),
        ("Battlecrest: Fellwoods Base Game", "battlecrest fellwoods"),
        # "Refresh" is a UK-retailer restocking/reprint term, confirmed never part of a real
        # game's own name across the full real Zatu catalogue.
        ("Guess Who Refresh", "guess who"),
        ("Memoir '44 Refresh", "memoir 44"),
        # Spelled-out ordinal editions ("Second Edition") -> the same abbreviated digit-ordinal
        # form ("2nd Edition") Zatu's own titles use, so the existing digit-edition noise strip
        # catches both -- the pre-existing pattern only matched the digit form.
        ("Gloomhaven (Second Edition)", "gloomhaven"),
        ("Nexus Ops Board Game: Third Edition", "nexus ops"),
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


def test_light_tier_distinguishes_base_game_from_its_own_big_box():
    # Real bug found by mining the unmatched-games list: normalize_title strips "Big Box" as
    # noise from *both* sides, so "Carcassonne" and BGG's own real, separately-priced
    # "Carcassonne Big Box" entry collided into the same normalized string -- ambiguous, both
    # dropped, even though the plain-titled Zatu query unambiguously means the plain base game.
    base = [_game(1, "Carcassonne"), _game(2, "Carcassonne Big Box")]
    index_ = BggIndex(base)
    plain = index_.match("Carcassonne")
    assert plain.confidence == "HIGH"
    assert plain.bgg_id == 1
    big_box = index_.match("Carcassonne Big Box")
    assert big_box.confidence == "HIGH"
    assert big_box.bgg_id == 2


def test_light_tier_distinguishes_base_game_from_its_spelled_ordinal_edition():
    # Real regression found while widening the edition-noise strip to also cover spelled-out
    # ordinal editions ("Second Edition"): BGG catalogues "Gloomhaven" and "Gloomhaven (Second
    # Edition)" as two separate, distinctly-priced entries (same pattern as Carcassonne/Big
    # Box) -- stripping "second edition" as bare noise at the aggressive tier collapsed that
    # real distinction into a false ambiguity. Fixed by converting spelled ordinals to their
    # abbreviated digit form ("second" -> "2nd") before either tier runs, so Zatu's own "2nd
    # Edition" phrasing and BGG's spelled "Second Edition" land on the same light-tier string
    # and resolve to the *specific* edition's id, not just the base game's.
    base = [_game(1, "Gloomhaven"), _game(2, "Gloomhaven (Second Edition)")]
    index_ = BggIndex(base)
    plain = index_.match("Gloomhaven")
    assert plain.confidence == "HIGH"
    assert plain.bgg_id == 1
    second_ed = index_.match("Gloomhaven 2nd Edition")
    assert second_ed.confidence == "HIGH"
    assert second_ed.bgg_id == 2


def test_light_tier_falls_through_to_aggressive_tier_when_still_ambiguous(index):
    # "Spirit Island" and "Spirit Island (Core Game)" both light-normalize to the same string
    # here since "(Core Game)" isn't an edition-noise word the light tier would treat
    # differently -- confirms the light tier doesn't change today's normal exact-match behavior
    # when there's nothing edition-specific to preserve.
    result = index.match("Spirit Island (Core Game)")
    assert result.confidence == "HIGH"
    assert result.bgg_id == 1


# --- BggIndex.match: fuzzy tier and the false-positive guards --------------------------------


def test_expansion_title_does_not_falsely_match_base_game(index):
    # "Spirit Island: Branch & Claw" was filtered out of the index (it's an expansion) —
    # must NOT fall through and fuzzy-match the base "Spirit Island" entry.
    result = index.match("Spirit Island: Branch & Claw")
    assert result.confidence == "LOW"
    assert result.bgg_id is None


def _game(id, name, is_expansion=False):
    return BggRankedGame(
        id=id, name=name, year=2020, rank=None, bayesaverage=None, average=8.0,
        usersrated=1000, is_expansion=is_expansion,
    )


def test_without_excluded_games_a_specific_expansion_query_wrongly_matches_the_base_game():
    # Reproduces a real, confirmed wrong live match: Zatu's "Terraforming Mars - Ares
    # Expedition: Crisis" (a real, separate BGG-catalogued mini-expansion, id 358738) scored
    # 90.4% fuzzy against the base game "Terraforming Mars: Ares Expedition" and was silently
    # accepted, comparing that mini-expansion's UK price against the wrong (much larger) base
    # game's France price. Without passing excluded_games, BggIndex can't know the expansion
    # exists at all, so this bug reproduces here exactly as it did for real.
    base = [_game(1, "Terraforming Mars: Ares Expedition")]
    index = BggIndex(base)
    result = index.match("Terraforming Mars - Ares Expedition: Crisis")
    assert result.confidence == "MEDIUM"
    assert result.bgg_id == 1


def test_excluded_games_veto_stops_the_wrong_expansion_match():
    # Same setup as above, but now BggIndex also knows about the real excluded expansion --
    # it must refuse the base-game fuzzy match entirely rather than silently picking the wrong
    # product, since the query exactly names a specific, known, different BGG entry.
    base = [_game(1, "Terraforming Mars: Ares Expedition")]
    excluded = [_game(2, "Terraforming Mars: Ares Expedition – Crisis", is_expansion=True)]
    index = BggIndex(base, excluded_games=excluded)
    result = index.match("Terraforming Mars - Ares Expedition: Crisis")
    assert result.confidence == "LOW"
    assert result.bgg_id is None
    assert "out of scope" in result.reason
    assert result.candidates == [(2, "Terraforming Mars: Ares Expedition – Crisis")]


def test_excluded_games_veto_does_not_affect_unrelated_queries(index, base_games):
    # The veto is keyed on an *exact* normalized-title match to a specific excluded entry --
    # it must not touch queries that have nothing to do with any excluded game.
    excluded = [_game(999, "Some Totally Different Expansion", is_expansion=True)]
    vetoed_index = BggIndex(base_games, excluded_games=excluded)
    result = vetoed_index.match("Brass: Birmingham")
    assert result.confidence == "HIGH"
    assert result.bgg_id == 2


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


def test_fuzzy_tier_downweights_bare_edition_word_to_recover_a_real_near_miss():
    # Real corpus gap: 128 real Zatu titles still carry a bare "edition" after the existing
    # phrase-based noise strip (_EDITION_NOISE_RE only catches specific curated phrases like
    # "kickstarter edition"), each paired with a one-off adjective too specific to hand-list
    # ("Citadels Revised Edition", "Mage Knight Boardgame Ultimate Edition", ...). Down-weighting
    # the bare words for fuzzy scoring only (never at either exact tier) lets titles like this
    # clear the threshold on their substantive words -- "citadels revised edition" vs "citadels"
    # scores 50.0 on raw token_sort_ratio (well below threshold) but 100.0 once "revised"/
    # "edition" are down-weighted on both sides.
    base = [_game(1, "Citadels")]
    idx = BggIndex(base)
    result = idx.match("Citadels Revised Edition")
    assert result.confidence == "MEDIUM"
    assert result.bgg_id == 1


def test_fuzzy_tier_does_not_let_a_shared_generic_word_alone_create_a_false_match():
    # The other side of the same fix: two genuinely unrelated games that happen to share a
    # generic suffix must not fuzzy-match just because that word inflates token_sort_ratio --
    # confirmed via a real live miss this session (Zatu's "Calico Kickstarter Edition" was
    # fuzzy-scoring against BGG's unrelated "Autobahn: Kickstarter Edition"). Down-weighting the
    # shared word here should *lower* the score of an otherwise-unrelated pair, not raise it.
    base = [_game(1, "Autobahn Kickstarter Edition")]
    idx = BggIndex(base)
    result = idx.match("Calico Kickstarter Edition")
    assert result.confidence == "LOW"


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


def test_ambiguous_exact_match_resolves_to_the_dominant_candidate():
    # Real pattern found mining the AMBIGUOUS_EXACT bucket: "Coup" exact-matches 3 BGG entries
    # (a 1975 wargame, a 1991 wargame, and the actual popular 2012 game), usersrated 90/161/
    # 52695 -- the real one is >=10x every other candidate, a strong enough signal to accept as
    # a MEDIUM-confidence match (a picked answer, not a proven identity) rather than drop.
    from sources.bgg import BggRankedGame

    homonyms = [
        BggRankedGame(1653, "Coup", 1991, 28591, 6.0, 6.0, 90, False),
        BggRankedGame(2088, "Coup", 1975, 13654, 6.0, 6.0, 161, False),
        BggRankedGame(131357, "Coup", 2012, 720, 7.5, 7.5, 52695, False),
    ]
    idx = BggIndex(homonyms)
    result = idx.match("Coup")
    assert result.confidence == "MEDIUM"
    assert result.bgg_id == 131357
    assert "ratings" in result.reason


def test_ambiguous_exact_match_still_drops_when_no_candidate_dominates():
    # A genuine near-tie (2.5x, below the 10x bar) must still be dropped, not guessed --
    # this is the same fixture test_ambiguous_exact_match_is_dropped uses, just asserting the
    # dominance tiebreak doesn't fire on it.
    from sources.bgg import BggRankedGame

    dupes = [
        BggRankedGame(101, "Aftermath", 2020, 100, 7.0, 7.0, 500, False),
        BggRankedGame(102, "AFTERMATH!", 1998, 5000, 6.0, 6.0, 200, False),
    ]
    idx = BggIndex(dupes)
    result = idx.match("Aftermath")
    assert result.confidence == "LOW"


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
