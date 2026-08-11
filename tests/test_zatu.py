import json
from pathlib import Path

import pytest
import requests

from sources.zatu import (
    ZatuProduct,
    extract_ean,
    extract_image_url,
    fetch_product_detail,
    fetch_product_ean,
    fetch_product_image,
    fetch_products_page,
    fetch_stock_status,
    harvest_all,
    parse_product,
    verify_gbp_currency,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, json_data=None, text="", status_code=200):
        self._json = json_data
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json


class FakeSession:
    """Stands in for requests.Session: serves fixed pages/detail/html by URL, no network."""

    def __init__(
        self,
        pages: list[dict] | None = None,
        html: str | None = None,
        product_detail: dict | None = None,
        product_detail_404: bool = False,
    ):
        self._pages = pages or []
        self._html = html
        self._product_detail = product_detail
        self._product_detail_404 = product_detail_404
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        if params is not None:
            page_num = params["page"]
            data = self._pages[page_num - 1] if page_num <= len(self._pages) else {"products": []}
            return FakeResponse(json_data=data)
        if url.endswith(".json"):
            if self._product_detail_404:
                return FakeResponse(status_code=404)
            return FakeResponse(json_data={"product": self._product_detail or {}})
        return FakeResponse(text=self._html or "")


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
    assert product.url == "https://zatu.com/products/manipulate"


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


def test_to_dict_includes_computed_properties(page1):
    product = parse_product(page1["products"][0])
    d = product.to_dict()
    assert d["ean"] == "5060453690123"
    assert d["in_stock"] is True
    assert d["min_price_gbp"] == 19.99
    assert d["handle"] == "manipulate"  # regular fields still present too


def test_fetch_products_page_returns_raw_list(page1):
    session = FakeSession(pages=[page1])
    result = fetch_products_page(session, page=1)
    assert len(result) == 5


def test_harvest_all_stops_on_empty_page(page1):
    session = FakeSession(pages=[page1])  # page 2 onward returns {"products": []}
    products = harvest_all(session=session, rate_limit_sec=0, max_pages=5)
    assert len(products) == 5
    assert all(isinstance(p, ZatuProduct) for p in products)
    assert session.calls == 2  # page 1 (hit), page 2 (empty, stops)


def test_verify_gbp_currency_true_for_gbp_page():
    # No product_detail configured -> per-product JSON has no price_currency field ->
    # falls back to the proven meta-tag check.
    html = (FIXTURES / "product_page_gbp.html").read_text()
    session = FakeSession(html=html)
    assert verify_gbp_currency(session) is True


def test_verify_gbp_currency_false_for_usd_page():
    html = (FIXTURES / "product_page_usd.html").read_text()
    session = FakeSession(html=html)
    assert verify_gbp_currency(session) is False


def test_verify_gbp_currency_prefers_json_field_when_present():
    # If the per-product JSON does carry price_currency, use it without touching the HTML page.
    detail = {"variants": [{"price_currency": "GBP"}]}
    html = (FIXTURES / "product_page_usd.html").read_text()  # would fail if this were read
    session = FakeSession(html=html, product_detail=detail)
    assert verify_gbp_currency(session) is True


def test_verify_gbp_currency_falls_back_when_detail_endpoint_404s():
    html = (FIXTURES / "product_page_gbp.html").read_text()
    session = FakeSession(html=html, product_detail_404=True)
    assert verify_gbp_currency(session) is True


def test_fetch_product_detail_unwraps_product_key():
    session = FakeSession(product_detail={"handle": "manipulate", "variants": []})
    detail = fetch_product_detail(session, "manipulate")
    assert detail["handle"] == "manipulate"


def test_fetch_product_ean_normalizes_upc_a_to_ean13():
    # 12-digit UPC-A -> zero-padded to 13 digits.
    session = FakeSession(product_detail={"variants": [{"barcode": "681706712456"}]})
    assert fetch_product_ean(session, "brass-birmingham") == "0681706712456"


def test_fetch_product_ean_passes_through_ean13():
    session = FakeSession(product_detail={"variants": [{"barcode": "5060453690123"}]})
    assert fetch_product_ean(session, "manipulate") == "5060453690123"


def test_fetch_product_ean_none_when_no_barcode():
    session = FakeSession(product_detail={"variants": [{"barcode": None}]})
    assert fetch_product_ean(session, "gloomhaven-jaws-of-the-lion") is None


def test_extract_image_url_prefers_primary_image_field():
    product = {
        "image": {"src": "https://cdn.zatu.example/primary.jpg"},
        "images": [{"src": "https://cdn.zatu.example/gallery-0.jpg"}],
    }
    assert extract_image_url(product) == "https://cdn.zatu.example/primary.jpg"


def test_extract_image_url_falls_back_to_first_gallery_image():
    product = {"image": None, "images": [{"src": "https://cdn.zatu.example/gallery-0.jpg"}]}
    assert extract_image_url(product) == "https://cdn.zatu.example/gallery-0.jpg"


def test_extract_image_url_none_when_no_images_at_all():
    assert extract_image_url({"image": None, "images": []}) is None
    assert extract_image_url({}) is None


def test_fetch_product_image_reads_through_product_detail():
    session = FakeSession(product_detail={"image": {"src": "https://cdn.zatu.example/manipulate.jpg"}})
    assert fetch_product_image(session, "manipulate") == "https://cdn.zatu.example/manipulate.jpg"


def test_extract_ean_matches_fetch_product_ean():
    # extract_ean is the pure function fetch_product_ean now wraps -- same behavior either way.
    product = {"variants": [{"barcode": "681706712456"}]}
    assert extract_ean(product) == "0681706712456"


@pytest.mark.parametrize(
    "page_text,expected",
    [
        ("Buy now. 3+ in stock. Next day delivery.", "IN_STOCK"),
        ("Sorry, this item is currently Out of Stock.", "OUT_OF_STOCK"),
        ("Status: Back-Order — ships in 2 weeks.", "BACK_ORDER"),
        ("Order in next 4 hours for Next Day Delivery.", "PREORDER"),
        ("No recognizable status text here.", "UNKNOWN"),
    ],
)
def test_fetch_stock_status_patterns(page_text, expected):
    session = FakeSession(html=f"<html><body>{page_text}</body></html>")
    assert fetch_stock_status(session, "manipulate") == expected


def test_is_coop_and_is_party_tags(page1):
    manipulate = parse_product(page1["products"][0])  # tags: Cooperative Play, Party Games
    assert manipulate.is_coop is True
    assert manipulate.is_party is True

    brass = parse_product(page1["products"][3])  # tags: Strategy
    assert brass.is_coop is False
    assert brass.is_party is False
