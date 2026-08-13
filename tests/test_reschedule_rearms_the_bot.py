"""Rescheduling a call has to end with a bot at the NEW call — and buy nothing to do it.

The original fault: a capture bot is booked for a MOMENT. reschedule() moved the calendar
event, the record and the confirmations, and left the bot on the old time. The operator
rescheduled, joined, and sat in the call alone. It also reset the status in a way that
dropped the call out of the transcript poller.

The fix is not "book a replacement immediately" — that pays for a bot every time a call
moves, and a call booked days out gets an ad-hoc bot that idles in an empty room. It is:
release the old bot, and let the arming window buy exactly one, shortly before the call.
So these tests follow the whole path — reschedule, then the window comes round, then a
bot is there — because that is the thing the operator actually needs to be true.
"""
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")


def _iso(dt):
    return dt.isoformat()


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "r.sqlite"))
    monkeypatch.delenv("CHORDENTIAL_NOTETAKER_ARM_LEAD_MIN", raising=False)
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    c = db_mod.connect()
    db_mod.init_db(c)
    yield c
    c.close()


class _Capture:
    name = "fake"

    def __init__(self):
        self.invited, self.cancelled = [], []

    def invite(self, *, join_url, meeting_ref, join_at=""):
        self.invited.append(join_at)
        return "bot-%d" % (len(self.invited) + 1)

    def cancel(self, external_ref):
        self.cancelled.append(external_ref)


@pytest.fixture()
def cap(monkeypatch):
    from chordential_oia import meetings as M
    c = _Capture()
    monkeypatch.setattr(M, "capture_configured", lambda: True)
    monkeypatch.setattr(M, "get_capture_provider", lambda: c)
    return c


def _booked(db, conn, *, start_at, bot_id="bot-1"):
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Anthem", description=""))
    mid = db.create_meeting(
        conn, opp_id=opp_id, ci_id=None, start_at=start_at,
        join_url="https://zoom.example/j/1", external_meeting_id="z1", duration_min=30,
        provider="zoom", notetaker_provider="fake", bot_id=bot_id,
        status="bot_invited", meeting_type="zoom",
        bot_armed_at=_iso(datetime.now(timezone.utc)))
    return opp_id, mid


def test_reschedule_then_the_bot_turns_up_at_the_new_time(conn, cap):
    """The operator's actual complaint, end to end."""
    from chordential_oia.web import db, meeting_scheduler
    _opp, mid = _booked(db, conn,
                        start_at=_iso(datetime.now(timezone.utc) + timedelta(hours=3)))

    new_start = _iso(datetime.now(timezone.utc) + timedelta(minutes=12))
    meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid), new_start)
    assert cap.invited == [], "moving the call must not buy anything"

    meeting_scheduler.arm_due_meetings(conn)          # the window comes round
    m = db.get_meeting(conn, mid)
    assert cap.invited == [new_start], "one bot, booked for the NEW time"
    assert m["bot_id"] and m["bot_id"] != "bot-1", "and it is a new bot, not the spent one"
    assert m["status"] == "bot_invited"


def test_the_old_bot_is_released_at_once(conn, cap):
    """It was booked for the old slot; left alone it turns up and records an empty room."""
    from chordential_oia.web import db, meeting_scheduler
    _opp, mid = _booked(db, conn, bot_id="bot-old",
                        start_at=_iso(datetime.now(timezone.utc) + timedelta(hours=3)))

    meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid),
                                 _iso(datetime.now(timezone.utc) + timedelta(days=1)))
    assert cap.cancelled == ["bot-old"]
    assert not (db.get_meeting(conn, mid)["bot_id"] or "")


def test_moving_a_call_repeatedly_still_buys_one_bot(conn, cap):
    """Reschedule three times, then let the window run: one bot, for the final time."""
    from chordential_oia.web import db, meeting_scheduler
    _opp, mid = _booked(db, conn,
                        start_at=_iso(datetime.now(timezone.utc) + timedelta(days=1)))
    for days in (2, 3):
        meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid),
                                     _iso(datetime.now(timezone.utc) + timedelta(days=days)))
    final = _iso(datetime.now(timezone.utc) + timedelta(minutes=12))
    meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid), final)
    meeting_scheduler.arm_due_meetings(conn)

    assert cap.invited == [final], "exactly one bot, for the time it settled on"


def test_a_call_with_no_notetaker_is_left_that_way(conn, cap):
    """Rescheduling must not quietly add recording to a call that never had it."""
    from chordential_oia.web import db, meeting_scheduler
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Anthem", description=""))
    mid = db.create_meeting(
        conn, opp_id=opp_id, ci_id=None,
        start_at=_iso(datetime.now(timezone.utc) + timedelta(hours=3)),
        join_url="", external_meeting_id="", duration_min=30, provider="manual",
        notetaker_provider="", bot_id="", status="scheduled", meeting_type="phone")

    meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid),
                                 _iso(datetime.now(timezone.utc) + timedelta(minutes=12)))
    meeting_scheduler.arm_due_meetings(conn)
    assert not cap.invited, "a phone call with no link gets no bot"


def test_the_call_still_moves_when_releasing_the_bot_fails(conn, monkeypatch):
    """A provider that will not take the cancellation must not block the reschedule."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meeting_scheduler

    class _Broken(_Capture):
        def cancel(self, external_ref):
            raise RuntimeError("recall down")

    monkeypatch.setattr(M, "capture_configured", lambda: True)
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Broken())
    _opp, mid = _booked(db, conn,
                        start_at=_iso(datetime.now(timezone.utc) + timedelta(hours=3)))

    new_start = _iso(datetime.now(timezone.utc) + timedelta(days=1))
    out = meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid), new_start)
    assert out["ok"] and db.get_meeting(conn, mid)["start_at"] == new_start
