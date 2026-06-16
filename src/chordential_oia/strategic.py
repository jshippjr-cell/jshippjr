"""The CMO's Strategic-Value lens.

A third signal — distinct from qualification *alignment* (fit) and the *opportunity
score* (attractiveness) — that captures how strategically valuable an opportunity
is to the business, per ``docs/cmo-positioning-brief.md`` §6. It exists to correct
a positioning failure: a $10k one-off municipal bid should **not** outrank a $2k
brief from a major agency that could become a repeat enterprise account.

Strategic Value (0-100) composes three inputs the CEO specified:

1. **Buyer-type desirability** — is this a Chordential customer?
2. **Buyer relationship value** — one-time vs repeat vs enterprise.
3. **Strategic importance** — a marquee / door-opener multiplier.

It does not change qualification or scoring; it is a complementary marketing
judgment that can override raw budget in ranking, with an explainable callout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import BuyerType, BuyerValue, Opportunity, Relationship

# 1. Buyer-type desirability (CMO rubric).
BUYER_DESIRABILITY = {
    BuyerType.AGENCY: 1.0,
    BuyerType.PRODUCTION_COMPANY: 0.9,
    BuyerType.BRAND: 0.85,
    BuyerType.EDUCATIONAL: 0.4,
    BuyerType.GOVERNMENT: 0.3,
    BuyerType.UNKNOWN: 0.5,
}

# 2. Buyer relationship value.
BUYER_VALUE_WEIGHT = {
    BuyerValue.ENTERPRISE: 1.0,
    BuyerValue.REPEAT: 0.8,
    BuyerValue.ONE_TIME: 0.4,
    BuyerValue.UNKNOWN: 0.5,
}

# Composition weights and the marquee (door-opener) bonus.
W_DESIRABILITY = 0.55
W_RELATIONSHIP = 0.45
MARQUEE_BONUS = 0.15

# A small-but-strategic opportunity is one whose strategic value is high while its
# disclosed budget is modest — exactly the "$2k agency beats $10k municipal" case.
STRATEGIC_FLOOR = 65.0
SMALL_BUDGET_CEILING = 5_000.0

_ENTERPRISE_KW = (
    "enterprise", "multi-year", "multi year", "idiq", "retainer", "ongoing",
    "recurring", "master service", "msa", "series", "episodic", "roster",
    "preferred vendor", "framework",
)
_MARQUEE_KW = (
    "national", "global", "worldwide", "fortune", "flagship", "award-winning",
    "major brand", "household name", "super bowl", "olympic",
)


@dataclass
class StrategicValue:
    """The Strategic-Value verdict for one opportunity."""

    score: float  # 0-100
    tier: str  # Door-opener / High / Medium / Low
    buyer_desirability: float  # 0-1 component
    relationship_value: float  # 0-1 component
    buyer_value: BuyerValue  # resolved (explicit or inferred)
    marquee: bool  # resolved
    rationale: str
    callout: Optional[str]  # set when small-but-strategic (override raw budget)
    inferred: bool  # True if buyer_value/marquee were inferred, not human-set


def _text(opp: Opportunity) -> str:
    return f"{opp.client} {opp.need} {opp.description} {' '.join(opp.tags)}".lower()


def resolve_buyer_value(opp: Opportunity) -> tuple[BuyerValue, bool]:
    """Return (buyer_value, inferred). Explicit value wins; else infer from text."""
    if opp.buyer_value is not BuyerValue.UNKNOWN:
        return opp.buyer_value, False
    text = _text(opp)
    if any(k in text for k in _ENTERPRISE_KW):
        return BuyerValue.ENTERPRISE, True
    if opp.relationship is Relationship.PAST_CLIENT:
        return BuyerValue.REPEAT, True
    return BuyerValue.ONE_TIME, True


def resolve_marquee(opp: Opportunity) -> tuple[bool, bool]:
    """Return (marquee, inferred). Explicit flag wins; else infer conservatively."""
    if opp.marquee:
        return True, False
    text = _text(opp)
    desirable = opp.buyer_type in (
        BuyerType.AGENCY, BuyerType.BRAND, BuyerType.PRODUCTION_COMPANY
    )
    if desirable and any(k in text for k in _MARQUEE_KW):
        return True, True
    return False, False


def _tier(score: float, marquee: bool, small_strategic: bool) -> str:
    if small_strategic or (marquee and score >= STRATEGIC_FLOOR):
        return "Door-opener"
    if score >= 75:
        return "High"
    if score >= 50:
        return "Medium"
    return "Low"


def assess_strategic_value(opp: Opportunity) -> StrategicValue:
    desirability = BUYER_DESIRABILITY.get(opp.buyer_type, 0.5)
    buyer_value, bv_inferred = resolve_buyer_value(opp)
    marquee, mq_inferred = resolve_marquee(opp)
    relationship = BUYER_VALUE_WEIGHT[buyer_value]

    base = W_DESIRABILITY * desirability + W_RELATIONSHIP * relationship
    if marquee:
        base = min(1.0, base + MARQUEE_BONUS)
    score = round(base * 100.0, 1)

    mid = opp.budget_midpoint
    small_budget = mid is None or mid < SMALL_BUDGET_CEILING
    small_strategic = score >= STRATEGIC_FLOOR and small_budget

    tier = _tier(score, marquee, small_strategic)

    buyer_name = opp.buyer_type.value.replace("_", " ")
    bits = [f"{buyer_name} buyer", buyer_value.label.lower()]
    if marquee:
        bits.append("marquee / door-opener")
    rationale = "Strategic value: " + ", ".join(bits) + "."

    callout = None
    if small_strategic:
        budget_phrase = f"${mid:,.0f}" if mid is not None else "undisclosed budget"
        reason = (
            "marquee relationship" if marquee
            else f"{buyer_name} {buyer_value.label.lower()}"
        )
        callout = (
            f"{budget_phrase} now — but a {reason}. Strategically ranked above "
            f"larger one-off bids."
        )

    return StrategicValue(
        score=score,
        tier=tier,
        buyer_desirability=desirability,
        relationship_value=relationship,
        buyer_value=buyer_value,
        marquee=marquee,
        rationale=rationale,
        callout=callout,
        inferred=bv_inferred or mq_inferred,
    )
