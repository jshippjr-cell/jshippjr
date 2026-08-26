"""Null providers — the deterministic default (ADR-0004, ADR-0015).

With no provider configured, a Meeting is still a real business object: the operator hosts it
(pastes the join link) and the transcript enters through the manual lanes. Nothing here calls
an external service; nothing raises.
"""
from __future__ import annotations

from typing import Mapping, Optional

from .base import EV_IGNORED, CaptureProvider, MeetingEvent, MeetingProvider, ScheduledMeeting, Transcript


class NullMeetingProvider(MeetingProvider):
    """Manual hosting: no meeting is created remotely; the operator supplies the join link."""
    name = "manual"

    def create(self, *, topic: str, start_at: str, duration_min: int,
               attendees: list) -> ScheduledMeeting:
        return ScheduledMeeting(provider="manual")


class NullCaptureProvider(CaptureProvider):
    """No bot joins; transcripts arrive via the manual paste/upload lanes. Honest, not faked."""
    name = "null"

    def invite(self, *, join_url: str, meeting_ref: str, join_at: str = "",
               realtime_url: str = "") -> str:
        # `realtime_url` is accepted and ignored: no bot means nothing to stream. Accepted
        # rather than omitted because a Protocol implementation that does not match the
        # Protocol is a crash waiting for the day somebody switches providers.
        return ""

    def cancel(self, external_ref: str) -> None:
        return None

    def fetch_transcript(self, external_ref: str) -> Optional[Transcript]:
        return None

    def parse_webhook(self, headers: Mapping, body: bytes) -> MeetingEvent:
        return MeetingEvent(type=EV_IGNORED)
