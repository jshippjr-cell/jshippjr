#!/usr/bin/env python3
"""Regenerate Chordential brand assets so the logo never disappears.

The master logo (static/logo.png) is a *white* wordmark with an orange mark —
made for the dark sidebar. On light surfaces (the capabilities PDF, a browser
tab) the white letters vanish, and on the phone home-screen tile the whole mark
washes out. This script derives, from that one master, the variants those
surfaces need:

  - logo-dark.png   the wordmark recolored to ink (#1F1E1E) for LIGHT backgrounds,
                    keeping the orange mark + its reflection.
  - icon-512/192/apple-touch  the orange mark on a dark charcoal tile, so the app
                    icon is high-contrast and on-brand at small sizes.

Run from the repo root:  python scripts/gen_brand_assets.py
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "src", "chordential_oia", "web", "static")
INK = (31, 30, 30)          # --ink
CHARCOAL = (31, 30, 30)     # icon tile background (matches sidebar)


def _is_orange(r, g, b):
    """The orange mark + its peach reflection (warm: red dominates blue)."""
    return r > 150 and b < 150 and g < 205 and (r - b) > 55


def make_dark_wordmark(src: Image.Image) -> Image.Image:
    """Recolor the white letters to ink for light backgrounds; keep the orange."""
    out = []
    for (r, g, b, a) in src.getdata():
        if a == 0:
            out.append((0, 0, 0, 0))
        elif _is_orange(r, g, b):
            out.append((r, g, b, a))                 # keep the orange mark/reflection
        else:
            out.append((INK[0], INK[1], INK[2], a))  # white letters -> ink
    img = Image.new("RGBA", src.size)
    img.putdata(out)
    return img


def crop_mark(src: Image.Image) -> Image.Image:
    """Bounding box of the *bright* orange mark (excludes the faint reflection)."""
    w, h = src.size
    xs, ys = [], []
    for i, (r, g, b, a) in enumerate(src.getdata()):
        if a > 170 and r > 180 and b < 115 and 40 < g < 175:
            xs.append(i % w)
            ys.append(i // w)
    pad = 12
    box = (max(0, min(xs) - pad), max(0, min(ys) - pad),
           min(w, max(xs) + pad), min(h, max(ys) + pad))
    return src.crop(box)


def make_icon(mark: Image.Image, size: int) -> Image.Image:
    """Orange mark centered on a dark charcoal tile (full-bleed → maskable-safe)."""
    tile = Image.new("RGBA", (size, size), CHARCOAL + (255,))
    target = int(size * 0.56)
    ratio = target / max(mark.size)
    m = mark.resize((max(1, int(mark.size[0] * ratio)),
                     max(1, int(mark.size[1] * ratio))), Image.LANCZOS)
    tile.alpha_composite(m, ((size - m.size[0]) // 2, (size - m.size[1]) // 2))
    return tile.convert("RGB")


def main() -> None:
    src = Image.open(os.path.join(STATIC, "logo.png")).convert("RGBA")

    make_dark_wordmark(src).save(os.path.join(STATIC, "logo-dark.png"))
    print("wrote logo-dark.png")

    mark = crop_mark(src)
    for name, size in [("icon-512.png", 512), ("icon-192.png", 192),
                       ("apple-touch-icon.png", 180)]:
        make_icon(mark, size).save(os.path.join(STATIC, name))
        print(f"wrote {name} ({size}x{size})")


if __name__ == "__main__":
    main()
