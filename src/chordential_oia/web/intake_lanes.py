"""Campaign Intake — the intake-lane registry (the extensibility framework).

Campaign Intake is an *extensible framework of intake lanes*, none privileged. A LANE is a
small descriptor of *how information arrived* (a discovery call, pasted notes, a transcript, a
producer debrief, an RFP, an email thread, a client brief, or — later — Meet/Teams/Slack/CRM).
Every lane normalizes to the ONE Capture envelope and funnels through the ONE shared pipeline
(extract → contribute → review → propagate) into the ONE Campaign Intelligence object. See
docs/discovery-call-intake-design.md §2 (ADR-0014).

This module is the SINGLE place lanes are enumerated. Adding a lane here (plus, for a new
provider, a seam) never touches the CI model, the extractor contract, or the review surface —
that separation is the whole point of the framework.

A lane carries only edge concerns (label, modality, default stance, the provenance token it
stamps, whether its provider seam is configured). It knows nothing about facets, kinds,
confidence, or the review UI.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

# The two capture STANCES stay orthogonal to the lane (a debrief is a stance, not a lane's
# private concept). Objective = "what happened?" (facts); debrief = "what's your read?"
# (insight / recommendation / open_question / risk — interpretation, never promoted to fact).
OBJECTIVE = "objective"
DEBRIEF = "debrief"

# Arrival kind: synchronous lanes produce a Capture inline (paste/upload); asynchronous lanes
# (a scheduled meeting) produce a Capture later, when a transcript webhook fires.
SYNC = "sync"
ASYNC = "async"


def _env_true(name: str) -> bool:
    return (os.environ.get(name, "") or "").strip().lower() not in ("", "0", "false", "null", "off")


@dataclass(frozen=True)
class Lane:
    """A single intake lane — the edge descriptor. ``available`` is a callable so provider
    seams are re-checked at request time (env can change without a reimport)."""
    key: str                      # stable registry id ("discovery_call")
    label: str                    # human label ("Discovery call")
    icon: str                     # a glyph for the UI
    stance: str                   # the default stance this lane produces
    modality: str                 # notes | transcript | voice | rfp | email | document
    provenance_source: str        # the token stamped on every field this lane contributes
    kind: str                     # SYNC | ASYNC
    describe: str                 # one-line help ("Paste notes from the call")
    available: Callable[[], bool] # is this lane's provider seam configured / usable?

    def is_available(self) -> bool:
        try:
            return bool(self.available())
        except Exception:  # noqa: BLE001 — a seam probe must never break intake
            return False


# Provider-seam availability probes. The seams themselves land in later increments; today the
# meeting/notetaker lanes report unavailable (null by default, ADR-0004) and the UI disables
# them honestly, while every manual lane is always usable.
def _notetaker_configured() -> bool:
    return _env_true("CHORDENTIAL_NOTETAKER_PROVIDER") and _env_true("CHORDENTIAL_MEETING_PROVIDER")


def _always() -> bool:
    return True


# The registry. Order is display order. NONE is privileged — the discovery call sits first
# because it is the richest source, not because the pipeline treats it specially.
LANES: List[Lane] = [
    Lane("discovery_call", "Discovery call", "🎥", OBJECTIVE, "transcript",
         "discovery_call", ASYNC,
         "Schedule a Zoom call; a notetaker records it and the transcript ingests itself.",
         _notetaker_configured),
    Lane("producer_debrief", "Producer debrief", "🎙", DEBRIEF, "voice",
         "producer_debrief", SYNC,
         "Your read after the call — insight, recommendations, risks (kept distinct from fact).",
         _always),
    Lane("meeting_notes", "Meeting notes", "📝", OBJECTIVE, "notes",
         "notes", SYNC, "Paste notes from the call.", _always),
    Lane("meeting_transcript", "Meeting transcript", "📄", OBJECTIVE, "transcript",
         "transcript", SYNC, "Paste a full meeting transcript.", _always),
    Lane("rfp", "RFP", "📋", OBJECTIVE, "rfp",
         "rfp", SYNC, "Paste (or upload) an RFP.", _always),
    Lane("email_thread", "Email thread", "✉️", OBJECTIVE, "email",
         "email", SYNC, "Paste an email thread.", _always),
    Lane("client_brief", "Client brief", "📎", OBJECTIVE, "document",
         "client_brief", SYNC, "Paste (or upload) a client brief.", _always),
]
LANES_BY_KEY: Dict[str, Lane] = {ln.key: ln for ln in LANES}

# Map a (stance, modality) pair to a lane — the back-compat bridge for callers that still speak
# in stance+modality (the current Update Intelligence panel). Debrief is always the producer
# debrief lane regardless of modality; otherwise the modality selects the objective lane.
_MODALITY_TO_LANE = {
    "notes": "meeting_notes", "transcript": "meeting_transcript", "rfp": "rfp",
    "email": "email_thread", "document": "client_brief", "voice": "meeting_notes",
}


def get_lane(key: str) -> Optional[Lane]:
    return LANES_BY_KEY.get(key)


def resolve_lane(*, lane_key: str = "", stance: str = OBJECTIVE,
                 modality: str = "notes") -> Lane:
    """Resolve the lane a capture belongs to. A DEBRIEF stance is a stance-level decision and
    always maps to the producer-debrief lane; otherwise an explicit ``lane_key`` wins, then
    the objective lane for the modality (default: meeting notes). Always returns a lane."""
    if stance == DEBRIEF:
        return LANES_BY_KEY["producer_debrief"]
    if lane_key and lane_key in LANES_BY_KEY:
        return LANES_BY_KEY[lane_key]
    return LANES_BY_KEY.get(_MODALITY_TO_LANE.get(modality, "meeting_notes"),
                            LANES_BY_KEY["meeting_notes"])


def available_lanes() -> List[Lane]:
    """Every lane whose provider seam is configured — what the UI may offer right now."""
    return [ln for ln in LANES if ln.is_available()]


def sync_lanes(available_only: bool = True) -> List[Lane]:
    """The synchronous (paste/upload) lanes for the Update Intelligence source picker."""
    return [ln for ln in LANES
            if ln.kind == SYNC and (ln.is_available() or not available_only)]


def async_lanes() -> List[Lane]:
    """The asynchronous (meeting-driven) lanes — rendered as scheduling actions."""
    return [ln for ln in LANES if ln.kind == ASYNC]
