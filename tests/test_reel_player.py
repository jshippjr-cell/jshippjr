"""The Reel's inline audio player: clicking a track card pops it forward,
highlights it, and plays that track through a docked player (styling reused
from /showreel) instead of navigating away. Case-study cards are unaffected
— they still navigate to /capabilities.
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


def _reel_css():
    return (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/site.css"
    ).read_text()


def _carousel_js():
    return (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/reel-carousel.js"
    ).read_text()


def test_reel_cards_are_bigger(client):
    css = _reel_css()
    assert "width:320px;height:210px" in css
    assert "width:230px;height:150px" not in css


def test_track_cards_carry_audio_url_case_cards_dont(client):
    from chordential_oia.web.showcase import get_showcase
    show = get_showcase()
    n_tracks = len([d for d in show.demos if (d.audio_url or "").strip()])

    t = client.get("/reel").text
    assert t.count("data-audio-url=") == n_tracks
    # Case cards still exist and still link to /capabilities.
    assert 'data-title="' in t
    assert "/capabilities" in t


def test_reel_has_a_docked_player_reusing_showreel_styling(client):
    t = client.get("/reel").text
    assert 'class="sr-player" data-rg-player' in t
    assert '<audio data-rg-audio preload="none" loop></audio>' in t
    assert "data-rg-toggle" in t
    assert "data-rg-prev" in t
    assert "data-rg-next" in t
    assert "data-rg-title" in t
    assert "data-rg-scrub" in t
    assert 'class="sr-icon sr-icon-play"' in t
    assert 'class="sr-icon sr-icon-pause"' in t


def test_player_is_pinned_to_the_viewport_not_the_perspective_stage(client):
    """.sr-player sits at body level here (outside .rg-stage, which has
    `perspective` set and would otherwise become the containing block for a
    fixed-position descendant — the same rule `transform` follows)."""
    css = _reel_css()
    assert ".rg-body .sr-player{position:fixed}" in css


def test_active_card_pops_forward_and_others_dim(client):
    css = _reel_css()
    assert ".rg-card.rg-active{" in css
    assert "translateZ(calc(var(--radius,300px) + 180px)) scale(1.16)" in css
    assert (
        ".rg-drum.rg-has-active .rg-card:not(.rg-active){\n"
        "  filter:brightness(.55) saturate(.7);\n"
        "  transform:rotateY(var(--slot-angle,0deg)) translateZ(var(--radius,300px)) scale(.82)}"
        in css
    )


def test_list_mode_clears_the_dimming_and_shrinking_even_with_an_active_card(client):
    """The dimming/shrinking rule has the SAME CSS specificity as a plain
    `filter:none;transform:none` reset, so list mode needs its own
    exact-shape override or a dimmed+shrunk card would stay that way forever
    once .rg-has-active is set (that class isn't cleared by the JS-free view
    toggle)."""
    css = _reel_css()
    assert (
        ".rg-view-input:checked ~ .rg-stage .rg-drum.rg-has-active .rg-card:not(.rg-active)"
        "{filter:none;transform:none}" in css
    )


def test_carousel_js_spins_the_clicked_track_to_face_front(client):
    js = _carousel_js()
    assert "function angleToFront(slotAngle)" in js
    assert "function spinToFront(card)" in js
    assert "function setActiveCard(card)" in js


def test_carousel_js_case_cards_still_navigate_normally(client):
    js = _carousel_js()
    assert "if (!card.dataset.audioUrl) return;" in js


def test_carousel_js_defaults_to_the_first_track_looping_on_sound_entry(client):
    """The entrance track is whichever track card is first in DOM order
    (tracks are appended before cases in public.py), which is already
    "Strings Arrangement for a Holiday Spot" — verified in practice, not
    hardcoded by title text here (that would break if the demo catalog
    ever gets reordered). It loads with reveal=false: it loops quietly in
    the background — no card pops, no docked player appears — until the
    visitor actually clicks a card themselves."""
    js = _carousel_js()
    assert "chordential:entered" in js
    assert "loadTrack(trackCards[0], true, false);" in js


def test_ambient_entrance_track_does_not_reveal_the_player_or_pop_a_card(client):
    js = _carousel_js()
    assert "function loadTrack(card, autoplay, reveal)" in js
    assert "if (reveal !== false) {" in js


def test_default_entrance_track_is_the_strings_arrangement_track(client):
    from chordential_oia.web.showcase import get_showcase
    show = get_showcase()
    tracks = [d for d in show.demos if (d.audio_url or "").strip()]
    assert tracks[0].title == "Strings Arrangement for a Holiday Spot"


def test_reel_audio_element_loops(client):
    t = client.get("/reel").text
    assert '<audio data-rg-audio preload="none" loop></audio>' in t
