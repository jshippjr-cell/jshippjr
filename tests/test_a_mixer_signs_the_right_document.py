"""The routing, walked end to end — portal, roster, queue, gate.

``test_the_agreement_a_mixer_should_be_asked_to_sign.py`` holds the rule and the document.
This file holds the thing that actually broke people: **every surface that asks "has this
person signed?" must ask about the document they were shown.**

A single reader left on ``DOC_COMPOSER_AGREEMENT`` is not a cosmetic miss. It tells a
mixer who signed that they have not, offers them the writer's agreement a second time,
and — in the Disposition Queue — silently drops every engineer's signature out of the
list of things waiting to be countersigned.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from chordential_oia import agreements, signing
from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "a.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("letmein"))
    conn = db.connect()
    db.init_db(conn)

    def hire(name, mail, *disciplines):
        tid = db.insert_talent(conn, Talent(name=name, email=mail, rate=90.0,
                                            disciplines=list(disciplines)))
        return tid, db.ensure_talent_portal_token(conn, tid)

    mixer = hire("Rae Okonkwo", "rae@example.com", MusicDiscipline.MIXING)
    writer = hire("Ada Cheng", "ada@example.com", MusicDiscipline.COMPOSITION)
    blank = hire("Nobody Yet", "no@example.com")
    conn.close()
    return c, db, mixer, writer, blank


def _sign(c, token, name):
    return c.post(f"/creator/{token}/agreement/sign",
                  data={"typed_name": name, "consent": "1"},
                  follow_redirects=False)


# ── the portal serves the right document ────────────────────────────────────────────
def test_the_mixers_portal_shows_the_service_agreement(studio):
    c, _db, (_tid, tok), *_ = studio
    page = c.get(f"/creator/{tok}/agreement").text
    assert "SERVICE AGREEMENT" in page
    assert "COMPOSER AGREEMENT" not in page, "still the writer's agreement"
    assert "<h1>Service Agreement</h1>" in page
    assert "NO PUBLISHING" in page


def test_the_writers_portal_is_unchanged(studio):
    c, _db, _m, (_tid, tok), _b = studio
    page = c.get(f"/creator/{tok}/agreement").text
    assert "COMPOSER AGREEMENT" in page
    assert "<h1>Composer Agreement</h1>" in page


def test_a_creator_with_no_craft_is_offered_neither(studio):
    """Not the writer's "just in case" — that IS the defect. The page says what is
    missing instead."""
    c, _db, _m, _w, (_tid, tok) = studio
    page = c.get(f"/creator/{tok}/agreement").text
    assert "Not ready to sign" in page
    assert "Add at least one discipline" in page
    assert "COMPOSER AGREEMENT" not in page and "SERVICE AGREEMENT" not in page


# ── signing files it under the right kind ───────────────────────────────────────────
def test_the_mixers_signature_is_filed_as_a_service_agreement(studio):
    c, db, (tid, tok), *_ = studio
    assert _sign(c, tok, "Rae Okonkwo").status_code == 303
    conn = db.connect()
    try:
        assert db.latest_talent_signature(
            conn, tid, signing.DOC_SERVICE_AGREEMENT) is not None
        assert db.latest_talent_signature(
            conn, tid, signing.DOC_COMPOSER_AGREEMENT) is None, (
            "filed under the writer's agreement — the one they never saw")
        row = db.get_talent(conn, tid)
    finally:
        conn.close()
    assert row["agreement_executed_at"], "the assignment gate did not open"
    assert "Service Agreement signed" in (row["agreement_ref"] or ""), (
        "the roster records a date without saying which document")


def test_the_signature_covers_the_text_they_were_shown(studio):
    """ADR-0059. If the digest were taken over the other document, the page would report
    SUPERSEDED forever and nobody would know why."""
    c, db, (tid, tok), *_ = studio
    _sign(c, tok, "Rae Okonkwo")
    conn = db.connect()
    try:
        sig = db.latest_talent_signature(conn, tid, signing.DOC_SERVICE_AGREEMENT)
        text = agreements.build_for(db.get_talent(conn, tid)).signable_text()
    finally:
        conn.close()
    assert signing.verify(sig["digest"], text) == signing.VALID
    assert "✓ Signed" in c.get(f"/creator/{tok}/agreement").text


def test_signing_twice_does_not_stack_rows(studio):
    c, db, (tid, tok), *_ = studio
    _sign(c, tok, "Rae Okonkwo")
    _sign(c, tok, "Rae Okonkwo")
    conn = db.connect()
    n = conn.execute("SELECT COUNT(*) c FROM signature WHERE talent_id = ? AND "
                     "doc_kind = ?", (tid, signing.DOC_SERVICE_AGREEMENT)).fetchone()["c"]
    conn.close()
    assert n == 1


def test_a_creator_with_no_craft_cannot_sign_anything(studio):
    c, db, _m, _w, (tid, tok) = studio
    _sign(c, tok, "Nobody Yet")
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) c FROM signature WHERE talent_id = ?",
                            (tid,)).fetchone()["c"] == 0
        assert not (db.get_talent(conn, tid)["agreement_executed_at"] or "")
    finally:
        conn.close()


def test_signing_it_joins_the_roster_too(studio):
    """The funnel rule (ADR-0081) is about the standing agreement, whichever one it is."""
    from chordential_oia.talent import InviteStatus
    c, db, (tid, tok), *_ = studio
    _sign(c, tok, "Rae Okonkwo")
    conn = db.connect()
    assert conn.execute("SELECT invite_status FROM talent WHERE id = ?",
                        (tid,)).fetchone()["invite_status"] == InviteStatus.JOINED.value
    conn.close()


# ── the surfaces that read it ───────────────────────────────────────────────────────
def test_the_portal_banner_names_the_right_agreement(studio):
    """The banner is the only mention of the agreement most creators ever read. Offering
    a mixer a "Composer Agreement" there tells them the studio thinks they write."""
    c, _db, (_mid, mtok), (_wid, wtok), _b = studio
    mixer = c.get(f"/creator/{mtok}").text
    assert ">Service Agreement<" in mixer
    assert "Composer Agreement" not in mixer
    assert ">Composer Agreement<" in c.get(f"/creator/{wtok}").text


def test_the_room_still_opens_for_everyone_who_is_not_a_creator(studio):
    """Regression, caught by the sweep and not by any of the tests above: naming the
    agreement in the room's banner read a variable that only exists on the creator's
    branch, so every OTHER role — the client on a share link, the studio — 500'd on the
    one surface all three share. A room is a shared door; a change on one arm of it is
    only proven by opening the other arms."""
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    c, db, (mid, mtok), *_ = studio
    conn = db.connect()
    try:
        pid = db.insert_project(conn, None, "The Larkspur Trust", "Sand Castle",
                                1000, 2000, ["Mixer"])
        db.add_assignment(conn, pid, "Mixer", mid)
        share = db.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    assert c.get(f"/room/{pid}").status_code == 200, "the studio's room broke"
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as anon:
        assert anon.get(f"/room/{pid}", params={"k": share}).status_code == 200, (
            "the client's room broke")
        creator = anon.get(f"/room/{pid}", params={"t": mtok})
    assert creator.status_code == 200
    assert ">Service Agreement<" in creator.text
    # …and the client is never shown a creator's standing agreement at all (ADR-0068).
    with TestClient(app_mod.app) as anon:
        assert "Service Agreement" not in anon.get(
            f"/room/{pid}", params={"k": share}).text


def test_the_roster_page_names_the_right_agreement(studio):
    c, _db, (tid, _tok), *_ = studio
    page = c.get(f"/talent/{tid}").text
    assert "Service Agreement not signed yet" in page
    assert "Composer Agreement" not in page


def test_the_roster_page_asks_for_a_craft_when_there_is_none(studio):
    c, _db, _m, _w, (tid, _tok) = studio
    page = c.get(f"/talent/{tid}").text
    assert "No standing agreement can be issued yet" in page
    assert "Add at least one discipline" in page


def test_the_queue_asks_for_the_countersignature_on_both(studio):
    """The reader most likely to be forgotten: a `doc_kind = ?` query pinned to the
    composer's kind drops every engineer's signature out of the list of decisions
    waiting on the studio, silently."""
    from chordential_oia.web import queue
    c, db, (_mid, mtok), (_wid, wtok), _b = studio
    _sign(c, mtok, "Rae Okonkwo")
    _sign(c, wtok, "Ada Cheng")
    conn = db.connect()
    try:
        cards = queue.compute_queue(conn, db)
    finally:
        conn.close()
    titles = [x["title"] for x in cards if x["kind"] == "composer_countersign"]
    assert any("Rae Okonkwo" in t for t in titles), "the mixer never reaches the queue"
    assert any("Ada Cheng" in t for t in titles)
    said = " ".join(x["detail"] for x in cards if x["kind"] == "composer_countersign")
    assert "Service Agreement" in said and "Composer Agreement" in said


def test_countersigning_lands_on_the_document_they_signed(studio):
    c, db, (tid, tok), *_ = studio
    _sign(c, tok, "Rae Okonkwo")
    r = c.post(f"/talent/{tid}/agreement/countersign",
               data={"typed_name": "Jon Shipp"}, follow_redirects=False)
    assert r.status_code == 303
    conn = db.connect()
    try:
        assert db.latest_talent_signature(
            conn, tid, signing.DOC_SERVICE_COUNTERSIGN) is not None
        assert db.latest_talent_signature(
            conn, tid, signing.DOC_COMPOSER_COUNTERSIGN) is None
    finally:
        conn.close()
    assert "✓ Countersigned" in c.get(f"/talent/{tid}").text


def test_countersigning_is_refused_before_they_sign(studio):
    c, db, (tid, _tok), *_ = studio
    r = c.post(f"/talent/{tid}/agreement/countersign", data={"typed_name": "Jon"},
               follow_redirects=False)
    assert r.headers["location"].endswith("?flag=not-signed#access")
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) c FROM signature WHERE talent_id = ?",
                        (tid,)).fetchone()["c"] == 0
    conn.close()


def test_the_gate_opens_for_a_mixer_who_signed_theirs(studio):
    """The point of the whole exercise: assignable, on the strength of the right
    document."""
    c, db, (tid, tok), *_ = studio
    conn = db.connect()
    try:
        assert db.talent_assignment_blockers(db.get_talent(conn, tid)) == ["agreement"]
    finally:
        conn.close()
    _sign(c, tok, "Rae Okonkwo")
    conn = db.connect()
    try:
        assert db.talent_assignment_blockers(db.get_talent(conn, tid)) == []
    finally:
        conn.close()


def test_the_invite_email_does_not_promise_a_mixer_a_writers_share(studio):
    """*"you keep 100% of your writer's share"* is a sentence about somebody else's job,
    and sending it is how a contractor arrives expecting publishing."""
    import chordential_oia.mailer as mailer
    sent = []
    c, _db, (tid, _tok), *_ = studio
    orig_conf, orig_send = mailer.mail_configured, mailer.send_email
    mailer.mail_configured = lambda: True
    mailer.send_email = lambda to, subj, body, **kw: (sent.append((subj, body)) or "sent")
    try:
        from chordential_oia.web import talent_routes
        talent_routes.mailer.mail_configured = mailer.mail_configured
        talent_routes.mailer.send_email = mailer.send_email
        c.post(f"/talent/{tid}/agreement/send", follow_redirects=False)
    finally:
        mailer.mail_configured, mailer.send_email = orig_conf, orig_send
    assert sent, "nothing was sent"
    subj, body = sent[0]
    assert "Service Agreement" in subj
    assert "writer's share" not in body
    assert "paid whether or not they've paid us yet" in body


def test_no_surface_still_hardcodes_the_composer_doc_kind():
    """A grep with a reason. Every reader of "has this creator signed?" goes through
    `agreements` now; a new one pinned to the composer's kind reintroduces the bug in
    one line, on a surface nobody thinks to re-test."""
    import pathlib
    web = pathlib.Path(agreements.__file__).parent / "web"
    offenders = []
    for p in sorted(web.glob("*.py")):
        body = p.read_text(encoding="utf-8")
        for i, line in enumerate(body.splitlines(), 1):
            if "DOC_COMPOSER_AGREEMENT" in line or "DOC_COMPOSER_COUNTERSIGN" in line:
                offenders.append(f"{p.name}:{i}")
    assert offenders == [], (
        "these ask about the writer's agreement directly instead of the one that "
        f"governs the creator: {offenders}")
