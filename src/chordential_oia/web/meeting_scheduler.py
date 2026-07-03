"""The Meeting Scheduler (ADR-0016) — the ONE engine both initiators use.

Clients REQUEST (a Discovery Request); the OPERATOR schedules. Whether the schedule is driven
from a client request or the operator's manual "Schedule Discovery", it lands here. By type:
  • Zoom  → create the Zoom meeting, arm Recall, send the calendar invite, record the Meeting.
  • Phone → a phone Meeting record + a confirmation email; no Recall, no join link.

Everything external (Zoom, Calendar, Recall, email) is behind a null-by-default seam, so this
works end-to-end with nothing configured (manual link, "not connected", emails logged). Campaign
Intelligence never appears here — it only ever receives Meeting events (ADR-0015).
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import mailer
from .. import meetings as M
from . import campaign_intelligence, campaigns, db

ZOOM, PHONE = "zoom", "phone"


def _public_base() -> str:
    return os.environ.get("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com").rstrip("/")


def _operator_email() -> str:
    return (os.environ.get("CHORDENTIAL_OPERATOR_EMAIL", "")
            or os.environ.get("CHORDENTIAL_SMTP_FROM", "")).strip()


def _fmt(start_at: str) -> str:
    dt = M.parse_iso(start_at)
    return dt.strftime("%a %b %d, %Y · %H:%M UTC") if dt else (start_at or "a time to be set")


def schedule(conn, opp, *, meeting_type: str = ZOOM, start_at: str = "",
             duration_min: int = 30, client_name: str = "", client_email: str = "",
             initiated_by: str = "operator", request_id: Optional[int] = None,
             scheduled_by: str = "operator") -> dict:
    """Schedule a discovery call (the shared engine). Best-effort across every seam; returns
    ``{"ok": True, "meeting": row}`` or ``{"ok": False, "error": …}``. Zoom arms Recall; phone
    never does."""
    meeting_type = PHONE if meeting_type == PHONE else ZOOM
    ci_id = None
    if campaigns.workspace_enabled():
        ci_id = campaign_intelligence.ensure_for_opportunity(conn, opp)["id"]
    manage_token = secrets.token_urlsafe(24)

    join_url = external_meeting_id = notetaker = bot_id = calendar_event_id = ""
    provider = "manual"
    status = M.SCHEDULED

    if meeting_type == ZOOM:
        # 1) host the Zoom meeting (manual if no provider)
        mp = M.get_meeting_provider()
        if mp.name != "manual":
            try:
                hosted = mp.create(topic=(opp["need"] or "Discovery call"),
                                   start_at=start_at, duration_min=duration_min, attendees=[])
                provider, join_url = hosted.provider, hosted.join_url
                external_meeting_id = hosted.external_meeting_id
            except Exception:  # noqa: BLE001 — degrade to manual, never fail the booking
                pass
        # 2) arm Recall (only for Zoom, only when configured + we have a link)
        if M.capture_configured() and join_url:
            try:
                cp = M.get_capture_provider()
                bot_id = cp.invite(join_url=join_url, meeting_ref=str(opp["id"]))
                if bot_id:
                    notetaker, status = cp.name, M.BOT_INVITED
            except Exception:  # noqa: BLE001
                pass

    # 3) calendar invite (both types, if a calendar is connected)
    cal = M.get_calendar_provider()
    if M.calendar_configured() and start_at:
        try:
            start_dt = M.parse_iso(start_at)
            end_dt = (start_dt + timedelta(minutes=duration_min)) if start_dt else None
            if start_dt and end_dt:
                where = join_url if meeting_type == ZOOM else "Phone call"
                calendar_event_id = cal.create_event(
                    summary=f"Discovery call — {opp['client']}",
                    description=(f"Discovery call for {opp['need']}.\n"
                                + (f"Join: {join_url}" if join_url else "We'll call you.")),
                    start=start_dt, end=end_dt,
                    attendees=[e for e in (_operator_email(), client_email) if e],
                    location=where)
        except Exception:  # noqa: BLE001
            pass

    mid = db.create_meeting(
        conn, opp_id=opp["id"], ci_id=ci_id, start_at=start_at, join_url=join_url,
        external_meeting_id=external_meeting_id, duration_min=duration_min or 30,
        provider=(provider if meeting_type == ZOOM else "phone"),
        notetaker_provider=notetaker, bot_id=bot_id, status=status, meeting_type=meeting_type,
        request_id=request_id, client_name=client_name, client_email=client_email,
        calendar_event_id=calendar_event_id, manage_token=manage_token,
        initiated_by=initiated_by, scheduled_by=scheduled_by)

    if request_id:
        db.set_discovery_request_status(conn, request_id, "scheduled", mid)
    _send_confirmations(opp, db.get_meeting(conn, mid))
    return {"ok": True, "meeting": db.get_meeting(conn, mid)}


def reschedule(conn, meeting, new_start: str, *, duration_min: Optional[int] = None) -> dict:
    """Move a scheduled call to a new time: update the calendar event + the record, re-confirm."""
    dur = duration_min or meeting["duration_min"] or 30
    if meeting["calendar_event_id"] and M.calendar_configured():
        try:
            s = M.parse_iso(new_start)
            if s:
                M.get_calendar_provider().update_event(
                    meeting["calendar_event_id"], start=s, end=s + timedelta(minutes=dur))
        except Exception:  # noqa: BLE001
            pass
    db.update_meeting(conn, meeting["id"], start_at=new_start, duration_min=dur,
                      status=M.SCHEDULED)
    row = db.get_meeting(conn, meeting["id"])
    opp = db.get_opportunity(conn, meeting["opp_id"])
    if opp is not None:
        _send_confirmations(opp, row, rescheduled=True)
    return {"ok": True, "meeting": row}


def cancel(conn, meeting) -> dict:
    """Cancel a call: drop the calendar event, mark canceled, notify the client."""
    if meeting["calendar_event_id"] and M.calendar_configured():
        try:
            M.get_calendar_provider().delete_event(meeting["calendar_event_id"])
        except Exception:  # noqa: BLE001
            pass
    db.update_meeting(conn, meeting["id"], status=M.CANCELED)
    if meeting["request_id"]:
        db.set_discovery_request_status(conn, meeting["request_id"], "new")  # reopen the ask
    opp = db.get_opportunity(conn, meeting["opp_id"])
    if opp is not None and (meeting["client_email"] or ""):
        _safe_mail(meeting["client_email"],
                   f"Discovery call canceled — {opp['client']}",
                   f"Your discovery call has been canceled. Reply and we'll find another time.")
    return {"ok": True}


# --------------------------------------------------------------------------- #
def _send_confirmations(opp, meeting, *, rescheduled: bool = False) -> None:
    when = _fmt(meeting["start_at"])
    verb = "rescheduled to" if rescheduled else "confirmed for"
    manage = f"{_public_base()}/meeting/{meeting['id']}/manage?k={meeting['manage_token']}"
    if meeting["meeting_type"] == PHONE:
        how = "We'll call you at the number on file."
    elif meeting["join_url"]:
        how = f"Join here: {meeting['join_url']}"
    else:
        how = "A meeting link will follow."
    if meeting["client_email"]:
        _safe_mail(
            meeting["client_email"], f"Discovery call {verb} {when}",
            f"Your discovery call with Chordential is {verb} {when}.\n{how}\n\n"
            f"Need to change it? {manage}")
    op = _operator_email()
    if op:
        _safe_mail(op, f"Discovery call {verb} {when} — {opp['client']}",
                   f"{meeting['meeting_type'].title()} call {verb} {when} with "
                   f"{meeting['client_name'] or opp['client']} "
                   f"({meeting['client_email'] or 'no email'}).")


def _safe_mail(to: str, subject: str, text: str) -> None:
    try:
        mailer.send_email(to, subject, text)
    except Exception:  # noqa: BLE001 — email is best-effort; a failure never blocks scheduling
        pass


def notify_new_request(request, opp) -> None:
    """Best-effort operator ping when a client submits a Discovery Request (ntfy/email)."""
    body = (f"New discovery request from {request['name'] or 'a client'} "
            f"({request['email'] or 'no email'}) for {opp['client']} — "
            f"{opp['need']}. Prefers {request['preferred_type']}."
            + (f' “{request["message"]}”' if request["message"] else ""))
    topic = os.environ.get("CHORDENTIAL_NTFY_TOPIC", "").strip()
    if topic:
        try:
            import urllib.request
            urllib.request.urlopen(urllib.request.Request(
                f"https://ntfy.sh/{topic}", data=body.encode(),
                headers={"Title": "New discovery request"}), timeout=8)
        except Exception:  # noqa: BLE001
            pass
    if _operator_email():
        _safe_mail(_operator_email(), f"New discovery request — {opp['client']}", body)
