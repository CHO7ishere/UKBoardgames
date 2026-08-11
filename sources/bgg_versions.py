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


def fetch_french_edition_info(page, bgg_id: int) -> dict:
    """`page` is a real Playwright page object (a headless browser, not `requests` — BGG blocks
    plain HTTP with a Cloudflare challenge). Returns
    `{"fr_edition_exists": bool, "fr_edition_titles": [str, ...]}`, or `fr_edition_exists: None`
    if the slug couldn't be resolved (treat as "couldn't tell", not "no French edition")."""
    page.goto(f"{BASE_URL}/boardgame/{bgg_id}", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    slug = parse_slug_from_url(page.url)
    if not slug:
        return {"fr_edition_exists": None, "fr_edition_titles": []}

    versions_url = f"{BASE_URL}/boardgame/{bgg_id}/{slug}/versions?language={FRENCH_LANGUAGE_ID}"
    page.goto(versions_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    versions = parse_french_versions(page.content())

    return {
        "fr_edition_exists": len(versions) > 0,
        "fr_edition_titles": [v["title"] for v in versions],
    }
