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


def _sender_email() -> str:
    """The address the confirmation actually goes out FROM."""
    return (os.environ.get("CHORDENTIAL_SMTP_FROM", "") or "").strip()


def operator_email_is_a_guess() -> bool:
    """Is the "operator" address really just the SMTP sender, because nobody set one?

    `_operator_email` falls back to CHORDENTIAL_SMTP_FROM, and that fallback is a TRAP:
    an unset operator address looks configured, so every confirmation — and every calendar
    invitation — has been going to the app's own sending address rather than to a person's
    inbox. Nothing failed, nothing logged, and the operator's calendar was simply never
    touched. CHORDENTIAL_OPERATOR_EMAIL is not even declared in render.yaml, so there was
    nothing in the dashboard to prompt for it either.

    The fallback stays (removing it would send confirmations NOWHERE for anyone relying on
    it today), but every surface that shows where a confirmation went says when the address
    was a guess.
    """
    return not (os.environ.get("CHORDENTIAL_OPERATOR_EMAIL", "") or "").strip() and bool(
        _sender_email())


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
    external_meeting_id = notetaker = bot_id = calendar_event_id = armed_at = ""
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
        # 2) arm Recall — but ONLY if the call is already inside the arming window.
        # Booking a bot now for a call next week is what made it ad-hoc: it joins an
        # empty room today and bills for the wait. `arm_due_meetings` books it shortly
        # before the call instead, so a call that never happens costs nothing.
        if M.capture_configured() and join_url and _within_arm_window(start_at):
            try:
                cp = M.get_capture_provider()
                bot_id = cp.invite(join_url=join_url, meeting_ref=str(opp["id"]),
                                   join_at=start_at or "")
                if bot_id:
                    notetaker, status = cp.name, M.BOT_INVITED
                    armed_at = datetime.now(timezone.utc).isoformat()
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
        calendar_event_id=calendar_event_id, manage_token=manage_token, bot_armed_at=armed_at,
        initiated_by=initiated_by, scheduled_by=scheduled_by)

    if request_id:
        db.set_discovery_request_status(conn, request_id, "scheduled", mid)
    # the Opportunity timeline records the meeting (ADR-0017)
    if ci_id:
        # the timeline never blocks the booking — and, inside a savepoint, never
        # poisons it either (see db.best_effort)
        with db.best_effort(conn, "timeline"):
            db.add_ci_event(conn, ci_id, actor=scheduled_by or "operator",
                            verb="meeting_scheduled", facet="engagement", key="discovery_call",
                            to_value=f"{meeting_type} · {fmt_et(start_at)}", source="scheduler")
    _send_confirmations(opp, db.get_meeting(conn, mid), conn=conn)
    return {"ok": True, "meeting": db.get_meeting(conn, mid)}


# ── When the bot is booked ────────────────────────────────────────────────────────
# It used to be booked the moment the CALL was booked, with no join_at. Recall treats
# that as an ad-hoc bot: it goes in immediately, joins an empty room, and sits there
# BILLING until it times out. Every call booked in advance paid for a bot that recorded
# nothing and was spent by the time the meeting came round.
#
# So the bot is booked shortly BEFORE the call instead — far enough ahead that Recall
# schedules it properly (its ad-hoc threshold is 10 minutes, so the lead must exceed
# that) and it waits rather than idling in the room. The consequences are all in the
# same direction:
#
#   • a call that is cancelled or moved before the window costs NOTHING — no bot was
#     ever created, so there is nothing to waste and nothing to stand down;
#   • rescheduling is free for the same reason;
#   • every call already in the book, pointing at one of the old spent bots, is
#     repaired on its own as its window comes round — no sweep, no bulk spend.
#
# Exactly one bot per call that actually happens, and none for a call that doesn't.
def _within_arm_window(start_at: str) -> bool:
    """Is this call close enough that the bot should be booked right now?"""
    if not start_at:
        return True                       # no time given: ad-hoc capture, arm it
    dt = M.parse_iso(start_at)
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt <= datetime.now(timezone.utc) + timedelta(minutes=_arm_lead_minutes())


def _arm_lead_minutes() -> int:
    try:
        v = int(os.environ.get("CHORDENTIAL_NOTETAKER_ARM_LEAD_MIN", "") or 15)
    except ValueError:
        v = 15
    return max(11, v)          # must clear Recall's 10-minute ad-hoc threshold


def arm_due_meetings(conn) -> int:
    """Book a capture bot for every call whose window has come round. Returns how many.

    Idempotent: a call that already has a bot armed for it (bot_armed_at set) is skipped,
    so a tick that runs twice does not buy two bots."""
    if not M.capture_configured():
        return 0
    now = datetime.now(timezone.utc)
    until = now + timedelta(minutes=_arm_lead_minutes())
    try:
        rows = db.meetings_awaiting_bot(conn, until_iso=until.isoformat(),
                                        now_iso=now.isoformat())
    except Exception as e:  # noqa: BLE001 — never take the loop down
        _log.warning("Could not look for calls needing a notetaker (%s)", type(e).__name__)
        return 0
    cp = M.get_capture_provider()
    armed = 0
    for m in rows:
        if (m["meeting_type"] or "zoom") != ZOOM:
            continue
        old = (m["bot_id"] or "").strip()
        if old:
            # one of the old ad-hoc bots: spent long ago, and it must not be left
            # holding a place in the meeting
            try:
                cp.cancel(old)
            except Exception:  # noqa: BLE001
                pass
        try:
            bot_id = cp.invite(join_url=m["join_url"], meeting_ref=str(m["opp_id"]),
                               join_at=m["start_at"] or "")
        except Exception as e:  # noqa: BLE001
            _log.warning("Arming the notetaker for meeting %s failed (%s: %s)",
                         m["id"], type(e).__name__, e)
            continue
        if not bot_id:
            continue
        db.update_meeting(conn, m["id"], bot_id=bot_id, notetaker_provider=cp.name,
                          status=M.BOT_INVITED, bot_armed_at=now.isoformat(),
                          poll_attempts=0, last_polled_at="", error="")
        armed += 1
        _log.info("Notetaker booked for meeting %s at %s (bot %s)",
                  m["id"], m["start_at"], bot_id)
    return armed


def reschedule(conn, meeting, new_start: str, *, duration_min: Optional[int] = None) -> dict:
    """Move a scheduled call to a new time: the calendar event, THE NOTETAKER, the record,
    and the confirmations.

    The notetaker was the missing one, and it made the button a lie. A capture bot is
    booked for a MOMENT — the old bot was scheduled for the old time and nothing here
    moved it, so the operator rescheduled, joined the new call, and sat in it alone. The
    bot is stood down and a new one booked for the new time.

    The status was the second half of the same bug: this reset it to SCHEDULED, and the
    poller only looks at BOT_INVITED / IN_PROGRESS / TRANSCRIPT_READY. So even if a
    transcript had existed, a rescheduled call was quietly dropped from the one loop that
    would have fetched it."""
    dur = duration_min or meeting["duration_min"] or 30
    if meeting["calendar_event_id"] and M.calendar_configured():
        try:
            s = M.parse_iso(new_start)
            if s:
                M.get_calendar_provider().update_event(
                    meeting["calendar_event_id"], start=s, end=s + timedelta(minutes=dur))
        except Exception:  # noqa: BLE001
            pass

    # The old bot was booked for the OLD time and is no use at the new one. Stand it
    # down and clear it: `arm_due_meetings` books a fresh one when the new time comes
    # round. Nothing is bought here, so moving a call — however many times — is free.
    old_bot = (meeting["bot_id"] or "").strip()
    if old_bot and M.capture_configured():
        try:
            M.get_capture_provider().cancel(old_bot)
        except Exception as e:  # noqa: BLE001
            _log.info("Standing down bot %s failed (%s); it will simply expire",
                      old_bot, type(e).__name__)
    db.update_meeting(conn, meeting["id"], start_at=new_start, duration_min=dur,
                      status=M.SCHEDULED, bot_id="", notetaker_provider="",
                      bot_armed_at="", poll_attempts=0, last_polled_at="", error="")
    # A calendar only accepts an update that outranks the one it holds. Advance the
    # sequence for THIS change, so the fourth reschedule moves the block as surely as
    # the first — a fixed number meant every move after the first was thrown away.
    db.bump_ical_sequence(conn, meeting["id"])
    row = db.get_meeting(conn, meeting["id"])
    opp = db.get_opportunity(conn, meeting["opp_id"])
    if opp is not None:
        _send_confirmations(opp, row, rescheduled=True, conn=conn)
    return {"ok": True, "meeting": row}


def cancel(conn, meeting) -> dict:
    """Cancel a call: drop the calendar event, mark canceled, notify the client."""
    if meeting["calendar_event_id"] and M.calendar_configured():
        try:
            M.get_calendar_provider().delete_event(meeting["calendar_event_id"])
        except Exception:  # noqa: BLE001
            pass
    db.update_meeting(conn, meeting["id"], status=M.CANCELED)
    seq = db.bump_ical_sequence(conn, meeting["id"])
    if meeting["request_id"]:
        db.set_discovery_request_status(conn, meeting["request_id"], "new")  # reopen the ask
    opp = db.get_opportunity(conn, meeting["opp_id"])
    if opp is not None:
        # A CANCEL invite (same UID, METHOD:CANCEL) removes the block from a calendar — and
        # only from a calendar WE put it on. It goes back to exactly whoever received the
        # REQUEST, which `invites_for` works out the same way it did then; a CANCEL for a
        # UID that side never held is noise, and a missing one leaves a dead call in the
        # diary of the one person whose only block came from us.
        client_ics, op_ics = invites_for(meeting, opp, cancel=True, sequence=seq)
        if meeting["client_email"]:
            _safe_mail(meeting["client_email"],
                       f"Discovery call canceled · {opp['client']}",
                       "Your discovery call has been canceled. Reply and we'll find another time.",
                       ics=client_ics)
        op = _operator_email()
        if op:
            _safe_mail(op, f"Discovery call canceled · {opp['client']}",
                       f"The discovery call with {meeting['client_name'] or opp['client']} "
                       f"was canceled.", ics=op_ics)
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
    # An invitation whose ORGANIZER is not the address that sent the mail looks forged, and
    # a calendar that suspects a forgery shows the mail without booking anything. SENT-BY is
    # the property that says "this really was sent on the organiser's behalf" (RFC 5545
    # §3.2.18) — needed here because the mail leaves from CHORDENTIAL_SMTP_FROM while the
    # organiser is the operator. Omitted when they are the same address, as they usually are.
    sender = _sender_email()
    sent_by = (f';SENT-BY="mailto:{sender}"'
               if sender and sender.lower() != organizer.lower() else "")
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
        f"ORGANIZER;CN=Chordential{sent_by}:mailto:{organizer}",
    ]
    # The client is a guest: RSVP=TRUE, NEEDS-ACTION. Their calendar shows the block and
    # asks them to reply, which is the most an invitation can do — nobody can write to a
    # stranger's calendar without their permission, and a system that could would be worse.
    #
    # The OPERATOR is the organiser, and was being listed as a guest of their own meeting:
    # RSVP=TRUE, NEEDS-ACTION, so their own calendar greyed the block out and waited for a
    # Yes. Marked ACCEPTED, it lands booked, with nothing to press.
    op = _operator_email()
    for addr, cn in ((meeting["client_email"], meeting["client_name"] or opp["client"]),
                     (op, "Chordential")):
        if not addr:
            continue
        if op and addr.lower() == op.lower():
            lines.append(f"ATTENDEE;CN={_ical_escape(cn)};ROLE=CHAIR;RSVP=FALSE;"
                         f"PARTSTAT=ACCEPTED:mailto:{addr}")
        else:
            lines.append(f"ATTENDEE;CN={_ical_escape(cn)};ROLE=REQ-PARTICIPANT;RSVP=TRUE;"
                         f"PARTSTAT=NEEDS-ACTION:mailto:{addr}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(ln) for ln in lines) + "\r\n"


def _fold(line: str) -> str:
    """Fold a content line to 75 octets (RFC 5545 §3.1).

    Lenient parsers ignore the limit; strict ones (Outlook among them) can reject the whole
    VEVENT over it, and a DESCRIPTION carrying a Zoom URL clears 75 easily. Folding counts
    OCTETS, not characters, and a multi-byte character must not be split across the fold —
    so the split point is found on the encoded bytes and moved back to a character boundary.
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, first = [], True
    while raw:
        limit = 75 if first else 74          # a continuation spends one octet on its space
        chunk, raw = raw[:limit], raw[limit:]
        while raw and (raw[0] & 0xC0) == 0x80:   # never cut inside a UTF-8 sequence
            raw = chunk[-1:] + raw
            chunk = chunk[:-1]
        out.append(chunk.decode("utf-8") if first else " " + chunk.decode("utf-8"))
        first = False
    return "\r\n".join(out)


def _send_confirmations(opp, meeting, *, rescheduled: bool = False, conn=None) -> list:
    when = _fmt(meeting["start_at"])
    verb = "rescheduled to" if rescheduled else "confirmed for"
    manage = f"{_public_base()}/meeting/{meeting['id']}/manage?k={meeting['manage_token']}"
    if meeting["meeting_type"] == PHONE:
        how = "We'll call you at the number on file."
    elif meeting["join_url"]:
        how = f"Join here: {meeting['join_url']}"
    else:
        how = "A meeting link will follow."
    client_ics, op_ics = invites_for(meeting, opp)
    native = _native_event(meeting)
    log: list = []
    if meeting["client_email"]:
        status = _safe_mail(
            meeting["client_email"], f"Discovery call {verb} {when}",
            f"Your discovery call with Chordential is {verb} {when}.\n{how}\n\n"
            # Honest about what an invitation can and cannot do: it puts the block on
            # their calendar if their calendar accepts invitations from us, and a Yes is
            # what confirms it either way. We do not claim to have booked their diary.
            + ("This email carries the calendar invitation, so the call should land on "
               "your calendar. A quick Yes confirms it.\n\n" if client_ics else "")
            + f"Need to change it? {manage}",
            ics=client_ics)
        log.append({"role": "client", "to": meeting["client_email"], "status": status,
                    "invite": bool(client_ics), "native": False})
    op = _operator_email()
    if op:
        # The operator gets the SAME join link + the .ics so the call lands on their
        # calendar too — the earlier operator email carried neither (reported live).
        status = _safe_mail(
            op, f"Discovery call {verb} {when} · {opp['client']}",
            f"{meeting['meeting_type'].title()} call {verb} {when} with "
            f"{meeting['client_name'] or opp['client']} "
            f"({meeting['client_email'] or 'no email'}).\n\n"
            f"{how}\n\n"
            + ("The block is on your calendar; nothing to accept.\n" if op_ics else "")
            + f"Manage / reschedule: {manage}",
            ics=op_ics)
        log.append({"role": "operator", "to": op, "status": status,
                    "invite": bool(op_ics), "native": bool(native and not op_ics),
                    "guessed_address": operator_email_is_a_guess()})
    else:
        # No operator address at all: the booking is real and NOBODY told the operator.
        log.append({"role": "operator", "to": "", "status": "no-address",
                    "invite": False, "native": False, "guessed_address": False})
    if conn is not None:
        db.record_confirmations(conn, meeting["id"], log)
    return log


def invites_for(meeting, opp, *, cancel: bool = False, sequence: Optional[int] = None):
    """The invitation each side should be sent, as ``(client_ics, operator_ics)``.

    Sent to WHOEVER THE PROVIDER DID NOT REACH, which is a per-recipient question and was
    being answered once for both. It has three answers, not two:

      • **No calendar connected.** Nobody was reached; both get the .ics. This is the
        common case and the only one the original code got right.
      • **OAuth as the operator.** Google invites both parties natively. Neither gets one;
        a second invitation with our own UID would be a DUPLICATE entry on both calendars.
      • **Service account.** It books the operator's calendar and invites nobody — it
        cannot, on a consumer calendar. So the client gets the .ics (it is their only
        route to a block, and withholding it was the bug) and the operator does NOT
        (they already have the native event, and a second one would double-book them).

    Collapsing those three onto "did an event id come back" gets one of them wrong
    whichever way you answer it.
    """
    if _native_event(meeting) and _provider_invites_attendees(meeting):
        return None, None
    ics = build_invite_ics(meeting, opp, cancel=cancel,
                           sequence=_ical_seq(meeting) if sequence is None else sequence)
    return ics, (None if _native_event(meeting) else ics)


def _native_event(meeting) -> bool:
    """Did a connected provider create a real calendar event for this meeting?"""
    return bool((meeting["calendar_event_id"] or "").strip()) and M.calendar_configured()


def _ical_seq(meeting) -> int:
    """This meeting's current invitation SEQUENCE, tolerating a row that predates it."""
    try:
        return max(0, int(meeting["ical_sequence"] or 0))
    except (KeyError, IndexError, TypeError, ValueError):
        return 0


def _provider_invites_attendees(meeting) -> bool:
    """Did a connected calendar provider already invite this meeting's attendees itself?"""
    if not _native_event(meeting):
        return False
    try:
        return bool(M.get_calendar_provider().invites_attendees())
    except Exception:  # noqa: BLE001 — an unanswerable seam must not cost anyone their
        return False    # invitation; sending one too many beats sending none


def _safe_mail(to: str, subject: str, text: str, ics: Optional[str] = None) -> str:
    """Send, and REPORT what happened: "sent" | "logged" | "error".

    The status was being returned by the mailer and dropped here, which is why nobody
    could answer "did my invitation go out". Still best-effort — a mail failure never
    blocks a booking — but now it is a failure someone can see."""
    try:
        return mailer.send_email(to, subject, text, ics=ics) or "error"
    except Exception:  # noqa: BLE001 — email is best-effort; a failure never blocks scheduling
        _log.exception("Confirmation to %s could not be sent", to)
        return "error"


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
