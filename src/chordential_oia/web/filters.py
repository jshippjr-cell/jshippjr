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
