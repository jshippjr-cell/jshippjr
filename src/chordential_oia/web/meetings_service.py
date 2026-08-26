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

import logging
import threading
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
            bot_id = cp.invite(join_url=the_join, meeting_ref=str(opp["id"]),
                               realtime_url=M.realtime_url())
            if bot_id:
                db.update_meeting(conn, mid, bot_id=bot_id, notetaker_provider=cp.name,
                                  status=M.BOT_INVITED)
        except Exception:  # noqa: BLE001 — honest: couldn't arm; stays 'not connected'
            try:
                conn.rollback()      # a half-written arm must not poison what follows
            except Exception:        # noqa: BLE001
                pass
    return db.get_meeting(conn, mid)


_log = logging.getLogger("chordential.meetings")


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


def _call_started(meeting, now=None) -> bool:
    """Has the call BEGUN? Below this there is nothing to ask about.

    The poller keyed off nothing but the meeting's status, and a meeting is `bot_invited`
    from the instant it is booked. So a call booked for next Tuesday was polled from the
    moment of booking — and every one of those polls spent a slice of the give-up budget
    on a recording that could not possibly exist yet. Twenty-four attempts is ~8.6 hours,
    so any call booked more than a day ahead was marked `failed` and never asked again
    BEFORE ANYONE JOINED IT. That is why the bot never came back with a transcript.

    Waiting for the scheduled END was too much. An operator books thirty minutes, talks
    for two and hangs up — and the poller sat on its hands for the remaining twenty-eight
    while a finished transcript was already waiting. The bot itself reports when it is
    done, so the honest trigger is: start asking once the call has begun, and let the
    provider say whether there is anything yet.

    A meeting with no start time is treated as started: ad-hoc captures have nothing to
    wait for, and refusing to poll them would be the same bug pointing the other way.
    """
    from datetime import datetime, timedelta, timezone
    start = (meeting["start_at"] or "") if "start_at" in meeting.keys() else ""
    if not start:
        return True
    try:
        dt = datetime.fromisoformat(str(start))
    except (ValueError, TypeError):
        return True                      # unparseable: do not strand it, poll it
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        mins = int(meeting["duration_min"] or 30)
    except (ValueError, TypeError, KeyError):
        mins = 30
    return (now or datetime.now(timezone.utc)) >= dt


def _past_scheduled_end(meeting, now=None) -> bool:
    """Is the call past the time it was BOOKED to end? That — not the start — is when the
    give-up budget may begin to run: a bot polled during its own call has not failed at
    anything, and spending attempts on it is how a long call talks itself into `failed`."""
    from datetime import datetime, timedelta, timezone
    start = (meeting["start_at"] or "") if "start_at" in meeting.keys() else ""
    if not start:
        return True
    try:
        dt = datetime.fromisoformat(str(start))
    except (ValueError, TypeError):
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        mins = int(meeting["duration_min"] or 30)
    except (ValueError, TypeError, KeyError):
        mins = 30
    return (now or datetime.now(timezone.utc)) >= dt + timedelta(minutes=max(1, mins))


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


# One in-flight hand-crank fetch per meeting. Pressing the button twice must not run
# the extraction engine twice — that is real money on the second press.
_fetching: set = set()
_fetch_lock = threading.Lock()


def fetch_state(meeting_id: int) -> bool:
    """Is a hand-crank fetch running for this meeting right now?"""
    with _fetch_lock:
        return meeting_id in _fetching


def start_fetch(meeting_id: int) -> str:
    """Kick a transcript fetch off the request thread and return AT ONCE.

    Doing it inline was the wheel of death: the press went out to Recall (up to four
    HTTP round trips) and then ran the ten-agent extraction engine, all inside the
    browser's request. A minute of spinner, and any proxy timeout in between turns a
    working fetch into a failed page.

    Returns a message for the operator. The work carries on behind it and the answer is
    on the meeting when they come back — which is the same contract the poller has.
    """
    with _fetch_lock:
        if meeting_id in _fetching:
            return "Already fetching this transcript — give it a moment and reload."
        _fetching.add(meeting_id)

    def _run():
        conn = None
        try:
            conn = db.connect()
            result = fetch_now(conn, meeting_id)
            _log.info("Hand-crank fetch for meeting %s: %s", meeting_id, result)
        except Exception:  # noqa: BLE001 — a background thread must never die loudly
            _log.exception("Hand-crank fetch for meeting %s failed", meeting_id)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
            with _fetch_lock:
                _fetching.discard(meeting_id)

    threading.Thread(target=_run, name=f"fetch-transcript-{meeting_id}",
                     daemon=True).start()
    return ("Asking the notetaker now. Filing a transcript runs the extraction engine, "
            "so give it up to a minute and reload.")


def fetch_now(conn, meeting_id: int) -> dict:
    """Ask the capture provider for THIS meeting's transcript right now, and ingest it.

    The background poller is the only thing that ever fetched a transcript, which made
    a whole discovery call's notes hostage to a loop the operator cannot see, cannot
    check and cannot restart. Worse, once it gives up (``_POLL_MAX_ATTEMPTS``) the
    meeting is `failed` and is never asked again — so a transcript that lands late, or
    a loop that was not running when it landed, is lost with no way to reach for it.

    This is the hand crank. It ignores the backoff, ignores the give-up, and clears the
    failed state so the poller will resume watching if the answer is "not yet". It
    decides nothing about the campaign — it only asks — which is why the operator may
    press it whenever they like.
    """
    try:
        meeting = db.get_meeting(conn, meeting_id)
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "error": f"could not read the meeting: {type(e).__name__}"}
    if meeting is None:
        return {"ok": False, "error": "no such meeting"}
    if meeting["status"] == M.INGESTED or (meeting["transcript_capture_id"] or ""):
        return {"ok": True, "already": True}
    if not M.capture_configured():
        return {"ok": False, "error": "No notetaker provider is configured, so there is "
                                      "nothing to ask. Paste the notes instead."}
    bot = (meeting["bot_id"] or "").strip()
    if not bot:
        return {"ok": False, "error": "No capture bot was armed for this call — there is "
                                      "no recording to fetch. Paste the notes instead."}
    try:
        transcript = M.get_capture_provider().fetch_transcript(bot)
    except Exception as e:      # noqa: BLE001 — report it, never raise into the request
        return {"ok": False, "error": f"The capture provider errored: {type(e).__name__}"}
    if transcript is None:
        # Not ready is not a failure. Put it back in the poller's sights: reset the
        # give-up so a call that was written off can still arrive.
        db.update_meeting(conn, meeting_id, status=M.BOT_INVITED, error="",
                          poll_attempts=0, last_polled_at="")
        return {"ok": True, "pending": True,
                "error": "The provider has no transcript yet. Watching for it again."}
    try:
        summary = campaign_intake.ingest_transcript(conn, meeting, transcript)
    except Exception as e:      # noqa: BLE001 — an operator pressing a button must never
        # meet a 500. Filing the transcript runs extraction, which can fail for reasons
        # that have nothing to do with the recording; SAY which, and keep the transcript
        # reachable rather than losing the press.
        _log.exception("ingesting transcript for meeting %s failed", meeting_id)
        return {"ok": False,
                "error": f"The transcript came back but filing it failed: {type(e).__name__}: {e}"}
    return {"ok": True, "ingested": True, "capture_id": summary.get("capture_id")}


def poll_and_ingest(conn) -> int:
    """POLLING (the webhook-free path): for every meeting with an armed capture bot that hasn't
    been ingested yet, ask the provider whether its transcript is ready and, if so, ingest it
    through the Meeting → Campaign Intake boundary. Idempotent and fail-soft — a bot still
    recording is retried on a BACKOFF, and after ``_POLL_MAX_ATTEMPTS`` the meeting is marked
    failed with the reason rather than asked for ever — but ONLY once the call has actually
    finished (see ``_call_over``; counting from the booking is what lost every transcript).
    A transient error never crashes the loop. No-ops entirely with the null provider (no
    bots). Returns the count ingested."""
    from datetime import datetime, timezone
    cp = M.get_capture_provider()
    done = 0
    seen = set()
    for status in (M.BOT_INVITED, M.IN_PROGRESS, M.TRANSCRIPT_READY):
        for meeting in db.meetings_by_status(conn, status):
            if meeting["id"] in seen or not (meeting["bot_id"] or "").strip():
                continue
            seen.add(meeting["id"])
            # Nothing to fetch until the call is over, and — the actual bug — no attempt
            # may be SPENT before then. Anything already accrued while the meeting was
            # still in the future is given back, so the give-up window starts when the
            # call ends rather than when it was booked. That also repairs the rows this
            # shipped with, which are sitting on a dozen attempts they never earned.
            # Nothing to fetch before the call begins, and no attempt may be spent
            # then either — counting from the BOOKING is what marked calls failed
            # before anyone joined. Anything accrued early is given back.
            if not _call_started(meeting):
                if (int(meeting["poll_attempts"] or 0)
                        if "poll_attempts" in meeting.keys() else 0):
                    db.update_meeting(conn, meeting["id"], poll_attempts=0,
                                      last_polled_at="")
                continue
            if not _poll_due(meeting):
                continue
            # During the call we ask, but we do not COUNT: a transcript that is not ready
            # while the meeting is still running is not a failure of anything. The budget
            # starts at the booked end time.
            counts = _past_scheduled_end(meeting)
            attempts = (int(meeting["poll_attempts"] or 0)
                        if "poll_attempts" in meeting.keys() else 0) + (1 if counts else 0)
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
