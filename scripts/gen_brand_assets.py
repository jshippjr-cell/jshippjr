#!/usr/bin/env python3
"""Regenerate the Chordential phone/app icons from the real brand logo.

The master wordmark (static/public/wordmark-dark.png — the wine "chordential"
with the orange mark, from the uploaded Echo artwork) reads fine on light
surfaces, but its white knockout twin washed out on the phone home-screen tile.
This script crops the orange mark from the real logo and sets it on a dark
charcoal tile, so the app icon is high-contrast and on-brand at small sizes.

Light-background surfaces (the capabilities PDF, browser tabs) use the real
wordmark directly — no derived asset.

Run from the repo root:  python scripts/gen_brand_assets.py
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "src", "chordential_oia", "web", "static")
SOURCE = os.path.join(STATIC, "public", "wordmark-dark.png")
CHARCOAL = (31, 30, 30)     # --ink, matches the sidebar


def crop_mark(src: Image.Image) -> Image.Image:
    """Bounding box of the *bright* orange mark (excludes the faint reflection)."""
    w, h = src.size
    xs, ys = [], []
    for i, (r, g, b, a) in enumerate(src.getdata()):
        if a > 170 and r > 180 and b < 115 and 40 < g < 175:
            xs.append(i % w)
            ys.append(i // w)
    pad = 14
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
    src = Image.open(SOURCE).convert("RGBA")
    mark = crop_mark(src)
    for name, size in [("icon-512.png", 512), ("icon-192.png", 192),
                       ("apple-touch-icon.png", 180)]:
        make_icon(mark, size).save(os.path.join(STATIC, name))
        print(f"wrote {name} ({size}x{size})")


if __name__ == "__main__":
    main()
