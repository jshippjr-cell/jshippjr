"""Chordential Opportunity Intelligence Agent (OIA).

Finds, scores, and ranks opportunities that Chordential can win across
government, agency, corporate, production, and creative-industry sources.
"""

from .models import (
    AgencySize,
    BuyerType,
    CompetitionLevel,
    Confidence,
    MusicDiscipline,
    MusicRequirement,
    Opportunity,
    QualificationAction,
    QualificationResult,
    Relationship,
    ScoreBreakdown,
    ScoredOpportunity,
    Tier,
    WinProbability,
)
from .qualification import (
    QUALIFICATION_WEIGHTS,
    QualificationEngine,
    classify_discipline,
    hard_disqualifiers,
    record_label,
)
from .scoring import DEFAULT_WEIGHTS, WIN_PROBABILITY_WEIGHTS, ScoringEngine

__version__ = "0.3.0"

__all__ = [
    "AgencySize",
    "BuyerType",
    "CompetitionLevel",
    "Confidence",
    "MusicDiscipline",
    "MusicRequirement",
    "Opportunity",
    "QualificationAction",
    "QualificationResult",
    "Relationship",
    "ScoreBreakdown",
    "ScoredOpportunity",
    "Tier",
    "WinProbability",
    "DEFAULT_WEIGHTS",
    "WIN_PROBABILITY_WEIGHTS",
    "ScoringEngine",
    "QUALIFICATION_WEIGHTS",
    "QualificationEngine",
    "classify_discipline",
    "hard_disqualifiers",
    "record_label",
    "__version__",
]
