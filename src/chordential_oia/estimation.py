"""Estimation engine — the Phase-1 expert model as a first-class intelligence layer.

Estimation is a pillar of the moat (see ``docs/company-strategy.md``: the hybrid
3-phase estimator). Phase 1 applies the ratified industry role-hour priors and
complexity multipliers to the team shape the qualification layer produces. This
module is the canonical home for that model — the dashboard's estimate page is a
thin consumer of it (``chordential_oia.web.estimate`` re-exports from here).

Phase 1 is deliberately *uncalibrated*: every estimate carries a wide confidence
**band** that is honest about the uncertainty. Phases 2/3 (market benchmarks,
Chordential actuals) narrow the band as real data accrues — they are out of scope
until that data exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import MusicDiscipline, Opportunity

# Ratified Phase-1 base role hours (midpoint of the documented ranges) and
# assumed blended rates ($/hr). Rates are placeholders to be replaced with
# AFM / SAG-AFTRA / market data in Phase 2.
ROLE_HOURS: Dict[str, float] = {
    "Composer": 8.0,
    "Arranger": 5.0,
    "Orchestrator": 12.0,
    "Music Editor": 2.5,
    "Mixer": 5.0,
    "Mix Engineer": 7.0,
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
    "Mix Engineer": 125.0,
    "Mastering": 120.0,
    "Project Manager": 85.0,
    "Sound Designer": 100.0,
    "Music Supervisor": 95.0,
}

# Target gross margin applied to suggested price (lean: protect margin).
TARGET_MARGIN = 0.40

# Phase-1 confidence band: ±this fraction around the point estimate. Wide on
# purpose (uncalibrated). Phase 3 calibration shrinks it from real variance.
BAND_SPREAD = 0.35


@dataclass
class RoleLine:
    role: str
    hours: float
    rate: float
    # When an assigned talent's rate is a day/flat rate, the line cost is not
    # simply hours × rate. ``cost_override`` carries the computed cost in that
    # case; left None, the line falls back to the hourly hours × rate.
    cost_override: Optional[float] = None

    @property
    def cost(self) -> float:
        if self.cost_override is not None:
            return self.cost_override
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
    # Phase-1 confidence band around the point cost estimate.
    cost_low: float = 0.0
    cost_high: float = 0.0
    band_spread_pct: float = BAND_SPREAD * 100.0
    assumptions: List[str] = field(default_factory=list)

    @property
    def cost_range(self) -> str:
        return f"${self.cost_low:,.0f}–${self.cost_high:,.0f}"


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


def _override_line(role: str, hours: float, override: dict) -> RoleLine:
    """Build a role line whose rate/cost come from an assigned talent's rate.

    ``override`` = {"rate": float, "unit": "hourly"|"day"|"project"}. Conversions:
      hourly  → cost = hours × rate (line behaves like a normal hourly line)
      day     → days = max(1, ceil(hours/8)); cost = days × rate
      project → flat: cost = rate (replaces the line cost regardless of hours)
    """
    rate = float(override["rate"])
    unit = (override.get("unit") or "hourly").lower()
    if unit == "day":
        days = max(1, math.ceil(hours / 8.0))
        return RoleLine(role, hours, rate, cost_override=days * rate)
    if unit == "project":
        return RoleLine(role, hours, rate, cost_override=rate)
    # hourly (default): plain hours × rate, no explicit override needed.
    return RoleLine(role, hours, rate)


def build_estimate(
    opp: Opportunity,
    team_shape: List[str],
    discipline: MusicDiscipline,
    rate_overrides: Optional[Dict[str, dict]] = None,
) -> Estimate:
    """Produce a Phase-1 expert estimate (point + confidence band) for an opp.

    ``rate_overrides`` maps {role_name: {"rate": float, "unit": ...}}. When a
    role is present, its line rate/cost are computed from that assigned-talent
    rate instead of the global default — this is how an assigned creator's real
    cost flows into the project proposal. Absent (the default), the estimate is
    identical to the pre-feature behaviour.
    """
    text = f"{opp.need} {opp.description} {' '.join(opp.tags)}".lower()

    roles = list(team_shape) if team_shape else ["Composer", "Mixer"]
    if "Project Manager" not in roles:
        roles = roles + ["Project Manager"]

    overrides = rate_overrides or {}
    lines = []
    for role in roles:
        hours = ROLE_HOURS.get(role, 4.0)
        if role in overrides and overrides[role] and overrides[role].get("rate") is not None:
            lines.append(_override_line(role, hours, overrides[role]))
        else:
            lines.append(RoleLine(role, hours, ROLE_RATES.get(role, 100.0)))
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

    cost_low = estimated_cost * (1.0 - BAND_SPREAD)
    cost_high = estimated_cost * (1.0 + BAND_SPREAD)

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
        cost_low=cost_low,
        cost_high=cost_high,
        band_spread_pct=BAND_SPREAD * 100.0,
        assumptions=[
            "Phase 1 — expert priors only; NOT calibrated on Chordential actuals.",
            "Role hours are midpoints of the ratified industry ranges.",
            "Rates are assumed blended $/hr — replace with AFM / SAG-AFTRA / market data (Phase 2).",
            f"Target gross margin {TARGET_MARGIN:.0%} applied to suggested price.",
            f"Confidence band ±{BAND_SPREAD:.0%} (uncalibrated) — narrows as actuals accrue.",
            "Unstated duration/instrumentation/revisions default to the documented baseline.",
        ],
    )


class EstimationEngine:
    """Phase-1 expert estimator. Mirrors the QualificationEngine/ScoringEngine shape.

    Derives the team from the qualification discipline when one isn't supplied,
    so callers can estimate straight off a qualification result.
    """

    def estimate(
        self,
        opp: Opportunity,
        team_shape: Optional[List[str]] = None,
        discipline: Optional[MusicDiscipline] = None,
        rate_overrides: Optional[Dict[str, dict]] = None,
    ) -> Estimate:
        discipline = discipline or MusicDiscipline.COMPOSITION
        team_shape = team_shape or discipline.team_shape
        return build_estimate(opp, team_shape, discipline, rate_overrides)
