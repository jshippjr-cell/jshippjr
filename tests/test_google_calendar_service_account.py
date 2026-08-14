"""Service-account auth for the Google Calendar provider — the durable fix for auto-booking
that kept dying when an OAuth "Testing"-mode refresh token expired after 7 days.

A service account never expires. It can't invite guests on a consumer calendar (no domain-wide
delegation), so we drop the block on the operator's calendar only and leave the client's invite
to our own .ics email. These tests cover key loading (raw + base64), auth-mode selection, and the
attendee/sendUpdates behavior — all without any network.
"""
import base64
import json

import pytest

from chordential_oia.meetings import google as g


def _fake_key():
    return {"type": "service_account", "client_email": "cal@proj.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token", "project_id": "proj"}


# `_load_service_account` returns (info, problem): a key that is SET BUT UNREADABLE is not
# the same state as no key, and collapsing them onto None is what let a broken key fall
# back to the retired OAuth token (see test_a_broken_key_does_not_become_the_old_one.py).
def test_loads_raw_json_key(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(_fake_key()))
    info, problem = g._load_service_account()
    assert not problem
    assert info and info["client_email"] == "cal@proj.iam.gserviceaccount.com"


def test_loads_base64_wrapped_key(monkeypatch):
    raw = base64.b64encode(json.dumps(_fake_key()).encode()).decode()
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", raw)
    info, problem = g._load_service_account()
    assert not problem
    assert info and info["type"] == "service_account"


def test_no_key_is_none_and_is_not_reported_as_a_problem(monkeypatch):
    """Absent is a legitimate choice — only SET-AND-BROKEN is a problem."""
    monkeypatch.delenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    assert g._load_service_account() == (None, "")


def test_service_account_counts_as_configured(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(_fake_key()))
    # no client id/secret/refresh token at all
    for k in ("CHORDENTIAL_GOOGLE_CLIENT_ID", "CHORDENTIAL_GOOGLE_CLIENT_SECRET",
              "CHORDENTIAL_GOOGLE_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    p = g.GoogleCalendarProvider()
    assert p.configured() and p._use_sa()


def test_refresh_token_still_works_without_service_account(monkeypatch):
    monkeypatch.delenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_REFRESH_TOKEN", "rt")
    p = g.GoogleCalendarProvider()
    assert p.configured() and not p._use_sa()


def test_service_account_create_event_omits_guests_and_sends_none(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(_fake_key()))
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_CALENDAR_ID", "jon@chordential.com")
    p = g.GoogleCalendarProvider()
    seen = {}
    monkeypatch.setattr(p, "_post", lambda url, body: seen.update(url=url, body=body) or {"id": "evt1"})
    eid = p.create_event(
        summary="Discovery call", description="d",
        start=datetime(2026, 7, 12, 18, tzinfo=timezone.utc),
        end=datetime(2026, 7, 12, 18, 30, tzinfo=timezone.utc),
        attendees=["client@aurora.com"], location="https://zoom.us/j/1")
    assert eid == "evt1"
    # the block lands on the operator's calendar, no guest invited (no DWD), no email storm
    assert "sendUpdates=none" in seen["url"]
    assert "jon%40chordential.com" in seen["url"]   # url-encoded calendar id
    assert "attendees" not in seen["body"]


def test_refresh_token_create_event_still_invites_the_guest(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.delenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_REFRESH_TOKEN", "rt")
    p = g.GoogleCalendarProvider()
    seen = {}
    monkeypatch.setattr(p, "_post", lambda url, body: seen.update(url=url, body=body) or {"id": "e2"})
    p.create_event(summary="s", description="d",
                   start=datetime(2026, 7, 12, 18, tzinfo=timezone.utc),
                   end=datetime(2026, 7, 12, 18, 30, tzinfo=timezone.utc),
                   attendees=["client@aurora.com"], location="")
    assert "sendUpdates=all" in seen["url"]
    assert seen["body"]["attendees"] == [{"email": "client@aurora.com"}]
