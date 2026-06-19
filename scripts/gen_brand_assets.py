#!/usr/bin/env python3
"""Regenerate the Chordential phone/app icons from the real brand wordmark.

The app icon shows the full "chordential" wordmark (knockout/white from
static/logo.png) on a dark charcoal tile — matching the in-app sidebar lockup
and staying legible on the Home Screen, where the plain white wordmark washed
out on a light tile.

Light-background surfaces (the capabilities PDF, browser tabs) use the wine
wordmark (static/public/wordmark-dark.png) directly — no derived asset.

Bump ICON_VERSION whenever the icon art changes, then update the ?v= query on
the icon URLs (base.html apple-touch link + the manifest in app.py) so iOS
re-fetches instead of serving a cached tile.

Run from the repo root:  python scripts/gen_brand_assets.py
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "src", "chordential_oia", "web", "static")
WORDMARK_KO = os.path.join(STATIC, "logo.png")   # white knockout wordmark
CHARCOAL = (31, 30, 30)                           # --ink, matches the sidebar

ICON_VERSION = 3   # keep in sync with the ?v= on the icon URLs


def make_wordmark_icon(wordmark: Image.Image, size: int) -> Image.Image:
    """Full wordmark centered on a dark charcoal tile (full-bleed → maskable-safe)."""
    tile = Image.new("RGBA", (size, size), CHARCOAL + (255,))
    target_w = int(size * 0.82)
    ratio = target_w / wordmark.width
    w2, h2 = target_w, max(1, int(wordmark.height * ratio))
    m = wordmark.resize((w2, h2), Image.LANCZOS)
    tile.alpha_composite(m, ((size - w2) // 2, (size - h2) // 2))
    return tile.convert("RGB")


def main() -> None:
    wordmark = Image.open(WORDMARK_KO).convert("RGBA")
    for name, size in [("icon-512.png", 512), ("icon-192.png", 192),
                       ("apple-touch-icon.png", 180)]:
        make_wordmark_icon(wordmark, size).save(os.path.join(STATIC, name))
        print(f"wrote {name} ({size}x{size})")


if __name__ == "__main__":
    main()
