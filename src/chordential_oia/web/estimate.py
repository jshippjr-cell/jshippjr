"""The web layer's one way to price an opportunity.

Estimation itself is a first-class intelligence-layer engine in
:mod:`chordential_oia.estimation`; this module is the seam that turns *a row in
the database* into an estimate, and it exists so that turning is done exactly
once (ADR-0033).

``estimate_for`` is that path. Before it, the four lines that resolve a
discipline, derive a team shape and call the engine were copy-pasted at nine
call sites — in three different versions. Two of them (the dashboard KPI and the
project estimate) used ``qual.discipline`` raw where the other seven applied a
qualified-fallback, so an unqualified deal was priced differently depending on
which page you opened; and only one resolved the assigned creators' real rates,
so the number a client approved could differ from the proposal generated after
assignment. Use ``estimate_for``; do not re-derive the arguments by hand.
"""

from __future__ import annotations

from typing import Optional

from ..estimation import (  # noqa: F401
    BAND_SPREAD,
    ROLE_HOURS,
    ROLE_RATES,
    TARGET_MARGIN,
    Estimate,
    EstimationEngine,
    Multiplier,
    RoleLine,
    build_estimate,
)

def estimate_for(opp, *, conn=None, project_id: Optional[int] = None, qual=None) -> Estimate:
    """THE estimate for an opportunity. One discipline fallback, one team shape,
    and the assigned creators' real rates whenever a project is in play.

    ``opp``        an ``Opportunity`` (callers holding a DB row convert first via
                   ``db.opportunity_from_row``).
    ``conn``       a live connection — required only to resolve rate overrides.
    ``project_id`` when given (with ``conn``), the assigned talent's own rates
                   replace the global role defaults, so the internal number and
                   the client-facing proposal cannot diverge after assignment.
    ``qual``       a pre-computed qualification, when the caller already has one;
                   otherwise it is evaluated here.
    """
    from .evaluate import evaluate                      # local: avoids a cycle
    from ..models import MusicDiscipline

    if qual is None:
        qual, _ = evaluate(opp)
    # An unqualified opp has no meaningful discipline of its own — fall back to
    # composition rather than pricing against whatever the classifier guessed.
    # Two call sites skipped this and produced a different number for the same deal.
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    team = list(qual.team_shape or discipline.team_shape)
    overrides = None
    if conn is not None and project_id is not None:
        from . import db as _db
        overrides = _db.assigned_rate_overrides(conn, project_id)
    return build_estimate(opp, team, discipline, rate_overrides=overrides)


__all__ = [
    "estimate_for",
    "BAND_SPREAD",
    "ROLE_HOURS",
    "ROLE_RATES",
    "TARGET_MARGIN",
    "Estimate",
    "EstimationEngine",
    "Multiplier",
    "RoleLine",
    "build_estimate",
]
