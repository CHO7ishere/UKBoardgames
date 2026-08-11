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
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

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
_EDITION_NOISE_RE = re.compile(
    r"\b(board game|card game|the game|\d+(st|nd|rd|th)\s+edition|deluxe edition|deluxe|"
    r"big box|retail edition|english edition|english|core game|standard edition|"
    r"anniversary edition|collector'?s edition)\b"
)
_ARTICLE_RE = re.compile(r"\b(a|an|the)\b")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
_DIGIT_RE = re.compile(r"\d+")

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


class BggIndex:
    """Precomputed index over a bg_ranks.csv load — build once per run, match many titles."""

    def __init__(self, games: list[BggRankedGame]):
        self.games = games
        self.normalized_names = [normalize_title(g.name) for g in games]
        self._exact: dict[str, list[BggRankedGame]] = defaultdict(list)
        for game, norm in zip(games, self.normalized_names):
            self._exact[norm].append(game)

        # Sorted (normalized_name, game) pairs for O(log n) prefix lookups — see
        # `_prefix_matches`. Confirmed valuable against the real 4178-product harvest: 62 titles
        # like "Five Tribes" are a retailer's shortened form of a BGG title with a subtitle
        # ("Five Tribes: The Djinns of Naqala") and would otherwise never match at all.
        self._sorted_pairs = sorted(zip(self.normalized_names, games), key=lambda p: p[0])
        self._sorted_names = [name for name, _ in self._sorted_pairs]

    def _prefix_matches(self, norm: str) -> list[BggRankedGame]:
        """BGG games whose normalized name is `norm` followed by a space and more text — i.e.
        `norm` is a shortened, word-boundary-safe prefix of the full title."""
        prefix = norm + " "
        lo = bisect.bisect_left(self._sorted_names, prefix)
        upper_bound = prefix[:-1] + chr(ord(" ") + 1)  # next char after space
        hi = bisect.bisect_left(self._sorted_names, upper_bound)
        return [self._sorted_pairs[i][1] for i in range(lo, hi)]

    def match(
        self, title: str, fuzzy_threshold: float = 90.0, min_gap: float = 5.0
    ) -> MatchResult:
        norm = normalize_title(title)

        exact = self._exact.get(norm)
        if exact:
            if len(exact) == 1:
                bgg = exact[0]
                return MatchResult(
                    title, bgg.id, bgg.name, "HIGH", 100.0, "exact normalized title match"
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

        if not self.normalized_names:
            return MatchResult(title, None, None, "LOW", None, "no BGG candidates loaded")

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
        results = process.extract(
            norm, self.normalized_names, scorer=fuzz.token_sort_ratio, limit=2
        )
        if not results:
            return MatchResult(title, None, None, "LOW", None, "no BGG candidates")

        _, best_score, best_idx = results[0]
        second_score = results[1][1] if len(results) > 1 else 0.0
        best_norm = self.normalized_names[best_idx]

        best_bgg = self.games[best_idx]

        if best_score < fuzzy_threshold or (best_score - second_score) < min_gap:
            return MatchResult(
                title,
                None,
                None,
                "LOW",
                best_score,
                "fuzzy score below threshold or too close to runner-up",
                candidates=[(best_bgg.id, best_bgg.name)],
            )

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
