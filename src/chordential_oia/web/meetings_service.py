"""Meeting orchestration (ADR-0015) — the wiring between the Meeting domain and the app.

The Meeting is the business object; this module drives it through its lifecycle using the two
provider seams, and hands the result to Campaign Intake as a Meeting + normalized Transcript.
Nothing here (or downstream) is coupled to a specific provider — the seams (``meetings``
package) and the webhook parser absorb every provider-specific detail.

    schedule()            → host via MeetingProvider + arm capture via CaptureProvider
    handle_capture_webhook() → provider payload → normalized MeetingEvent → ingest
    process_ready_meetings() → scheduler fallback: fetch + ingest any transcript_ready meeting
"""
from __future__ import annotations

from typing import Mapping, Optional

from . import campaign_intake, campaign_intelligence, campaigns, db
from .. import meetings as M


def schedule(conn, opp, *, start_at: str = "", join_url: str = "", duration_min: int = 20,
             scheduled_by: str = "operator"):
    """Schedule a discovery call for an opportunity. Hosts it via the meeting provider (Zoom
    when configured; manual otherwise) and arms the capture provider (Recall when configured).
    Everything is best-effort and honest: a provider that isn't configured simply leaves the
    meeting manual with the operator-supplied link and 'not connected' capture. Returns the
    Meeting row."""
    mp, cp = M.get_meeting_provider(), M.get_capture_provider()
    ci_id = None
    if campaigns.workspace_enabled():
        ci_id = campaign_intelligence.ensure_for_opportunity(conn, opp)["id"]

    hosted = None
    if mp.name != "manual":
        try:
            hosted = mp.create(topic=opp["need"] or "Discovery call", start_at=start_at,
                               duration_min=duration_min, attendees=[])
        except Exception:  # noqa: BLE001 — a provider outage degrades to manual, never errors
            hosted = None
    provider = hosted.provider if hosted else "manual"
    the_join = (hosted.join_url if hosted and hosted.join_url else (join_url or "").strip())
    external_meeting_id = hosted.external_meeting_id if hosted else ""

    mid = db.create_meeting(
        conn, opp_id=opp["id"], ci_id=ci_id, start_at=(start_at or "").strip(),
        join_url=the_join, duration_min=duration_min or 20, provider=provider,
        scheduled_by=scheduled_by, status=M.SCHEDULED)
    if external_meeting_id:
        db.update_meeting(conn, mid, external_meeting_id=external_meeting_id)

    # Arm the capture bot only if a real provider is configured AND we have a join URL.
    if M.capture_configured() and the_join:
        try:
            bot_id = cp.invite(join_url=the_join, meeting_ref=str(opp["id"]))
            if bot_id:
                db.update_meeting(conn, mid, bot_id=bot_id, notetaker_provider=cp.name,
                                  status=M.BOT_INVITED)
        except Exception:  # noqa: BLE001 — honest: couldn't arm; stays 'not connected'
            pass
    return db.get_meeting(conn, mid)


def handle_capture_webhook(conn, provider_key: str, headers: Mapping, body: bytes) -> dict:
    """Turn a capture-provider webhook into a normalized Meeting event and act on it. Verifies
    + parses via the provider seam (the ONE place a provider payload is understood), correlates
    to a Meeting by bot id, and ingests the transcript through Campaign Intake. Idempotent; a
    payload we can't verify/match is ignored, never trusted."""
    cp = M.get_capture_provider()
    if cp.name != provider_key:
        return {"ok": True, "ignored": "provider-not-active"}
    ev = cp.parse_webhook(headers, body)
    if ev.type == M.EV_IGNORED:
        return {"ok": True, "ignored": True}
    meeting = db.meeting_by_external(conn, ev.external_ref)
    if meeting is None:
        return {"ok": True, "unmatched": True}     # a bot we didn't originate — don't guess
    if ev.type == M.EV_FAILED:
        db.update_meeting(conn, meeting["id"], status=M.FAILED, error=ev.error)
        return {"ok": True, "failed": True}
    if ev.type == M.EV_TRANSCRIPT_READY:
        if meeting["status"] == M.INGESTED:
            return {"ok": True, "duplicate": True}  # re-delivery — no double ingest
        db.update_meeting(conn, meeting["id"], status=M.TRANSCRIPT_READY)
        transcript = ev.transcript or cp.fetch_transcript(ev.external_ref)
        if transcript is not None:
            summary = campaign_intake.ingest_transcript(conn, meeting, transcript)
            return {"ok": True, "ingested": True, "capture_id": summary.get("capture_id")}
        return {"ok": True, "transcript_ready": True}   # scheduler tick will fetch + ingest
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Polling: back off, and eventually stop
# --------------------------------------------------------------------------- #
# "Retried next tick" had no end. The loop asked the provider about every un-ingested
# bot every base tick — ~30 seconds — for as long as the row existed. A bot that
# reaches `done` and produces no transcript (a call with no audio, a bot removed from
# the room, a provider that simply never renders one) returns None forever, so the
# meeting is asked again ~2,880 times a day, for ever, each time logging a WARNING.
#
# The cost is not really the API calls. It is that **a failed capture is invisible**:
# the discovery call's notes never arrive, the meeting sits in `transcript_ready`
# looking like it is still working, and nobody is told the recording is not coming.
# The operator finds out when they go looking for notes that do not exist.
#
# So: a schedule that is dense early (transcripts usually land within minutes of a
# call ending) and decays, and a give-up that writes a REAL terminal state with the
# reason in it. Giving up does not decide anything about the campaign — it records
# that the machine could not get the transcript, which is the operator's cue to add
# the notes by hand ("the machine proposes, Jon disposes").
_POLL_BACKOFF = (0, 30, 30, 60, 120, 300, 600, 900, 1800)   # seconds before attempt N
_POLL_MAX_ATTEMPTS = 24                                      # ≈ 8 hours, then stop


def _poll_delay(attempts: int) -> int:
    idx = min(attempts, len(_POLL_BACKOFF) - 1)
    return _POLL_BACKOFF[idx]


def _poll_due(meeting, now=None) -> bool:
    """Has this meeting's next attempt come round yet?"""
    from datetime import datetime, timezone
    attempts = int(meeting["poll_attempts"] or 0) if "poll_attempts" in meeting.keys() else 0
    last = (meeting["last_polled_at"] or "") if "last_polled_at" in meeting.keys() else ""
    if not last:
        return True
    now = now or datetime.now(timezone.utc)
    try:
        prev = datetime.fromisoformat(str(last))
        if prev.tzinfo is None:
            prev = prev.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return (now - prev).total_seconds() >= _poll_delay(attempts)


def poll_and_ingest(conn) -> int:
    """POLLING (the webhook-free path): for every meeting with an armed capture bot that hasn't
    been ingested yet, ask the provider whether its transcript is ready and, if so, ingest it
    through the Meeting → Campaign Intake boundary. Idempotent and fail-soft — a bot still
    recording is retried on a BACKOFF, and after ``_POLL_MAX_ATTEMPTS`` the meeting is marked
    failed with the reason rather than asked for ever. A transient error never crashes the
    loop. No-ops entirely with the null provider (no bots). Returns the count ingested."""
    from datetime import datetime, timezone
    cp = M.get_capture_provider()
    done = 0
    seen = set()
    for status in (M.BOT_INVITED, M.IN_PROGRESS, M.TRANSCRIPT_READY):
        for meeting in db.meetings_by_status(conn, status):
            if meeting["id"] in seen or not (meeting["bot_id"] or "").strip():
                continue
            seen.add(meeting["id"])
            if not _poll_due(meeting):
                continue
            attempts = (int(meeting["poll_attempts"] or 0)
                        if "poll_attempts" in meeting.keys() else 0) + 1
            db.update_meeting(conn, meeting["id"], poll_attempts=attempts,
                              last_polled_at=datetime.now(timezone.utc).isoformat())
            try:
                transcript = cp.fetch_transcript(meeting["bot_id"])
            except Exception:  # noqa: BLE001 — a provider hiccup is not our failure
                transcript = None
            if transcript is not None:
                campaign_intake.ingest_transcript(conn, meeting, transcript)
                done += 1
            elif attempts >= _POLL_MAX_ATTEMPTS:
                # Stop, and SAY so. A meeting parked in `transcript_ready` for ever looks
                # like it is still working; this is the state that tells the truth.
                db.update_meeting(
                    conn, meeting["id"], status=M.FAILED,
                    error=("No transcript after %d attempts over ~8 hours — the capture "
                           "provider never produced one. The call was not transcribed; "
                           "add the notes by hand." % attempts))
    return done


# Back-compat alias (the webhook path still refers to the fetch-later fallback by this name).
process_ready_meetings = poll_and_ingest
