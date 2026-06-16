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
    """Score-band confidence label derived from the opportunity score."""

    HIGH = "High"
    MEDIUM = "Medium"
    LONG_SHOT = "Long-shot"


class BuyerType(Enum):
    """Who is buying. Drives both the buyer-fit signal and tier rules."""

    UNKNOWN = "unknown"
    AGENCY = "agency"  # creative / ad agency
    BRAND = "brand"  # brand / marketing team buying direct
    PRODUCTION_COMPANY = "production_company"  # film/TV/branded-content shop
    GOVERNMENT = "government"  # public sector / procurement
    EDUCATIONAL = "educational"  # university / school / district


class BuyerValue(Enum):
    """Relationship value of the buyer over time (CMO Strategic-Value input).

    Distinct from :class:`Relationship` (which tracks prior *contact*); this is
    *how much future business* the buyer represents.
    """

    UNKNOWN = "unknown"
    ONE_TIME = "one_time"  # single project, no expected repeat
    REPEAT = "repeat"  # recurring / returning buyer
    ENTERPRISE = "enterprise"  # multi-project / multi-year / portfolio buyer

    @property
    def label(self) -> str:
        return {
            BuyerValue.UNKNOWN: "Unknown",
            BuyerValue.ONE_TIME: "One-time project",
            BuyerValue.REPEAT: "Repeat buyer",
            BuyerValue.ENTERPRISE: "Enterprise buyer",
        }[self]


class Tier(Enum):
    """Strategic action bucket assigned by rule (A/B/C), plus a Watch fallback.

    Tiers are classified by the combination-rules in :mod:`scoring`, not by a
    raw score threshold; the weighted score is used only to rank *within* a tier.
    """

    A = "A-Tier"
    B = "B-Tier"
    C = "C-Tier"
    WATCH = "Watch"

    @property
    def label(self) -> str:
        return {
            Tier.A: "A-Tier — Pursue Immediately",
            Tier.B: "B-Tier — Strong Lead",
            Tier.C: "C-Tier — Government / Needs Teaming",
            Tier.WATCH: "Watch — Monitor Only",
        }[self]

    @property
    def order(self) -> int:
        """Sort rank (A first)."""
        return {Tier.A: 0, Tier.B: 1, Tier.C: 2, Tier.WATCH: 3}[self]


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

    # Which source tier this came from (1=gov/corporate RFP, 2=agency intel,
    # 3=film/TV/production, 4=gaming). None when unknown.
    source_tier: Optional[int] = None

    # --- Primary scoring signals (Chordential commercial model) ---
    buyer_type: BuyerType = BuyerType.UNKNOWN
    # Tri-state booleans: True/False set by the source, None = infer from text.
    commercial_campaign: Optional[bool] = None  # commercial/video campaign work
    sonic_branding: Optional[bool] = None  # sonic/audio branding mentioned
    video_production: Optional[bool] = None  # video production included
    music_requirement: MusicRequirement = MusicRequirement.IMPLIED
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    location: Optional[str] = None

    # --- Secondary signals (used by the alternate win-probability profile) ---
    turnaround_days: Optional[int] = None
    remote_friendly: bool = True
    competition: CompetitionLevel = CompetitionLevel.MEDIUM
    agency_size: AgencySize = AgencySize.UNKNOWN
    relationship: Relationship = Relationship.NONE
    decision_maker: Optional[str] = None

    # --- CMO Strategic-Value inputs (buyer relationship value + door-opener) ---
    buyer_value: BuyerValue = BuyerValue.UNKNOWN
    marquee: bool = False  # marquee brand / named agency — a strategic door-opener

    # Arbitrary extra tags surfaced from the source (e.g. "cutdowns", "sync")
    tags: list = field(default_factory=list)

    @property
    def budget_midpoint(self) -> Optional[float]:
        """Midpoint of the disclosed budget range, or None if undisclosed."""
        if self.budget_min is not None and self.budget_max is not None:
            return (self.budget_min + self.budget_max) / 2
        if self.budget_min is not None:
            return self.budget_min
        if self.budget_max is not None:
            return self.budget_max
        return None

    @property
    def budget_disclosed(self) -> bool:
        return self.budget_midpoint is not None

    def budget_display(self) -> str:
        """Human-readable budget string for the scorecard."""
        if self.budget_min is None and self.budget_max is None:
            return "Unknown"
        if self.budget_min is not None and self.budget_max is not None:
            return f"Estimated ${self.budget_min:,.0f}-${self.budget_max:,.0f}"
        amount = self.budget_min if self.budget_min is not None else self.budget_max
        return f"Estimated ${amount:,.0f}"


class MusicDiscipline(Enum):
    """The kind of music craft an opportunity calls for (Qualify Stage 1).

    ``fit_weight`` expresses how Chordential-shaped each discipline is: core
    original craft scores full, adjacent disciplines are weighted down, and
    ``NON_CRAFT`` is the disqualified bucket routed out by Stage 0.
    """

    COMPOSITION = "composition"  # original scoring / custom music — the bullseye
    SONIC_BRANDING = "sonic_branding"  # mnemonics / sound logos — core, sticky
    SOUND_DESIGN = "sound_design"  # core craft, often bundled with composition
    ARRANGEMENT = "arrangement"  # arrangement / orchestration — core-adjacent
    SUPERVISION = "supervision"  # music supervision / sync placement — adjacent
    LICENSING = "licensing"  # pre-existing / library music — weak fit
    NON_CRAFT = "non_craft"  # not Chordential-shaped — disqualified

    @property
    def label(self) -> str:
        return {
            MusicDiscipline.COMPOSITION: "Original composition",
            MusicDiscipline.SONIC_BRANDING: "Sonic branding",
            MusicDiscipline.SOUND_DESIGN: "Sound design",
            MusicDiscipline.ARRANGEMENT: "Arrangement / orchestration",
            MusicDiscipline.SUPERVISION: "Music supervision",
            MusicDiscipline.LICENSING: "Licensing (pre-existing)",
            MusicDiscipline.NON_CRAFT: "Not music craft",
        }[self]

    @property
    def fit_weight(self) -> float:
        """0.0-1.0 craft-fit strength used by the Stage 2 rubric."""
        return {
            MusicDiscipline.COMPOSITION: 1.0,
            MusicDiscipline.SONIC_BRANDING: 1.0,
            MusicDiscipline.SOUND_DESIGN: 1.0,
            MusicDiscipline.ARRANGEMENT: 0.8,
            MusicDiscipline.SUPERVISION: 0.5,
            MusicDiscipline.LICENSING: 0.3,
            MusicDiscipline.NON_CRAFT: 0.0,
        }[self]

    @property
    def team_shape(self) -> list:
        """Default team roles, handed to the estimator (Estimation Agent input)."""
        return {
            MusicDiscipline.COMPOSITION: ["Composer", "Mixer", "Music Editor"],
            MusicDiscipline.SONIC_BRANDING: ["Composer", "Sound Designer", "Mixer"],
            MusicDiscipline.SOUND_DESIGN: ["Sound Designer", "Mixer"],
            MusicDiscipline.ARRANGEMENT: ["Arranger", "Orchestrator", "Mixer"],
            MusicDiscipline.SUPERVISION: ["Music Supervisor"],
            MusicDiscipline.LICENSING: ["Music Supervisor"],
            MusicDiscipline.NON_CRAFT: [],
        }[self]


class Confidence(Enum):
    """How explicit the deciding signals were (vs inferred from free text)."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class QualificationAction(Enum):
    """Routing decision emitted by the qualification layer."""

    PURSUE = "Pursue"  # qualified, aligned, confident -> real-time alert
    REVIEW = "Review"  # qualified but needs a human look before alerting
    WATCH = "Watch"  # qualified but low alignment -> DB only, full recall
    PASS = "Pass"  # disqualified -> stored for recall, never alerted

    @property
    def alertable(self) -> bool:
        """Only PURSUE fires a real-time alert (precision-biased, Decision #3)."""
        return self is QualificationAction.PURSUE


@dataclass
class QualificationResult:
    """The Qualify-stage verdict for one opportunity (see qualification-spec.md §2).

    Distinct from :class:`ScoredOpportunity`: qualification decides *whether* and
    *how well* something fits (and can hard-reject), while scoring orders the
    opportunities that already qualified.
    """

    qualified: bool
    discipline: MusicDiscipline
    alignment_pct: float  # 0-100 fit-with-Chordential score (Stage 2 rubric)
    fit_summary: str
    recommended_action: QualificationAction
    confidence: Confidence
    needs_human_review: bool
    fit_reasons: list = field(default_factory=list)  # list[str]
    disqualifiers: list = field(default_factory=list)  # list[str]
    gaps: list = field(default_factory=list)  # list[str]
    secondary_disciplines: list = field(default_factory=list)  # list[MusicDiscipline]
    team_shape: list = field(default_factory=list)  # roles, handed to the estimator
    breakdown: list = field(default_factory=list)  # list[ScoreBreakdown]

    @property
    def alertable(self) -> bool:
        return self.recommended_action.alertable


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
    tier: Tier  # A/B/C/Watch action bucket (rule-based)
    win_probability: WinProbability  # score-band confidence label
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
