"""Stage 2 — offline BGG match (docs/spec.md §3-4). Matches a title against the pre-downloaded
bg_ranks.csv; no network calls. Confidence cascade per spec §4.2: exact normalized-title match
is HIGH; a fuzzy match above threshold with a clear gap to the runner-up is MEDIUM; anything
else is LOW and gets dropped — ambiguous matches are never surfaced for manual review (spec P2),
only logged to dropped.csv for later skimming.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

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

# Marketing/edition noise stripped before comparison (spec §4.1). Matched as whole phrases so
# "2nd edition"/"deluxe edition" disappear together rather than leaving a stray "2"/"deluxe".
_EDITION_NOISE_RE = re.compile(
    r"\b(board game|card game|\d+(st|nd|rd|th)\s+edition|deluxe edition|deluxe|big box|"
    r"retail edition|english edition|english|core game|core|standard edition|"
    r"anniversary edition|collector'?s edition)\b"
)
_ARTICLE_RE = re.compile(r"^(a|an|the)\s+")
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
    """Lowercase, strip accents/edition noise/punctuation/leading articles, normalise '&'->'and'
    and roman numerals, collapse whitespace (spec §4.1)."""
    text = html.unescape(title).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _TRAILING_YEAR_RE.sub(" ", text)
    text = _THOUSANDS_COMMA_RE.sub("", text)
    text = text.replace("&", " and ")
    text = _EDITION_NOISE_RE.sub(" ", text)
    text = _ROMAN_RE.sub(lambda m: _ROMAN_MAP.get(m.group(0).lower(), m.group(0)), text)
    text = _PUNCT_RE.sub(" ", text)
    text = _ARTICLE_RE.sub("", text)
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


class BggIndex:
    """Precomputed index over a bg_ranks.csv load — build once per run, match many titles."""

    def __init__(self, games: list[BggRankedGame]):
        self.games = games
        self.normalized_names = [normalize_title(g.name) for g in games]
        self._exact: dict[str, list[BggRankedGame]] = defaultdict(list)
        for game, norm in zip(games, self.normalized_names):
            self._exact[norm].append(game)

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
            )

        if not self.normalized_names:
            return MatchResult(title, None, None, "LOW", None, "no BGG candidates loaded")

        results = process.extract(
            norm, self.normalized_names, scorer=fuzz.token_sort_ratio, limit=2
        )
        if not results:
            return MatchResult(title, None, None, "LOW", None, "no BGG candidates")

        _, best_score, best_idx = results[0]
        second_score = results[1][1] if len(results) > 1 else 0.0
        best_norm = self.normalized_names[best_idx]

        if best_score < fuzzy_threshold or (best_score - second_score) < min_gap:
            return MatchResult(
                title,
                None,
                None,
                "LOW",
                best_score,
                "fuzzy score below threshold or too close to runner-up",
            )

        if _digits_conflict(norm, best_norm):
            return MatchResult(
                title,
                None,
                None,
                "LOW",
                best_score,
                "digit conflict (likely a different sequel/season/expansion)",
            )

        bgg = self.games[best_idx]
        return MatchResult(
            title,
            bgg.id,
            bgg.name,
            "MEDIUM",
            best_score,
            "fuzzy match above threshold with clear gap to runner-up",
        )
