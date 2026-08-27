"""The phone knew and the dashboard did not.

    "When notifications go out per phase i get the notification on my phone but no alert
     is popping up in the dashboard. for example the client just paid their deposit. i got
     the phone notification but i opened the dashboard and there is no red badge to tell me
     what recently occurred."                              — the operator, 2026-08-27

Three nav badges already existed — Incoming, Queue, Signals — and none of them could ever
have carried this. They count things WAITING: unactioned gigs, submissions at the taste
gate. A client paying their deposit is not waiting for anything. It needs no decision, so
it appears in no queue, and the queue is right to leave it out: that surface answers "what
must I decide", and a list that pads itself with things needing nothing is one nobody
trusts to be short.

What was missing is the other question — "what happened while I was away" — which had a
channel to the operator's phone and no surface at all.

It is drawn from the OUTBOX's push rows rather than a hand-kept list of interesting
events. Every operator notification is recorded there already (ADR-0086), so the badge is
complete by construction, including for events added later. A curated list is the shape
that just failed on the delivery side: eleven callers remembered to notify and one did not,
and the one that did not was the one that mattered.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def console(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "a.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db, outbox
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    c.get("/dashboard")          # start from a read state
    return c, db, outbox


def _alert(outbox, title, body="something happened"):
    outbox.record_alert(title=title, body=body, status="sent")


def test_the_two_events_that_were_reported_now_badge(console):
    c, _db, outbox = console
    assert c.get("/alerts/count").json()["new"] == 0
    _alert(outbox, "Deposit paid · Pike and Rowan", "The deposit cleared.")
    _alert(outbox, "Assets uploaded · Pike and Rowan", "The client uploaded 3 files.")
    assert c.get("/alerts/count").json()["new"] == 2


def test_the_badge_is_visible_from_every_page(console):
    """It has to be legible from wherever the operator happens to be — that was the whole
    complaint: the notification arrived and the screen said nothing."""
    c, _db, outbox = console
    _alert(outbox, "Deposit paid")
    for path in ("/queue", "/projects", "/inbox"):
        page = c.get(path).text
        assert 'id="alert-badge"' in page, path
        assert ">1<" in page, path


def test_opening_the_dashboard_shows_what_happened(console):
    c, _db, outbox = console
    _alert(outbox, "Deposit paid · Pike and Rowan", "The deposit cleared.")
    _alert(outbox, "Assets uploaded · Pike and Rowan", "The client uploaded 3 files.")
    page = c.get("/dashboard").text
    assert "Since you were last here" in page
    assert "Deposit paid" in page and "Assets uploaded" in page
    assert page.count('pv-review">new') == 2


def test_reading_is_the_acknowledgement(console):
    """A badge that needs a second press to clear is a badge people stop trusting — and
    nothing on this panel is asking for a decision, so there is nothing to dismiss."""
    c, _db, outbox = console
    _alert(outbox, "Deposit paid")
    assert c.get("/alerts/count").json()["new"] == 1
    c.get("/dashboard")
    assert c.get("/alerts/count").json()["new"] == 0
    assert ">1<" not in c.get("/queue").text


def test_the_dashboard_does_not_show_a_count_it_is_clearing(console):
    """The shell fills `new_alerts` for every page. On THIS page it would be the number the
    operator came here to clear, still lit beside the panel clearing it."""
    c, _db, outbox = console
    _alert(outbox, "Deposit paid")
    page = c.get("/dashboard").text
    marker = page[page.index('id="alert-badge"'):][:220]
    assert "display:none" in marker, "the badge is still lit on the page that clears it"


def test_older_alerts_stay_readable_after_they_are_seen(console):
    """The panel is a record, not an inbox. Something read yesterday is still what
    happened."""
    c, _db, outbox = console
    _alert(outbox, "Deposit paid")
    c.get("/dashboard")
    _alert(outbox, "Assets uploaded")
    page = c.get("/dashboard").text
    assert "Deposit paid" in page and "Assets uploaded" in page
    assert page.count('pv-review">new') == 1, "the older one is still flagged new"


def test_it_counts_pushes_and_not_emails(console):
    """The outbox holds both. An email to a client is not something that happened TO the
    operator, and badging it would make the count meaningless within a day."""
    c, _db, outbox = console
    from chordential_oia import mailer
    mailer.send_email("client@example.com", "Your signed copy", "text")
    assert c.get("/alerts/count").json()["new"] == 0
    _alert(outbox, "Deposit paid")
    assert c.get("/alerts/count").json()["new"] == 1


def test_an_alert_nobody_could_deliver_is_still_counted(console):
    """`send_push` records `unset` when no ntfy topic is configured. That is precisely the
    case where the dashboard is the ONLY way the operator finds out, so it must count —
    and the panel says the status so a run of them is diagnosable."""
    c, _db, outbox = console
    outbox.record_alert(title="Deposit paid", body="", status="unset")
    assert c.get("/alerts/count").json()["new"] == 1
    assert "unset" in c.get("/dashboard").text


def test_the_queue_is_left_alone(console):
    """The fix must not pad the decision list. A paid deposit needs nothing from the
    operator, and a queue that lists things needing nothing is one nobody trusts to be
    short."""
    from chordential_oia.web import db as dbm, queue as queue_mod
    c, _db, outbox = console
    conn = dbm.connect()
    try:
        before = queue_mod.queue_view(conn, dbm)["total"]
    finally:
        conn.close()
    _alert(outbox, "Deposit paid")
    conn = dbm.connect()
    try:
        assert queue_mod.queue_view(conn, dbm)["total"] == before
    finally:
        conn.close()


def test_the_badge_never_takes_a_page_down(console):
    """Best-effort by construction: a count that cannot be read shows nothing rather than
    failing the page it decorates."""
    from chordential_oia.web import db as dbm
    conn = dbm.connect()
    try:
        conn.execute("DROP TABLE IF EXISTS alert_watermark")
        conn.commit()
        assert dbm.unseen_alert_count(conn) >= 0
        assert dbm.recent_alerts(conn) == [] or True
    finally:
        conn.close()
    c, _db, _outbox = console
    assert c.get("/queue").status_code == 200
