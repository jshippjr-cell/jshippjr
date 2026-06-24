"""Inbound leads (Cycle 1.2) — public intake → internal review queue.

The precision-bias contract: a public submission becomes a *lead*, never an
opportunity, until a human explicitly promotes it.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def _opp_count(db_mod):
    conn = db_mod.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
    finally:
        conn.close()


def _lead_count(db_mod):
    conn = db_mod.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM inbound_leads").fetchone()[0]
    finally:
        conn.close()


def test_intake_forms_render(ctx):
    client, _ = ctx
    assert client.get("/start").status_code == 200
    assert client.get("/book").status_code == 200


def test_questionnaire_creates_lead_not_opportunity(ctx):
    client, db_mod = ctx
    before_opps = _opp_count(db_mod)
    before_leads = _lead_count(db_mod)
    r = client.post(
        "/start",
        data={
            "contact_name": "Dana Rivera", "contact_email": "dana@acme.com",
            "phone": "555-0101",
            "company": "Acme Co", "project_type": ":30 brand spot",
            "description": "Warm, hopeful, orchestral.", "budget_text": "around $6k",
            "timeline": "4 weeks",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Redirects to the thank-you page (may carry an indicative price band).
    assert r.headers["location"].startswith("/thanks?kind=project")
    # A lead was created; NO opportunity entered the pipeline.
    assert _lead_count(db_mod) == before_leads + 1
    assert _opp_count(db_mod) == before_opps


def test_book_call_creates_lead_with_source(ctx):
    client, db_mod = ctx
    r = client.post(
        "/book",
        data={"contact_name": "Lee Park", "contact_email": "lee@studio.tv",
              "phone": "555-0102",
              "description": "Title sequence sound design."},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/thanks?kind=call"
    conn = db_mod.connect()
    try:
        row = conn.execute(
            "SELECT * FROM inbound_leads WHERE contact_name = 'Lee Park'"
        ).fetchone()
    finally:
        conn.close()
    assert row["source"] == "book_call"
    assert row["status"] == "New"


def test_lead_appears_in_internal_queue(ctx):
    client, _ = ctx
    client.post("/start", data={"contact_name": "Mara Voss", "company": "Voss Films",
                                "contact_email": "mara@vossfilms.com", "phone": "555-0103"})
    q = client.get("/leads")
    assert q.status_code == 200
    assert "Mara Voss" in q.text
    assert "Voss Films" in q.text


def test_promote_creates_exactly_one_opportunity_and_links(ctx):
    client, db_mod = ctx
    client.post(
        "/start",
        data={"contact_name": "Sam Cole", "company": "Cole Brands",
              "contact_email": "sam@colebrands.com", "phone": "555-0104",
              "project_type": "Sonic logo", "description": "Three-note mnemonic."},
    )
    conn = db_mod.connect()
    lead_id = conn.execute(
        "SELECT id FROM inbound_leads WHERE company='Cole Brands'"
    ).fetchone()[0]
    conn.close()

    before = _opp_count(db_mod)
    r = client.post(f"/leads/{lead_id}/promote", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/opportunity/")
    assert _opp_count(db_mod) == before + 1

    conn = db_mod.connect()
    try:
        lead = conn.execute(
            "SELECT * FROM inbound_leads WHERE id=?", (lead_id,)
        ).fetchone()
        opp = conn.execute(
            "SELECT * FROM opportunities WHERE id=?", (lead["linked_opp_id"],)
        ).fetchone()
    finally:
        conn.close()
    assert lead["status"] == "Qualified"
    assert lead["linked_opp_id"] is not None
    assert opp["client"] == "Cole Brands"
    assert opp["need"] == "Sonic logo"
    assert opp["source"] == "front_of_house"


def test_promote_is_idempotent(ctx):
    client, db_mod = ctx
    client.post("/start", data={"contact_name": "Pat Vue", "company": "Vue Co",
                                "contact_email": "pat@vue.co", "phone": "555-0105"})
    conn = db_mod.connect()
    lead_id = conn.execute(
        "SELECT id FROM inbound_leads WHERE company='Vue Co'"
    ).fetchone()[0]
    conn.close()
    client.post(f"/leads/{lead_id}/promote")
    after_first = _opp_count(db_mod)
    # Promoting again must not create a second opportunity.
    client.post(f"/leads/{lead_id}/promote")
    assert _opp_count(db_mod) == after_first


def test_dismiss_sets_status(ctx):
    client, db_mod = ctx
    client.post("/start", data={"contact_name": "Nat Kim", "company": "Kim LLC",
                                "contact_email": "nat@kim.llc", "phone": "555-0106"})
    conn = db_mod.connect()
    lead_id = conn.execute(
        "SELECT id FROM inbound_leads WHERE company='Kim LLC'"
    ).fetchone()[0]
    conn.close()
    client.post(f"/leads/{lead_id}/status", data={"status": "Dismissed"})
    conn = db_mod.connect()
    try:
        status = conn.execute(
            "SELECT status FROM inbound_leads WHERE id=?", (lead_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "Dismissed"
