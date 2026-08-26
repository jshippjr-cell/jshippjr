"""A capture bot is bought as late as possible, so nothing is paid for a call that
doesn't happen.

The bot used to be booked the instant the CALL was booked, with no join_at. Recall calls
that an ad-hoc bot: it goes straight in, joins an empty room, and BILLS while it waits.
So every call booked in advance paid for a bot that recorded nothing and was spent by the
time the meeting came round — and rescheduling or cancelling bought another.

Booking it shortly before the call instead makes all of that free:
  • a call cancelled or moved before the window costs nothing — no bot ever existed;
  • the calls already in the book, pointing at spent ad-hoc bots, repair themselves as
    their window arrives, with no bulk spend and no sweep;
  • exactly one bot per call that actually happens.
"""
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")


def _iso(dt):
    return dt.isoformat()


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "a.sqlite"))
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

    def invite(self, *, join_url, meeting_ref, join_at="", realtime_url=""):
        self.invited.append(join_at)
        return "bot-new-%d" % len(self.invited)

    def cancel(self, external_ref):
        self.cancelled.append(external_ref)


@pytest.fixture()
def cap(monkeypatch):
    from chordential_oia import meetings as M
    c = _Capture()
    monkeypatch.setattr(M, "capture_configured", lambda: True)
    monkeypatch.setattr(M, "get_capture_provider", lambda: c)
    return c


def _meeting(db, conn, *, start_at, bot_id="", armed_at="", status="scheduled"):
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Anthem", description=""))
    mid = db.create_meeting(
        conn, opp_id=opp_id, ci_id=None, start_at=start_at,
        join_url="https://zoom.example/j/1", external_meeting_id="z1", duration_min=30,
        provider="zoom", notetaker_provider="", bot_id=bot_id, status=status,
        meeting_type="zoom")
    if armed_at:
        db.update_meeting(conn, mid, bot_armed_at=armed_at)
    return opp_id, mid


def test_a_call_next_week_buys_nothing_today(conn, cap):
    """The money leak: a bot dispatched at booking joins an empty room and bills."""
    from chordential_oia.web import db, meeting_scheduler
    _meeting(db, conn, start_at=_iso(datetime.now(timezone.utc) + timedelta(days=7)))
    assert meeting_scheduler.arm_due_meetings(conn) == 0
    assert cap.invited == [], "no bot may be bought for a call that is a week away"


def test_the_bot_is_bought_when_the_call_comes_round(conn, cap):
    from chordential_oia.web import db, meeting_scheduler
    start = _iso(datetime.now(timezone.utc) + timedelta(minutes=12))
    _opp, mid = _meeting(db, conn, start_at=start)

    assert meeting_scheduler.arm_due_meetings(conn) == 1
    assert cap.invited == [start], "and told exactly when to join, so it does not idle"
    m = db.get_meeting(conn, mid)
    assert m["bot_id"] == "bot-new-1"
    assert m["status"] == "bot_invited", "and it goes back into the poller's sights"
    assert (m["bot_armed_at"] or ""), "the arming moment is recorded"


def test_it_never_buys_twice_for_the_same_call(conn, cap):
    """A tick that runs twice must not buy two bots."""
    from chordential_oia.web import meeting_scheduler, db
    _meeting(db, conn, start_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=12)))
    meeting_scheduler.arm_due_meetings(conn)
    meeting_scheduler.arm_due_meetings(conn)
    assert len(cap.invited) == 1


def test_an_old_ad_hoc_bot_is_replaced_and_stood_down(conn, cap):
    """Every meeting already in the book points at one of these. They repair themselves
    as their window arrives — no sweep, no bulk spend."""
    from chordential_oia.web import db, meeting_scheduler
    _opp, mid = _meeting(db, conn, bot_id="bot-spent", armed_at="",
                         status="bot_invited",
                         start_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=12)))

    assert meeting_scheduler.arm_due_meetings(conn) == 1
    assert cap.cancelled == ["bot-spent"], "the spent bot must not keep a seat"
    assert db.get_meeting(conn, mid)["bot_id"] == "bot-new-1"


def test_a_bot_armed_properly_is_left_alone(conn, cap):
    from chordential_oia.web import db, meeting_scheduler
    _meeting(db, conn, bot_id="bot-good", armed_at=_iso(datetime.now(timezone.utc)),
             status="bot_invited",
             start_at=_iso(datetime.now(timezone.utc) + timedelta(minutes=12)))
    assert meeting_scheduler.arm_due_meetings(conn) == 0
    assert not cap.invited and not cap.cancelled


def test_rescheduling_buys_nothing(conn, cap):
    """Move a call as often as you like: the bot is bought once, near the call."""
    from chordential_oia.web import db, meeting_scheduler
    _opp, mid = _meeting(db, conn, bot_id="bot-old", status="bot_invited",
                         armed_at=_iso(datetime.now(timezone.utc)),
                         start_at=_iso(datetime.now(timezone.utc) + timedelta(hours=2)))

    meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid),
                                 _iso(datetime.now(timezone.utc) + timedelta(days=3)))
    assert cap.invited == [], "moving a call must not buy a bot"
    assert cap.cancelled == ["bot-old"], "and must release the one it had"
    m = db.get_meeting(conn, mid)
    assert not (m["bot_id"] or "") and m["status"] == "scheduled"


def test_a_call_already_inside_the_window_is_armed_at_booking(conn, cap, monkeypatch):
    """Booking a call for ten minutes' time must still record it."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meeting_scheduler
    monkeypatch.setattr(M, "meeting_configured", lambda: True)
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Anthem", description=""))
    start = _iso(datetime.now(timezone.utc) + timedelta(minutes=5))

    meeting_scheduler.schedule(conn, db.get_opportunity(conn, opp_id), start_at=start,
                               duration_min=30, meeting_type="zoom",
                               join_url="https://zoom.example/j/9")
    assert cap.invited == [start]


def test_a_call_booked_far_out_is_not_armed_at_booking(conn, cap, monkeypatch):
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meeting_scheduler
    monkeypatch.setattr(M, "meeting_configured", lambda: True)
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Anthem", description=""))

    meeting_scheduler.schedule(
        conn, db.get_opportunity(conn, opp_id),
        start_at=_iso(datetime.now(timezone.utc) + timedelta(days=2)),
        duration_min=30, meeting_type="zoom", join_url="https://zoom.example/j/9")
    assert cap.invited == [], "nothing is bought until the call is close"


def test_the_lead_must_clear_recalls_ad_hoc_threshold(monkeypatch):
    """Under 10 minutes Recall treats the bot as ad-hoc and sends it in immediately —
    which is the idling-in-an-empty-room behaviour this whole change exists to stop."""
    from chordential_oia.web import meeting_scheduler
    monkeypatch.setenv("CHORDENTIAL_NOTETAKER_ARM_LEAD_MIN", "2")
    assert meeting_scheduler._arm_lead_minutes() >= 11
