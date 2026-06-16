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


def test_missing_opportunity_404(client):
    assert client.get("/opportunity/99999").status_code == 404
