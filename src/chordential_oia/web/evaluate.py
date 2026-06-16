"""Single entry point that runs the existing engines on an opportunity.

The dashboard never re-implements scoring or qualification — it calls these
module-level engine singletons so the web layer and the CLI always agree.
"""

from __future__ import annotations

from typing import Tuple

from ..models import Opportunity, QualificationResult, ScoredOpportunity
from ..qualification import QualificationEngine
from ..scoring import ScoringEngine

QUAL_ENGINE = QualificationEngine()
SCORE_ENGINE = ScoringEngine()


def evaluate(opp: Opportunity) -> Tuple[QualificationResult, ScoredOpportunity]:
    """Return (qualification, score) for one opportunity."""
    return QUAL_ENGINE.qualify(opp), SCORE_ENGINE.score(opp)
