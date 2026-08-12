# tests/fixtures/bgg_api_thing_gloomhaven_marvel_champions.xml is reconstructed from real
# captured output of scripts/probe_bgg_api.py (2026-08-12), run live via GitHub Actions against
# https://boardgamegeek.com/xmlapi2/thing?id=174430,285774&stats=1&versions=1 with a real
# Authorization: Bearer token. Structure, tag names, and attribute values for
# name/description/yearpublished/minplayers/maxplayers/categories/mechanics/language_dependence
# (Gloomhaven, id 174430) and the boardgameversion/canonicalname/language-link block (Marvel
# Champions, id 285774) are all real, taken verbatim from the captured job log. statistics/
# average etc. numeric values were not captured in the log's truncated output and are
# placeholders (not asserted on by any test below) -- everything the tests actually check
# against is real.

from pathlib import Path

from sources.bgg_api import (
    FetchStats,
    _chunked,
    _parse_french_editions,
    _parse_language_dependence,
    fetch_things,
    parse_thing_item,
    parse_thing_xml,
)
import xml.etree.ElementTree as ET

FIXTURES = Path(__file__).parent / "fixtures"
REAL_XML = (FIXTURES / "bgg_api_thing_gloomhaven_marvel_champions.xml").read_text()


# --- parse_thing_xml / parse_thing_item, against real captured data ----------------------------


def test_parse_thing_xml_returns_one_dict_per_item():
    items = parse_thing_xml(REAL_XML)
    assert len(items) == 2
    assert {i["bgg_id"] for i in items} == {174430, 285774}


def test_parse_thing_item_gloomhaven_basic_fields():
    items = {i["bgg_id"]: i for i in parse_thing_xml(REAL_XML)}
    gh = items[174430]
    assert gh["name"] == "Gloomhaven"
    assert "Gloomhaven: Aventures à Havrenuit" in gh["alternate_names"]
    assert gh["yearpublished"] == 2017
    assert gh["minplayers"] == 1
    assert gh["maxplayers"] == 4
    assert {"id": "2023", "value": "Cooperative Game"} in gh["mechanics"]
    assert {"id": "1022", "value": "Adventure"} in gh["categories"]
    assert gh["statistics"]["usersrated"] == 67504


def test_parse_thing_item_gloomhaven_language_dependence_picks_plurality():
    # Real captured poll: totalvotes=72, level 4 ("Extensive use of text...") has 48 of them,
    # the clear plurality winner -> HIGH per score.py's LOW(1-2)/MED(3)/HIGH(4-5) scale.
    items = {i["bgg_id"]: i for i in parse_thing_xml(REAL_XML)}
    gh = items[174430]
    assert gh["language_level"] == "HIGH"
    assert gh["language_votes"] == {1: 1, 3: 2, 4: 48, 5: 21}  # level 2 (0 votes) dropped


def test_parse_thing_item_gloomhaven_no_versions_data_means_no_fr_edition_claim():
    # This fixture item has no <versions> block at all (Gloomhaven wasn't the versions=1 probe
    # target) -- must report "we don't know", not "no French edition exists".
    items = {i["bgg_id"]: i for i in parse_thing_xml(REAL_XML)}
    gh = items[174430]
    assert gh["fr_edition_exists"] is False
    assert gh["fr_edition_titles"] == []


def test_parse_thing_item_marvel_champions_real_french_edition():
    # Real captured versions block: canonicalname "Marvel Champions: Le Jeu De Cartes", version
    # id 468045, <link type="language" id="2187" value="French"> -- exact match to what
    # sources/bgg_versions.py's headless-browser scraper independently found via the versions
    # page (same title, same id) -- cross-validated, not just internally consistent.
    items = {i["bgg_id"]: i for i in parse_thing_xml(REAL_XML)}
    mc = items[285774]
    assert mc["fr_edition_exists"] is True
    assert mc["fr_edition_titles"] == ["Marvel Champions: Le Jeu De Cartes"]
    assert mc["language_level"] == "MED"  # level 3 has 8 of 10 real captured votes


# --- _parse_language_dependence / _parse_french_editions, edge cases ---------------------------


def test_parse_language_dependence_none_when_no_poll():
    item = ET.fromstring('<item type="boardgame" id="1"><name type="primary" value="X"/></item>')
    assert _parse_language_dependence(item) == {"level": None, "votes": {}}


def test_parse_language_dependence_none_when_poll_present_but_zero_votes():
    xml = """
    <item type="boardgame" id="1">
      <poll name="language_dependence" totalvotes="0">
        <results>
          <result level="1" value="No necessary in-game text" numvotes="0" />
        </results>
      </poll>
    </item>
    """
    item = ET.fromstring(xml)
    assert _parse_language_dependence(item) == {"level": None, "votes": {}}


def test_parse_french_editions_ignores_non_french_versions():
    xml = """
    <item type="boardgame" id="1">
      <versions>
        <item type="boardgameversion" id="1">
          <canonicalname value="Some German Edition" />
          <link type="language" id="2184" value="German" />
        </item>
      </versions>
    </item>
    """
    item = ET.fromstring(xml)
    assert _parse_french_editions(item) == []


def test_parse_french_editions_falls_back_to_primary_name_when_no_canonicalname():
    xml = """
    <item type="boardgame" id="1">
      <versions>
        <item type="boardgameversion" id="1">
          <name type="primary" value="Edition Francaise" />
          <link type="language" id="2187" value="French" />
        </item>
      </versions>
    </item>
    """
    item = ET.fromstring(xml)
    editions = _parse_french_editions(item)
    assert editions == [{"version_id": "1", "title": "Edition Francaise"}]


# --- fetch_things (session faked out) -----------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)  # one per .get() call, in order
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self._responses.pop(0)


def test_chunked_splits_into_groups_of_the_given_size():
    assert list(_chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_fetch_things_batches_by_20_and_dedupes(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    ids = list(range(1, 25))  # 24 unique ids -> 2 batches of 20 + 4
    session = _FakeSession([_FakeResponse(text=REAL_XML), _FakeResponse(text=REAL_XML)])

    results, stats = fetch_things(session, ids, token="fake-token", rate_limit_sec=0)

    assert len(session.calls) == 2
    assert session.calls[0]["headers"]["Authorization"] == "Bearer fake-token"
    assert session.calls[0]["params"]["stats"] == 1
    assert session.calls[0]["params"]["versions"] == 1
    assert stats.batches == 2
    assert stats.items_returned == 4  # 2 items per fake response x 2 batches


def test_fetch_things_dedupes_repeated_ids(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    session = _FakeSession([_FakeResponse(text=REAL_XML)])

    _, stats = fetch_things(session, [1, 1, 1], token="t", rate_limit_sec=0)

    assert stats.batches == 1  # deduped to a single id before batching
    assert len(session.calls) == 1


def test_fetch_things_retries_on_202_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    session = _FakeSession([_FakeResponse(status_code=202, text=""), _FakeResponse(text=REAL_XML)])

    results, stats = fetch_things(session, [1], token="t", rate_limit_sec=0, backoff_sec=0)

    assert len(session.calls) == 2  # first 202, retried once
    assert stats.retries_202 == 1
    assert len(results) == 2


def test_fetch_things_gives_up_after_max_retries_and_records_an_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    session = _FakeSession([_FakeResponse(status_code=202, text="") for _ in range(3)])

    results, stats = fetch_things(
        session, [1], token="t", rate_limit_sec=0, max_retries=3, backoff_sec=0
    )

    assert results == []
    assert len(stats.errors) == 1
    assert "202" in stats.errors[0]


def test_fetch_things_survives_a_request_exception(monkeypatch):
    import requests

    monkeypatch.setattr("time.sleep", lambda s: None)

    class _RaisingSession:
        def get(self, *a, **kw):
            raise requests.exceptions.ConnectionError("boom")

    results, stats = fetch_things(_RaisingSession(), [1], token="t", rate_limit_sec=0)

    assert results == []
    assert len(stats.errors) == 1
    assert "boom" in stats.errors[0]


def test_fetch_stats_default_construction():
    stats = FetchStats()
    assert stats.batches == 0
    assert stats.errors == []
