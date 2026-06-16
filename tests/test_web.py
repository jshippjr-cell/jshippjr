"""Smoke + behavior tests for the dashboard (FastAPI TestClient)."""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isolate the DB per test run.
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:  # triggers lifespan seeding
        yield c


def test_dashboard_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Executive Summary" in r.text
    assert "Win rate" in r.text


def test_inbox_and_search(client):
    assert client.get("/inbox").status_code == 200
    r = client.get("/inbox", params={"action": "Pursue"})
    assert r.status_code == 200
    # Search narrows results without erroring.
    assert client.get("/inbox", params={"q": "campaign"}).status_code == 200


def test_lanes_render(client):
    r = client.get("/lanes")
    assert r.status_code == 200
    for lane in ("Pursue", "Review", "Pass"):
        assert lane in r.text


def test_detail_and_subpages(client):
    # First opportunity id should exist after seeding.
    r = client.get("/opportunity/1")
    assert r.status_code == 200
    assert client.get("/opportunity/1/qualification").status_code == 200
    assert client.get("/opportunity/1/estimate").status_code == 200
    # Estimate page surfaces the Phase-1 honesty banner.
    assert "Phase 1" in client.get("/opportunity/1/estimate").text


def test_win_loss_tracking_updates_metrics(client):
    # Mark an opportunity Won with a value, then confirm it shows on the dashboard.
    r = client.post(
        "/opportunity/1/status",
        data={"status": "Won", "outcome_value": "9000"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    dash = client.get("/").text
    assert "$9,000" in dash  # won value rendered


def test_notes_persist(client):
    client.post("/opportunity/2/notes", data={"notes": "Call the EP Monday"},
                follow_redirects=True)
    assert "Call the EP Monday" in client.get("/opportunity/2").text


def test_buyer_profile(client):
    detail = client.get("/opportunity/1")
    assert detail.status_code == 200
    # The buyer link is reachable.
    r = client.get("/buyer/Acme%20Marketing%20(agency)")
    assert r.status_code in (200, 404)  # depends on seed naming; must not 500


def test_buyer_profile_shows_strategic_standing(client):
    import re
    detail = client.get("/opportunity/1").text
    m = re.search(r'href="(/buyer/[^"]+)"', detail)
    assert m, "buyer link not found on detail page"
    page = client.get(m.group(1)).text
    assert "Strategic value" in page  # CMO buyer-value KPI present
    # Header shows a buyer relationship value chip (one of the BuyerValue labels).
    assert any(lbl in page for lbl in
               ("One-time project", "Repeat buyer", "Enterprise buyer", "Unknown"))


def test_missing_opportunity_404(client):
    assert client.get("/opportunity/99999").status_code == 404


def test_outreach_page_and_text(client):
    r = client.get("/opportunity/1/outreach")
    assert r.status_code == 200
    assert "Recommended cadence" in r.text
    txt = client.get("/opportunity/1/outreach.txt")
    assert txt.status_code == 200
    assert "OUTREACH PLAN" in txt.text


def test_outreach_contact_and_followup_persist(client):
    r = client.post(
        "/opportunity/1/outreach",
        data={
            "contact_name": "Dana Reyes",
            "contact_email": "dana@acme.com",
            "contact_role": "Creative Director",
            "next_action": "Send intro email + reel",
            "next_action_due": "2020-01-01",  # in the past -> due now
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    page = client.get("/opportunity/1/outreach").text
    assert "Dana Reyes" in page
    assert "dana@acme.com" in page
    # A past-due next action surfaces on the dashboard follow-up queue.
    dash = client.get("/").text
    assert "Follow-ups due" in dash
    assert "Send intro email + reel" in dash


def test_outreach_event_logs_and_stamps_contact(client):
    client.post(
        "/opportunity/2/outreach/event",
        data={"channel": "Email", "direction": "Sent", "note": "Sent intro + reel"},
        follow_redirects=True,
    )
    page = client.get("/opportunity/2/outreach").text
    assert "Sent intro + reel" in page
    assert "Last contacted" in page  # last_contacted stamped


def test_outreach_event_ignores_empty_note(client):
    client.post(
        "/opportunity/3/outreach/event",
        data={"channel": "Email", "direction": "Sent", "note": "   "},
        follow_redirects=True,
    )
    page = client.get("/opportunity/3/outreach").text
    assert "No touches logged yet" in page


def test_old_database_migrates_without_data_loss(tmp_path, monkeypatch):
    """An old-shape chordential.db (no outreach columns) must migrate cleanly."""
    import sqlite3

    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        """CREATE TABLE opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client TEXT NOT NULL, need TEXT NOT NULL, status TEXT DEFAULT 'New'
        )"""
    )
    conn.execute("INSERT INTO opportunities (client, need) VALUES ('Legacy Co','Old need')")
    conn.commit()
    conn.close()

    monkeypatch.setenv("CHORDENTIAL_DB", str(db_file))
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)  # should ALTER in the new columns + events table
    # Pre-existing row survives and gains the new (NULL) outreach fields.
    row = conn.execute("SELECT * FROM opportunities WHERE client='Legacy Co'").fetchone()
    assert row["need"] == "Old need"
    assert "next_action_due" in row.keys()
    db_mod.update_outreach(conn, row["id"], next_action="Call", next_action_due="2020-01-01")
    db_mod.add_outreach_event(conn, row["id"], "Email", "Sent", "hello")
    assert len(db_mod.list_outreach_events(conn, row["id"])) == 1
    conn.close()


def test_strategic_value_on_detail_and_sort(client):
    # Detail page surfaces the CMO Strategic-Value lens.
    detail = client.get("/opportunity/1").text
    assert "Strategic value" in detail
    # Inbox can sort by strategic value without erroring.
    assert client.get("/inbox", params={"order_by": "strategic"}).status_code == 200


def test_set_strategic_inputs_recomputes(client):
    # Marking a buyer as enterprise + marquee should raise its strategic standing.
    r = client.post(
        "/opportunity/1/strategic",
        data={"buyer_value": "enterprise", "marquee": "on"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Enterprise buyer" in r.text  # selected option reflected back
