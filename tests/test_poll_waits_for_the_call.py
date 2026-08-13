"""The transcript never came back because the poller gave up before the call happened.

A meeting is `bot_invited` from the moment it is BOOKED. The poller keyed off status
alone and never looked at `start_at`, so it began asking Recall for the transcript of a
call scheduled for next week — immediately — and every one of those polls spent a slice
of the give-up budget. Twenty-four attempts is about 8.6 hours, so any call booked more
than a day out was marked `failed`, and never asked again, BEFORE ANYONE JOINED IT.

Live evidence: a call scheduled for 2pm today already read "tried 12x" hours beforehand.

So: no polling, and no attempt spent, until the call is actually over.
"""
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")


def _iso(dt):
    return dt.isoformat()


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "m.sqlite"))
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    c = db_mod.connect()
    db_mod.init_db(c)
    yield c
    c.close()


def _booked(db, conn, *, start_at, duration_min=30, attempts=0):
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Anthem", description=""))
    mid = db.create_meeting(
        conn, opp_id=opp_id, ci_id=None, start_at=start_at,
        join_url="https://zoom.example/j/1", external_meeting_id="z1",
        duration_min=duration_min, provider="zoom", notetaker_provider="recall",
        bot_id="bot-1", status="bot_invited", meeting_type="zoom")
    if attempts:
        db.update_meeting(conn, mid, poll_attempts=attempts)
    return mid


class _Provider:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def fetch_transcript(self, bot_id):
        self.calls += 1
        return None


def test_a_call_that_has_not_happened_yet_is_not_polled(conn, monkeypatch):
    """The bug itself: a meeting booked for next week was asked about immediately."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    p = _Provider()
    monkeypatch.setattr(M, "get_capture_provider", lambda: p)
    _booked(db, conn, start_at=_iso(datetime.now(timezone.utc) + timedelta(days=7)))

    meetings_service.poll_and_ingest(conn)
    assert p.calls == 0, "there is no recording of a call that has not happened"


def test_no_attempt_is_spent_before_the_call(conn, monkeypatch):
    """The damage wasn't the wasted API call — it was the give-up budget draining."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Provider())
    mid = _booked(db, conn, start_at=_iso(datetime.now(timezone.utc) + timedelta(days=7)))

    for _ in range(30):                      # far past _POLL_MAX_ATTEMPTS
        meetings_service.poll_and_ingest(conn)

    m = db.get_meeting(conn, mid)
    assert (m["poll_attempts"] or 0) == 0
    assert m["status"] == "bot_invited", "it must not be written off before the call"


def test_attempts_accrued_before_the_call_are_given_back(conn, monkeypatch):
    """Repairs the rows already in this state — the one reading 'tried 12x'."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Provider())
    mid = _booked(db, conn, start_at=_iso(datetime.now(timezone.utc) + timedelta(hours=6)),
                  attempts=12)

    meetings_service.poll_and_ingest(conn)
    assert (db.get_meeting(conn, mid)["poll_attempts"] or 0) == 0


def test_once_the_call_is_over_it_is_polled_normally(conn, monkeypatch):
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    p = _Provider()
    monkeypatch.setattr(M, "get_capture_provider", lambda: p)
    mid = _booked(db, conn, duration_min=30,
                  start_at=_iso(datetime.now(timezone.utc) - timedelta(hours=2)))

    meetings_service.poll_and_ingest(conn)
    assert p.calls == 1, "a finished call must be asked about"
    assert (db.get_meeting(conn, mid)["poll_attempts"] or 0) == 1


def test_a_call_still_in_progress_is_left_alone(conn, monkeypatch):
    """Started ten minutes ago, booked for thirty — the transcript cannot exist yet."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    p = _Provider()
    monkeypatch.setattr(M, "get_capture_provider", lambda: p)
    _booked(db, conn, duration_min=30,
            start_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=10)))

    meetings_service.poll_and_ingest(conn)
    assert p.calls == 0


def test_a_meeting_with_no_start_time_is_still_polled(conn, monkeypatch):
    """An ad-hoc capture has nothing to wait for; refusing to poll it would be the same
    bug pointing the other way."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    p = _Provider()
    monkeypatch.setattr(M, "get_capture_provider", lambda: p)
    _booked(db, conn, start_at="")

    meetings_service.poll_and_ingest(conn)
    assert p.calls == 1


def test_the_give_up_still_bites_after_the_call(conn, monkeypatch):
    """The backoff's purpose survives: a call that finished and produced nothing is
    eventually written off with a reason, rather than asked for ever."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Provider())
    mid = _booked(db, conn, duration_min=30, attempts=meetings_service._POLL_MAX_ATTEMPTS - 1,
                  start_at=_iso(datetime.now(timezone.utc) - timedelta(days=1)))
    db.update_meeting(conn, mid, last_polled_at="")

    meetings_service.poll_and_ingest(conn)
    m = db.get_meeting(conn, mid)
    assert m["status"] == "failed" and "No transcript" in (m["error"] or "")
