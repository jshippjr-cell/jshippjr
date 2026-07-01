"""Stills (/stills) — the editorial alternative to /reel's orbiting carousel:
same tracks + case studies, presented as a scroll-tilted grid instead. Pure
CSS transform/filter driven by a small vanilla-JS scroll engine
(scroll-tilted-grid.js); no framework, no external images.
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


def test_stills_renders_a_tile_per_track_and_case(client):
    from chordential_oia.web.showcase import get_showcase
    show = get_showcase()
    n_tracks = len([d for d in show.demos if (d.audio_url or "").strip()])
    n_cases = len(show.cases)

    r = client.get("/stills")
    assert r.status_code == 200
    assert r.text.count('class="stl-tile"') == n_tracks + n_cases


def test_stills_tiles_link_to_showreel_deep_link_and_capabilities(client):
    t = client.get("/stills").text
    assert "/showreel?t=0" in t
    assert "/capabilities" in t


def test_stills_reuses_the_reel_gradient_tiles_no_new_imagery(client):
    # Same gradient classes as /reel — no external stock photos, no new
    # image assets, no guessed/fabricated URLs.
    t = client.get("/stills").text
    assert "rg-wine-orange" in t or "rg-slate-sand" in t
    assert "pinimg.com" not in t
    assert "unsplash.com" not in t


def test_stills_is_public_no_admin_gate(client, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "secret")
    r = client.get("/stills", follow_redirects=False)
    assert r.status_code == 200


def test_stills_loads_the_scroll_engine_script(client):
    t = client.get("/stills").text
    assert '<script src="/static/public/scroll-tilted-grid.js"></script>' in t
    r = client.get("/static/public/scroll-tilted-grid.js")
    assert r.status_code == 200
    assert "IntersectionObserver" in r.text


def test_homepage_unaffected_by_the_stills_build(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "stl-tile" not in r.text


def _site_css():
    return (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/site.css"
    ).read_text()


def test_stills_grid_has_a_static_fallback_for_touch_reduced_motion_narrow(client):
    css = _site_css()
    assert "(hover:none),(prefers-reduced-motion:reduce),(max-width:640px)" in css
    assert ".stl-frame{transform:none;filter:none" in css


def test_scroll_engine_bails_out_early_for_reduced_motion_and_touch(client):
    r = client.get("/static/public/scroll-tilted-grid.js")
    js = r.text
    assert "prefers-reduced-motion: reduce" in js
    assert "hover: none" in js
    assert "if (reduce || coarse) return;" in js
