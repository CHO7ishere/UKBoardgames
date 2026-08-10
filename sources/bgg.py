"""BGG bulk-ranked-games CSV — Stage 2 offline match source (docs/spec.md §0.1, §3). Downloaded
by hand from boardgamegeek.com/data_dumps/bg_ranks while logged into a browser — no token needed
for this file, unlike the thing/search API (Stage 3). This module never makes network calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class BggRankedGame:
    id: int
    name: str
    year: int | None
    rank: int | None
    bayesaverage: float | None
    average: float | None
    usersrated: int
    is_expansion: bool


def _safe_int(value) -> int | None:
    """BGG's `rank` column is the literal string "Not Ranked" for many obscure games rather
    than a number — handled defensively here, not assumed numeric."""
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def load_bg_ranks(csv_path: str | Path) -> list[BggRankedGame]:
    """Parse BGG's bulk ranked-games CSV (id, name, yearpublished, rank, bayesaverage, average,
    usersrated, is_expansion, ... — extra columns are ignored)."""
    df = pd.read_csv(csv_path)
    games = []
    for _, row in df.iterrows():
        games.append(
            BggRankedGame(
                id=int(row["id"]),
                name=str(row["name"]),
                year=_safe_int(row.get("yearpublished")),
                rank=_safe_int(row.get("rank")),
                bayesaverage=_safe_float(row.get("bayesaverage")),
                average=_safe_float(row.get("average")),
                usersrated=int(row.get("usersrated", 0) or 0),
                is_expansion=bool(int(row.get("is_expansion", 0) or 0)),
            )
        )
    return games


def filter_base_games(
    games: list[BggRankedGame], include_expansions: bool = False
) -> list[BggRankedGame]:
    """Drop expansions by default (spec Stage 2: "you're buying playable boxes")."""
    if include_expansions:
        return games
    return [g for g in games if not g.is_expansion]
