"""Rescheduling a call has to move the notetaker with it.

It didn't. A capture bot is booked for a MOMENT: the bot was scheduled against the old
time, and reschedule() updated the calendar, the record and the confirmations — but
nothing moved the bot. The operator rescheduled, joined the new call, and sat in it
alone. Which makes the reschedule button a lie: it moves everything the client sees and
none of what the machine needs.

The second half of the same bug was quieter. reschedule() reset the status to SCHEDULED,
and the poller only scans BOT_INVITED / IN_PROGRESS / TRANSCRIPT_READY — so a rescheduled
call was silently dropped from the only loop that ever fetches a transcript.
"""
import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "r.sqlite"))
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    c = db_mod.connect()
    db_mod.init_db(c)
    yield c
    c.close()


class _Capture:
    name = "fake"

    def __init__(self, new_id="bot-2"):
        self.new_id, self.invited, self.cancelled = new_id, [], []

    def invite(self, *, join_url, meeting_ref, join_at=""):
        self.invited.append({"join_url": join_url, "join_at": join_at})
        return self.new_id

    def cancel(self, external_ref):
        self.cancelled.append(external_ref)


def _booked(db, conn, *, bot_id="bot-1"):
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Anthem", description=""))
    mid = db.create_meeting(
        conn, opp_id=opp_id, ci_id=None, start_at="2026-08-20T15:00:00+00:00",
        join_url="https://zoom.example/j/1", external_meeting_id="z1", duration_min=30,
        provider="zoom", notetaker_provider="fake", bot_id=bot_id,
        status="bot_invited", meeting_type="zoom")
    return opp_id, mid


def test_a_new_bot_is_booked_for_the_new_time(conn, monkeypatch):
    """The bug the operator hit: rescheduled, joined, and no bot came."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meeting_scheduler
    cap = _Capture()
    monkeypatch.setenv("CHORDENTIAL_NOTETAKER_PROVIDER", "fake")
    monkeypatch.setattr(M, "capture_configured", lambda: True)
    monkeypatch.setattr(M, "get_capture_provider", lambda: cap)
    _opp, mid = _booked(db, conn)

    new_start = "2026-08-21T18:00:00+00:00"
    meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid), new_start)

    assert cap.invited, "a bot must be booked for the new time"
    assert cap.invited[0]["join_at"] == new_start, "and told WHEN the new call is"
    m = db.get_meeting(conn, mid)
    assert m["bot_id"] == "bot-2", "the meeting must carry the NEW bot"
    assert m["start_at"] == new_start


def test_the_old_bot_is_stood_down(conn, monkeypatch):
    """Otherwise it turns up to the original slot and records an empty room."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meeting_scheduler
    cap = _Capture()
    monkeypatch.setattr(M, "capture_configured", lambda: True)
    monkeypatch.setattr(M, "get_capture_provider", lambda: cap)
    _opp, mid = _booked(db, conn, bot_id="bot-1")

    meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid), "2026-08-21T18:00:00+00:00")
    assert cap.cancelled == ["bot-1"]


def test_the_call_stays_in_the_pollers_sights(conn, monkeypatch):
    """Resetting to SCHEDULED removed it from the only loop that fetches transcripts."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meeting_scheduler
    monkeypatch.setattr(M, "capture_configured", lambda: True)
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Capture())
    _opp, mid = _booked(db, conn)

    meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid), "2026-08-21T18:00:00+00:00")
    m = db.get_meeting(conn, mid)
    assert m["status"] == "bot_invited", "a rescheduled call must still be polled"
    assert (m["poll_attempts"] or 0) == 0, "the new call gets a fresh give-up budget"


def test_a_failure_to_re_arm_does_not_block_the_reschedule(conn, monkeypatch):
    """Moving the call matters more than recording it — but it must not silently claim a
    notetaker it does not have."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meeting_scheduler

    class _Broken(_Capture):
        def invite(self, **kw):
            raise RuntimeError("recall down")

    monkeypatch.setattr(M, "capture_configured", lambda: True)
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Broken())
    _opp, mid = _booked(db, conn)

    out = meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid),
                                       "2026-08-21T18:00:00+00:00")
    assert out["ok"]
    m = db.get_meeting(conn, mid)
    assert m["start_at"] == "2026-08-21T18:00:00+00:00", "the call still moves"
    assert not (m["notetaker_provider"] or ""), "and does not claim a notetaker it lost"


def test_a_call_with_no_notetaker_is_left_that_way(conn, monkeypatch):
    """Rescheduling must not quietly add recording to a call that never had it."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meeting_scheduler
    cap = _Capture()
    monkeypatch.setattr(M, "capture_configured", lambda: True)
    monkeypatch.setattr(M, "get_capture_provider", lambda: cap)
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Anthem", description=""))
    mid = db.create_meeting(
        conn, opp_id=opp_id, ci_id=None, start_at="2026-08-20T15:00:00+00:00",
        join_url="https://zoom.example/j/1", external_meeting_id="", duration_min=30,
        provider="zoom", notetaker_provider="", bot_id="", status="scheduled",
        meeting_type="zoom")

    meeting_scheduler.reschedule(conn, db.get_meeting(conn, mid), "2026-08-21T18:00:00+00:00")
    assert not cap.invited
    assert db.get_meeting(conn, mid)["status"] == "scheduled"


def test_booking_tells_recall_when_the_call_is(conn, monkeypatch):
    """Without join_at Recall treats the bot as ad-hoc and sends it in NOW — so a call
    booked for next week got a bot that joined an empty room today."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meeting_scheduler
    cap = _Capture(new_id="bot-9")
    monkeypatch.setattr(M, "capture_configured", lambda: True)
    monkeypatch.setattr(M, "get_capture_provider", lambda: cap)
    monkeypatch.setattr(M, "meeting_configured", lambda: True)
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Anthem", description=""))
    opp = db.get_opportunity(conn, opp_id)

    start = "2026-09-01T14:00:00+00:00"
    meeting_scheduler.schedule(conn, opp, start_at=start, duration_min=30,
                               meeting_type="zoom", join_url="https://zoom.example/j/5")
    assert cap.invited and cap.invited[0]["join_at"] == start
