"""The ranking engine.

Each criterion has a *weight* (the seven default weights sum to 100) and a
*scorer* that reads an :class:`Opportunity` and returns a normalized 0.0-1.0
signal plus a short human note. The total score is::

    score = sum(weight_i * normalized_i)   # 0-100

which is then mapped to a :class:`WinProbability` band for ranking. Weights
are configurable (see :func:`ScoringEngine.from_config`) so Chordential can
retune the model without touching code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .models import (
    AgencySize,
    CompetitionLevel,
    MusicRequirement,
    Opportunity,
    Relationship,
    ScoreBreakdown,
    ScoredOpportunity,
    WinProbability,
)

# A scorer returns (normalized_score in [0,1], human-readable note).
Scorer = Callable[[Opportunity], Tuple[float, str]]

# Chordential's budget sweet spot. Projects inside this band fit the studio's
# process and margins best; smaller ones are thin, larger ones invite heavy
# competition from established houses.
BUDGET_SWEET_MIN = 5_000.0
BUDGET_SWEET_MAX = 50_000.0
BUDGET_FLOOR = 1_500.0  # below this, rarely worth the effort

# Turnaround (in days). Fast turnaround is a Chordential strength, but
# impossibly tight timelines become a delivery risk.
TURNAROUND_IDEAL_MIN = 7
TURNAROUND_IDEAL_MAX = 45
TURNAROUND_TOO_TIGHT = 3

# Target geographies get a small geography bump. Everything else still scores
# reasonably because Chordential delivers remotely.
TARGET_REGIONS = {
    "us",
    "usa",
    "united states",
    "uk",
    "united kingdom",
    "canada",
    "remote",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# Individual criterion scorers
# --------------------------------------------------------------------------- #
def score_music_needed(opp: Opportunity) -> Tuple[float, str]:
    mapping = {
        MusicRequirement.ORIGINAL: (1.0, "Requires original music"),
        MusicRequirement.LICENSED: (0.55, "Needs licensed/library music"),
        MusicRequirement.IMPLIED: (0.4, "Music need is implied, not stated"),
        MusicRequirement.NONE: (0.0, "No clear music need"),
    }
    return mapping[opp.music_requirement]


def score_budget_fit(opp: Opportunity) -> Tuple[float, str]:
    lo, hi = opp.budget_min, opp.budget_max
    if lo is None and hi is None:
        return 0.5, "Budget unknown (neutral)"

    # Use the midpoint of whatever range we have.
    if lo is not None and hi is not None:
        midpoint = (lo + hi) / 2
    else:
        midpoint = lo if lo is not None else hi

    if midpoint < BUDGET_FLOOR:
        return 0.1, f"Budget ~${midpoint:,.0f} is below viable floor"
    if BUDGET_SWEET_MIN <= midpoint <= BUDGET_SWEET_MAX:
        return 1.0, f"Budget ~${midpoint:,.0f} sits in the sweet spot"
    if midpoint < BUDGET_SWEET_MIN:
        # Ramp from floor up to the sweet-spot minimum.
        frac = (midpoint - BUDGET_FLOOR) / (BUDGET_SWEET_MIN - BUDGET_FLOOR)
        return _clamp(0.3 + 0.6 * frac), f"Budget ~${midpoint:,.0f} is modest"
    # Above the sweet spot: still attractive but more competitive.
    overshoot = (midpoint - BUDGET_SWEET_MAX) / BUDGET_SWEET_MAX
    return _clamp(0.85 - 0.35 * overshoot), f"Budget ~${midpoint:,.0f} is large"


def score_turnaround_fit(opp: Opportunity) -> Tuple[float, str]:
    days = opp.turnaround_days
    if days is None:
        return 0.5, "Turnaround unknown (neutral)"
    if days <= TURNAROUND_TOO_TIGHT:
        return 0.35, f"{days}-day turnaround is very tight (delivery risk)"
    if TURNAROUND_IDEAL_MIN <= days <= TURNAROUND_IDEAL_MAX:
        return 1.0, f"{days}-day turnaround fits Chordential's fast process"
    if days < TURNAROUND_IDEAL_MIN:
        frac = (days - TURNAROUND_TOO_TIGHT) / (TURNAROUND_IDEAL_MIN - TURNAROUND_TOO_TIGHT)
        return _clamp(0.6 + 0.4 * frac), f"{days}-day turnaround is quick but doable"
    # Long timelines are fine but the speed advantage matters less.
    return 0.7, f"{days}-day turnaround is relaxed"


def score_geography(opp: Opportunity) -> Tuple[float, str]:
    if opp.remote_friendly and not opp.location:
        return 0.8, "Remote-friendly, location-agnostic"
    loc = (opp.location or "").strip().lower()
    if not loc:
        return 0.6, "Location unknown"
    if any(region in loc for region in TARGET_REGIONS):
        return 1.0, f"In a target region ({opp.location})"
    if opp.remote_friendly:
        return 0.7, f"Outside target regions but remote-friendly ({opp.location})"
    return 0.4, f"On-site outside target regions ({opp.location})"


def score_competition(opp: Opportunity) -> Tuple[float, str]:
    mapping = {
        CompetitionLevel.LOW: (1.0, "Low competition expected"),
        CompetitionLevel.MEDIUM: (0.6, "Moderate competition"),
        CompetitionLevel.HIGH: (0.25, "Crowded field / high competition"),
    }
    return mapping[opp.competition]


def score_agency_size(opp: Opportunity) -> Tuple[float, str]:
    mapping = {
        AgencySize.BOUTIQUE: (0.85, "Boutique buyer - agile, values a partner"),
        AgencySize.MID: (1.0, "Mid-size buyer - ideal budget and pace"),
        AgencySize.LARGE: (0.6, "Large buyer - budget present but slower"),
        AgencySize.ENTERPRISE: (0.45, "Enterprise buyer - procurement-heavy"),
        AgencySize.UNKNOWN: (0.55, "Buyer size unknown"),
    }
    return mapping[opp.agency_size]


def score_relationship(opp: Opportunity) -> Tuple[float, str]:
    mapping = {
        Relationship.PAST_CLIENT: (1.0, "Existing past client"),
        Relationship.WARM_LEAD: (0.7, "Warm lead / prior contact"),
        Relationship.NONE: (0.2, "No existing relationship"),
    }
    return mapping[opp.relationship]


@dataclass
class Criterion:
    """A named, weighted scoring dimension."""

    name: str
    weight: float
    scorer: Scorer


# Default weights from Chordential's ranking spec (sum = 100).
DEFAULT_WEIGHTS: Dict[str, float] = {
    "Music Needed": 25,
    "Budget Fit": 20,
    "Turnaround Fit": 15,
    "Competition": 15,
    "Agency Size": 10,
    "Existing Relationship": 10,
    "Geography": 5,
}

_SCORERS: Dict[str, Scorer] = {
    "Music Needed": score_music_needed,
    "Budget Fit": score_budget_fit,
    "Turnaround Fit": score_turnaround_fit,
    "Competition": score_competition,
    "Agency Size": score_agency_size,
    "Existing Relationship": score_relationship,
    "Geography": score_geography,
}

# Score thresholds for the win-probability bands.
HIGH_THRESHOLD = 70.0
MEDIUM_THRESHOLD = 45.0

# A criterion is "strong" enough to list as a reason when its normalized
# signal clears this bar; "weak" enough to flag as a risk below this one.
REASON_THRESHOLD = 0.75
RISK_THRESHOLD = 0.4


class ScoringEngine:
    """Scores and ranks opportunities against weighted criteria."""

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        weights = weights or DEFAULT_WEIGHTS
        self.criteria: List[Criterion] = []
        for name, weight in weights.items():
            scorer = _SCORERS.get(name)
            if scorer is None:
                raise ValueError(f"No scorer registered for criterion {name!r}")
            self.criteria.append(Criterion(name, float(weight), scorer))

    @classmethod
    def from_config(cls, path: str) -> "ScoringEngine":
        """Build an engine from a JSON file of ``{criterion: weight}``."""
        import json

        with open(path, "r", encoding="utf-8") as handle:
            weights = json.load(handle)
        return cls(weights=weights)

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.criteria)

    def score(self, opp: Opportunity) -> ScoredOpportunity:
        breakdown: List[ScoreBreakdown] = []
        reasons: List[str] = []
        risks: List[str] = []

        for criterion in self.criteria:
            normalized, note = criterion.scorer(opp)
            normalized = _clamp(normalized)
            breakdown.append(
                ScoreBreakdown(
                    name=criterion.name,
                    weight=criterion.weight,
                    normalized=normalized,
                    note=note,
                )
            )
            if normalized >= REASON_THRESHOLD:
                reasons.append(note)
            elif normalized <= RISK_THRESHOLD:
                risks.append(note)

        raw = sum(b.points for b in breakdown)
        # Normalize to 0-100 in case custom weights don't sum to 100.
        total = self.total_weight or 1.0
        score = round(raw * 100.0 / total, 1)

        return ScoredOpportunity(
            opportunity=opp,
            score=score,
            win_probability=self._band(score),
            breakdown=breakdown,
            reasons=reasons or ["Meets baseline fit"],
            risks=risks or ["No major risks flagged"],
            decision_maker=opp.decision_maker or self._infer_decision_maker(opp),
        )

    def rank(self, opportunities: List[Opportunity]) -> List[ScoredOpportunity]:
        """Score every opportunity and return them sorted best-first."""
        scored = [self.score(opp) for opp in opportunities]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    @staticmethod
    def _band(score: float) -> WinProbability:
        if score >= HIGH_THRESHOLD:
            return WinProbability.HIGH
        if score >= MEDIUM_THRESHOLD:
            return WinProbability.MEDIUM
        return WinProbability.LONG_SHOT

    @staticmethod
    def _infer_decision_maker(opp: Opportunity) -> str:
        text = f"{opp.need} {opp.description}".lower()
        if any(k in text for k in ("film", "tv", "trailer", "sync", "supervis")):
            return "Likely Music Supervisor / Producer"
        if any(k in text for k in ("brand", "campaign", "advert", "commercial", "marketing")):
            return "Likely Producer / Creative Director"
        if any(k in text for k in ("event", "live", "experien")):
            return "Likely Event / Experiential Producer"
        if any(k in text for k in ("rfp", "tender", "procure", "government", "agency")):
            return "Likely Procurement / Program Manager"
        return "Likely Producer / Creative Director"
