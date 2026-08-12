"""Triangulate the Leland glyph outlines once, so the browser can instance them.

Same normalisation as build_cube.load_glyph: one font em == EM units, origin at
the glyph's baseline/left. Emits score_scene/glyph-protos.json:
    {name: {"v": [x,y, x,y, ...], "i": [a,b,c, ...]}}

Run: blender --background --python scripts/export_score_glyphs.py
"""
import bpy, bmesh, json, os
from mathutils import Matrix, Vector

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "score_scene")
SS, EM, UPM = 2.0, 8.0, 1000.0
BOUNDS = json.load(open(os.path.join(HERE, "glyph-bounds.json")))
NAMES = ("treble", "bass", "head", "flag8", "headopen", "sharp", "flat", "rest4", "rest8")

bpy.ops.wm.read_factory_settings(use_empty=True)
out = {}

for name in NAMES:
    before = set(bpy.data.objects)
    bpy.ops.import_curve.svg(filepath=os.path.join(HERE, f"glyph-{name}.svg"))
    curves = [o for o in bpy.data.objects if o not in before and o.type == "CURVE"]
    bpy.ops.object.select_all(action="DESELECT")
    for o in curves:
        o.select_set(True)
    bpy.context.view_layer.objects.active = curves[0]
    if len(curves) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    cu = ob.data
    cu.dimensions = "2D"
    cu.fill_mode = "BOTH"
    cu.extrude = 0.0
    cu.resolution_u = 12

    xs, ys = [], []
    for sp in cu.splines:
        for bp in sp.bezier_points:
            xs.append(bp.co.x); ys.append(bp.co.y)
        for pp in sp.points:
            xs.append(pp.co.x); ys.append(pp.co.y)
    cur_h = (max(ys) - min(ys)) if ys else 1.0
    xmin, ymin, xmax, ymax = BOUNDS[name]
    s = ((ymax - ymin) / UPM * EM) / cur_h if cur_h > 0 else 1.0
    cu.transform(Matrix.Scale(s, 4))
    cu.transform(Matrix.Translation(Vector((-min(xs) * s, ymin / UPM * EM - min(ys) * s, 0))))
    ob.matrix_world = Matrix.Identity(4)

    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.convert(target="MESH")
    me = bpy.context.view_layer.objects.active.data

    bm = bmesh.new()
    bm.from_mesh(me)
    # the fill produces a front and a back face at z=0; keep one sheet only
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.verts.ensure_lookup_table()
    v = []
    for vt in bm.verts:
        v += [round(vt.co.x, 4), round(vt.co.y, 4)]
    idx = []
    for f in bm.faces:
        idx += [lv.vert.index for lv in f.loops]
    bm.free()
    out[name] = {"v": v, "i": idx}
    print("%-10s verts %5d  tris %5d" % (name, len(v) // 2, len(idx) // 3))

json.dump(out, open(os.path.join(HERE, "glyph-protos.json"), "w"))
print("total tris:", sum(len(g["i"]) // 3 for g in out.values()))
