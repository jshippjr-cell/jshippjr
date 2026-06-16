"""Chordential Opportunity Intelligence Agent (OIA).

Finds, scores, and ranks opportunities that Chordential can win across
government, agency, corporate, production, and creative-industry sources.
"""

from .models import (
    AgencySize,
    BuyerType,
    BuyerValue,
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
from .estimation import Estimate, EstimationEngine, build_estimate
from .prepare import PursuitBrief, build_pursuit_brief
from .strategic import StrategicValue, assess_strategic_value
from .intake import parse_alert_email, parse_email_path
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
    "BuyerValue",
    "CompetitionLevel",
    "Confidence",
    "StrategicValue",
    "assess_strategic_value",
    "Estimate",
    "EstimationEngine",
    "build_estimate",
    "PursuitBrief",
    "build_pursuit_brief",
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
    "parse_alert_email",
    "parse_email_path",
    "__version__",
]
