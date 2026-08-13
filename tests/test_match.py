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
    # ("Mage Knight Boardgame Ultimate Edition", ...). Down-weighting the bare words for fuzzy
    # scoring only (never at either exact tier) lets titles like this clear the threshold on
    # their substantive words -- "mage knight boardgame ultimate edition" vs "mage knight
    # boardgame" scores well below threshold on raw token_sort_ratio but clears it once
    # "ultimate"/"edition" are down-weighted on both sides. ("Ultimate" is deliberately not in
    # `_LIGHT_SAFE_FILLER_RE`'s corpus-checked exact-tier list, so this still exercises the
    # fuzzy-only path -- unlike "Citadels Revised Edition", which now resolves earlier and more
    # precisely via the light exact tier itself, see test_match_bgg.py's real-corpus fixes.)
    base = [_game(1, "Mage Knight Boardgame")]
    idx = BggIndex(base)
    result = idx.match("Mage Knight Boardgame Ultimate Edition")
    assert result.confidence == "MEDIUM"
    assert result.bgg_id == 1


def test_light_tier_resolves_revised_edition_to_the_sole_real_candidate():
    # A real user-reported miss (2026-08-12): "Citadels Revised Edition" has no distinguishing
    # word to strip on BGG's own side when there's only one real "Citadels" entry -- the light
    # tier now strips "revised"/"edition" itself (corpus-checked: see _LIGHT_SAFE_FILLER_RE),
    # resolving this as a clean single-candidate HIGH match rather than falling through to fuzzy.
    base = [_game(1, "Citadels")]
    idx = BggIndex(base)
    result = idx.match("Citadels Revised Edition")
    assert result.confidence == "HIGH"
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


def test_ambiguous_exact_match_is_dropped_when_no_dominance_and_low_votes():
    # Ambiguous exact match with low vote counts -> must drop rather than guess (spec P2).
    # New example: both candidates have sparse vote data (niche games), so even a 2.5x ratio
    # is not confident enough. The 4x threshold still applies for these rare/obscure titles.
    from sources.bgg import BggRankedGame

    niche_dupes = [
        BggRankedGame(103, "Obscure A", 2020, 100, 7.0, 7.0, 35, False),
        BggRankedGame(104, "Obscure A", 1998, 5000, 6.0, 6.0, 14, False),  # 2.5x but < 100 votes
    ]
    idx = BggIndex(niche_dupes)
    result = idx.match("Obscure A")
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


def test_ambiguous_exact_match_still_drops_when_both_have_high_votes_but_no_dominance():
    # A true tie (2x ratio but both have >100 votes) at the limit of the adaptive threshold
    # must still be dropped: e.g., both games have substantial player bases (110 vs 100 votes).
    # The 2x rule requires strict inequality (top >= 2*runner-up), so 110 is not >= 2*100 (200).
    from sources.bgg import BggRankedGame

    weak_dupes = [
        BggRankedGame(105, "Borderline", 2020, 100, 7.0, 7.0, 110, False),
        BggRankedGame(106, "BORDERLINE!", 1998, 5000, 6.0, 6.0, 100, False),  # 1.1x ratio
    ]
    idx = BggIndex(weak_dupes)
    result = idx.match("Borderline")
    assert result.confidence == "LOW"


def test_ambiguous_exact_match_resolves_with_adaptive_2x_threshold_when_votes_high():
    # Adaptive strategy: 2x ratio is safe when top candidate has >= 100 votes (abundant community
    # data means a 2x difference is a genuine signal). For niche games with sparse data, still
    # require 4x. Real pattern: a well-established game (200 votes) vs a variant (100 votes)
    # is clearly the right pick; ambiguous exact match with 2.5x ratio and sufficient vote count.
    from sources.bgg import BggRankedGame

    well_established = [
        BggRankedGame(101, "Dune: Imperium", 2020, 2023, 7.5, 7.5, 200, False),  # Variant
        BggRankedGame(102, "Dune: Imperium", 2020, 2023, 7.8, 7.8, 500, False),   # Base game (2.5x)
    ]
    idx = BggIndex(well_established)
    result = idx.match("Dune: Imperium")
    assert result.confidence == "MEDIUM"  # Picked via adaptive 2x (500 >= 2*200 and 500 >= 100)
    assert result.bgg_id == 102


def test_ambiguous_exact_match_requires_4x_when_votes_sparse():
    # Niche games with limited vote count: stick with conservative 4x ratio to avoid false
    # positives. Real case: a game with 25 votes vs 10 votes (2.5x) should still be dropped.
    from sources.bgg import BggRankedGame

    niche = [
        BggRankedGame(201, "Obscure Game", 2020, 2023, 6.0, 6.0, 10, False),
        BggRankedGame(202, "Obscure Game", 2019, 2023, 6.5, 6.5, 25, False),  # 2.5x but too few votes
    ]
    idx = BggIndex(niche)
    result = idx.match("Obscure Game")
    assert result.confidence == "LOW"  # Rejected: 25 < 100 votes threshold


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


def test_fuzzy_tie_resolved_by_dominance_tiebreak():
    # Real case: "Battle Royale: Last One Standing" matches two BGG entries with identical
    # fuzzy scores: id 237171 (90 ratings) and id 284496 (15 ratings, 2nd Edition).
    # The dominance tiebreak should pick the one with clearly more ratings (6x).
    from sources.bgg import BggRankedGame

    games = [
        BggRankedGame(801, "Last One Standing: The Battle Royale Board Game", 2018, 23297, 5.9, 6.0, 90, False),
        BggRankedGame(802, "Last One Standing: The Battle Royale Board Game 2nd Edition", 2019, 0, 6.3, 6.3, 15, False),
    ]
    idx = BggIndex(games)
    result = idx.match("Battle Royale: Last One Standing", fuzzy_threshold=85, min_gap=5)
    # Should match to the dominant candidate (90 ratings > 15 ratings, ratio 6x > 4x) with MEDIUM confidence
    assert result.confidence == "MEDIUM"
    assert result.bgg_id == 801
    assert result.score == 100.0


def test_fuzzy_tie_without_clear_dominance_is_dropped():
    # When multiple candidates tie at the same fuzzy score and no candidate is
    # clearly dominant (by rating count), the match should be rejected as ambiguous.
    from sources.bgg import BggRankedGame

    games = [
        BggRankedGame(901, "Title A: Edition One", 2020, 100, 7.0, 7.0, 100, False),
        BggRankedGame(902, "Title A: Edition Two", 2021, 200, 7.0, 7.0, 95, False),  # Only 1.05x rating, below 4x dominance bar
    ]
    idx = BggIndex(games)
    result = idx.match("Title A", fuzzy_threshold=85, min_gap=5)
    # No clear dominance (100 / 95 = 1.05, much below the 4x bar), so should be dropped despite high fuzzy score
    assert result.confidence == "LOW"
    assert result.bgg_id is None


def test_fuzzy_match_with_small_gap_accepted_when_score_is_very_high():
    # Real case: "Poo Bingo" vs "Poop Bingo" (typo/spelling variant). Fuzzy scores 94.74%
    # against the correct match but the runner-up "Bingo Pongo" scores 90%, giving a gap of
    # only 4.74 (below the 5-point min_gap). However, 94.74% is so close to perfect that the
    # gap is acceptable even though it's small, since the high score suggests a strong match.
    from sources.bgg import BggRankedGame

    games = [
        BggRankedGame(1001, "Poop Bingo", 2020, 500, 6.5, 6.5, 1000, False),
        BggRankedGame(1002, "Bingo Pongo", 2019, 100, 6.0, 6.0, 300, False),
    ]
    idx = BggIndex(games)
    result = idx.match("Poo Bingo", fuzzy_threshold=85, min_gap=5)
    # Gap is 4.74 < 5, but score is 94.74 >= 90, so should accept as MEDIUM confidence
    assert result.confidence == "MEDIUM"
    assert result.bgg_id == 1001
    assert result.score > 94.0  # Poop Bingo match
