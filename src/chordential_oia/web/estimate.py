"""Backward-compatible shim.

Estimation is now a first-class intelligence-layer engine in
:mod:`chordential_oia.estimation`. The dashboard imports the same engine so the
web layer carries **no** estimation logic of its own. Kept as a shim so existing
imports (``from .estimate import build_estimate``) keep working.
"""

from __future__ import annotations

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

__all__ = [
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
