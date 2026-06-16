"""Phase-1 expert estimate for the budget-estimate page.

This is a *presentation* of the estimation model the board already ratified in
``docs/company-strategy.md`` (the hybrid 3-phase estimator, Phase 1). It applies
the documented role-hour priors and complexity multipliers to the team shape the
qualification layer already produced. It is **not** new scoring logic and not the
calibrated estimator — Phases 2/3 (market benchmarks, Chordential actuals) are
explicitly out of scope until real data exists. Every number is labeled as an
uncalibrated industry prior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..models import MusicDiscipline, Opportunity

# Ratified Phase-1 base role hours (midpoint of the documented ranges) and
# assumed blended rates ($/hr). Rates are placeholders to be replaced with
# AFM / SAG-AFTRA / market data in Phase 2.
ROLE_HOURS: Dict[str, float] = {
    "Composer": 8.0,
    "Arranger": 5.0,
    "Orchestrator": 12.0,
    "Music Editor": 2.5,
    "Mixer": 5.0,
    "Mastering": 1.5,
    "Project Manager": 2.0,
    "Sound Designer": 6.0,
    "Music Supervisor": 4.0,
}
ROLE_RATES: Dict[str, float] = {
    "Composer": 150.0,
    "Arranger": 100.0,
    "Orchestrator": 90.0,
    "Music Editor": 75.0,
    "Mixer": 110.0,
    "Mastering": 120.0,
    "Project Manager": 85.0,
    "Sound Designer": 100.0,
    "Music Supervisor": 95.0,
}

# Target gross margin applied to suggested price (lean: protect margin).
TARGET_MARGIN = 0.40


@dataclass
class RoleLine:
    role: str
    hours: float
    rate: float

    @property
    def cost(self) -> float:
        return self.hours * self.rate


@dataclass
class Multiplier:
    name: str
    setting: str
    factor: float


@dataclass
class Estimate:
    discipline: MusicDiscipline
    lines: List[RoleLine]
    multipliers: List[Multiplier]
    base_cost: float
    multiplier_total: float
    revision_uplift: float
    estimated_cost: float
    suggested_price: float
    expected_margin_pct: float
    disclosed_budget: Optional[str]
    budget_delta_note: str
    assumptions: List[str] = field(default_factory=list)


def _infer_duration(text: str) -> Multiplier:
    if ":15" in text or "15-second" in text or "15 second" in text:
        return Multiplier("Duration", ":15 spot", 0.5)
    if ":60" in text or "60-second" in text or "60 second" in text or "anthem" in text:
        return Multiplier("Duration", ":60 / long form", 1.5)
    return Multiplier("Duration", ":30 spot (assumed)", 1.0)


def _infer_instrumentation(text: str) -> Multiplier:
    if "full orchestra" in text or "orchestral" in text or "orchestra" in text:
        return Multiplier("Instrumentation", "Full orchestra", 4.0)
    if "hybrid" in text or "ensemble" in text or "strings" in text or "band" in text:
        return Multiplier("Instrumentation", "Hybrid orchestral", 2.0)
    return Multiplier("Instrumentation", "Piano / simple (assumed)", 1.0)


def _infer_licensing(text: str) -> Multiplier:
    if "global" in text or "worldwide" in text or "international" in text:
        return Multiplier("Licensing reach", "Global", 1.5)
    if "national" in text or "nationwide" in text:
        return Multiplier("Licensing reach", "National", 1.2)
    return Multiplier("Licensing reach", "Local (assumed)", 1.0)


def _revisions(text: str) -> Multiplier:
    if "3 rounds" in text or "three rounds" in text:
        return Multiplier("Revisions", "3 rounds (+30%)", 1.30)
    if "1 round" in text or "one round" in text:
        return Multiplier("Revisions", "1 round (baseline)", 1.0)
    return Multiplier("Revisions", "2 rounds assumed (+15%)", 1.15)


def build_estimate(opp: Opportunity, team_shape: List[str], discipline: MusicDiscipline) -> Estimate:
    text = f"{opp.need} {opp.description} {' '.join(opp.tags)}".lower()

    roles = list(team_shape) if team_shape else ["Composer", "Mixer"]
    if "Project Manager" not in roles:
        roles = roles + ["Project Manager"]

    lines = [
        RoleLine(role, ROLE_HOURS.get(role, 4.0), ROLE_RATES.get(role, 100.0))
        for role in roles
    ]
    base_cost = sum(line.cost for line in lines)

    duration = _infer_duration(text)
    instrumentation = _infer_instrumentation(text)
    licensing = _infer_licensing(text)
    revisions = _revisions(text)
    multipliers = [duration, instrumentation, licensing, revisions]

    multiplier_total = duration.factor * instrumentation.factor * licensing.factor
    estimated_cost = base_cost * multiplier_total * revisions.factor
    revision_uplift = base_cost * multiplier_total * (revisions.factor - 1.0)

    suggested_price = estimated_cost / (1.0 - TARGET_MARGIN)
    expected_margin_pct = TARGET_MARGIN * 100.0

    disclosed = opp.budget_display() if opp.budget_disclosed else None
    delta_note = "No disclosed budget to compare against."
    mid = opp.budget_midpoint
    if mid is not None:
        if suggested_price <= mid:
            delta_note = (
                f"Suggested price ${suggested_price:,.0f} fits within the disclosed "
                f"budget (~${mid:,.0f}) — healthy room."
            )
        else:
            delta_note = (
                f"Suggested price ${suggested_price:,.0f} exceeds the disclosed "
                f"midpoint (~${mid:,.0f}) — scope down or justify the premium."
            )

    return Estimate(
        discipline=discipline,
        lines=lines,
        multipliers=multipliers,
        base_cost=base_cost,
        multiplier_total=multiplier_total,
        revision_uplift=revision_uplift,
        estimated_cost=estimated_cost,
        suggested_price=suggested_price,
        expected_margin_pct=expected_margin_pct,
        disclosed_budget=disclosed,
        budget_delta_note=delta_note,
        assumptions=[
            "Phase 1 — expert priors only; NOT calibrated on Chordential actuals.",
            "Role hours are midpoints of the ratified industry ranges.",
            "Rates are assumed blended $/hr — replace with AFM / SAG-AFTRA / market data (Phase 2).",
            f"Target gross margin {TARGET_MARGIN:.0%} applied to suggested price.",
            "Unstated duration/instrumentation/revisions default to the documented baseline.",
        ],
    )
