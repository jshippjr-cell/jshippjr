"""The Living-OS layer (bible: "Living OS principle"): every page carries at
least one living element that can't exist in print, implemented honestly —
the machine beacon breathes only when the autonomous engines are actually on,
and live.js is a progressive enhancement every page loads."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c


def test_live_js_is_served_and_loaded_on_every_app_page(client):
    assert client.get("/static/live.js").status_code == 200
    page = client.get("/dashboard").text
    assert "/static/live.js" in page


def test_machine_beacon_is_honest_about_engine_state(client, monkeypatch):
    # engines off (default in tests) → the beacon must NOT claim the machine runs
    monkeypatch.delenv("CHORDENTIAL_AUTONOMOUS", raising=False)
    page = client.get("/dashboard").text
    assert "machine idle" in page and 'machine-beacon off' in page
    # engines on → it breathes
    monkeypatch.setenv("CHORDENTIAL_AUTONOMOUS", "1")
    page = client.get("/dashboard").text
    assert "machine running" in page and 'machine-beacon off' not in page


def test_living_grammar_present_in_stylesheet(client):
    css = client.get("/static/style.css").text
    for cls in (".machine-beacon", ".lv-veil", ".lv-halo", "lv-breathe"):
        assert cls in css
    # reduced-motion dignity is mandatory for the living layer
    assert "prefers-reduced-motion" in css


def test_update_intelligence_carries_the_honest_thinking_hooks(client):
    """Phase 2: the CI analyze form is marked for the thinking veil, its path
    names the real modules, the fit%% is machine-readable for the count-up —
    and the no-JS path (a plain form post) stays fully intact."""
    page = client.get("/opportunity/1").text
    assert "data-think" in page
    assert "Campaign Intelligence|Qualification|Buyer Profile" in page
    assert 'data-fit-pct="' in page
    # the plain form action is unchanged — progressive enhancement only
    assert 'action="/opportunity/1/intelligence/analyze"' in page
    # the real POST still works without any JS
    r = client.post("/opportunity/1/intelligence/analyze",
                    data={"stance": "objective", "lane": "meeting_notes",
                          "text": "Budget is $18,000. Need it by November."},
                    follow_redirects=False)
    assert r.status_code == 303
