from pathlib import Path

import pytest
import requests

from sources.philibert import (
    fetch_product_page,
    search_by_ean,
    search_by_title,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code
        self.content = text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error")


class FakeSession:
    """Serves fixed HTML by URL substring, no network."""

    def __init__(self, routes: dict[str, str]):
        self._routes = routes  # substring -> fixture filename

    def get(self, url, params=None, timeout=None):
        query = (params or {}).get("search_query") or (params or {}).get("s") or ""
        key = query if query else url
        for substring, fixture in self._routes.items():
            if substring in key or substring in url:
                html = (FIXTURES / fixture).read_text()
                return FakeResponse(text=html)
        return FakeResponse(text="<html><body>no match configured</body></html>")


# --- search_by_ean ------------------------------------------------------------------------


def test_search_by_ean_finds_unique_match():
    session = FakeSession({"3701551706461": "philibert_search_ean_hit.html"})
    url = search_by_ean(session, "3701551706461")
    assert url == "https://www.philibertnet.com/fr/iello/171597-athletes-de-compete-3701551706461.html"


def test_search_by_ean_returns_none_for_empty_results():
    session = FakeSession({"9999999999999": "philibert_search_empty.html"})
    assert search_by_ean(session, "9999999999999") is None


def test_search_by_ean_returns_none_when_ean_not_in_any_link():
    # links exist (Philibert's confirmed junk-fallback behavior) but none actually contain the
    # queried EAN -> don't guess one of them.
    session = FakeSession({"0000000000000": "philibert_search_title_junk.html"})
    assert search_by_ean(session, "0000000000000") is None


# --- search_by_title -----------------------------------------------------------------------


def test_search_by_title_picks_the_best_fuzzy_match():
    session = FakeSession({"Spirit Island": "philibert_search_title_mixed.html"})
    url = search_by_title(session, "Spirit Island")
    assert url == "https://www.philibertnet.com/fr/intrafin/64223-spirit-island-5425037740173.html"


def test_search_by_title_rejects_junk_fallback_results():
    # Confirmed real behavior: a query with no real match still returns unrelated results
    # rather than an empty page -- must not accept any of them.
    session = FakeSession({"zzz_not_a_real_game": "philibert_search_title_junk.html"})
    assert search_by_title(session, "zzz_not_a_real_game") is None


def test_search_by_title_returns_none_for_truly_empty_results():
    session = FakeSession({"nothing here": "philibert_search_empty.html"})
    assert search_by_title(session, "nothing here") is None


def test_search_by_title_falls_back_to_unique_prefix_match():
    # Real scenario, fixture built from the actual live search results (probed 2026-08-10):
    # Philibert lists "Slay the Spire" under its French subtitle ("...Le Jeu de Plateau") plus
    # four accessory SKUs (spare player board, upgrade tokens, an expansion's component set)
    # that ALSO share "slay the spire" as a normalized-title prefix -- without the accessory
    # category filter, the prefix tier saw 5 candidates instead of 1 and refused to guess.
    session = FakeSession({"Slay the Spire": "philibert_search_title_prefix.html"})
    url = search_by_title(session, "Slay the Spire: The Board Game")
    assert url == "https://www.philibertnet.com/fr/matagot/130149-slay-the-spire-le-jeu-de-plateau-3760372232801.html"


def test_search_by_title_rejects_ambiguous_prefix_match():
    # Two different BGG-style subtitled editions both extend the same query prefix -- must not
    # guess, same rationale as Stage 2's BggIndex.
    session = FakeSession({"Suspects": "philibert_search_title_ambiguous_prefix.html"})
    assert search_by_title(session, "Suspects") is None


# --- fetch_product_page ---------------------------------------------------------------------


def test_fetch_product_page_extracts_features_and_price():
    session = FakeSession({"product_page": "philibert_product_page.html"})
    result = fetch_product_page(session, "product_page")
    assert result["ean"] == "3701551706461"
    assert result["language"] == "Français"
    assert result["publisher"] == "Iello"
    assert result["price_eur"] == 26.90


def test_fetch_product_page_ignores_cross_sell_price_and_stock_noise():
    # The fixture's cross-sell widget has its own price (3,59€) and an "Indisponible" accessory
    # -- must not be picked up as the primary product's price or stock signal.
    session = FakeSession({"product_page": "philibert_product_page.html"})
    result = fetch_product_page(session, "product_page")
    assert result["price_eur"] == 26.90  # not 3.59
    assert result["stock_status"] != "OUT_OF_STOCK"  # not fooled by the accessory's "Indisponible"


def test_fetch_product_page_precommande_is_in_stock():
    session = FakeSession({"product_page": "philibert_product_page.html"})
    result = fetch_product_page(session, "product_page")
    assert result["stock_status"] == "IN_STOCK"


def test_fetch_product_page_detects_in_stock():
    session = FakeSession({"in_stock": "philibert_product_in_stock.html"})
    result = fetch_product_page(session, "in_stock")
    assert result["stock_status"] == "IN_STOCK"
    assert result["price_eur"] == 34.90


def test_fetch_product_page_detects_out_of_stock():
    session = FakeSession({"out_of_stock": "philibert_product_out_of_stock.html"})
    result = fetch_product_page(session, "out_of_stock")
    assert result["stock_status"] == "OUT_OF_STOCK"
    assert result["price_eur"] == 19.90


def test_fetch_product_page_unknown_when_no_stock_container():
    session = FakeSession({"no_container": "philibert_search_ean_hit.html"})
    result = fetch_product_page(session, "no_container")
    assert result["stock_status"] == "UNKNOWN"
