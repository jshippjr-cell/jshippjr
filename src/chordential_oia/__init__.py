"""Chordential Opportunity Intelligence Agent (OIA).

Finds, scores, and ranks opportunities that Chordential can win across
government, agency, corporate, production, and creative-industry sources.
"""

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
from .scoring import DEFAULT_WEIGHTS, ScoringEngine

__version__ = "0.1.0"

__all__ = [
    "AgencySize",
    "CompetitionLevel",
    "MusicRequirement",
    "Opportunity",
    "Relationship",
    "ScoreBreakdown",
    "ScoredOpportunity",
    "WinProbability",
    "DEFAULT_WEIGHTS",
    "ScoringEngine",
    "__version__",
]
