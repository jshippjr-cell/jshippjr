"""Availability engine (ADR-0016) — deterministic slot computation + the reserve-time guard."""
from datetime import datetime, timezone

from chordential_oia.meetings.availability import WorkingHours, free_slots, slot_is_free

_NOW = datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc)   # a Friday, 08:00 UTC
_WH = WorkingHours(tz_offset_min=0, days=frozenset({0, 1, 2, 3, 4}), start_hour=9, end_hour=11,
                   slot_min=30, buffer_min=0, min_notice_min=0, horizon_days=0)


def test_free_slots_within_working_hours():
    got = [s.start.strftime("%H:%M") for s in free_slots(_NOW, _WH, [])]
    assert got == ["09:00", "09:30", "10:00", "10:30"]


def test_busy_intervals_remove_overlapping_slots():
    busy = [(datetime(2026, 7, 3, 9, 30, tzinfo=timezone.utc),
             datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc))]
    got = [s.start.strftime("%H:%M") for s in free_slots(_NOW, _WH, busy)]
    assert "09:30" not in got and "09:00" in got and "10:00" in got


def test_min_notice_and_buffer_and_weekends():
    wh = WorkingHours(start_hour=9, end_hour=11, slot_min=30, min_notice_min=120, horizon_days=0)
    got = [s.start.strftime("%H:%M") for s in free_slots(_NOW, wh, [])]
    assert got == ["10:00", "10:30"]                        # 08:00 + 120min notice → from 10:00
    # buffer pads busy on both sides
    whb = WorkingHours(start_hour=9, end_hour=11, slot_min=30, buffer_min=30, min_notice_min=0,
                       horizon_days=0)
    busy = [(datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
             datetime(2026, 7, 3, 10, 30, tzinfo=timezone.utc))]
    got2 = [s.start.strftime("%H:%M") for s in free_slots(_NOW, whb, busy)]
    assert "09:30" not in got2 and "10:00" not in got2 and "10:30" not in got2  # padded out


def test_slot_is_free_guard():
    busy = [(datetime(2026, 7, 3, 9, 30, tzinfo=timezone.utc),
             datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc))]
    assert slot_is_free(datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc), _WH, [])
    assert not slot_is_free(datetime(2026, 7, 3, 9, 30, tzinfo=timezone.utc), _WH, busy)  # taken
    assert not slot_is_free(datetime(2026, 7, 4, 10, 0, tzinfo=timezone.utc), _WH, [])  # Saturday
    assert not slot_is_free(datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc), _WH, [])   # pre-hours
