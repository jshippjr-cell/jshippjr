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
from urllib.parse import quote_plus

from .estimation import Estimate
from .models import BuyerType, MusicDiscipline, Opportunity, QualificationResult, ScoredOpportunity
from .strategic import StrategicValue

# --------------------------------------------------------------------------- #
# Per-discipline creative content for the outreach message.
#
# IMPORTANT (company strategy): Chordential does NOT synthesize audio. These are
# recommendations for which *existing portfolio* examples to attach and which
# deliverables to anticipate — not generated audio. They complement the brief's
# vision so the human can attach the right reel.
# --------------------------------------------------------------------------- #
# What to attach: example types tuned to the discipline (the "audio examples").
_RECOMMENDED_EXAMPLES = {
    MusicDiscipline.COMPOSITION: [
        "Original score / theme example",
        "Theme-and-variations example",
        "Multi-channel campaign cut example",
    ],
    MusicDiscipline.SONIC_BRANDING: [
        "Sonic logo example",
        "Brand anthem example",
        "Campaign adaptation example",
    ],
    MusicDiscipline.SOUND_DESIGN: [
        "Signature sound-design example",
        "Motion / UI sound example",
        "Trailer / promo sound example",
    ],
    MusicDiscipline.ARRANGEMENT: [
        "Arrangement / orchestration example",
        "Ensemble recording example",
        "Adaptation / re-arrangement example",
    ],
    MusicDiscipline.SUPERVISION: [
        "Curated placement example",
        "Cleared-track shortlist example",
        "Needle-drop reel example",
    ],
    MusicDiscipline.LICENSING: [
        "Licensing / library reel example",
        "Cleared-track example",
    ],
}

# Deliverables we'd "anticipate supporting" — the unified-system framing.
_DELIVERABLES = {
    MusicDiscipline.COMPOSITION: [
        "Original composition / score", "Theme development and variations",
        "Campaign cutdowns and alternate lengths",
        "Stems and alternate versions for each channel",
        "Final mixes optimized for delivery",
    ],
    MusicDiscipline.SONIC_BRANDING: [
        "Sonic logo development", "Brand anthem composition",
        "Campaign cutdowns and adaptations",
        "Alternate versions for social, digital, and broadcast",
        "Final mixes optimized for advertising delivery",
    ],
    MusicDiscipline.SOUND_DESIGN: [
        "Signature sound-design palette", "Key-moment scoring and effects",
        "Motion / UI / transition sound", "Alternate versions per channel",
        "Final mixes optimized for delivery",
    ],
    MusicDiscipline.ARRANGEMENT: [
        "Arrangement / orchestration", "Ensemble preparation and recording",
        "Alternate arrangements and lengths", "Stems and alternate mixes",
        "Final mixes optimized for delivery",
    ],
    MusicDiscipline.SUPERVISION: [
        "Music supervision and curation", "Track shortlist and creative direction",
        "Clearance and licensing coordination", "Alternate options per channel",
        "Delivery-ready files",
    ],
    MusicDiscipline.LICENSING: [
        "Track curation and licensing", "Clearance coordination",
        "Alternate options per channel", "Delivery-ready files",
    ],
}

# Relevant-work bullets for the message ([Project] is the human's to fill in).
_EXAMPLE_WORK = {
    MusicDiscipline.COMPOSITION: [
        "[Project] — Original score for a branded film",
        "[Project] — Campaign music package with cutdowns and alternate versions",
        "[Project] — Original composition supporting a multi-channel launch",
    ],
    MusicDiscipline.SONIC_BRANDING: [
        "[Project] — Sonic identity and brand theme development",
        "[Project] — National campaign music package with cutdowns and alternate versions",
        "[Project] — Original composition supporting a multi-channel brand launch",
    ],
    MusicDiscipline.SOUND_DESIGN: [
        "[Project] — Signature sound-design system for a product launch",
        "[Project] — Motion and UI sound for a digital campaign",
        "[Project] — Trailer / promo sound-design package",
    ],
    MusicDiscipline.ARRANGEMENT: [
        "[Project] — Orchestral arrangement for a brand film",
        "[Project] — Ensemble arrangement and recording",
        "[Project] — Multi-version adaptation across channels",
    ],
    MusicDiscipline.SUPERVISION: [
        "[Project] — Music supervision for a branded campaign",
        "[Project] — Curated, cleared placements across channels",
        "[Project] — Needle-drop reel for a product launch",
    ],
    MusicDiscipline.LICENSING: [
        "[Project] — Licensed music package with clearance",
        "[Project] — Curated cleared-track selection for a campaign",
    ],
}

_SYSTEM_FRAMING = {
    MusicDiscipline.SONIC_BRANDING: (
        "The combination of a sonic logo, brand anthem, and campaign adaptations "
        "immediately suggests a unified music system rather than a collection of "
        "individual deliverables, and that's where we tend to provide the most value."
    ),
}


def _for_discipline(table, disc):
    """Discipline lookup with a Composition fallback (keeps disqualified safe)."""
    return table.get(disc) or table[MusicDiscipline.COMPOSITION]


def _build_first_touch(opp, qual, contact_name):
    """The first-touch message — a relationship-first proposal that adapts the
    examples, deliverables, and framing to the lead's discipline and brand."""
    disc = qual.discipline
    name = (contact_name or "").strip() or "there"
    framing = _SYSTEM_FRAMING.get(disc) or (
        "The scope reads as a unified music system rather than a collection of "
        f"individual deliverables, and that's where {disc.label.lower()} work like "
        "this tends to provide the most value."
    )
    examples = _for_discipline(_EXAMPLE_WORK, disc)
    deliverables = _for_discipline(_DELIVERABLES, disc)
    ex_lines = "\n".join(f"• {e}" for e in examples)
    dl_lines = "\n".join(f"• {d}" for d in deliverables)
    return (
        f"Hi {name},\n\n"
        f"Thank you for the opportunity to be considered for {opp.need}.\n\n"
        "After reviewing the brief, we're confident this is the type of work "
        f"Chordential is built for. {framing}\n\n"
        "I've included a few examples of relevant work below that align closely "
        "with what you've described:\n\n"
        f"{ex_lines}\n\n"
        "What stood out to us in your brief is the opportunity to create a musical "
        f"identity that can extend well beyond this campaign and become an asset "
        f"{opp.client} can continue to leverage across future content and activations.\n\n"
        "Based on the information provided, we would anticipate supporting:\n\n"
        f"{dl_lines}\n\n"
        "Our team has already begun discussing several creative directions that "
        "could support the objectives outlined in the brief, and we'd welcome the "
        "opportunity to walk you through those ideas and better understand your "
        "goals, timeline, and success criteria."
    )


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
    linkedin_search_url: str = ""
    recommended_examples: List[str] = field(default_factory=list)
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


def _linkedin_research_url(target: str, company: str) -> str:
    """A LinkedIn people-search deep-link for the inferred decision-maker.

    Deterministic lead enrichment: we can't fetch a specific private profile
    without an external data provider, but we *can* point one click at the
    person to find — the decision-maker's role at this buyer. Built from the
    RFP's own facts (the scoring engine's inferred role + the buyer name), with
    the ``Likely`` qualifier and any parenthetical buyer-type suffix stripped so
    the search terms are clean.
    """
    role = target.replace("Likely ", "").strip()
    company_clean = company.split("(")[0].strip()
    keywords = f"{role} {company_clean}".strip()
    return (
        "https://www.linkedin.com/search/results/people/?keywords="
        + quote_plus(keywords)
    )


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
    contact_name: Optional[str] = None,
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

    first_touch_message = _build_first_touch(opp, qual, contact_name)
    # Subject line for the one-click mailto draft (kept short and concrete).
    email_subject = f"{opp.need} — Chordential"
    recommended_examples = _for_discipline(_RECOMMENDED_EXAMPLES, discipline) if qual.qualified else []

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
        linkedin_search_url=_linkedin_research_url(target, opp.client),
        recommended_examples=recommended_examples,
        qualified=qual.qualified,
        assumptions=[
            "Sequenced deterministically from the qualification, estimate, and "
            "strategic-value engines — no AI generation.",
            f"Contact ({target}) is inferred — confirm the real name/email before sending.",
            "Recommended examples are existing portfolio pieces to attach — "
            "Chordential does not synthesize audio (human craft + Jon-reviewed reels).",
            "LinkedIn link is an auto-built people search for the decision-maker at "
            "this buyer — open it to find the person, then paste their profile to lock it in.",
            "Log each touch below; the outcome feeds the win/loss moat.",
        ],
    )
