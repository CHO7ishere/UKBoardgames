import json
from pathlib import Path

import pytest

from sources.zatu import (
    ZatuProduct,
    fetch_products_page,
    harvest_all,
    parse_product,
    verify_gbp_currency,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, json_data=None, text=""):
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeSession:
    """Stands in for requests.Session: serves fixed pages by call order, no network."""

    def __init__(self, pages: list[dict] | None = None, html: str | None = None):
        self._pages = pages or []
        self._html = html
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        if params is not None:
            page_num = params["page"]
            data = self._pages[page_num - 1] if page_num <= len(self._pages) else {"products": []}
            return FakeResponse(json_data=data)
        return FakeResponse(text=self._html)


@pytest.fixture
def page1():
    return json.loads((FIXTURES / "zatu_products_page1.json").read_text())


def test_parse_product_extracts_ean(page1):
    raw = page1["products"][0]
    product = parse_product(raw)
    assert product.title == "Manipulate"
    assert product.handle == "manipulate"
    assert product.ean == "5060453690123"
    assert product.in_stock is True
    assert product.min_price_gbp == 19.99
    assert product.url == "https://zatu.com/en-gb/products/manipulate"


def test_parse_product_handles_string_tags(page1):
    raw = page1["products"][1]
    product = parse_product(raw)
    assert product.tags == ["Cooperative Play", "Legacy"]


def test_parse_product_missing_barcode_is_none(page1):
    raw = page1["products"][1]
    product = parse_product(raw)
    assert product.ean is None
    assert product.in_stock is False


def test_parse_product_picks_lowest_price_across_variants(page1):
    raw = page1["products"][3]  # Brass: Birmingham, two variants
    product = parse_product(raw)
    assert product.min_price_gbp == 54.99
    assert product.in_stock is True  # standard edition available even though deluxe isn't


def test_fetch_products_page_returns_raw_list(page1):
    session = FakeSession(pages=[page1])
    result = fetch_products_page(session, page=1)
    assert len(result) == 4


def test_harvest_all_stops_on_empty_page(page1):
    session = FakeSession(pages=[page1])  # page 2 onward returns {"products": []}
    products = harvest_all(session=session, rate_limit_sec=0, max_pages=5)
    assert len(products) == 4
    assert all(isinstance(p, ZatuProduct) for p in products)
    assert session.calls == 2  # page 1 (hit), page 2 (empty, stops)


def test_verify_gbp_currency_true_for_gbp_page():
    html = (FIXTURES / "product_page_gbp.html").read_text()
    session = FakeSession(html=html)
    assert verify_gbp_currency(session) is True


def test_verify_gbp_currency_false_for_usd_page():
    html = (FIXTURES / "product_page_usd.html").read_text()
    session = FakeSession(html=html)
    assert verify_gbp_currency(session) is False
