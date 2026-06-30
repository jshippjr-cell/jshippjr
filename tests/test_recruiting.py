"""Recruiting campaign — the 'Why Chordential for artists' page + invite composer.

The composer drafts a personalized, honest invite (respect + fair terms + first-look,
never volume/salary); Jon copies, edits, and sends it. Deterministic, no LLM.
"""

import importlib

import pytest

from chordential_oia import recruiting
from chordential_oia.talent import Talent
from chordential_oia.models import MusicDiscipline


def test_invite_personalizes_with_credit():
    t = Talent(name="Mara Velez", disciplines=[MusicDiscipline.COMPOSITION],
               credits="Scored two national auto spots")
    inv = recruiting.compose_invite(
        t, apply_url="https://x/apply", artists_url="https://x/for-artists")
    assert "Mara" in inv["subject"]
    assert "Scored two national auto spots".lower() in inv["body"].lower()
    assert "https://x/apply" in inv["body"]
    assert "https://x/for-artists" in inv["body"]


def test_invite_falls_back_to_discipline_without_credit():
    t = Talent(name="Devin Park", disciplines=[MusicDiscipline.SOUND_DESIGN])
    inv = recruiting.compose_invite(
        t, apply_url="https://x/apply", artists_url="https://x/a")
    # No credit → leads with the craft, not a fabricated credit.
    assert "roster" in inv["body"].lower()
    assert inv["body"].startswith("Hi Devin,")


def test_invite_is_honest_never_promises_salary():
    t = Talent(name="Sofia Ramos", disciplines=[MusicDiscipline.SONIC_BRANDING])
    body = recruiting.compose_invite(
        t, apply_url="https://x/apply", artists_url="https://x/a")["body"].lower()
    assert "salary" not in body
    assert "steady income" not in body
    assert "we're early" in body  # under-promises volume


def test_skip_blocks():
    t = Talent(name="Ada", disciplines=[MusicDiscipline.COMPOSITION])
    inv = recruiting.compose_invite(
        t, apply_url="https://x/apply", artists_url="https://x/a", skip=["signoff"])
    assert "Chordential" in inv["body"]
    assert not inv["body"].rstrip().endswith("— Jon, Chordential")


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def test_for_artists_page_renders(ctx):
    client, _ = ctx
    r = client.get("/for-artists")
    assert r.status_code == 200
    assert "Real briefs" in r.text
    assert "/apply" in r.text and "/refer" in r.text


def test_talent_detail_shows_invite_composer(ctx):
    client, db_mod = ctx
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="Mara Velez", disciplines=[MusicDiscipline.COMPOSITION],
        credits="Scored two spots"))
    conn.close()
    page = client.get(f"/talent/{tid}").text
    assert "Recruiting invite" in page


def test_send_invite_falls_back_to_manual(ctx):
    # No email + null mailer → no send, stays Prospect, flagged manual (never crashes).
    client, db_mod = ctx
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="No Email", disciplines=[MusicDiscipline.COMPOSITION]))
    conn.close()
    r = client.post(f"/talent/{tid}/invite/send", follow_redirects=False)
    assert r.status_code == 303
    assert "invite=manual" in r.headers["location"]
    conn = db_mod.connect()
    try:
        inv = conn.execute(
            "SELECT invite_status FROM talent WHERE id=?", (tid,)).fetchone()[0]
    finally:
        conn.close()
    assert inv == "Prospect"  # unchanged — nothing was sent


def test_send_invite_emails_and_advances(ctx, monkeypatch):
    client, db_mod = ctx
    from chordential_oia.web import app as app_mod
    sent = {}

    def fake_send(to, subject, text, html=None):
        sent.update(to=to, subject=subject, text=text)
        return "sent"

    monkeypatch.setattr(app_mod.mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(app_mod.mailer, "send_email", fake_send)
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="Mara Velez", email="mara@example.com",
        disciplines=[MusicDiscipline.COMPOSITION], credits="Scored two spots"))
    conn.close()
    r = client.post(f"/talent/{tid}/invite/send", follow_redirects=False)
    assert "invite=sent" in r.headers["location"]
    assert sent["to"] == "mara@example.com"
    assert "Chordential" in sent["text"]
    conn = db_mod.connect()
    try:
        inv = conn.execute(
            "SELECT invite_status FROM talent WHERE id=?", (tid,)).fetchone()[0]
    finally:
        conn.close()
    assert inv == "Invited"  # funnel advanced on a successful send
