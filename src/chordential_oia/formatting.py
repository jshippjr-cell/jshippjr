"""Rendering of scored opportunities into the Chordential scorecard format."""

from __future__ import annotations

from typing import List

from typing import Tuple

from .models import Opportunity, QualificationAction, QualificationResult, ScoredOpportunity, Tier


def render_qualification_report(
    pairs: List[Tuple[Opportunity, QualificationResult]],
) -> str:
    """Render the Qualify-stage verdicts grouped by recommended action."""
    headings = {
        QualificationAction.PURSUE: "PURSUE — QUALIFIED, ALIGNED, ALERTABLE",
        QualificationAction.REVIEW: "REVIEW — QUALIFIED, NEEDS A HUMAN LOOK",
        QualificationAction.WATCH: "WATCH — QUALIFIED, LOW ALIGNMENT (DB ONLY)",
        QualificationAction.PASS: "PASS — DISQUALIFIED (FULL RECALL RETAINED)",
    }
    order = [
        QualificationAction.PURSUE,
        QualificationAction.REVIEW,
        QualificationAction.WATCH,
        QualificationAction.PASS,
    ]
    out: List[str] = []
    out.append("=" * 60)
    out.append("  CHORDENTIAL — QUALIFICATION REPORT")
    out.append(f"  {len(pairs)} opportunities qualified")
    out.append("=" * 60)
    for action in order:
        in_group = [(o, q) for o, q in pairs if q.recommended_action is action]
        if not in_group:
            continue
        out.append("")
        out.append(f"### {headings[action]}  ({len(in_group)})")
        for opp, q in in_group:
            out.append(f"  [{q.confidence.value:<6}] {opp.client}: {opp.need}")
            out.append(f"           {q.fit_summary}")
            if q.disqualifiers:
                out.append(f"           ✗ {'; '.join(q.disqualifiers)}")
            elif q.needs_human_review and q.gaps:
                out.append(f"           ? {'; '.join(q.gaps[:2])}")
    return "\n".join(out)


def render_scorecard(scored: ScoredOpportunity) -> str:
    """Render a single opportunity in the spec's scorecard layout."""
    opp = scored.opportunity
    lines: List[str] = []
    lines.append(f"Opportunity Score: {scored.score:.0f}/100")
    lines.append(f"Tier: {scored.tier.label}")
    lines.append("")
    lines.append(f"Client: {opp.client}")
    lines.append(f"Need: {opp.need}")
    lines.append(f"Buyer: {opp.buyer_type.value.replace('_', ' ').title()}")
    lines.append(f"Budget: {opp.budget_display()}")
    lines.append(f"Decision Maker: {scored.decision_maker}")
    lines.append("Reason For Fit:")
    for reason in scored.reasons:
        lines.append(f"  - {reason}")
    lines.append(f"Win Probability: {scored.win_probability.value}")
    lines.append("Risks:")
    for risk in scored.risks:
        lines.append(f"  - {risk}")
    if opp.source and opp.source != "unknown":
        tier_tag = f"Tier {opp.source_tier}" if opp.source_tier else ""
        src = f"{opp.source} {tier_tag}".strip()
        if opp.url:
            src = f"{src} ({opp.url})"
        lines.append(f"Source: {src}")
    return "\n".join(lines)


def render_breakdown(scored: ScoredOpportunity) -> str:
    """Render the per-criterion weighted breakdown table."""
    rows = [f"{'Criterion':<26}{'Weight':>7}{'Signal':>8}{'Points':>8}"]
    rows.append("-" * 49)
    for b in scored.breakdown:
        rows.append(
            f"{b.name:<26}{b.weight:>7.0f}{b.normalized:>8.0%}{b.points:>8.1f}"
        )
    rows.append("-" * 49)
    rows.append(f"{'Total':<26}{scored.score:>23.1f}")
    return "\n".join(rows)


def render_ranked_report(scored_list: List[ScoredOpportunity], show_breakdown: bool = False) -> str:
    """Render a full ranked report grouped by A/B/C/Watch tier."""
    headings = {
        Tier.A: "A-TIER — PURSUE IMMEDIATELY",
        Tier.B: "B-TIER — STRONG LEADS",
        Tier.C: "C-TIER — GOVERNMENT / NEEDS TEAMING",
        Tier.WATCH: "WATCH — MONITOR ONLY",
    }
    out: List[str] = []
    out.append("=" * 60)
    out.append("  CHORDENTIAL — OPPORTUNITY INTELLIGENCE REPORT")
    out.append(f"  {len(scored_list)} opportunities ranked")
    out.append("=" * 60)

    for tier in (Tier.A, Tier.B, Tier.C, Tier.WATCH):
        in_tier = [s for s in scored_list if s.tier == tier]
        if not in_tier:
            continue
        out.append("")
        out.append(f"### {headings[tier]}  ({len(in_tier)})")
        out.append("")
        for scored in in_tier:
            out.append(render_scorecard(scored))
            if show_breakdown:
                out.append("")
                out.append(render_breakdown(scored))
            out.append("")
            out.append("-" * 40)
    return "\n".join(out)
