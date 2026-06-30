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


def test_reel_cards_genuinely_orbit_not_just_fall():
    """The motion must SWEEP through an angle (orbit around an offset pivot), not
    just sit at a fixed tilt while falling straight down — that was the reported
    gap ("falling instead of rotating in a spiral")."""
    css_path = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/site.css"
    )
    css = css_path.read_text()
    # An animated full-circle orbit keyframe must exist...
    assert "@keyframes rg-orbit" in css
    assert "rotate:360deg" in css or "rotate: 360deg" in css
    # ...and the card's transform-origin must be offset OUTSIDE itself (not 50% 50%)
    # — a card spinning around its own center never visibly orbits/displaces.
    assert "transform-origin:50% var(--orbit" in css
    # The orbit animation must actually be applied to .rg-card, not just defined.
    assert "rg-orbit var(--spin" in css


def test_reel_cards_have_depth_cycle_near_far_near():
    """Scale + blur must be bundled INTO the same orbit keyframe (not static
    per-card values) so a card visibly grows/sharpens at the front of its sweep
    and shrinks/blurs at the back — that's what makes depth actually READ as the
    cards move, answering "you should be able to see the cards in the foreground
    and background"."""
    css_path = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/site.css"
    )
    css = css_path.read_text()
    assert "scale:var(--near" in css
    assert "scale:var(--far" in css
    assert "filter:blur(var(--fblur" in css
    # Every slot must define its own near/far/blur range.
    assert css.count("--near:") == 6
    assert css.count("--far:") == 6
