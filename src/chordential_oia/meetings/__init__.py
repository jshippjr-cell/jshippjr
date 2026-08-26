"""Meeting domain — the business object and its two provider seams (ADR-0015).

``get_meeting_provider`` / ``get_capture_provider`` return the implementation chosen by env,
defaulting to the deterministic Null providers. These are the ONLY seams where Zoom / Recall
slot in; nothing else in the app references a meeting or notetaker SDK, and everything
downstream (Campaign Intake → Campaign Intelligence) consumes the Meeting + a normalized
Transcript, never a provider-specific event.
"""
from __future__ import annotations

import os
from urllib.parse import quote

from .base import (BOT_INVITED, CANCELED, EV_BOT_JOINED, EV_FAILED, EV_IGNORED,
                   EV_TRANSCRIPT_READY, FAILED, INGESTED, IN_PROGRESS, OPEN_STATUSES,
                   SCHEDULED, TRANSCRIPT_READY, CaptureProvider, MeetingEvent, MeetingProvider,
                   ScheduledMeeting, Transcript, TranscriptSegment)
from .availability import Slot, WorkingHours, free_slots, parse_iso, slot_is_free
from .calendar import (CALENDAR_PROVIDER_ENV, CalendarProvider, NullCalendarProvider,
                       calendar_configured, get_calendar_provider)
from .null import NullCaptureProvider, NullMeetingProvider

MEETING_PROVIDER_ENV = "CHORDENTIAL_MEETING_PROVIDER"
CAPTURE_PROVIDER_ENV = "CHORDENTIAL_NOTETAKER_PROVIDER"


def get_meeting_provider() -> MeetingProvider:
    choice = (os.environ.get(MEETING_PROVIDER_ENV, "null") or "null").strip().lower()
    if choice == "zoom":
        from .zoom import ZoomMeetingProvider  # lazy — no import unless selected
        return ZoomMeetingProvider()
    return NullMeetingProvider()


def get_capture_provider() -> CaptureProvider:
    choice = (os.environ.get(CAPTURE_PROVIDER_ENV, "null") or "null").strip().lower()
    if choice == "recall":
        from .recall import RecallCaptureProvider
        return RecallCaptureProvider()
    return NullCaptureProvider()


def capture_configured() -> bool:
    """Is a real capture provider selected (drives the honest 'notetaker connected' state)?"""
    return (os.environ.get(CAPTURE_PROVIDER_ENV, "null") or "null").strip().lower() not in (
        "", "null", "0", "false", "off")


def meeting_configured() -> bool:
    """Is a real meeting (Zoom/Meet/Teams) provider selected?"""
    return (os.environ.get(MEETING_PROVIDER_ENV, "null") or "null").strip().lower() not in (
        "", "null", "0", "false", "off", "manual")


def calendar_route() -> str:
    """HOW a calendar block reaches each party, which is not the same question as whether a
    calendar is connected — and the banner was answering the wrong one. "Calendar: not
    connected" reads as "no block will appear", while in fact the confirmation email carries
    a standard invitation and the block appears either way.

      ``native``    a connected provider invites BOTH parties itself (OAuth as the operator)
      ``operator``  a connected provider books the operator only (a service account cannot
                    invite guests on a consumer calendar); the client is invited by our .ics
      ``invite``    nothing connected; both parties are invited by our .ics
    """
    if not calendar_configured():
        return "invite"
    try:
        p = get_calendar_provider()
        if getattr(p, "config_problem", lambda: "")():
            return "invite"       # the credential is broken; only the .ics will reach anyone
        return "native" if p.invites_attendees() else "operator"
    except Exception:  # noqa: BLE001 — an unanswerable seam is reported as the weaker claim
        return "operator"


def calendar_problem() -> str:
    """What is wrong with the calendar credential, in words, or ``""``.

    Reported because the chip above reads the CONFIGURATION and a configuration can be
    present and unusable at the same time — which is exactly the state that produced a page
    saying "Google invites both calendars" while Google answered 400 to everything."""
    if not calendar_configured():
        return ""
    try:
        return str(getattr(get_calendar_provider(), "config_problem", lambda: "")() or "")
    except Exception:  # noqa: BLE001
        return ""


def integration_status() -> dict:
    """A secret-free snapshot of which discovery seams are switched on (for the setup banner —
    the #1 gotcha is setting a key but forgetting its *_PROVIDER switch)."""
    return {"zoom": meeting_configured(), "recall": capture_configured(),
            "calendar": calendar_configured(), "calendar_route": calendar_route(),
            "calendar_problem": calendar_problem()}


__all__ = [
    "get_meeting_provider", "get_capture_provider", "capture_configured",
    "MeetingProvider", "CaptureProvider", "NullMeetingProvider", "NullCaptureProvider",
    "Transcript", "TranscriptSegment", "ScheduledMeeting", "MeetingEvent",
    "SCHEDULED", "BOT_INVITED", "IN_PROGRESS", "TRANSCRIPT_READY", "INGESTED", "FAILED",
    "CANCELED", "OPEN_STATUSES", "EV_BOT_JOINED", "EV_TRANSCRIPT_READY", "EV_FAILED",
    "EV_IGNORED", "MEETING_PROVIDER_ENV", "CAPTURE_PROVIDER_ENV",
    "meeting_configured", "integration_status",
    "WorkingHours", "Slot", "free_slots", "slot_is_free", "parse_iso",
    "CalendarProvider", "NullCalendarProvider", "get_calendar_provider",
    "calendar_configured", "calendar_route", "calendar_problem",
    "CALENDAR_PROVIDER_ENV",
]

def realtime_url() -> str:
    """Where a capture provider should stream the live transcript — or "" to not ask.

    The Call Copilot (Phase 2 of docs/discovery-copilot-plan.md) needs the provider to POST
    each utterance to us while the call runs. Three things all have to be true, and the
    guard lives HERE rather than at the three places that arm a bot, because a rule copied
    into three call sites is a rule that will hold in two of them:

    * **A token.** Recall verifies a realtime webhook with a token on the URL. Without
      ``CHORDENTIAL_COPILOT_TOKEN`` the endpoint would accept anything anyone posted, so
      with no token we do not ask for the stream at all. Refusing to listen beats
      listening to strangers.

      It is its OWN variable and deliberately not the lifecycle webhook's
      ``CHORDENTIAL_RECALL_WEBHOOK_SECRET``. That one is an HMAC key Recall has to be told
      about in its own workspace settings; setting it to a random string to switch this
      panel on would start rejecting every lifecycle event and quietly stop transcripts
      from being ingested. Any random string will do here — Recall never sees it as
      anything but an opaque query parameter.
    * **A public HTTPS host.** The provider POSTs from the internet. A laptop, a preview
      tunnel, or a `localhost` default cannot receive it, and a bot pointed at an endpoint
      that refuses the connection is worse than one that never streamed — it retries.
    * **Not switched off.** ``CHORDENTIAL_CALL_COPILOT=0`` stands the whole thing down
      without touching the notetaker, which still records and still ingests as before.
    """
    if (os.environ.get("CHORDENTIAL_CALL_COPILOT", "1") or "1").strip() == "0":
        return ""
    # THE ACTIVE PROVIDER HAS TO BE ABLE TO RECEIVE IT. This URL is Recall-shaped — it
    # names Recall's parser in its own path — and was handed to whatever provider happened
    # to be configured. A future Zoom-AI or Fireflies provider, or the Null one, would have
    # been asked to stream to a door that only understands Recall. `parse_realtime` is the
    # capability, so it is what gets asked about, rather than a name.
    cp = get_capture_provider()
    if cp.name != "recall" or not hasattr(cp, "parse_realtime"):
        return ""
    token = (os.environ.get("CHORDENTIAL_COPILOT_TOKEN", "") or "").strip()
    if not token:
        return ""
    base = (os.environ.get("CHORDENTIAL_PUBLIC_DOMAIN", "") or "").strip().rstrip("/")
    if not base.startswith("https://"):
        return ""
    host = base[len("https://"):].split("/")[0].lower()
    if host.startswith("localhost") or host.startswith("127.") or not host:
        return ""
    # The trailing slash before the query is Recall's own instruction: without it their
    # fetcher answers 400 on a URL that carries query parameters.
    return f"{base}/webhooks/capture/recall/live/?token={quote(token, safe='')}"
