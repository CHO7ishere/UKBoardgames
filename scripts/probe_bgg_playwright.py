#!/usr/bin/env python3
"""One-off diagnostic: does a real (headless) browser get past BGG's Cloudflare bot challenge,
where plain `requests` couldn't (scripts/probe_bgg_page.py confirmed a 403 "Just a moment..."
page on every URL tried)? If Playwright/Chromium can load a real game page, checks whether the
language-dependence poll and version/language data are actually present in the rendered DOM --
getting past Cloudflare is necessary but not sufficient, the data still has to be there.

Not part of the production pipeline; run manually via the probe-bgg-playwright workflow. Needs
`playwright install --with-deps chromium` first (not pre-installed on GitHub-hosted runners,
unlike this coding sandbox).
"""

from __future__ import annotations

import re
import sys

from playwright.sync_api import sync_playwright

GAMES = [
    (285774, "Marvel Champions: The Card Game"),
    (30549, "Pandemic"),
]

# User-suggested lead: BGG's versions page takes a `?language=<id>` filter
# (https://boardgamegeek.com/boardgame/162886/spirit-island/versions?language=2187) -- if this
# changes the *server* response (not just client-side JS filtering an already-fetched list), it
# could sidestep the "versions page looks identical to the main page" problem seen in the first
# probe round (the unfiltered /versions URL returned near-identical HTML to the main page,
# suggesting the real version list is loaded via a later AJAX call our fixed 6s wait didn't
# catch). Tested against Spirit Island itself (162886, the user's own example, presumably
# because it has a known French edition) plus Marvel Champions, to see whether the filtered URL
# surfaces real French-edition content either of these ways.
VERSIONS_LANGUAGE_GAMES = [
    (162886, "Spirit Island", "spirit-island"),
    (285774, "Marvel Champions: The Card Game", "marvel-champions-the-card-game"),
]
FRENCH_LANGUAGE_ID = 2187

LANGUAGE_POLL_MARKERS = [
    "Language Dependence",
    "No necessary in-game text",
    "Extensive use of text",
]


def probe(page, url: str, label: str) -> None:
    print(f"\n-- {label}: {url} --", file=sys.stderr)
    resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    print(f"  navigation status: {resp.status if resp else 'None'}", file=sys.stderr)
    # Cloudflare's JS challenge, if triggered, resolves within a few seconds in a real browser.
    page.wait_for_timeout(6000)
    title = page.title()
    print(f"  page title: {title!r}", file=sys.stderr)
    html = page.content()
    print(f"  html length: {len(html)}", file=sys.stderr)
    if "Just a moment" in title or "Just a moment" in html[:2000]:
        print("  STILL BLOCKED by Cloudflare challenge", file=sys.stderr)
        return
    print("  Cloudflare challenge NOT present -- real page loaded", file=sys.stderr)
    for marker in LANGUAGE_POLL_MARKERS:
        print(f"    {marker!r}: {'FOUND' if marker in html else 'not found'}", file=sys.stderr)


def probe_versions(page, url: str) -> None:
    print(f"\n-- versions page: {url} --", file=sys.stderr)
    resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    print(f"  navigation status: {resp.status if resp else 'None'}", file=sys.stderr)
    page.wait_for_timeout(6000)
    title = page.title()
    html = page.content()
    print(f"  page title: {title!r}", file=sys.stderr)
    print(f"  html length: {len(html)}", file=sys.stderr)
    if "Just a moment" in title or "Just a moment" in html[:2000]:
        print("  STILL BLOCKED by Cloudflare challenge", file=sys.stderr)
        return
    print("  Cloudflare challenge NOT present -- real page loaded", file=sys.stderr)
    for word in ["Français", "French", "France", "Édition française"]:
        count = html.count(word)
        print(f"    {word!r}: {count} occurrence(s)", file=sys.stderr)


def probe_versions_language_filtered(page, bgg_id: int, slug: str, name: str) -> None:
    # networkidle times out (BGG never goes fully idle -- confirmed live, 45s timeout hit on
    # every attempt, presumably persistent analytics/background requests). domcontentloaded + a
    # fixed settle wait is what actually worked in every earlier probe round.
    unfiltered_url = f"https://boardgamegeek.com/boardgame/{bgg_id}/{slug}/versions"
    filtered_url = f"{unfiltered_url}?language={FRENCH_LANGUAGE_ID}"

    print(f"\n-- unfiltered versions: {unfiltered_url} --", file=sys.stderr)
    page.goto(unfiltered_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    unfiltered_html = page.content()
    print(f"  html length: {len(unfiltered_html)}", file=sys.stderr)

    print(f"\n-- FRENCH-filtered versions: {filtered_url} --", file=sys.stderr)
    resp = page.goto(filtered_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    filtered_html = page.content()
    print(f"  navigation status: {resp.status if resp else 'None'}", file=sys.stderr)
    print(f"  html length: {len(filtered_html)}", file=sys.stderr)
    print(f"  differs from unfiltered: {filtered_html != unfiltered_html}", file=sys.stderr)

    # Look for version/edition entries -- BGG version pages typically render each edition as a
    # link to /boardgameversion/<id>/... with the edition's own name as link text.
    soup_links = re.findall(r'href="(/boardgameversion/\d+/[^"]+)"[^>]*>([^<]*)', filtered_html)
    print(f"  {len(soup_links)} /boardgameversion/ link(s) found on the filtered page", file=sys.stderr)
    for href, text in soup_links[:15]:
        print(f"    {href}  ->  {text.strip()!r}", file=sys.stderr)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        for bgg_id, name in GAMES:
            print(f"\n{'=' * 70}\n{name} (bgg_id={bgg_id})", file=sys.stderr)
            probe(page, f"https://boardgamegeek.com/boardgame/{bgg_id}", "main page")
            probe_versions(page, f"https://boardgamegeek.com/boardgame/{bgg_id}/versions")

        for bgg_id, name, slug in VERSIONS_LANGUAGE_GAMES:
            print(f"\n{'=' * 70}\n{name} (bgg_id={bgg_id}) -- language-filtered versions", file=sys.stderr)
            probe_versions_language_filtered(page, bgg_id, slug, name)

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
