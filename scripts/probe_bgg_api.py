#!/usr/bin/env python3
"""One-off diagnostic: now that a real BGG API token exists (BGG_TOKEN secret, added 2026-08-12),
check what the *real* BGG XML API2 (`thing`/`search`) actually returns -- with and without the
`Authorization: Bearer` header -- before building any real Stage 3 code against it. This
sandbox can't reach boardgamegeek.com at all, so nothing here has been verified yet; read the
results in the job log, nothing is committed.

Specifically checking:
- Does the classic public endpoint (https://boardgamegeek.com/xmlapi2/thing) still work with
  plain `requests` (unlike the HTML pages, which are Cloudflare-blocked), or does it also need
  a browser?
- Does adding `Authorization: Bearer <token>` change the response (unlock more data, avoid a
  202-queued response, avoid a rate limit) or is it a no-op / rejected?
- Real shape of the language-dependence poll data (`<poll name="language_dependence">`) and
  mechanics/versions data in the `thing` response, so the real Stage 3 parser can be built
  against confirmed real XML, not assumed schema.

Not part of the production pipeline -- run manually via the probe-bgg-api workflow.
"""

from __future__ import annotations

import os
import sys
import time

import requests

BASE_URL = "https://boardgamegeek.com/xmlapi2"
USER_AGENT = "UKBoardgamesAdvisor/1.0 (personal one-off tool; contact: mdeygout@gmail.com)"

# A spread of real ids already used elsewhere in this project's probes/docs, so results are
# directly comparable to what's already known from the headless-browser approach.
THING_IDS = [
    174430,  # Gloomhaven -- known real French edition + language-dependence data (headless probe)
    285774,  # Marvel Champions: The Card Game -- known real French edition title
    437705,  # Horrified: Dungeons & Dragons -- user's own example for language dependence
]


def probe_thing(session: requests.Session, ids: list[int], token: str | None, label: str) -> None:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{BASE_URL}/thing"
    params = {"id": ",".join(str(i) for i in ids), "stats": 1}
    print(f"\n-- thing ({label}): {url} ids={ids} --", file=sys.stderr)
    resp = session.get(url, params=params, headers=headers, timeout=30)
    print(f"  status: {resp.status_code}", file=sys.stderr)
    print(f"  headers: {dict(resp.headers)}", file=sys.stderr)
    body = resp.text
    print(f"  body length: {len(body)}", file=sys.stderr)
    if resp.status_code == 202:
        print("  202 -- BGG is queuing the request, retrying after 5s...", file=sys.stderr)
        time.sleep(5)
        resp = session.get(url, params=params, headers=headers, timeout=30)
        print(f"  retry status: {resp.status_code}", file=sys.stderr)
        body = resp.text
        print(f"  retry body length: {len(body)}", file=sys.stderr)
    # Print the raw body (truncated) so the real XML schema is visible in the job log.
    print("  --- body (first 2000 chars) ---", file=sys.stderr)
    print(body[:2000], file=sys.stderr)
    print("  --- language_dependence poll block (exact real structure) ---", file=sys.stderr)
    idx = body.find('poll name="language_dependence"')
    if idx != -1:
        start = body.rfind("<poll", 0, idx)
        end = body.find("</poll>", idx)
        print(body[start:end + len("</poll>")], file=sys.stderr)
    else:
        print("  NOT FOUND in this response", file=sys.stderr)
    print("  --- boardgamemechanic / boardgamecategory link tags (first item only) ---", file=sys.stderr)
    first_item_end = body.find("</item>")
    first_item = body[:first_item_end]
    import re as _re
    for m in _re.finditer(r'<link type="(boardgamemechanic|boardgamecategory)"[^/]*/>', first_item):
        print("   ", m.group(0), file=sys.stderr)
    print("  --- alternate (localized) names, first item only ---", file=sys.stderr)
    for m in _re.finditer(r'<name type="alternate"[^/]*/>', first_item):
        print("   ", m.group(0), file=sys.stderr)


def probe_versions(session: requests.Session, ids: list[int], token: str) -> None:
    """Real French-edition-exists needs actual *version* data with a language tag, not the
    `thing` response's plain `<name type="alternate">` list (confirmed via round 1: those
    alternate names carry no language attribute at all -- Cyrillic/Japanese/Korean/French names
    all mixed together with no way to tell which is which). The classic API's `versions=1` param
    is the documented way to get real `<item type="boardgameversion">` entries, each with
    `<link type="language" value="...">` -- this checks the *real* shape before assuming it.
    Uses ids already cross-checked against the existing headless-browser scraper's real findings
    (Spirit Island: 4 French printings; Marvel Champions: exactly 1, "Marvel Champions: Le Jeu De
    Cartes") so the API result can be directly compared against already-confirmed truth.
    """
    headers = {"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/thing"
    params = {"id": ",".join(str(i) for i in ids), "versions": 1}
    print(f"\n-- thing versions=1: {url} ids={ids} --", file=sys.stderr)
    resp = session.get(url, params=params, headers=headers, timeout=30)
    print(f"  status: {resp.status_code}", file=sys.stderr)
    body = resp.text
    if resp.status_code == 202:
        print("  202 -- retrying after 5s...", file=sys.stderr)
        time.sleep(5)
        resp = session.get(url, params=params, headers=headers, timeout=30)
        print(f"  retry status: {resp.status_code}", file=sys.stderr)
        body = resp.text
    print(f"  body length: {len(body)}", file=sys.stderr)

    import re as _re

    # Print each <item type="boardgameversion"> block in full, but only ones that actually
    # mention French, to keep the log readable against a potentially huge versions list.
    version_items = _re.findall(
        r'<item type="boardgameversion"[^>]*>.*?</item>', body, flags=_re.DOTALL
    )
    print(f"  {len(version_items)} total boardgameversion items found", file=sys.stderr)
    french_items = [v for v in version_items if "French" in v or "Français" in v]
    print(f"  {len(french_items)} mention French/Français anywhere in the block", file=sys.stderr)
    for v in french_items[:6]:
        print("  ---", file=sys.stderr)
        print(v[:1500], file=sys.stderr)


def probe_combined_stats_and_versions(session: requests.Session, bgg_id: int, token: str) -> None:
    """Does stats=1 and versions=1 work together in one request (one call per batch instead of
    two)? Both were only probed separately so far."""
    headers = {"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/thing"
    params = {"id": bgg_id, "stats": 1, "versions": 1}
    print(f"\n-- thing stats=1&versions=1 combined: {url} id={bgg_id} --", file=sys.stderr)
    resp = session.get(url, params=params, headers=headers, timeout=30)
    print(f"  status: {resp.status_code}", file=sys.stderr)
    body = resp.text
    print(f"  body length: {len(body)}", file=sys.stderr)
    has_lang_dep = "language_dependence" in body
    has_versions = 'type="boardgameversion"' in body
    has_french_link = 'type="language" id="2187"' in body
    print(f"  has language_dependence poll: {has_lang_dep}", file=sys.stderr)
    print(f"  has boardgameversion items: {has_versions}", file=sys.stderr)
    print(f"  has language link (French): {has_french_link}", file=sys.stderr)


def probe_search(session: requests.Session, query: str, token: str | None, label: str) -> None:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{BASE_URL}/search"
    params = {"query": query, "type": "boardgame"}
    print(f"\n-- search ({label}): {url} query={query!r} --", file=sys.stderr)
    resp = session.get(url, params=params, headers=headers, timeout=30)
    print(f"  status: {resp.status_code}", file=sys.stderr)
    body = resp.text
    print(f"  body length: {len(body)}", file=sys.stderr)
    print(body[:2000], file=sys.stderr)


def main() -> int:
    token = os.environ.get("BGG_TOKEN")
    print(f"BGG_TOKEN present: {bool(token)}", file=sys.stderr)

    session = requests.Session()

    # Round 1: no auth header at all -- is the classic API even reachable from plain requests,
    # and does it already return full data without a token?
    probe_thing(session, THING_IDS, token=None, label="no auth")
    time.sleep(5)

    # Round 2: with the real Bearer token -- does anything change?
    if token:
        probe_thing(session, THING_IDS, token=token, label="with Bearer token")
        time.sleep(5)
        probe_search(session, "Gloomhaven", token=token, label="with Bearer token")
        time.sleep(5)
        # Spirit Island (162886) and Marvel Champions (285774) -- real French-edition ground
        # truth already confirmed via the headless-browser scraper (4 printings / exactly 1).
        probe_versions(session, [162886, 285774], token=token)
        time.sleep(5)
        probe_combined_stats_and_versions(session, 285774, token=token)
    else:
        print("\nNo BGG_TOKEN in environment -- skipping authenticated rounds.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
