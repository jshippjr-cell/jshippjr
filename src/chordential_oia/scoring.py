"""The ranking engine.

Two weight profiles ship:

* ``DEFAULT_WEIGHTS`` — Chordential's commercial model (the default). Seven
  signals tuned to surface fast-turnaround commercial/branded music work:

      Commercial / video campaign involved   25
      Agency or production-company buyer      20
      Budget disclosed                        15
      Original music requested                15
      Sonic branding mentioned                10
      Video production included               10
      Miami / Southeast location               5   (soft bonus, never penalizes)

* ``WIN_PROBABILITY_WEIGHTS`` — the original fit/win-probability profile, kept
  as an alternate.

The weighted total (0-100) ranks opportunities *within* a tier. The **tier**
itself (A/B/C/Watch) is assigned by combination-rules in :func:`classify_tier`,
not by a score threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .models import (
    AgencySize,
    BuyerType,
    CompetitionLevel,
    MusicRequirement,
    Opportunity,
    Relationship,
    ScoreBreakdown,
    ScoredOpportunity,
    Tier,
    WinProbability,
)

# A scorer returns (normalized_score in [0,1], human-readable note).
Scorer = Callable[[Opportunity], Tuple[float, str]]

# A-Tier requires a disclosed budget above this floor.
A_TIER_BUDGET_FLOOR = 5_000.0

# Keyword sets for inferring tri-state signals from free text when a source
# leaves them unset (None). Sources should set the booleans explicitly when
# they can; these are the messy-RFP fallback.
_COMMERCIAL_KEYWORDS = (
    "campaign",
    "commercial",
    "advert",
    "brand",
    " ad ",
    "ad spot",
    "spot",
    "promo",
    "social",
    "marketing",
)
_SONIC_BRANDING_KEYWORDS = (
    "sonic brand",
    "sonic branding",
    "sonic logo",
    "sonic identity",
    "audio brand",
    "audio identity",
    "mnemonic",
    "sound logo",
)
_VIDEO_KEYWORDS = (
    "video",
    "film",
    "footage",
    "trailer",
    "shoot",
    "post-production",
    "post production",
    "edit",
    "spot",
    "broadcast",
)

# Miami / US Southeast location markers (soft +5 home-region bonus).
_SOUTHEAST_KEYWORDS = (
    "miami",
    "south florida",
    "florida",
    " fl",
    "orlando",
    "tampa",
    "atlanta",
    "georgia",
    " ga",
    "southeast",
    "fort lauderdale",
    "jacksonville",
    "nashville",
    "tennessee",
    "carolina",
    "alabama",
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _text(opp: Opportunity) -> str:
    return f"{opp.need} {opp.description} {' '.join(opp.tags)}".lower()


# --------------------------------------------------------------------------- #
# Signal resolvers (explicit field, else infer from text)
# --------------------------------------------------------------------------- #
def resolve_commercial_campaign(opp: Opportunity) -> bool:
    if opp.commercial_campaign is not None:
        return opp.commercial_campaign
    if opp.buyer_type in (BuyerType.AGENCY, BuyerType.BRAND):
        return True
    return any(k in _text(opp) for k in _COMMERCIAL_KEYWORDS)


def resolve_sonic_branding(opp: Opportunity) -> bool:
    if opp.sonic_branding is not None:
        return opp.sonic_branding
    return any(k in _text(opp) for k in _SONIC_BRANDING_KEYWORDS)


def resolve_video_production(opp: Opportunity) -> bool:
    if opp.video_production is not None:
        return opp.video_production
    return any(k in _text(opp) for k in _VIDEO_KEYWORDS)


def _is_southeast(opp: Opportunity) -> bool:
    loc = (opp.location or "").lower()
    return any(k in loc for k in _SOUTHEAST_KEYWORDS)


# --------------------------------------------------------------------------- #
# Commercial-model criterion scorers
# --------------------------------------------------------------------------- #
def score_commercial_campaign(opp: Opportunity) -> Tuple[float, str]:
    if opp.commercial_campaign is True:
        return 1.0, "Commercial / video campaign work"
    if opp.commercial_campaign is False:
        return 0.0, "Not a commercial campaign"
    return (
        (0.85, "Reads as commercial/campaign work")
        if resolve_commercial_campaign(opp)
        else (0.1, "No commercial-campaign signal")
    )


def score_buyer_type(opp: Opportunity) -> Tuple[float, str]:
    mapping = {
        BuyerType.AGENCY: (1.0, "Agency buyer"),
        BuyerType.BRAND: (1.0, "Brand / marketing buyer"),
        BuyerType.PRODUCTION_COMPANY: (0.85, "Production-company buyer"),
        BuyerType.GOVERNMENT: (0.3, "Government buyer (procurement-heavy)"),
        BuyerType.EDUCATIONAL: (0.4, "Educational buyer (procurement-heavy)"),
        BuyerType.UNKNOWN: (0.4, "Buyer type unknown"),
    }
    return mapping[opp.buyer_type]


def score_budget_disclosed(opp: Opportunity) -> Tuple[float, str]:
    if not opp.budget_disclosed:
        return 0.0, "Budget not disclosed"
    return 1.0, f"Budget disclosed (~${opp.budget_midpoint:,.0f})"


def score_original_music(opp: Opportunity) -> Tuple[float, str]:
    mapping = {
        MusicRequirement.ORIGINAL: (1.0, "Original music requested"),
        MusicRequirement.LICENSED: (0.3, "Licensed (not original) music"),
        MusicRequirement.IMPLIED: (0.4, "Music need implied, not original"),
        MusicRequirement.NONE: (0.0, "No music need stated"),
    }
    return mapping[opp.music_requirement]


def score_sonic_branding(opp: Opportunity) -> Tuple[float, str]:
    return (
        (1.0, "Sonic branding mentioned")
        if resolve_sonic_branding(opp)
        else (0.0, "No sonic-branding signal")
    )


def score_video_production(opp: Opportunity) -> Tuple[float, str]:
    return (
        (1.0, "Video production included")
        if resolve_video_production(opp)
        else (0.0, "No video-production signal")
    )


def score_miami_southeast(opp: Opportunity) -> Tuple[float, str]:
    # Soft home-region bonus: Southeast scores full, everywhere else stays
    # neutral (0.5) so remote / out-of-region work is never penalized.
    if _is_southeast(opp):
        return 1.0, f"Miami / Southeast location ({opp.location})"
    return 0.5, "Outside Southeast (no penalty)"


# --------------------------------------------------------------------------- #
# Win-probability (alternate) criterion scorers
# --------------------------------------------------------------------------- #
_WP_BUDGET_SWEET_MIN = 5_000.0
_WP_BUDGET_SWEET_MAX = 50_000.0


def score_budget_fit(opp: Opportunity) -> Tuple[float, str]:
    mid = opp.budget_midpoint
    if mid is None:
        return 0.5, "Budget unknown (neutral)"
    if _WP_BUDGET_SWEET_MIN <= mid <= _WP_BUDGET_SWEET_MAX:
        return 1.0, f"Budget ~${mid:,.0f} sits in the sweet spot"
    if mid < _WP_BUDGET_SWEET_MIN:
        return _clamp(0.3 + 0.6 * (mid / _WP_BUDGET_SWEET_MIN)), f"Budget ~${mid:,.0f} is modest"
    overshoot = (mid - _WP_BUDGET_SWEET_MAX) / _WP_BUDGET_SWEET_MAX
    return _clamp(0.85 - 0.35 * overshoot), f"Budget ~${mid:,.0f} is large"


def score_turnaround_fit(opp: Opportunity) -> Tuple[float, str]:
    days = opp.turnaround_days
    if days is None:
        return 0.5, "Turnaround unknown (neutral)"
    if days <= 3:
        return 0.35, f"{days}-day turnaround is very tight (delivery risk)"
    if 7 <= days <= 45:
        return 1.0, f"{days}-day turnaround fits Chordential's fast process"
    if days < 7:
        return _clamp(0.6 + 0.4 * ((days - 3) / 4)), f"{days}-day turnaround is quick but doable"
    return 0.7, f"{days}-day turnaround is relaxed"


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


def score_geography_remote(opp: Opportunity) -> Tuple[float, str]:
    if _is_southeast(opp):
        return 1.0, f"Home region ({opp.location})"
    if opp.remote_friendly:
        return 0.7, "Remote-friendly"
    return 0.4, f"On-site, out of region ({opp.location})"


@dataclass
class Criterion:
    """A named, weighted scoring dimension."""

    name: str
    weight: float
    scorer: Scorer


# Chordential commercial model (default). Sums to 100.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "Commercial Campaign": 25,
    "Agency/Production Buyer": 20,
    "Budget Disclosed": 15,
    "Original Music": 15,
    "Sonic Branding": 10,
    "Video Production": 10,
    "Miami/Southeast": 5,
}

# Alternate fit/win-probability model. Sums to 100.
WIN_PROBABILITY_WEIGHTS: Dict[str, float] = {
    "Music Needed": 25,
    "Budget Fit": 20,
    "Turnaround Fit": 15,
    "Competition": 15,
    "Agency Size": 10,
    "Existing Relationship": 10,
    "Geography": 5,
}

_SCORERS: Dict[str, Scorer] = {
    # commercial model
    "Commercial Campaign": score_commercial_campaign,
    "Agency/Production Buyer": score_buyer_type,
    "Budget Disclosed": score_budget_disclosed,
    "Original Music": score_original_music,
    "Sonic Branding": score_sonic_branding,
    "Video Production": score_video_production,
    "Miami/Southeast": score_miami_southeast,
    # win-probability model
    "Music Needed": score_original_music,
    "Budget Fit": score_budget_fit,
    "Turnaround Fit": score_turnaround_fit,
    "Competition": score_competition,
    "Agency Size": score_agency_size,
    "Existing Relationship": score_relationship,
    "Geography": score_geography_remote,
}

# Score-band thresholds for the secondary win-probability label.
HIGH_THRESHOLD = 70.0
MEDIUM_THRESHOLD = 45.0

REASON_THRESHOLD = 0.75
RISK_THRESHOLD = 0.4


def classify_tier(opp: Opportunity) -> Tuple[Tier, str]:
    """Assign an A/B/C/Watch tier from Chordential's combination-rules.

    Returns the tier and a short rationale. Rules are evaluated top-down:

    * **A** — original music AND commercial campaign AND budget > $5k AND
      agency/brand buyer (pursue immediately).
    * **B** — production-company buyer with a likely music component, OR a
      commercial/agency/brand lead with music likely that misses an A condition
      (e.g. budget undisclosed).
    * **C** — government media contract with music buried in a larger scope
      (needs a teaming partner).
    * **Watch** — matches none of the above.
    """
    is_original = opp.music_requirement is MusicRequirement.ORIGINAL
    is_commercial = resolve_commercial_campaign(opp)
    music_likely = opp.music_requirement is not MusicRequirement.NONE
    buyer = opp.buyer_type
    mid = opp.budget_midpoint

    if (
        is_original
        and is_commercial
        and mid is not None
        and mid > A_TIER_BUDGET_FLOOR
        and buyer in (BuyerType.AGENCY, BuyerType.BRAND)
    ):
        return Tier.A, "Original music + commercial campaign + >$5k + agency/brand buyer"

    if buyer is BuyerType.PRODUCTION_COMPANY and music_likely:
        return Tier.B, "Production-company buyer with a likely music component"

    if is_commercial and music_likely and buyer in (BuyerType.AGENCY, BuyerType.BRAND):
        return Tier.B, "Commercial agency/brand lead, music likely (missing an A condition)"

    if buyer is BuyerType.GOVERNMENT and music_likely:
        return Tier.C, "Government media contract; music buried, likely needs teaming"

    return Tier.WATCH, "No A/B/C rule matched; monitor only"


class ScoringEngine:
    """Scores, tiers, and ranks opportunities against weighted criteria."""

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
                ScoreBreakdown(criterion.name, criterion.weight, normalized, note)
            )
            if normalized >= REASON_THRESHOLD:
                reasons.append(note)
            elif normalized <= RISK_THRESHOLD:
                risks.append(note)

        raw = sum(b.points for b in breakdown)
        total = self.total_weight or 1.0
        score = round(raw * 100.0 / total, 1)

        tier, tier_reason = classify_tier(opp)

        return ScoredOpportunity(
            opportunity=opp,
            score=score,
            tier=tier,
            win_probability=self._band(score),
            breakdown=breakdown,
            reasons=[tier_reason] + (reasons or ["Meets baseline fit"]),
            risks=risks or ["No major risks flagged"],
            decision_maker=opp.decision_maker or self._infer_decision_maker(opp),
        )

    def rank(self, opportunities: List[Opportunity]) -> List[ScoredOpportunity]:
        """Score everything, then sort by tier (A→Watch), score within tier."""
        scored = [self.score(opp) for opp in opportunities]
        scored.sort(key=lambda s: (s.tier.order, -s.score))
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
        if opp.buyer_type is BuyerType.AGENCY:
            return "Likely Producer / Creative Director"
        if opp.buyer_type is BuyerType.BRAND:
            return "Likely Brand / Marketing Lead"
        if opp.buyer_type is BuyerType.PRODUCTION_COMPANY:
            return "Likely Executive Producer / Music Supervisor"
        if opp.buyer_type is BuyerType.GOVERNMENT:
            return "Likely Procurement / Program Manager"
        text = _text(opp)
        if any(k in text for k in ("film", "tv", "trailer", "sync", "supervis")):
            return "Likely Music Supervisor / Producer"
        if any(k in text for k in ("event", "live", "experien")):
            return "Likely Event / Experiential Producer"
        return "Likely Producer / Creative Director"
