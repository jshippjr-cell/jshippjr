# Chordential scroll-world — landing experience (WIP)

A scroll-driven "clay diorama" landing page that travels from the creative brief to the
final cleared master. Built with the [scroll-world](https://github.com/oso95/scroll-world)
concept, adapted to a **stills-only** scrollytelling page (no video yet — see below).

## Status (as of this commit)
- ✅ 5 of 6 clay-diorama scenes generated (Higgsfield · Nano Banana Pro, 2K)
- ✅ Scrollytelling page built: crossfade + parallax + pinned copy + progress rail
- ⏳ **Scene 6 (Hero) not yet generated** — ran out of trial credits (see prompt in `prompts/scene6.txt`)
- ⏳ Not yet wired into the FastAPI/Jinja app — this is a standalone `index.html` for now

## Preview it
Open `index.html` in a browser, or serve the folder:
```bash
cd scroll-world && python3 -m http.server 8123
# → http://localhost:8123
```
QA any scene directly: `index.html?scene=2` (0-indexed).

## The scenes (locked narrative)
1. The Brief — "Every campaign starts with a creative brief."
2. The Match — "We assemble the right creative team for the work."
3. The Composer's Studio — "Original music begins with people — not prompts."
4. Approval — "Built to survive approval." (emotional climax)
5. Delivery OS — "Everything arrives organized, cleared, and ready."
6. Hero — "Original music for campaigns. Composed. Cleared. Delivered." *(still to generate)*

Full brief + guardrails: [`CHORDENTIAL-BRIEF.md`](./CHORDENTIAL-BRIEF.md).
Exact image prompts: [`prompts/`](./prompts) (style preamble in `prompts/style.txt`).

## To finish (at home)
1. **Generate Scene 6** — free in the Higgsfield web UI (trial = unlimited there):
   use `prompts/style.txt` + `prompts/scene6.txt` as the prompt, 3:2, 2K. Save the PNG
   as `stills/scene6.png`. The page auto-includes it.
2. **(Optional) Upgrade to the full video fly-through** — the free trial can't drive
   video via the CLI (needs a paid plan). With Plus active, the scroll-world skill can
   generate the seamless camera dives + connectors and swap the stills for scrubbed video.
3. **Integrate into the site** — port `index.html` into a Jinja template + FastAPI route
   (e.g. `/experience`) under `src/chordential_oia/web/`, moving stills to the static dir.

## Notes
- Palette pulled from the app's real brand tokens (orange `#E4671F`, wine `#44161E`, cream, sand, olive, slate, ink).
- Art direction: soft matte clay diorama, isometric, tilt-shift miniature — one style preamble reused across all scenes for cohesion.
- No AI-audio claims; scenes show humans making music (honors the brand honesty rules).
