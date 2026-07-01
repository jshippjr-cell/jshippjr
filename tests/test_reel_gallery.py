"""The Reel gallery (/reel) — falling/spiral cards, pure-CSS motion, no animation JS.

A new page (does NOT replace the converting homepage). Cards link to the showreel
(deep-linked to a track) or a case study. Spiral/list toggle is pure CSS (checkbox
hack); mobile/touch/reduced-motion fall back to a static list automatically via CSS.
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


def test_reel_renders_a_card_per_track_and_case(client):
    from chordential_oia.web.showcase import get_showcase
    show = get_showcase()
    n_tracks = len([d for d in show.demos if (d.audio_url or "").strip()])
    n_cases = len(show.cases)

    r = client.get("/reel")
    assert r.status_code == 200
    assert r.text.count('class="rg-card ') == n_tracks + n_cases


def test_reel_cards_link_to_showreel_deep_link_and_capabilities(client):
    t = client.get("/reel").text
    assert "/showreel?t=0" in t
    assert "/capabilities" in t


def test_reel_has_spiral_list_toggle(client):
    t = client.get("/reel").text
    assert 'id="rg-view-toggle"' in t
    assert "rg-toggle" in t


def test_reel_is_public_no_admin_gate(client, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "secret")
    r = client.get("/reel", follow_redirects=False)
    assert r.status_code == 200


def test_homepage_unaffected_by_the_gallery_build(client):
    # The converting homepage stays exactly what it was — /reel is additive.
    r = client.get("/")
    assert r.status_code == 200
    assert "rg-card" not in r.text


def test_showreel_honors_deep_link_track_index(client):
    t = client.get("/showreel?t=2").text
    # The starting index is threaded into the player init call.
    assert "load(i)" in t


def test_showreel_links_back_to_the_gallery(client):
    # Landing directly on /showreel (skipping /reel) shouldn't dead-end — this is
    # the exact confusion that prompted the fix: the founder typed /showreel
    # directly and expected to see the gallery cards that only exist on /reel.
    t = client.get("/showreel").text
    assert 'href="/reel"' in t


def _reel_css():
    return (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/site.css"
    ).read_text()


def test_reel_uses_real_css_3d_not_a_flattened_illusion():
    """Genuine 3D, not a 2D-rotate-plus-manual-blur fake: the stage needs a real
    perspective + preserve-3d viewing context, and each card must revolve around
    the Y AXIS via the `transform` property's own function order — rotateY()
    THEN translateZ() — which is what actually sweeps a card's depth-push around
    a circle. (The standalone `rotate`/`translate` CSS properties can't do this:
    the spec applies them in a fixed order — translate always before rotate — so
    a standalone translateZ never gets carried around by a standalone rotateY;
    every card would just spin in place instead of orbiting.)"""
    css = _reel_css()
    assert "perspective:1400px" in css
    assert "transform-style:preserve-3d" in css
    assert "@keyframes rg-orbit" in css
    assert "transform:rotateY(var(--slot-angle,0deg)) translateZ(var(--orbit-r" in css
    assert "transform:rotateY(calc(var(--slot-angle,0deg) + 180deg)) translateZ(var(--orbit-r" in css
    assert "rg-orbit var(--spin" in css  # actually applied to .rg-card


def test_reel_cards_hide_their_backface():
    """Without this, a card rotated past 90deg shows a mirrored (backwards-text)
    image of its own front face instead of turning cleanly away from the
    viewer — a real visual glitch caught by screenshotting the live orbit."""
    css = _reel_css()
    assert "backface-visibility:hidden" in css


def test_reel_cards_share_one_central_column():
    """An "orbit" only reads as orbiting a CENTRAL column if every card starts
    from the SAME base position (dead center of the stage) and is fanned out
    purely by its own --slot-angle + --orbit-r — not six independent per-card
    `left:X%` slots, which would make each card spin around its own tiny orbit
    instead of one shared axis."""
    css = _reel_css()
    assert "left:50%" in css
    assert "margin-left:-115px" in css
    assert "left:6%" not in css  # the old per-card horizontal slot is gone


def test_reel_cards_have_depth_cycle_near_far_near():
    """Scale + blur are still bundled INTO the orbit keyframe as an ADDITIONAL cue
    on top of the real geometric foreshortening — a card grows/sharpens at the
    front of its sweep and shrinks/blurs at the back."""
    css = _reel_css()
    assert "scale(var(--near" in css
    assert "scale(var(--far" in css
    assert "filter:blur(var(--fblur" in css
    # Every slot must define its own near/far/blur range and its own orbit radius.
    assert css.count("--near:") == 6
    assert css.count("--far:") == 6
    assert css.count("--slot-angle:") == 6
    assert css.count("--orbit-r:") == 6


def test_reel_fallback_resets_the_3d_properties():
    """List-mode and the mobile/touch/reduced-motion fallback must fully neutralize
    both `transform` (the orbit) and `translate` (the fall) — a bare rotate:0deg
    reset wouldn't touch either, since the orbit now lives entirely in `transform`."""
    css = _reel_css()
    assert css.count("translate:none") >= 2
    assert css.count("transform:none") >= 2
