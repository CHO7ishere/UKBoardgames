"""Stage 3 (partial) — BGG French-edition-exists via a real headless browser (docs/spec.md §3
Stage 3, §5.2's `fr_edition_exists` gap). BGG's public pages are Cloudflare-protected (confirmed
live via scripts/probe_bgg_page.py: a plain `requests` call always gets a 403 "Just a moment..."
page), but a real headless browser gets through untouched (confirmed via
scripts/probe_bgg_playwright.py). BGG's own versions page takes a `?language=<id>` filter
(user-supplied lead) that changes the *server* response — confirmed live against Spirit Island (4
real French printings) and Marvel Champions (1 French edition, titled "Marvel Champions: Le Jeu
De Cartes" — an exact match for the real Philibert listing, extracted with zero translation
guessing).

Needs the real BGG title slug, not just the numeric id — confirmed live that a slug-less
`/boardgame/<id>/versions?language=<id>` request gets redirected straight to the plain game page
(not the versions page), silently dropping the `/versions` path and the query entirely (0 results,
not an error). Resolved with an extra page load: visit the bare `/boardgame/<id>` page first
(BGG's own redirect fills in the canonical slug), read the final URL, then build the real
versions URL from that slug.

**SUPERSEDED in production (2026-08-12), kept as a documented fallback, not deleted.** Once a
real BGG API token existed, `sources/bgg_api.py`'s `thing?id=...&stats=1&versions=1` (plain
`requests`, `Authorization: Bearer <token>`, no browser needed) turned out to return the exact
same real data faster and batched (up to 20 ids per call vs. 2 page loads per game here) --
cross-validated directly against this module's own prior finding: the API's Marvel Champions
French edition is character-for-character the same title *and* the same version id (468045) this
module found independently via the versions page. `scripts/enrich_bgg_fr_edition.py` calls
`bgg_api.py` now, not this module. Left in place (module + its tests) in case token/API access
ever changes and the headless-browser path is needed again.
"""

from __future__ import annotations

import re

FRENCH_LANGUAGE_ID = 2187
BASE_URL = "https://boardgamegeek.com"

# Confirmed live: each real BGG version renders TWO anchors pointing at the same
# /boardgameversion/<id>/... URL (an image link with no text, then a text link with the
# version's display name) — dedupe by version id, keep the first non-empty title seen.
_VERSION_LINK_RE = re.compile(r'href="(/boardgameversion/(\d+)/[^"]+)"[^>]*>([^<]*)')
_SLUG_RE = re.compile(r"/boardgame/\d+/([^/?]+)")


def parse_slug_from_url(url: str) -> str | None:
    match = _SLUG_RE.search(url)
    return match.group(1) if match else None


def parse_french_versions(html: str) -> list[dict]:
    """Extracts unique French-edition version entries from a language-filtered versions page."""
    versions: dict[str, str] = {}
    for _, version_id, text in _VERSION_LINK_RE.findall(html):
        text = text.strip()
        if text and not versions.get(version_id):
            versions[version_id] = text
    return [{"version_id": vid, "title": title} for vid, title in versions.items()]


# BGG's own five-point "Language Dependence" community poll (confirmed live via
# scripts/probe_bgg_playwright.py that a real headless browser render carries this exact text --
# "Language Dependence poll text present and extractable"). Order matters: index+1 is the poll's
# own 1-5 scale, which score.py's language_points() buckets as LOW (1-2) / MED (3) / HIGH (4-5).
LANGUAGE_DEPENDENCE_LABELS = [
    "No necessary in-game text",
    "Some necessary text - easily memorized or small crib sheet",
    "Moderate in-game text - needs crib sheet or paste ups",
    "Extensive use of text - massive conversion needed to be playable",
    "Unplayable in another language",
]
_LEVEL_BY_LABEL_INDEX = {0: "LOW", 1: "LOW", 2: "MED", 3: "HIGH", 4: "HIGH"}

_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"Language Dependence", re.IGNORECASE)
# A vote count sits near its label's text in BGG's poll summary -- direction (before/after)
# isn't pinned down without a real captured page (unverified in this sandbox, BGG is
# network-blocked here -- see the caveat in enrich_bgg_fr_edition.py's docstring), so both a
# few characters before and after the label are checked and the closer number wins.
_NEARBY_NUMBER_RE = re.compile(r"\d+")
_SEARCH_WINDOW_CHARS = 4000
_NUMBER_PROXIMITY_CHARS = 30


def _plain_text(html: str) -> str:
    return _TAG_RE.sub(" ", html)


def parse_language_dependence(html: str) -> dict:
    """Best-effort extraction of BGG's language-dependence poll result from the *main* game
    page's rendered HTML (the same page load fetch_french_edition_info already does to resolve
    the title slug -- no extra request). Returns
    `{"language_level": "LOW"/"MED"/"HIGH"/None, "language_votes": {label: count, ...}}`.

    Not yet confirmed against a real captured page (this sandbox can't reach boardgamegeek.com --
    see enrich_bgg_fr_edition.py's module docstring). Deliberately markup-agnostic (works off
    stripped plain text, not CSS selectors/classes) so it degrades to "couldn't tell" rather than
    silently misreading if BGG's exact poll markup differs from what's assumed here -- a missing
    vote count for every label just means language_level stays None, same as never having
    checked at all.
    """
    text = _plain_text(html)
    heading_match = _HEADING_RE.search(text)
    if not heading_match:
        return {"language_level": None, "language_votes": {}}
    window = text[heading_match.end():heading_match.end() + _SEARCH_WINDOW_CHARS]

    votes: dict[str, int] = {}
    for label in LANGUAGE_DEPENDENCE_LABELS:
        label_match = re.search(re.escape(label), window)
        if not label_match:
            continue
        before = window[max(0, label_match.start() - _NUMBER_PROXIMITY_CHARS):label_match.start()]
        after = window[label_match.end():label_match.end() + _NUMBER_PROXIMITY_CHARS]
        before_nums = list(_NEARBY_NUMBER_RE.finditer(before))
        after_nums = list(_NEARBY_NUMBER_RE.finditer(after))
        count = None
        if before_nums and after_nums:
            # Whichever number sits closer to the label text wins.
            gap_before = len(before) - before_nums[-1].end()
            gap_after = after_nums[0].start()
            count = int((before_nums[-1] if gap_before <= gap_after else after_nums[0]).group())
        elif before_nums:
            count = int(before_nums[-1].group())
        elif after_nums:
            count = int(after_nums[0].group())
        if count is not None:
            votes[label] = count

    if not votes:
        return {"language_level": None, "language_votes": {}}

    winning_label = max(votes, key=votes.get)
    winning_index = LANGUAGE_DEPENDENCE_LABELS.index(winning_label)
    return {"language_level": _LEVEL_BY_LABEL_INDEX[winning_index], "language_votes": votes}


def fetch_french_edition_info(page, bgg_id: int) -> dict:
    """`page` is a real Playwright page object (a headless browser, not `requests` — BGG blocks
    plain HTTP with a Cloudflare challenge). Returns `{"fr_edition_exists": bool,
    "fr_edition_titles": [str, ...], "language_level": "LOW"/"MED"/"HIGH"/None,
    "language_votes": {label: count, ...}}`, or `fr_edition_exists: None` if the slug couldn't
    be resolved (treat as "couldn't tell", not "no French edition").

    Language dependence is read from the *main* game page (the same page load already needed to
    resolve the title slug for the versions-page request below) -- no extra navigation, see
    parse_language_dependence."""
    page.goto(f"{BASE_URL}/boardgame/{bgg_id}", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    language_info = parse_language_dependence(page.content())
    slug = parse_slug_from_url(page.url)
    if not slug:
        return {"fr_edition_exists": None, "fr_edition_titles": [], **language_info}

    versions_url = f"{BASE_URL}/boardgame/{bgg_id}/{slug}/versions?language={FRENCH_LANGUAGE_ID}"
    page.goto(versions_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    versions = parse_french_versions(page.content())

    return {
        "fr_edition_exists": len(versions) > 0,
        "fr_edition_titles": [v["title"] for v in versions],
        **language_info,
    }
