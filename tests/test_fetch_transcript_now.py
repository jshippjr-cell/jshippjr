"""A recorded call's notes must never be hostage to a background loop.

Until `fetch_now`, the ONLY route from a capture bot to Campaign Intelligence was the
scheduler's poller: invisible to the operator, impossible to check, and after
`_POLL_MAX_ATTEMPTS` (~8 hours) it wrote `failed` and never asked again. So a
transcript that landed late — or landed while the loop happened not to be running —
was gone, with no control anywhere in the product to reach for it.

These cover the hand crank: it asks now, it ingests when there is something to ingest,
and when there is not it puts the meeting back in the poller's sights instead of
leaving it written off.
"""
import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.sqlite"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c


class _Transcript:
    text = "Budget is around $40,000. We need it by March. Warm, acoustic, no vocal."
    external_ref = "bot-1"

    def metadata(self):
        return {"provider": "fake"}


class _Provider:
    """A capture provider whose answer we control, exactly as Recall's would arrive."""
    name = "fake"

    def __init__(self, answer=None, boom=False):
        self.answer, self.boom, self.calls = answer, boom, 0

    def fetch_transcript(self, bot_id):
        self.calls += 1
        if self.boom:
            raise RuntimeError("provider down")
        return self.answer


def _armed_meeting(db, conn):
    """A booked Zoom call with a capture bot armed — what the operator is looking at."""
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Campaign anthem", description=""))
    mid = db.create_meeting(
        conn, opp_id=opp_id, ci_id=None, start_at="2026-08-01T15:00:00+00:00",
        join_url="https://zoom.example/j/1", external_meeting_id="z1", duration_min=30,
        provider="zoom", notetaker_provider="fake", bot_id="bot-1",
        status="bot_invited", meeting_type="zoom")
    return opp_id, mid


def test_it_ingests_the_transcript_into_campaign_intelligence(client, monkeypatch):
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    monkeypatch.setenv("CHORDENTIAL_NOTETAKER_PROVIDER", "fake")
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Provider(_Transcript()))
    conn = db.connect()
    try:
        _opp, mid = _armed_meeting(db, conn)
        out = meetings_service.fetch_now(conn, mid)
        assert out["ok"] and out.get("ingested"), out
        assert out.get("capture_id"), "the transcript must land as a Capture"
        m = db.get_meeting(conn, mid)
        assert (m["transcript_capture_id"] or ""), "the meeting must record its capture"
    finally:
        conn.close()


def test_not_ready_is_not_a_failure_it_goes_back_on_watch(client, monkeypatch):
    """The case that loses notes: the poller gave up, the transcript arrives later."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    monkeypatch.setenv("CHORDENTIAL_NOTETAKER_PROVIDER", "fake")
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Provider(None))
    conn = db.connect()
    try:
        _opp, mid = _armed_meeting(db, conn)
        # the poller had written it off after ~8 hours
        db.update_meeting(conn, mid, status="failed", error="gave up", poll_attempts=24)

        out = meetings_service.fetch_now(conn, mid)
        assert out["ok"] and out.get("pending"), out
        m = db.get_meeting(conn, mid)
        assert m["status"] == "bot_invited", "a written-off call must be watched again"
        assert (m["poll_attempts"] or 0) == 0, "the give-up counter must reset"
        assert not (m["error"] or ""), "the stale failure message must be cleared"
    finally:
        conn.close()


def test_a_provider_error_is_reported_not_raised(client, monkeypatch):
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    monkeypatch.setenv("CHORDENTIAL_NOTETAKER_PROVIDER", "fake")
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Provider(boom=True))
    conn = db.connect()
    try:
        _opp, mid = _armed_meeting(db, conn)
        out = meetings_service.fetch_now(conn, mid)
        assert out["ok"] is False and "provider" in out["error"].lower()
    finally:
        conn.close()


def test_it_says_so_when_there_is_nothing_to_fetch(client, monkeypatch):
    """No bot armed means no recording exists — say that, don't imply a retry will help."""
    from chordential_oia import meetings as M
    from chordential_oia.web import db, meetings_service
    monkeypatch.setenv("CHORDENTIAL_NOTETAKER_PROVIDER", "fake")
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Provider(_Transcript()))
    conn = db.connect()
    try:
        from chordential_oia.models import Opportunity
        opp_id = db.insert_opportunity(conn, Opportunity(
            client="AURORA", need="Anthem", description=""))
        mid = db.create_meeting(conn, opp_id=opp_id, ci_id=None,
                                start_at="2026-08-01T15:00:00+00:00", join_url="",
                                external_meeting_id="", duration_min=30, provider="manual",
                                notetaker_provider="", bot_id="", status="scheduled",
                                meeting_type="zoom")
        out = meetings_service.fetch_now(conn, mid)
        assert out["ok"] is False and "no capture bot" in out["error"].lower()
    finally:
        conn.close()


def test_the_button_is_on_the_opportunity_while_a_transcript_is_outstanding(client):
    from chordential_oia.web import db
    conn = db.connect()
    try:
        opp_id, mid = _armed_meeting(db, conn)
    finally:
        conn.close()
    page = client.get(f"/opportunity/{opp_id}").text
    assert f"/discovery/{mid}/fetch-transcript" in page, "the operator needs a way to ask"
    assert "Fetch it now" in page


def test_the_route_answers_and_returns_to_the_call(client, monkeypatch):
    from chordential_oia import meetings as M
    from chordential_oia.web import db
    monkeypatch.setenv("CHORDENTIAL_NOTETAKER_PROVIDER", "fake")
    monkeypatch.setattr(M, "get_capture_provider", lambda: _Provider(_Transcript()))
    conn = db.connect()
    try:
        opp_id, mid = _armed_meeting(db, conn)
    finally:
        conn.close()
    r = client.post(f"/opportunity/{opp_id}/discovery/{mid}/fetch-transcript",
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/opportunity/{opp_id}?fetch=transcript#discovery"
