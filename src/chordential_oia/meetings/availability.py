"""Availability engine (ADR-0016) — pure, deterministic slot computation.

Turns the operator's working hours + their calendar's busy intervals into a list of bookable
slots, and answers "is this exact slot still free?" at reserve time (the server-side double-book
guard). No I/O, no provider knowledge — the Meeting Scheduler feeds it busy times from whatever
CalendarProvider is configured. Fully testable with a fixed ``now``.

Timezone: a fixed UTC offset (``CHORDENTIAL_BOOKING_TZ_OFFSET_MIN``) keeps this dependency-free
and deterministic. It does not itself handle DST — set the offset for your current season, or
wire a zoneinfo-backed provider later; the engine's contract does not change.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

Interval = Tuple[datetime, datetime]   # (start, end), timezone-aware (UTC)


@dataclass
class WorkingHours:
    tz_offset_min: int = 0          # minutes east of UTC (e.g. New York EDT = -240)
    days: frozenset = frozenset({0, 1, 2, 3, 4})   # weekdays bookable (Mon=0 … Sun=6)
    start_hour: float = 9.0         # local day start (24h, fractional ok: 9.5 = 09:30)
    end_hour: float = 17.0          # local day end
    slot_min: int = 30              # meeting length / slot granularity
    buffer_min: int = 0             # padding kept free around existing events
    min_notice_min: int = 120       # earliest bookable, from now
    horizon_days: int = 14          # how far ahead to offer

    @classmethod
    def from_env(cls) -> "WorkingHours":
        def _int(name, d):
            try:
                return int(os.environ.get(name, "").strip() or d)
            except ValueError:
                return d

        def _float(name, d):
            try:
                return float(os.environ.get(name, "").strip() or d)
            except ValueError:
                return d
        days_raw = (os.environ.get("CHORDENTIAL_BOOKING_DAYS", "") or "0,1,2,3,4").strip()
        try:
            days = frozenset(int(x) for x in days_raw.split(",") if x.strip() != "")
        except ValueError:
            days = frozenset({0, 1, 2, 3, 4})
        return cls(
            tz_offset_min=_int("CHORDENTIAL_BOOKING_TZ_OFFSET_MIN", 0),
            days=days or frozenset({0, 1, 2, 3, 4}),
            start_hour=_float("CHORDENTIAL_BOOKING_START_HOUR", 9.0),
            end_hour=_float("CHORDENTIAL_BOOKING_END_HOUR", 17.0),
            slot_min=_int("CHORDENTIAL_BOOKING_SLOT_MIN", 30),
            buffer_min=_int("CHORDENTIAL_BOOKING_BUFFER_MIN", 0),
            min_notice_min=_int("CHORDENTIAL_BOOKING_MIN_NOTICE_MIN", 120),
            horizon_days=_int("CHORDENTIAL_BOOKING_HORIZON_DAYS", 14),
        )


@dataclass
class Slot:
    start: datetime      # aware UTC
    end: datetime

    def iso(self) -> str:
        return self.start.isoformat()


def _overlaps(a: Interval, b: Interval) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _expand(busy: Sequence[Interval], buffer_min: int) -> List[Interval]:
    if not buffer_min:
        return list(busy)
    pad = timedelta(minutes=buffer_min)
    return [(s - pad, e + pad) for s, e in busy]


def free_slots(now: datetime, working: WorkingHours,
               busy: Sequence[Interval]) -> List[Slot]:
    """Every bookable slot from ``now`` to the horizon: within working hours, not overlapping a
    (buffer-padded) busy interval, and no sooner than the minimum notice. Deterministic in
    ``now``. ``now`` and ``busy`` must be timezone-aware UTC."""
    now = _as_utc(now)
    padded = _expand(busy, working.buffer_min)
    earliest = now + timedelta(minutes=working.min_notice_min)
    tz = timezone(timedelta(minutes=working.tz_offset_min))
    slot = timedelta(minutes=working.slot_min)
    out: List[Slot] = []
    start_day = now.astimezone(tz).date()
    for d in range(working.horizon_days + 1):
        day = start_day + timedelta(days=d)
        if day.weekday() not in working.days:
            continue
        # step local start_hour → end_hour in slot_min increments
        minute = int(round(working.start_hour * 60))
        end_minute = int(round(working.end_hour * 60))
        while minute + working.slot_min <= end_minute:
            local = datetime(day.year, day.month, day.day,
                             minute // 60, minute % 60, tzinfo=tz)
            s = local.astimezone(timezone.utc)
            e = s + slot
            minute += working.slot_min
            if s < earliest:
                continue
            if any(_overlaps((s, e), b) for b in padded):
                continue
            out.append(Slot(start=s, end=e))
    return out


def slot_is_free(start: datetime, working: WorkingHours, busy: Sequence[Interval],
                 now: Optional[datetime] = None) -> bool:
    """The reserve-time guard: is exactly this start still bookable? Re-checked against live busy
    at booking (not just the UI list), so two people can't grab the same slot."""
    start = _as_utc(start)
    end = start + timedelta(minutes=working.slot_min)
    if now is not None and start < _as_utc(now) + timedelta(minutes=working.min_notice_min):
        return False
    tz = timezone(timedelta(minutes=working.tz_offset_min))
    local = start.astimezone(tz)
    if local.weekday() not in working.days:
        return False
    local_min = local.hour * 60 + local.minute
    if local_min < int(round(working.start_hour * 60)):
        return False
    if local_min + working.slot_min > int(round(working.end_hour * 60)):
        return False
    for b in _expand(busy, working.buffer_min):
        if _overlaps((start, end), b):
            return False
    return True


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO slot string back to an aware UTC datetime (None if unparseable)."""
    try:
        dt = datetime.fromisoformat((value or "").strip())
    except (ValueError, TypeError):
        return None
    return _as_utc(dt)
