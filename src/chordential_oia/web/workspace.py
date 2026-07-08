"""The Client Workspace phase engine (ADR-0018).

One client relationship has one durable, token-gated destination — the Workspace — whose
URL never changes. What changes is its **phase**: a single computed lifecycle state that
is the one answer to "where is this deal." Every later surface (Commercial Review, Kickoff,
Production, Delivery) is a *view* of a phase, not a separate destination.

This module is deliberately pure and DB-free: ``compute_phase`` maps a dict of signals to a
phase, so the mapping is trivially testable and the route layer stays responsible for
gathering the signals. Phases the product hasn't built yet (commercial/kickoff) are already
in the enum and the ordering, guarded by signals that are simply absent until those features
land — so adding them later is data, not a rewrite.
"""
from __future__ import annotations

# The lifecycle, in order. The client walks these left to right; the workspace never
# moves them backward and never changes URL.
INTRO = "intro"
DISCOVERY = "discovery"
BRIEF = "brief"
COMMERCIAL = "commercial"
KICKOFF = "kickoff"
PRODUCTION = "production"
DELIVERY = "delivery"
ARCHIVE = "archive"

PHASES = [INTRO, DISCOVERY, BRIEF, COMMERCIAL, KICKOFF, PRODUCTION, DELIVERY, ARCHIVE]

# Client-facing labels + the one-line "what happens here" for the workspace rail.
PHASE_LABEL = {
    INTRO: "Welcome",
    DISCOVERY: "Discovery",
    BRIEF: "Discovery Summary",
    COMMERCIAL: "Commercial Review",
    KICKOFF: "Kickoff",
    PRODUCTION: "Production",
    DELIVERY: "Delivery",
    ARCHIVE: "Archive",
}
PHASE_BLURB = {
    INTRO: "Say hello and book your discovery call.",
    DISCOVERY: "A short call about your campaign — creative direction, timeline, needs.",
    BRIEF: "What we heard — confirm we understood your campaign correctly.",
    COMMERCIAL: "Your proposal — scope, pricing, timeline and terms, one approval.",
    KICKOFF: "How we'll work together: contacts, cadence, expectations.",
    PRODUCTION: "The work in motion — versions, comments, reviews.",
    DELIVERY: "Final masters, stems, cue sheet, rights — your delivery package.",
    ARCHIVE: "The finished campaign, kept and downloadable.",
}


def phase_index(phase: str) -> int:
    try:
        return PHASES.index(phase)
    except ValueError:
        return 0


def compute_phase(signals: dict) -> str:
    """Map deal signals to the current workspace phase (ADR-0018).

    ``signals`` keys (all optional; absent = False/None):
      archived            — the campaign is closed out and archived
      has_project         — a project has been created (award happened)
      delivered           — the delivery package is complete
      commercial_approved — the client approved the Commercial Review  (future: P3)
      commercial_ready    — a Commercial Review has been generated       (future: P1)
      brief_ready         — the Campaign Brief is meaningful (discovery done / CI populated)
      in_discovery        — a discovery call is booked or offered, not yet completed

    Later-phase signals (commercial/kickoff) are simply absent until those features ship,
    so this function is already shaped for them without special-casing today."""
    if signals.get("archived"):
        return ARCHIVE
    if signals.get("has_project") and signals.get("delivered"):
        return DELIVERY
    # A project created by the client's Commercial approval sits in KICKOFF (the
    # Sales→Production handoff) until the operator confirms Start Production. A legacy/
    # manually-created project (no approved review) skips Kickoff and reads as Production.
    if (signals.get("has_project") and signals.get("commercial_approved")
            and not signals.get("kickoff_complete")):
        return KICKOFF
    if signals.get("has_project"):
        return PRODUCTION
    if signals.get("commercial_approved"):
        return KICKOFF          # approved but the project isn't created yet (safety)
    if signals.get("commercial_ready"):
        return COMMERCIAL
    if signals.get("brief_ready"):
        return BRIEF
    if signals.get("in_discovery"):
        return DISCOVERY
    return INTRO


def rail(phase: str) -> list:
    """The lifecycle rail for the client shell: each phase with its label, blurb, and
    whether it's done / current / upcoming relative to where the deal is now."""
    here = phase_index(phase)
    out = []
    for i, p in enumerate(PHASES):
        state = "done" if i < here else ("current" if i == here else "upcoming")
        out.append({"phase": p, "label": PHASE_LABEL[p], "blurb": PHASE_BLURB[p],
                    "state": state})
    return out
