"""Meeting domain — the business object and its two provider seams (ADR-0015).

``get_meeting_provider`` / ``get_capture_provider`` return the implementation chosen by env,
defaulting to the deterministic Null providers. These are the ONLY seams where Zoom / Recall
slot in; nothing else in the app references a meeting or notetaker SDK, and everything
downstream (Campaign Intake → Campaign Intelligence) consumes the Meeting + a normalized
Transcript, never a provider-specific event.
"""
from __future__ import annotations

import os

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


__all__ = [
    "get_meeting_provider", "get_capture_provider", "capture_configured",
    "MeetingProvider", "CaptureProvider", "NullMeetingProvider", "NullCaptureProvider",
    "Transcript", "TranscriptSegment", "ScheduledMeeting", "MeetingEvent",
    "SCHEDULED", "BOT_INVITED", "IN_PROGRESS", "TRANSCRIPT_READY", "INGESTED", "FAILED",
    "CANCELED", "OPEN_STATUSES", "EV_BOT_JOINED", "EV_TRANSCRIPT_READY", "EV_FAILED",
    "EV_IGNORED", "MEETING_PROVIDER_ENV", "CAPTURE_PROVIDER_ENV",
    "WorkingHours", "Slot", "free_slots", "slot_is_free", "parse_iso",
    "CalendarProvider", "NullCalendarProvider", "get_calendar_provider",
    "calendar_configured", "CALENDAR_PROVIDER_ENV",
]
