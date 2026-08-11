from pathlib import Path

from sources.bgg_versions import (
    fetch_french_edition_info,
    parse_french_versions,
    parse_language_dependence,
    parse_slug_from_url,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Synthetic, not captured from a real page -- this sandbox can't reach boardgamegeek.com (see
# enrich_bgg_fr_edition.py's module docstring), so parse_language_dependence is only verified
# against a plausible reconstruction of BGG's own five-label poll, not real markup. Needs a live
# GitHub Actions dispatch to confirm the parser against the actual rendered page.
_SYNTHETIC_POLL_NUMBER_BEFORE = """
<div class="poll">
  <h3>Language Dependence</h3>
  <table>
    <tr><td class="votes">66</td><td>No necessary in-game text</td></tr>
    <tr><td class="votes">40</td><td>Some necessary text - easily memorized or small crib sheet</td></tr>
    <tr><td class="votes">10</td><td>Moderate in-game text - needs crib sheet or paste ups</td></tr>
    <tr><td class="votes">2</td><td>Extensive use of text - massive conversion needed to be playable</td></tr>
    <tr><td class="votes">1</td><td>Unplayable in another language</td></tr>
  </table>
</div>
"""

_SYNTHETIC_POLL_NUMBER_AFTER = """
<div class="poll">
  <h3>Language Dependence</h3>
  <ul>
    <li>No necessary in-game text (2 votes)</li>
    <li>Some necessary text - easily memorized or small crib sheet (5 votes)</li>
    <li>Moderate in-game text - needs crib sheet or paste ups (30 votes)</li>
    <li>Extensive use of text - massive conversion needed to be playable (4 votes)</li>
    <li>Unplayable in another language (1 votes)</li>
  </ul>
</div>
"""


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


# --- parse_language_dependence -----------------------------------------------------------------


def test_parse_language_dependence_number_before_label_picks_the_plurality_winner():
    info = parse_language_dependence(_SYNTHETIC_POLL_NUMBER_BEFORE)
    assert info["language_level"] == "LOW"  # "No necessary in-game text" got the most votes (66)
    assert info["language_votes"]["No necessary in-game text"] == 66


def test_parse_language_dependence_number_after_label_also_works():
    info = parse_language_dependence(_SYNTHETIC_POLL_NUMBER_AFTER)
    # "Moderate in-game text..." (index 2) got the most votes (30) -> MED
    assert info["language_level"] == "MED"
    assert info["language_votes"]["Moderate in-game text - needs crib sheet or paste ups"] == 30


def test_parse_language_dependence_high_when_extensive_text_wins():
    html = """
    <h3>Language Dependence</h3>
    <div>2 No necessary in-game text</div>
    <div>1 Some necessary text - easily memorized or small crib sheet</div>
    <div>1 Moderate in-game text - needs crib sheet or paste ups</div>
    <div>50 Extensive use of text - massive conversion needed to be playable</div>
    <div>3 Unplayable in another language</div>
    """
    info = parse_language_dependence(html)
    assert info["language_level"] == "HIGH"


def test_parse_language_dependence_none_when_no_language_dependence_heading():
    assert parse_language_dependence("<html><body>nothing relevant here</body></html>") == {
        "language_level": None,
        "language_votes": {},
    }


def test_parse_language_dependence_none_when_heading_present_but_no_labels_found():
    # Heading found but the poll itself didn't render (e.g. zero votes cast) -- "couldn't tell"
    # degrades to None rather than guessing.
    html = "<h3>Language Dependence</h3><p>No votes yet.</p>"
    assert parse_language_dependence(html) == {"language_level": None, "language_votes": {}}


# --- fetch_french_edition_info (Playwright page object faked out) ----------------------------


class FakePage:
    def __init__(self, redirected_url: str, versions_html: str, main_page_html: str = ""):
        self._redirected_url = redirected_url
        self._versions_html = versions_html
        self._main_page_html = main_page_html
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
        # First goto (main page) reads language dependence; second (versions page) reads
        # French-edition links -- fetch_french_edition_info calls .content() once per page.
        return self._main_page_html if len(self.goto_calls) == 1 else self._versions_html


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


def test_fetch_french_edition_info_also_returns_language_dependence_from_the_main_page():
    # Same page load already used for the slug redirect also carries language dependence -- no
    # extra navigation needed.
    page = FakePage(
        redirected_url="https://boardgamegeek.com/boardgame/285774/marvel-champions-the-card-game",
        versions_html="<html><body>no results</body></html>",
        main_page_html=_SYNTHETIC_POLL_NUMBER_BEFORE,
    )

    info = fetch_french_edition_info(page, 285774)

    assert info["language_level"] == "LOW"
    assert page.goto_calls == [
        "https://boardgamegeek.com/boardgame/285774",
        "https://boardgamegeek.com/boardgame/285774/marvel-champions-the-card-game/versions?language=2187",
    ]  # confirms no extra navigation was added for language data


def test_fetch_french_edition_info_language_level_none_when_slug_unresolved():
    page = FakePage(
        redirected_url="https://boardgamegeek.com/error",
        versions_html="",
        main_page_html=_SYNTHETIC_POLL_NUMBER_BEFORE,
    )

    info = fetch_french_edition_info(page, 999999)

    # Language dependence is still read from the one page load that did happen, even though the
    # French-edition check itself couldn't proceed past the unresolved slug.
    assert info["language_level"] == "LOW"
