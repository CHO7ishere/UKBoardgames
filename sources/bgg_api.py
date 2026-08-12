"""Stage 3 — the real BGG XML API2 (docs/spec.md's originally-intended path: "thing/search need
a registered app + Authorization: Bearer <token>"). Supersedes sources/bgg_versions.py's
headless-browser scraping in production now that a real token exists (2026-08-12) --
sources/bgg_versions.py is kept as a documented fallback, not deleted, but nothing calls it
anymore.

Confirmed live via scripts/probe_bgg_api.py, four rounds, before writing any of this:
- Without `Authorization: Bearer <token>`: 401 Unauthorized. With it: 200, full XML.
- `stats=1` (language_dependence poll) and `versions=1` (real per-edition data, each with a
  `<link type="language">`) combine into ONE request -- confirmed live against Marvel Champions
  (id 285774): status 200, both the poll and the versions block present together.
- Real `language_dependence` poll shape: `<poll name="language_dependence" totalvotes="N">
  <results><result level="1..5" value="<label>" numvotes="M"/>...</results></poll>` -- levels
  exactly match score.py's LOW(1-2)/MED(3)/HIGH(4-5) scale already.
  - <item type="boardgameversion"> real shape: `<canonicalname value="...">` (or a
    `<name type="primary" value="...">` fallback) plus `<link type="language" id="2187"
    value="French">` -- id "2187" is the same French-language id sources/bgg_versions.py's
    `FRENCH_LANGUAGE_ID` already used, confirmed identical (both approaches independently landed
    on the same BGG-internal id). Cross-validated against Marvel Champions: the API's
    canonicalname ("Marvel Champions: Le Jeu De Cartes", version id 468045) is character-for-
    character the same title AND id the headless-browser scraper found via the versions page.
- `<name type="alternate">` (no `versions=1` needed) has *no* language attribute at all -- it's
  every alternate name in every language mixed together (Cyrillic, Japanese, Korean, French all
  in one list with nothing to tell them apart), so it's not used here for French-edition
  detection; `versions=1`'s per-version `<link type="language">` is the only reliable signal.
- Up to 20 ids per call (spec's own note); can return HTTP 202 while BGG queues the request,
  needing a retry with backoff (also spec's own note, not yet observed live for a batch this
  small, but implemented per the documented behaviour).
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

BASE_URL = "https://boardgamegeek.com/xmlapi2"
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"
MAX_IDS_PER_CALL = 20
FRENCH_LANGUAGE_ID = "2187"

_LEVEL_TO_SCALE = {1: "LOW", 2: "LOW", 3: "MED", 4: "HIGH", 5: "HIGH"}


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _to_int(value) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except ValueError:
        return None


def _to_float(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _parse_links(item_el: ET.Element, link_type: str) -> list[dict]:
    return [
        {"id": link.get("id"), "value": link.get("value")}
        for link in item_el.findall(f'link[@type="{link_type}"]')
    ]


def _parse_alternate_names(item_el: ET.Element) -> list[str]:
    return [n.get("value") for n in item_el.findall('name[@type="alternate"]') if n.get("value")]


def _parse_statistics(item_el: ET.Element) -> dict | None:
    ratings = item_el.find("statistics/ratings")
    if ratings is None:
        return None

    def _val(tag: str) -> str | None:
        el = ratings.find(tag)
        return el.get("value") if el is not None else None

    return {
        "average": _to_float(_val("average")),
        "usersrated": _to_int(_val("usersrated")),
        "bayesaverage": _to_float(_val("bayesaverage")),
    }


def _parse_language_dependence(item_el: ET.Element) -> dict:
    """Returns `{"level": "LOW"/"MED"/"HIGH"/None, "votes": {level_int: numvotes}}` -- `level`
    is the plurality (highest-vote) result, matching how BGG's own poll UI presents a "current
    consensus." `votes` is kept as int-keyed (BGG's own 1-5 scale) for full transparency, not
    just the derived LOW/MED/HIGH bucket."""
    poll = item_el.find('poll[@name="language_dependence"]')
    if poll is None:
        return {"level": None, "votes": {}}
    votes = {}
    for result in poll.findall("./results/result"):
        level = _to_int(result.get("level"))
        numvotes = _to_int(result.get("numvotes")) or 0
        if level and numvotes > 0:
            votes[level] = numvotes
    if not votes:
        return {"level": None, "votes": {}}
    winning_level = max(votes, key=votes.get)
    return {"level": _LEVEL_TO_SCALE[winning_level], "votes": votes}


def _parse_french_editions(item_el: ET.Element) -> list[dict]:
    """Real French-edition detection needs actual per-version data (`versions=1`), not the
    plain `<name type="alternate">` list -- confirmed live that alternate names carry no
    language attribute at all. Each returned dict is `{"version_id": str, "title": str|None}`."""
    editions = []
    versions_el = item_el.find("versions")
    if versions_el is None:
        return editions
    for version_item in versions_el.findall('item[@type="boardgameversion"]'):
        has_french = any(
            link.get("id") == FRENCH_LANGUAGE_ID
            for link in version_item.findall('link[@type="language"]')
        )
        if not has_french:
            continue
        canonical = version_item.find("canonicalname")
        title = canonical.get("value") if canonical is not None else None
        if not title:
            name_el = version_item.find('name[@type="primary"]')
            title = name_el.get("value") if name_el is not None else None
        editions.append({"version_id": version_item.get("id"), "title": title})
    return editions


def parse_thing_item(item_el: ET.Element) -> dict:
    """Parses one `<item type="boardgame">` block into the *full* set of fields BGG returns for
    it (name, alternate names, description, mechanics/categories/designers/publishers/artists,
    stats, language dependence, French editions) -- not just the couple of fields Stage 5/6
    currently read. Stored in full (data/bgg_details.json) so future work never needs a second
    live fetch for data already sitting in this response."""
    bgg_id = int(item_el.get("id"))
    primary_el = item_el.find('name[@type="primary"]')
    name = primary_el.get("value") if primary_el is not None else None
    description_el = item_el.find("description")
    description = description_el.text if description_el is not None else None

    def _attr_int(tag: str) -> int | None:
        el = item_el.find(tag)
        return _to_int(el.get("value")) if el is not None else None

    lang_dep = _parse_language_dependence(item_el)
    fr_editions = _parse_french_editions(item_el)

    return {
        "bgg_id": bgg_id,
        "name": name,
        "alternate_names": _parse_alternate_names(item_el),
        "description": description,
        "yearpublished": _attr_int("yearpublished"),
        "minplayers": _attr_int("minplayers"),
        "maxplayers": _attr_int("maxplayers"),
        "playingtime": _attr_int("playingtime"),
        "mechanics": _parse_links(item_el, "boardgamemechanic"),
        "categories": _parse_links(item_el, "boardgamecategory"),
        "designers": _parse_links(item_el, "boardgamedesigner"),
        "publishers": _parse_links(item_el, "boardgamepublisher"),
        "artists": _parse_links(item_el, "boardgameartist"),
        "statistics": _parse_statistics(item_el),
        "language_level": lang_dep["level"],
        "language_votes": lang_dep["votes"],
        "fr_edition_exists": len(fr_editions) > 0,
        "fr_edition_titles": [e["title"] for e in fr_editions if e["title"]],
    }


def parse_thing_xml(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    return [parse_thing_item(item) for item in root.findall('item[@type="boardgame"]')]


@dataclass
class FetchStats:
    batches: int = 0
    retries_202: int = 0
    ids_requested: int = 0
    items_returned: int = 0
    errors: list[str] = field(default_factory=list)


def _fetch_batch_xml(
    session: requests.Session, ids: list[int], token: str, max_retries: int, backoff_sec: float,
    stats: FetchStats,
) -> str | None:
    headers = {"Authorization": f"Bearer {token}"}
    params = {"id": ",".join(str(i) for i in ids), "stats": 1, "versions": 1}
    for _ in range(max_retries):
        resp = session.get(f"{BASE_URL}/thing", params=params, headers=headers, timeout=30)
        if resp.status_code == 202:
            stats.retries_202 += 1
            time.sleep(backoff_sec)
            continue
        resp.raise_for_status()
        return resp.text
    stats.errors.append(f"ids={ids}: still 202 after {max_retries} retries")
    return None


def fetch_things(
    session: requests.Session,
    ids: list[int],
    token: str,
    rate_limit_sec: float = 5.0,
    max_retries: int = 5,
    backoff_sec: float = 5.0,
) -> tuple[list[dict], FetchStats]:
    """Batches `ids` into groups of up to MAX_IDS_PER_CALL (20, BGG's documented limit) and
    fetches each in one combined stats+versions request -- one HTTP call per 20 games, not one
    per game, which is what makes this fast enough to run against the full ~680-survivor corpus
    in minutes rather than the ~2-3 hours the headless-browser approach would have needed at one
    page load per game."""
    stats = FetchStats(ids_requested=len(ids))
    results: list[dict] = []
    unique_ids = list(dict.fromkeys(ids))  # de-dupe, preserve order
    batches = list(_chunked(unique_ids, MAX_IDS_PER_CALL))
    for i, batch in enumerate(batches):
        stats.batches += 1
        try:
            xml_text = _fetch_batch_xml(session, batch, token, max_retries, backoff_sec, stats)
        except requests.exceptions.RequestException as exc:
            stats.errors.append(f"ids={batch}: {exc}")
            xml_text = None
        if xml_text:
            items = parse_thing_xml(xml_text)
            results.extend(items)
            stats.items_returned += len(items)
        if i < len(batches) - 1:
            time.sleep(rate_limit_sec)
    return results, stats
