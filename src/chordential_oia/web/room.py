"""One room, capability-gated by who holds the link.

The decision (operator, 2026-08-18): *"one room, capability-gated by who holds the link,
published versions only."*

Until now the same engagement had three surfaces — the composer's Session Room, the
client's delivery portal, the operator's console — each with its own template, its own
idea of what a version is, and its own copy of the picture. Three renderings of one
thing is how they drift, and it is why a creator with three hats got three rooms and a
client got a page that looked nothing like the room the work happens in.

So: **one derivation, many reporters** (the rule ADR-0029/0033/0057 already apply to the
queue, the price and the relationship), applied to the room itself. `room_view` builds
the engagement ONCE. `CAPS` decides what a given role is handed. A surface renders what
it is given and asks no further questions.

The gate is server-side and subtractive: content a role may not see is **absent from the
dict**, not hidden in the template. A template that forgets an `{% if %}` then leaks
nothing, which is the only arrangement worth trusting — the client's copy is built by
never putting the pending take in it.

Roles
-----
``operator``  the studio. Sees everything, including what is still pending.
``talent``    the people doing the work. See the brief, the picture, the client's notes,
              their OWN pending submission, and who else played.
``client``    the buyer. Sees the picture, **published versions only**, the notes
              conversation, and the deliverables they are signing off.
"""

from __future__ import annotations

from typing import Optional

OPERATOR, TALENT, CLIENT = "operator", "talent", "client"
ROLES = (OPERATOR, TALENT, CLIENT)

# What each role may do or see. Read as: everything absent is denied.
CAPS = {
    OPERATOR: {
        "see_pending", "see_internal", "see_contributors", "see_captures",
        "see_deliverable_specs", "see_money", "upload_take", "comment",
        "download_source", "approve", "publish",
    },
    TALENT: {
        # Their own pending submission — they uploaded it; hiding it made the portal
        # look like nothing had happened (reported live, and fixed once already).
        "see_pending", "see_internal", "see_contributors", "see_captures",
        "see_deliverable_specs", "upload_take", "comment", "download_source",
    },
    CLIENT: {
        # PUBLISHED VERSIONS ONLY. A client who can hear an unreviewed take makes the
        # taste gate decorative, and the gate is the thing that protects them from a
        # first impression nobody chose.
        "comment", "approve",
    },
}


def caps_for(role: str) -> frozenset:
    """The capability set for a role. An unknown role gets nothing, deliberately —
    a typo must fail closed, not open."""
    return frozenset(CAPS.get(role, frozenset()))


def can(role: str, capability: str) -> bool:
    return capability in caps_for(role)


def priced_notes_only(feedback: dict) -> dict:
    """The composer's list, with everything a human has not yet priced removed.

    ADR-0069. "Request changes" cost a revision round and a plain note cost nothing —
    and both reached the composer and both got worked on. That is an unpriced revision
    channel running beside a counter that says "Round 1 of 2", and the buyer learns which
    lane is free within one project. A note becomes WORK only once the studio has called
    it a conform (picture moved — free), a revision (counts a round), or out of scope
    (quoted separately, never actioned for nothing).

    This is "the machine proposes, Jon disposes" applied to feedback rather than to
    buttons — the same rule, one layer deeper.
    """
    fb = dict(feedback or {})
    kept = [n for n in (fb.get("notes") or [])
            if (n.get("disposition") or "") in ("conform", "revision")]
    fb["notes"] = kept
    fb["open_count"] = sum(1 for n in kept
                           if n.get("kind") in ("comment", "change_request")
                           and not (n.get("resolved") or n.get("addressed")))
    return fb


def room_view(conn, db, project_id: int, role: str, *,
              talent_id: Optional[int] = None, build) -> Optional[dict]:
    """THE engagement, shaped for one role.

    ``build`` is the existing per-project builder (``creator_routes._room_for_project``)
    passed in rather than imported, because that module imports this one — the dependency
    runs one way. This function's whole job is the SUBTRACTION: take the full room and
    remove what this role may not have.
    """
    room = build(conn, project_id)
    if room is None:
        return None
    allowed = caps_for(role)
    room = dict(room)
    room["role_in_room"] = role
    room["caps"] = allowed

    if "see_pending" not in allowed:
        # The published ladder, and nothing else. Not hidden — absent.
        room["pending"] = None
    if "see_contributors" not in allowed:
        room["contributors"] = []
    if "see_captures" not in allowed:
        room["captures"] = []
    if "see_deliverable_specs" not in allowed:
        room["deliverables"] = []
    if role == TALENT:
        # A creator is handed only what has been priced (ADR-0069).
        room["feedback"] = priced_notes_only(room.get("feedback") or {})
    if "see_internal" not in allowed:
        # Studio-side replies on a client note are internal by definition.
        fb = dict(room.get("feedback") or {})
        fb["notes"] = [
            dict(n, replies=[r for r in (n.get("replies") or [])
                             if not r.get("internal")])
            for n in (fb.get("notes") or [])
        ]
        room["feedback"] = fb
    return room
