"""The Reel gallery (/reel) — a user-draggable 3D carousel drum (pure CSS 3D +
a small vanilla-JS drag/momentum engine, no framework). Cards link to the
showreel (deep-linked to a track) or a case study. Carousel/list toggle is
pure CSS (checkbox hack); reduced motion drops only the release-momentum
spin (the drag itself is direct, user-driven motion); a narrow screen falls
back to a static list via CSS.
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


def test_reel_has_carousel_list_toggle(client):
    t = client.get("/reel").text
    assert 'id="rg-view-toggle"' in t
    assert "rg-toggle" in t
    assert "carousel" in t  # the renamed label — it's a drum, not a spiral now
    assert "list" in t


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


def test_reel_cards_get_evenly_spaced_slot_angles(client):
    # Server-computed at render time (not nth-child CSS) so it's correct for
    # however many tracks/cases actually exist, not a hardcoded card count.
    from chordential_oia.web.showcase import get_showcase
    show = get_showcase()
    n = len([d for d in show.demos if (d.audio_url or "").strip()]) + len(show.cases)

    t = client.get("/reel").text
    assert "--slot-angle:0.0deg" in t or "--slot-angle:0deg" in t
    expected_second = 360 / n
    assert f"--slot-angle:{expected_second}deg" in t


def test_reel_loads_the_drag_carousel_engine(client):
    t = client.get("/reel").text
    assert '<script src="/static/public/reel-carousel.js"></script>' in t
    assert 'id="rg-drum"' in t
    r = client.get("/static/public/reel-carousel.js")
    assert r.status_code == 200
    assert "pointerdown" in r.text


def _reel_css():
    return (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/site.css"
    ).read_text()


def test_reel_uses_real_css_3d_not_a_flattened_illusion():
    """Genuine 3D, not a 2D-rotate-plus-manual-blur fake: the stage needs a real
    perspective + preserve-3d viewing context, and each card sits via the
    `transform` property's own function order — rotateY() THEN translateZ() —
    which is what actually places a card's depth-push around a circle rather
    than spinning it in place. The drum (not each card) is what the drag
    engine rotates, sweeping every card around together."""
    css = _reel_css()
    assert "perspective:1400px" in css
    assert "transform-style:preserve-3d" in css
    assert "transform:rotateY(var(--slot-angle,0deg)) translateZ(var(--radius" in css
    assert ".rg-drum{" in css


def test_reel_cards_hide_their_backface():
    """Without this, a card rotated past 90deg shows a mirrored (backwards-text)
    image of its own front face instead of turning cleanly away from the
    viewer — a real visual glitch caught by screenshotting the live orbit."""
    css = _reel_css()
    assert "backface-visibility:hidden" in css


def test_reel_drum_radius_is_computed_from_measured_card_width_not_hardcoded():
    """The old build hand-tuned a fixed --orbit-r per card via nth-child. The
    drag carousel instead measures the actual card width at load and derives
    one shared radius from the "N tiles around a circle" formula, so it still
    looks right whatever the number of tracks/cases happens to be."""
    js = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/reel-carousel.js"
    ).read_text()
    assert "getBoundingClientRect" in js
    assert "Math.tan(Math.PI / n)" in js
    assert "--radius" in js


def test_reel_fallback_resets_the_3d_properties():
    """List-mode and the narrow-screen fallback must fully neutralize the
    card's own `transform` (its fixed drum slot)."""
    css = _reel_css()
    assert css.count("transform:none") >= 2


def test_reel_carousel_stays_interactive_on_touch():
    """A draggable carousel is naturally suited to touch (drag/swipe is a
    primary touch gesture) — unlike the old auto-spinning orbit, touch
    devices should NOT be forced into the static list fallback. Only a
    narrow viewport (max-width) still falls back."""
    css = _reel_css()
    assert "@media (max-width:640px){" in css
    assert "@media (hover:none),(prefers-reduced-motion:reduce),(max-width:760px){" not in css


def test_drag_past_threshold_suppresses_the_card_click():
    js = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/reel-carousel.js"
    ).read_text()
    assert "moved > 6" in js
    assert "e.preventDefault()" in js


def test_reduced_motion_drops_only_the_release_momentum_not_the_live_drag():
    js = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/reel-carousel.js"
    ).read_text()
    assert "prefers-reduced-motion: reduce" in js
    assert "if (!reduceMotion && Math.abs(velocity) > 0.05) momentumStep();" in js


def test_carousel_avoids_setpointercapture_which_swallows_real_clicks():
    """Confirmed live via Playwright: capturing the pointer on the drum
    redirects pointerup's target to the drum <div>, and the click event
    synthesized right after inherits that same wrong target — so every
    non-drag click on a card silently landed on the drum instead of the
    card <a>, and never navigated. Plain window-level move/up listeners
    (attached only while dragging) avoid the pitfall entirely."""
    js = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/reel-carousel.js"
    ).read_text()
    assert "drum.setPointerCapture(" not in js
    assert 'window.addEventListener("pointermove", onMove)' in js
    assert 'window.addEventListener("pointerup", onUp)' in js


def test_list_mode_hides_the_drag_hint(client):
    """A sibling combinator only reaches direct siblings — .rg-hint lives
    INSIDE .rg-stage, not as its own sibling of the checkbox, so
    `.rg-view-input:checked ~ .rg-hint` silently never matched. Caught by
    screenshotting list mode and seeing the hint still showing underneath
    the static grid where dragging no longer applies."""
    css = _reel_css()
    assert ".rg-view-input:checked ~ .rg-stage .rg-hint{display:none}" in css
