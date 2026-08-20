"""A warranty nobody signed is a letterhead.

Reported live (operator, 2026-08-20): *"Dont i need to have an actual clearance
signature on the certificate? i was never asked for that in the whole process."*

Right on both counts. The Clearance Certificate is the studio warranting the chain of
title — it is the thing that makes a delivery worth what a client pays for it — and it
shipped with ``Signature: ________________________________`` printed on it. A ruled line
under a warranty reads as executed. Nothing in the flow ever asked anyone to fill it.

The CLIENT's acceptance already existed (`DOC_CLEARANCE`, verified reviewer only, consent
required, digest-bound — ADR-0059). What did not exist is Chordential's own execution of
the document it is handing over. `DOC_CLEARANCE_EXECUTED` is that, held to the same
standard: consent unticked by default, bound to the exact text, and reported SUPERSEDED
the moment a term changes underneath it.
"""
import os
import tempfile
import zipfile

import pytest
from fastapi.testclient import TestClient

from chordential_oia import signing
from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    import importlib
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db, production
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    c = TestClient(app_mod.app)
    up = str(tmp_path / "up")
    os.makedirs(up, exist_ok=True)
    with open(os.path.join(up, "v.wav"), "wb") as fh:
        fh.write(b"RIFF0000WAVE" + os.urandom(200))
    conn = db.connect()
    db.init_db(conn)
    pid = db.insert_project(conn, None, "The Larkspur Trust", "Sand Castle",
                            1000, 2000, ["Composer"])
    tid = db.insert_talent(conn, Talent(name="Jon Shipp", email="j@x.com",
                                        disciplines=[MusicDiscipline.COMPOSITION]))
    db.add_assignment(conn, pid, "Composer", tid)
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v2 FINAL", "url": "/uploads/v.wav",
                         "filename": "v.wav"}])
    production.set_creative_lock(conn, db, pid, version_n=2, by="Marta Ruiz")
    conn.close()
    admin = (ADMIN_COOKIE, admin_cookie_value("letmein"))
    c.cookies.set(*admin)
    return c, db, pid, up, admin


def _cert(db, pid):
    from chordential_oia.web.project_routes import _delivery_view
    conn = db.connect()
    try:
        return _delivery_view(conn, pid)["cert"]
    finally:
        conn.close()


def _sign(c, pid, **kw):
    data = {"typed_name": "Jon Shipp", "consent": "1"}
    data.update(kw)
    return c.post(f"/project/{pid}/delivery/certificate/execute", data=data,
                  follow_redirects=False)


# ── the state before anyone signs ───────────────────────────────────────────────────
def test_an_unsigned_certificate_says_so_rather_than_ruling_a_line(studio):
    c, db, pid, up, _a = studio
    cert = _cert(db, pid)
    assert cert.execution_state == "", "an unsigned certificate claims a signature"
    from chordential_oia.delivery import build_clearance_certificate, clearance_certificate_html
    html = clearance_certificate_html(cert)
    assert "Not yet executed" in html
    assert "________" not in html, "the blank ruled line is back — it reads as executed"


def test_it_is_named_as_a_hold(studio):
    c, db, pid, _up, _a = studio
    from chordential_oia.web.delivery_ops import DELIVERY_HELD, delivery_held_by
    conn = db.connect()
    # everything else about this delivery is done
    from chordential_oia.delivery import scoped_deliverables
    prow = db.get_project(conn, pid)
    assets = [{"label": d["asset"], "filename": "v.wav", "url": "/uploads/v.wav",
               "kind": "audio"}
              for d in scoped_deliverables(prow, db.get_delivery(conn, pid))
              if not d.get("is_master")]
    db.update_delivery(conn, pid, "assets", assets)
    for a in assets:
        db.set_asset_approval(conn, pid, db.asset_key(a), status="Approved",
                              by="Marta", email="m@a.com", version="2")
    db.update_delivery(conn, pid, "license_confirmed", {"by": "Jon", "date": "2026-08-20"})
    held = delivery_held_by(db.get_delivery(conn, pid), prow)
    conn.close()
    assert held == "unsigned", held
    assert "warranting the chain of title" in DELIVERY_HELD["unsigned"]


# ── signing it ──────────────────────────────────────────────────────────────────────
def test_consent_is_required_and_not_assumed(studio):
    """The same ESIGN/UETA rule the client's signature follows. The studio does not get
    a weaker standard than the person it is asking to sign."""
    c, db, pid, _up, _a = studio
    r = _sign(c, pid, consent="")
    assert "cert=consent" in r.headers["location"]
    conn = db.connect()
    assert db.latest_signature(conn, pid, signing.DOC_CLEARANCE_EXECUTED) is None
    conn.close()


def test_a_name_is_required(studio):
    c, db, pid, _up, _a = studio
    r = _sign(c, pid, typed_name="   ")
    assert "cert=empty" in r.headers["location"]


def test_signing_records_a_real_signature(studio):
    c, db, pid, _up, _a = studio
    r = _sign(c, pid)
    assert "cert=signed" in r.headers["location"]
    conn = db.connect()
    try:
        sig = db.latest_signature(conn, pid, signing.DOC_CLEARANCE_EXECUTED)
        assert sig is not None
        assert sig["signer_name"] == "Jon Shipp"
        assert len(sig["digest"]) == 64, "not a SHA-256 of the document"
        summary = db.get_delivery(conn, pid)["certificate_executed"]
        assert summary["digest"] == sig["digest"], (
            "the rendered summary and the record disagree")
    finally:
        conn.close()


def test_the_signature_binds_to_the_document_it_was_printed_beside(studio):
    c, db, pid, _up, _a = studio
    _sign(c, pid)
    cert = _cert(db, pid)
    assert cert.execution_state == "valid"
    assert cert.executed["digest"] == signing.document_digest(cert.signable_text())


def test_changing_a_term_afterwards_supersedes_it(studio):
    """The whole point of binding to a digest. A client whose warranty was edited after
    signing is entitled to see that it was."""
    c, db, pid, _up, _a = studio
    _sign(c, pid)
    conn = db.connect()
    db.update_delivery(conn, pid, "license", {"territory": "North America only"})
    conn.close()
    cert = _cert(db, pid)
    assert cert.execution_state == "superseded"
    from chordential_oia.delivery import clearance_certificate_html
    html = clearance_certificate_html(cert)
    assert "HAS CHANGED since" in html


# ── and it reaches the package the client opens ─────────────────────────────────────
def _package_cert(db, pid, up):
    from chordential_oia.web.delivery_ops import _build_delivery_package
    conn = db.connect()
    pkg = _build_delivery_package(conn, pid)
    conn.close()
    z = zipfile.ZipFile(os.path.join(up, pkg["filename"]))
    return (z.read("Docs/For-filing/rights_certificate.txt").decode(),
            z.read("Docs/Clearance-Certificate.html").decode())


def test_the_delivered_certificate_carries_the_signature(studio):
    c, db, pid, up, _a = studio
    _sign(c, pid)
    txt, html = _package_cert(db, pid, up)
    assert "Signed:      Jon Shipp" in txt, txt[txt.index("SIGNATORY"):][:300]
    assert "SHA-256:" in txt
    assert "Signature:   ____" not in txt
    assert "Signed electronically by Jon Shipp" in html


def test_an_unsigned_certificate_ships_saying_so(studio):
    """It must not ship a ruled blank that reads as executed — the client cannot tell
    the difference between "not signed" and "sign here"."""
    c, db, pid, up, _a = studio
    txt, html = _package_cert(db, pid, up)
    assert "NOT YET EXECUTED" in txt
    assert "Not yet executed" in html


def test_a_superseded_certificate_ships_saying_that_too(studio):
    c, db, pid, up, _a = studio
    _sign(c, pid)
    conn = db.connect()
    db.update_delivery(conn, pid, "license", {"term": "3 years"})
    conn.close()
    txt, _html = _package_cert(db, pid, up)
    assert "SUPERSEDED" in txt
    assert "covers the earlier version" in txt


# ── who may do it ───────────────────────────────────────────────────────────────────
def test_no_token_can_execute_the_studios_own_warranty(studio):
    """There is no client or creator credential that should ever produce Chordential's
    signature on Chordential's warranty."""
    c, db, pid, _up, _a = studio
    c.cookies.clear()
    r = _sign(c, pid)
    assert r.status_code in (303, 401, 403, 404)
    if r.status_code == 303:
        assert "/admin" in r.headers["location"] or "login" in r.headers["location"]
    conn = db.connect()
    assert db.latest_signature(conn, pid, signing.DOC_CLEARANCE_EXECUTED) is None
    conn.close()


def test_the_console_offers_it_and_asks_for_the_licence_first(studio):
    c, db, pid, _up, _a = studio
    page = c.get(f"/project/{pid}/delivery").text
    assert "/delivery/certificate/execute" in page
    assert "I agree to sign electronically" in page
    assert "Confirm license terms" in page, (
        "the licence must be offered first — confirming it changes the document")
    _sign(c, pid)
    import re as _re
    page = _re.sub(r"\s+", " ", c.get(f"/project/{pid}/delivery").text)
    assert "Certificate signed by Jon Shipp" in page
