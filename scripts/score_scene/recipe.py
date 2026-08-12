"""The cube of engraved notation — ONE recipe, several reporters.

Where the marks go is decided here and nowhere else. `compose(rec)` walks the
whole model and calls back into a recorder:

    rec.piece()                              start a new movable piece
    rec.box(M, length, width, cx, cy)        a rule, stem, beam, barline, ledger
    rec.glyph(name, M, lx, ly, scale, sx, rot)   a Leland outline

`scripts/build_score_scene.py` records marks and ships them to the browser;
`scripts/blender_score_cube.py` records real geometry and renders the still.
They were three copies of these 300 lines until 2026-08-12, and the copies had
already drifted: staves hung out of the web cube by up to 125 units — 42% of
the cube's own width — while the Blender file they were judged in did not
change at all. Add a surface, add a recorder; never a second copy of the
recipe.

Coordinates are the canvas engine's: x right, y up, z depth. A staff space is
SS = 2.0, so a staff is 8 tall; the cube is SPAN*2 = 300 wide and 600 tall.
Glyphs are true Leland outlines (em == staff height == 8).
"""
import math

SEED = 20260810

SS = 2.0
SPAN = 150.0
GAP = 100.0
STRATA = 6
EM = 4 * SS
UPM = 1000.0

# The cube itself. Every mark lives in here; `fit` and `seat` are what keep
# that true rather than hopeful.
TOP, BOTTOM = GAP * 0.5, -(STRATA - 1) * GAP - GAP * 0.5
BOXMIN = (-SPAN, BOTTOM, -SPAN)
BOXMAX = (SPAN, TOP, SPAN)
CENTER = (0.0, 0.0, -(STRATA - 1) * GAP / 2)   # in the browser's axis order

# ── minimal linear algebra (mathutils shim, row-major 4x4) ───────────────────
class Vector:
    __slots__ = ("x", "y", "z")
    def __init__(self, t):
        self.x, self.y, self.z = float(t[0]), float(t[1]), float(t[2])
    def cross(self, o):
        return Vector((self.y * o.z - self.z * o.y,
                       self.z * o.x - self.x * o.z,
                       self.x * o.y - self.y * o.x))
    @property
    def length(self):
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)
    def normalized(self):
        n = self.length or 1.0
        return Vector((self.x / n, self.y / n, self.z / n))

class Matrix:
    __slots__ = ("m",)
    def __init__(self, rows):
        self.m = [list(r) for r in rows]
    def __matmul__(self, o):
        a = self.m
        if isinstance(o, Vector):
            v = (o.x, o.y, o.z, 1.0)
            return Vector(tuple(sum(a[i][k] * v[k] for k in range(4)) for i in range(3)))
        b = o.m
        return Matrix([[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
                       for i in range(4)])
    @staticmethod
    def Identity(_n):
        return Matrix([[1 if i == j else 0 for j in range(4)] for i in range(4)])
    @staticmethod
    def Translation(v):
        M = Matrix.Identity(4)
        M.m[0][3], M.m[1][3], M.m[2][3] = v.x, v.y, v.z
        return M
    @staticmethod
    def Scale(s, _n, axis=None):
        M = Matrix.Identity(4)
        if axis is None:
            M.m[0][0] = M.m[1][1] = M.m[2][2] = s
        else:
            for i, a in enumerate(axis):
                if a:
                    M.m[i][i] = s
        return M
    @staticmethod
    def Rotation(a, _n, ax):
        c, s = math.cos(a), math.sin(a)
        M = Matrix.Identity(4)
        if ax == 'Z':
            M.m[0][0], M.m[0][1], M.m[1][0], M.m[1][1] = c, -s, s, c
        return M

class Rng:
    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF
    def __call__(self):
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s & 0xFFFFFFFF
        return self.s / 4294967296.0

def frame(basis, pos):
    U, V = basis
    Ub = Vector((U[0], U[2], U[1]))
    Vb = Vector((V[0], V[2], V[1]))
    P = Vector((pos[0], pos[2], pos[1]))
    Yl = Vector((-Vb.x, -Vb.y, -Vb.z))
    Zl = Ub.cross(Yl).normalized()
    return Matrix(((Ub.x, Yl.x, Zl.x, P.x),
                   (Ub.y, Yl.y, Zl.y, P.y),
                   (Ub.z, Yl.z, Zl.z, P.z),
                   (0, 0, 0, 1)))

FLOOR = ([1, 0, 0], [0, 0, 1])
WALLXZ = ([1, 0, 0], [0, -1, 0])
WALLZY = ([0, 0, 1], [0, -1, 0])

# ── containment ──────────────────────────────────────────────────────────────
# A run of notation is placed by (position, direction, length). Left alone, the
# generators below happily start a 190-unit staff 100 units from the far wall,
# and it hangs out of the cube like a plank off a truck. `fit` intersects the
# run with the box and slides it back along its OWN axis until it fits — the
# staff keeps its length wherever the cube is wide enough to hold it, and is
# only shortened when it genuinely cannot fit. Nothing is dropped: the cloud's
# density comes from the recipe, not from which runs happened to fall inside.
# Notation occupies a band either side of the line it is written on: stems and
# flags hang about 20 below the top staff line, beamed groups reach about 15
# above it. Measured off the recipe below, not guessed.
FIT_PAD = 1.5          # the last barline/flag of a fragment lands about here
BAND_STAFF = (20.0, 16.0)      # a fragment, under/over its own top line
BAND_SLAB = (16.0, 2.0)        # a beam bundle with its notes hanging below
BAND_CLEF = (12.0, 6.0)        # a clef, its stub staff and that staff's notes
BAND_MARK = (8.0, 12.0)        # a loose field mark — the tallest is a clef


def _step(pos, U, t):
    return (pos[0] + U[0] * t, pos[1] + U[1] * t, pos[2] + U[2] * t)


def _chord(U, pos, pad):
    """The interval of t for which pos + t*U is inside the cube."""
    tmin, tmax = -1e9, 1e9
    for i in range(3):
        d = U[i]
        if abs(d) < 1e-9:
            continue                      # this axis is not traversed at all
        a = (BOXMIN[i] + pad - pos[i]) / d
        b = (BOXMAX[i] - pad - pos[i]) / d
        if a > b:
            a, b = b, a
        tmin = max(tmin, a)
        tmax = min(tmax, b)
    return tmin, tmax


def fit(basis, pos, length, pad=FIT_PAD):
    """Slide (and only if it must, shorten) a run so it lies inside the cube.

    Returns (pos', length'). Positions are canvas coordinates; the run travels
    from pos' along basis[0] for length'.
    """
    U = basis[0]
    tmin, tmax = _chord(U, pos, pad)
    if tmax - tmin < length:              # the chord is shorter than the run
        return _step(pos, U, tmin), max(0.0, tmax - tmin)
    return _step(pos, U, min(max(0.0, tmin), tmax - length)), length


def seat(basis, pos, lo, hi, across=False, pad=FIT_PAD):
    """Shift a placement along its own frame so the interval [lo, hi] it
    occupies lands inside the cube. Returns the shifted anchor.

    `across=True` shifts perpendicular to the run instead — local +y, which is
    up the staff. That is the axis a stem hangs off, and the one that put the
    bottom rows of notation through the floor of the box.
    """
    U = basis[0] if not across else (-basis[1][0], -basis[1][1], -basis[1][2])
    tmin, tmax = _chord(U, pos, pad)
    if tmax - tmin < hi - lo:             # cannot fit; centre what we can
        return _step(pos, U, (tmin + tmax) / 2 - (lo + hi) / 2)
    return _step(pos, U, min(max(0.0, tmin - lo), tmax - hi))

LINE_W   = 0.13 * SS
W_LEDGER = 0.13 * SS
W_STEM   = 0.19 * SS
W_BAR    = 0.19 * SS
W_BEAM   = 0.62 * SS

def compose(rec, seed=SEED):
    """Walk the model, reporting every mark to `rec`."""
    begin_piece = rec.piece

    def add_box(mat_world, length, width, cx, cy):
        rec.box(mat_world, length, width, cx, cy)

    def place_glyph(name, mat_world, lx, ly, scale=1.0, sx=1.0, rot=0.0):
        rec.glyph(name, mat_world, lx, ly, scale, sx, rot)

    def fragment(basis, pos, length, rand, dense=False, bare_floor=False):
        begin_piece()
        pos = seat(basis, pos, -BAND_STAFF[0], BAND_STAFF[1], across=True)
        pos, length = fit(basis, pos, length)
        M = frame(basis, pos)
        bareP = 0.0 if dense else (0.34 if bare_floor else 0.24)
        for l in range(5):
            add_box(M, length, LINE_W, length / 2, -l * SS)
        px = 22.0 if rand() < 0.18 else 3.0
        if px > 3.0:
            which = "treble" if rand() < 0.42 else "bass"
            base = -3 * SS if which == "treble" else -1 * SS
            place_glyph(which, M, 2.0, base, scale=1.0)
        while px < length - 8:
            if rand() < bareP:
                px += 14 + rand() * 22
                continue
            r0 = rand()
            grouped = 1 if r0 < 0.26 else (2 if r0 < 0.42 else (3 if r0 < 0.56 else (4 if r0 < 0.72 else (6 if r0 < 0.88 else 8))))
            group = []
            g = 0
            while g < grouped and px < length - 8:
                group.append((px, (-3.2 + rand() * 10.4) * (SS / 2)))
                px += 3.9 + rand() * 2.4
                g += 1
            if not group:
                break
            tipA = group[0][1] - 11.0
            tipB = group[-1][1] - 11.0
            for gi, (nx, nz) in enumerate(group):
                place_glyph("head" if len(group) > 1 or rand() > 0.10 else "headopen",
                            M, nx, -nz, scale=1.45, sx=1.7)
                down = nz < -0.4 * SS
                if len(group) > 1:
                    stem = tipA + (tipB - tipA) * (gi / max(1, len(group) - 1))
                else:
                    stem = nz + (8 + rand() * 3) if down else nz - 8 - rand() * 3
                x_st = nx + (0.0 if down else 2.55)
                add_box(M, W_STEM, abs(stem - nz), x_st, -(stem + nz) / 2)
                if len(group) == 1 and rand() < 0.8:
                    place_glyph("flag8", M, x_st - LINE_W * 0.45, -stem)
            if len(group) > 1:
                n_beams = 2 if rand() < 0.55 else 1
                x1, x2 = group[0][0] + 2.2, group[-1][0] + 2.2 + LINE_W * 0.45
                for r in range(n_beams):
                    frac = 1.0 if r == 0 else (0.45 + rand() * 0.55)
                    zb = (tipA + tipB) / 2 + r * 2.6
                    dxl = (x2 - x1) * frac
                    ang = math.atan2(tipB - tipA, dxl)
                    cmat = M @ Matrix.Translation(Vector(((x1 + x2) / 2, -zb, 0))) @ Matrix.Rotation(-ang, 4, 'Z')
                    add_box(cmat, math.hypot(dxl, tipB - tipA), W_BEAM, 0, 0)
            px += 3 + rand() * 7
            if rand() < 0.55 and px < length - 10:
                add_box(M, W_BAR, 4.8 * SS, px, -2 * SS)
                px += 5

    def slab(basis, pos, length, rand):
        begin_piece()
        pos = seat(basis, pos, -BAND_SLAB[0], BAND_SLAB[1], across=True)
        pos, length = fit(basis, pos, length)
        M = frame(basis, pos)
        for r in range(2):
            add_box(M, length, W_BEAM, length / 2, -(2 + r * 3.0))
        n = 5 + int(rand() * 4)
        for k in range(n):
            hx = 2 + (length - 6) * k / (n - 1)
            hy = -(2 + 8.0) + (rand() - .5) * 3.2 * SS
            add_box(M, W_STEM, abs(hy + 2), hx + 2.55, (hy - 2) / 2)
            place_glyph("head", M, hx, hy, scale=1.45, sx=1.7)

    rand = Rng(seed)

    # floors
    for s in range(STRATA):
        y = -s * GAP
        rows = 3 if s == 0 else 4
        for k in range(rows):
            z = -SPAN + 22 + k * ((SPAN * 2 - 44) / (rows - 1))
            x = -SPAN + 4 + rand() * 16
            while x < SPAN - 60:
                ln = 74 + rand() * 66
                fragment(FLOOR, (x, y, z), ln, rand, bare_floor=True)
                x += ln + 2 + rand() * 6

    # walls + slabs + weave fill
    top, bottom = TOP, BOTTOM
    rows = round((top - bottom) / 56)
    for face in range(4):
        side = -1 if face % 2 == 0 else 1
        vertical = face < 2
        basis = WALLXZ if vertical else WALLZY
        for r in range(rows):
            wy = top - (top - bottom) * (0.11 + 0.78 * (r + (rand() - .5) * 0.6) / max(1, rows - 1))
            a = -SPAN - 18 + rand() * 26
            while a < SPAN - 46:
                ln = 104 + rand() * 86
                pos = (a, wy, side * SPAN) if vertical else (side * SPAN, wy, a)
                if rand() > 0.30:
                    fragment(basis, pos, ln, rand)
                a += ln + 2 + rand() * 6
            if (rand() < 0.30 or r in (0, rows - 2)) and r < rows - 1:
                sa = -SPAN + 6 if rand() < 0.5 else SPAN - 64
                spos = (sa, wy - 3, side * SPAN) if vertical else (side * SPAN, wy - 3, sa)
                slab(basis, spos, 58 + rand() * 44, rand)
            if r < rows - 1 and rand() < 0.85:
                gy = wy - ((top - bottom) / rows) * (0.35 + rand() * 0.3)
                gpos = (-SPAN + 30 + rand() * SPAN * 1.5, gy, side * SPAN) if vertical \
                    else (side * SPAN, gy, -SPAN + 30 + rand() * SPAN * 1.5)
                fragment(basis, gpos, 22 + rand() * 26, rand, dense=True)

    # clef columns
    cols = [(SPAN - 6, -SPAN + 6, WALLXZ),
            (SPAN - 6, SPAN - 6, WALLZY),
            (-SPAN + 6, -SPAN + 6, WALLXZ)]
    for ci, (cx, cz, cbasis) in enumerate(cols):
        # A clef governs a staff, and the staff has to have somewhere to go. Reserve
        # the longest run this column can draw (stub 25 + its barline, on whichever
        # side of the clef this column writes) and slide the whole column inward
        # until that room exists — clef and staff move together, so the assembly is
        # never taken apart to make it fit.
        lo = -(15 + 25.0) if ci == 1 else 0.0
        hi = 6.0 if ci == 1 else (11 * 1.15 + 25.0 + W_BAR)
        for e in range(30):
            begin_piece()
            cy = top - 12 - (e + (rand() - .5) * 0.9) * ((top - bottom - 34) / 29)
            anchor = seat(cbasis, (cx, cy, cz), lo, hi)
            anchor = seat(cbasis, anchor, -BAND_CLEF[0], BAND_CLEF[1], across=True)
            M = frame(cbasis, anchor)
            which = "bass" if rand() < 0.28 else "treble"
            base = -3 * SS if which == "treble" else -1 * SS
            sc = 0.95 + rand() * 0.2
            place_glyph(which, M, 0, base * sc, scale=sc, rot=(rand() - .5) * 0.16)
            stub = 15 + rand() * 10
            x0 = -(15 + stub) if ci == 1 else 11 * sc
            for l in range(5):
                add_box(M, stub, LINE_W, x0 + stub / 2, -l * SS)
            add_box(M, W_BAR, 4.3 * SS, x0 + stub, -2 * SS)
            for h in range(2):
                hy = -(1 + h) * SS
                place_glyph("head", M, x0 + stub * (0.28 + 0.34 * h), hy, scale=1.45, sx=1.7)
                add_box(M, W_STEM, 7.5, x0 + stub * (0.28 + 0.34 * h) + 2.55, hy + 3.75)

    # heavy structural bands
    for (by, tag) in [(top - 6, "t"), (bottom + 6, "b"),
                      (top - (top - bottom) * 0.34, "m1"),
                      (top - (top - bottom) * 0.62, "m2")]:
        for face in range(4):
            side = -1 if face % 2 == 0 else 1
            vertical = face < 2
            basis = WALLXZ if vertical else WALLZY
            pos = (-SPAN + 8, by, side * SPAN) if vertical else (side * SPAN, by, -SPAN + 8)
            rim = tag in ('t', 'b')
            if tag == 'b' and face > 1:
                continue
            segs = 2 + int(rand() * 3)
            cur = 8.0
            for sgi in range(segs):
                seglen = (SPAN * 2 - 30) / segs * (0.45 + rand() * 0.4)
                if cur + seglen > SPAN * 2 - 12:
                    break
                begin_piece()
                spos = seat(basis, _step(pos, basis[0], cur), -9.0, 1.0, across=True)
                spos, slen = fit(basis, spos, seglen)
                Mb = frame(basis, spos)
                if rim:
                    for r in range(5):
                        add_box(Mb, slen, LINE_W, slen / 2, -r * SS)
                else:
                    for r in range(4):
                        add_box(Mb, slen, W_BEAM, slen / 2, -r * 1.55)
                cur += seglen + 18 + rand() * 30

    # field fill — these are the particles
    for face in range(4):
        side = -1 if face % 2 == 0 else 1
        vertical = face < 2
        basis = WALLXZ if vertical else WALLZY
        holes = [(-SPAN + rand() * SPAN * 2, top - rand() * (top - bottom), 60 + rand() * 40)
                 for _ in range(3)]
        for _ in range(78):
            a = -SPAN + rand() * SPAN * 2
            fy = top - (top - bottom) * (0.13 + rand() * 0.74)
            if any(abs(a - hx) < hr and abs(fy - hy) < hr * 0.7 for hx, hy, hr in holes):
                continue
            pos = (a, fy, side * SPAN) if vertical else (side * SPAN, fy, a)
            # a field mark is small but not a point: the widest of them (a run of
            # hairlines, a ledger and its dot) reaches about 16 either side of its
            # anchor, so seat it that far in from the wall it is scattered across
            fpos = seat(basis, pos, -16.0, 16.0)
            M = frame(basis, seat(basis, fpos, -BAND_MARK[0], BAND_MARK[1], across=True))
            begin_piece()
            rr = rand()
            if rr < 0.34:
                place_glyph("head", M, 0, 0, scale=0.8 + rand() * 0.35)
            elif rr < 0.50:
                place_glyph("flag8", M, 0, 0, scale=0.8 + rand() * 0.5)
            elif rr < 0.60:
                place_glyph("bass" if rand() < 0.45 else "treble", M, 0, 0,
                            scale=0.85 + rand() * 0.45)
            elif rr < 0.72:
                add_box(M, W_BAR, 3.4 * SS + rand() * 2 * SS, 0, 0)
            elif rr < 0.84:
                add_box(M, 2.2 * SS, W_LEDGER, 0, 0)
                if rand() < 0.6:
                    place_glyph("head", M, 2.9 * SS, 0, scale=0.42)
            else:
                Mh = M @ Matrix.Rotation((rand() - .5) * 1.2, 4, 'Z')
                for h in range(2 + int(rand() * 3)):
                    add_box(Mh, 10 + rand() * 18, LINE_W * 0.5, 0, -h * 1.5)

    # heavy rails crossing both diagonal directions
    for i in range(8):
        face = i % 4
        side = -1 if face % 2 == 0 else 1
        vertical = face < 2
        basis = WALLXZ if vertical else WALLZY
        a = (-SPAN + 12 + rand() * 50) if i % 2 else (SPAN - 62 - rand() * 50)
        fy = top - (top - bottom) * (0.18 + rand() * 0.62)
        pos = (a, fy, side * SPAN) if vertical else (side * SPAN, fy, a)
        sign = 1 if i % 2 == 0 else -1
        tilt = sign * (0.14 + rand() * 0.16)
        ln = 60 + rand() * 62
        # Fitted against the un-tilted axis: the tilt only shortens the run's reach
        # along it, so this is the conservative side of the wall. Across, though,
        # the tilt is what dominates — the far end of a 120-unit rail leaning 0.3rad
        # sits 36 above or below where it started.
        swing = ln * abs(math.sin(tilt))
        pos = seat(basis, pos, -(15.0 + swing), 1.0 + swing, across=True)
        # A rail is the one run whose notation hangs off the END: the last notehead
        # sits past the last beam, its stem past that, and the tilt swings both
        # further out again. Seat the whole reach rather than fitting the bare
        # length — a rail is short enough that there is always somewhere to put it.
        pos = seat(basis, pos, -6.0, ln + 6.0 + swing)
        Ma = frame(basis, pos) @ Matrix.Rotation(tilt, 4, 'Z')
        nb = 6 + int(rand() * 4)
        pitch = [(rand() - .5) * 3.4 * SS for _ in range(nb)]
        begin_piece()
        for r in range(2):
            add_box(Ma, ln, W_BEAM, ln / 2, -r * 3.0)
        for k in range(nb):
            hx = 2 + (ln - 6) * k / (nb - 1)
            hy = -9.0 - 1.0 + pitch[k]
            add_box(Ma, W_STEM, abs(hy + 1.0), hx + 2.55, (hy - 1.0) / 2)
            place_glyph("head", Ma, hx, hy, scale=1.45, sx=1.7)

    # implied corners
    VERT = ([0, 1, 0], [1, 0, 0])
    for (cx, cz) in [(SPAN, -SPAN), (SPAN, SPAN), (-SPAN, -SPAN), (-SPAN, SPAN)]:
        H = top - bottom
        y = bottom + 2
        while y < top - 2:
            seg = 5 + rand() * 15
            if rand() < 0.78:
                begin_piece()
                # These run UP the corner, so the only wall they can cross is the
                # lid. The dash that starts two units below it is the one that ends
                # up hanging in the air above the cube.
                vpos, vseg = fit(VERT, (cx, y, cz), seg)
                Mv = frame(VERT, vpos)
                add_box(Mv, vseg, LINE_W, vseg / 2, 0)
            y += seg + 5 + rand() * 12
        for t in range(15):
            ty = bottom + (t + 0.4 + rand() * 0.3) * H / 15
            if rand() < 0.72:
                begin_piece()
                # the corner IS the boundary, so this little assembly — ledger, its
                # note, stem, sometimes a barline — has to be seated inward by its
                # own width or it hangs off the silhouette edge, where it shows most
                tpos = seat(WALLXZ, (cx, ty, cz), -5.0, 7.0)
                Mt = frame(WALLXZ, seat(WALLXZ, tpos, -9.0, 7.0, across=True))
                w = 2.3 * SS + rand() * 1.3 * SS
                add_box(Mt, w, W_LEDGER, 0, 0)
                place_glyph("head", Mt, -0.5 * SS, 0, scale=1.0)
                add_box(Mt, W_STEM, 6.5, 1.55 * SS, 3.2)
                if rand() < 0.45:
                    add_box(Mt, W_BAR, 4.2 * SS, 2.9 * SS, -2 * SS)

    # hairline weave diagonals
    for dg in range(8):
        dv = dg % 2 == 0
        ds = -1 if dg % 4 < 2 else 1
        slope = (1 if rand() < 0.5 else -1) * (0.22 + rand() * 0.3)
        nrm = math.hypot(1, slope)
        U = [1 / nrm, slope / nrm, 0] if dv else [0, slope / nrm, 1 / nrm]
        V = [0, -1, 0]
        y0 = GAP * 0.2 - rand() * (top - bottom) * 0.8
        pos = (-SPAN + 20 + rand() * 60, y0, ds * SPAN) if dv else (ds * SPAN, y0, -SPAN + 20 + rand() * 60)
        begin_piece()
        # this one is drawn centred 80 units down its own axis, so the run it has to
        # fit is [80 - len/2, 80 + len/2] — not [0, len]
        dln = 68 + rand() * 34
        dpos, dln = fit((U, V), _step(pos, U, 80 - dln / 2), dln)
        M = frame((U, V), seat((U, V), dpos, -1.0, 1.0, across=True))
        add_box(M, dln, LINE_W * 0.6, dln / 2, 0)

    # top-face cross grid
    for g in range(5):
        gz = -SPAN + 30 + g * ((SPAN * 2 - 60) / 4)
        fragment(FLOOR, (-SPAN + 10 + rand() * 20, GAP * 0.5, gz), 210 + rand() * 60, rand)
