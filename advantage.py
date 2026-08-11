"""Stage 5/6 partial — UK-vs-France advantage verdict (docs/spec.md §5.2). Consumes Stage 5's
Philibert lookup result plus Zatu's own price/stock (already in Stage 0's harvest).

The FR-edition-exists cross-check (spec §5.2's UNAVAILABLE_FR vs UNAVAILABLE_FR?) is now real,
via Stage 3 (`sources/bgg_versions.py`, a headless-browser check of BGG's own versions data).
User's explicit, direct instruction (2026-08-11) after a real case (Gloomhaven: Jaws of the
Lion — genuinely not on Philibert, but BGG confirms a real French edition exists, just not
currently purchasable anywhere): "I don't want to buy English versions if a French one exists
(even if unavailable)" — "everything that has a French version just needs to be removed." So
`fr_edition_exists is True` is *not* a weaker version of UNAVAILABLE_FR, it's excluded from the
shortlist entirely (`VERDICT_FRENCH_EDITION_EXISTS`), same treatment as `NONE`/
`FAMILY_AVAILABLE_FR` — a known French edition, even a currently-unpurchasable one, means this
isn't a genuine "must buy in the UK" opportunity. `fr_edition_exists is None` (Stage 3 hasn't
checked this game, e.g. it was outside this run's NOT_LISTED-only scope) still gets the
conservative weak/uncertain UNAVAILABLE_FR — unproven, not the same as proven-nonexistent.
"""

from __future__ import annotations

from dataclasses import dataclass

VERDICT_UNAVAILABLE_FR = "UNAVAILABLE_FR"
VERDICT_OUT_OF_STOCK_FR = "OUT_OF_STOCK_FR"
VERDICT_CHEAPER_UK = "CHEAPER_UK"
VERDICT_NONE = "NONE"
VERDICT_EXCLUDED = "EXCLUDED"  # Zatu itself out of stock — spec: "not a real opportunity"
# This exact Zatu SKU (a specific edition/expansion/collection) isn't listed on Philibert, but
# the base/family game is, under a plainer title -- e.g. Zatu's "Everdell Complete Collection"
# vs Philibert's plain "Everdell", or "Cthulhu: Death May Die - Fear of the Unknown" vs
# Philibert's "Cthulhu: Death May Die". User-confirmed real cases: treat "the family is
# available in France" the same as a genuine French availability -- no UK-buy urgency, so this
# is excluded from the shortlist just like NONE/EXCLUDED, not scored as an advantage. Distinct
# from NONE (which means "this exact game, in stock both sides, at a similar price") because we
# deliberately never fetched/compared this SKU's own price -- it would be comparing the wrong
# product.
VERDICT_FAMILY_AVAILABLE_FR = "FAMILY_AVAILABLE_FR"
# A known French edition exists somewhere (BGG's own versions data, Stage 3) even though this
# exact game isn't listed on Philibert right now. User's explicit call: treat this the same as
# NONE/FAMILY_AVAILABLE_FR -- not a genuine UK-exclusive buy, even if the French edition itself
# isn't currently purchasable anywhere. Distinct from the weak/uncertain UNAVAILABLE_FR (which
# means "we don't know either way") -- this means we *do* know, and the answer excludes it.
VERDICT_FRENCH_EDITION_EXISTS = "FRENCH_EDITION_EXISTS"


@dataclass
class AdvantageResult:
    verdict: str
    points: float
    discount_pct: float | None
    needs_eyeball: bool
    reason: str


def compute_advantage(
    zatu_in_stock: bool,
    zatu_price_gbp: float | None,
    philibert_status: str,  # "NOT_LISTED" | "LISTED_OUT_OF_STOCK" | "LISTED_IN_STOCK" | "FAMILY_LISTED_FR"
    philibert_price_eur: float | None,
    fx_gbp_eur: float,
    discount_threshold: float,
    weights: dict,
    fr_edition_exists: bool | None = None,
) -> AdvantageResult:
    """Spec §5.2's verdict table. `NONE` (in stock both sides, discount below threshold) is the
    "no genuine UK advantage" case — the one to filter out of a shortlist."""
    if not zatu_in_stock:
        return AdvantageResult(
            VERDICT_EXCLUDED, 0.0, None, False, "Zatu itself is out of stock — not a real opportunity"
        )

    if philibert_status == "FAMILY_LISTED_FR":
        return AdvantageResult(
            VERDICT_FAMILY_AVAILABLE_FR,
            0.0,
            None,
            True,
            "not listed under this exact edition, but the base/family game is listed on "
            "Philibert -- treated as available in France",
        )

    if philibert_status == "NOT_LISTED":
        if fr_edition_exists is False:
            return AdvantageResult(
                VERDICT_UNAVAILABLE_FR,
                weights["unavailable_fr"],
                None,
                False,
                "not listed on Philibert, no French edition exists at all",
            )
        if fr_edition_exists is True:
            return AdvantageResult(
                VERDICT_FRENCH_EDITION_EXISTS,
                0.0,
                None,
                True,
                "not listed on Philibert, but a French edition exists (per BGG) -- not a "
                "genuine UK-exclusive buy",
            )
        return AdvantageResult(
            VERDICT_UNAVAILABLE_FR,
            weights["unavailable_fr_weak"],
            None,
            True,
            "not listed on Philibert; French-edition-exists check unavailable for this game",
        )

    if philibert_status == "LISTED_OUT_OF_STOCK":
        return AdvantageResult(
            VERDICT_OUT_OF_STOCK_FR, weights["out_of_stock_fr"], None, False,
            "listed on Philibert but out of stock",
        )

    if philibert_status != "LISTED_IN_STOCK":
        raise ValueError(f"unknown philibert_status: {philibert_status!r}")

    if zatu_price_gbp is None or philibert_price_eur is None or philibert_price_eur <= 0:
        return AdvantageResult(
            VERDICT_NONE, 0.0, None, True, "in stock both sides but a price is missing"
        )

    discount = (philibert_price_eur - zatu_price_gbp * fx_gbp_eur) / philibert_price_eur

    if discount >= discount_threshold:
        excess_points = (discount - discount_threshold) * 100
        bonus = min(10.0, excess_points / 4)
        points = weights["cheaper_uk_base"] + bonus
        return AdvantageResult(
            VERDICT_CHEAPER_UK, points, discount, False,
            f"in stock both sides, UK is {discount:.0%} cheaper",
        )

    return AdvantageResult(
        VERDICT_NONE, 0.0, discount, False,
        f"in stock both sides, UK only {discount:.0%} cheaper (below {discount_threshold:.0%} threshold)",
    )
