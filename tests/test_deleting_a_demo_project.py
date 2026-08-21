"""A board you could only add to.

Reported live (operator, 2026-08-20): *"I need a way to delete demo projects."* Every
rehearsal run of the funnel left a project behind, and a demo sat in the pipeline looking
exactly like work someone is waiting on.

As with the roster (``test_removing_a_creator_from_the_roster.py``), **the refusals are
the feature**. A project accumulates records that outlive it — a paid invoice is an
accounting entry, a signature is append-only (ADR-0059), and a delivered package is the
record of work a client has in hand. "Clear the demos" must never be able to take one of
those with it, and when it declines it says which one it is.

The other half is what it must NOT take: the opportunity. A project is one delivery of a
deal; deleting the delivery and the deal together would erase the buyer relationship to
tidy a list.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from chordential_oia.invoicing import Invoice


@pytest.fixture()
def board(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "p.db"))
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

    def spin(need):
        return db.insert_project(conn, None, "The Larkspur Trust", need,
                                 1000, 2000, ["Composer"])

    demo = spin("Rehearsal Spot")
    paid = spin("Sand Castle")
    signed = spin("Winter Light")
    shipped = spin("Night Ferry")
    conn.close()
    return c, db, demo, paid, signed, shipped


# ── the delete ──────────────────────────────────────────────────────────────────────
def test_a_demo_project_can_be_deleted(board):
    c, db, demo, *_ = board
    r = c.post(f"/project/{demo}/delete", follow_redirects=False)
    assert r.status_code == 303 and "deleted=Rehearsal%20Spot" in r.headers["location"]
    conn = db.connect()
    assert db.get_project(conn, demo) is None
    conn.close()


def test_it_takes_its_own_children_with_it(board):
    """Assignments, milestones and notes belong to the project — left behind they are
    rows pointing at nothing, and the next report that counts them is wrong."""
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    c, db, demo, *_ = board
    conn = db.connect()
    tid = db.insert_talent(conn, Talent(name="Ada Cheng", email="ada@x.com",
                                        disciplines=[MusicDiscipline.COMPOSITION]))
    db.add_assignment(conn, demo, "Composer", tid)
    db.add_review_comment(conn, demo, author="Marta", body="Warmer strings?",
                          t_seconds=12, version="1")
    conn.close()
    c.post(f"/project/{demo}/delete")
    conn = db.connect()
    assert db.list_assignments(conn, demo) == []
    assert conn.execute("SELECT COUNT(*) c FROM review_comments WHERE project_id = ?",
                        (demo,)).fetchone()["c"] == 0
    assert db.get_talent(conn, tid) is not None, "it deleted the creator too"
    conn.close()


def test_the_deal_it_came_from_is_kept(board):
    """A project is ONE DELIVERY of a deal. Clearing the delivery must not clear the
    buyer relationship behind it."""
    c, db, *_ = board
    conn = db.connect()
    opp_id = conn.execute(
        "INSERT INTO opportunities (client, need, source) VALUES (?,?,?)",
        ("The Larkspur Trust", "Spring campaign", "manual")).lastrowid
    pid = db.insert_project(conn, opp_id, "The Larkspur Trust", "Spring spot",
                            1000, 2000, ["Composer"])
    conn.commit()
    conn.close()
    c.post(f"/project/{pid}/delete")
    conn = db.connect()
    assert db.get_project(conn, pid) is None
    assert db.get_opportunity(conn, opp_id) is not None, "it deleted the deal as well"
    conn.close()


def test_the_board_says_what_went(board):
    c, _db, demo, *_ = board
    c.post(f"/project/{demo}/delete")
    assert "Deleted Rehearsal Spot." in c.get("/projects?deleted=Rehearsal%20Spot").text


# ── and what it refuses ─────────────────────────────────────────────────────────────
def test_a_project_money_moved_on_is_refused(board):
    c, db, _demo, paid, _s, _sh = board
    conn = db.connect()
    iid = db.insert_invoice(conn, paid, None, Invoice(
        client="The Larkspur Trust", need="Sand Castle", kind="Deposit", amount=1200.0))
    conn.execute("UPDATE invoices SET status = 'Paid' WHERE id = ?", (iid,))
    conn.commit()
    assert db.project_delete_block(conn, paid) == "paid"
    conn.close()
    r = c.post(f"/project/{paid}/delete", follow_redirects=False)
    # …and carries the id/name so the override can be offered on that very row (ADR-0087).
    assert r.headers["location"].startswith("/projects?kept=paid&id=")
    conn = db.connect()
    assert db.get_project(conn, paid) is not None, "deleted anyway"
    conn.close()


def test_an_unpaid_invoice_does_not_block_it(board):
    """A draft invoice is not a record of anything. Refusing on it would make the
    refusals noise, and noise is what gets clicked through."""
    c, db, demo, *_ = board
    conn = db.connect()
    db.insert_invoice(conn, demo, None, Invoice(
        client="The Larkspur Trust", need="Rehearsal Spot", kind="Deposit", amount=900.0))
    assert db.project_delete_block(conn, demo) == ""
    conn.close()
    r = c.post(f"/project/{demo}/delete", follow_redirects=False)
    assert "deleted=" in r.headers["location"]


def test_a_project_something_was_signed_on_is_refused(board):
    """ADR-0059: signature rows are append-only, so what they cover stays."""
    from chordential_oia import signing
    c, db, _d, _p, signed, _sh = board
    conn = db.connect()
    db.record_signature(conn, signing.build_signature(
        doc_kind=signing.DOC_CLEARANCE_EXECUTED, project_id=signed,
        document_text="CLEARANCE CERTIFICATE\nChain of title.",
        signer_name="Jon Shipp", signer_email="jon@example.com",
        typed_name="Jon Shipp"))
    assert db.project_delete_block(conn, signed) == "signed"
    conn.close()
    r = c.post(f"/project/{signed}/delete", follow_redirects=False)
    assert r.headers["location"].startswith("/projects?kept=signed&id=")
    conn = db.connect()
    assert db.get_project(conn, signed) is not None
    conn.close()


def test_a_delivered_project_is_refused(board):
    c, db, _d, _p, _s, shipped = board
    conn = db.connect()
    db.update_delivery(conn, shipped, "state", "Delivered")
    assert db.project_delete_block(conn, shipped) == "delivered"
    conn.close()
    r = c.post(f"/project/{shipped}/delete", follow_redirects=False)
    assert r.headers["location"].startswith("/projects?kept=delivered&id=")
    conn = db.connect()
    assert db.get_project(conn, shipped) is not None
    conn.close()


def test_the_refusal_says_which_and_what_to_do(board):
    c, _db, *_ = board
    for why, phrase in (("paid", "A paid invoice is an accounting record"),
                        ("signed", "Signatures are a permanent record"),
                        ("delivered", "the record of work a client has in hand")):
        page = c.get(f"/projects?kept={why}").text
        assert "Not deleted." in page and phrase in page, why


def test_the_refusal_copy_lives_with_the_rule(board):
    """One derivation, many reporters. The sentence explaining a refusal sits next to
    the check that produces it — a second copy in a template is how a page ends up
    saying something the code no longer does."""
    from chordential_oia.web import db as dbm
    page = (c := board[0]).get("/projects?kept=paid").text
    assert dbm.PROJECT_DELETE_BLOCK["paid"] in page
    assert set(dbm.PROJECT_DELETE_BLOCK) == {"paid", "signed", "delivered"}
    assert "A paid invoice is an accounting record" not in \
        (open("src/chordential_oia/web/templates/projects.html", encoding="utf-8").read())


def test_a_missing_project_is_not_an_error(board):
    c, *_ = board
    r = c.post("/project/99999/delete", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/projects"


# ── the control is there to press ───────────────────────────────────────────────────
def test_every_row_offers_it(board):
    c, _db, demo, paid, signed, shipped = board
    page = c.get("/projects").text
    assert page.count('class="pj-del"') == 4, "not one control per project"
    for pid in (demo, paid, signed, shipped):
        assert f'action="/project/{pid}/delete"' in page
    assert "onsubmit=\"return confirm(" in page, "a permanent delete with no confirm"
