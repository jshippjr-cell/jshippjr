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


def process_ready_meetings(conn) -> int:
    """Scheduler fallback: ingest any meeting left at transcript_ready (e.g. a provider that
    signals then requires a fetch). No-ops with the null provider. Returns the count ingested."""
    cp = M.get_capture_provider()
    done = 0
    for meeting in db.meetings_by_status(conn, M.TRANSCRIPT_READY):
        transcript = cp.fetch_transcript(meeting["bot_id"] or "")
        if transcript is not None:
            campaign_intake.ingest_transcript(conn, meeting, transcript)
            done += 1
    return done
