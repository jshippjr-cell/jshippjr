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
    return client.get("/static/public/site.css?v=12").text


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
