"""Stage 5/6 partial — UK-vs-France advantage verdict (docs/spec.md §5.2). Consumes Stage 5's
Philibert lookup result plus Zatu's own price/stock (already in Stage 0's harvest).

The FR-edition-exists cross-check (distinguishing the strong UNAVAILABLE_FR from the weaker,
NEEDS_EYEBALL-flagged UNAVAILABLE_FR?) needs Stage 3's BGG enrich data — not yet built (blocked
on the BGG token). Until then, `fr_edition_exists` is always None here, and NOT_LISTED always
takes the weaker/uncertain variant rather than assuming no French edition exists at all.
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
        weak_reason = (
            "not listed on Philibert, but a French edition exists elsewhere"
            if fr_edition_exists
            else "not listed on Philibert; French-edition-exists check unavailable "
            "(Stage 3 not built yet)"
        )
        return AdvantageResult(
            VERDICT_UNAVAILABLE_FR, weights["unavailable_fr_weak"], None, True, weak_reason
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
