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

from .. import agreements, contributor_release, delivery, signing
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
        role, who = _session_role(conn, project_id, k, r, t, request)
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
            # The crafts behind the hats — what a deliverable lane is keyed by (ADR-0075).
            view["role_keys"] = list(dict.fromkeys(
                k for k in (delivery.role_key(r) for r in view["roles"]) if k))
            viewer = db.talent_from_row(trow) if trow is not None else None
            # The standing agreement belongs to the CREATOR. Passing None made the banner
            # render its unsigned copy — so a client opening the room was told to read and
            # sign a Composer Agreement, and the studio was told the same. Reported live.
            # …and WHICH standing agreement is theirs depends on their craft (ADR-0082):
            # a mixer's is the Service Agreement, and reading the composer's kind here
            # would tell someone who had signed that they had not.
            _kind = agreements.kind_for(trow) if trow is not None else None
            agr_signed = db.latest_talent_signature(
                conn, trow["id"], agreements.DOC_KINDS[_kind]
            ) if (trow is not None and _kind in agreements.DOC_KINDS) else None
            agr_counter = db.latest_talent_signature(
                conn, trow["id"], agreements.COUNTERSIGN_KINDS[_kind]
            ) if (trow is not None and _kind in agreements.COUNTERSIGN_KINDS) else None
        else:
            viewer, agr_signed, agr_counter, _kind = None, None, None, None
        contributors = {project_id: [
            dict(c, signed=db.latest_contributor_signature(
                conn, c["id"], signing.DOC_CONTRIBUTOR_RELEASE) is not None)
            for c in (dict(x) for x in db.list_contributors(conn, project_id))
        ]} if "see_contributors" in view["caps"] else {project_id: []}
    finally:
        conn.close()
    # The note route needs a real name+email. A creator and the studio have one; a client
    # on a share link may not, so the bar asks — once — and the cookie remembers.
    from .project_routes import _reviewer_identity
    _kn, _km = _reviewer_identity(request)
    needs_identity = (role == room.CLIENT and not (_kn and _km))
    return render(
        request, "creator_portal.html", nav="",
        needs_identity=needs_identity, known_name=_kn, known_email=_km,
        # The room's own door for each role — the token it must keep presenting.
        token=(t or ""), room_token=(t or k or r), room_token_kind=("t" if t else
                                                                   ("r" if r else "k")),
        t=viewer, completeness=(profile_completeness(viewer) if viewer else 100),
        assignments=[view], all_rooms=[view], focused=project_id,
        contributors=contributors, contributor_roles=contributor_release.ROLES,
        agr_signed=agr_signed, agr_counter=agr_counter,
        # …and NAMED, so a mixer's banner does not offer them a writer's agreement.
        agr_label=agreements.LABELS.get(_kind, "Standing agreement"),
        # The name presence should show for this viewer — resolved by
        # `_session_role`, not re-derived from the role, which is why the
        # operator appeared twice as "Studio" and "Operator".
        room_who=who,
        room_role=view["role_in_room"], caps=view["caps"],
    )
