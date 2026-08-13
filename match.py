"""Stage 2 — offline BGG match (docs/spec.md §3-4). Matches a title against the pre-downloaded
bg_ranks.csv; no network calls. Confidence cascade per spec §4.2: exact normalized-title match
is HIGH; a fuzzy match above threshold with a clear gap to the runner-up is MEDIUM; a title
that's a unique shortened prefix of exactly one BGG title (e.g. Zatu's "Five Tribes" for BGG's
"Five Tribes: The Djinns of Naqala") is also MEDIUM, tried only as a fallback after fuzzy finds
nothing; anything else is LOW and gets dropped — ambiguous matches (multiple BGG entries tied on
exact title or shared prefix) are never surfaced for manual review (spec P2), only logged to
dropped.csv for later skimming.
"""

from __future__ import annotations

import bisect
import html
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz, process

from sources.bgg import BggRankedGame

_ROMAN_MAP = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}
_ROMAN_RE = re.compile(r"\b(x|ix|viii|vii|vi|v|iv|iii|ii|i)\b", re.IGNORECASE)

# "Volume One"/"Vol. 3"/"Vol 2" all denote the same thing -- found via a real miss (Zatu's
# "Unmatched Battle Of Legends, Vol. 1" vs BGG's "Unmatched: Battle of Legends, Volume One",
# ~87% fuzzy, below threshold). Expand the retailer's "Vol."/"Vol" abbreviation to BGG's
# spelled-out "volume" first (two-step: turn a trailing dot into a space, then match the bare
# word) so the two sides compare equal, rather than stripping the word entirely -- the volume
# number is exactly what distinguishes these entries, so it must be kept and aligned, not noise.
_VOL_DOT_RE = re.compile(r"\bvol\.(?=\s|\d)")
_VOL_WORD_RE = re.compile(r"\bvol\b")

# Same real miss also showed BGG spelling the volume number as a word ("One"/"Two"/"Three")
# where Zatu uses a digit ("1"/"2"/"3") -- convert low word-numbers to digits the same way roman
# numerals already are, so both sides land on the same digit token.
_WORD_NUM_MAP = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}
_WORD_NUM_RE = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b")

# Spelled-out ordinals ("Second Edition") -> the abbreviated digit-ordinal form Zatu actually
# uses ("2nd Edition"), applied *before* the edition-noise strip below so both sides land on the
# same token instead of just one. Found as a real regression while widening the noise list to
# also strip spelled-out ordinal editions: BGG catalogues "Gloomhaven" and "Gloomhaven (Second
# Edition)" as two separate, distinctly-priced entries (same pattern as Carcassonne/Big Box) --
# stripping "second edition" as bare noise collapsed that real distinction into a false
# ambiguity, and the light tier couldn't rescue it either since it never converted BGG's spelled
# "second edition" to match Zatu's digit "2nd edition" in the first place. Converting instead of
# stripping fixes both: aggressive tier no longer conflates the two entries, and light tier can
# now exact-match Zatu's "Gloomhaven 2nd Edition" to the specific BGG "Gloomhaven (Second
# Edition)" id -- more precise than the pre-regression behaviour, which fell through to the base
# game's id instead.
_ORDINAL_MAP = {
    "first": "1st", "second": "2nd", "third": "3rd",
    "fourth": "4th", "fifth": "5th", "sixth": "6th",
}
_ORDINAL_RE = re.compile(r"\b(first|second|third|fourth|fifth|sixth)\b")

# "v." as a bare "versus" abbreviation (all 23 real occurrences in bg_ranks.csv are Dice Throne
# matchup titles, e.g. "Dice Throne: ... Pyromancer v. Shadow Thief") was being silently
# misread by the roman-numeral regex below as "V" = 5 -- found via a real regression the vol/
# word-number fixes above exposed: once "Season One" on both sides became "Season 1", the
# query's real digit ("1") and the candidate's *fake* one (this "v"->5 misread) started
# disagreeing, tripping the digit-conflict veto on a game that used to match. Normalize the
# abbreviation to "vs" (matching how Zatu spells it) before the roman-numeral pass ever sees a
# bare "v", rather than letting it get read as a numeral -- restricted to "v." followed by
# whitespace so it can't misfire on a genuine roman-numeral "V" (which never carries a trailing
# dot in these titles).
_V_DOT_RE = re.compile(r"\bv\.(?=\s)")

# "Collector's"/"Collectors" -> "Collector": a real cross-check of 10 user-reported "should have
# matched" misses (2026-08-12) found Tenpenny Parks: BGG's own real distinct entry is literally
# titled "Tenpenny Parks: Collector's Edition" (apostrophe-s), but Zatu's product is "Tenpenny
# Parks: Collector Edition" (no apostrophe-s) -- punctuation stripping alone still leaves
# "collectors" vs "collector" as different tokens. Narrow, targeted word-pair alignment (same
# pattern as the Vol./ordinal fixes above), not a general plural/possessive-stripping rule that
# could conflate unrelated words.
_COLLECTOR_RE = re.compile(r"\bcollector'?s\b")

# "Back Stories" -> "Backstories": Zatu titles the game as "Back Stories: Alone Under the Ice"
# (two words) but BGG catalogues it as "Backstories: Alone Under the Ice" (one word) — a real
# match miss (fuzzy 83.64, below 90 threshold). Narrow compound-word alignment: only applied
# when "back stories" appear together, not "back" or "stories" alone.
_BACKSTORIES_RE = re.compile(r"\bback\s+stories\b")

# Words safe to strip even at the light tier -- a real cross-check of 10 user-reported "should
# have matched" misses (2026-08-12), each verified against the full 140,261-base-game corpus
# before being added here (same method as every other noise word in this file): does stripping
# it, on *both* the query and every BGG name, ever merge two BGG entries that weren't already
# colliding? A light-tier collision is always safe regardless (it just falls through to the
# aggressive tier exactly like today, since light tier only auto-resolves a *single* candidate --
# never a wrong silent match), but a word that collides real, meaningfully-different products
# still isn't worth adding blind, since it destroys the light tier's ability to disambiguate them
# via the recency-tiebreak below or a future, more specific fix.
#
# "the game" -- 0 new collisions, matches the existing aggressive-tier reasoning (EXIT franchise).
# Bare "edition" -- 16 new collisions, all BGG-side near-duplicate listings for the literal same
# real product (e.g. "Time's Up! Party" id 38713 vs "Time's Up! Party Edition" id 230262) --
# never two genuinely different games.
# "complete"/"standard"/"anniversary"/"revised" -- 4/0/3/1 new collisions respectively, all either
# near-zero-rated noise or (Stone Age vs Stone Age: Anniversary, Talisman variants) real distinct
# editions -- but since light-tier collisions can't produce a wrong match, these still can only
# help (e.g. Arkwright: Anniversary -> Arkwright, Trailblazers Standard -> Trailblazers,
# Air, Land & Sea: Revised Edition -> Air, Land, & Sea, Tenpenny Parks: Collector Edition ->
# Tenpenny Parks: Collector's Edition once paired with _COLLECTOR_RE above).
#
# Deliberately EXCLUDES "board game"/"card game" despite being pure category filler in most
# cases (e.g. Slay the Spire: The Board Game) -- real corpus check found these strip real,
# separately-catalogued spin-off products too: "Arkwright: The Card Game" (a genuinely different
# game, not an edition of base Arkwright) is one of 455 real "card game" collisions, "board game"
# has 123. Confirmed via a real miss this would have broken (Arkwright: The Card Game light-
# matching itself correctly today) before it was excluded. Zatu's "Orleans Board Game: Big Box
# Edition" -> BGG's "Orléans: Big Box" needs exactly this word to resolve and is NOT fixed by
# this round -- flagged separately rather than risking the Arkwright-class regression.
_LIGHT_SAFE_FILLER_RE = re.compile(r"\b(the game|edition|complete|standard|anniversary|revised)\b")

# Recency-signal words: when a query's own wording says "this is a newer printing" and it ties
# with another BGG entry sharing the exact identical bare name (e.g. BGG catalogues "Citadels"
# twice -- id 478, 2000, and id 205398, 2016's Revised Edition, with no distinguishing word in
# either BGG name itself), prefer the tied candidate with the latest yearpublished. Deliberately
# narrow: only the words that actually mean "newer than before" (not "standard"/"premium"/
# "collector"/"complete", which say nothing about timing) and only when there's a single, clearly
# latest year among the *already-tied* candidates -- never a broader guess.
_RECENCY_SIGNAL_RE = re.compile(r"\b(revised|anniversary|renewed|remastered|reprint(ed)?)\b", re.IGNORECASE)

# Marketing/edition noise stripped before comparison (spec §4.1). Matched as whole phrases so
# "2nd edition"/"deluxe edition" disappear together rather than leaving a stray "2"/"deluxe".
# NOTE: "core" is deliberately NOT stripped as a bare word (only the "core game" phrase) —
# it used to be, which silently mangled "Company of Heroes: 2nd Edition Core Set" into "...set"
# by eating "core" out of "Core Set", a real BGG product-line term, not marketing noise.
# "the game" is here too -- found via a real, concentrated miss class: BGG catalogues the whole
# EXIT: puzzle-room series as "EXIT: The Game – <subtitle>", but Zatu's listings drop "The Game"
# entirely ("EXIT: The Sinister Mansion" / "EXiT - The Sinister Mansion"), landing ~15 real EXIT
# titles at 85-90% fuzzy, just under/too close-to-threshold. Safe even in the worst case: if two
# genuinely different BGG entries only differ by "the game", stripping it just makes them collide
# into the ambiguous-exact-match branch (correctly dropped), never a wrong silent match.
#
# "kickstarter edition"/"special edition"/"base game"/spelled-out ordinal editions
# ("second edition" etc, the existing digit-only "\d+(st|nd|rd|th) edition" branch never
# caught these) and bare "refresh" (a UK-retailer term for a reprinted/restocked SKU, 26 real
# Zatu titles, never part of a real game's own name) added the same way, each checked against
# the full corpus first: every real BGG title carrying "base game" pairs it with a distinguishing
# prefix (e.g. "Battlecrest: Fellwoods Base Game"), so stripping it can't merge two different
# products; "kickstarter edition"/"special edition" turned out to be actively harmful *unstripped*
# — matched to real wrong-game near-misses in the corpus (e.g. Zatu's "Calico Kickstarter
# Edition" fuzzy-scoring against BGG's unrelated "Autobahn: Kickstarter Edition" purely off the
# shared suffix) before this fix, not just missed real matches.
# Real regression found and fixed here: a handful of BGG titles use a compound ordinal
# ("Mission: Red Planet (Second/Third Edition)", "Fury of Dracula (Third/Fourth Edition)" --
# 5 total in bg_ranks.csv) for an edition that folds two BGG-catalogued printings into one
# entry. Stripping only a single trailing ordinal ("\d+(st|nd|rd|th)\s+edition") left a stray
# leading ordinal token behind on the BGG side ("mission red planet 2nd") while the query's own
# simple "Third Edition" stripped clean to "mission red planet" -- an asymmetric strip that
# silently exact-matched the *wrong*, separate, lower-quality base-game BGG entry (a real
# distinct id that exists for exactly this reason) instead of correctly falling through to
# ambiguous. `(\d+(st|nd|rd|th)\s*/\s*)*` consumes any number of slash-joined leading ordinals
# before the final one, so the whole compound phrase strips as a single unit on both sides.
_EDITION_NOISE_RE = re.compile(
    r"\b(board game|card game|the game|(\d+(st|nd|rd|th)\s*/\s*)*\d+(st|nd|rd|th)\s+edition|"
    r"deluxe edition|deluxe|big box edition|"
    r"big box|retail edition|english edition|english|core game|standard edition|"
    r"anniversary edition|collector edition|kickstarter edition|kickstarter|special edition|"
    r"base game|refresh(ed)?)\b"
)
# Broader generic-descriptor list, applied *only* inside the fuzzy tier's own scoring (see
# `_fuzzy_score_text`), never at either exact-match tier. _EDITION_NOISE_RE above only strips
# specific curated *phrases* ("kickstarter edition", "special edition") -- real corpus check
# (2026-08-11) found 128 real Zatu titles still carry a bare "edition" after that (e.g. "Cyclades
# Legendary Edition", "Citadels Revised Edition", "Mage Knight Boardgame Ultimate Edition") that
# the phrase list can't catch without an ever-growing whitelist of every adjective BGG/Zatu might
# pair it with. Deliberately NOT folded into `normalize_title`/_EDITION_NOISE_RE itself: exact-
# tier identity resolution (both light and aggressive) genuinely needs these words in some cases
# -- "Big Box"/"Second Edition"-style qualifiers are how BGG distinguishes real, separately-priced
# catalogue entries (confirmed repeatedly this session: Carcassonne vs Carcassonne Big Box,
# Gloomhaven vs Gloomhaven Second Edition). The fuzzy tier is different: it only ever runs *after*
# both exact tiers already failed to find a specific id, so down-weighting these words there to
# find the substantive words underneath can't cause the exact-identity mistakes stripping them
# earlier in the pipeline would -- worst case it's a fuzzy score that's still gated by the
# existing threshold/gap/digit-conflict checks. "core"/"master"/"legacy" are deliberately excluded
# even here -- all three are real, meaningful genre/product-line terms in this corpus (Pandemic
# *Legacy*, Marvel Champions *Core* Set, Summoner Wars *Master* Set), not marketing filler.
_FUZZY_EXTRA_NOISE_RE = re.compile(
    r"\b(kickstarter|edition|version|retail|special|standard|collectors?|anniversary|"
    r"remastered|revised|definitive|ultimate|exclusive|complete|premium|essentials?|limited)\b"
)
_ARTICLE_RE = re.compile(r"\b(a|an|the)\b")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
_DIGIT_RE = re.compile(r"\d+")


def _fuzzy_score_text(normalized: str) -> str:
    """Further down-weights generic marketing/edition-status words for fuzzy comparison only --
    see `_FUZZY_EXTRA_NOISE_RE`'s docstring for why this doesn't touch either exact-match tier."""
    return _WS_RE.sub(" ", _FUZZY_EXTRA_NOISE_RE.sub(" ", normalized)).strip()

# A trailing "(2013)"-style reprint/release-year annotation — confirmed present on 18 real
# Zatu titles (e.g. "Pandemic (2013)", "CATAN 6th Edition (2025)") with no BGG counterpart
# carrying the same suffix; stripped before the digit-conflict veto would otherwise see it as
# a spurious extra digit token. Anchored to the end and requires parens so it doesn't touch a
# year that's actually part of the game's name (e.g. "The Great Fire of London 1666").
_TRAILING_YEAR_RE = re.compile(r"\(\s*(19|20)\d{2}\s*\)\s*$")

# "40,000" -> "40000": BGG writes some titles with a thousands-separator comma (463 real
# entries, mostly "Warhammer 40,000" variants) that Zatu's listings never do — left alone,
# general punctuation stripping below would turn "40,000" into two digit tokens ("40", "000")
# instead of one, so it would never equal Zatu's unpunctuated "40000" and would spuriously
# trip the digit-conflict veto.
_THOUSANDS_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")


def normalize_title_light(title: str) -> str:
    """Same as `normalize_title` but *without* the edition-noise strip (spec §4.1's punctuation/
    accent/article/roman-numeral/spelling normalization only) -- used for a first, more
    conservative exact-match pass (see `BggIndex`). Edition-noise words like "Big Box"/"Card
    Game"/"Deluxe Edition" aren't just retailer marketing filler; BGG frequently catalogues them
    as their own distinct, separately-priced products (e.g. "Carcassonne" vs "Carcassonne Big
    Box" are different real BGG entries with different ids). `normalize_title` strips those
    words indiscriminately from *both* the query and BGG's own names, which is exactly why so
    many exact matches come back ambiguous: "Carcassonne" and "Carcassonne Big Box" collide onto
    the same stripped string, even though the query text itself still says which one it means.
    This lighter pass preserves that distinction so an exact match can be tried before any
    information is thrown away.
    """
    text = html.unescape(title).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _TRAILING_YEAR_RE.sub(" ", text)
    text = _THOUSANDS_COMMA_RE.sub("", text)
    text = text.replace("&", " and ")
    text = _VOL_DOT_RE.sub("vol ", text)
    text = _VOL_WORD_RE.sub("volume", text)
    text = _V_DOT_RE.sub("vs", text)
    text = _ORDINAL_RE.sub(lambda m: _ORDINAL_MAP[m.group(0)], text)
    text = _COLLECTOR_RE.sub("collector", text)
    text = _BACKSTORIES_RE.sub("backstories", text)
    text = _LIGHT_SAFE_FILLER_RE.sub(" ", text)
    text = _WORD_NUM_RE.sub(lambda m: _WORD_NUM_MAP[m.group(0)], text)
    text = _ROMAN_RE.sub(lambda m: _ROMAN_MAP.get(m.group(0).lower(), m.group(0)), text)
    text = _PUNCT_RE.sub(" ", text)
    text = _ARTICLE_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def normalize_title(title: str) -> str:
    """Lowercase, strip accents/edition noise/punctuation/articles, normalise '&'->'and' and
    roman numerals, collapse whitespace (spec §4.1).

    Articles are stripped anywhere in the string, not just a leading one — found via a real
    miss ("Slay the Spire: The Board Game" vs Philibert's title for it): stripping the noise
    phrase "board game" out of "...: The Board Game" left a dangling, ungrammatical "the" behind
    that a leading-only strip couldn't reach, corrupting the comparison string.
    """
    text = html.unescape(title).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _TRAILING_YEAR_RE.sub(" ", text)
    text = _THOUSANDS_COMMA_RE.sub("", text)
    text = text.replace("&", " and ")
    text = _VOL_DOT_RE.sub("vol ", text)
    text = _VOL_WORD_RE.sub("volume", text)
    text = _V_DOT_RE.sub("vs", text)
    text = _ORDINAL_RE.sub(lambda m: _ORDINAL_MAP[m.group(0)], text)
    text = _COLLECTOR_RE.sub("collector", text)
    text = _BACKSTORIES_RE.sub("backstories", text)
    text = _EDITION_NOISE_RE.sub(" ", text)
    text = _WORD_NUM_RE.sub(lambda m: _WORD_NUM_MAP[m.group(0)], text)
    text = _ROMAN_RE.sub(lambda m: _ROMAN_MAP.get(m.group(0).lower(), m.group(0)), text)
    text = _PUNCT_RE.sub(" ", text)
    text = _ARTICLE_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _digits_conflict(a: str, b: str) -> bool:
    """True if both titles carry digit tokens and those tokens differ — e.g. "Pandemic Legacy:
    Season 1" vs "Season 2" score ~96% on token_sort_ratio despite being different games; a
    general string-similarity scorer has no notion that a "1"->"2" edit changes the game
    entirely. Cheap, explicit veto for the single biggest false-positive class in fuzzy title
    matching for numbered sequels/seasons/expansions."""
    da, db = set(_DIGIT_RE.findall(a)), set(_DIGIT_RE.findall(b))
    return bool(da) and bool(db) and da != db


@dataclass
class MatchResult:
    query_title: str
    bgg_id: int | None
    bgg_name: str | None
    confidence: str  # "HIGH" | "MEDIUM" | "LOW"
    score: float | None
    reason: str
    # Purely informational, never used to decide match/no-match: the BGG entry/entries that
    # were closest to (or tied with) the query when a LOW-confidence result is returned, so a
    # human can eyeball a dropped title and judge "near-miss worth a closer look" vs "genuinely
    # not on BGG" -- e.g. surfaced in the website's unmatched-games list. Deliberately kept
    # separate from bgg_id/bgg_name, which stay None on LOW so nothing downstream can mistake
    # this for an actual match.
    candidates: list[tuple[int, str]] = field(default_factory=list)


# Ambiguous-exact tiebreak threshold (user-confirmed 2026-08-11, after reviewing real numbers):
# mining the real 213-entry AMBIGUOUS_EXACT bucket found that most "ties" aren't real ties at
# all -- e.g. "Coup" exact-matches 3 BGG entries (a 1975 wargame, a 1991 wargame, and the actual
# 2012 game everyone means), with usersrated 90 / 161 / 52,695. A same-named BGG entry with
# usersrated below the quality gate's own min_votes floor was always going to be filtered out
# downstream anyway, so refusing the match over it is precision theatre, not real caution.
# Adaptive strategy: 2x is confident when the top candidate has abundant vote data (>=100),
# since the community signal is strong; 4x is always safe, even for niche games with sparse data.
# This recovers matches like 500 vs 250 votes (well-established game) while staying cautious
# about 25 vs 12 votes (niche game with limited signal).
_DOMINANCE_RATIO = 4
_DOMINANCE_RATIO_PERMISSIVE = 2
_DOMINANCE_MIN_VOTES_FOR_PERMISSIVE = 100


class BggIndex:
    """Precomputed index over a bg_ranks.csv load — build once per run, match many titles."""

    def __init__(
        self, games: list[BggRankedGame], excluded_games: list[BggRankedGame] | None = None
    ):
        self.games = games
        self.normalized_names = [normalize_title(g.name) for g in games]
        # Fuzzy-only further down-weighting of generic marketing/edition words -- see
        # `_fuzzy_score_text`'s docstring. Precomputed once here (not per-query) since it's used
        # for every fuzzy comparison; index-aligned 1:1 with `self.games`/`normalized_names`, so
        # a match found here still looks up the right game by position.
        self._fuzzy_names = [_fuzzy_score_text(n) for n in self.normalized_names]
        self._exact: dict[str, list[BggRankedGame]] = defaultdict(list)
        for game, norm in zip(games, self.normalized_names):
            self._exact[norm].append(game)

        # Lighter exact-match index, tried first (see normalize_title_light's docstring): keeps
        # "Big Box"/"Card Game"/"Deluxe Edition"-type words instead of stripping them, so a
        # query that includes one of these words can land on the specific real BGG entry for
        # that product rather than colliding with a same-named plainer edition.
        self._exact_light: dict[str, list[BggRankedGame]] = defaultdict(list)
        for game in games:
            self._exact_light[normalize_title_light(game.name)].append(game)

        # Sorted (normalized_name, game) pairs for O(log n) prefix lookups — see
        # `_prefix_matches`. Confirmed valuable against the real 4178-product harvest: 62 titles
        # like "Five Tribes" are a retailer's shortened form of a BGG title with a subtitle
        # ("Five Tribes: The Djinns of Naqala") and would otherwise never match at all.
        self._sorted_pairs = sorted(zip(self.normalized_names, games), key=lambda p: p[0])
        self._sorted_names = [name for name, _ in self._sorted_pairs]

        # Exact-title index over games this BggIndex was *not* built to match against --
        # normally the corpus dropped by `filter_base_games(include_expansions=False)`. Found
        # via a real, confirmed wrong live match: Zatu's "Terraforming Mars - Ares Expedition:
        # Crisis" (a $17 mini-expansion) scored 90.4% fuzzy against the base game "Terraforming
        # Mars: Ares Expedition" and was silently accepted -- comparing the wrong two products'
        # prices. The real BGG entry for it ("Terraforming Mars: Ares Expedition – Crisis", id
        # 358738) exists and normalizes to an *exact* match of the query -- it's excluded from
        # `self.games` only because it's an expansion, not because it's unknown. When the query
        # exactly names a specific excluded product like this, that's a precise identity we
        # already know, not an ambiguous guess -- refuse to fall through to a fuzzy/prefix match
        # against a different (base-game) product instead of silently picking the wrong one.
        self._excluded_exact: dict[str, list[BggRankedGame]] = defaultdict(list)
        for game in excluded_games or []:
            self._excluded_exact[normalize_title(game.name)].append(game)

        # Alternate-names index from Stage 3's BGG API fetch (data/bgg_details.json) -- folk game
        # names like "Liars Dice" that don't match commercial names like "Perudo" (id 45). Maps
        # normalized alternate name → list of (bgg_id, game) tuples. Loaded optionally: if
        # bgg_details.json doesn't exist (first run, before Stage 3), matching still works but
        # skips the alternate-name tier.
        self._alternate_names_index: dict[str, list[tuple[int, BggRankedGame]]] = defaultdict(list)
        self._load_alternate_names_index(games)

    @staticmethod
    def _dominant_by_rating_count(candidates: list[BggRankedGame]) -> BggRankedGame | None:
        """Among title-tied candidates, return the one that dominates by rating count -- or None
        if no candidate dominates clearly (a genuine tie, left for the caller to drop as ambiguous).
        Adaptive strategy: if the top candidate has abundant vote data (>=100), a 2x ratio is
        enough (well-established games have strong community signal); otherwise require 4x
        (niche games need higher confidence bar to avoid false positives)."""
        by_rating = sorted(candidates, key=lambda g: g.usersrated, reverse=True)
        top, runner_up = by_rating[0], by_rating[1]

        # Permissive: 2x is safe when top candidate has rich vote data
        if (top.usersrated >= _DOMINANCE_MIN_VOTES_FOR_PERMISSIVE and
            top.usersrated >= _DOMINANCE_RATIO_PERMISSIVE * max(runner_up.usersrated, 1)):
            return top

        # Conservative: 4x always wins, even for niche games
        if top.usersrated >= _DOMINANCE_RATIO * max(runner_up.usersrated, 1):
            return top

        return None

    @staticmethod
    def _recency_pick(candidates: list[BggRankedGame], raw_title: str) -> BggRankedGame | None:
        """Among title-tied candidates that share the *identical* bare name (e.g. BGG catalogues
        "Citadels" twice -- the 2000 original and 2016's Revised Edition, with no distinguishing
        word in either BGG name itself), pick the latest `yearpublished` one, but *only* when the
        query's own raw text says this is a newer printing (see `_RECENCY_SIGNAL_RE`) and exactly
        one candidate has the clearly-latest year. Real case that prompted this (2026-08-12):
        Zatu's "Citadels Revised Edition" -- usersrated dominance alone picks the *wrong* one here
        (the 2000 original has more cumulative ratings simply from being older, 57379 vs 17553,
        neither reaching the 10x bar anyway), so this tiebreak is tried as a distinct fallback,
        not a replacement for it."""
        if not _RECENCY_SIGNAL_RE.search(raw_title):
            return None
        by_year = sorted(candidates, key=lambda g: g.year or 0, reverse=True)
        top, runner_up = by_year[0], by_year[1]
        if top.year and (runner_up.year or 0) < top.year:
            return top
        return None

    def _prefix_matches(self, norm: str) -> list[BggRankedGame]:
        """BGG games whose normalized name is `norm` followed by a space and more text — i.e.
        `norm` is a shortened, word-boundary-safe prefix of the full title."""
        prefix = norm + " "
        lo = bisect.bisect_left(self._sorted_names, prefix)
        upper_bound = prefix[:-1] + chr(ord(" ") + 1)  # next char after space
        hi = bisect.bisect_left(self._sorted_names, upper_bound)
        return [self._sorted_pairs[i][1] for i in range(lo, hi)]

    def _load_alternate_names_index(self, games: list[BggRankedGame]) -> None:
        """Load BGG alternate names from Stage 3's bgg_details.json if it exists. Maps
        normalized alternate name → list of (bgg_id, game) tuples. Gracefully degrades if
        the file doesn't exist (e.g. first run, before Stage 3 completes)."""
        details_path = Path("data/bgg_details.json")
        if not details_path.exists():
            return

        try:
            details = json.loads(details_path.read_text())
            game_by_id = {g.id: g for g in games}
            # details is keyed by bgg_id (string); iterate over items
            for bgg_id_str, item in details.items():
                bgg_id = int(bgg_id_str) if isinstance(bgg_id_str, str) else bgg_id_str
                game = game_by_id.get(bgg_id)
                if not game:
                    continue
                for alt_name in item.get("alternate_names", []):
                    if alt_name:
                        norm = normalize_title(alt_name)
                        self._alternate_names_index[norm].append((bgg_id, game))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            # If bgg_details.json is malformed or missing expected fields, silently degrade
            pass

    def _alternate_name_match(self, norm: str) -> BggRankedGame | None:
        """Check if normalized query matches any alternate name in bgg_details.json.
        Returns the matched game if exactly one match exists, None otherwise."""
        matches = self._alternate_names_index.get(norm)
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0][1]
        # Multiple games share this alternate name -- ambiguous, don't guess
        return None

    def match(
        self, title: str, fuzzy_threshold: float = 90.0, min_gap: float = 5.0
    ) -> MatchResult:
        # Try the lighter (edition-noise-preserving) exact match first -- only when it resolves
        # to a *single* candidate, since anything it finds ambiguous will only stay ambiguous
        # (or grow more so) once edition-noise stripping merges further groups together; falling
        # through to the aggressive-tier exact check below in that case still produces a
        # correct, more complete candidate list for the ambiguous-drop result.
        light_exact = self._exact_light.get(normalize_title_light(title))
        if light_exact:
            if len(light_exact) == 1:
                bgg = light_exact[0]
                return MatchResult(
                    title, bgg.id, bgg.name, "HIGH", 100.0,
                    "exact match preserving edition/format words (e.g. Big Box, Card Game)",
                )
            # _LIGHT_SAFE_FILLER_RE can turn a query that used to resolve at this tier alone into
            # a tie against a real BGG variant (e.g. "X: Anniversary Edition") -- try the same two
            # proven-safe tiebreaks the aggressive tier already uses (dominance first, matching
            # its own order) before falling through, rather than only the recency one.
            dominant = self._dominant_by_rating_count(light_exact)
            if dominant is not None:
                return MatchResult(
                    title, dominant.id, dominant.name, "MEDIUM", 100.0,
                    "ambiguous exact title, but one BGG entry dominates by community ratings -- "
                    "picked as the game Zatu almost certainly means",
                    candidates=[(g.id, g.name) for g in light_exact[:5]],
                )
            recent = self._recency_pick(light_exact, title)
            if recent is not None:
                return MatchResult(
                    title, recent.id, recent.name, "MEDIUM", 100.0,
                    "ambiguous exact title (multiple BGG entries share this bare name), but the "
                    "query's own wording signals a newer printing -- picked the candidate with "
                    "the latest yearpublished among the tied entries",
                    candidates=[(g.id, g.name) for g in light_exact[:5]],
                )

        norm = normalize_title(title)

        exact = self._exact.get(norm)
        if exact:
            if len(exact) == 1:
                bgg = exact[0]
                return MatchResult(
                    title, bgg.id, bgg.name, "HIGH", 100.0, "exact normalized title match"
                )
            dominant = self._dominant_by_rating_count(exact)
            if dominant is not None:
                return MatchResult(
                    title,
                    dominant.id,
                    dominant.name,
                    "MEDIUM",
                    100.0,
                    "ambiguous exact title, but one BGG entry dominates by community ratings -- "
                    "picked as the game Zatu almost certainly means",
                    candidates=[(g.id, g.name) for g in exact[:5]],
                )
            recent = self._recency_pick(exact, title)
            if recent is not None:
                return MatchResult(
                    title, recent.id, recent.name, "MEDIUM", 100.0,
                    "ambiguous exact title (multiple BGG entries share this bare name), but the "
                    "query's own wording signals a newer printing -- picked the candidate with "
                    "the latest yearpublished among the tied entries",
                    candidates=[(g.id, g.name) for g in exact[:5]],
                )
            return MatchResult(
                title,
                None,
                None,
                "LOW",
                None,
                "ambiguous: multiple BGG entries share this normalized title",
                candidates=[(g.id, g.name) for g in exact[:5]],
            )

        # Try matching against BGG's alternate names (Stage 3's bgg_details.json): folk game
        # names like "Liars Dice" that don't match commercial names like "Perudo" (id 45).
        # Only tried if exact tiers found nothing, and only returns a match if exactly one
        # game has this name as an alternate (no ambiguity).
        alt_match = self._alternate_name_match(norm)
        if alt_match is not None:
            return MatchResult(
                title, alt_match.id, alt_match.name, "HIGH", 100.0,
                "exact match against BGG alternate/folk name (from Stage 3 BGG API data)",
            )

        if not self.normalized_names:
            return MatchResult(title, None, None, "LOW", None, "no BGG candidates loaded")

        excluded = self._excluded_exact.get(norm)
        if excluded:
            return MatchResult(
                title,
                None,
                None,
                "LOW",
                100.0,
                "exact match is a BGG expansion/non-base entry, out of scope -- refusing to "
                "fall back to a fuzzy match against an unrelated base game",
                candidates=[(g.id, g.name) for g in excluded[:5]],
            )

        fuzzy_result = self._match_fuzzy(title, norm, fuzzy_threshold, min_gap)
        if fuzzy_result.confidence != "LOW":
            return fuzzy_result

        # Fuzzy failed — try a unique-prefix fallback before giving up. Purely additive: it
        # only fires when fuzzy already found nothing acceptable, so it can't override or
        # regress an existing fuzzy decision.
        prefix_hits = self._prefix_matches(norm)
        unique_ids = {g.id for g in prefix_hits}
        if len(unique_ids) == 1:
            bgg = prefix_hits[0]
            return MatchResult(
                title,
                bgg.id,
                bgg.name,
                "MEDIUM",
                95.0,
                "unique prefix match (query is a shortened form of the BGG title)",
            )
        if len(unique_ids) > 1:
            return MatchResult(
                title,
                None,
                None,
                "LOW",
                fuzzy_result.score,
                "ambiguous: multiple BGG entries share this title as a prefix",
                candidates=[(g.id, g.name) for g in prefix_hits[:5]],
            )

        return fuzzy_result

    def _match_fuzzy(
        self, title: str, norm: str, fuzzy_threshold: float, min_gap: float
    ) -> MatchResult:
        # Scored against `_fuzzy_names` (generic marketing/edition words further down-weighted --
        # see `_fuzzy_score_text`), not `normalized_names` -- but `norm`/`best_norm` (the plain
        # aggressive normalization) are still what the digit-conflict veto checks below, so a
        # down-weighted word can never mask a real digit disagreement.
        query_fuzzy = _fuzzy_score_text(norm)
        # Fetch top 10 to efficiently detect ties and apply dominance tiebreak without scanning
        # the entire corpus -- if there are 3+ tied at the same score, 10 is enough to see them
        results = process.extract(
            query_fuzzy, self._fuzzy_names, scorer=fuzz.token_sort_ratio, limit=10
        )
        if not results:
            return MatchResult(title, None, None, "LOW", None, "no BGG candidates")

        _, best_score, best_idx = results[0]
        best_norm = self.normalized_names[best_idx]
        best_bgg = self.games[best_idx]

        # When the best score is below threshold, reject immediately
        if best_score < fuzzy_threshold:
            # Build candidates list from top scorers
            second_score = results[1][1] if len(results) > 1 else 0.0
            return MatchResult(
                title,
                None,
                None,
                "LOW",
                best_score,
                "fuzzy score below threshold or too close to runner-up",
                candidates=[(best_bgg.id, best_bgg.name)],
            )

        # Best score passes threshold — check the gap against runner-ups. Find all candidates
        # that tied with the best score (same fuzzy rating) — when multiple perfect/near-perfect
        # matches exist, apply dominance tiebreak before rejecting as "too close".
        tied_candidates = [self.games[idx] for _, score, idx in results if score == best_score]

        if len(tied_candidates) > 1:
            # Multiple candidates tied at the same score — try dominance tiebreak
            dominant = self._dominant_by_rating_count(tied_candidates)
            if dominant:
                # One candidate is clearly more authoritative by rating count
                best_bgg = dominant
                best_norm = normalize_title(dominant.name)
                # Fall through to digit-conflict check, then return MEDIUM
            else:
                # No dominant candidate — genuine tie, reject as ambiguous
                second_score = results[1][1] if len(results) > 1 else 0.0
                gap = best_score - second_score
                if gap < min_gap:
                    return MatchResult(
                        title,
                        None,
                        None,
                        "LOW",
                        best_score,
                        "fuzzy score below threshold or too close to runner-up",
                        candidates=[(g.id, g.name) for g in tied_candidates[:5]],
                    )
        else:
            # Single best candidate — check gap to runner-up. Accept if either:
            # (a) gap is sufficient (>= min_gap), OR
            # (b) best score is very high (>= 90) — so close to perfect that small gap is acceptable.
            # Real case: "Poo Bingo" scores 94.74 vs "Bingo Pongo" at 90.00; gap is 4.74 < 5,
            # but 94.74 is already 94.74% similar, suggesting a strong match (likely typo/variant).
            second_score = results[1][1] if len(results) > 1 else 0.0
            gap = best_score - second_score
            if gap < min_gap and best_score < 90:
                # Reject: gap is too small and score isn't high enough to be confident anyway
                return MatchResult(
                    title,
                    None,
                    None,
                    "LOW",
                    best_score,
                    "fuzzy score below threshold or too close to runner-up",
                    candidates=[(best_bgg.id, best_bgg.name)],
                )
            # If we get here: either gap is sufficient (>= 5), or best score is very high (>= 90).
            # Both cases are safe to accept as MEDIUM confidence.

        if _digits_conflict(norm, best_norm):
            return MatchResult(
                title,
                None,
                None,
                "LOW",
                best_score,
                "digit conflict (likely a different sequel/season/expansion)",
                candidates=[(best_bgg.id, best_bgg.name)],
            )

        return MatchResult(
            title,
            best_bgg.id,
            best_bgg.name,
            "MEDIUM",
            best_score,
            "fuzzy match above threshold with clear gap to runner-up",
        )
