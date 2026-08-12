"""Where every piece goes when the cube becomes the delivery package.

The last thing the front door says is that everything arrives together. So the
cube does not simply stop — it folds down into a shipping carton with its
flaps open, and the carton's OUTLINE is staff paper: each of its 24 edges is a
run of engraved notation laid end to end along it. What does not become an edge
becomes the contents, stacked flat inside the box in layers, visible through
the wireframe.

Nothing is thrown away and nothing is invented. All 728 pieces of the cube are
still on screen; they have only been put where they belong. One delivery,
nothing missing — which is the claim the words beside it make, so the picture
had better make it too.

Every target is (position, scale, quaternion) about the piece's own centroid,
which is exactly the transform `score-gl.js` already applies per piece — the
morph needs no new machinery in the renderer, only a second place to go.

Axes here are the browser's: x across, y depth, z up.
"""
import math

from .recipe import CENTER, SPAN

# ── the carton ───────────────────────────────────────────────────────────────
W, D, H = 300.0, 260.0, 200.0          # width, depth, height
FLAP_TILT = math.radians(58.0)         # how far the open flaps lean back
EDGE_SCALE = 0.46                      # notation laid along an edge
EDGE_GAP = 3.0                         # breath between two runs on one edge
EDGE_INSET = 1.0                       # the staff band sits just inside the line
FILL_SCALE = 0.34                      # notation packed inside the box
FILL_LAYERS = 7
FILL_FLOOR, FILL_HEAD = 0.06, 0.62     # the contents fill the lower box only

CX, CY, CZ = CENTER
HW, HD = W / 2, D / 2
Z0, Z1 = CZ - H / 2, CZ + H / 2


def _n(v):
    m = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1.0
    return (v[0] / m, v[1] / m, v[2] / m)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _add(*vs):
    return (sum(v[0] for v in vs), sum(v[1] for v in vs), sum(v[2] for v in vs))


def _mul(v, s):
    return (v[0] * s, v[1] * s, v[2] * s)


class Edge:
    """One line of the carton's outline, and which way notation lies on it.

    `F` points from the edge into the surface it shares, so a staff written
    along `U` with its lines running back along `F` lies ON the carton rather
    than hanging off it.
    """

    __slots__ = ("p0", "u", "f", "length", "used", "at", "flap")

    def __init__(self, p0, p1, f, flap=-1):
        self.flap = flap        # which lid panel this edge belongs to, or -1
        self.p0 = p0
        d = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
        self.length = math.sqrt(_dot(d, d))
        self.u = _n(d)
        self.f = _n(f)
        self.used = 0.0
        self.at = 0.0          # where the run currently being placed starts

    @property
    def room(self):
        return self.length - self.used


def carton(tilt=FLAP_TILT):
    """The 24 edges: a box, and four flaps hinged on its rim.

    `tilt` is how far each flap leans back off horizontal. FLAP_TILT stands them
    open; pi lays them flat and inward, which is the box shut — the flaps are
    cut to just under half the span they cross, so folded they meet in the
    middle the way a real carton does. Same 24 edges in the same order at any
    angle, and the same lengths, so a piece keeps its place on its own edge
    while the lid closes around it.
    """
    up, dn = (0, 0, 1), (0, 0, -1)
    corners = [(-HW, -HD), (HW, -HD), (HW, HD), (-HW, HD)]
    edges = []

    # the two horizontal rectangles. Their notation lies on the side walls —
    # up from the floor, down from the rim — so both read as part of the box
    for z, f in ((Z0, up), (Z1, dn)):
        for k in range(4):
            a, b = corners[k], corners[(k + 1) % 4]
            edges.append(Edge((a[0], a[1], z), (b[0], b[1], z), f))

    # the four uprights, each written across the wall it stands in
    for (x, y) in corners:
        edges.append(Edge((x, y, Z0), (x, y, Z1), (0.0, -1.0 if y > 0 else 1.0, 0.0)))

    # the flaps: hinged on the rim, leaning back and open. A closed box is a
    # box; an open one is a delivery.
    for k in range(4):
        a, b = corners[k], corners[(k + 1) % 4]
        hinge = _n((b[0] - a[0], b[1] - a[1], 0.0))
        out = _n((-(hinge[1]), hinge[0], 0.0))          # away from the box
        if _dot(out, (a[0], a[1], 0)) < 0:
            out = _mul(out, -1.0)
        lean = _add(_mul(out, math.cos(tilt)), _mul(up, math.sin(tilt)))
        depth = (HD if abs(hinge[0]) > 0.5 else HW) * 0.98
        A = (a[0], a[1], Z1)
        B = (b[0], b[1], Z1)
        A2, B2 = _add(A, _mul(lean, depth)), _add(B, _mul(lean, depth))
        edges.append(Edge(A, A2, hinge, k))              # the two folded sides
        edges.append(Edge(B, B2, _mul(hinge, -1.0), k))
        edges.append(Edge(A2, B2, _mul(lean, -1.0), k))  # and the open lip
    return edges


def hinges():
    """The axis each lid panel turns on, and how far it turns to shut.

    The renderer used to recover these from the open and shut positions — a
    rigid rotation IS determined by its endpoints, but the reconstruction has to
    pick which side of the chord the centre falls on, and when it picked wrong
    it gave up and left that panel standing. Some of the lid folded and some of
    it did not, which is a tent, not a closed box.

    They are known exactly right here, so they are shipped rather than deduced.
    A flap turns from FLAP_TILT to flat about its own hinge on the rim: the axis
    is `out x up`, which is the rim edge itself, and the angle is whatever is
    left between leaning open and lying shut.
    """
    up = (0.0, 0.0, 1.0)
    corners = [(-HW, -HD), (HW, -HD), (HW, HD), (-HW, HD)]
    out = []
    for k in range(4):
        a, b = corners[k], corners[(k + 1) % 4]
        hinge = _n((b[0] - a[0], b[1] - a[1], 0.0))
        away = _n((-(hinge[1]), hinge[0], 0.0))
        if _dot(away, (a[0], a[1], 0)) < 0:
            away = _mul(away, -1.0)
        out.append({"p": [a[0], a[1], Z1],            # a point on the hinge
                    "n": list(_cross(away, up)),      # …the hinge itself
                    "a": math.pi - FLAP_TILT})        # open to flat
    return out


# ── orientation ──────────────────────────────────────────────────────────────
def _quat(uh, yh, ut, yt):
    """The rotation carrying a piece's own frame onto a target frame."""
    # The eight hairline diagonals are written on a skewed frame — their "up"
    # is not square to their run. Square it up here rather than letting a
    # non-orthogonal basis turn into a shear that no quaternion can express.
    yh = _n((yh[0] - uh[0] * _dot(uh, yh), yh[1] - uh[1] * _dot(uh, yh),
             yh[2] - uh[2] * _dot(uh, yh)))
    zh, zt = _cross(uh, yh), _cross(ut, yt)
    # R = T * H^T, with H's rows being the home axes and T's columns the target
    R = [[ut[i] * uh[j] + yt[i] * yh[j] + zt[i] * zh[j] for j in range(3)]
         for i in range(3)]
    tr = R[0][0] + R[1][1] + R[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = ((R[2][1] - R[1][2]) / s, (R[0][2] - R[2][0]) / s,
             (R[1][0] - R[0][1]) / s, 0.25 * s)
    elif R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        s = math.sqrt(1.0 + R[0][0] - R[1][1] - R[2][2]) * 2
        q = (0.25 * s, (R[0][1] + R[1][0]) / s, (R[0][2] + R[2][0]) / s,
             (R[2][1] - R[1][2]) / s)
    elif R[1][1] > R[2][2]:
        s = math.sqrt(1.0 + R[1][1] - R[0][0] - R[2][2]) * 2
        q = ((R[0][1] + R[1][0]) / s, 0.25 * s, (R[1][2] + R[2][1]) / s,
             (R[0][2] - R[2][0]) / s)
    else:
        s = math.sqrt(1.0 + R[2][2] - R[0][0] - R[1][1]) * 2
        q = ((R[0][2] + R[2][0]) / s, (R[1][2] + R[2][1]) / s, 0.25 * s,
             (R[1][0] - R[0][1]) / s)
    m = math.sqrt(sum(c * c for c in q)) or 1.0
    if q[3] < 0:
        m = -m          # q and -q are the same rotation; keep w positive so the
    return tuple(c / m for c in q)   # renderer slerps the short way round


class _Rng:
    """The recipe's own xorshift, so the packing is the same every build."""

    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def __call__(self):
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s & 0xFFFFFFFF
        return self.s / 4294967296.0


def _dist2(p, e):
    """How far a piece at `p` is from the middle of edge `e`."""
    m = _add(e.p0, _mul(e.u, e.length / 2))
    return (p[0]-m[0])**2 + (p[1]-m[1])**2 + (p[2]-m[2])**2


def _on_edge(e, uh, yh, a, by):
    """Place a run along one edge at parameter `t`, already stored in the edge."""
    yt = _mul(e.f, -1.0)                         # lines run back into the face
    pos = _add(e.p0, _mul(e.u, e.at - EDGE_SCALE * a),
               _mul(e.f, EDGE_SCALE * by + EDGE_INSET))
    return pos + (EDGE_SCALE,) + _quat(uh, yh, e.u, yt)


def targets(boxes, frames, ranges, seed=52099):
    """Where each piece goes in the package, open and then shut.

    Returns (open_targets, shut_targets, flap_of_piece, on_edges, edges): one
    (x, y, z, scale, qx, qy, qz, qw) per piece per state, in piece order.
    Longest pieces first onto the longest remaining edge, so the outline is
    drawn by the runs that can actually draw a line; everything else lies down
    inside the box.

    The assignment is made ONCE, against the open carton, and then evaluated
    against both — so closing the lid rotates each flap's own notation about its
    own hinge instead of re-dealing the whole outline and making every piece
    jump somewhere else.
    """
    edges = carton()
    shut = carton(math.pi)
    order = sorted(range(len(boxes)),
                   key=lambda i: ranges[i][1] - ranges[i][0], reverse=True)
    out = [None] * len(boxes)
    sealed = [None] * len(boxes)
    flap = [-1] * len(boxes)      # which lid panel carries it, if any
    rng = _Rng(seed)
    contents = []

    for i in order:
        uh, yh = frames[i] or ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        b = boxes[i]
        c = ((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2)
        u0, u1, y0, y1 = ranges[i]
        a = u0 - _dot(c, uh)                     # the run, about its centroid
        by = y1 - _dot(c, yh)
        need = (u1 - u0) * EDGE_SCALE

        # the NEAREST edge that can still take it, not the emptiest. Filling
        # the emptiest sent pieces across the model to whichever edge happened
        # to be free, so the fold was a swarm crossing its own interior; going
        # to the nearest one that fits cuts the average trip by a quarter and
        # the fold reads as the cube opening out rather than scattering.
        fits = [k for k in range(len(edges))
                if need <= edges[k].room - (EDGE_GAP if edges[k].used else 0.0)]
        k = min(fits, key=lambda k: _dist2(c, edges[k])) if fits else \
            max(range(len(edges)), key=lambda k: edges[k].room)
        e, s = edges[k], shut[k]
        gap = EDGE_GAP if e.used else 0.0
        if 1.0 < need <= e.room - gap:
            e.at = s.at = e.used + gap
            e.used = s.used = e.at + need
            out[i] = _on_edge(e, uh, yh, a, by)
            sealed[i] = _on_edge(s, uh, yh, a, by)
            flap[i] = e.flap
        else:
            contents.append(i)

    # What is left is what is IN the box: flat layers of score, lying face up.
    #
    # Where each one lands is derived from where it already IS, not drawn fresh.
    # Given a random spot each, every piece crossed the model to somewhere
    # unrelated and the middle of the fold was an unreadable cloud — the cube
    # dissolved and a carton condensed out of it. Taking the destination from
    # the source makes the same fold read as the cube COMPRESSING into the box:
    # each piece settles roughly below where it was, and the picture stays
    # legible the whole way through.
    #
    # Height decides the layer by RANK, so the stack is still evenly filled
    # while the order through it is the order the pieces were stacked in the
    # cube — the top of the cube becomes the top of the pile.
    by_height = sorted(contents,
                       key=lambda i: (boxes[i][2] + boxes[i][5]) / 2)
    layer_of = {i: min(FILL_LAYERS - 1, n * FILL_LAYERS // max(1, len(contents)))
                for n, i in enumerate(by_height)}
    for n, i in enumerate(contents):
        uh, yh = frames[i] or ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        b = boxes[i]
        c = ((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2)
        u0, u1, y0, y1 = ranges[i]
        half_u = (u1 - u0) * FILL_SCALE / 2
        half_y = (y1 - y0) * FILL_SCALE / 2

        # keep the heading it already had, flattened — a run lying east-west in
        # the cube lies east-west in the box, so the turn is the shortest one
        # that gets it face up rather than a random spin
        th = math.atan2(uh[1], uh[0]) + (rng() - 0.5) * 0.5
        ut = (math.cos(th), math.sin(th), 0.0)
        yt = (-ut[1], ut[0], 0.0)
        layer = layer_of[i]
        z = Z0 + H * (FILL_FLOOR + (FILL_HEAD - FILL_FLOOR)
                      * (layer + 0.15 + rng() * 0.7) / FILL_LAYERS)
        reach = math.sqrt(half_u ** 2 + half_y ** 2)
        rx = max(2.0, HW - 6 - reach)
        ry = max(2.0, HD - 6 - reach)
        # its own place in the cube's footprint, squeezed into the box's
        jit = 0.12
        pos = (max(-rx, min(rx, c[0] / SPAN * rx + (rng() * 2 - 1) * rx * jit)),
               max(-ry, min(ry, c[1] / SPAN * ry + (rng() * 2 - 1) * ry * jit)),
               z)
        # the contents are inside the box; shutting the lid does not move them
        out[i] = sealed[i] = pos + (FILL_SCALE,) + _quat(uh, yh, ut, yt)

    return out, sealed, flap, len(boxes) - len(contents), edges
