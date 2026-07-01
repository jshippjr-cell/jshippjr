"""Intro gate — "Welcome" crossfades into the Chordential mark, then a sound
choice, shown on EVERY visit to /reel and /showreel (no session-skip, per the
founder's call). The chosen button is the user gesture that unlocks audio.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c


@pytest.mark.parametrize("path", ["/reel", "/showreel"])
def test_intro_gate_present_on_every_load(client, path):
    # No session-skip mechanism — every GET renders the gate fresh.
    for _ in range(3):
        t = client.get(path).text
        assert 'data-ig-gate' in t
        assert 'data-ig-enter="sound"' in t
        assert 'data-ig-enter="muted"' in t


def test_intro_gate_uses_the_cropped_mark_icon(client):
    t = client.get("/reel").text
    assert "mark-icon.png" in t
    r = client.get("/static/public/mark-icon.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_intro_gate_dispatches_entered_event(client):
    t = client.get("/showreel").text
    assert "chordential:entered" in t
    # The sound choice is what triggers showreel playback (the user gesture).
    assert "e.detail.sound" in t


def test_intro_gate_dismisses_on_backdrop_click_and_escape(client):
    # Hardening after a real-world report: a gate that only responds to its two
    # small buttons can read as "broken" if the visitor taps elsewhere. The whole
    # gate element now carries its own click listener (defaulting to muted), plus
    # an Escape-key fallback.
    t = client.get("/reel").text
    assert "gate.addEventListener('click'" in t
    assert "e.key === 'Escape'" in t


def test_intro_gate_has_css_only_failsafe(client):
    # Even total JS failure can't permanently block the page underneath.
    # 3 minutes of no action, not a hair-trigger — a visitor reading the
    # choices shouldn't get shoved into the carousel mid-decision.
    css = client.get("/static/public/site.css?v=18").text
    assert "ig-failsafe-fade" in css
    assert "180s" in css
    assert "9s forwards" not in css
