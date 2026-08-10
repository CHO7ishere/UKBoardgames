import json
from pathlib import Path

from filters import filter_board_games, is_probably_accessory
from sources.zatu import parse_product

FIXTURES = Path(__file__).parent / "fixtures"


def _products():
    raw = json.loads((FIXTURES / "zatu_products_page1.json").read_text())
    return [parse_product(p) for p in raw["products"]]


_ACCESSORY_HANDLES = {"the-mind-dice-set", "wooden-meeple-set"}


def test_dice_set_flagged_as_accessory_by_keyword():
    products = _products()
    dice_set = next(p for p in products if p.handle == "the-mind-dice-set")
    assert is_probably_accessory(dice_set) is True


def test_meeple_set_flagged_as_accessory_by_product_type():
    # Title alone wouldn't trip any keyword — only product_type == "Accessories" catches this.
    products = _products()
    meeples = next(p for p in products if p.handle == "wooden-meeple-set")
    assert meeples.product_type == "Accessories"
    assert is_probably_accessory(meeples) is True


def test_real_games_not_flagged():
    products = _products()
    for p in products:
        if p.handle not in _ACCESSORY_HANDLES:
            assert is_probably_accessory(p) is False


def test_filter_board_games_drops_only_accessories():
    products = _products()
    kept = filter_board_games(products)
    assert len(kept) == len(products) - len(_ACCESSORY_HANDLES)
    assert all(p.handle not in _ACCESSORY_HANDLES for p in kept)
