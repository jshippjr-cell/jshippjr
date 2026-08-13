"""The transcript poller had no end.

`poll_and_ingest` asked the capture provider about every un-ingested bot on every base
tick — about 30 seconds — for as long as the row existed. A bot that reaches `done` and
produces no transcript (a call with no audio, a bot removed from the room, a provider
that simply never renders one) returns None every time, so the meeting was asked again
**~2,880 times a day, for ever**, logging a WARNING on each pass.

The API calls are not the real cost. The real cost is that **a failed capture was
invisible**: the discovery call's notes never arrived, the meeting sat in
`transcript_ready` looking like it was still working, and nothing told anyone the
recording was not coming. The operator found out by going to read notes that did not
exist.

So the poller backs off, and it eventually stops — writing a real terminal state with
the reason in it. Giving up decides nothing about the campaign; it records that the
machine could not get the transcript, which is the operator's cue to add the notes by
hand ("the machine proposes, Jon disposes").
"""

import importlib
from datetime import datetime, timedelta, timezone

import pytest

from chordential_oia import meetings as M
from chordential_oia.web import db as db_mod
from chordential_oia.web import meetings_service as svc


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "m.db"))
    importlib.reload(db_mod)
    importlib.reload(svc)
    c = db_mod.connect()
    db_mod.init_db(c)
    yield c
    c.close()


class _NeverReady:
    """A bot that finished and produced nothing — the exact case that span for ever."""
    calls = 0

    def fetch_transcript(self, bot_id):
        _NeverReady.calls += 1
        return None


def _meeting(conn, status=None):
    # The call is OVER. Polling only begins once it has finished (see `_call_over`):
    # counting attempts from the booking is what marked every call failed before anyone
    # joined it. A backoff test has to start where a real poll starts.
    ended = datetime.now(timezone.utc) - timedelta(hours=2)
    conn.execute(
        "INSERT INTO meetings (opp_id, provider, bot_id, status, start_at, duration_min) "
        "VALUES (?,?,?,?,?,?)",
        (1, "zoom", "bot-abc", status or M.TRANSCRIPT_READY, ended.isoformat(), 30))
    conn.commit()
    return conn.execute("SELECT * FROM meetings ORDER BY id DESC LIMIT 1").fetchone()


def _age_last_poll(conn, mid, seconds):
    when = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    conn.execute("UPDATE meetings SET last_polled_at = ? WHERE id = ?", (when, mid))
    conn.commit()


# --------------------------------------------------------------------------- #
# The bookkeeping has to actually be written
# --------------------------------------------------------------------------- #
def test_update_meeting_refuses_a_field_it_cannot_write(conn):
    """The trap this fix walked into. `poll_attempts` was not on `update_meeting`'s
    allowlist, so the backoff wrote nothing, every meeting stayed on attempt 0, and the
    whole change would have shipped looking correct while doing nothing. Silence on an
    unknown field is how that happens; now it raises."""
    m = _meeting(conn)
    with pytest.raises(ValueError):
        db_mod.update_meeting(conn, m["id"], no_such_column="x")


def test_the_attempt_counter_survives_the_write(conn):
    m = _meeting(conn)
    db_mod.update_meeting(conn, m["id"], poll_attempts=3,
                          last_polled_at="2026-08-06T00:00:00+00:00")
    row = conn.execute("SELECT * FROM meetings WHERE id = ?", (m["id"],)).fetchone()
    assert row["poll_attempts"] == 3
    assert row["last_polled_at"].startswith("2026-08-06")


# --------------------------------------------------------------------------- #
# Backoff
# --------------------------------------------------------------------------- #
def test_a_never_ready_bot_is_not_asked_every_tick(conn, monkeypatch):
    """The bug, stated as a number. Ten consecutive scheduler ticks used to mean ten
    provider calls; now the schedule decides, and after the first the meeting is not
    due again for a while."""
    monkeypatch.setattr(M, "get_capture_provider", lambda: _NeverReady())
    _NeverReady.calls = 0
    _meeting(conn)
    for _ in range(10):                       # ten ticks, back to back
        svc.poll_and_ingest(conn)
    assert _NeverReady.calls == 1, (
        f"asked the provider {_NeverReady.calls} times across ten ticks")


def test_it_is_asked_again_once_the_delay_has_passed(conn, monkeypatch):
    """The control. A poller that backs off to infinity on the first miss would pass
    the test above and never collect a transcript that arrives two minutes late."""
    monkeypatch.setattr(M, "get_capture_provider", lambda: _NeverReady())
    _NeverReady.calls = 0
    m = _meeting(conn)
    svc.poll_and_ingest(conn)
    assert _NeverReady.calls == 1
    _age_last_poll(conn, m["id"], 3600)       # an hour later
    svc.poll_and_ingest(conn)
    assert _NeverReady.calls == 2


def test_the_delay_grows(conn):
    """Dense early — a transcript usually lands within minutes of a call ending — then
    decaying, so a dead bot costs a couple of calls an hour rather than 120."""
    delays = [svc._poll_delay(n) for n in range(0, 12)]
    assert delays[0] == 0, "the first poll must be immediate"
    assert delays == sorted(delays), f"the backoff is not monotonic: {delays}"
    assert delays[-1] >= 1800, "it must decay to a genuinely slow cadence"


# --------------------------------------------------------------------------- #
# Giving up, out loud
# --------------------------------------------------------------------------- #
def test_it_eventually_stops_and_says_why(conn, monkeypatch):
    """A meeting parked in `transcript_ready` for ever looks like it is still working.
    The terminal state is the one that tells the truth."""
    monkeypatch.setattr(M, "get_capture_provider", lambda: _NeverReady())
    m = _meeting(conn)
    for _ in range(svc._POLL_MAX_ATTEMPTS + 2):
        _age_last_poll(conn, m["id"], 7200)   # always due
        svc.poll_and_ingest(conn)
    row = conn.execute("SELECT * FROM meetings WHERE id = ?", (m["id"],)).fetchone()
    assert row["status"] == M.FAILED
    assert "no transcript" in (row["error"] or "").lower()
    assert "by hand" in (row["error"] or "").lower(), (
        "the operator is not told what to do about it")


def test_once_it_has_given_up_it_stops_calling(conn, monkeypatch):
    """The point of stopping. A failed meeting is no longer in a polled status, so the
    provider is not asked about it again."""
    monkeypatch.setattr(M, "get_capture_provider", lambda: _NeverReady())
    m = _meeting(conn)
    for _ in range(svc._POLL_MAX_ATTEMPTS + 1):
        _age_last_poll(conn, m["id"], 7200)
        svc.poll_and_ingest(conn)
    _NeverReady.calls = 0
    for _ in range(5):
        _age_last_poll(conn, m["id"], 7200)
        svc.poll_and_ingest(conn)
    assert _NeverReady.calls == 0


def test_a_transcript_that_arrives_is_still_ingested(conn, monkeypatch):
    """The control that matters most: none of this may cost us a transcript that DOES
    turn up. A backoff that swallowed a good one would be a worse bug than the one it
    replaces."""
    class Ready:
        def fetch_transcript(self, bot_id):
            return M.Transcript(text="We need a warm :60 anthem.", speakers=["Priya"],
                                external_ref=bot_id)
    ingested = {}
    monkeypatch.setattr(M, "get_capture_provider", lambda: Ready())
    monkeypatch.setattr(svc.campaign_intake, "ingest_transcript",
                        lambda c, m, t: ingested.setdefault("t", t))
    _meeting(conn)
    assert svc.poll_and_ingest(conn) == 1
    assert "warm :60 anthem" in ingested["t"].text


def test_a_provider_that_throws_still_counts_as_an_attempt(conn, monkeypatch):
    """Otherwise a provider erroring every time is the forever-loop again, wearing a
    different hat — the old code `continue`d before any bookkeeping."""
    class Boom:
        def fetch_transcript(self, bot_id):
            raise RuntimeError("provider down")
    monkeypatch.setattr(M, "get_capture_provider", lambda: Boom())
    m = _meeting(conn)
    svc.poll_and_ingest(conn)
    row = conn.execute("SELECT * FROM meetings WHERE id = ?", (m["id"],)).fetchone()
    assert row["poll_attempts"] == 1


def test_the_operator_is_not_told_pending_for_ever(conn):
    """The chip the operator actually reads. While the poller had no end, the meeting
    tile said "◐ Transcript pending" indefinitely — so the failure looked like patience.
    A terminal state nobody can see is just a quieter kind of invisible."""
    from pathlib import Path
    import chordential_oia.web.app as app_mod
    html = (Path(app_mod.__file__).parent / "templates" / "detail.html"
            ).read_text(encoding="utf-8")
    assert "meeting['status'] == 'failed'" in html, (
        "the tile cannot distinguish a capture still working from one that gave up")
    block = html.split("Transcript ready")[1].split("</div>")[0]
    assert block.index("failed") < block.index("Transcript pending"), (
        "'pending' is checked first, so a failed capture still reads as pending")
    assert "add the notes by hand" in html
