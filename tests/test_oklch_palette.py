"""Chordential's brand palette in site.css :root is defined in OKLCH, not hex —
equal L steps read as equal brightness (hex/HSL varies wildly by hue), and
hue stays constant across the lightness range instead of drifting. Each
value was converted from and round-trips exactly back to the original hex
this file used before (verified below by rendering, not just asserting text).
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


def test_brand_palette_uses_oklch_not_hex(client):
    css = client.get("/static/public/site.css").text
    # The brand-palette paragraph ends at the blank line before --paper —
    # there's no closing "}" until the very end of :root{...}, so splitting
    # on that would swallow the (intentionally untouched) --paper/etc. block.
    block = css.split("/* Chordential brand palette")[1].split("\n\n")[0]
    for var in ("--cream", "--sand", "--olive", "--slate", "--ink", "--wine", "--orange", "--white"):
        assert f"{var}:oklch(" in block, f"{var} isn't defined in oklch()"
    # The old hex literals are gone from this specific block (they're free to
    # appear elsewhere in the file, e.g. rgba() shadows derived from --ink).
    for old_hex in ("#FCF7F8", "#D8CDB6", "#737469", "#546671", "#1F1E1E", "#44161E", "#E4671F"):
        assert old_hex not in block


def test_oklch_values_round_trip_to_the_exact_original_hex():
    # Real color math, not string matching — converts each oklch() triple
    # back through OKLab -> linear sRGB -> sRGB and checks it lands on the
    # exact original hex Chordential's brand used before this pass.
    import math
    import re
    from pathlib import Path

    css = (
        Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/static/public/site.css"
    ).read_text()
    block = css.split("/* Chordential brand palette")[1].split("}")[0]

    expected = {
        "--cream": "#FCF7F8", "--sand": "#D8CDB6",
        # ADR-0041 (operator ruling): olive darkened from #737469, which was under
        # AA as type. The OKLCH value must still land EXACTLY on the intended hex —
        # that is what this test is for; only the intended hex changed.
        "--olive": "#65665B", "--slate": "#546671",
        "--ink": "#1F1E1E", "--wine": "#44161E", "--orange": "#E4671F", "--white": "#FFFFFF",
    }

    def oklch_to_hex(l, c, h):
        a = c * math.cos(math.radians(h))
        b = c * math.sin(math.radians(h))
        l_ = l + 0.3963377774 * a + 0.2158037573 * b
        m_ = l - 0.1055613458 * a - 0.0638541728 * b
        s_ = l - 0.0894841775 * a - 1.2914855480 * b
        ll, mm, ss = l_**3, m_**3, s_**3
        r = 4.0767416621 * ll - 3.3077115913 * mm + 0.2309699292 * ss
        g = -1.2684380046 * ll + 2.6097574011 * mm - 0.3413193965 * ss
        bb = -0.0041960863 * ll - 0.7034186147 * mm + 1.7076147010 * ss

        def to_srgb(x):
            x = max(0.0, min(1.0, x))
            return x * 12.92 if x <= 0.0031308 else 1.055 * (x ** (1 / 2.4)) - 0.055

        r, g, bb = to_srgb(r), to_srgb(g), to_srgb(bb)
        return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(bb * 255))

    for var, expected_hex in expected.items():
        m = re.search(rf"{re.escape(var)}:oklch\(([\d.]+) ([\d.]+) ([\d.]+)\)", block)
        assert m, f"couldn't find an oklch() value for {var}"
        l, c, h = (float(x) for x in m.groups())
        actual_hex = oklch_to_hex(l, c, h)
        assert actual_hex == expected_hex, f"{var}: oklch({l} {c} {h}) -> {actual_hex}, expected {expected_hex}"
