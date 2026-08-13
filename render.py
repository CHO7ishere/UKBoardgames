"""Stage 7 — static HTML output (docs/spec.md §6). Renders the Stage 6 scored shortlist into a
single self-contained HTML file: an inline vanilla-JS sortable/filterable table, no CDN
dependencies (so it works offline, unlike the DataTables/Alpine suggestion in spec §7), no
server.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent / "templates"

# Zatu's `tags` field is a grab-bag: real genre/mechanic tags (Cooperative, Party, Legacy, Deck
# Building) mixed in with player-count/duration ranges, holiday marketing, and site-admin noise
# (Christmas, Next Day Delivery, Podcast Approved...) -- none of which are a "category" a buyer
# would want to filter by. Coop/party already have their own dedicated, well-tested boolean
# fields (zatu_is_coop/zatu_is_party per sources/zatu.py); this only covers the "other Zatu
# tags" a user asked to also be able to filter on.
_NOISE_TAG_RE = re.compile(
    r"^\d+[+\-–]?\d*\s*(players?|minutes?)$"
    r"|^(cooperative( play)?|party( games?)?)$",  # already covered by dedicated coop/party facets
    re.IGNORECASE,
)
_NOISE_TAG_EXACT = {
    "christmas", "valentines day", "father's day", "national board game day",
    "next day delivery", "no gift wrap", "podcast approved", "bgg golden geek",
    "golden pear", "dice tower award", "value for money", "top 5000 board games",
    "board games",
}


def clean_category_tags(tags: list[str] | None) -> list[str]:
    """Filters Zatu's raw tag list down to ones worth offering as a category filter (spec's own
    genre-bonus source, generalized per user request to expose more than just coop/party)."""
    if not tags:
        return []
    cleaned = []
    seen = set()
    for tag in tags:
        tag = tag.strip()
        key = tag.lower()
        if not tag or key in seen or key in _NOISE_TAG_EXACT or _NOISE_TAG_RE.match(tag):
            continue
        seen.add(key)
        cleaned.append(tag)
    return cleaned


def top_category_tags(games: list[dict], limit: int = 24) -> list[str]:
    """Union of every game's cleaned category tags, most-common first, capped so the filter UI
    stays usable rather than listing every tag that appears even once."""
    counts = Counter(tag for game in games for tag in game.get("category_tags", []))
    return [tag for tag, _ in counts.most_common(limit)]

_LANGUAGE_LABELS = {"LOW": "low text", "MED": "medium text", "HIGH": "heavy text"}

_DURATION_TAG_RE = re.compile(r"^\d+[+\-–]?\d*\s*minutes?$", re.IGNORECASE)
_PLAYER_COUNT_TAG_RE = re.compile(r"^\d+[+\-–]?\d*\s*players?$", re.IGNORECASE)


def extract_duration_tag(tags: list[str] | None) -> str | None:
    """The one real "N-M Minutes" tag Zatu attaches, if any -- clean_category_tags() strips this
    same tag as filter noise, but it's a genuinely useful at-a-glance signal on a card."""
    for tag in tags or []:
        if _DURATION_TAG_RE.match(tag.strip()):
            return tag.strip()
    return None


def extract_player_count_tag(tags: list[str] | None) -> str | None:
    for tag in tags or []:
        if _PLAYER_COUNT_TAG_RE.match(tag.strip()):
            return tag.strip()
    return None

_ADVANTAGE_CSS_CLASS = {
    "UNAVAILABLE_FR": "adv-unavailable",
    "OUT_OF_STOCK_FR": "adv-outofstock",
    "CHEAPER_UK": "adv-cheaper",
}


def _philibert_search_url(title: str) -> str:
    return f"https://www.philibertnet.com/fr/recherche?search_query={quote(title)}"


def _bgg_search_url(title: str) -> str:
    return f"https://boardgamegeek.com/geeksearch.php?action=search&objecttype=boardgame&q={quote(title)}"


_MATCH_CATEGORY_LABELS = {
    "NO_CONFIDENT_MATCH": "No confident BGG match",
    "AMBIGUOUS_EXACT": "Ambiguous — multiple BGG editions share this title",
    "AMBIGUOUS_PREFIX": "Ambiguous — multiple BGG entries share this as a subtitle prefix",
    "DIGIT_CONFLICT": "Possible mismatch — looks like a different numbered sequel/expansion",
}


def build_closest_bgg_guess(game: dict) -> str | None:
    """A one-line "closest BGG guess" for a game Stage 2 couldn't confidently match, so a human
    can eyeball a dropped title and judge "near-miss worth a closer look" vs "genuinely not on
    BGG" without re-running the matcher by hand."""
    candidates = game.get("bgg_candidates") or []
    if not candidates:
        return None
    names = [c["bgg_name"] for c in candidates[:3]]
    label = ", ".join(names)
    if len(candidates) > 3:
        label += f", +{len(candidates) - 3} more"
    score = game.get("match_score")
    if score is not None and len(candidates) == 1:
        label += f" ({score:.0f}% similar)"
    return label


def build_why(game: dict) -> str:
    """Spec §6: 'a one-line "why"' per row, e.g. "Not sold in France, no FR edition exists ·
    8.2 (3,400 votes) · coop · low text." Coop/party/duration/player-count now get their own
    dedicated card badges (see extract_duration_tag/extract_player_count_tag) rather than living
    only in this text, so they're not repeated here. The language clause is only included when a
    real level is known (2026-08-11: every row was UNKNOWN before Stage 3's language scraping
    landed, making "language unknown" pure noise repeated on literally every card -- omitted
    entirely rather than stated as a universal disclaimer; once real LOW/MED/HIGH data exists for
    a game this shows it, silence for the rest is the correct default)."""
    reason = game["advantage_reason"]
    parts = [reason[0].upper() + reason[1:] if reason else reason]
    parts.append(f"{game['bgg_average']:.1f} ({game['bgg_usersrated']:,} votes)")
    language_label = _LANGUAGE_LABELS.get(game.get("bgg_language_level"))
    if language_label:
        parts.append(language_label)
    return " · ".join(parts)


def build_flags(game: dict) -> list[str]:
    """Spec §6: flag badge for NEEDS_EYEBALL (PREORDER/VARIANT_EDITION aren't detected yet -- no
    stock-wording or SKU-variant signal is captured upstream for those). UNKNOWN_LANG is
    deliberately not surfaced as a per-row badge -- see build_why's docstring."""
    flags = []
    if game.get("needs_eyeball"):
        flags.append("NEEDS_EYEBALL")
    return flags


def prepare_games(
    games: list[dict],
    excluded_handles: set[str] | None = None,
    favorited_handles: set[str] | None = None,
) -> list[dict]:
    excluded_handles = excluded_handles or set()
    favorited_handles = favorited_handles or set()
    prepared = []
    for game in games:
        prepared.append(
            {
                **game,
                "why": build_why(game),
                "flags": build_flags(game),
                "advantage_css_class": _ADVANTAGE_CSS_CLASS.get(game["advantage_verdict"], ""),
                "philibert_link_url": game.get("philibert_url")
                or _philibert_search_url(game["zatu_title"]),
                "philibert_link_is_search": game.get("philibert_url") is None,
                "category_tags": clean_category_tags(game.get("zatu_tags")),
                "duration_tag": extract_duration_tag(game.get("zatu_tags")),
                "player_count_tag": extract_player_count_tag(game.get("zatu_tags")),
                "user_excluded": game["zatu_handle"] in excluded_handles,
                "user_favorited": game["zatu_handle"] in favorited_handles,
            }
        )
    return prepared


# User's explicit framing (2026-08-11): "remove all the titles removed for a good reason
# (typically the extensions) and only keep the ones where we tried to find a match on bgg and
# failed." AMBIGUOUS_EXACT/AMBIGUOUS_PREFIX/DIGIT_CONFLICT/MATCHES_EXCLUDED_EXPANSION all found a
# real BGG candidate (or several) and declined for a specific, already-understood reason -- not
# a genuine "we looked and there's nothing" case. NO_CONFIDENT_MATCH is the only bucket where
# Stage 2 tried and found no candidate at all, which is the one worth a human eyeballing for a
# missed gem. The full, untrimmed list stays in data/unmatched_games.json for transparency --
# this filter is display-only, applied here rather than at Stage 2.
_DISPLAY_MATCH_CATEGORIES = {"NO_CONFIDENT_MATCH"}


def prepare_unmatched(
    games: list[dict],
    excluded_handles: set[str] | None = None,
    favorited_handles: set[str] | None = None,
) -> list[dict]:
    """Games Stage 2 could never confidently match to BGG at all (not just failed the quality
    gate) -- no score/quality data exists for these, so they can never reach the scored
    shortlist, but they're still real Zatu listings worth a human's own eyeball. See
    scripts/match_bgg.py's `run()`. Only NO_CONFIDENT_MATCH is shown -- see
    _DISPLAY_MATCH_CATEGORIES."""
    excluded_handles = excluded_handles or set()
    favorited_handles = favorited_handles or set()
    prepared = []
    for game in games:
        if game.get("match_category") not in _DISPLAY_MATCH_CATEGORIES:
            continue
        prepared.append(
            {
                **game,
                "match_category_label": _MATCH_CATEGORY_LABELS.get(
                    game.get("match_category"), game.get("match_category")
                ),
                "closest_bgg_guess": build_closest_bgg_guess(game),
                "bgg_search_url": _bgg_search_url(game["zatu_title"]),
                "category_tags": clean_category_tags(game.get("zatu_tags")),
                "user_excluded": game["zatu_handle"] in excluded_handles,
                "user_favorited": game["zatu_handle"] in favorited_handles,
            }
        )
    return prepared


def render_html(
    games: list[dict],
    run_metadata: dict,
    unmatched_games: list[dict] | None = None,
    excluded_handles: set[str] | None = None,
    favorited_handles: set[str] | None = None,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html.jinja2")
    prepared = prepare_games(games, excluded_handles, favorited_handles)
    prepared_unmatched = prepare_unmatched(unmatched_games or [], excluded_handles, favorited_handles)
    return template.render(
        games=prepared,
        meta=run_metadata,
        filter_tags=top_category_tags(prepared),
        unmatched_games=prepared_unmatched,
        unmatched_filter_tags=top_category_tags(prepared_unmatched),
    )
