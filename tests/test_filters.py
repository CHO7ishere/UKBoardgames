import json
from pathlib import Path

from filters import filter_board_games, is_probably_accessory
from sources.zatu import parse_product

FIXTURES = Path(__file__).parent / "fixtures"


def _products():
    raw = json.loads((FIXTURES / "zatu_products_page1.json").read_text())
    return [parse_product(p) for p in raw["products"]]


def test_dice_set_flagged_as_accessory():
    products = _products()
    dice_set = next(p for p in products if p.handle == "the-mind-dice-set")
    assert is_probably_accessory(dice_set) is True


def test_real_games_not_flagged():
    products = _products()
    for p in products:
        if p.handle != "the-mind-dice-set":
            assert is_probably_accessory(p) is False


def test_filter_board_games_drops_only_accessories():
    products = _products()
    kept = filter_board_games(products)
    assert len(kept) == len(products) - 1
    assert all(p.handle != "the-mind-dice-set" for p in kept)
