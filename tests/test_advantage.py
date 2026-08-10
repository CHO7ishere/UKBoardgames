import pytest

from advantage import compute_advantage

WEIGHTS = {
    "unavailable_fr": 40,
    "unavailable_fr_weak": 28,
    "out_of_stock_fr": 30,
    "cheaper_uk_base": 15,
}
FX = 1.17
THRESHOLD = 0.40


def test_zatu_out_of_stock_excludes_regardless_of_philibert():
    result = compute_advantage(
        zatu_in_stock=False,
        zatu_price_gbp=20.0,
        philibert_status="NOT_LISTED",
        philibert_price_eur=None,
        fx_gbp_eur=FX,
        discount_threshold=THRESHOLD,
        weights=WEIGHTS,
    )
    assert result.verdict == "EXCLUDED"


def test_not_listed_no_fr_edition_is_full_strength():
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=20.0,
        philibert_status="NOT_LISTED",
        philibert_price_eur=None,
        fx_gbp_eur=FX,
        discount_threshold=THRESHOLD,
        weights=WEIGHTS,
        fr_edition_exists=False,
    )
    assert result.verdict == "UNAVAILABLE_FR"
    assert result.points == 40
    assert result.needs_eyeball is False


def test_not_listed_fr_edition_exists_is_weaker_and_flagged():
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=20.0,
        philibert_status="NOT_LISTED",
        philibert_price_eur=None,
        fx_gbp_eur=FX,
        discount_threshold=THRESHOLD,
        weights=WEIGHTS,
        fr_edition_exists=True,
    )
    assert result.verdict == "UNAVAILABLE_FR"
    assert result.points == 28
    assert result.needs_eyeball is True


def test_not_listed_unknown_fr_edition_defaults_to_weaker_and_flagged():
    # Stage 3 (BGG enrich) isn't built yet -> fr_edition_exists is always None for now.
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=20.0,
        philibert_status="NOT_LISTED",
        philibert_price_eur=None,
        fx_gbp_eur=FX,
        discount_threshold=THRESHOLD,
        weights=WEIGHTS,
        fr_edition_exists=None,
    )
    assert result.verdict == "UNAVAILABLE_FR"
    assert result.points == 28
    assert result.needs_eyeball is True


def test_family_listed_fr_is_excluded_style_verdict_and_flagged():
    # search_family_title found the base/family game on Philibert, not this exact Zatu SKU --
    # user-confirmed real cases (Everdell Complete Collection, Cthulhu: Death May Die - Fear of
    # the Unknown, Gloomhaven 2nd Edition): treat "the family is available in France" as no
    # genuine UK-buy urgency, distinct from a real price-comparable NONE/LISTED_IN_STOCK match.
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=39.99,
        philibert_status="FAMILY_LISTED_FR",
        philibert_price_eur=None,
        fx_gbp_eur=FX,
        discount_threshold=THRESHOLD,
        weights=WEIGHTS,
    )
    assert result.verdict == "FAMILY_AVAILABLE_FR"
    assert result.points == 0.0
    assert result.needs_eyeball is True


def test_family_listed_fr_takes_priority_even_when_zatu_out_of_stock():
    # zatu_in_stock=False still wins (EXCLUDED) -- "not a real opportunity" is checked first
    # regardless of Philibert status.
    result = compute_advantage(
        zatu_in_stock=False,
        zatu_price_gbp=39.99,
        philibert_status="FAMILY_LISTED_FR",
        philibert_price_eur=None,
        fx_gbp_eur=FX,
        discount_threshold=THRESHOLD,
        weights=WEIGHTS,
    )
    assert result.verdict == "EXCLUDED"


def test_out_of_stock_fr():
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=20.0,
        philibert_status="LISTED_OUT_OF_STOCK",
        philibert_price_eur=None,
        fx_gbp_eur=FX,
        discount_threshold=THRESHOLD,
        weights=WEIGHTS,
    )
    assert result.verdict == "OUT_OF_STOCK_FR"
    assert result.points == 30


def test_cheaper_uk_at_exactly_the_threshold():
    # discount = (100 - 60*1.0)/100 = 0.40 exactly, using fx=1.0 for round numbers
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=60.0,
        philibert_status="LISTED_IN_STOCK",
        philibert_price_eur=100.0,
        fx_gbp_eur=1.0,
        discount_threshold=0.40,
        weights=WEIGHTS,
    )
    assert result.verdict == "CHEAPER_UK"
    assert result.discount_pct == pytest.approx(0.40)
    assert result.points == 15  # no bonus at exactly the threshold


def test_cheaper_uk_bonus_scales_and_caps_at_10():
    # discount = 0.80 -> excess = 40 percentage points -> bonus = min(10, 40/4) = 10 (capped)
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=20.0,
        philibert_status="LISTED_IN_STOCK",
        philibert_price_eur=100.0,
        fx_gbp_eur=1.0,
        discount_threshold=0.40,
        weights=WEIGHTS,
    )
    assert result.verdict == "CHEAPER_UK"
    assert result.points == 25  # 15 + 10 (capped)


def test_cheaper_uk_bonus_uncapped_case():
    # discount = 0.60 -> excess = 20 -> bonus = 20/4 = 5 -> points = 20
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=40.0,
        philibert_status="LISTED_IN_STOCK",
        philibert_price_eur=100.0,
        fx_gbp_eur=1.0,
        discount_threshold=0.40,
        weights=WEIGHTS,
    )
    assert result.points == pytest.approx(20.0)


def test_none_verdict_when_discount_below_threshold():
    # UK price close to FR price -> no real advantage -> this is the "remove it" case.
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=45.0,
        philibert_status="LISTED_IN_STOCK",
        philibert_price_eur=50.0,
        fx_gbp_eur=1.0,
        discount_threshold=0.40,
        weights=WEIGHTS,
    )
    assert result.verdict == "NONE"
    assert result.points == 0.0


def test_none_verdict_when_uk_is_more_expensive():
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=60.0,
        philibert_status="LISTED_IN_STOCK",
        philibert_price_eur=50.0,
        fx_gbp_eur=1.0,
        discount_threshold=0.40,
        weights=WEIGHTS,
    )
    assert result.verdict == "NONE"
    assert result.discount_pct < 0


def test_none_verdict_when_price_missing():
    result = compute_advantage(
        zatu_in_stock=True,
        zatu_price_gbp=None,
        philibert_status="LISTED_IN_STOCK",
        philibert_price_eur=50.0,
        fx_gbp_eur=FX,
        discount_threshold=THRESHOLD,
        weights=WEIGHTS,
    )
    assert result.verdict == "NONE"
    assert result.needs_eyeball is True


def test_unknown_philibert_status_raises():
    with pytest.raises(ValueError):
        compute_advantage(
            zatu_in_stock=True,
            zatu_price_gbp=20.0,
            philibert_status="BOGUS",
            philibert_price_eur=None,
            fx_gbp_eur=FX,
            discount_threshold=THRESHOLD,
            weights=WEIGHTS,
        )
