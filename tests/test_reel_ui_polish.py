"""UI polish pass on the reel/showreel/intro-gate feature, from a
userinterface-wiki review: tactile :active states, hover transitions, shadow
color, reduced-motion parity, and heading text-wrap — none of it changes the
underlying orbit/player/gate behavior already covered elsewhere.
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


def _css(client):
    return client.get("/static/public/site.css?v=13").text


def test_every_clickable_control_has_a_pressed_state(client):
    css = _css(client)
    for selector in (
        ".rg-card:active", ".rg-menu:active", ".sr-close:active",
        ".sr-btn:active", ".sr-tap:active", ".ig-btn:active",
    ):
        assert selector in css, f"missing :active feedback for {selector}"


def test_hover_states_ease_instead_of_snapping(client):
    css = _css(client)
    # Each hoverable control declares its own transition (not just a bare
    # color/background swap with no easing).
    assert "transition:background .15s ease,transform .15s ease" in css  # .rg-menu, .sr-close
    assert "transition:background .15s ease,transform .15s ease" in css  # .sr-btn (same pattern)
    assert "transition:background .15s ease,color .15s ease,transform .15s ease" in css  # .ig-btn


def test_showreel_respects_reduced_motion_like_the_rest_of_the_feature(client):
    # .rg-* and .ig-* already had a prefers-reduced-motion fallback; .sr-* was
    # the one gap left on this feature.
    css = _css(client)
    assert "@media (prefers-reduced-motion:reduce){" in css
    assert ".sr-video,.sr-hint,.sr-player{transition:none}" in css


def test_shadows_use_brand_ink_not_pure_black(client):
    # Scoped to the reel/showreel shadows specifically (unrelated pure-black
    # shadows elsewhere in the file, e.g. .pub-header, are out of this pass's
    # scope and untouched).
    css = _css(client)
    assert "box-shadow:0 18px 40px rgba(31,30,30,.45)" in css  # .rg-card
    assert "box-shadow:0 6px 20px rgba(31,30,30,.35)" in css   # .sr-cursor
    assert "box-shadow:0 10px 30px rgba(31,30,30,.4)" in css   # .sr-player


def test_showreel_heading_balances_its_line_breaks(client):
    css = _css(client)
    assert "text-wrap:balance" in css


def test_press_states_use_the_canonical_scale_value(client):
    # make-interfaces-feel-better: always 0.96, never below 0.95 ("feels
    # exaggerated"). .sr-close and .sr-btn had drifted to .94/.9.
    css = _css(client)
    assert "scale(.94)" not in css
    assert "scale(.9)" not in css
    for selector in (".sr-close:active", ".sr-btn:active", ".sr-tap:active", ".ig-btn:active"):
        assert f"{selector}{{transform:scale(.96)}}" in css


def test_intro_gate_choices_stagger_instead_of_moving_as_one_block(client):
    css = _css(client)
    assert "animation-delay:2.05s" in css   # .ig-btn-primary
    assert "animation-delay:2.13s" in css   # .ig-btn-ghost, ~80ms later


def test_intro_gate_word_exit_is_softer_than_its_entrance(client):
    # The entrance only slides 6px; the exit shouldn't be a louder 30% shrink.
    css = _css(client)
    assert "@keyframes ig-word-out{ to{opacity:0;transform:translateY(-6px)} }" in css
    assert "scale(.7)" not in css


def test_reel_and_showreel_pages_get_font_smoothing(client):
    # body.pub already has this; /reel and /showreel use their own standalone
    # <body> classes and never inherited it.
    css = _css(client)
    assert ".rg-body{" in css and "-webkit-font-smoothing:antialiased" in css.split(".rg-body{")[1][:120]
    assert ".sr-body{" in css and "-webkit-font-smoothing:antialiased" in css.split(".sr-body{")[1][:120]


def test_spiral_list_toggle_clears_minimum_hit_area(client):
    css = _css(client)
    assert "padding:11px 4px" in css  # .rg-toggle
