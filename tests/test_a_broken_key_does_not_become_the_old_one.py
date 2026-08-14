"""A credential that is set and unusable is not the same as a credential that is absent.

The operator hit the 7-day OAuth expiry, and fixed it — they moved to a service account,
which is exactly what `docs/discovery-setup-guide.md` §3-SA recommends and exactly what
never expires. Weeks later the meeting card read:

    ✕ Google refused the event — HTTPError: HTTP Error 400: Bad Request

and the schedule page still said **"Google invites both calendars"** — the OAuth banner,
for an account that had moved off OAuth.

`_load_service_account` returned ``None`` for a key it could not parse, with the comment
"malformed key → treat as unconfigured, never crash". `configured()` then fell through to
the leftover CHORDENTIAL_GOOGLE_CLIENT_ID / _SECRET / _REFRESH_TOKEN and quietly resumed
using the retired, expired token. A fixed problem un-fixed itself because a typo in one
env var was indistinguishable from a decision not to use that env var at all.

So: a broken service-account key does NOT fall back. It reports. Booking is unaffected —
with no native event the emailed .ics reaches both calendars, which is the whole point of
having that fallback — but the product stops claiming a mode it is not in.
"""
import base64
import importlib
import json

import pytest

_GOOD_KEY = {"type": "service_account", "client_email": "bot@x.iam.gserviceaccount.com",
             "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
             "token_uri": "https://oauth2.googleapis.com/token"}


@pytest.fixture()
def clean(monkeypatch):
    for k in ("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON",
              "CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_FILE",
              "CHORDENTIAL_GOOGLE_CLIENT_ID", "CHORDENTIAL_GOOGLE_CLIENT_SECRET",
              "CHORDENTIAL_GOOGLE_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CHORDENTIAL_CALENDAR_PROVIDER", "google")
    from chordential_oia.meetings import google as g
    return importlib.reload(g)


def _oauth(monkeypatch):
    """The legacy variables, left behind in the dashboard after moving to a key file."""
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_REFRESH_TOKEN", "expired-token")


# ── the regression itself ────────────────────────────────────────────────────────
def test_a_broken_key_never_silently_resumes_the_retired_oauth_token(clean, monkeypatch):
    """THE bug. Both are configured; the key is unreadable; the old token must NOT be used."""
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", "eyJ0eXAiOiJ...truncated")
    _oauth(monkeypatch)
    p = clean.GoogleCalendarProvider()

    assert p.auth_mode() == "broken"
    assert p.configured() is False, (
        "falling back to the token the operator retired is how this looked fixed for weeks")
    assert p.create_event(summary="s", description="d", start=_dt(), end=_dt(),
                          attendees=["a@b.c"]) == "", "and it must not reach Google at all"


def test_the_problem_is_reported_in_words_that_name_the_fix(clean, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", "not base64 and not json {")
    _oauth(monkeypatch)
    problem = clean.GoogleCalendarProvider().config_problem()
    assert "SERVICE_ACCOUNT_JSON" in problem
    assert "base64" in problem                      # how to re-do it
    assert "NOT being used as a fallback" in problem  # and what is happening meanwhile


def test_a_key_that_decodes_but_is_the_wrong_file_is_caught_too(clean, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON",
                       base64.b64encode(json.dumps({"installed": {"client_id": "x"}})
                                        .encode()).decode())
    p = clean.GoogleCalendarProvider()
    assert p.auth_mode() == "broken"
    assert "private_key" in p.config_problem()


# ── the states that must keep working ────────────────────────────────────────────
def test_a_good_key_is_the_service_account_and_says_so(clean, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON",
                       base64.b64encode(json.dumps(_GOOD_KEY).encode()).decode())
    _oauth(monkeypatch)
    p = clean.GoogleCalendarProvider()
    assert p.auth_mode() == "service_account" and p.configured() and not p.config_problem()
    assert p.invites_attendees() is False, "a service account cannot invite guests"


def test_raw_json_still_works_for_anyone_not_using_base64(clean, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(_GOOD_KEY))
    p = clean.GoogleCalendarProvider()
    assert p.auth_mode() == "service_account" and not p.config_problem()


def test_the_key_file_pasted_straight_in_works(clean, monkeypatch):
    """The paste anyone would try first, and the one that used to fail.

    A service-account key file escapes the PEM's newlines as ``\\n``. Paste that file into
    a dashboard field and they commonly arrive as REAL line breaks, which is no longer
    valid JSON — so the key silently did not load. Requiring `base64 -w0` first was a
    workaround the operator had to get right on the first attempt with no feedback."""
    pretty = json.dumps(_GOOD_KEY, indent=2)
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON",
                       pretty.replace("\\n", "\n"))     # what the paste does to it
    p = clean.GoogleCalendarProvider()
    assert p.auth_mode() == "service_account", p.config_problem()
    assert "BEGIN PRIVATE KEY" in p.sa_info["private_key"]
    assert "\n" in p.sa_info["private_key"], "the PEM must come back as real lines"


def test_repairing_a_paste_never_touches_the_json_structure(clean):
    """Only newlines INSIDE a string are escaped. The line breaks between fields are legal
    whitespace, and escaping those would corrupt the document rather than repair it."""
    src = '{\n  "a": "one\ntwo",\n  "b": 2\n}'
    assert json.loads(clean._reescape_newlines_inside_strings(src)) == {"a": "one\ntwo", "b": 2}


def test_no_key_at_all_uses_oauth_exactly_as_before(clean, monkeypatch):
    """Absent is NOT broken. Someone deliberately on OAuth must be unaffected."""
    _oauth(monkeypatch)
    p = clean.GoogleCalendarProvider()
    assert p.auth_mode() == "oauth" and p.configured() and not p.config_problem()
    assert p.invites_attendees() is True


def test_nothing_configured_is_not_a_problem_to_report(clean):
    p = clean.GoogleCalendarProvider()
    assert p.auth_mode() == "none" and not p.configured() and not p.config_problem()


# ── and the operator is told, on the page where they book ────────────────────────
def test_the_schedule_page_stops_claiming_a_mode_it_is_not_in(clean, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from chordential_oia.models import Opportunity
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "b.db"))
    monkeypatch.setenv("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", "truncated-paste")
    _oauth(monkeypatch)
    from chordential_oia.web import db as dbm
    dbm = importlib.reload(dbm)
    conn = dbm.connect()
    dbm.init_db(conn)
    oid = dbm.insert_opportunity(conn, Opportunity(
        client="Champ Atlantic", need="Fall launch", description=""))
    conn.close()
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{oid}/schedule").text

    assert "credential cannot be used" in page
    assert "Google invites both calendars" not in page, (
        "the OAuth banner for an account that is not on OAuth is the lie that hid this")


def _dt():
    from datetime import datetime, timezone
    return datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
