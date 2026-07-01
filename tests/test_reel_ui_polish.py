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
    return client.get("/static/public/site.css?v=21").text


def test_every_clickable_control_has_a_pressed_state(client):
    css = _css(client)
    for selector in (
        ".rg-card:active", ".rg-menu:active", ".sr-close:active",
        ".sr-btn:active", ".sr-tap:active", ".ig-btn:active",
    ):
        assert selector in css, f"missing :active feedback for {selector}"


def test_hover_states_ease_instead_of_snapping(client):
    css = _css(client)
    # Press feedback (:active, transform-only) still eases on its own element.
    assert "transition:transform .15s ease" in css
    assert "transition:color .15s ease,transform .15s ease" in css  # .ig-btn


def test_showreel_respects_reduced_motion_like_the_rest_of_the_feature(client):
    # .rg-* and .ig-* already had a prefers-reduced-motion fallback; .sr-* was
    # the one gap left on this feature. Refined further in the review-animations
    # pass: reduced motion means gentler, not zero — .sr-video/.sr-hint only
    # ever transition opacity (no movement), so they're left alone entirely;
    # only .sr-player's transform-driven slide-up gets neutralized.
    css = _css(client)
    assert "@media (prefers-reduced-motion:reduce){" in css
    assert ".sr-player{transition:opacity .3s ease}" in css
    assert ".sr-video,.sr-hint,.sr-player{transition:none}" not in css


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
    assert ":active{transform:scale(.94)}" not in css
    assert ":active{transform:scale(.9)}" not in css
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


# --------------------------------------------------------------------------- #
# review-animations follow-up pass — these were reviewed and reported earlier
# but not actually applied until this round.
# --------------------------------------------------------------------------- #

def test_hover_motion_is_gated_to_real_pointers(client):
    # Ungated :hover leaves a tap "stuck" in its hovered state on touch, with
    # no way to un-hover — an explicit escalation trigger in the review. Each
    # gated rule must appear (anywhere) inside a hover-capable media block,
    # and the OLD ungated form of each must be gone.
    css = _css(client)
    for gated_rule, old_ungated in (
        (".rg-card:hover::after{opacity:.38}", ".rg-card:hover::after{background:rgba(0,0,0,.38)}"),
        (".rg-menu:hover::before{opacity:1}", ".rg-menu:hover{background:rgba(255,255,255,.16)}"),
        (".sr-close:hover::before{opacity:1}", ".sr-close:hover{background:rgba(255,255,255,.16)}"),
        (".sr-btn:hover::before{opacity:1}", ".sr-btn:hover{background:var(--wine)}"),
        (".sr-gallery-link:hover{color:var(--dark-text)}", None),
        (".ig-btn-primary:hover::before{opacity:1}", ".ig-btn-primary:hover{background:var(--wine)}"),
        (".ig-btn-ghost:hover{color:var(--dark-text)}", None),
    ):
        assert gated_rule in css, f"missing gated rule: {gated_rule}"
        if old_ungated:
            assert old_ungated not in css, f"old ungated form still present: {old_ungated}"
    # Every one of those rules must live inside a hover-capable media block —
    # none should appear at the top level of the stylesheet any more.
    assert css.count("@media (hover:hover) and (pointer:fine){") >= 3


def test_hover_fills_animate_opacity_not_background(client):
    # background-color is a repaint; opacity is GPU-compositable. Each hover
    # fill now lives on its own overlay (::before/::after) instead of
    # animating the element's own `background`.
    css = _css(client)
    assert "background:rgba(0,0,0,0);transition:background" not in css  # old .rg-card::after
    assert "background:#000;opacity:0;transition:opacity .15s ease" in css  # .rg-card::after
    for selector in (".sr-close::before", ".sr-btn::before", ".rg-menu::before", ".ig-btn-primary::before"):
        assert selector in css
        assert "opacity:0;transition:opacity .15s ease" in css.split(selector)[1][:220]


def test_intro_mark_does_not_appear_from_nothing(client):
    # scale(.4) reads as conjured rather than settling into place; the floor
    # is ~0.9. The -12deg rotation still carries the entrance's flourish.
    css = _css(client)
    assert "transform:scale(.4) rotate(-12deg)" not in css
    assert "transform:scale(.9) rotate(-12deg)" in css


def test_intro_sequence_uses_a_strong_easing_curve_not_weak_built_in_ease(client):
    # Built-in `ease` is "too weak" for a deliberate, watched entrance; the
    # whole sequence now shares ig-mark-in's existing strong curve.
    css = _css(client)
    assert "ig-word-in .5s ease forwards" not in css
    assert "ig-choices-in .5s ease forwards" not in css
    assert "animation:ig-word-in .5s cubic-bezier(.2,.8,.2,1) forwards, ig-word-out .7s cubic-bezier(.2,.8,.2,1) forwards" in css
    assert "animation:ig-choices-in .5s cubic-bezier(.2,.8,.2,1) forwards" in css


# --------------------------------------------------------------------------- #
# Play/pause icon cross-fade — replaces the innerHTML swap that popped
# instantly with no transition at all.
# --------------------------------------------------------------------------- #

def test_play_pause_crossfades_instead_of_swapping_innerhtml(client):
    css = _css(client)
    assert ".sr-icon{" in css
    assert "opacity .25s cubic-bezier(.2,0,0,1)" in css
    assert "scale(.25)" in css
    assert "filter:blur(4px)" in css
    assert ".sr-btn.is-playing .sr-icon-play{opacity:0" in css
    assert ".sr-btn.is-playing .sr-icon-pause{opacity:1" in css


def test_play_pause_icon_transform_drops_under_reduced_motion(client):
    css = _css(client)
    assert ".sr-icon{transition:opacity .3s ease}" in css


def test_showreel_has_two_icon_spans_not_an_innerhtml_swap(client):
    t = client.get("/showreel").text
    assert 'class="sr-icon sr-icon-play"' in t
    assert 'class="sr-icon sr-icon-pause"' in t
    assert "b.innerHTML = on ? '&#10073;&#10073;' : '&#9654;';" not in t
    assert "classList.toggle('is-playing', on)" in t
