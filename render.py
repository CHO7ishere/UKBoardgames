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

_ADVANTAGE_CSS_CLASS = {
    "UNAVAILABLE_FR": "adv-unavailable",
    "OUT_OF_STOCK_FR": "adv-outofstock",
    "CHEAPER_UK": "adv-cheaper",
}


def _philibert_search_url(title: str) -> str:
    return f"https://www.philibertnet.com/fr/recherche?search_query={quote(title)}"


def build_why(game: dict) -> str:
    """Spec §6: 'a one-line "why"' per row, e.g. "Not sold in France, no FR edition exists ·
    8.2 (3,400 votes) · coop · low text.\""""
    reason = game["advantage_reason"]
    parts = [reason[0].upper() + reason[1:] if reason else reason]
    parts.append(f"{game['bgg_average']:.1f} ({game['bgg_usersrated']:,} votes)")
    if game.get("zatu_is_coop"):
        parts.append("coop")
    if game.get("zatu_is_party"):
        parts.append("party")
    parts.append(_LANGUAGE_LABELS.get(game.get("bgg_language_level"), "language unknown"))
    return " · ".join(parts)


def build_flags(game: dict) -> list[str]:
    """Spec §6: flag badges for NEEDS_EYEBALL, UNKNOWN_LANG (PREORDER/VARIANT_EDITION aren't
    detected yet -- no stock-wording or SKU-variant signal is captured upstream for those)."""
    flags = []
    if game.get("needs_eyeball"):
        flags.append("NEEDS_EYEBALL")
    if game.get("language_unknown"):
        flags.append("UNKNOWN_LANG")
    return flags


def prepare_games(games: list[dict]) -> list[dict]:
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
            }
        )
    return prepared


def render_html(games: list[dict], run_metadata: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html.jinja2")
    prepared = prepare_games(games)
    return template.render(games=prepared, meta=run_metadata, filter_tags=top_category_tags(prepared))
