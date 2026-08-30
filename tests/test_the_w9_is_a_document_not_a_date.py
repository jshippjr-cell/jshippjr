"""A W-9 you can actually produce, and a funnel that moves when someone signs.

Reported live (operator, 2026-08-20): *"is there a way for me to store the w-9 attached
to each particular talent? right now i just see a button. after the talent has signed
their agreement shouldn't the recruiting funnel move to 'joined'"*

Two things, both the same shape: **a flag standing in for the thing itself.**

``w9_received_at`` was a date the operator typed by pressing a button. A W-9 is the
document you produce when a payment is questioned — a date with nothing behind it is
worse than an empty field, because it reads as done. Marking it received by hand still
works (one that arrived by post is still a W-9) and the page says which of the two it is.

And ``invite_status`` never left *Invited* in the live flow. Only ``seed.py`` ever wrote
*Joined*, so a real creator who had signed the standing agreement — the moment they
become assignable — sat in the recruiting funnel forever as someone we were still
waiting on.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import InviteStatus, Talent


@pytest.fixture()
def roster(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    from chordential_oia.web import publicpaths as _gate
    importlib.reload(app_mod)
    from chordential_oia.web import db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("letmein"))
    conn = db.connect()
    db.init_db(conn)
    tid = db.insert_talent(conn, Talent(
        name="Ada Cheng", email="ada@example.com", rate=90.0,
        disciplines=[MusicDiscipline.COMPOSITION]))
    db.update_talent_invite(conn, tid, InviteStatus.INVITED.value)
    token = db.ensure_talent_portal_token(conn, tid)
    conn.close()
    return c, db, tid, token


# ── the W-9 is a file ───────────────────────────────────────────────────────────────
def test_the_form_takes_a_file(roster):
    c, db, tid, _tok = roster
    r = c.post(f"/talent/{tid}/w9",
               files={"file": ("ada-w9.pdf", b"%PDF-1.4 fake", "application/pdf")},
               follow_redirects=False)
    assert r.status_code == 303
    conn = db.connect()
    row = conn.execute("SELECT * FROM talent WHERE id = ?", (tid,)).fetchone()
    conn.close()
    assert row["w9_filename"], "the bytes went nowhere — only a date was stored"
    assert row["w9_orig"] == "ada-w9.pdf", "the operator cannot tell what they attached"
    assert row["w9_received_at"], "attaching the form did not satisfy the payout gate"


def test_the_bytes_go_through_the_write_door(roster):
    """ADR-0043: every upload is written by ``_persist_upload``, so it lands wherever the
    object store is — never by opening a path here."""
    c, db, tid, _tok = roster
    c.post(f"/talent/{tid}/w9",
           files={"file": ("ada-w9.pdf", b"%PDF-1.4 fake", "application/pdf")})
    conn = db.connect()
    name = conn.execute("SELECT w9_filename FROM talent WHERE id = ?",
                        (tid,)).fetchone()["w9_filename"]
    conn.close()
    import os
    from chordential_oia.web.uploads import upload_dir
    assert os.path.exists(os.path.join(upload_dir(), name))


def test_the_page_offers_the_stored_form_back(roster):
    c, _db, tid, _tok = roster
    c.post(f"/talent/{tid}/w9",
           files={"file": ("ada-w9.pdf", b"%PDF-1.4 fake", "application/pdf")})
    page = c.get(f"/talent/{tid}").text
    assert "✓ W-9 on file" in page
    assert "ada-w9.pdf" in page, "it is on file and there is no way to open it"
    assert 'enctype="multipart/form-data"' in page


def test_marking_it_by_hand_still_works_and_says_so(roster):
    """A W-9 that arrived by post is still a W-9. What must not happen is the page
    claiming a document it does not have."""
    c, db, tid, _tok = roster
    c.post(f"/talent/{tid}/w9", data={"received": "1"})
    conn = db.connect()
    row = conn.execute("SELECT * FROM talent WHERE id = ?", (tid,)).fetchone()
    conn.close()
    assert row["w9_received_at"] and not row["w9_filename"]
    page = c.get(f"/talent/{tid}").text
    assert "marked received by hand; no file attached" in page


def test_clearing_takes_the_file_with_it(roster):
    c, db, tid, _tok = roster
    c.post(f"/talent/{tid}/w9",
           files={"file": ("ada-w9.pdf", b"%PDF-1.4 fake", "application/pdf")})
    c.post(f"/talent/{tid}/w9", data={"received": "0"})
    conn = db.connect()
    row = conn.execute("SELECT * FROM talent WHERE id = ?", (tid,)).fetchone()
    conn.close()
    assert not row["w9_received_at"] and not row["w9_filename"], (
        "the flag was cleared while the page still had a form to hand back")


def test_an_oversized_file_is_refused_by_name(roster):
    """A tax form is a page or two. Anything else is the wrong file, and saying which
    is the difference between a fix and a shrug."""
    from chordential_oia.web import talent_routes
    c, db, tid, _tok = roster
    big = b"x" * (talent_routes._W9_MAX_BYTES + 1)
    r = c.post(f"/talent/{tid}/w9",
               files={"file": ("huge.pdf", big, "application/pdf")},
               follow_redirects=False)
    assert r.headers["location"] == f"/talent/{tid}?w9=big#access"
    conn = db.connect()
    assert not conn.execute("SELECT w9_received_at FROM talent WHERE id = ?",
                            (tid,)).fetchone()["w9_received_at"]
    conn.close()
    assert "over 16" in c.get(f"/talent/{tid}?w9=big").text


def test_the_w9_is_not_a_public_url(roster):
    """It carries a taxpayer ID. ``/uploads/{name}`` is behind the admin gate — client
    media reaches a buyer through the token-scoped ``/project/{id}/dl/`` instead — and
    this is the assertion that keeps it there."""
    from chordential_oia.web import publicpaths as _gate
    assert not _gate.is_public("/uploads/w9-1-abc.pdf")


# ── and the funnel moves ────────────────────────────────────────────────────────────
def test_signing_the_agreement_joins_the_roster(roster):
    c, db, tid, token = roster
    r = c.post(f"/creator/{token}/agreement/sign",
               data={"typed_name": "Ada Cheng", "consent": "1",
                     "signer_email": "ada@example.com"},
               follow_redirects=False)
    assert r.status_code == 303
    conn = db.connect()
    row = conn.execute("SELECT * FROM talent WHERE id = ?", (tid,)).fetchone()
    conn.close()
    assert row["agreement_executed_at"], "the signature did not satisfy the gate"
    assert row["invite_status"] == InviteStatus.JOINED.value, (
        "signed, assignable, and still sitting in the funnel as Invited")


def test_an_unsigned_creator_is_left_where_they_are(roster):
    """The funnel moves on the SIGNATURE, not on opening the page."""
    c, db, tid, token = roster
    c.get(f"/creator/{token}/agreement")
    c.post(f"/creator/{token}/agreement/sign", data={"typed_name": "", "consent": ""})
    conn = db.connect()
    assert conn.execute("SELECT invite_status FROM talent WHERE id = ?",
                        (tid,)).fetchone()["invite_status"] == InviteStatus.INVITED.value
    conn.close()


def test_signing_never_demotes_someone_already_joined(roster):
    c, db, tid, token = roster
    conn = db.connect()
    db.update_talent_invite(conn, tid, InviteStatus.JOINED.value)
    conn.close()
    c.post(f"/creator/{token}/agreement/sign",
           data={"typed_name": "Ada Cheng", "consent": "1"})
    conn = db.connect()
    assert conn.execute("SELECT invite_status FROM talent WHERE id = ?",
                        (tid,)).fetchone()["invite_status"] == InviteStatus.JOINED.value
    conn.close()
