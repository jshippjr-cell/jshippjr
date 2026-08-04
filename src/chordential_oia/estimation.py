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

# Base role hours for ONE campaign cue carried end to end — brief and spotting,
# demo directions, the revision rounds, the final, stems and the deliverable
# versions. They were previously demo-scale (8 composer hours is one demo, not a
# national campaign), which is a large part of why the engine priced a national
# :30 at roughly a third of the market band the public planning tool quotes.
# Rates are blended placeholders pending AFM / SAG-AFTRA / market data.
ROLE_HOURS: Dict[str, float] = {
    "Composer": 20.0,
    "Arranger": 8.0,
    "Orchestrator": 16.0,
    "Music Editor": 5.0,
    "Mixer": 8.0,
    "Mix Engineer": 10.0,
    "Mastering": 2.0,
    "Project Manager": 6.0,
    "Sound Designer": 10.0,
    "Music Supervisor": 6.0,
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
    # The rate unit, so the line displays correctly on the client proposal —
    # a day/flat rate must NOT render as "Nh × $rate/h" (reads as $rate/hour).
    unit: str = "hourly"

    @property
    def cost(self) -> float:
        if self.cost_override is not None:
            return self.cost_override
        return self.hours * self.rate

    @property
    def _days(self) -> int:
        return max(1, math.ceil(self.hours / 8.0))

    @property
    def qty_label(self) -> str:
        """Quantity column on the proposal (hours, days, or a flat marker)."""
        if self.unit == "day":
            return f"{self._days}d"
        if self.unit == "project":
            return "flat"
        return f"{self.hours:g}h"

    @property
    def rate_label(self) -> str:
        """Rate column, unit-correct so the client never sees a $/h day rate."""
        if self.unit == "day":
            return f"${self.rate:,.0f}/day"
        if self.unit == "project":
            return "flat fee"
        return f"${self.rate:,.0f}/h"

    @property
    def breakdown(self) -> str:
        """One-line scope row for the plain-text proposal."""
        if self.unit == "day":
            return f"{self._days}d × ${self.rate:,.0f}/day = ${self.cost:,.0f}"
        if self.unit == "project":
            return f"flat fee = ${self.cost:,.0f}"
        return f"{self.hours:g}h × ${self.rate:,.0f}/h = ${self.cost:,.0f}"


@dataclass
class Multiplier:
    name: str
    setting: str
    factor: float
    # Where the factor lands. The estimate page showed four factors above a
    # "Compounded multiplier" that was not their product, because one of them
    # was applied elsewhere and nothing said so. "desk" factors compound into
    # multiplier_total; "price" factors are fees applied after margin.
    applies: str = "desk"


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
    # Players + room. Kept separate from the desk lines because it is the part a
    # client most often asks to see itemised, and the part that used to be missing.
    session_cost: float = 0.0
    session_label: str = ""
    band_spread_pct: float = BAND_SPREAD * 100.0
    assumptions: List[str] = field(default_factory=list)

    @property
    def cost_range(self) -> str:
        return f"${self.cost_low:,.0f}–${self.cost_high:,.0f}"


# What it costs to actually record the music, by instrumentation. None of this
# existed before: "full orchestra" was a ×4 on desk hours — including the project
# manager's — which multiplied the wrong thing and never paid a single player.
# Figures are session-scale placeholders (players at scale + the room), to be
# replaced with AFM rate-card data alongside ROLE_RATES.
SESSION_PACKAGES: Dict[str, dict] = {
    "simple": {"label": "Piano / simple (assumed)", "players": 1, "player_fee": 600.0,
               "studio": 600.0, "extras": 0.0, "complexity": 1.0},
    "hybrid": {"label": "Hybrid / small ensemble", "players": 4, "player_fee": 650.0,
               "studio": 1800.0, "extras": 0.0, "complexity": 1.25},
    "orchestral": {"label": "Full orchestra", "players": 30, "player_fee": 650.0,
                   "studio": 3500.0, "extras": 2700.0, "complexity": 1.6},
}

# Usage/licensing is a RIGHTS FEE on the price, not a cost of making the music —
# a wider licence does not make the session longer. These factors are the same
# ones the public planning band quotes (see PUBLIC_USAGE), so the internal number
# and the number a visitor is shown can no longer drift apart.
USAGE_FACTORS: Dict[str, float] = {"local": 0.75, "national": 1.0, "global": 2.0}

# The public planning band (the /commission estimator). These are the researched,
# operator-ratified market priors — the engine is calibrated toward them, not the
# other way round. They lived as hardcoded JavaScript inside the template, which
# is how the site came to quote $9,000-18,000 for a job the engine costed at
# $4,847. One definition, rendered into the page; a test asserts they still agree.
PUBLIC_BANDS: Dict[str, tuple] = {
    "anthem": (16000, 28000),
    "spot": (9000, 18000),
    "title": (12000, 22000),
    "social": (4500, 9000),
}
PUBLIC_LENGTHS: Dict[str, float] = {"15": 0.8, "30": 1.0, "60": 1.25, "120": 1.6}
PUBLIC_USAGE: Dict[str, float] = {
    "social": USAGE_FACTORS["local"],
    "national": USAGE_FACTORS["national"],
    "global": USAGE_FACTORS["global"],
}


def public_band(kind: str, length: str, usage: str) -> tuple:
    """The band the public estimator shows, computed from the shared priors."""
    low, high = PUBLIC_BANDS[kind]
    factor = PUBLIC_LENGTHS[length] * PUBLIC_USAGE[usage]
    return round(low * factor), round(high * factor)


def _infer_duration(text: str) -> Multiplier:
    """Longest mention wins.

    This used to test ``:15`` first, so a brief reading ":60 anthem with :30 and
    :15 cutdowns" was classified as a :15 spot and priced at HALF the bare :30 —
    enumerating the deliverables made the job cheaper. Real campaign briefs
    always list their cutdown suite, so the bug fired on the biggest jobs.
    """
    if any(k in text for k in (":120", "2-minute", "two minute", "long form")):
        return Multiplier("Duration", ":120 / long form", 1.6)
    if any(k in text for k in (":60", "60-second", "60 second", "anthem")):
        return Multiplier("Duration", ":60 / anthem", 1.25)
    if any(k in text for k in (":30", "30-second", "30 second")):
        return Multiplier("Duration", ":30 spot", 1.0)
    if any(k in text for k in (":15", ":06", "15-second", "15 second")):
        return Multiplier("Duration", ":15 spot", 0.8)
    return Multiplier("Duration", ":30 spot (assumed)", 1.0)


def _cutdown_count(text: str) -> int:
    """Cutdowns are additive scope — each is a conform, a mix and a master, not a
    reason to reclassify the whole job as its shortest deliverable."""
    return sum(1 for k in (":60", ":30", ":15", ":06") if k in text)


def _infer_instrumentation(text: str) -> tuple:
    """Returns (Multiplier for writing complexity, session package key).

    Writing for an orchestra genuinely takes longer at the desk — but only a
    little longer, and the players are a separate line. The old flat ×4 was
    standing in for a recording budget that was never actually priced.
    """
    if "full orchestra" in text or "orchestral" in text or "orchestra" in text:
        key = "orchestral"
    elif any(k in text for k in ("hybrid", "ensemble", "strings", "band", "live players")):
        key = "hybrid"
    else:
        key = "simple"
    pkg = SESSION_PACKAGES[key]
    return Multiplier("Instrumentation", pkg["label"], pkg["complexity"]), key


def _session_cost(key: str, duration_factor: float) -> float:
    """Players + room, scaled by how much music is being recorded."""
    pkg = SESSION_PACKAGES[key]
    players = pkg["players"] * pkg["player_fee"]
    return (players + pkg["studio"] + pkg["extras"]) * duration_factor


def _infer_usage(text: str) -> Multiplier:
    if any(k in text for k in ("global", "worldwide", "international")):
        return Multiplier("Usage / licence", "Global", USAGE_FACTORS["global"], applies="price")
    if any(k in text for k in ("national", "nationwide", "broadcast")):
        return Multiplier("Usage / licence", "National", USAGE_FACTORS["national"], applies="price")
    return Multiplier("Usage / licence", "Local / social (assumed)", USAGE_FACTORS["local"],
                      applies="price")


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
        return RoleLine(role, hours, rate, cost_override=days * rate, unit="day")
    if unit == "project":
        return RoleLine(role, hours, rate, cost_override=rate, unit="project")
    # hourly (default): plain hours × rate, no explicit override needed.
    return RoleLine(role, hours, rate, unit="hourly")


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
    instrumentation, session_key = _infer_instrumentation(text)
    usage = _infer_usage(text)
    revisions = _revisions(text)
    cutdowns = _cutdown_count(text)
    # Each additional deliverable length is a conform + mix + master pass.
    cutdown_factor = 1.0 + 0.12 * max(0, cutdowns - 1)
    multipliers = [duration, instrumentation, usage, revisions]
    if cutdowns > 1:
        multipliers.append(
            Multiplier("Cutdowns", f"{cutdowns} lengths (+{(cutdown_factor - 1) * 100:.0f}%)",
                       cutdown_factor))

    # Desk work scales with how much music and how complex it is; the revision
    # budget scales the desk only — you do not re-book the orchestra to change a
    # note. Every factor shown in `multipliers` is applied here except usage,
    # which is a fee on the price rather than a cost of production.
    multiplier_total = (duration.factor * instrumentation.factor
                        * cutdown_factor * revisions.factor)
    desk_cost = base_cost * multiplier_total
    revision_uplift = base_cost * (multiplier_total / revisions.factor) * (revisions.factor - 1.0)
    session_cost = _session_cost(session_key, duration.factor)
    estimated_cost = desk_cost + session_cost

    # Usage is a rights fee, applied to the price. Rolling it into cost (as a
    # 1.2× on a national licence) implied a wider licence cost more to produce
    # and quietly inflated the margin calculation.
    suggested_price = (estimated_cost / (1.0 - TARGET_MARGIN)) * usage.factor
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
        session_cost=session_cost,
        session_label=SESSION_PACKAGES[session_key]["label"],
        band_spread_pct=BAND_SPREAD * 100.0,
        assumptions=[
            "Phase 1 — expert priors only; NOT calibrated on Chordential actuals.",
            "Role hours cover one campaign cue end to end (brief, demos, revisions, stems, versions).",
            "Session line pays players and the room; usage is a rights fee on the price, not a cost.",
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
