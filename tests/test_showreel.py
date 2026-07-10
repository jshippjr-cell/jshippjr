"""Showreel page — the immersive cursor-follow + docked-player stage.

A public, full-bleed page: hero video background, a cursor-following "play" label,
and the cleared capability tracks playing in a docked player. Vanilla, no deps.
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


def test_showreel_renders(client):
    r = client.get("/showreel")
    assert r.status_code == 200
    t = r.text
    # The immersive stage + signature interaction hooks.
    assert "data-cursor-stage" in t
    assert "sr-cursor" in t            # the cursor-following pill
    assert "data-sr-player" in t       # the docked player
    assert "sr-tap" in t               # the touch fallback button


def test_showreel_features_real_cleared_tracks(client):
    t = client.get("/showreel").text
    # Real Cloudinary capability tracks are embedded for the player (not placeholders).
    assert "SR_TRACKS" in t
    assert "res.cloudinary.com" in t and ".mp3" in t


def test_showreel_uses_hero_video_background(client):
    t = client.get("/showreel").text
    assert "sr-video" in t
    # The hero footage is the stage background (reused, per the plan).
    assert "herospliced" in t


def test_public_css_cachebuster_comes_from_one_source(client):
    """The site.css ?v= buster is a single template global (asset_v), not hardcoded
    per template — a bump used to require editing 4 files, and once didn't, serving
    stale CSS. Every public page that uses site.css must render the resolved value.

    The homepage (``/`` → experience.html) is a self-contained immersive page with its
    own inline styles and deliberately does NOT link site.css, so it's excluded here."""
    from chordential_oia.web.public import ASSET_VERSION
    for path in ("/showreel", "/stills"):
        t = client.get(path).text
        assert f"site.css?v={ASSET_VERSION}" in t
        assert "{{ asset_v }}" not in t     # the global actually resolved


def test_cursor_label_script_is_served(client):
    r = client.get("/static/public/cursor-label.js")
    assert r.status_code == 200
    assert "data-cursor" in r.text     # the contextual-label mechanism


def test_showreel_is_public_no_admin_gate(client, monkeypatch):
    # Public marketing surface: reachable even with the admin gate enabled.
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "secret")
    r = client.get("/showreel", follow_redirects=False)
    assert r.status_code == 200
