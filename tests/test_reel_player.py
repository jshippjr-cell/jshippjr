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
        "  transform:rotateY(var(--slot-angle,0deg)) translateZ(var(--radius,300px)) scale(.82)\n"
        "    rotateX(var(--tilt-x,0deg)) rotateY(var(--tilt-y,0deg))}"
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


# --------------------------------------------------------------------------- #
# Clicking the active card a SECOND time closes it back down — un-pops it,
# hides the player, and resumes the default entrance track quietly, instead
# of just pausing in place.
# --------------------------------------------------------------------------- #

def test_clicking_the_active_card_again_calls_deactivate_not_toggle_play_pause(client):
    js = _carousel_js()
    assert "if (card === activeCard) deactivate();" in js
    assert "if (card === activeCard) togglePlayPause();" not in js


def test_deactivate_unpops_the_card_hides_the_player_and_resumes_the_default_track(client):
    js = _carousel_js()
    assert "function deactivate() {" in js
    body = js.split("function deactivate() {", 1)[1].split("\n  }", 1)[0]
    assert 'activeCard.classList.remove("rg-active")' in body
    assert 'drum.classList.remove("rg-has-active")' in body
    assert 'player.classList.remove("on")' in body
    assert "loadTrack(trackCards[0], true, false)" in body


# --------------------------------------------------------------------------- #
# Holographic tilt: each card tips toward the cursor and shows a cursor-
# tracked sheen, on real pointer devices only, and never fights the drag.
# --------------------------------------------------------------------------- #

def test_cards_carry_tilt_and_shine_custom_properties_in_every_transform_state(client):
    css = _reel_css()
    assert "rotateX(var(--tilt-x,0deg)) rotateY(var(--tilt-y,0deg))" in css
    # Base slot placement, the active pop, AND the dimmed/shrunk state must
    # all include the tilt terms — whichever one currently applies to a card.
    assert css.count("rotateX(var(--tilt-x,0deg)) rotateY(var(--tilt-y,0deg))") >= 3
    assert ".rg-card-shine{" in css
    assert "radial-gradient(circle at var(--hx,50%) var(--hy,50%)" in css


def test_tilt_transition_is_faster_than_the_base_transform_transition(client):
    """The base .5s transition would make the continuous mousemove-driven
    tilt visibly lag behind the cursor, chasing a moving target. JS toggles
    a class for a much shorter transition only while actively tracking."""
    css = _reel_css()
    assert ".rg-card.rg-tilting{transition:transform .12s ease-out" in css


def test_reel_card_template_includes_the_shine_overlay(client):
    t = client.get("/reel").text
    assert 'class="rg-card-shine"' in t


def test_tilt_is_gated_to_real_pointer_devices(client):
    js = _carousel_js()
    assert 'var isDesktop = window.matchMedia("(hover: hover) and (pointer: fine)").matches;' in js
    assert "if (isDesktop) {" in js


def test_tilt_and_drag_are_mutually_exclusive_by_device_capability(client):
    """Tilt (desktop-only, mouse-driven) and drag (touch-only) never run at
    the same time on the same device — isDesktop picks exactly one
    interaction model, so there's no runtime state needed to keep them from
    fighting each other."""
    js = _carousel_js()
    assert "drum.addEventListener(\"pointerdown\", onDown);" in js
    # The pointerdown attach (drag) and the tilt attach are each gated by
    # isDesktop in opposite directions.
    drag_attach = js.split('drum.addEventListener("pointerdown", onDown);', 1)[0]
    assert "if (isDesktop) {" in drag_attach
    assert "} else {" in js


def test_mouseleave_resets_tilt_to_neutral(client):
    js = _carousel_js()
    assert 'card.addEventListener("mouseleave", resetAllTilts);' in js


# --------------------------------------------------------------------------- #
# Desktop: the carousel spins on its own instead of being drag-driven, and
# scrolling gives it a temporary speed boost. Touch keeps drag exactly as
# before (verified separately in test_reel_gallery.py's drag-fix tests).
# --------------------------------------------------------------------------- #

def test_desktop_auto_rotates_and_scroll_boosts_the_rate(client):
    js = _carousel_js()
    assert "function autoRotateStep(t) {" in js
    assert "function startAutoRotate() {" in js
    assert "function stopAutoRotate() {" in js
    assert 'drum.addEventListener("wheel", function (e) {' in js
    assert "boost += Math.min(Math.abs(e.deltaY), 120) * 0.6;" in js


def test_auto_rotate_starts_immediately_on_desktop_and_never_on_touch(client):
    js = _carousel_js()
    assert "if (isDesktop) {\n    startAutoRotate();" in js


def test_auto_rotate_respects_reduced_motion(client):
    js = _carousel_js()
    body = js.split("function startAutoRotate() {", 1)[1].split("\n  }", 1)[0]
    assert "if (autoRotateId || reduceMotion) return;" in body


def test_popping_a_card_pauses_ambient_motion_deactivating_resumes_it_on_desktop(client):
    js = _carousel_js()
    assert "function pauseAmbientMotion() {" in js
    body = js.split("function pauseAmbientMotion() {", 1)[1].split("\n  }", 1)[0]
    assert "stopMomentum();" in body
    assert "stopAutoRotate();" in body
    assert "pauseAmbientMotion();" in js.split("function spinToFront(card) {", 1)[1].split("\n  }", 1)[0]
    assert "if (isDesktop) startAutoRotate();" in js.split("function deactivate() {", 1)[1].split("\n  }", 1)[0]


def test_desktop_hint_says_scroll_not_drag(client):
    t = client.get("/reel").text
    assert 'class="rg-hint rg-hint-desktop"' in t
    assert "Scroll to spin faster" in t
    assert 'class="rg-hint rg-hint-touch"' in t
    assert "Drag to look around" in t


def test_hint_variants_are_gated_by_device_capability_not_screen_width(client):
    css = _reel_css()
    assert ".rg-hint-touch{display:none}" in css
    assert "@media (hover:none),(pointer:coarse){" in css


# --------------------------------------------------------------------------- #
# Mobile drag "shake": the browser's own native vertical-pan handling was
# coexisting with our JS's horizontal rotation on the same touch gesture —
# touch-action:none claims the whole gesture for JS so only one system
# drives motion during a touch-drag.
# --------------------------------------------------------------------------- #

def test_drum_claims_the_full_touch_gesture_no_competing_native_pan(client):
    css = _reel_css()
    assert "touch-action:none" in css
    assert "touch-action:pan-y" not in css
