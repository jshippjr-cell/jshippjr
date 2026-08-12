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
import math
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
    assert meta["offPack"] == meta["offPieces"] + meta["nPieces"] * 16
    assert meta["offSeal"] == meta["offPack"] + meta["nPieces"] * 32
    assert meta["offFlap"] == meta["offSeal"] + meta["nPieces"] * 32
    assert len(blob) >= meta["offFlap"] + meta["nPieces"]


def test_the_renderer_is_told_where_the_centre_is(shipped):
    """score-gl.js orbits, fogs and frames the world about META.center."""
    meta, _ = shipped
    assert tuple(meta["center"]) == tuple(CENTER)
    assert BOTTOM < CENTER[2] < TOP


def test_every_piece_has_somewhere_to_go_in_the_package(shipped):
    """The cube folds into a delivery carton and takes all of itself with it.

    "One delivery. Nothing missing." is the claim the words next to it make. If
    a change ever starts dropping pieces out of the pack — collapsing them to
    nothing, or leaving them behind at their cube position — the picture stops
    agreeing with the sentence.
    """
    meta, blob = shipped
    n = meta["nPieces"]
    packed = [struct.unpack_from("<8f", blob, meta["offPack"] + i * 32)
              for i in range(n)]
    assert len(packed) == n
    for i, t in enumerate(packed):
        assert t[3] > 0.05, "piece %d packs to nothing" % i
        q = math.sqrt(sum(c * c for c in t[4:]))
        assert abs(q - 1.0) < 1e-3, "piece %d has a non-unit quaternion" % i
        assert t[7] >= 0, "piece %d slerps the long way round" % i


def test_the_package_is_a_carton_and_the_pieces_lie_inside_it(shipped):
    """Nothing sticks out of the package either — that was the whole lesson.

    The bound is the carton's OWN outline, worked out from the edges the packer
    lays notation along, rather than a number written down a second time here
    and left to drift from it.
    """
    from score_scene.pack import carton                  # noqa: E402
    meta, blob = shipped
    lo = [1e9] * 3
    hi = [-1e9] * 3
    for e in carton():
        for end in (e.p0, tuple(e.p0[i] + e.u[i] * e.length for i in range(3))):
            for i in range(3):
                lo[i] = min(lo[i], end[i])
                hi[i] = max(hi[i], end[i])
    pad = 14.0                       # a run of notation is wider than its line
    n = meta["nPieces"]
    for i in range(n):
        t = struct.unpack_from("<8f", blob, meta["offPack"] + i * 32)
        for ax, name in enumerate(("x", "depth", "up")):
            assert lo[ax] - pad <= t[ax] <= hi[ax] + pad, \
                "piece %d sits outside the package on %s" % (i, name)


def test_the_outline_is_drawn_and_the_rest_is_contents(shipped):
    """The carton's edges are staff paper; what is left is what is in the box.

    Two populations, told apart by scale, because that is exactly how
    score-gl.js tells them apart when it decides what folds first.
    """
    meta, blob = shipped
    n = meta["nPieces"]
    packed = [struct.unpack_from("<8f", blob, meta["offPack"] + i * 32)
              for i in range(n)]
    on_edge = [t for t in packed if t[3] >= 0.40]
    inside = [t for t in packed if t[3] < 0.40]
    assert len(on_edge) == meta["packOnEdges"]
    assert 40 <= len(on_edge) <= 200, "the outline needs runs long enough to draw it"
    assert len(inside) > len(on_edge), "a wireframe you cannot see through is a box"
    assert len(on_edge) + len(inside) == n


def test_the_generator_is_in_the_repo():
    """The scene is a build artifact; the thing that builds it has to be here.

    It lived only in a scratch directory until 2026-08-12, which is how three
    divergent copies of the layout came to exist at once.
    """
    for p in ("build_score_scene.py", "blender_score_cube.py",
              "export_score_glyphs.py", os.path.join("score_scene", "recipe.py"),
              os.path.join("score_scene", "glyph-protos.json")):
        assert os.path.exists(os.path.join(ROOT, "scripts", p)), p


def test_shutting_the_lid_moves_the_flaps_and_nothing_else(shipped):
    """The lid folds; the box and its contents stay exactly where they are.

    Both states ship, and the renderer recovers each flap's hinge from the pair
    — so if a change ever made every piece differ between them, the fold would
    stop being a fold and become the whole model sliding sideways.
    """
    meta, blob = shipped
    n = meta["nPieces"]
    moved = still = 0
    for i in range(n):
        p = struct.unpack_from("<8f", blob, meta["offPack"] + i * 32)
        s = struct.unpack_from("<8f", blob, meta["offSeal"] + i * 32)
        if max(abs(a - b) for a, b in zip(p, s)) > 1e-4:
            moved += 1
        else:
            still += 1
    assert moved, "nothing moves when the lid closes"
    # only the four flaps travel: a minority of the pieces that draw the outline
    assert moved < meta["packOnEdges"], (
        "%d pieces move but only %d are on the carton at all" % (moved, meta["packOnEdges"]))
    assert still > n * 0.8, "far too much of the model moves for a lid closing"


def test_the_shut_lid_is_lower_than_the_open_one(shipped):
    """A flap folded flat sits at the rim; standing open it reaches well above."""
    meta, blob = shipped
    n = meta["nPieces"]
    top_open = max(struct.unpack_from("<8f", blob, meta["offPack"] + i * 32)[2]
                   for i in range(n))
    top_shut = max(struct.unpack_from("<8f", blob, meta["offSeal"] + i * 32)[2]
                   for i in range(n))
    assert top_shut < top_open - 40, (
        "the lid barely drops (%.0f -> %.0f); it is not closing" % (top_open, top_shut))


def test_the_fold_is_a_compression_not_a_dissolve(built):
    """Each piece lands near where it already was.

    Given a free choice of destination the packer sent every piece across the
    model to somewhere unrelated, and the middle of the fold — the part you
    actually scroll through — was an unreadable cloud: the cube dissolved and a
    carton condensed out of it. Taking each destination from the source instead
    (nearest edge that fits; contents keep their own footprint and their own
    stacking order) halved the average trip and made the same fold read as the
    cube compressing into the box.

    This is a LOOK held in a number. If it regresses the picture still ends in
    the right place, so nothing else here would notice.
    """
    meta, blob, boxes = built
    n = meta["nPieces"]
    trav = []
    for i in range(n):
        t = struct.unpack_from("<8f", blob, meta["offPack"] + i * 32)
        b = boxes[i]
        c = ((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2)
        trav.append(math.dist(c, t[:3]))
    trav.sort()
    median = trav[len(trav) // 2]
    assert median < 170, (
        "the median piece travels %.0f units into the package; over about 170 "
        "the fold stops reading as a fold and becomes a dissolve" % median)


def test_the_contents_keep_their_own_footprint(built):
    """What is packed inside lands under roughly where it was standing.

    That is what makes the fill read as the cube settling into the box rather
    than as 648 pieces being re-dealt, and it is the half of the fold nobody
    sees in the finished frame — only while scrolling through it.
    """
    meta, blob, boxes = built
    n = meta["nPieces"]
    xs, us = [], []
    for i in range(n):
        t = struct.unpack_from("<8f", blob, meta["offPack"] + i * 32)
        if t[3] >= 0.40:            # skip the outline; those go to edges
            continue
        b = boxes[i]
        xs.append((b[0] + b[3]) / 2)
        us.append(t[0])
    assert len(xs) > 300
    mx, mu = sum(xs) / len(xs), sum(us) / len(us)
    cov = sum((a - mx) * (b - mu) for a, b in zip(xs, us))
    sx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    su = math.sqrt(sum((b - mu) ** 2 for b in us))
    r = cov / (sx * su)
    assert r > 0.75, (
        "where a piece ends up across the box barely relates to where it "
        "started (r=%.2f) — the contents are being re-dealt, not packed" % r)


def test_every_piece_that_moves_is_told_which_hinge_moves_it(shipped):
    """The lid's four hinges ship; the renderer does not deduce them.

    It used to: a rigid rotation IS determined by its endpoints, but recovering
    it means choosing which side of the chord the centre falls on, and where
    that choice went wrong the panel was left standing. Some of the lid folded
    and some did not — a tent, not a closed box. Anything whose shut position
    differs from its open one must now name the hinge that takes it there, and
    anything that names one must actually move.
    """
    meta, blob = shipped
    n = meta["nPieces"]
    assert len(meta["flaps"]) == 4
    for f in meta["flaps"]:
        assert abs(math.sqrt(sum(c * c for c in f["n"])) - 1.0) < 1e-6
        assert 0.5 < f["a"] < math.pi
    for i in range(n):
        p = struct.unpack_from("<8f", blob, meta["offPack"] + i * 32)
        s = struct.unpack_from("<8f", blob, meta["offSeal"] + i * 32)
        moves = max(abs(a - b) for a, b in zip(p, s)) > 1e-4
        flap = blob[meta["offFlap"] + i]
        assert moves == (flap < 4), (
            "piece %d moves=%s but its hinge tag is %d" % (i, moves, flap))


def test_each_hinge_actually_shuts_its_own_panel(shipped):
    """Turning a piece about the hinge it names lands it on its shut position.

    This is the assertion the old reconstruction could not make about itself.
    """
    meta, blob = shipped
    n = meta["nPieces"]
    worst = 0.0
    turned = 0
    for i in range(n):
        flap = blob[meta["offFlap"] + i]
        if flap >= 4:
            continue
        f = meta["flaps"][flap]
        p = struct.unpack_from("<8f", blob, meta["offPack"] + i * 32)[:3]
        want = struct.unpack_from("<8f", blob, meta["offSeal"] + i * 32)[:3]
        nx, ny, nz = f["n"]
        a = f["a"]
        v = [p[j] - f["p"][j] for j in range(3)]
        ca, sa = math.cos(a), math.sin(a)
        d = nx * v[0] + ny * v[1] + nz * v[2]
        got = (f["p"][0] + v[0]*ca + (ny*v[2]-nz*v[1])*sa + nx*d*(1-ca),
               f["p"][1] + v[1]*ca + (nz*v[0]-nx*v[2])*sa + ny*d*(1-ca),
               f["p"][2] + v[2]*ca + (nx*v[1]-ny*v[0])*sa + nz*d*(1-ca))
        worst = max(worst, math.dist(got, want))
        turned += 1
    assert turned >= 20, "hardly any of the lid turns"
    assert worst < 0.5, (
        "a panel turned about its own hinge misses its shut position by "
        "%.1f units — that flap folds the wrong way" % worst)


def test_the_blender_recorder_still_calls_the_packer_correctly():
    """The offline recorder needs Blender to run, so nothing here executes it.

    That is exactly how it broke: `pack.targets` grew a return value, the web
    recorder was updated, and the Blender one went on unpacking the old arity —
    an immediate crash the moment anyone rendered, invisible to a green suite
    for a whole commit. The call is checked statically instead.
    """
    import inspect
    import re
    src = open(os.path.join(ROOT, "scripts", "blender_score_cube.py")).read()
    m = re.search(r"^([A-Z_,\s]+)=\s*pack\.targets\(", src, re.M)
    assert m, "blender_score_cube.py no longer calls pack.targets"
    names = [n for n in m.group(1).replace(" ", "").split(",") if n]
    ret = re.search(r"return (out, sealed.*)$",
                    inspect.getsource(gen.pack.targets), re.M)
    assert ret, "pack.targets no longer returns a plain tuple"
    assert len(names) == len(ret.group(1).split(",")), (
        "blender_score_cube.py unpacks %d values from pack.targets, which "
        "returns %d" % (len(names), len(ret.group(1).split(","))))
