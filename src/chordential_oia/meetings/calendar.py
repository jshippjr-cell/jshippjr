"""Calendar provider seam (ADR-0016) — availability + event lifecycle behind one contract.

The Meeting Scheduler reads busy-time and writes/cancels events through this seam, never a
calendar SDK. Null by default: no busy-time (availability = plain working hours) and event
writes no-op, so booking still works end-to-end with nothing configured. Google Calendar is the
first real implementation (``google.py``).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional, Protocol, Sequence, Tuple, runtime_checkable

Interval = Tuple[datetime, datetime]


@runtime_checkable
class CalendarProvider(Protocol):
    name: str

    def busy(self, start: datetime, end: datetime) -> List[Interval]:
        """Busy intervals in [start, end) — the events availability must avoid."""
        ...

    def create_event(self, *, summary: str, description: str, start: datetime,
                      end: datetime, attendees: Sequence[str], location: str = "") -> str:
        """Create a calendar event (inviting attendees); return the provider event id."""
        ...

    def update_event(self, event_id: str, *, start: datetime, end: datetime) -> None: ...

    def delete_event(self, event_id: str) -> None: ...

    def invites_attendees(self) -> bool:
        """Does `create_event` actually INVITE the attendees it is given?

        Creating an event and inviting people to it are two different things, and the
        scheduler used to treat them as one: if an event id came back, it suppressed its
        own .ics on the reasoning that the provider had invited everybody. That holds
        for OAuth-as-the-operator; it is false for a service account, which cannot invite
        guests on a consumer calendar and so is deliberately called with no attendees at
        all. In that configuration the block landed on the operator's calendar and the
        CLIENT got a confirmation email announcing an invitation that was not there.

        So the seam answers for itself, and a provider that cannot invite gets the .ics
        sent to whoever it did not reach, alongside its native event rather than instead
        of it.
        """
        ...


class NullCalendarProvider(CalendarProvider):
    """No calendar connected: availability falls back to plain working hours; writes no-op."""
    name = "null"

    def busy(self, start: datetime, end: datetime) -> List[Interval]:
        return []

    def invites_attendees(self) -> bool:
        return False

    def create_event(self, *, summary, description, start, end, attendees, location="") -> str:
        return ""

    def update_event(self, event_id, *, start, end) -> None:
        return None

    def delete_event(self, event_id) -> None:
        return None


CALENDAR_PROVIDER_ENV = "CHORDENTIAL_CALENDAR_PROVIDER"


def get_calendar_provider() -> CalendarProvider:
    choice = (os.environ.get(CALENDAR_PROVIDER_ENV, "null") or "null").strip().lower()
    if choice == "google":
        from .google import GoogleCalendarProvider   # lazy — no import unless selected
        return GoogleCalendarProvider()
    return NullCalendarProvider()


def calendar_configured() -> bool:
    return (os.environ.get(CALENDAR_PROVIDER_ENV, "null") or "null").strip().lower() not in (
        "", "null", "0", "false", "off")
