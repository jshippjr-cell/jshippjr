#!/usr/bin/env python3
"""Batch-generate the Chordential capabilities film clips with Google Veo.

Submits each shot from the production brief (docs/capabilities-video-veo-brief.md)
to Veo via the google-genai SDK, polls each long-running operation, and saves the
resulting MP4s into an output directory. Generate text-free PLATES here; add the
typography and Chordential's own music in an editor afterward.

This sandbox has no Veo access — run this on a machine that has:
  * google-genai installed:      pip install google-genai
  * a Gemini API key with Veo:   export GEMINI_API_KEY=...   (or GOOGLE_API_KEY)
  * outbound network to Google's API

The SHOTS data and prompt-building are import-safe (the SDK is imported lazily
inside main), so the prompts can be inspected/tested without the dependency.

Examples:
  python scripts/gen_capabilities_film.py --shots all          # all 11 film shots
  python scripts/gen_capabilities_film.py --shots loop         # the hero-loop plates
  python scripts/gen_capabilities_film.py --shots 1,2,11       # just these
  python scripts/gen_capabilities_film.py --dry-run            # print prompts, call nothing
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# ── Brand style, applied to every prompt (see brief §1) ──────────────────────
STYLE_PREFIX = (
    "Cinematic anamorphic commercial film, 24fps, fine film grain, shallow depth "
    "of field, deep charcoal base with a warm amber-orange key light (#E4671F), "
    "wine shadows (#44161E) and cream highlights (#FCF7F8), slow deliberate camera, "
    "premium and understated. "
)
NEGATIVE = (
    "on-screen text, captions, subtitles, watermark, logos, brand names, UI text, "
    "distorted hands, warped instruments, extra fingers, jittery camera, oversaturation"
)

# ── The 11 film shots (brief §3) — text-free plates ─────────────────────────
SHOTS = [
    ("01", "opening-ink", (
        "Extreme close-up in total darkness. A single drop of warm amber ink blooms and unfurls "
        "slowly into black water, tendrils glowing like embers, a faint cream particle drifting "
        "through frame. Slow push-in. Mysterious, restrained. 16:9, 1080p.")),
    ("02", "opening-embers", (
        "Slow-motion embers and fine dust float upward through a dark void, catching a warm amber "
        "rim light; a soft cream glow swells in the distance and gently fills the frame. Subtle "
        "volumetric haze, anamorphic lens flare. Camera drifts upward. Building anticipation. 16:9.")),
    ("03", "capabilities-a", (
        "Fast elegant montage, ~2s per beat, seamless whip-pans: a sleek commercial film set with "
        "cinema lights and a director's monitor; a polished corporate event stage at night with "
        "audience silhouettes under warm spotlights; a glossy brand-launch product reveal on a "
        "rotating plinth with amber accent lighting. Confident dolly moves, shallow focus. 16:9.")),
    ("04", "capabilities-b", (
        "Fast elegant montage continuing, ~2s per beat: a luxury hospitality lobby at dusk with warm "
        "ambient glow and guests in soft slow motion; a cinematic film frame of a lone figure in a "
        "dramatic landscape at golden hour; a gaming/experiential moment of glowing screens and "
        "reactive LED light reflecting on faces. Smooth transitions, cream highlights on charcoal. 16:9.")),
    ("05", "process-concept", (
        "Close-up of a composer's hands sketching musical ideas by warm desk-lamp light in a dim "
        "studio, headphones nearby; slow rack focus from the pencil to a waveform faintly glowing on "
        "a monitor behind. Intimate, thoughtful, the beginning of an idea. 16:9, 1080p.")),
    ("06", "process-composition", (
        "Over-the-shoulder of a music producer at a glowing DAW workstation, a colorful MIDI "
        "piano-roll and orchestral track stacks scrolling on a widescreen monitor; fingers moving "
        "across a MIDI keyboard; soft blue-and-amber screen glow on the face in a darkened studio. "
        "Slow push-in. Realistic software UI but no readable words. 16:9.")),
    ("07", "process-production", (
        "Cinematic studio sequence: a small string ensemble performing under warm spotlights in a "
        "recording live room seen through control-room glass; cut to a hand riding faders on a large "
        "mixing console with channel-meter LEDs glowing; finish on a master fader pushed up. "
        "Reverent, warm, the craft coming together. 16:9, 1080p.")),
    ("08", "results-brandfilms", (
        "Polished brand-film montage: a hero product shot with a slow-motion liquid splash under "
        "studio light; a lifestyle campaign frame of confident people lit warmly; a city billboard "
        "glowing at night. High-end advertising look, rich contrast, warm orange accents. 16:9, 1080p.")),
    ("09", "results-experiential", (
        "A large experiential brand activation at night — crowds beneath a glowing immersive light "
        "installation; cut to a sleek corporate keynote stage with a speaker silhouette and warm "
        "uplighting; audience faces lit by the glow. Epic but tasteful, cinematic scale. 16:9.")),
    ("10", "results-interactive", (
        "Close and atmospheric: faces lit by the reactive glow of an interactive screen, moving color "
        "reflected in their eyes; cut to abstract audio-reactive visuals pulsing in sync with unseen "
        "music, warm amber and wine particles. Immersive, contemporary, emotive. 16:9, 1080p.")),
    ("11", "closing-plate", (
        "Slow drifting atmosphere in deep charcoal and wine: fine warm amber particles and soft "
        "volumetric haze settle toward stillness, a gentle cream glow centered as if a light is about "
        "to resolve into a mark. Calm, confident, resolved. Very slow push-in coming to rest. Leave "
        "the center clean and uncluttered (logo is added in post). 16:9, 1080p.")),
]

# ── Hero-loop plates (brief §9) — darker, lower-contrast, seamless ──────────
LOOP_SHOTS = [
    ("loop-a", "loop-hero", (
        "Slow continuous abstract motion in deep charcoal and wine: warm amber audio-waveform light "
        "ripples drifting left to right, fine glowing particles and soft volumetric haze orbiting "
        "gently, a faint cream bloom pulsing slowly like a breathing light. No focal subject, endless "
        "flowing seamless texture. The frame stays mostly dark with light low and to the sides so the "
        "center remains clean for headline text. 16:9, 1080p.")),
    ("loop-b1", "loop-bokeh", (
        "Heavily defocused commercial-film footage and brand color washes drifting slowly past, "
        "reading as warm abstract bokeh light in charcoal and amber. Continuous gentle parallax, dark "
        "and clean in the center. Seamless. 16:9.")),
    ("loop-b2", "loop-score", (
        "A glowing orchestral score and slow-scrolling MIDI piano-roll light, abstracted out of focus "
        "into flowing amber and cream streaks over black; subtle particle drift. Endless seamless "
        "motion. 16:9.")),
    ("loop-b3", "loop-waveform", (
        "Soft audio-reactive waveforms and equalizer light pulsing slowly in wine and amber over deep "
        "charcoal, fine embers rising. Hypnotic, seamless, low-contrast. 16:9.")),
]


def build_prompt(prompt: str) -> str:
    """Full prompt = brand style prefix + the shot description."""
    return STYLE_PREFIX + prompt


def select(which: str):
    """Resolve the --shots selector to a list of (id, slug, prompt) shots."""
    w = which.strip().lower()
    if w in ("all", "film"):
        return list(SHOTS)
    if w == "loop":
        return list(LOOP_SHOTS)
    if w == "everything":
        return list(SHOTS) + list(LOOP_SHOTS)
    wanted = {p.strip().lstrip("0") or "0" for p in w.split(",")}
    pool = SHOTS + LOOP_SHOTS
    return [s for s in pool if s[0].lstrip("0") in wanted or s[0] in w.split(",")]


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Chordential capabilities clips with Veo.")
    ap.add_argument("--shots", default="all",
                    help="all | film | loop | everything | comma list e.g. 1,2,11 or loop-a")
    ap.add_argument("--out", default="capabilities_clips", help="output directory for MP4s")
    ap.add_argument("--model", default=os.environ.get("VEO_MODEL", "veo-3.0-generate-preview"))
    ap.add_argument("--aspect", default="16:9", help="aspect ratio, e.g. 16:9 or 9:16")
    ap.add_argument("--takes", type=int, default=1, help="videos per shot (pick the best afterward)")
    ap.add_argument("--poll", type=int, default=10, help="seconds between status polls")
    ap.add_argument("--force", action="store_true", help="re-generate even if the file exists")
    ap.add_argument("--dry-run", action="store_true", help="print prompts and exit (no API calls)")
    args = ap.parse_args()

    shots = select(args.shots)
    if not shots:
        print(f"No shots matched --shots={args.shots!r}.", file=sys.stderr)
        return 2

    if args.dry_run:
        for sid, slug, prompt in shots:
            print(f"\n=== {sid} {slug} ===\n{build_prompt(prompt)}\n  [negative] {NEGATIVE}")
        print(f"\n{len(shots)} shot(s). Dry run — nothing generated.")
        return 0

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Set GEMINI_API_KEY (or GOOGLE_API_KEY) to a key with Veo access.", file=sys.stderr)
        return 2
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Missing dependency. Install with:  pip install google-genai", file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    client = genai.Client(api_key=api_key)
    failures = 0

    for sid, slug, prompt in shots:
        base = os.path.join(args.out, f"{sid}_{slug}")
        if not args.force and os.path.exists(f"{base}.mp4"):
            print(f"• {sid} {slug}: exists, skipping (use --force to redo)")
            continue
        print(f"▶ {sid} {slug}: submitting…")
        try:
            op = client.models.generate_videos(
                model=args.model,
                prompt=build_prompt(prompt),
                config=types.GenerateVideosConfig(
                    aspect_ratio=args.aspect,
                    negative_prompt=NEGATIVE,
                    number_of_videos=max(1, args.takes),
                ),
            )
            while not op.done:
                time.sleep(args.poll)
                op = client.operations.get(op)
                print(f"  … {sid} working")
            videos = op.response.generated_videos
            for i, gv in enumerate(videos):
                suffix = "" if i == 0 else f"_take{i+1}"
                out_path = f"{base}{suffix}.mp4"
                client.files.download(file=gv.video)
                gv.video.save(out_path)
                print(f"  ✓ saved {out_path}")
        except Exception as e:  # noqa: BLE001 — keep going through the batch
            failures += 1
            print(f"  ✗ {sid} {slug} failed: {e}", file=sys.stderr)

    print(f"\nDone. {len(shots) - failures}/{len(shots)} shot(s) generated into {args.out}/")
    print("Next: add typography + your own music in an editor (see docs/capabilities-video-veo-brief.md).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
