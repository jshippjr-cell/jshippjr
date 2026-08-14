"""When no block reaches a calendar, the product must say which of the reasons it was.

Reported live, twice, after the invitation itself was corrected: *"I STILL DONT SEE MY
CALENDAR BLOCKED WHEN THE ZOOM MEETING IS SCHEDULED."* The invitation was well-formed by
then — the failure was upstream of it, and invisible:

  • **No mail provider.** `mailer.send_email` is a no-op by default. It returns
    ``"logged"``, and `_safe_mail` threw that answer away. No email, no invitation, no
    block, no trace.
  • **No operator address.** `_operator_email` falls back to `CHORDENTIAL_SMTP_FROM` —
    the address the app sends *from*. An unset inbox therefore looks configured, and the
    invitation goes to the sender rather than to a person. `CHORDENTIAL_OPERATOR_EMAIL`
    was not declared in `render.yaml` at all, so nothing ever prompted for it.
  • **A send that errored.** Swallowed identically.

All three looked the same from outside: a page that reloaded and a calendar that stayed
empty. These tests are the difference between a system that fails and a system that fails
*legibly* — each cause names itself, before the call is booked and after.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity

pytest.importorskip("fastapi")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "w.db"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("CHORDENTIAL_CALENDAR_PROVIDER", raising=False)
    from chordential_oia.web import db as dbm
    dbm = importlib.reload(dbm)
    from chordential_oia.web import meeting_scheduler as ms
    ms = importlib.reload(ms)
    conn = dbm.connect()
    dbm.init_db(conn)
    oid = dbm.insert_opportunity(conn, Opportunity(
        client="Vance Athletic", need="Spring launch", description="",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL))
    try:
        yield dbm, ms, conn, dbm.get_opportunity(conn, oid)
    finally:
        conn.close()


def _book(dbm, ms, conn, opp):
    return ms.schedule(conn, opp, meeting_type="zoom",
                       start_at="2026-09-20T15:00:00+00:00", duration_min=30,
                       client_name="Dana", client_email="dana@vance.example",
                       join_url="https://zoom.example/j/1")


def _log(dbm, conn, meeting_id):
    return dbm.confirmations(dbm.get_meeting(conn, meeting_id))


# ── the record exists at all ─────────────────────────────────────────────────────
def test_a_booking_records_where_every_confirmation_went(env, monkeypatch):
    dbm, ms, conn, opp = env
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jshippjr@gmail.com")
    monkeypatch.setattr(ms.mailer, "send_email",
                        lambda to, subject, text, html=None, ics=None: "sent")
    res = _book(dbm, ms, conn, opp)

    log = _log(dbm, conn, res["meeting"]["id"])
    by_role = {e["role"]: e for e in log}
    assert set(by_role) == {"client", "operator"}
    assert by_role["operator"]["to"] == "jshippjr@gmail.com"
    assert by_role["operator"]["status"] == "sent"
    assert by_role["operator"]["invite"] is True


# ── cause 1: nothing is configured, so nothing was sent ──────────────────────────
def test_no_mail_provider_is_recorded_as_not_sent_rather_than_as_success(env, monkeypatch):
    """The default. `send_email` returns "logged" — intent recorded, nothing delivered."""
    dbm, ms, conn, opp = env
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jshippjr@gmail.com")
    monkeypatch.delenv("CHORDENTIAL_MAIL_PROVIDER", raising=False)
    res = _book(dbm, ms, conn, opp)

    log = _log(dbm, conn, res["meeting"]["id"])
    assert log and all(e["status"] == "logged" for e in log), (
        "a no-op mailer must be recorded as such, not left to look like a send")


def test_a_send_that_errors_is_recorded_as_an_error(env, monkeypatch):
    dbm, ms, conn, opp = env
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jshippjr@gmail.com")
    monkeypatch.setattr(ms.mailer, "send_email",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp down")))
    res = _book(dbm, ms, conn, opp)

    assert res["ok"], "a mail failure must never fail the booking"
    assert all(e["status"] == "error" for e in _log(dbm, conn, res["meeting"]["id"]))


# ── cause 2: the address that looked configured and was not ──────────────────────
def test_the_operator_address_falling_back_to_the_sender_is_flagged(env, monkeypatch):
    """THE bug. Unset CHORDENTIAL_OPERATOR_EMAIL silently becomes the app's own sending
    address, so the invitation goes to the mailbox the app sends FROM, not to a person."""
    dbm, ms, conn, opp = env
    monkeypatch.delenv("CHORDENTIAL_OPERATOR_EMAIL", raising=False)
    monkeypatch.setenv("CHORDENTIAL_SMTP_FROM", "hello@chordential.com")
    monkeypatch.setattr(ms.mailer, "send_email",
                        lambda to, subject, text, html=None, ics=None: "sent")
    assert ms.operator_email_is_a_guess() is True

    res = _book(dbm, ms, conn, opp)
    op = [e for e in _log(dbm, conn, res["meeting"]["id"]) if e["role"] == "operator"][0]
    assert op["to"] == "hello@chordential.com"
    assert op["guessed_address"] is True, "a guessed inbox must never read as a real one"


def test_a_real_operator_address_is_not_flagged(env, monkeypatch):
    _dbm, ms, _conn, _opp = env
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jshippjr@gmail.com")
    monkeypatch.setenv("CHORDENTIAL_SMTP_FROM", "hello@chordential.com")
    assert ms.operator_email_is_a_guess() is False


def test_no_address_anywhere_is_recorded_not_silently_skipped(env, monkeypatch):
    dbm, ms, conn, opp = env
    monkeypatch.delenv("CHORDENTIAL_OPERATOR_EMAIL", raising=False)
    monkeypatch.delenv("CHORDENTIAL_SMTP_FROM", raising=False)
    res = _book(dbm, ms, conn, opp)

    op = [e for e in _log(dbm, conn, res["meeting"]["id"]) if e["role"] == "operator"][0]
    assert op["status"] == "no-address", (
        "a booking nobody was told about must not look like a booking everyone was told about")


# ── it reaches a human, before and after the booking ─────────────────────────────
def test_the_schedule_page_warns_before_the_call_is_booked(env, monkeypatch):
    """The warning is worth most BEFORE the mistake, on the page where the call is made."""
    from fastapi.testclient import TestClient
    dbm, _ms, _conn, opp = env
    monkeypatch.setenv("CHORDENTIAL_MAIL_PROVIDER", "smtp")
    monkeypatch.setenv("CHORDENTIAL_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("CHORDENTIAL_SMTP_FROM", "hello@chordential.com")
    monkeypatch.delenv("CHORDENTIAL_OPERATOR_EMAIL", raising=False)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp['id']}/schedule").text
    assert "CHORDENTIAL_OPERATOR_EMAIL" in page
    assert "not your inbox" in page


def test_the_meeting_card_reports_what_happened_after(env, monkeypatch):
    from fastapi.testclient import TestClient
    dbm, ms, conn, opp = env
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jshippjr@gmail.com")
    _book(dbm, ms, conn, opp)          # default mailer → "logged", nothing delivered
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp['id']}").text
    assert "no mail provider configured" in page, (
        "the meeting card must say the invitation was never sent")


def test_the_page_says_where_your_copy_goes_even_when_nothing_is_wrong(env, monkeypatch):
    """A check that only speaks up on failure cannot be told apart from a deploy that has
    not landed. The operator hit exactly that: no warning, and no way to know whether the
    warning existed. So the line is always there, and its CONTENT carries the verdict."""
    from fastapi.testclient import TestClient
    _dbm, _ms, _conn, opp = env
    monkeypatch.setenv("CHORDENTIAL_MAIL_PROVIDER", "smtp")
    monkeypatch.setenv("CHORDENTIAL_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("CHORDENTIAL_SMTP_FROM", "hello@chordential.com")
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jshippjr@gmail.com")
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp['id']}/schedule").text
    assert "Your copy of this call goes to" in page
    assert "jshippjr@gmail.com" in page
    assert "not your inbox" not in page, "nothing is wrong here — do not cry wolf"


def test_a_calendar_that_refuses_the_event_says_so_instead_of_logging_it(env, monkeypatch):
    """The failure this hid. An OAuth refresh token minted in Testing status dies after 7
    days; `create_event` then raises `invalid_grant`, the exception was swallowed into a
    log warning, and the schedule page went on reporting a connected calendar."""
    from fastapi.testclient import TestClient
    dbm, ms, conn, opp = env
    monkeypatch.setenv("CHORDENTIAL_CALENDAR_PROVIDER", "google")
    monkeypatch.setenv("CHORDENTIAL_OPERATOR_EMAIL", "jshippjr@gmail.com")

    class _Refuses:
        name = "google"

        def invites_attendees(self):
            return True

        def create_event(self, **kw):
            raise RuntimeError("HTTP 400: invalid_grant")

    monkeypatch.setattr(ms.M, "get_calendar_provider", lambda: _Refuses())
    res = _book(dbm, ms, conn, opp)

    assert res["ok"], "a calendar refusal must never fail the booking"
    cal = [e for e in _log(dbm, conn, res["meeting"]["id"]) if e["role"] == "calendar"]
    assert cal and cal[0]["status"] == "error"
    assert "invalid_grant" in cal[0]["detail"]

    # and, because Google created nothing, the emailed invitation must take over
    others = [e for e in _log(dbm, conn, res["meeting"]["id"]) if e["role"] != "calendar"]
    assert all(e["invite"] for e in others), (
        "with no native event, the .ics is the only route to any calendar")

    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp['id']}").text
    assert "Google refused the event" in page


def test_the_deploy_blueprint_declares_the_operator_address():
    """It was missing entirely, so the Render dashboard never prompted for the one setting
    that decides whether the operator's calendar is ever touched."""
    import pathlib
    blueprint = pathlib.Path(__file__).resolve().parents[1] / "render.yaml"
    assert "CHORDENTIAL_OPERATOR_EMAIL" in blueprint.read_text()
