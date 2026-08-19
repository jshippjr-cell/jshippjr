"""THE room — one surface, whoever is looking.

Operator decision, 2026-08-18: *"one room, capability-gated by who holds the link,
published versions only."*

Its own router because the room is its own group (ADR-0044): a creator's token, a
client's share link, a reviewer's link and an admin session all arrive at the same URL,
and none of those is "the creator portal". The capability model and the subtraction live
in :mod:`room`; the room's CONTENT is built once by ``creator_routes._room_for_project``.
This module is the door and nothing else.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import contributor_release, signing
from ..talent import profile_completeness
from . import db, room
from .creator_routes import _room_for_project
from .shell import admin_authed, render

router = APIRouter(tags=["room"])


@router.get("/room/{project_id}", response_class=HTMLResponse)
def one_room(request: Request, project_id: int, k: str = "", r: str = "",
             t: str = ""):
    """THE room — one surface, whoever is looking (operator decision, 2026-08-18:
    *"one room, capability-gated by who holds the link, published versions only"*).

    Four credentials reach the same door: a creator's portal token (``?t=``), the
    client's share token (``?k=``), a named reviewer's link (``?r=``), or an admin
    session for the studio. Which one you hold decides your ROLE; the role decides what
    the room is built with — not what the template chooses to hide, because a template
    that forgets an `{% if %}` leaks, and a dict that never held the take cannot.

    The client's copy carries **published versions only**. A buyer who can hear an
    unreviewed take makes the taste gate decorative, and the gate is what protects them
    from a first impression nobody chose.
    """
    from .project_routes import _session_role
    # The operator arm of `_session_role` is "no token, so the login gate already
    # vouched for you" — and this path is EXEMPT from that gate, because a creator and a
    # client have to reach it. Presenting nothing would therefore have been read as
    # "the studio", handing the whole room to anyone who guessed a project id. The
    # exemption is granted only to routes that make their own, stricter check; this is
    # that check.
    if not (t or k or r) and not admin_authed(request):
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        role, who = _session_role(conn, project_id, k, r, t)
        if role is None:
            return HTMLResponse("Not found", status_code=404)
        view = room.room_view(conn, db, project_id, role,
                              build=_room_for_project)
        if view is None:
            return HTMLResponse("Not found", status_code=404)
        # The hats, for a creator who is in the room as one.
        if role == room.TALENT:
            trow = db.get_talent_by_portal_token(conn, t)
            hats = [a["role"] for a in db.list_assignments(conn, project_id)
                    if trow is not None and int(a["talent_id"] or 0) == int(trow["id"])]
            view["roles"] = list(dict.fromkeys(hats))
            view["role"] = " · ".join(view["roles"]) or "Creator"
            viewer = db.talent_from_row(trow) if trow is not None else None
        else:
            viewer = None
        contributors = {project_id: [
            dict(c, signed=db.latest_contributor_signature(
                conn, c["id"], signing.DOC_CONTRIBUTOR_RELEASE) is not None)
            for c in (dict(x) for x in db.list_contributors(conn, project_id))
        ]} if "see_contributors" in view["caps"] else {project_id: []}
    finally:
        conn.close()
    return render(
        request, "creator_portal.html", nav="",
        # The room's own door for each role — the token it must keep presenting.
        token=(t or ""), room_token=(t or k or r), room_token_kind=("t" if t else
                                                                   ("r" if r else "k")),
        t=viewer, completeness=(profile_completeness(viewer) if viewer else 100),
        assignments=[view], all_rooms=[view], focused=project_id,
        contributors=contributors, contributor_roles=contributor_release.ROLES,
        agr_signed=None, agr_counter=None,
        room_role=view["role_in_room"], caps=view["caps"],
    )
