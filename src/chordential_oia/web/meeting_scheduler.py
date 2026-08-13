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

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from .. import mailer
from .. import meetings as M
from . import campaign_intelligence, campaigns, db

ZOOM, PHONE = "zoom", "phone"
_log = logging.getLogger("chordential.meeting_scheduler")


def _public_base() -> str:
    return os.environ.get("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com").rstrip("/")


def _operator_email() -> str:
    return (os.environ.get("CHORDENTIAL_OPERATOR_EMAIL", "")
            or os.environ.get("CHORDENTIAL_SMTP_FROM", "")).strip()


CLIENT_TZ = ZoneInfo("America/New_York")


def to_client_tz(start_at: str) -> Optional[datetime]:
    dt = M.parse_iso(start_at)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CLIENT_TZ)


def fmt_et(start_at: str, *, long: bool = False) -> str:
    """Client-facing time — always Eastern, never UTC (ADR-0017). The tz label is honest
    (EST in winter, EDT in summer) courtesy of zoneinfo."""
    dt = to_client_tz(start_at)
    if dt is None:
        return start_at or "a time to be set"
    hm = dt.strftime("%I:%M %p").lstrip("0")
    if long:
        return f"{dt.strftime('%A')} · {dt.strftime('%B')} {dt.day} · {hm} {dt.strftime('%Z')}"
    return f"{dt.strftime('%a %b')} {dt.day}, {dt.year} · {hm} {dt.strftime('%Z')}"


def et_to_utc_iso(date_str: str, time_str: str) -> str:
    """An operator-entered Eastern wall-clock → ISO UTC for storage."""
    try:
        local = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return local.replace(tzinfo=CLIENT_TZ).astimezone(timezone.utc).isoformat()
    except ValueError:
        return ""


_fmt = fmt_et   # every scheduling email speaks Eastern now


def schedule(conn, opp, *, meeting_type: str = ZOOM, start_at: str = "",
             duration_min: int = 30, client_name: str = "", client_email: str = "",
             join_url: str = "", initiated_by: str = "operator",
             request_id: Optional[int] = None, scheduled_by: str = "operator") -> dict:
    """Schedule a discovery call (the shared engine). Best-effort across every seam; returns
    ``{"ok": True, "meeting": row}``. Zoom arms Recall against whatever join link we have —
    auto-created by the Zoom provider, or one the operator PASTES (e.g. their Personal Meeting
    Room), so the Zoom API is optional: Recall + a pasted link is enough. Phone never arms Recall.
    """
    meeting_type = PHONE if meeting_type == PHONE else ZOOM
    ci_id = None
    if campaigns.workspace_enabled():
        ci_id = campaign_intelligence.ensure_for_opportunity(conn, opp)["id"]
    manage_token = secrets.token_urlsafe(24)

    join_url = (join_url or "").strip()   # an operator-pasted link (used if no Zoom provider)
    external_meeting_id = notetaker = bot_id = calendar_event_id = ""
    provider = "zoom" if join_url else "manual"
    status = M.SCHEDULED

    if meeting_type == ZOOM:
        # 1) host the Zoom meeting via the provider; a pasted link already covers the manual case
        mp = M.get_meeting_provider()
        if mp.name != "manual" and not join_url:
            try:
                hosted = mp.create(topic=(opp["need"] or "Discovery call"),
                                   start_at=start_at, duration_min=duration_min, attendees=[])
                provider, join_url = hosted.provider, hosted.join_url
                external_meeting_id = hosted.external_meeting_id
            except Exception as e:  # noqa: BLE001 — degrade to manual, never fail the booking
                _log.warning("Zoom create failed (%s: %s); meeting stays manual",
                             type(e).__name__, e)
        # 2) arm Recall (only for Zoom, only when configured + we have a link)
        if M.capture_configured() and join_url:
            try:
                cp = M.get_capture_provider()
                bot_id = cp.invite(join_url=join_url, meeting_ref=str(opp["id"]))
                if bot_id:
                    notetaker, status = cp.name, M.BOT_INVITED
            except Exception as e:  # noqa: BLE001
                _log.warning("Recall invite failed (%s: %s); notetaker not armed",
                             type(e).__name__, e)
        elif M.capture_configured() and not join_url:
            _log.info("Recall is configured but no join link exists, so nothing to record; "
                      "check Zoom creation or paste a meeting link.")

    # 3) calendar invite (both types, if a calendar is connected)
    cal = M.get_calendar_provider()
    if M.calendar_configured() and start_at:
        try:
            start_dt = M.parse_iso(start_at)
            end_dt = (start_dt + timedelta(minutes=duration_min)) if start_dt else None
            if start_dt and end_dt:
                where = join_url if meeting_type == ZOOM else "Phone call"
                calendar_event_id = cal.create_event(
                    summary=f"Discovery call · {opp['client']}",
                    description=(f"Discovery call for {opp['need']}.\n"
                                + (f"Join: {join_url}" if join_url else "We'll call you.")),
                    start=start_dt, end=end_dt,
                    attendees=[e for e in (_operator_email(), client_email) if e],
                    location=where)
        except Exception as e:  # noqa: BLE001
            _log.warning("Calendar event create failed (%s: %s); no invite sent",
                         type(e).__name__, e)

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
    # the Opportunity timeline records the meeting (ADR-0017)
    if ci_id:
        try:
            db.add_ci_event(conn, ci_id, actor=scheduled_by or "operator",
                            verb="meeting_scheduled", facet="engagement", key="discovery_call",
                            to_value=f"{meeting_type} · {fmt_et(start_at)}", source="scheduler")
        except Exception:  # noqa: BLE001 — the timeline never blocks the booking
            pass
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
    if opp is not None:
        # A CANCEL invite (same UID, method=CANCEL) removes the block from both calendars —
        # but only when WE placed it via .ics. If the provider made a native event we already
        # delete_event'd it above; a CANCEL .ics for a UID the client never had would be noise.
        native_event = bool((meeting["calendar_event_id"] or "").strip())
        ics = (None if native_event
               else build_invite_ics(meeting, opp, sequence=2, cancel=True))
        if meeting["client_email"]:
            _safe_mail(meeting["client_email"],
                       f"Discovery call canceled · {opp['client']}",
                       "Your discovery call has been canceled. Reply and we'll find another time.",
                       ics=ics)
        op = _operator_email()
        if op:
            _safe_mail(op, f"Discovery call canceled · {opp['client']}",
                       f"The discovery call with {meeting['client_name'] or opp['client']} "
                       f"was canceled.", ics=ics)
    return {"ok": True}


# --- Meeting Proposals — the operator offers up to three times; one pick books it ------- #
def propose(conn, opp, *, slots: list, meeting_type: str = ZOOM, duration_min: int = 30,
            client_name: str = "", client_email: str = "", message: str = "",
            join_url: str = "", request_id: Optional[int] = None) -> dict:
    """Create a proposal (status=draft). ``slots`` are ISO-UTC strings, at most three.
    Nothing is emailed yet — the machine proposes, the operator reviews then sends."""
    slots = [s for s in slots if s][:3]
    if not slots:
        return {"ok": False, "error": "Pick at least one time."}
    pid = db.create_meeting_proposal(
        conn, opp_id=opp["id"], token=secrets.token_urlsafe(24), slots=slots,
        meeting_type=meeting_type, duration_min=duration_min, client_name=client_name,
        client_email=client_email, message=message, join_url=join_url,
        request_id=request_id)
    return {"ok": True, "proposal": db.get_meeting_proposal(conn, pid)}


def proposal_slots(proposal) -> list:
    try:
        return list(json.loads(proposal["slots_json"] or "[]"))
    except Exception:  # noqa: BLE001
        return []


def proposal_email(opp, proposal) -> dict:
    """The client email presenting the options — Eastern times, pick links, no calendar
    exposure. Returned (not sent) so the operator can review it first."""
    pick_base = f"{_public_base()}/meet/{proposal['token']}"
    slots = proposal_slots(proposal)
    lines = []
    for i, s in enumerate(slots):
        lines.append(f"  Option {i + 1} · {fmt_et(s, long=True)}\n  {pick_base}?pick={i}")
    how = ("a Zoom call" if proposal["meeting_type"] == ZOOM else "a phone call")
    first = (proposal["client_name"] or "").split(" ")[0] or "there"
    note = (proposal["message"] or "").strip()
    body = (
        f"Hi {first},\n\n"
        f"Let's find a time for {how} about {opp['need'] or 'your campaign'}. "
        f"Here are a few times that work on our side. Pick whichever suits you and "
        f"everything else (calendar invites, the meeting link) is handled automatically:\n\n"
        + "\n\n".join(lines)
        + (f"\n\n{note}" if note else "")
        + f"\n\nOr see every option here: {pick_base}"
        + "\n\nIf none of these work, just reply and we'll offer more times.\n\n"
        + "Chordential")
    return {"subject": f"Times for our call · {opp['client'] or 'Chordential'}",
            "to": proposal["client_email"] or "", "body": body}


def _prop_field(proposal, key: str) -> str:
    """Read a possibly-absent proposal column (sqlite3.Row raises on unknown keys)."""
    try:
        return (proposal[key] or "")
    except (KeyError, IndexError):
        return ""


def resolved_proposal_email(opp, proposal) -> dict:
    """The EXACT email that will be sent: the operator's edited subject/body when they
    reviewed-and-edited the draft, otherwise the generated one. The preview renders this
    and ``send_proposal`` delivers it, so "Review before it sends" is literal — what you
    see (and can edit) is what goes out."""
    gen = proposal_email(opp, proposal)
    subj = _prop_field(proposal, "subject_override").strip()
    body = _prop_field(proposal, "body_override").strip()
    return {"subject": subj or gen["subject"], "to": gen["to"],
            "body": body or gen["body"], "edited": bool(subj or body),
            "suggested_subject": gen["subject"], "suggested_body": gen["body"]}


def send_proposal(conn, opp, proposal) -> dict:
    """Operator pressed Send: mail the options to the client, mark the proposal sent."""
    email = resolved_proposal_email(opp, proposal)
    if not email["to"]:
        return {"ok": False, "error": "No client email on the proposal."}
    try:
        mailer.send_email(email["to"], email["subject"], email["body"],
                          html=mailer.branded_html(_public_base(), email["body"]))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Email failed: {e}"}
    db.update_meeting_proposal(conn, proposal["id"], status="sent")
    return {"ok": True}


def book_from_proposal(conn, proposal, pick_index: int) -> dict:
    """The client picked an option. Locks it transactionally: first pick wins, the booking
    runs through the ONE engine (Zoom, Recall, calendar invites, confirmations, timeline),
    and the remaining options expire with the proposal."""
    slots = proposal_slots(proposal)
    if not (0 <= pick_index < len(slots)):
        return {"ok": False, "error": "unknown_option"}
    # the lock: only a 'sent' proposal can be booked, exactly once
    cur = conn.execute(
        "UPDATE meeting_proposals SET status = 'booked', chosen_slot = ?, updated_at = ? "
        "WHERE id = ? AND status = 'sent'",
        (slots[pick_index], datetime.now(timezone.utc).isoformat(), proposal["id"]))
    conn.commit()
    if cur.rowcount == 0:
        return {"ok": False, "error": "already_booked",
                "proposal": db.get_meeting_proposal(conn, proposal["id"])}
    opp = db.get_opportunity(conn, proposal["opp_id"])
    if opp is None:
        return {"ok": False, "error": "unknown_option"}
    res = schedule(
        conn, opp, meeting_type=proposal["meeting_type"], start_at=slots[pick_index],
        duration_min=proposal["duration_min"] or 30,
        client_name=proposal["client_name"] or "", client_email=proposal["client_email"] or "",
        join_url=proposal["join_url"] or "", initiated_by="client_pick",
        request_id=proposal["request_id"], scheduled_by="client")
    db.update_meeting_proposal(conn, proposal["id"], meeting_id=res["meeting"]["id"])
    return {"ok": True, "meeting": res["meeting"],
            "proposal": db.get_meeting_proposal(conn, proposal["id"])}


# --------------------------------------------------------------------------- #
def _ical_dt(iso: str) -> str:
    """An ISO instant → iCalendar UTC stamp (``YYYYMMDDTHHMMSSZ``)."""
    dt = M.parse_iso(iso)
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ical_escape(text: str) -> str:
    """Escape a value for an iCalendar text field (RFC 5545 §3.3.11)."""
    return (str(text or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def build_invite_ics(meeting, opp, *, sequence: int = 0, cancel: bool = False) -> Optional[str]:
    """A calendar invite (VCALENDAR/VEVENT) for this meeting, or ``None`` if we don't
    have a real start time to invite to.

    This is the provider-independent path to a calendar block: attached to the
    confirmation email as ``text/calendar; method=REQUEST``, Gmail/Apple/Outlook add
    the event to the recipient's calendar with no Google-API connection required — so
    a block lands on BOTH calendars whether or not the Google seam is configured.

    A stable ``UID`` (per meeting) plus an increasing ``SEQUENCE`` means a reschedule
    updates the same event in-place; ``cancel=True`` (METHOD:CANCEL) removes it.
    """
    start = _ical_dt(meeting["start_at"])
    if not start:
        return None
    end = _ical_dt(
        (M.parse_iso(meeting["start_at"]) + timedelta(
            minutes=meeting["duration_min"] or 30)).isoformat())
    uid = f"chord-meeting-{meeting['id']}@chordential.com"
    is_zoom = meeting["meeting_type"] == ZOOM
    title = f"Discovery call · Chordential × {meeting['client_name'] or opp['client']}"
    join = meeting["join_url"] or ""
    if is_zoom and join:
        desc = f"Discovery call about {opp['need'] or 'your campaign'}.\nJoin here: {join}"
        location = join
    elif is_zoom:
        desc = f"Discovery call about {opp['need'] or 'your campaign'}. A meeting link will follow."
        location = "Online"
    else:
        desc = f"Discovery call about {opp['need'] or 'your campaign'}. We'll call you at the number on file."
        location = "Phone"
    organizer = _operator_email() or "hello@chordential.com"
    method = "CANCEL" if cancel else "REQUEST"
    status = "CANCELLED" if cancel else "CONFIRMED"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Chordential//Meeting Scheduler//EN",
        f"METHOD:{method}", "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SEQUENCE:{max(0, int(sequence))}",
        f"DTSTAMP:{_ical_dt(datetime.now(timezone.utc).isoformat())}",
        f"DTSTART:{start}", f"DTEND:{end}",
        f"SUMMARY:{_ical_escape(title)}",
        f"DESCRIPTION:{_ical_escape(desc)}",
        f"LOCATION:{_ical_escape(location)}",
        f"STATUS:{status}",
        f"ORGANIZER;CN=Chordential:mailto:{organizer}",
    ]
    for addr, cn in ((meeting["client_email"], meeting["client_name"] or opp["client"]),
                     (_operator_email(), "Chordential")):
        if addr:
            lines.append(
                f"ATTENDEE;CN={_ical_escape(cn)};RSVP=TRUE;"
                f"PARTSTAT=NEEDS-ACTION:mailto:{addr}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


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
    # Only attach our .ics when the calendar provider did NOT already create a native event
    # (calendar_event_id is set): with Google connected it invites both parties itself, so a
    # second .ics with a different UID would show up as a DUPLICATE calendar entry. When no
    # provider is connected, the .ics is the only way a block reaches either calendar.
    native_event = bool((meeting["calendar_event_id"] or "").strip())
    ics = (None if native_event
           else build_invite_ics(meeting, opp, sequence=1 if rescheduled else 0))
    if meeting["client_email"]:
        _safe_mail(
            meeting["client_email"], f"Discovery call {verb} {when}",
            f"Your discovery call with Chordential is {verb} {when}.\n{how}\n\n"
            f"The calendar invite is attached. Accept it to add the call to your calendar.\n\n"
            f"Need to change it? {manage}",
            ics=ics)
    op = _operator_email()
    if op:
        # The operator gets the SAME join link + the .ics so the call lands on their
        # calendar too — the earlier operator email carried neither (reported live).
        _safe_mail(
            op, f"Discovery call {verb} {when} · {opp['client']}",
            f"{meeting['meeting_type'].title()} call {verb} {when} with "
            f"{meeting['client_name'] or opp['client']} "
            f"({meeting['client_email'] or 'no email'}).\n\n"
            f"{how}\n\n"
            f"The calendar invite is attached.\n"
            f"Manage / reschedule: {manage}",
            ics=ics)


def _safe_mail(to: str, subject: str, text: str, ics: Optional[str] = None) -> None:
    try:
        mailer.send_email(to, subject, text, ics=ics)
    except Exception:  # noqa: BLE001 — email is best-effort; a failure never blocks scheduling
        pass


def notify_new_request(request, opp) -> None:
    """Best-effort operator ping when a client submits a Discovery Request (ntfy/email)."""
    body = (f"New discovery request from {request['name'] or 'a client'} "
            f"({request['email'] or 'no email'}) for {opp['client']}: "
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
        _safe_mail(_operator_email(), f"New discovery request · {opp['client']}", body)
