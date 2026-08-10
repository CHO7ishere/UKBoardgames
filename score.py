"""Stage 2 quality gate + score (docs/spec.md §5.1), plus Stage 6's genre/language/composite
scoring (§5.3-5.4). Shrinks the raw BGG rating toward a neutral prior so vote count is a
continuous signal rather than a hard switch — a game with few votes is automatically scored more
cautiously, no separate rule needed.
"""

from __future__ import annotations

from dataclasses import dataclass

from sources.bgg import BggRankedGame

_MAX_SHRUNK = 8.6  # spec §5.1's quality_pts formula ceiling — not config-tunable, unlike the gate


@dataclass
class QualityResult:
    shrunk: float
    quality_pts: float
    passes_gate: bool
    label: str


def shrunk_rating(average: float, usersrated: int, shrink_m: float, prior: float) -> float:
    return (usersrated * average + shrink_m * prior) / (usersrated + shrink_m)


def quality_points(shrunk: float, min_shrunk: float) -> float:
    span = _MAX_SHRUNK - min_shrunk
    frac = (shrunk - min_shrunk) / span if span else 0.0
    return max(0.0, min(1.0, frac)) * 45


def quality_label(average: float, usersrated: int) -> str:
    """Display-only bands (spec §5.1) — labels, not gating logic."""
    if average >= 8.0 and usersrated >= 100:
        return "EXCELLENT"
    if average >= 7.5 and usersrated >= 100:
        return "STRONG"
    if average >= 8.0:
        return "UNPROVEN"
    if average >= 7.5:
        return "BORDERLINE"
    return "UNLABELED"


def evaluate_quality(
    game: BggRankedGame,
    shrink_m: float = 100.0,
    prior: float = 6.5,
    min_shrunk: float = 7.2,
    min_votes: int = 30,
) -> QualityResult:
    average = game.average or 0.0
    usersrated = game.usersrated or 0
    shrunk = shrunk_rating(average, usersrated, shrink_m, prior)
    passes = shrunk >= min_shrunk and usersrated >= min_votes
    return QualityResult(
        shrunk=shrunk,
        quality_pts=quality_points(shrunk, min_shrunk),
        passes_gate=passes,
        label=quality_label(average, usersrated),
    )


def genre_points(is_coop: bool | None, is_party: bool | None, weights: dict) -> float:
    """Spec §5.3: coop and party bonuses stack. `None` (unknown, e.g. the Zatu tag signal wasn't
    available for this product) is treated the same as False — no bonus, not a penalty."""
    pts = 0.0
    if is_coop:
        pts += weights["coop"]
    if is_party:
        pts += weights["party"]
    return pts


def language_points(level: str | None, weights: dict) -> tuple[float, bool]:
    """Spec §5.4: `level` is "LOW" (1-2), "MED" (3), "HIGH" (4-5), or None when unknown (no BGG
    language-dependence data yet — Stage 3 is blocked on the BGG token). Returns
    `(points, is_unknown)`; `is_unknown` drives the `UNKNOWN_LANG` flag badge in the Stage 7
    render, spec §6."""
    if level == "LOW":
        return weights["low"], False
    if level == "MED":
        return weights["med"], False
    if level == "HIGH":
        return weights["high"], False
    return weights["unknown"], True


def composite_score(
    advantage_pts: float, quality_pts: float, genre_pts: float, language_pts: float
) -> float:
    """Spec §5: composite = advantage + quality + genre + language."""
    return advantage_pts + quality_pts + genre_pts + language_pts
