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

import sys

from playwright.sync_api import sync_playwright

GAMES = [
    (285774, "Marvel Champions: The Card Game"),
    (30549, "Pandemic"),
]

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

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
