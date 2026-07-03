"""Campaign Workspace (Creative OS) — the domain layer for the campaign workspace.

The campaign elevates a project into "one screen, one campaign, everything": the
brief, creative direction, team, timeline, cues, versions, reviews, approvals, rights,
and delivery. This module holds the deterministic domain model (the creative-timeline
phases, the structured direction sections, the feature flag); storage lives in `db.py`
and routes in `app.py`. See docs/campaign-workspace-prd.md.

Ships behind CHORDENTIAL_CAMPAIGN_WORKSPACE (default OFF) so the existing product is
untouched until the workspace is dogfooded on a real campaign.
"""
from __future__ import annotations

import os
from typing import List, Optional

_FALSEY = {"0", "false", "no", "off", ""}


def workspace_enabled() -> bool:
    """The Campaign Workspace flag. Now ON by default — Jon has decided to dogfood it
    in prod, and a code default deploys reliably (unlike a render.yaml env-var-only
    change, which Render doesn't always re-apply to a running service). Set
    CHORDENTIAL_CAMPAIGN_WORKSPACE=0 to hide it again."""
    return os.environ.get(
        "CHORDENTIAL_CAMPAIGN_WORKSPACE", "1").strip().lower() not in _FALSEY


# The creative timeline — a music-campaign arc, NOT a generic todo board. The
# campaign's phase moves along this rail; transitions are human-driven (the machine
# proposes the next phase, a person advances it — Constitution §4.1).
PHASES: List[str] = [
    "Briefing",          # assembling creative direction + crew
    "Direction",         # composer exploring; Direction A/B submitted (internal)
    "Internal Review",   # producer vets before any client exposure (publish gate)
    "Agency Review",     # a published version is with the agency for feedback
    "Revisions",         # bounded, counted revision rounds
    "Approved",          # agency final approval captured
    "Delivered",         # rights + cue sheet + package released
    "Archived",          # closed; retained as moat data
]


def next_phase(phase: str) -> Optional[str]:
    """The phase the machine PROPOSES next (a human still advances it). None at the end."""
    try:
        i = PHASES.index(phase)
    except ValueError:
        return None
    return PHASES[i + 1] if i + 1 < len(PHASES) else None


def phase_index(phase: str) -> int:
    try:
        return PHASES.index(phase)
    except ValueError:
        return 0


# The structured creative-direction sections — the composer's brief, as checklist-able
# pieces. This is the single most "Creative OS, not PM" object: a real, sectioned
# brief the composer inherits, not a description field.
DIRECTION_SECTIONS = [
    ("emotional_arc", "Emotional Arc",
     "The feeling and its shape over time — where it starts, turns, and lands."),
    ("reference_playlist", "Reference Playlist",
     "Tracks that point at the target — with a word on why each one."),
    ("agency_notes", "Agency Notes",
     "What the agency asked for, in their words."),
    ("producer_notes", "Producer Notes",
     "Your creative read and the guardrails for the composer."),
    ("brand_history", "Brand History",
     "The brand's sonic past — what they've sounded like, what to honor or avoid."),
    ("previous_campaigns", "Previous Campaigns",
     "What we (or others) made for them before, and how it landed."),
]

DIRECTION_KEYS = [key for key, _, _ in DIRECTION_SECTIONS]
DIRECTION_LABELS = {key: label for key, label, _ in DIRECTION_SECTIONS}


def hydrate_phase_from_delivery(delivery: dict) -> str:
    """Map an existing project's delivery state onto a starting campaign phase, so a
    campaign opened over in-flight work lands in a sensible place rather than 'Briefing'."""
    state = (delivery or {}).get("state") or ""
    return {
        "Released": "Delivered",
        "Delivered": "Delivered",
        "Approved": "Approved",
        "In review": "Agency Review",
        "In production": "Direction",
    }.get(state, "Briefing")


def direction_completeness(direction: dict) -> dict:
    """Completeness of the creative direction — {done, total, pct} — for the brief's
    progress meter. A section counts as done when explicitly marked complete."""
    total = len(DIRECTION_SECTIONS)
    done = sum(1 for key in DIRECTION_KEYS
               if key in direction and direction[key]["complete"])
    return {"done": done, "total": total,
            "pct": round(done / total * 100) if total else 0}
