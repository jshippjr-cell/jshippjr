#!/usr/bin/env python3
"""Assemble the Chordential capabilities film from the Veo plates + typography.

Takes the generated clips in capabilities_clips/ and lays the framework's
on-screen text over them — opening lines, capability list, Concept→Delivery
flow, project list, and the closing logo + tagline — with cinematic fades, in
the brand palette. Outputs one silent MP4 (add your own music track in an
editor). Pure-Python via moviepy + the imageio-ffmpeg binary.

Run:  python scripts/assemble_capabilities_film.py
"""
from __future__ import annotations

import os

from moviepy import (
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
    vfx,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CLIPS = os.path.join(ROOT, "capabilities_clips")
LOGO = os.path.join(ROOT, "src", "chordential_oia", "web", "static", "logo.png")
OUT = os.path.join(ROOT, "capabilities_clips", "chordential_capabilities_film.mp4")

# Brand
CREAM = "#FCF7F8"
ORANGE = "#E4671F"
SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

W, H = 1280, 720  # standardized; overridden to match first real clip

# Per-clip text overlays. style: hero | label | flow.
ORDER = [
    ("01", "hero", ["Music shapes perception."]),
    ("02", "hero", ["Music drives emotion.", "Music moves audiences."]),
    ("03", "label", ["Original Composition", "Orchestration"]),
    ("04", "label", ["Music Production", "Sound Design", "Audio Post"]),
    ("05", "flow", ["Concept"]),
    ("06", "flow", ["Composition"]),
    ("07", "flow", ["Production", "Delivery"]),
    ("08", "label", ["Brand Films", "Commercial Campaigns"]),
    ("09", "label", ["Experiential Events", "Corporate Storytelling"]),
    ("10", "label", ["Interactive Media"]),
]


def find_clip(cid: str) -> str | None:
    if not os.path.isdir(CLIPS):
        return None
    for f in sorted(os.listdir(CLIPS)):
        if f.startswith(f"{cid}_") and f.endswith(".mp4"):
            return os.path.join(CLIPS, f)
    return None


def txt(text, font, size, color=CREAM, box=None, align="center"):
    return TextClip(font=font, text=text, font_size=size, color=color,
                    method="caption", size=box or (int(W * 0.82), None),
                    text_align=align, stroke_color=None)


def fade(clip, d=0.5):
    return clip.with_effects([vfx.FadeIn(d), vfx.FadeOut(d)])


def overlay_for(style, words, clip_dur):
    """Build the timed text layers for one clip."""
    layers = []
    n = max(1, len(words))
    slot = clip_dur / n
    for i, word in enumerate(words):
        start = i * slot
        dur = slot
        if style == "hero":
            t = fade(txt(word, SERIF, 58).with_duration(dur).with_position("center"), 0.8)
        elif style == "flow":
            block = CompositeVideoClip([
                txt(word, SANS_BOLD, 52).with_position(("center", 0.40), relative=True),
                txt("↓", SANS, 46, color=ORANGE).with_position(("center", 0.56), relative=True),
            ], size=(W, H)).with_duration(dur)
            t = fade(block, 0.5)
        else:  # label — lower third
            t = fade(txt(word, SANS_BOLD, 46).with_duration(dur)
                     .with_position(("center", 0.78), relative=True), 0.5)
        layers.append(t.with_start(start))
    return layers


def build_section(cid, style, words):
    path = find_clip(cid)
    if not path:
        print(f"  ! missing clip {cid} — skipping")
        return None
    base = VideoFileClip(path).without_audio().resized((W, H))
    scrim_op = 0.45 if style in ("hero",) else 0.28
    scrim = ColorClip((W, H), color=(10, 8, 10)).with_opacity(scrim_op).with_duration(base.duration)
    comp = CompositeVideoClip([base, scrim, *overlay_for(style, words, base.duration)], size=(W, H))
    return comp.with_duration(base.duration)


def closing_clip():
    path = find_clip("11")
    dur = 6.0
    if path:
        base = VideoFileClip(path).without_audio().resized((W, H))
        dur = base.duration
        layers = [base, ColorClip((W, H), (10, 8, 10)).with_opacity(0.5).with_duration(dur)]
    else:
        layers = [ColorClip((W, H), (20, 16, 19)).with_duration(dur)]
    if os.path.exists(LOGO):
        logo = (ImageClip(LOGO).resized(width=int(W * 0.42))
                .with_duration(dur).with_position(("center", 0.30), relative=True))
        layers.append(logo)
    tagline = CompositeVideoClip([
        txt("Music for Brands.", SERIF, 40).with_position(("center", 0.56), relative=True),
        txt("Music for Stories.", SERIF, 40).with_position(("center", 0.66), relative=True),
        txt("Music for Experiences.", SERIF, 40).with_position(("center", 0.76), relative=True),
    ], size=(W, H)).with_duration(dur)
    layers.append(tagline)
    return CompositeVideoClip(layers, size=(W, H)).with_duration(dur)


def main():
    global W, H
    first = next((find_clip(cid) for cid, _, _ in ORDER if find_clip(cid)), None)
    if first:
        with VideoFileClip(first) as c:
            W, H = c.size
        print(f"Target resolution {W}x{H}")

    sections = []
    for cid, style, words in ORDER:
        s = build_section(cid, style, words)
        if s:
            sections.append(s)
    sections.append(closing_clip())

    # Fade the whole film up from / down to black at the ends.
    sections[0] = sections[0].with_effects([vfx.FadeIn(1.5)])
    sections[-1] = sections[-1].with_effects([vfx.FadeOut(2.0)])

    film = concatenate_videoclips(sections, method="chain")
    print(f"Total duration {film.duration:.1f}s, {len(sections)} segments")
    film.write_videofile(OUT, fps=24, codec="libx264", audio=False,
                         preset="medium", bitrate="6000k")
    print(f"\n✓ wrote {OUT}")


if __name__ == "__main__":
    main()
