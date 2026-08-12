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
    else:
        print("\nNo BGG_TOKEN in environment -- skipping authenticated rounds.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
