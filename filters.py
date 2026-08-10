"""Stage 1 — light board-game filter (docs/spec.md §3). Stage 0's collection is already
game-scoped, so this only drops obvious non-game listings by title keyword; Stage 2's BGG
match is the real quality gate.
"""

from __future__ import annotations

from sources.zatu import ZatuProduct

_ACCESSORY_KEYWORDS = (
    "sleeve",
    "sleeves",
    "playmat",
    "play mat",
    "dice tower",
    "storage box",
    "organizer",
    "organiser",
    "promo card",
    "gift card",
    "miniature paint",
    "d&d dice",
    "dice set",
    "token set",
    "insert",
    "carrying case",
)


def is_probably_accessory(product: ZatuProduct) -> bool:
    title = product.title.lower()
    return any(keyword in title for keyword in _ACCESSORY_KEYWORDS)


def filter_board_games(products: list[ZatuProduct]) -> list[ZatuProduct]:
    return [p for p in products if not is_probably_accessory(p)]
