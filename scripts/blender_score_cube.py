"""Build the cube for real in Blender, from the same recipe the browser gets.

This is the second recorder for `score_scene/recipe.py`. Every mark the web
exporter ships as an instanced quad, this one builds as actual geometry, so the
model can be looked at, lit and rendered offline — and so a change to the recipe
shows up in both places at once. There is no separate Blender layout any more;
if this render and the live page disagree, one of the two recorders is wrong,
which is a much smaller thing to go and find.

Each piece becomes its own object with its origin at its own centroid, which is
what lets it be flung out and brought back without deforming.

    blender --background --python scripts/blender_score_cube.py -- [out.png] [seed]
"""
import bpy, bmesh, sys, json, math, os                            # noqa: E402
from mathutils import Vector as BV, Matrix as BM                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from score_scene import recipe                                    # noqa: E402
from score_scene.recipe import SS, SPAN, GAP, STRATA, EM, UPM     # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
GLYPHS = os.path.join(HERE, "score_scene")
OUT = argv[0] if argv else os.path.join(GLYPHS, "cube.png")
SEED = int(argv[1]) if len(argv) > 1 else recipe.SEED
INK_TH = 0.45                     # extrusion thickness of the ink

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

ink = bpy.data.materials.new("Ink")
ink.use_nodes = True
_nt = ink.node_tree
_nt.nodes.clear()
_em = _nt.nodes.new("ShaderNodeEmission")
_em.inputs[0].default_value = (0.012, 0.008, 0.006, 1)
_nt.links.new(_em.outputs[0], _nt.nodes.new("ShaderNodeOutputMaterial").inputs[0])

# ── glyph curve templates from the Leland SVGs ───────────────────────────────
BOUNDS = json.load(open(os.path.join(GLYPHS, "glyph-bounds.json")))


def load_glyph(name):
    """One template per glyph, normalised so a font em is EM units tall with
    its origin on the baseline at the left sidebearing — the same
    normalisation `export_score_glyphs.py` bakes into the browser's protos."""
    before = set(bpy.data.objects)
    bpy.ops.import_curve.svg(filepath=os.path.join(GLYPHS, "glyph-%s.svg" % name))
    curves = [o for o in bpy.data.objects if o not in before and o.type == "CURVE"]
    bpy.ops.object.select_all(action="DESELECT")
    for o in curves:
        o.select_set(True)
    bpy.context.view_layer.objects.active = curves[0]
    if len(curves) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = "glyph_%s" % name
    cu = ob.data
    cu.dimensions = "2D"
    cu.fill_mode = "BOTH"
    cu.extrude = 0.0
    cu.resolution_u = 12
    cu.materials.clear()
    cu.materials.append(ink)
    # Measure the curve's own control points: object dimensions are stale in
    # background mode until the depsgraph updates.
    xs, ys = [], []
    for sp in cu.splines:
        for bp in sp.bezier_points:
            xs.append(bp.co.x); ys.append(bp.co.y)
        for pp in sp.points:
            xs.append(pp.co.x); ys.append(pp.co.y)
    cur_h = (max(ys) - min(ys)) if ys else 1.0
    _, ymin, _, ymax = BOUNDS[name]
    s = ((ymax - ymin) / UPM * EM) / cur_h if cur_h > 0 else 1.0
    cu.transform(BM.Scale(s, 4))
    cu.transform(BM.Translation(BV((-min(xs) * s, ymin / UPM * EM - min(ys) * s, 0))))
    ob.matrix_world = BM.Identity(4)
    ob.hide_render = ob.hide_viewport = True
    return ob


TMPL = {n: load_glyph(n) for n in
        ("treble", "bass", "head", "flag8", "headopen", "sharp", "flat",
         "rest4", "rest8")}


def mat(M):
    """The recipe's shim matrix as a mathutils one. Both are row-major, and the
    recipe has already put itself in Blender's axes inside `frame`."""
    return BM(M.m)


class BlenderRecorder:
    """Records the recipe as real geometry, one object per movable piece."""

    def __init__(self):
        self.pieces = []           # (bmesh, [glyph objects])
        self._bm = None
        self._glyphs = None

    def piece(self):
        self._close()
        self._bm, self._glyphs = bmesh.new(), []

    def _close(self):
        if self._bm is None:
            return
        if len(self._bm.verts) or self._glyphs:
            self.pieces.append((self._bm, self._glyphs))
        else:
            self._bm.free()
        self._bm = self._glyphs = None

    def box(self, mat_world, length, width, cx, cy):
        """A slab in the fragment's local frame: x along the staff, y across it
        (the line's thickness), extruded through the page in z."""
        bm, M = self._bm, mat(mat_world)
        hx, hy, hz = length / 2, width / 2, INK_TH / 2
        v = [bm.verts.new(M @ BV((cx + dx, cy + dy, dz)))
             for dx in (-hx, hx) for dy in (-hy, hy) for dz in (-hz, hz)]
        for a, b, c, d in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 2, 6, 4),
                           (1, 5, 7, 3), (0, 4, 5, 1), (2, 3, 7, 6)):
            try:
                bm.faces.new((v[a], v[b], v[c], v[d]))
            except ValueError:
                pass                       # a degenerate run; the rest stands
    def glyph(self, name, mat_world, lx, ly, scale=1.0, sx=1.0, rot=0.0):
        ob = TMPL[name].copy()             # linked data — one curve, many uses
        ob.hide_render = ob.hide_viewport = False
        m = mat(mat_world) @ BM.Translation(BV((lx, ly, 0)))
        if scale != 1.0:
            m = m @ BM.Scale(scale, 4)
        if sx != 1.0:                      # heads are wider than they are tall
            m = m @ BM.Scale(sx, 4, (1, 0, 0))
        if rot:
            m = m @ BM.Rotation(rot, 4, 'Z')
        ob.matrix_world = m
        self._glyphs.append(ob)

    def done(self):
        self._close()
        return self.pieces


rec = BlenderRecorder()
recipe.compose(rec, seed=SEED)
PIECES = rec.done()
print("pieces:", len(PIECES))

# ── one object per piece, origin at its own centroid ─────────────────────────
for pi, (pbm, pglyphs) in enumerate(PIECES):
    if len(pbm.verts):
        co = [v.co.copy() for v in pbm.verts]
        cen = sum(co, BV()) / len(co)
    elif pglyphs:
        cen = sum((g.matrix_world.translation for g in pglyphs), BV()) / len(pglyphs)
    else:
        pbm.free()
        continue
    me = bpy.data.meshes.new("p%d" % pi)
    if len(pbm.verts):
        bmesh.ops.translate(pbm, verts=pbm.verts, vec=-cen)
        pbm.to_mesh(me)
        me.materials.append(ink)
    pbm.free()
    ob = bpy.data.objects.new("p%d" % pi, me)
    ob.location = cen
    scene.collection.objects.link(ob)
    for g in pglyphs:                      # glyphs ride their piece
        gm = g.matrix_world.copy()
        scene.collection.objects.link(g)
        g.parent = ob
        g.matrix_parent_inverse = BM.Translation(-cen)
        # matrix_basis, NOT matrix_world. Assigning matrix_world here resolves
        # it against whatever the parent's matrix says right now, and in
        # background mode that is still the identity — the piece's own centroid
        # then gets applied twice and every glyph in the model lands at double
        # its offset. The parent chain is T(cen) @ T(-cen) == identity by
        # construction, so the basis IS the world matrix and no depsgraph
        # round-trip is needed to know it.
        g.matrix_basis = gm

# ── camera + world + render ──────────────────────────────────────────────────
cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.ortho_scale = float(os.environ.get("ORTHO", 815))
cam_data.clip_start, cam_data.clip_end = 1.0, 20000.0
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
center = BV((0, 0, -(STRATA - 1) * GAP / 2))
az, el, r = 0.785, 0.235, 2000
cam.location = center + BV((math.sin(az) * math.cos(el) * r,
                            -math.cos(az) * math.cos(el) * r,
                            math.sin(el) * r))
cam.rotation_euler = (center - cam.location).normalized().to_track_quat('-Z', 'Y').to_euler()

world = bpy.data.worlds.new("paper")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.878, 0.837, 0.762, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

scene.render.engine = "CYCLES"
scene.view_settings.view_transform = "Standard"   # AgX grays the cream
scene.cycles.samples = int(os.environ.get("SAMPLES", 48))
scene.cycles.use_denoising = False
scene.render.resolution_x = int(os.environ.get("RESX", 1400))
scene.render.resolution_y = int(os.environ.get("RESY", 2100))
scene.render.filepath = OUT
scene.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(GLYPHS, "cube.blend"))
print("rendered:", OUT, "| saved", os.path.join(GLYPHS, "cube.blend"))
