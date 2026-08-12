"""Ship the cube to the browser: score-scene.json + score-scene.bin.

The model itself lives in `score_scene/recipe.py`. This file is one of its
recorders — it turns every mark into (prototype, 3x4 affine) and packs them for
`web/static/public/score-gl.js`, which draws them instanced. Prototype 0 is a
unit quad, so every staff line, stem, beam, barline and ledger is one scaled
rectangle; prototypes 1..N are the triangulated Leland outlines produced by
`export_score_glyphs.py`.

Marks are grouped into PIECES: the things that fly apart at the top of the page
and come back as you scroll. A fragment of staff is one piece; a lone notehead
out in the field is one piece.

Run: python3 scripts/build_score_scene.py
"""
import json, math, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from score_scene import pack, recipe                              # noqa: E402
from score_scene.recipe import Matrix, Vector, SPAN, TOP, BOTTOM  # noqa: E402
from score_scene.pack import W as W_CARTON, D as D_CARTON, H as H_CARTON  # noqa: E402

GLYPHS = os.path.join(HERE, "score_scene")
OUT = os.path.join(os.path.dirname(HERE), "src", "chordential_oia", "web",
                   "static", "public")

# ── prototypes ───────────────────────────────────────────────────────────────
PROTOS = json.load(open(os.path.join(GLYPHS, "glyph-protos.json")))
PROTO_ORDER = ["rect"] + list(PROTOS.keys())
PROTO_IDX = {n: i for i, n in enumerate(PROTO_ORDER)}
PROTO_BBOX = {"rect": (-0.5, -0.5, 0.5, 0.5)}
for _n, _g in PROTOS.items():
    PROTO_BBOX[_n] = (min(_g["v"][0::2]), min(_g["v"][1::2]),
                      max(_g["v"][0::2]), max(_g["v"][1::2]))


def _axes(M):
    """A mark's own axes: column 0 is along its run, column 1 is up it.

    A mark is placed by `frame @ translate @ scale`, so those columns come out
    scaled by the mark's length and width — unit them and the piece's
    orientation falls out of the geometry with nothing extra to keep in step.
    """
    def unit(j, fallback):
        v = (M.m[0][j], M.m[1][j], M.m[2][j])
        n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
        return fallback if n < 1e-9 else (v[0] / n, v[1] / n, v[2] / n)
    return unit(0, (1.0, 0.0, 0.0)), unit(1, (0.0, 0.0, 1.0))


class MarkRecorder:
    """Records the recipe as instanced marks, and each piece's bounding box.

    It also keeps each piece's own FRAME — which way its staff runs and which
    way is up it — taken from the first mark laid down, which for every run of
    notation in the recipe is that run's first staff line. That is what lets
    the packer turn a piece to lie along an edge of the delivery carton instead
    of guessing an orientation from an axis-aligned box.
    """

    def __init__(self):
        self.marks = []        # (protoIdx, pieceIdx, 12 floats)
        self.boxes = []        # [minx, miny, minz, maxx, maxy, maxz] per piece
        self.frames = []       # (U, Y) unit vectors per piece — along, up
        self.ranges = []       # [minU, maxU, minY, maxY] per piece, in its frame
        self._cur = -1

    def piece(self):
        self.boxes.append([1e9, 1e9, 1e9, -1e9, -1e9, -1e9])
        self.frames.append(None)
        self.ranges.append([1e9, -1e9, 1e9, -1e9])
        self._cur = len(self.boxes) - 1

    def box(self, mat_world, length, width, cx, cy):
        M = mat_world @ Matrix.Translation(Vector((cx, cy, 0)))
        S = Matrix.Identity(4)
        S.m[0][0], S.m[1][1] = length, width
        self._record("rect", M @ S)

    def glyph(self, name, mat_world, lx, ly, scale=1.0, sx=1.0, rot=0.0):
        m = mat_world @ Matrix.Translation(Vector((lx, ly, 0)))
        if scale != 1.0:
            m = m @ Matrix.Scale(scale, 4)
        if sx != 1.0:
            m = m @ Matrix.Scale(sx, 4, (1, 0, 0))
        if rot:
            m = m @ Matrix.Rotation(rot, 4, 'Z')
        self._record(name, m)

    def _record(self, proto, M):
        x0, y0, x1, y1 = PROTO_BBOX[proto]
        box = self.boxes[self._cur]
        if self.frames[self._cur] is None:
            self.frames[self._cur] = _axes(M)
        U, Y = self.frames[self._cur]
        rng = self.ranges[self._cur]
        for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            p = M @ Vector((cx, cy, 0))
            for i, c in enumerate((p.x, p.y, p.z)):
                box[i] = min(box[i], c)
                box[i + 3] = max(box[i + 3], c)
            du = p.x * U[0] + p.y * U[1] + p.z * U[2]
            dy = p.x * Y[0] + p.y * Y[1] + p.z * Y[2]
            rng[0] = min(rng[0], du); rng[1] = max(rng[1], du)
            rng[2] = min(rng[2], dy); rng[3] = max(rng[3], dy)
        self.marks.append((PROTO_IDX[proto], self._cur,
                           [M.m[0][0], M.m[0][1], M.m[0][2], M.m[0][3],
                            M.m[1][0], M.m[1][1], M.m[1][2], M.m[1][3],
                            M.m[2][0], M.m[2][1], M.m[2][2], M.m[2][3]]))


def measure(seed=recipe.SEED):
    """Walk the recipe and report every piece's box, frame and extent.

    Split out so the Blender recorder can ask for the same measurements — it
    builds curves and meshes, which is the wrong shape to take a glyph's
    bounding box from, and the two walks visit the same pieces in the same
    order from the same seed.

    Returns (rec, alive, boxes, frames, ranges).
    """
    rec = MarkRecorder()
    recipe.compose(rec, seed=seed)
    alive = [i for i, b in enumerate(rec.boxes) if b[3] > b[0] - 1e8]
    return (rec, alive,
            [rec.boxes[i] for i in alive],
            [rec.frames[i] for i in alive],
            [rec.ranges[i] for i in alive])


def build(seed=recipe.SEED):
    """Run the recipe and pack it. Returns (meta, blob, boxes).

    `boxes` is the exact per-piece bounding box, which the shipped blob does
    NOT carry — it stores centre and longest span, all the renderer needs.
    tests/test_score_scene.py asks this for the real boxes.
    """
    rec, alive, boxes, frames, ranges = measure(seed)
    remap = {old: new for new, old in enumerate(alive)}

    pieces_out = [((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2,
                   max(b[3] - b[0], b[4] - b[1], b[5] - b[2])) for b in boxes]

    # …and where each of them goes once the cube becomes the package
    packed, on_edges, edges = pack.targets(boxes, frames, ranges)

    # sort marks by prototype so each proto is one contiguous instanced draw
    marks = sorted(rec.marks, key=lambda m: m[0])
    counts = [0] * len(PROTO_ORDER)
    buf, pidx = bytearray(), bytearray()
    for proto, piece, aff in marks:
        counts[proto] += 1
        buf += struct.pack("<12f", *aff)
        pidx += struct.pack("<H", remap[piece])

    while len(pidx) % 4:          # keep the next Float32Array 4-byte aligned
        pidx += b"\0\0"

    pbuf = bytearray()
    for cx, cy, cz, span in pieces_out:
        pbuf += struct.pack("<4f", cx, cy, cz, span)

    kbuf = bytearray()
    for t in packed:
        kbuf += struct.pack("<8f", *t)      # x,y,z, scale, qx,qy,qz,qw

    meta = {
        "protos": [{"name": n,
                    "v": ([-0.5, -0.5, 0.5, -0.5, 0.5, 0.5, -0.5, 0.5] if n == "rect"
                          else PROTOS[n]["v"]),
                    "i": ([0, 1, 2, 0, 2, 3] if n == "rect" else PROTOS[n]["i"])}
                   for n in PROTO_ORDER],
        "counts": counts,
        "nMarks": len(marks),
        "nPieces": len(pieces_out),
        "center": recipe.CENTER,
        "offMarks": 0,
        "offPidx": len(buf),
        "offPieces": len(buf) + len(pidx),
        "offPack": len(buf) + len(pidx) + len(pbuf),
        "packOnEdges": on_edges,
        "carton": [W_CARTON, D_CARTON, H_CARTON],
    }
    blob = bytes(buf) + bytes(pidx) + bytes(pbuf) + bytes(kbuf)
    return meta, blob, boxes


def escapes(boxes):
    """How far each axis of the model escapes the cube. Zero, or it shows."""
    lo = (-SPAN, -SPAN, BOTTOM)      # the browser's axis order: x, depth, up
    hi = (SPAN, SPAN, TOP)
    worst, out = [0.0, 0.0, 0.0], []
    for idx, b in enumerate(boxes):
        esc = 0.0
        for i in range(3):
            d = max(lo[i] - b[i], b[i + 3] - hi[i], 0.0)
            worst[i] = max(worst[i], d)
            esc = max(esc, d)
        if esc > 1.0:
            out.append((idx, round(esc, 1)))
    return worst, out


def main():
    meta, blob, boxes = build()
    open(os.path.join(OUT, "score-scene.bin"), "wb").write(blob)
    json.dump(meta, open(os.path.join(OUT, "score-scene.json"), "w"))

    print("marks   %6d" % meta["nMarks"])
    print("pieces  %6d" % meta["nPieces"])
    print("tris    %6d" % sum(meta["counts"][i] * len(meta["protos"][i]["i"]) // 3
                              for i in range(len(PROTO_ORDER))))
    print("bin     %6.1f KB" % (len(blob) / 1024))
    for i, n in enumerate(PROTO_ORDER):
        if meta["counts"][i]:
            print("   %-10s %5d" % (n, meta["counts"][i]))
    worst, out = escapes(boxes)
    print("outside %6d  (worst  x %+.2f   depth %+.2f   up %+.2f)"
          % (len(out), worst[0], worst[1], worst[2]))
    edges = pack.carton()
    print("carton  %gx%gx%g  %d edges, %.0f units of outline"
          % (pack.W, pack.D, pack.H, len(edges), sum(e.length for e in edges)))
    print("        %d pieces draw the outline, %d are packed inside"
          % (meta["packOnEdges"], meta["nPieces"] - meta["packOnEdges"]))


if __name__ == "__main__":
    main()
