"""The Prepare layer — assemble a ready-to-use Pursuit Brief.

The fifth mission verb (Identify → Rank → Qualify → Estimate → **Prepare**). It is
deliberately **deterministic** (no LLM cost): it assembles what the engines have
already produced — the qualification verdict, the estimate, and the strategic
value — into a clean brief a human can act on, plus a suggested response outline.

This is where the product stops being analysis and starts doing the work: instead
of a verdict, you get a pursuit-ready brief.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .capabilities import quote_phrase
from .estimation import Estimate
from .models import (
    MusicDiscipline,
    Opportunity,
    QualificationResult,
    ScoredOpportunity,
)
from .strategic import StrategicValue

# One discipline-specific line for the response outline.
_DISCIPLINE_HINT = {
    MusicDiscipline.COMPOSITION: "Offer a short custom sketch direction (tempo, instrumentation, references).",
    MusicDiscipline.SONIC_BRANDING: "Propose a mnemonic exploration — 2–3 sonic-logo directions.",
    MusicDiscipline.SOUND_DESIGN: "Outline the sound-design palette and the key moments to score.",
    MusicDiscipline.ARRANGEMENT: "Note the arrangement / orchestration approach and ensemble.",
    MusicDiscipline.SUPERVISION: "Propose a curated track shortlist and a clearance plan.",
    MusicDiscipline.LICENSING: "Propose licensing options and how clearance will be handled.",
    MusicDiscipline.NON_CRAFT: "",
}

_PLACEHOLDER_GAPS = {"No major gaps", "No major risks flagged"}


@dataclass
class PursuitBrief:
    client: str
    need: str
    recommendation: str
    discipline: str
    fit_summary: str
    why_fit: List[str]
    watchouts: List[str]
    team: List[str]
    budget_line: str
    strategic_angle: str
    # ONE action list. It used to be three — ``response_outline``, ``next_steps`` and
    # this — with the same steps worded differently; the HTML brief rendered only the
    # checklist while ``brief.txt`` rendered only the other two, so the same brief gave
    # two different instructions depending on how you opened it. The quote line was in
    # all three, which is how the wrong number survived three separate reviews.
    checklist: List[str] = field(default_factory=list)
    qualified: bool = True
    assumptions: List[str] = field(default_factory=list)

    def render_text(self) -> str:
        """Plain-text brief for copy-paste."""
        def block(title: str, items: List[str]) -> str:
            body = "\n".join(f"  - {i}" for i in items) if items else "  - —"
            return f"{title}\n{body}"

        parts = [
            f"PURSUIT BRIEF — {self.need}",
            f"Client: {self.client}",
            f"Recommendation: {self.recommendation}",
            f"Discipline: {self.discipline}",
            "",
            self.fit_summary,
            "",
            block("Why it fits:", self.why_fit),
            "",
            block("Watch-outs:", self.watchouts),
            "",
            f"Team: {', '.join(self.team) if self.team else '—'}",
            f"Budget: {self.budget_line}",
            f"Strategic angle: {self.strategic_angle}",
            "",
            block("Pursuit checklist:", self.checklist),
        ]
        return "\n".join(parts)


def build_pursuit_brief(
    opp: Opportunity,
    qual: QualificationResult,
    scored: ScoredOpportunity,
    estimate: Optional[Estimate],
    strategic: StrategicValue,
    quote_band: Optional[tuple] = None,
) -> PursuitBrief:
    """Assemble a deterministic pursuit brief from existing engine outputs.

    ``quote_band`` is ``capabilities.quote_band(...)`` — the ONE number we quote a
    buyer (ADR-0034), resolved by the caller because it needs Campaign Intelligence
    and the operator's overrides. The brief renders it; it never derives a quote of
    its own. Without it the checklist says so rather than inventing a figure.
    """
    discipline = qual.discipline
    buyer = opp.buyer_type.value.replace("_", " ")

    recommendation = (
        f"{qual.recommended_action.value} — {strategic.tier} · "
        f"{qual.alignment_pct:.0f}% fit"
    )

    why_fit = [r for r in qual.fit_reasons if r not in _PLACEHOLDER_GAPS] or ["—"]
    watchouts = [
        g for g in (list(qual.gaps) + list(scored.risks)) if g not in _PLACEHOLDER_GAPS
    ] or ["None flagged"]

    team = qual.team_shape or (discipline.team_shape if qual.qualified else [])

    if estimate is not None:
        price = estimate.suggested_price
        budget_line = (
            f"Estimated {estimate.cost_range}; suggested price "
            f"${price:,.0f} at {estimate.expected_margin_pct:.0f}% target margin. "
            f"{estimate.budget_delta_note}"
        )
    else:
        budget_line = "No estimate available."

    strategic_angle = strategic.callout or strategic.rationale

    # The one client-facing number, resolved by the caller. This step used to read
    # "Provide an indicative quote: $4,342–$9,018" — the estimate's *cost* range,
    # what production costs US, labelled as the quote to give the buyer. On the
    # seeded Brightline deal that instructed quoting $4,342 to a client who had
    # disclosed a $20,000–$40,000 budget.
    quoted = quote_phrase(quote_band)

    hint = _DISCIPLINE_HINT.get(discipline, "")
    team_line = ", ".join(team) if team else "TBD"
    checklist = [
        f"Acknowledge the brief and confirm scope, deliverables, and deadline with {scored.decision_maker}.",
        f"Frame why Chordential: {discipline.label} craft, fast turnaround, fit for {buyer} work.",
    ]
    if hint:
        checklist.append(hint)
    checklist += [
        f"Confirm team availability: {team_line}.",
        "Attach a relevant reel / 2–3 reference pieces (see the Outreach tab's recommended examples).",
        f"Provide an indicative quote: {quoted}.",
        "Send the response and close with a timeline and one clear next step.",
        "Log the outcome (win/loss) once decided — it feeds the moat.",
    ]

    return PursuitBrief(
        client=opp.client,
        need=opp.need,
        recommendation=recommendation,
        discipline=discipline.label,
        fit_summary=qual.fit_summary,
        why_fit=why_fit,
        watchouts=watchouts,
        team=team,
        budget_line=budget_line,
        strategic_angle=strategic_angle,
        checklist=checklist,
        qualified=qual.qualified,
        assumptions=[
            "Assembled deterministically from the qualification, estimate, and "
            "strategic-value engines — no AI generation.",
            "Estimate is Phase-1 expert priors (uncalibrated). Verify before sending.",
        ],
    )
