"""Scheduling — the client's pick page, the operator's manage view, and the capture hook.

ADR-0044, slice 11. Five routes with no helpers of their own; the work is in
:mod:`meeting_scheduler` and :mod:`meetings_service`.

``/meet/{token}`` and ``/meeting/{id}/manage`` are token-gated client surfaces (the gate
exempts them), and ``/webhooks/capture/{provider}`` is the ONE inbound door for meeting
transcripts — verified by the provider's own signature rather than by a session, which is
why it is public.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import copilot, db, meeting_scheduler, meetings_service
from .opportunity_ops import _to_utc_iso
from .shell import render

router = APIRouter(tags=["meetings"])


# ── Client slot pick — public, token-gated by the unguessable proposal token. ─────────
@router.get("/meet/{token}", response_class=HTMLResponse)
def meet_pick_page(request: Request, token: str, pick: str = ""):
    """The client's view of the offered times (Eastern, never UTC). GET never books —
    email scanners prefetch links — it only preselects; the POST confirms."""
    conn = db.connect()
    try:
        prop = db.meeting_proposal_by_token(conn, token)
        if prop is None:
            return HTMLResponse("Not found", status_code=404)
        opp = db.get_opportunity(conn, prop["opp_id"])
        slots = meeting_scheduler.proposal_slots(prop)
        meeting = (db.get_meeting(conn, prop["meeting_id"])
                   if prop["meeting_id"] else None)
    finally:
        conn.close()
    sel = int(pick) if pick.strip().isdigit() and int(pick) < len(slots) else None
    return render(request, "meet.html", nav="", prop=prop, opp=opp, sel=sel,
                  slots_et=[meeting_scheduler.fmt_et(s, long=True) for s in slots],
                  chosen_et=(meeting_scheduler.fmt_et(prop["chosen_slot"], long=True)
                             if prop["chosen_slot"] else ""),
                  meeting=meeting)


@router.post("/meet/{token}/pick")
def meet_pick_submit(token: str, pick: int = Form(...)):
    """The client confirmed an option: first pick wins (transactional lock), the booking runs
    the full engine — Zoom, Recall, calendar invites both sides, confirmations, timeline —
    and the other options expire with the proposal."""
    conn = db.connect()
    try:
        prop = db.meeting_proposal_by_token(conn, token)
        if prop is None:
            return HTMLResponse("Not found", status_code=404)
        meeting_scheduler.book_from_proposal(conn, prop, pick)
    finally:
        conn.close()
    return RedirectResponse(f"/meet/{token}", status_code=303)


# ── Client MANAGE (reschedule / cancel their own call) — token-gated. ─────────────────
@router.get("/meeting/{meeting_id}/manage", response_class=HTMLResponse)
def meeting_manage(request: Request, meeting_id: int, k: str = "", done: str = ""):
    conn = db.connect()
    try:
        m = db.get_meeting(conn, meeting_id)
        if m is None or not m["manage_token"] or not k or not hmac.compare_digest(
                str(k), str(m["manage_token"])):
            return HTMLResponse("Not found", status_code=404)
    finally:
        conn.close()
    return render(request, "meeting_manage.html", nav="", m=m, k=k, done=bool(done))


@router.post("/meeting/{meeting_id}/manage")
def meeting_manage_action(meeting_id: int, k: str = Form(""), action: str = Form(""),
                          date: str = Form(""), time: str = Form(""), tz_offset: str = Form("")):
    conn = db.connect()
    try:
        m = db.get_meeting(conn, meeting_id)
        if m is None or not m["manage_token"] or not k or not hmac.compare_digest(
                str(k), str(m["manage_token"])):
            return HTMLResponse("Not found", status_code=404)
        if action == "cancel":
            meeting_scheduler.cancel(conn, m)
        elif action == "reschedule" and date.strip():
            start_at = _to_utc_iso(f"{date.strip()}T{time.strip() or '09:00'}", tz_offset)
            if start_at:
                meeting_scheduler.reschedule(conn, m, start_at)
    finally:
        conn.close()
    return RedirectResponse(f"/meeting/{meeting_id}/manage?k={k}&done=1", status_code=303)


@router.post("/webhooks/capture/{provider}/live/")
@router.post("/webhooks/capture/{provider}/live")
async def capture_realtime_webhook(provider: str, request: Request, token: str = ""):
    """The LIVE transcript door — Phase 2 of docs/discovery-copilot-plan.md.

    Recall posts one finalized utterance here as it is spoken, several times a minute for
    the length of a call. Separate from the lifecycle webhook next door on purpose: that
    one verifies a signed body and can afford to fetch and ingest a whole transcript, while
    this one runs on a cadence where every millisecond is spent during somebody's
    conversation. It parses, correlates and INSERTs — nothing else.

    Verified by the token on the URL (Recall's own alternative to a workspace signature);
    without `CHORDENTIAL_RECALL_WEBHOOK_SECRET` set we never asked for the stream in the
    first place, so nothing should be arriving. Public surface, like its neighbour: the
    token is the access control, not the admin login.

    Answers 200 to anything it will not act on. A webhook that returns an error teaches the
    sender to retry, and a stream we are deliberately ignoring must not be re-sent all call.
    """
    body = await request.body()
    headers = dict(request.headers)

    def _work():
        conn = db.connect()
        try:
            return copilot.ingest_line(conn, provider, headers, body, token)
        finally:
            conn.close()

    return JSONResponse(await run_in_threadpool(_work))


@router.post("/webhooks/capture/{provider}")
async def capture_webhook(provider: str, request: Request):
    """Capture-provider webhook (Recall.ai, …). The ONE inbound door for meeting transcripts:
    the provider seam verifies + normalizes the payload into a Meeting event, we correlate it
    to a Meeting and ingest the transcript through Campaign Intake. Signature-verified in the
    provider parser, idempotent, and non-blocking (the work is offloaded). Public surface —
    the provider signature, not the admin login, is the access control (ADR-0011/0015)."""
    body = await request.body()
    headers = dict(request.headers)

    def _work():
        conn = db.connect()
        try:
            return meetings_service.handle_capture_webhook(conn, provider, headers, body)
        finally:
            conn.close()

    result = await run_in_threadpool(_work)
    return JSONResponse(result)
