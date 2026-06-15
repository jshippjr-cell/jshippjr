"""Domain models for the Opportunity Intelligence Agent.

An ``Opportunity`` captures the raw, normalized facts pulled from a source.
The scoring engine turns it into a ``ScoredOpportunity`` carrying the
0-100 opportunity score, a per-criterion breakdown, a win-probability band,
and the human-readable reasons / risks shown on the scorecard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class MusicRequirement(Enum):
    """How central a music need is to the opportunity."""

    NONE = "none"
    IMPLIED = "implied"  # marketing/video work that usually needs music
    LICENSED = "licensed"  # wants pre-existing / library music
    ORIGINAL = "original"  # explicitly wants original / custom composition

    @property
    def label(self) -> str:
        return {
            MusicRequirement.NONE: "No music need",
            MusicRequirement.IMPLIED: "Implied music need",
            MusicRequirement.LICENSED: "Licensed music need",
            MusicRequirement.ORIGINAL: "Original music required",
        }[self]


class CompetitionLevel(Enum):
    """How crowded the field is expected to be."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgencySize(Enum):
    """Size of the buying organization.

    Boutique and mid-size shops tend to be the best fit for Chordential:
    big enough to have budget, small enough to move fast and value a partner.
    """

    UNKNOWN = "unknown"
    BOUTIQUE = "boutique"
    MID = "mid"
    LARGE = "large"
    ENTERPRISE = "enterprise"


class Relationship(Enum):
    """Prior relationship between Chordential and the client."""

    NONE = "none"
    WARM_LEAD = "warm_lead"  # prior contact / intro / inbound interest
    PAST_CLIENT = "past_client"  # has paid Chordential before


class WinProbability(Enum):
    """Ranking band derived from the opportunity score."""

    HIGH = "High"
    MEDIUM = "Medium"
    LONG_SHOT = "Long-shot"


@dataclass
class Opportunity:
    """A normalized opportunity pulled from a source.

    Only ``client`` and ``need`` are required; every scoring signal is
    optional so partial records from messy sources can still be ranked
    (missing signals score neutrally rather than crashing).
    """

    client: str
    need: str

    # Provenance
    source: str = "unknown"
    url: Optional[str] = None
    posted_date: Optional[date] = None
    opportunity_id: Optional[str] = None

    # Free-text context (used for keyword fallbacks and the scorecard)
    description: str = ""

    # Scoring signals
    music_requirement: MusicRequirement = MusicRequirement.IMPLIED
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    turnaround_days: Optional[int] = None
    location: Optional[str] = None
    remote_friendly: bool = True
    competition: CompetitionLevel = CompetitionLevel.MEDIUM
    agency_size: AgencySize = AgencySize.UNKNOWN
    relationship: Relationship = Relationship.NONE
    decision_maker: Optional[str] = None

    # Arbitrary extra tags surfaced from the source (e.g. "cutdowns", "sync")
    tags: list = field(default_factory=list)

    def budget_display(self) -> str:
        """Human-readable budget string for the scorecard."""
        if self.budget_min is None and self.budget_max is None:
            return "Unknown"
        if self.budget_min is not None and self.budget_max is not None:
            return f"Estimated ${self.budget_min:,.0f}-${self.budget_max:,.0f}"
        amount = self.budget_min if self.budget_min is not None else self.budget_max
        return f"Estimated ${amount:,.0f}"


@dataclass
class ScoreBreakdown:
    """One criterion's contribution to the total score."""

    name: str
    weight: float
    # Normalized 0.0-1.0 signal strength for this criterion.
    normalized: float
    # Human-readable note explaining the score.
    note: str = ""

    @property
    def points(self) -> float:
        """Weighted points contributed toward the 0-100 total."""
        return self.weight * self.normalized


@dataclass
class ScoredOpportunity:
    """An opportunity plus everything the ranking engine produced for it."""

    opportunity: Opportunity
    score: float  # 0-100
    win_probability: WinProbability
    breakdown: list  # list[ScoreBreakdown]
    reasons: list  # list[str] - positive fit factors
    risks: list  # list[str] - things that could lose the deal
    decision_maker: str

    @property
    def client(self) -> str:
        return self.opportunity.client

    @property
    def need(self) -> str:
        return self.opportunity.need
