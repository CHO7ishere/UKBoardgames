from pathlib import Path

from sources.bgg_versions import (
    fetch_french_edition_info,
    parse_french_versions,
    parse_slug_from_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


# --- parse_slug_from_url ---------------------------------------------------------------------


def test_parse_slug_from_url_extracts_the_real_slug():
    url = "https://boardgamegeek.com/boardgame/291457/gloomhaven-jaws-of-the-lion"
    assert parse_slug_from_url(url) == "gloomhaven-jaws-of-the-lion"


def test_parse_slug_from_url_ignores_trailing_query_string():
    url = "https://boardgamegeek.com/boardgame/162886/spirit-island?some=param"
    assert parse_slug_from_url(url) == "spirit-island"


def test_parse_slug_from_url_returns_none_when_no_slug_present():
    assert parse_slug_from_url("https://boardgamegeek.com/boardgame/291457") is None


# --- parse_french_versions --------------------------------------------------------------------


def test_parse_french_versions_dedupes_image_and_text_anchors():
    html = (FIXTURES / "bgg_versions_spirit_island_french.html").read_text()
    versions = parse_french_versions(html)
    assert len(versions) == 4  # not 8 -- each real version has two anchors, deduped by id
    assert {v["title"] for v in versions} == {"Spirit Island"}
    assert {v["version_id"] for v in versions} == {"629701", "626989", "488453", "392223"}


def test_parse_french_versions_extracts_the_real_localized_title():
    html = (FIXTURES / "bgg_versions_marvel_champions_french.html").read_text()
    versions = parse_french_versions(html)
    assert versions == [{"version_id": "468045", "title": "Marvel Champions: Le Jeu De Cartes"}]


def test_parse_french_versions_empty_page_means_no_french_edition():
    assert parse_french_versions("<html><body>no results</body></html>") == []


# --- fetch_french_edition_info (Playwright page object faked out) ----------------------------


class FakePage:
    def __init__(self, redirected_url: str, versions_html: str):
        self._redirected_url = redirected_url
        self._versions_html = versions_html
        self.url = ""
        self.goto_calls = []

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append(url)
        # First call (bare /boardgame/<id>) "redirects" to the canonical slugged URL; second
        # call (the versions page) keeps that url as-is.
        self.url = self._redirected_url if len(self.goto_calls) == 1 else url
        return None

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return self._versions_html


def test_fetch_french_edition_info_true_when_versions_found():
    versions_html = (FIXTURES / "bgg_versions_marvel_champions_french.html").read_text()
    page = FakePage(
        redirected_url="https://boardgamegeek.com/boardgame/285774/marvel-champions-the-card-game",
        versions_html=versions_html,
    )

    info = fetch_french_edition_info(page, 285774)

    assert info["fr_edition_exists"] is True
    assert info["fr_edition_titles"] == ["Marvel Champions: Le Jeu De Cartes"]
    assert page.goto_calls == [
        "https://boardgamegeek.com/boardgame/285774",
        "https://boardgamegeek.com/boardgame/285774/marvel-champions-the-card-game/versions?language=2187",
    ]


def test_fetch_french_edition_info_false_when_no_versions_found():
    page = FakePage(
        redirected_url="https://boardgamegeek.com/boardgame/1/some-game",
        versions_html="<html><body>no results</body></html>",
    )

    info = fetch_french_edition_info(page, 1)

    assert info["fr_edition_exists"] is False
    assert info["fr_edition_titles"] == []


def test_fetch_french_edition_info_none_when_slug_cannot_be_resolved():
    # Simulates a redirect that never lands on a real /boardgame/<id>/<slug> URL (e.g. an error
    # page) -- must not guess, "couldn't tell" is not the same as "confirmed no French edition".
    page = FakePage(redirected_url="https://boardgamegeek.com/error", versions_html="")

    info = fetch_french_edition_info(page, 999999)

    assert info["fr_edition_exists"] is None
    assert page.goto_calls == ["https://boardgamegeek.com/boardgame/999999"]  # never fetched versions
