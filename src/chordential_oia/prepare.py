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
    response_outline: List[str]
    next_steps: List[str]
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
            block("Suggested response outline:", self.response_outline),
            "",
            block("Next steps:", self.next_steps),
        ]
        return "\n".join(parts)


def build_pursuit_brief(
    opp: Opportunity,
    qual: QualificationResult,
    scored: ScoredOpportunity,
    estimate: Optional[Estimate],
    strategic: StrategicValue,
) -> PursuitBrief:
    """Assemble a deterministic pursuit brief from existing engine outputs."""
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
        price = None
        budget_line = "No estimate available."

    strategic_angle = strategic.callout or strategic.rationale

    price_phrase = f"~${price:,.0f}" if price is not None else "TBD"
    outline = [
        f"Acknowledge the brief: {opp.need}.",
        f"Why Chordential: {discipline.label} craft, fast turnaround, fit for {buyer} work.",
    ]
    hint = _DISCIPLINE_HINT.get(discipline, "")
    if hint:
        outline.append(hint)
    outline += [
        f"Proposed team: {', '.join(team) if team else 'TBD'}.",
        f"Indicative budget: {estimate.cost_range if estimate else 'TBD'} "
        f"(suggested {price_phrase}).",
        "Close with timeline and a single clear next step.",
    ]

    next_steps = [
        f"Confirm scope, deliverables, and deadline with {scored.decision_maker}.",
        "Send relevant reel / 2–3 reference pieces.",
        f"Provide an indicative quote ({price_phrase}).",
        f"Pre-check team availability: {', '.join(team) if team else 'TBD'}.",
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
        response_outline=outline,
        next_steps=next_steps,
        qualified=qual.qualified,
        assumptions=[
            "Assembled deterministically from the qualification, estimate, and "
            "strategic-value engines — no AI generation.",
            "Estimate is Phase-1 expert priors (uncalibrated). Verify before sending.",
        ],
    )
