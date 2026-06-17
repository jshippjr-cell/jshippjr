"""Generate the front-of-house hero loop (animated WebP).

A deterministic, seamless, brand-coloured motion graphic for the hero background:
a dark warm gradient with two slowly drifting stage-light glows and a subtle
equaliser pulse along the bottom. Dark and low-contrast on purpose — the centred
headline + veil sit on top. No external assets; pure PIL.

Run:  python scripts/gen_hero_loop.py
Out:  src/chordential_oia/web/static/public/hero-loop.webp

This is a generated placeholder; drop a real .mp4 into HERO['video'] to replace it.
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFilter

W, H = 1280, 720
FRAMES = 120
FPS = 20

ORANGE = (228, 103, 31)
SLATE = (84, 102, 113)
TOP = (42, 35, 32)      # warm dark top
BOT = (18, 15, 14)      # near-black bottom


def _vertical_gradient() -> Image.Image:
    base = Image.new("RGB", (W, H))
    px = base.load()
    for y in range(H):
        t = y / (H - 1)
        r = int(TOP[0] + (BOT[0] - TOP[0]) * t)
        g = int(TOP[1] + (BOT[1] - TOP[1]) * t)
        b = int(TOP[2] + (BOT[2] - TOP[2]) * t)
        for x in range(W):
            px[x, y] = (r, g, b)
    return base


def _glow_sprite(color, size=1100, power=1.9) -> Image.Image:
    """A soft radial glow sprite (RGBA), built small then scaled + blurred."""
    s = 256
    g = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gp = g.load()
    c = (s - 1) / 2
    for y in range(s):
        for x in range(s):
            d = math.hypot(x - c, y - c) / c
            a = max(0.0, 1.0 - d) ** power
            gp[x, y] = (color[0], color[1], color[2], int(a * 255))
    g = g.resize((size, size), Image.BICUBIC).filter(ImageFilter.GaussianBlur(size / 18))
    return g


def _vignette() -> Image.Image:
    v = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(v)
    d.ellipse([-W * 0.25, -H * 0.35, W * 1.25, H * 1.35], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(120))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 130))
    inv = Image.eval(v, lambda p: 255 - p)
    dark.putalpha(inv)
    return dark


def build() -> None:
    base = _vertical_gradient()
    warm = _glow_sprite(ORANGE, 1180, 2.0)
    cool = _glow_sprite(SLATE, 1000, 2.1)
    vign = _vignette()
    n_bars = 56
    bar_w = W / n_bars

    frames = []
    for f in range(FRAMES):
        th = 2 * math.pi * f / FRAMES
        frame = base.copy().convert("RGBA")

        # warm glow — drifts upper-right, gentle pulse
        wx = int(W * 0.66 + 150 * math.sin(th)) - warm.width // 2
        wy = int(H * 0.20 + 70 * math.sin(2 * th)) - warm.height // 2
        wa = 0.55 + 0.22 * math.sin(th + 0.6)
        warm_f = warm.copy()
        warm_f.putalpha(warm_f.getchannel("A").point(lambda p: int(p * wa)))
        frame.alpha_composite(warm_f, (wx, wy))

        # cool glow — drifts lower-left, counter-phase
        cx = int(W * 0.20 + 130 * math.sin(th + math.pi)) - cool.width // 2
        cy = int(H * 0.78 + 60 * math.sin(2 * th + 1.0)) - cool.height // 2
        ca = 0.32 + 0.16 * math.sin(th + 2.0)
        cool_f = cool.copy()
        cool_f.putalpha(cool_f.getchannel("A").point(lambda p: int(p * ca)))
        frame.alpha_composite(cool_f, (cx, cy))

        # subtle equaliser pulse along the bottom (loops: integer cycles per bar)
        bars = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bars)
        for i in range(n_bars):
            cyc = 1 + (i % 3)
            level = 0.5 + 0.5 * math.sin(th * cyc + i * 0.7)
            bh = 26 + level * 150
            x0 = i * bar_w + bar_w * 0.18
            x1 = (i + 1) * bar_w - bar_w * 0.18
            bd.rectangle([x0, H - bh, x1, H], fill=(*ORANGE, 42))
        bars = bars.filter(ImageFilter.GaussianBlur(2))
        frame.alpha_composite(bars)

        frame.alpha_composite(vign)
        frames.append(frame.convert("RGB"))

    out = os.path.join(
        os.path.dirname(__file__), "..",
        "src/chordential_oia/web/static/public/hero-loop.webp",
    )
    out = os.path.abspath(out)
    frames[0].save(
        out, format="WEBP", save_all=True, append_images=frames[1:],
        duration=int(1000 / FPS), loop=0, quality=68, method=4,
    )
    print("wrote", out, f"{os.path.getsize(out)//1024} KB, {FRAMES} frames")


if __name__ == "__main__":
    build()
