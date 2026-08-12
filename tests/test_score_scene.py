"""The cube is a cube.

The front door's world is 728 pieces of engraved notation that fly apart and
reassemble into a box. For a long time 150 of them did not fit in the box: they
finished assembling with staves projecting out of the faces, the worst by 125
units — 42% of the cube's own width. It is the kind of defect that renders
perfectly, ships, and then cannot be unseen.

The shipped blob carries only each piece's centre and longest span, which is
all the renderer needs and not enough to check containment, so these tests run
the generator for the real boxes (40ms) — and then assert that what is on disk
is still what the generator produces, so a stale asset cannot pass by being
tidy in a file nobody rebuilt.
"""
import json
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "src", "chordential_oia", "web", "static", "public")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import build_score_scene as gen                             # noqa: E402
from score_scene.recipe import SPAN, TOP, BOTTOM, CENTER    # noqa: E402


@pytest.fixture(scope="module")
def built():
    return gen.build()


@pytest.fixture(scope="module")
def shipped():
    meta = json.load(open(os.path.join(STATIC, "score-scene.json")))
    blob = open(os.path.join(STATIC, "score-scene.bin"), "rb").read()
    return meta, blob


def test_no_piece_escapes_the_cube(built):
    """Not one mark outside the box, on any of the six faces."""
    _, _, boxes = built
    worst, out = gen.escapes(boxes)
    assert not out, (
        "%d piece(s) hang out of the cube, worst x %+.1f depth %+.1f up %+.1f: %s"
        % (len(out), worst[0], worst[1], worst[2], out[:8]))


def test_the_cube_is_still_full(built):
    """Containment must not have been bought by throwing notation away.

    The fix slides a run inward and only shortens it when the box is genuinely
    narrower. If a later change starts DROPPING runs instead, the cube gets
    tidy and empty, and this is what notices.
    """
    meta, _, _ = built
    by_name = dict(zip([p["name"] for p in meta["protos"]], meta["counts"]))
    assert meta["nPieces"] >= 700
    assert meta["nMarks"] >= 7000
    assert by_name["rect"] >= 4500          # rules, stems, beams, barlines
    assert by_name["head"] >= 2000          # it has to read as music
    assert by_name["treble"] + by_name["bass"] >= 100


def test_the_cube_still_reaches_its_own_walls(built):
    """Containment implemented as "shrink everything" would pass the two tests
    above. The model has to touch all six faces or it is not a box."""
    _, _, boxes = built
    for i, (name, lo, hi) in enumerate([("x", -SPAN, SPAN), ("depth", -SPAN, SPAN),
                                        ("up", BOTTOM, TOP)]):
        assert min(b[i] for b in boxes) <= lo + 20, \
            "%s: nothing within 20 of the near wall" % name
        assert max(b[i + 3] for b in boxes) >= hi - 20, \
            "%s: nothing within 20 of the far wall" % name


def test_the_shipped_scene_is_what_the_generator_builds(built, shipped):
    """A regenerated scene and the one on disk are the same bytes.

    Without this, containment could be true of the recipe and false of the
    asset the browser downloads — which is exactly the shape the original
    defect had, three copies of the layout and only one of them looked at.
    """
    meta, blob, _ = built
    smeta, sblob = shipped
    assert smeta["nMarks"] == meta["nMarks"]
    assert smeta["nPieces"] == meta["nPieces"]
    assert smeta["counts"] == meta["counts"]
    assert sblob == blob, ("score-scene.bin is stale — "
                           "run python3 scripts/build_score_scene.py")


def test_the_shipped_scene_matches_its_own_header(shipped):
    meta, blob = shipped
    assert meta["nMarks"] == sum(meta["counts"])
    assert meta["offPidx"] == meta["nMarks"] * 48          # 12 floats per mark
    assert len(blob) == meta["offPieces"] + meta["nPieces"] * 16


def test_the_renderer_is_told_where_the_centre_is(shipped):
    """score-gl.js orbits, fogs and frames the world about META.center."""
    meta, _ = shipped
    assert tuple(meta["center"]) == tuple(CENTER)
    assert BOTTOM < CENTER[2] < TOP


def test_the_generator_is_in_the_repo():
    """The scene is a build artifact; the thing that builds it has to be here.

    It lived only in a scratch directory until 2026-08-12, which is how three
    divergent copies of the layout came to exist at once.
    """
    for p in ("build_score_scene.py", "blender_score_cube.py",
              "export_score_glyphs.py", os.path.join("score_scene", "recipe.py"),
              os.path.join("score_scene", "glyph-protos.json")):
        assert os.path.exists(os.path.join(ROOT, "scripts", p)), p
