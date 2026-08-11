"""Stage 1 — light board-game filter (docs/spec.md §3). Stage 0's collection is already
game-scoped, so this only drops obvious non-game listings; Stage 2's BGG match is the real
quality gate.

`product_type == "Accessories"` is dropped outright — confirmed against the first real harvest
(4178 products) as a clean, unambiguous category (81 products). Other non-"Board Games" types
seen in the same harvest (Miniatures, Books, Puzzles, Trading Card Games — 28 products total) are
deliberately left alone: dropping them here risks losing genuine crossover games with no upside,
since Stage 2's BGG match is the real gate regardless.
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


def is_probably_accessory_fields(product_type: str | None, title: str) -> bool:
    """Same check as `is_probably_accessory`, taking plain fields instead of a `ZatuProduct` --
    for callers working off the committed JSON's raw dicts (e.g. the unmatched-games list),
    which don't need a full `ZatuProduct` just to run this one check."""
    if product_type == "Accessories":
        return True
    title = title.lower()
    return any(keyword in title for keyword in _ACCESSORY_KEYWORDS)


def is_probably_accessory(product: ZatuProduct) -> bool:
    return is_probably_accessory_fields(product.product_type, product.title)


def filter_board_games(products: list[ZatuProduct]) -> list[ZatuProduct]:
    return [p for p in products if not is_probably_accessory(p)]
