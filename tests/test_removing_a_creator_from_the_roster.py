"""A roster you can only add to.

Reported live (operator, 2026-08-20): *"I need a way to delete talent, especially the
demo talent that was created."* There was no delete — not on the roster, not on the
creator's own page, not anywhere.

The interesting part is what it must REFUSE. A creator row is pointed at by assignments
(the crew on a delivery, the chain of title on its clearance certificate, the payout
ledger) and by signatures — and ADR-0059 is explicit that signature rows are append-only
and withdrawal marks rather than deletes. Deleting the human to tidy a list would quietly
remove a counterparty from a contract. So the refusals are the feature: they say which
one it is, and what to do instead.
"""
import re

import pytest
from fastapi.testclient import TestClient

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent


@pytest.fixture()
def roster(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    import importlib
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("letmein"))
    conn = db.connect()
    db.init_db(conn)
    pid = db.insert_project(conn, None, "The Larkspur Trust", "Sand Castle",
                            1000, 2000, ["Composer"])

    def hire(name, mail):
        return db.insert_talent(conn, Talent(name=name, email=mail,
                                             disciplines=[MusicDiscipline.COMPOSITION]))

    free = hire("Demo Prospect", "demo@x.com")
    booked = hire("Ada Cheng", "ada@x.com")
    signer = hire("Ben Iyer", "ben@x.com")
    db.add_assignment(conn, pid, "Composer", booked)
    conn.close()
    return c, db, pid, free, booked, signer


# ── the delete ──────────────────────────────────────────────────────────────────────
def test_an_unassigned_creator_can_be_removed(roster):
    c, db, _pid, free, _b, _s = roster
    r = c.post(f"/talent/{free}/delete", follow_redirects=False)
    assert r.status_code == 303 and "removed=Demo%20Prospect" in r.headers["location"]
    conn = db.connect()
    assert db.get_talent(conn, free) is None
    conn.close()


def test_the_roster_says_who_went(roster):
    c, _db, _pid, free, _b, _s = roster
    c.post(f"/talent/{free}/delete", follow_redirects=False)
    page = c.get("/talent?removed=Demo%20Prospect").text
    assert "Removed Demo Prospect from the roster." in page


# ── and what it refuses ─────────────────────────────────────────────────────────────
def test_a_creator_on_a_project_is_refused(roster):
    """Deleting them leaves the crew, the chain of title and the payout ledger pointing
    at nobody."""
    c, db, _pid, _f, booked, _s = roster
    r = c.post(f"/talent/{booked}/delete", follow_redirects=False)
    assert r.headers["location"] == f"/talent/{booked}?delete=assigned"
    conn = db.connect()
    assert db.get_talent(conn, booked) is not None, "deleted anyway"
    conn.close()


def test_a_creator_who_signed_something_is_refused(roster):
    """ADR-0059: signature rows are append-only. The person who signed stays."""
    c, db, _pid, _f, _b, signer = roster
    from chordential_oia import signing
    conn = db.connect()
    sig = signing.build_signature(
        doc_kind=signing.DOC_COMPOSER_AGREEMENT, talent_id=signer,
        document_text="COMPOSER AGREEMENT\nTerms.", signer_name="Ben Iyer",
        signer_email="ben@x.com", typed_name="Ben Iyer")
    db.record_signature(conn, sig)
    assert db.talent_delete_block(conn, signer) == "signed"
    conn.close()
    r = c.post(f"/talent/{signer}/delete", follow_redirects=False)
    assert r.headers["location"] == f"/talent/{signer}?delete=signed"
    conn = db.connect()
    assert db.get_talent(conn, signer) is not None
    conn.close()


def test_the_refusal_says_which_and_what_to_do(roster):
    c, _db, _pid, _f, booked, _s = roster
    page = c.get(f"/talent/{booked}?delete=assigned").text
    assert "Not removed" in page
    assert "Remove them from it first" in page
    signed = c.get(f"/talent/{booked}?delete=signed").text
    assert "Signatures are a permanent record" in signed


def test_a_missing_creator_is_not_an_error(roster):
    c, _db, _pid, _f, _b, _s = roster
    r = c.post("/talent/99999/delete", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/talent"


# ── the control is there to press ───────────────────────────────────────────────────
def test_every_roster_card_offers_it(roster):
    c, _db, _pid, _f, _b, _s = roster
    page = c.get("/talent").text
    assert page.count('class="tc-del"') == 3, "not one control per creator"
    assert 'class="tc-wrap"' in page
    # the form must be a SIBLING of the card link, never nested inside the <a>
    assert not re.search(r'<a class="spot-card talent-card"[^>]*>(?:(?!</a>).)*?<form',
                         page, re.S), "a form inside an anchor"


def test_the_creators_own_page_offers_it(roster):
    c, _db, _pid, _f, booked, _s = roster
    page = c.get(f"/talent/{booked}").text
    assert f'action="/talent/{booked}/delete"' in page
    assert "Remove from roster" in page


# ── and two things that moved on the way past ───────────────────────────────────────
def test_the_pipeline_sits_under_the_decisions(roster):
    """*"put this section under the waiting on you"*. The three pipeline columns opened
    the page above Mission Control, so it started on deal state rather than on the one
    thing only the operator can do."""
    c, _db, _pid, _f, _b, _s = roster
    page = c.get("/dashboard").text
    assert page.index("Waiting on you") < page.index("pipeline-grid"), (
        "the pipeline is above the decisions again")
    tail = page.index("⚙ Machine running")
    assert page.index("pipeline-grid") < tail


def test_incoming_sits_above_today(roster):
    """*"put incoming above the today tab on the sidebar"*. What arrives on its own —
    and goes stale if nobody looks — belongs above what you do with it."""
    c, _db, _pid, _f, _b, _s = roster
    page = c.get("/dashboard").text
    assert page.index('href="/incoming"') < page.index('href="/dashboard"')
