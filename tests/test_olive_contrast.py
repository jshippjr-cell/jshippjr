"""`--olive` reads as body text on every surface it lands on.

The last open item of the launch review's Phase 1 contrast pass, deferred at the time
because darkening a brand token is a palette decision rather than a bug fix. Ruled by
the operator: darken it.

`#737469` measured **4.47:1** on `--bg`, **4.15:1** on `--panel` and **3.89:1** on
`--panel2` — under AA's 4.5:1 on three of the four surfaces it is used as type on. The
same value also survived, unfixed by the earlier pass, as `--muted` in **`brief.css`**
and **`first_touch.html`** — two documents a *client* reads — at 4.47:1 on the page and
3.86:1 on the body, and as a hardcoded literal on the homepage's paper card (3.84:1
against the dark end of its gradient).

ADR-0041 moves it to `#65665B` — same hue, same chroma, lightness down 0.05 in OKLCH.
Worst case is now 4.78:1.

These tests compute the ratios from the stylesheets rather than asserting a hex, so the
palette can move again as long as it keeps passing.
"""

import re
from pathlib import Path

import pytest

from chordential_oia.web import app as app_mod

STATIC = Path(app_mod.__file__).parent / "static"
TPL = Path(app_mod.__file__).parent / "templates"

AA_NORMAL = 4.5


def _lin(c):
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexs):
    h = hexs.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg, bg):
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _var(css: str, name: str) -> str:
    m = re.search(rf"{re.escape(name)}\s*:\s*(#[0-9A-Fa-f]{{6}})", css)
    assert m, f"{name} is not defined as a hex in this stylesheet"
    return m.group(1)


# --------------------------------------------------------------------------- #
# The console
# --------------------------------------------------------------------------- #
def test_olive_passes_aa_on_every_console_surface():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    olive = _var(css, "--olive")
    surfaces = {name: _var(css, f"--{name}") for name in ("bg", "card", "panel", "panel2")}
    failing = {n: round(contrast(olive, bg), 2)
               for n, bg in surfaces.items() if contrast(olive, bg) < AA_NORMAL}
    assert failing == {}, f"--olive ({olive}) is under AA on: {failing}"


def test_the_public_palette_holds_the_same_olive():
    """Two palettes, one colour. The public site stores it in OKLCH; if the two drift
    the brand says different things on either side of the login."""
    from chordential_oia.web import showcase  # noqa: F401  (package import guard)

    site = (STATIC / "public" / "site.css").read_text(encoding="utf-8")
    m = re.search(r"--olive:\s*oklch\(([\d.]+)", site)
    assert m, "the public --olive is no longer OKLCH"
    assert abs(float(m.group(1)) - 0.505) < 0.001, (
        "the public olive's lightness diverged from the console's")


# --------------------------------------------------------------------------- #
# The documents a client reads — missed by the earlier pass
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("where", ["static/brief.css", "templates/first_touch.html"])
def test_client_documents_pass_aa(where):
    """These carry their own self-contained palettes, which is exactly why the first
    contrast pass fixed `site.css` and left these at the failing value."""
    root = Path(app_mod.__file__).parent
    css = (root / where).read_text(encoding="utf-8")
    muted = _var(css, "--muted")
    for bg in ("#FCF7F8", "#ece7e3"):        # the page, and the body behind it
        r = contrast(muted, bg)
        assert r >= AA_NORMAL, f"{where}: --muted {muted} is {r:.2f}:1 on {bg}"


def test_the_homepage_paper_card_passes():
    """A light paper card on the dark homepage — its type is measured against the card,
    not the page. Against the dark end of its own gradient it was 3.84:1."""
    home = (TPL / "public" / "commission.html").read_text(encoding="utf-8")
    m = re.search(r"\.item\.paper \.l\{[^}]*color:(#[0-9A-Fa-f]{6})", home, re.S)
    assert m, "the paper card's label colour moved"
    for bg in ("#FCF7F8", "#EFE6DA"):        # the gradient's light and dark ends
        assert contrast(m.group(1), bg) >= AA_NORMAL


# --------------------------------------------------------------------------- #
# Nothing keeps the old value alive
# --------------------------------------------------------------------------- #
def test_the_failing_value_is_gone_from_every_stylesheet_and_template():
    """Including `var(--olive, #737469)` fallbacks: a page that renders before or
    without the palette must not land on the value that failed."""
    root = Path(app_mod.__file__).parent
    offenders = []
    for path in list(root.rglob("*.css")) + list(root.rglob("*.html")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "737469" in line and "ADR-0041" not in line and "was" not in line:
                offenders.append(f"{path.name}:{i}")
    assert offenders == [], f"the pre-AA olive survives at: {offenders}"


def test_darkening_kept_the_colour_the_same_colour():
    """A palette fix that changes the hue is a rebrand. Chroma and hue are untouched;
    only lightness moved, so it is still the brand's olive."""
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    olive = _var(css, "--olive").lstrip("#")
    r, g, b = (int(olive[i:i + 2], 16) for i in (0, 2, 4))
    # olive: green the largest channel, blue the smallest, all three close together.
    assert g >= r > b, f"#{olive} is no longer an olive"
    assert max(r, g, b) - min(r, g, b) <= 24, "the colour became saturated"
    assert _lum(f"#{olive}") < _lum("#737469"), "the token did not actually darken"
