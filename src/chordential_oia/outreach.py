"""The Outreach-to-Win layer — turn a qualified pursuit into a contact plan.

The sixth mission verb (Identify → Rank → Qualify → Estimate → Prepare →
**Outreach**). Like :mod:`prepare`, it is deliberately **deterministic** (no LLM
cost): it assembles what the engines already produced — the qualification
verdict, the estimate, the strategic value, and the inferred decision-maker —
into a concrete, sequenced outreach plan a human can act on, plus a ready
first-touch message.

This is where the product stops preparing and starts *winning the business*: a
recommended contact, an urgency call, and a touch-by-touch cadence tuned to the
buyer. It does **not** send mail — it drafts and structures the outreach so Jon
(or a producer) can run it and log the result, which feeds the win/loss moat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .estimation import Estimate
from .models import BuyerType, Opportunity, QualificationResult, ScoredOpportunity
from .strategic import StrategicValue

# Per-buyer-type opening channel + the channel used to ask for a live conversation.
_CHANNELS = {
    BuyerType.AGENCY: ("Email, then a LinkedIn touch", "Phone / video call"),
    BuyerType.BRAND: ("Email, then a LinkedIn touch", "Phone / video call"),
    BuyerType.PRODUCTION_COMPANY: ("Email to the production contact", "Phone / video call"),
    BuyerType.GOVERNMENT: ("Formal email / procurement portal", "Scheduled call within the process"),
    BuyerType.EDUCATIONAL: ("Email to the department contact", "Phone / video call"),
    BuyerType.UNKNOWN: ("Email", "Phone / video call"),
}


@dataclass
class OutreachStep:
    """One sequenced touch in the outreach cadence."""

    order: int
    action: str
    channel: str
    timing: str
    talking_point: str


@dataclass
class OutreachPlan:
    target_contact: str
    urgency: str
    primary_channel: str
    steps: List[OutreachStep]
    first_touch_message: str
    email_subject: str = ""
    qualified: bool = True
    assumptions: List[str] = field(default_factory=list)

    def render_text(self) -> str:
        """Plain-text outreach plan for copy-paste."""
        lines = [
            "OUTREACH PLAN",
            f"Contact: {self.target_contact}",
            f"Urgency: {self.urgency}",
            f"Primary channel: {self.primary_channel}",
            "",
            "First-touch message:",
            self.first_touch_message,
            "",
            "Cadence:",
        ]
        for s in self.steps:
            lines.append(f"  {s.order}. {s.action} — {s.channel} ({s.timing})")
            lines.append(f"     {s.talking_point}")
        if self.assumptions:
            lines.append("")
            lines.append("Notes:")
            lines += [f"  - {a}" for a in self.assumptions]
        return "\n".join(lines)


def _urgency(qual: QualificationResult, scored: ScoredOpportunity,
             strategic: StrategicValue, opp: Opportunity) -> str:
    tight = opp.turnaround_days is not None and opp.turnaround_days <= 7
    if strategic.tier == "Door-opener":
        return "Reach out within 24h — strategic door-opener; speed wins the relationship."
    if tight:
        return f"Reach out within 24h — tight {opp.turnaround_days}-day turnaround."
    if qual.recommended_action.value == "Pursue":
        return "Reach out within 1–2 business days — qualified, high-fit pursuit."
    return "Reach out within 2–3 business days — warm, non-urgent."


def build_outreach_plan(
    opp: Opportunity,
    qual: QualificationResult,
    scored: ScoredOpportunity,
    estimate: Optional[Estimate],
    strategic: StrategicValue,
) -> OutreachPlan:
    """Assemble a deterministic outreach plan from existing engine outputs."""
    discipline = qual.discipline
    buyer = opp.buyer_type.value.replace("_", " ")
    target = scored.decision_maker  # inferred role/name from the scoring engine
    primary_channel, call_channel = _CHANNELS.get(
        opp.buyer_type, _CHANNELS[BuyerType.UNKNOWN]
    )

    if estimate is not None:
        price = estimate.suggested_price
        price_phrase = f"~${price:,.0f}"
        cost_range = estimate.cost_range
    else:
        price_phrase = "TBD"
        cost_range = "TBD"

    first_touch_message = (
        f"Hi {target} — I saw {opp.client} is exploring {opp.need}. "
        f"{qual.fit_summary} "
        f"Chordential can move fast on this; indicative range {cost_range}. "
        "Open to a quick 15-minute call this week to talk scope?"
    )
    # Subject line for the one-click mailto draft (kept short and concrete).
    email_subject = f"{opp.need} — Chordential"

    steps: List[OutreachStep] = []
    is_gov = opp.buyer_type is BuyerType.GOVERNMENT
    if is_gov:
        steps.append(OutreachStep(
            1, "Confirm submission requirements", primary_channel,
            "Day 0 — before pitching",
            "Pull the deadline, format, and eligibility from the posting/portal; "
            "note any teaming or registration requirement.",
        ))

    base = [
        OutreachStep(
            0, f"Introductory message to {target}", primary_channel,
            "Day 0 (within the urgency window)",
            f"Lead with the fit: {discipline.label} craft for {buyer} work; "
            "attach one relevant reference.",
        ),
        OutreachStep(
            0, "Value follow-up", "Email",
            "Day 3 (if no reply)",
            "Share a 2–3 piece reel tuned to the brief; restate the fast turnaround.",
        ),
        OutreachStep(
            0, "Offer a scoping call", call_channel,
            "Day 5",
            f"Propose a 15-min call to confirm scope, deliverables, and deadline with {target}.",
        ),
        OutreachStep(
            0, "Send indicative quote / proposal", "Email",
            "After the call (or Day 7)",
            f"Provide the indicative quote ({price_phrase}); close with one clear next step.",
        ),
    ]
    steps += base
    # Re-number sequentially so an optional gov step 1 doesn't collide.
    for i, s in enumerate(steps, start=1):
        s.order = i

    return OutreachPlan(
        target_contact=target,
        urgency=_urgency(qual, scored, strategic, opp),
        primary_channel=primary_channel,
        steps=steps,
        first_touch_message=first_touch_message,
        email_subject=email_subject,
        qualified=qual.qualified,
        assumptions=[
            "Sequenced deterministically from the qualification, estimate, and "
            "strategic-value engines — no AI generation.",
            f"Contact ({target}) is inferred — confirm the real name/email before sending.",
            "Log each touch below; the outcome feeds the win/loss moat.",
        ],
    )
