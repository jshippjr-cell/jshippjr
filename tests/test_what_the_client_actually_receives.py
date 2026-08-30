"""Twenty-seven send sites, and no record of a single one.

Reported live (operator, 2026-08-21), on being asked how to test the product end to end
without borrowing a person to play the client: *"will this rehearsal console demo emails
sends, and alerts?"*

It could not have. On the null mail provider — the default, and what any rehearsal runs
on — ``send_email`` returned ``"logged"``, which was one line of ``logger.info`` carrying
a recipient and a subject and **no body at all**. Two questions therefore had no answer
from inside the product:

*"What does my client actually receive?"* Never seen. Every other defect in the client's
experience was found by sitting a real person in front of a real screen; the emails were
the one surface that could not be looked at without configuring SMTP and mailing a real
inbox — which during a rehearsal is worse, not better.

*"Did the pay link go out, and to whom?"* Unanswerable. A notification is best-effort and
silent by design — right for the request, wrong for the record.

So every send is recorded, sent or merely logged, **with the branded HTML the recipient
would see**. Storing only the plain text would have reproduced the original defect one
layer down: the branded shell IS the email (ADR-0066).
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def console(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "o.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.delenv("CHORDENTIAL_MAIL_PROVIDER", raising=False)
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    for m in ("db", "campaigns", "uploads", "outbox", "signals", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    return c, app_mod, db


# ── the record exists at all ────────────────────────────────────────────────────────
def test_a_send_is_recorded_even_when_nothing_is_sent(console):
    """The whole point. With no provider configured nothing leaves the building — and
    that is exactly when you most need to read what would have gone."""
    from chordential_oia import mailer
    _c, _app, db = console
    assert mailer.send_email("marta@larkspur.example", "Your proposal is ready",
                             "Hi Marta,\n\nHere it is.") == "logged"
    conn = db.connect()
    try:
        rows = db.list_outbox(conn)
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["recipient"] == "marta@larkspur.example"
    assert rows[0]["subject"] == "Your proposal is ready"
    assert rows[0]["status"] == "logged"
    assert "Hi Marta" in (rows[0]["body_text"] or ""), "the BODY was not kept"


def test_the_branded_html_is_kept_because_that_is_the_email(console):
    """A body carrying a link gets the branded shell, and that shell is what lands.
    Keeping only the plain text would answer "what does my client receive?" with
    something the client never sees."""
    from chordential_oia import mailer
    _c, _app, db = console
    mailer.send_email("marta@larkspur.example", "Your summary",
                      "Read it: https://chordential.com/workspace/abc123")
    conn = db.connect()
    try:
        row = db.list_outbox(conn)[0]
    finally:
        conn.close()
    html = row["body_html"] or ""
    assert html, "the rendered email was not stored"
    assert '<a href="https://chordential.com/workspace/abc123"' in html, (
        "the link is not a real anchor — the defect ADR-0066 exists to prevent")


def test_a_real_send_is_marked_sent_not_logged(console, monkeypatch):
    from chordential_oia import mailer
    _c, _app, db = console
    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(mailer, "_send_smtp", lambda *a, **k: "sent")
    mailer.send_email("marta@larkspur.example", "Real one", "Body")
    conn = db.connect()
    try:
        assert db.list_outbox(conn)[0]["status"] == "sent"
    finally:
        conn.close()


def test_a_failed_send_is_recorded_too(console, monkeypatch):
    """The one you most need afterwards."""
    from chordential_oia import mailer
    _c, _app, db = console

    def _boom(*a, **k):
        raise RuntimeError("smtp refused")

    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(mailer, "_send_smtp", _boom)
    assert mailer.send_email("marta@larkspur.example", "Doomed", "Body") == "error"
    conn = db.connect()
    try:
        rows = db.list_outbox(conn)
    finally:
        conn.close()
    assert rows and rows[0]["status"] == "error"


def test_recording_can_never_break_a_send(console, monkeypatch):
    """An audit trail that can fail the thing it audits is worse than none — the same
    rule `_log_decision` follows in app.py."""
    from chordential_oia import mailer
    from chordential_oia.web import outbox
    _c, _app, _db = console

    def _explode(**kw):
        raise RuntimeError("the outbox is on fire")

    monkeypatch.setattr(outbox, "_write", _explode)
    assert mailer.send_email("marta@larkspur.example", "Still fine", "Body") == "logged"


def test_a_send_with_no_recipient_records_nothing(console):
    from chordential_oia import mailer
    _c, _app, db = console
    assert mailer.send_email("", "Nowhere", "Body") == "error"
    conn = db.connect()
    try:
        assert db.list_outbox(conn) == []
    finally:
        conn.close()


# ── alerts, which had the same hole ─────────────────────────────────────────────────
def test_an_alert_nobody_configured_a_channel_for_says_so(console, monkeypatch):
    """'unset' is the interesting status: from the request's side an alert that fired and
    one that had nowhere to go look identical."""
    from chordential_oia.web import signals
    _c, _app, db = console
    monkeypatch.delenv("CHORDENTIAL_NTFY_TOPIC", raising=False)
    assert signals.send_push("New gig", body="Nike, :30 spot") == "unset"
    conn = db.connect()
    try:
        rows = db.list_outbox(conn)
    finally:
        conn.close()
    assert rows and rows[0]["channel"] == "push"
    assert rows[0]["status"] == "unset" and rows[0]["subject"] == "New gig"


# ── and it can be read ──────────────────────────────────────────────────────────────
def test_the_console_lists_what_would_have_gone(console):
    from chordential_oia import mailer
    c, _app, _db = console
    mailer.send_email("marta@larkspur.example", "Your proposal is ready", "Hi Marta")
    page = c.get("/outbox").text
    assert "Your proposal is ready" in page
    assert "marta@larkspur.example" in page
    assert "nothing left the building" in page, (
        "the page does not say that mail is off — the reader would think it was sent")


def test_one_message_can_be_read_as_the_client_would_see_it(console):
    from chordential_oia import mailer
    c, _app, db = console
    mailer.send_email("marta@larkspur.example", "Your summary",
                      "Read it: https://chordential.com/workspace/abc")
    conn = db.connect()
    try:
        mid = db.list_outbox(conn)[0]["id"]
    finally:
        conn.close()
    page = c.get(f"/outbox/{mid}").text
    assert f'src="/outbox/{mid}?raw=1"' in page, "no preview of the real email"
    assert "sandbox" in page, "a stored mail body is framed without a sandbox"
    raw = c.get(f"/outbox/{mid}?raw=1")
    assert raw.status_code == 200
    assert "chordential.com/workspace/abc" in raw.text


def test_the_preview_cannot_script_or_phone_home(console):
    """Replayed stored content, behind the admin gate, in a same-origin frame. It is not
    a page we are writing today and must not behave like one."""
    from chordential_oia import mailer
    c, _app, db = console
    mailer.send_email("x@example.com", "S", "Link: https://chordential.com/x")
    conn = db.connect()
    try:
        mid = db.list_outbox(conn)[0]["id"]
    finally:
        conn.close()
    r = c.get(f"/outbox/{mid}?raw=1")
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp
    assert "script-src" not in csp or "'unsafe-inline'" not in csp.split("script-src")[1][:30]
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_the_outbox_is_behind_the_admin_gate(console):
    """It holds every client's address and the full text of what we told them."""
    from fastapi.testclient import TestClient
    from chordential_oia.web import publicpaths as _gate
    _c, app_mod, _db = console
    assert not _gate.is_public("/outbox")
    with TestClient(app_mod.app) as anon:
        assert anon.get("/outbox", follow_redirects=False).status_code == 303


def test_clearing_is_deliberate_and_says_what_it_does_not_do(console):
    from chordential_oia import mailer
    c, _app, db = console
    mailer.send_email("a@example.com", "One", "Body")
    assert "does not unsend" in c.get("/outbox").text
    c.post("/outbox/clear", data={"project": ""}, follow_redirects=False)
    conn = db.connect()
    try:
        assert db.list_outbox(conn) == []
    finally:
        conn.close()


def test_the_nav_offers_it(console):
    c, _app, _db = console
    assert 'href="/outbox"' in c.get("/outbox").text
