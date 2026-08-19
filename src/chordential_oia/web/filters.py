"""Shared Jinja filter functions.

Pure, presentation-only helpers used by both the internal dashboard
(:mod:`chordential_oia.web.app`) and the public front-of-house site
(:mod:`chordential_oia.web.public`). Kept here so the two surfaces share one
definition rather than drifting apart.
"""

from __future__ import annotations

from typing import Optional


def money(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"${value:,.0f}"


def pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.0f}%"


def slug(value: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in (value or "").lower()).strip("-")


def displayurl(value: Optional[str]) -> str:
    """Render a stored URL compactly — drop the scheme and any trailing slash."""
    if not value:
        return "—"
    return value.split("://", 1)[-1].rstrip("/")


# CSS-class maps for the pipeline vocabularies. Pure view mappings with no application
# state, so they belong beside the other filters rather than in `app.py` (ADR-0044 — that
# file only shrinks). The templates reach them as the globals registered below.
_ACTION_CLASS = {"Pursue": "pursue", "Review": "review", "Watch": "watch", "Pass": "pass"}
_TIER_CLASS = {"A-Tier": "a", "B-Tier": "b", "C-Tier": "c", "Watch": "watch"}
_STATUS_CLASS = {"New": "new", "Pursuing": "pursuing", "Submitted": "submitted",
                 "Won": "won", "Lost": "lost", "Passed": "passed"}
_STRAT_CLASS = {"Door-opener": "door", "High": "high", "Medium": "medium", "Low": "low"}


def action_class(v) -> str:
    return _ACTION_CLASS.get(v, "")


def tier_class(v) -> str:
    return _TIER_CLASS.get(v, "")


def status_class(v) -> str:
    return _STATUS_CLASS.get(v, "")


def strat_class(v) -> str:
    return _STRAT_CLASS.get(v, "")
