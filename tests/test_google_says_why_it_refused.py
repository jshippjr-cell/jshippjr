"""When Google refuses, report the reason Google gave.

Live, 2026-08-14, on the meeting card:

    ✕ Google refused the event — HTTPError: HTTP Error 400: Bad Request

Which names neither the problem nor the fix. `str(HTTPError)` is only the status line: the
reason is in the RESPONSE BODY, and urllib does not read it for you. The most likely cause
on the OAuth path says so explicitly in that body —

    {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}

— a refresh token minted while the Google app is in "Testing" publishing status, which
Google revokes after 7 days. That is the documented cause of "auto-booking worked for a
week and then stopped", and it was arriving as an unexplained 400.
"""
import io
import json
import urllib.error

import pytest


def _http_error(code: int, body: dict, url: str = "https://www.googleapis.com/calendar/v3/x"):
    raw = json.dumps(body).encode()
    return urllib.error.HTTPError(url, code, "Bad Request", {}, io.BytesIO(raw))


@pytest.fixture()
def provider(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_REFRESH_TOKEN", "rt")
    monkeypatch.delenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    from chordential_oia.meetings.google import GoogleCalendarProvider
    return GoogleCalendarProvider()


def test_an_expired_refresh_token_names_itself_and_names_the_fix(provider, monkeypatch):
    """THE one. It presented as a bare 400 for as long as it has been happening."""
    from chordential_oia.meetings import google as g

    def boom(req, timeout=None):
        raise _http_error(400, {"error": "invalid_grant",
                                "error_description": "Token has been expired or revoked."},
                          url=g._TOKEN_URL)
    monkeypatch.setattr(g.urllib.request, "urlopen", boom)

    with pytest.raises(g.GoogleCalendarError) as exc:
        provider.create_event(summary="s", description="d",
                              start=_dt(), end=_dt(), attendees=["a@b.c"])
    msg = str(exc.value)
    assert "invalid_grant" in msg
    assert "expired or revoked" in msg
    assert "Testing status" in msg and "service account" in msg, (
        "the reason is only useful if it carries what to do about it")


def test_a_calendar_api_refusal_carries_googles_own_message(provider, monkeypatch):
    from chordential_oia.meetings import google as g
    monkeypatch.setattr(provider, "_access_token", lambda: "tok")

    def boom(req, timeout=None):
        raise _http_error(400, {"error": {"code": 400, "message": "Invalid attendee email."}})
    monkeypatch.setattr(g.urllib.request, "urlopen", boom)

    with pytest.raises(g.GoogleCalendarError) as exc:
        provider.create_event(summary="s", description="d",
                              start=_dt(), end=_dt(), attendees=["not-an-email"])
    assert "Invalid attendee email." in str(exc.value)
    assert "400" in str(exc.value)


def test_an_unreadable_body_still_reports_the_status_rather_than_nothing(provider, monkeypatch):
    from chordential_oia.meetings import google as g
    monkeypatch.setattr(provider, "_access_token", lambda: "tok")

    class _Unreadable(urllib.error.HTTPError):
        def read(self, *a, **k):
            raise OSError("connection closed")

    def boom(req, timeout=None):
        raise _Unreadable("https://x", 503, "Service Unavailable", {}, io.BytesIO(b""))
    monkeypatch.setattr(g.urllib.request, "urlopen", boom)

    with pytest.raises(g.GoogleCalendarError) as exc:
        provider.create_event(summary="s", description="d",
                              start=_dt(), end=_dt(), attendees=[])
    assert "503" in str(exc.value)


def test_the_booking_survives_the_refusal_and_falls_back_to_the_emailed_invite(
        tmp_path, monkeypatch):
    """The half that keeps the product usable while the token is dead: no native event
    means the .ics is the only route to a calendar, so both sides must still get one."""
    import importlib
    from chordential_oia.models import Opportunity
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "g.db"))
    monkeypatch.setenv("CHORDENTIAL_CALENDAR_PROVIDER", "google")
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jshippjr@gmail.com")
    from chordential_oia.web import db as dbm
    dbm = importlib.reload(dbm)
    from chordential_oia.web import meeting_scheduler as ms
    ms = importlib.reload(ms)

    class _Dead:
        name = "google"

        def invites_attendees(self):
            return True

        def create_event(self, **kw):
            from chordential_oia.meetings.google import GoogleCalendarError
            raise GoogleCalendarError(
                "Google the token endpoint refused (400): invalid_grant: "
                "Token has been expired or revoked.")

    monkeypatch.setattr(ms.M, "get_calendar_provider", lambda: _Dead())
    conn = dbm.connect()
    dbm.init_db(conn)
    try:
        oid = dbm.insert_opportunity(conn, Opportunity(
            client="Champ Atlantic", need="Fall launch", description=""))
        res = ms.schedule(conn, dbm.get_opportunity(conn, oid), meeting_type="zoom",
                          start_at="2026-09-20T15:00:00+00:00", duration_min=30,
                          client_name="Dana", client_email="dana@champ.example",
                          join_url="https://zoom.example/j/1")
        assert res["ok"]
        log = dbm.confirmations(dbm.get_meeting(conn, res["meeting"]["id"]))
        cal = [e for e in log if e["role"] == "calendar"][0]
        assert "invalid_grant" in cal["detail"]
        assert all(e["invite"] for e in log if e["role"] != "calendar"), (
            "with Google refusing, the emailed invitation is the ONLY calendar route")
    finally:
        conn.close()


def _dt():
    from datetime import datetime, timezone
    return datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
