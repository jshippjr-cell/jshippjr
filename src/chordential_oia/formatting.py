"""Rendering of scored opportunities into the Chordential scorecard format."""

from __future__ import annotations

from typing import List

from .models import ScoredOpportunity, WinProbability


def render_scorecard(scored: ScoredOpportunity) -> str:
    """Render a single opportunity in the spec's scorecard layout."""
    opp = scored.opportunity
    lines: List[str] = []
    lines.append(f"Opportunity Score: {scored.score:.0f}/100")
    lines.append("")
    lines.append(f"Client: {opp.client}")
    lines.append(f"Need: {opp.need}")
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
        src = opp.source
        if opp.url:
            src = f"{src} ({opp.url})"
        lines.append(f"Source: {src}")
    return "\n".join(lines)


def render_breakdown(scored: ScoredOpportunity) -> str:
    """Render the per-criterion weighted breakdown table."""
    rows = [f"{'Criterion':<24}{'Weight':>7}{'Signal':>8}{'Points':>8}"]
    rows.append("-" * 47)
    for b in scored.breakdown:
        rows.append(
            f"{b.name:<24}{b.weight:>7.0f}{b.normalized:>8.0%}{b.points:>8.1f}"
        )
    rows.append("-" * 47)
    rows.append(f"{'Total':<24}{scored.score:>23.1f}")
    return "\n".join(rows)


def render_ranked_report(scored_list: List[ScoredOpportunity], show_breakdown: bool = False) -> str:
    """Render a full ranked report grouped by win-probability band."""
    bands = {
        WinProbability.HIGH: "HIGHEST PROBABILITY",
        WinProbability.MEDIUM: "MEDIUM PROBABILITY",
        WinProbability.LONG_SHOT: "LONG-SHOT OPPORTUNITIES",
    }
    out: List[str] = []
    out.append("=" * 60)
    out.append("  CHORDENTIAL — OPPORTUNITY INTELLIGENCE REPORT")
    out.append(f"  {len(scored_list)} opportunities ranked")
    out.append("=" * 60)

    for band, heading in bands.items():
        in_band = [s for s in scored_list if s.win_probability == band]
        if not in_band:
            continue
        out.append("")
        out.append(f"### {heading}  ({len(in_band)})")
        out.append("")
        for scored in in_band:
            out.append(render_scorecard(scored))
            if show_breakdown:
                out.append("")
                out.append(render_breakdown(scored))
            out.append("")
            out.append("-" * 40)
    return "\n".join(out)
