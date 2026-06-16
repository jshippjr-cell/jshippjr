"""Chordential Opportunity Intelligence Agent (OIA).

Finds, scores, and ranks opportunities that Chordential can win across
government, agency, corporate, production, and creative-industry sources.
"""

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
from .scoring import DEFAULT_WEIGHTS, WIN_PROBABILITY_WEIGHTS, ScoringEngine

__version__ = "0.2.0"

__all__ = [
    "AgencySize",
    "BuyerType",
    "CompetitionLevel",
    "MusicRequirement",
    "Opportunity",
    "Relationship",
    "ScoreBreakdown",
    "ScoredOpportunity",
    "Tier",
    "WinProbability",
    "DEFAULT_WEIGHTS",
    "WIN_PROBABILITY_WEIGHTS",
    "ScoringEngine",
    "__version__",
]
