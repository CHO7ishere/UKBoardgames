import re

import pytest

from render import (
    build_closest_bgg_guess,
    build_flags,
    build_why,
    clean_category_tags,
    prepare_games,
    prepare_unmatched,
    render_html,
    top_category_tags,
)

GAME_UNAVAILABLE = {
    "zatu_handle": "unavailable-game",
    "zatu_title": "Unavailable Game",
    "zatu_url": "https://zatu.com/products/unavailable-game",
    "zatu_price_gbp": 39.99,
    "zatu_is_coop": True,
    "zatu_is_party": False,
    "zatu_tags": ["Cooperative Play", "Legacy", "2-4 Players", "30-60 Minutes", "Christmas"],
    "bgg_id": 12345,
    "bgg_year": 2021,
    "bgg_average": 8.2,
    "bgg_usersrated": 3400,
    "quality_shrunk": 8.05,
    "quality_pts": 40.0,
    "quality_label": "EXCELLENT",
    "philibert_status": "NOT_LISTED",
    "philibert_price_eur": None,
    "philibert_url": None,
    "advantage_verdict": "UNAVAILABLE_FR",
    "advantage_reason": "not sold in france, no fr edition exists",
    "discount_pct": None,
    "match_confidence": "HIGH",
    "needs_eyeball": True,
    "genre_points": 12,
    "language_points": -3,
    "language_unknown": True,
    "composite_score": 77.0,
}

GAME_CHEAPER = {
    **GAME_UNAVAILABLE,
    "zatu_handle": "cheaper-game",
    "zatu_title": "Cheaper Game",
    "zatu_is_coop": False,
    "zatu_is_party": False,
    "philibert_status": "LISTED_IN_STOCK",
    "philibert_price_eur": 60.0,
    "philibert_url": "https://www.philibertnet.com/fr/pub/1-cheaper-game.html",
    "advantage_verdict": "CHEAPER_UK",
    "advantage_reason": "in stock both sides, uk is 42% cheaper",
    "discount_pct": 0.42,
    "needs_eyeball": False,
    "composite_score": 55.0,
}


def test_build_why_includes_reason_rating_genre_and_language():
    why = build_why(GAME_UNAVAILABLE)
    assert "Not sold in france" in why
    assert "8.2 (3,400 votes)" in why
    assert "coop" in why
    assert "language unknown" in why


def test_build_why_omits_genre_when_neither_coop_nor_party():
    why = build_why(GAME_CHEAPER)
    assert "coop" not in why
    assert "party" not in why


def test_build_flags_needs_eyeball_and_unknown_lang():
    flags = build_flags(GAME_UNAVAILABLE)
    assert flags == ["NEEDS_EYEBALL", "UNKNOWN_LANG"]


def test_build_flags_empty_when_confident_and_language_known():
    game = {**GAME_CHEAPER, "needs_eyeball": False, "language_unknown": False}
    assert build_flags(game) == []


def test_prepare_games_falls_back_to_philibert_search_url_when_not_listed():
    prepared = prepare_games([GAME_UNAVAILABLE])[0]
    assert prepared["philibert_link_is_search"] is True
    assert "recherche?search_query=Unavailable" in prepared["philibert_link_url"]


def test_prepare_games_uses_real_philibert_url_when_listed():
    prepared = prepare_games([GAME_CHEAPER])[0]
    assert prepared["philibert_link_is_search"] is False
    assert prepared["philibert_link_url"] == GAME_CHEAPER["philibert_url"]


def test_prepare_games_marks_user_excluded_by_handle():
    prepared = prepare_games([GAME_UNAVAILABLE, GAME_CHEAPER], {GAME_UNAVAILABLE["zatu_handle"]})
    assert prepared[0]["user_excluded"] is True
    assert prepared[1]["user_excluded"] is False


def test_prepare_games_defaults_to_none_excluded():
    prepared = prepare_games([GAME_UNAVAILABLE])
    assert prepared[0]["user_excluded"] is False


def test_clean_category_tags_drops_player_count_duration_and_marketing_noise():
    tags = ["Cooperative Play", "Legacy", "2-4 Players", "30-60 Minutes", "Christmas", "Party Games"]
    assert clean_category_tags(tags) == ["Legacy"]


def test_clean_category_tags_dedupes_case_insensitively():
    assert clean_category_tags(["Legacy", "legacy", "Deck Building"]) == ["Legacy", "Deck Building"]


def test_clean_category_tags_handles_none_and_empty():
    assert clean_category_tags(None) == []
    assert clean_category_tags([]) == []


def test_top_category_tags_ranks_by_frequency_and_respects_limit():
    games = [
        {"category_tags": ["Legacy", "Deck Building"]},
        {"category_tags": ["Legacy"]},
        {"category_tags": ["Legacy", "Abstract"]},
    ]
    assert top_category_tags(games, limit=2) == ["Legacy", "Deck Building"]


def test_prepare_games_includes_cleaned_category_tags():
    prepared = prepare_games([GAME_UNAVAILABLE])[0]
    assert prepared["category_tags"] == ["Legacy"]


def test_prepare_games_maps_advantage_verdict_to_css_class():
    prepared = prepare_games([GAME_UNAVAILABLE, GAME_CHEAPER])
    assert prepared[0]["advantage_css_class"] == "adv-unavailable"
    assert prepared[1]["advantage_css_class"] == "adv-cheaper"


UNMATCHED_NO_CANDIDATE = {
    "zatu_handle": "totally-obscure-game",
    "zatu_title": "Totally Obscure Game",
    "zatu_url": "https://zatu.com/products/totally-obscure-game",
    "zatu_price_gbp": 12.5,
    "zatu_in_stock": True,
    "zatu_is_coop": False,
    "zatu_is_party": True,
    "zatu_tags": ["Party Games", "2-4 Players"],
    "match_category": "NO_CONFIDENT_MATCH",
    "bgg_candidates": [],
    "match_score": None,
}

UNMATCHED_NEAR_MISS = {
    "zatu_handle": "near-miss-game",
    "zatu_title": "Near Miss Game Deluxe",
    "zatu_url": "https://zatu.com/products/near-miss-game",
    "zatu_price_gbp": 25.0,
    "zatu_in_stock": False,
    "zatu_is_coop": False,
    "zatu_is_party": False,
    "zatu_tags": [],
    "match_category": "DIGIT_CONFLICT",
    "bgg_candidates": [{"bgg_id": 999, "bgg_name": "Near Miss Game 2"}],
    "match_score": 92.5,
}

UNMATCHED_AMBIGUOUS = {
    "zatu_handle": "ambiguous-game",
    "zatu_title": "Ambiguous Game",
    "zatu_url": "https://zatu.com/products/ambiguous-game",
    "zatu_price_gbp": None,
    "zatu_in_stock": True,
    "zatu_is_coop": False,
    "zatu_is_party": False,
    "zatu_tags": [],
    "match_category": "AMBIGUOUS_EXACT",
    "bgg_candidates": [
        {"bgg_id": 1, "bgg_name": "Ambiguous Game (2001)"},
        {"bgg_id": 2, "bgg_name": "Ambiguous Game (Big Box)"},
    ],
    "match_score": None,
}


def test_build_closest_bgg_guess_none_when_no_candidates():
    assert build_closest_bgg_guess(UNMATCHED_NO_CANDIDATE) is None


def test_build_closest_bgg_guess_includes_score_for_single_candidate():
    guess = build_closest_bgg_guess(UNMATCHED_NEAR_MISS)
    assert guess == "Near Miss Game 2 (92% similar)"


def test_build_closest_bgg_guess_lists_multiple_candidates_without_a_score():
    guess = build_closest_bgg_guess(UNMATCHED_AMBIGUOUS)
    assert guess == "Ambiguous Game (2001), Ambiguous Game (Big Box)"


def test_prepare_unmatched_maps_category_to_friendly_label_and_bgg_search_url():
    prepared = prepare_unmatched([UNMATCHED_NEAR_MISS])
    assert prepared[0]["match_category_label"].startswith("Possible mismatch")
    assert prepared[0]["bgg_search_url"].startswith(
        "https://boardgamegeek.com/geeksearch.php?"
    )
    assert prepared[0]["closest_bgg_guess"] == "Near Miss Game 2 (92% similar)"


def test_render_html_produces_self_contained_page_with_both_games():
    html = render_html(
        [GAME_UNAVAILABLE, GAME_CHEAPER],
        {"generated_at": "2026-08-10 12:00 UTC", "fx_gbp_eur": 1.17, "discount_threshold": 0.40},
        [UNMATCHED_NO_CANDIDATE, UNMATCHED_NEAR_MISS],
    )
    assert "<!doctype html>" in html.lower()
    assert "Unavailable Game" in html
    assert "Cheaper Game" in html
    assert "2 games matched your criteria" in html
    # "Not interested" hide button + handle are baked into every scored row.
    assert html.count('class="hide-btn"') == 2
    assert 'data-handle="unavailable-game"' in html
    # Mobile card layout (thead hidden, td stacked) reads each cell's own data-label -- a
    # regression here would silently drop the label prefix on narrow screens.
    assert 'data-label="Score"' in html
    assert 'data-label="Advantage"' in html
    assert 'data-label="UK price"' in html
    assert 'id="games-sort-select"' in html
    assert "Totally Obscure Game" in html
    assert "Near Miss Game Deluxe" in html
    assert "Near Miss Game 2 (92% similar)" in html
    # self-contained: every external link points at one of the three known content sources,
    # never a CDN asset (script/style src) -- no <script src=...> or <link href=...> at all.
    assert "<script src=" not in html
    assert '<link href=' not in html
    allowed_domains = ("zatu.com", "boardgamegeek.com", "www.philibertnet.com")
    for url in re.findall(r'href="(https?://[^"]+)"', html):
        domain = re.match(r"https?://([^/]+)", url).group(1)
        assert domain in allowed_domains, f"unexpected external link: {url}"
