# Chordential — Capabilities Film (Veo Production Package)

*A paste-ready prompt package for generating the 60–90s Chordential capabilities reel
in Google **Veo 3 / 3.1** (via Google Flow, the Gemini app, or Vertex AI). Built to the
approved structure. Brand-grounded in `company-definition.md` and `cmo-positioning-brief.md`.*

---

## 0. How to read this (the one thing that matters)

Veo makes **8-second clips** and is **unreliable at rendering exact multi-line text**. So this
package follows the pro pattern:

1. **Generate clean visual PLATES in Veo** — atmospheric footage, **no on-screen text**.
2. **Add every word of typography in an editor** (CapCut / DaVinci Resolve / Premiere / After
   Effects) so the fonts and brand colors are perfect and identical across cards.
3. **Score it with Chordential's OWN music**, not Veo's generated audio. You are a music house —
   the track is the product. Use Veo audio only as a scratch/ambience reference.

So your workflow is: **Veo → plates** ➜ **Editor → text + your music + cut to length**.

---

## 1. Global style bible (put this at the top of every prompt)

**Look:** cinematic commercial film, anamorphic, shallow depth of field, 24fps, fine film grain,
soft volumetric haze, premium and warm — think a high-end brand spot, not stock footage.

**Color palette (brand):** deep charcoal / near-black base, **warm amber-orange key light
(#E4671F)**, **wine / burgundy shadows (#44161E)**, **cream highlights (#FCF7F8)**. Rich blacks,
gentle bloom on highlights.

**Camera:** slow, deliberate moves — dolly-ins, subtle push, gentle parallax, rack focus.
No frantic handheld. Confidence and control (mirrors the brand's "before competitors see it").

**Aspect ratio:** `16:9`, 1080p. (Also export a `9:16` pass for Reels/Shorts if needed — same
prompts, change aspect.)

**Negative prompt (append to every plate):**
`no on-screen text, no captions, no subtitles, no watermark, no logos, no brand names, no UI text,
no distorted hands, no warped instruments, no extra fingers, no jittery camera, no oversaturation`

**Audio in Veo:** request only subtle room tone / ambience (or silence). The real track is added
in post.

---

## 2. The timeline at a glance

| # | Section | Time | Plate (Veo) | Text added in post |
|---|---|---|---|---|
| 1 | Opening | 0–5s | Ink-in-darkness plate | "Music shapes perception." |
| 2 | Opening | 5–10s | Embers / dust plate | "Music drives emotion." → "Music moves audiences." |
| 3 | Capabilities | 10–18s | Montage A (commercial/corporate/brand) | "Original Composition" · "Orchestration" |
| 4 | Capabilities | 18–26s | Montage B (hospitality/film/gaming/experiential) | "Music Production" · "Sound Design" · "Audio Post" |
| 5 | Process | 26–34s | Concept → studio sketch | "Concept ↓" |
| 6 | Process | 34–42s | DAW + MIDI orchestration | "Composition ↓" |
| 7 | Process | 42–50s | Live players + mixing console | "Production ↓ → Delivery" |
| 8 | Results | 50–58s | Brand film / campaign world | "Brand Films" · "Commercial Campaigns" |
| 9 | Results | 58–66s | Experiential / corporate | "Experiential Events" · "Corporate Storytelling" |
| 10 | Results | 66–75s | Interactive / gaming glow | "Interactive Media" |
| 11 | Closing | 75–90s | Charcoal/wine atmosphere plate | Logo + 3-line tagline (overlay the real wordmark) |

**To hit 60s instead of 90s:** keep shots 1, 2, 3, 6, 7, 8, 11 and trim each to ~6–8s.
**To hit 90s:** use all 11 and let them breathe.

---

## 3. Shot-by-shot Veo prompts (copy one block per generation)

> Prefix each with the Global Style Bible (§1) or paste the short form: *"Cinematic anamorphic
> commercial film, 24fps, film grain, shallow depth of field, charcoal base with warm amber-orange
> key light and wine shadows, cream highlights, slow deliberate camera."*

### Shot 1 — Opening / "Music shapes perception" (0–5s)
```
Extreme close-up, total darkness. A single drop of warm amber ink blooms and unfurls slowly into
black water, tendrils glowing like embers, then a faint cream particle drifts through frame. Slow
push-in. Near-silent, deep sub-bass room tone. Mysterious, premium, restrained. Wine-black palette
with a single warm orange light source. 16:9, 1080p.
[+ negative prompt §1]
```

### Shot 2 — Opening / "drives emotion → moves audiences" (5–10s)
```
Slow-motion embers and fine dust float upward through a dark void, catching a warm amber rim light;
a soft cream glow swells in the distance and gently fills the frame toward the end. Subtle volumetric
haze, anamorphic lens flare. Camera drifts upward. Quiet, cinematic, building anticipation. 16:9.
[+ negative prompt §1]
```

### Shot 3 — Capabilities montage A (10–18s)
```
Fast elegant montage, ~2 seconds per beat, seamless whip-pan transitions: (1) a sleek commercial
film set with cinema lights and a director's monitor; (2) a polished corporate event stage at night,
audience silhouettes under warm spotlights; (3) a glossy brand-launch product reveal on a rotating
plinth with amber accent lighting. Confident dolly moves, shallow focus, premium color grade,
charcoal and warm orange. No text. 16:9, 1080p.
[+ negative prompt §1]
```

### Shot 4 — Capabilities montage B (18–26s)
```
Fast elegant montage continuing, ~2s per beat: (1) a luxury hospitality lobby at dusk, warm
ambient glow, guests moving in soft slow motion; (2) a cinematic film frame — a lone figure in a
dramatic landscape at golden hour; (3) a gaming/experiential moment — glowing screens and reactive
LED light installation reflecting on faces. Smooth transitions, anamorphic, cream highlights on a
charcoal base. No text. 16:9.
[+ negative prompt §1]
```

### Shot 5 — Process / Concept (26–34s)
```
Close-up of a composer's hands sketching musical ideas and notes by warm desk lamp light in a dim
studio, a coffee and headphones nearby; slow rack focus from the pencil to a waveform faintly
glowing on a monitor behind. Intimate, thoughtful, the beginning of an idea. Warm amber practical
light, wine shadows. Quiet room tone. 16:9, 1080p.
[+ negative prompt §1]
```

### Shot 6 — Process / Composition (34–42s)
```
Over-the-shoulder of a music producer at a glowing DAW workstation, a colorful MIDI piano-roll and
orchestral track stacks scrolling on a widescreen monitor; fingers move across a MIDI keyboard;
soft blue-and-amber screen glow on the face in a darkened studio. Slow push-in on the screen.
Focused, modern, expert. Realistic software UI but no readable logos or words. 16:9.
[+ negative prompt §1]
```

### Shot 7 — Process / Production → Delivery (42–50s)
```
Cinematic studio sequence: a small string ensemble performing under warm spotlights in a recording
live room seen through control-room glass; cut to a hand riding faders on a large mixing console,
channel-meter LEDs glowing; finish on a master fader pushed up and a render/export progress glow.
Reverent, warm, the craft coming together. Anamorphic, shallow focus, charcoal + amber. 16:9, 1080p.
[+ negative prompt §1]
```

### Shot 8 — Results / Brand Films & Campaigns (50–58s)
```
Polished brand-film montage: a hero product shot with liquid splash in slow motion under studio
light; a lifestyle campaign frame of confident people lit warmly; a city billboard glowing at
night. High-end advertising look, rich contrast, warm orange accents on charcoal. Smooth elegant
cuts. No text or brand names. 16:9, 1080p.
[+ negative prompt §1]
```

### Shot 9 — Results / Experiential & Corporate (58–66s)
```
A large experiential brand activation at night — crowds beneath a glowing immersive light
installation; cut to a sleek corporate keynote stage with a speaker silhouette and warm uplighting;
audience faces lit by the glow. Epic but tasteful, cinematic scale, cream and amber highlights on
deep charcoal. Slow sweeping camera. No text. 16:9.
[+ negative prompt §1]
```

### Shot 10 — Results / Interactive Media (66–75s)
```
Close, atmospheric: faces lit by the reactive glow of a game or interactive screen, reflections of
moving color in their eyes; cut to abstract audio-reactive visuals pulsing in sync with unseen
music, warm amber and wine particles. Immersive, contemporary, emotive. Shallow focus, film grain.
No text. 16:9, 1080p.
[+ negative prompt §1]
```

### Shot 11 — Closing plate (75–90s) — *logo added in post*
```
Slow drifting atmosphere in deep charcoal and wine: fine warm amber particles and soft volumetric
haze settle toward stillness, a gentle cream glow centered in frame as if a light is about to
resolve into a mark. Calm, confident, premium, resolved. Very slow push-in coming to rest. Silent
except deep room tone. Leave the center clean and uncluttered. 16:9, 1080p.
[+ negative prompt §1]
```
> Do **not** ask Veo to draw the Chordential wordmark — it will mangle it. Generate this clean
> centered plate and overlay the real `static/logo.png` / Echo wordmark in your editor.

---

## 4. Typography / title cards (add these in the editor, not in Veo)

**Fonts:** a refined high-contrast serif or a clean wide sans in **cream `#FCF7F8`** on near-black;
brand orange `#E4671F` for emphasis words. Letter-spacing slightly open. Slow fade/slide-up (~0.6s
in, hold, fade out). Keep one idea per card.

| Card | Text | Note |
|---|---|---|
| Opening 1 | `Music shapes perception.` | Type appears letter-faded over Shot 1 |
| Opening 2 | `Music drives emotion.` then `Music moves audiences.` | Two quick beats over Shot 2 |
| Capabilities | `Original Composition` · `Orchestration` · `Music Production` · `Sound Design` · `Audio Post` | One word per ~1.5s, lower-third, over Shots 3–4 |
| Process | `Concept ↓ Composition ↓ Production ↓ Delivery` | Reveal each step in sync with Shots 5–7; the ↓ chain can build as a vertical list |
| Results | `Brand Films` · `Commercial Campaigns` · `Experiential Events` · `Corporate Storytelling` · `Interactive Media` | One per beat over Shots 8–10 |
| Closing | **Logo (Echo wordmark)** then: `Music for Brands.` / `Music for Stories.` / `Music for Experiences.` | Wordmark fades in centered on Shot 11; tagline lines reveal one at a time below it |

**Brand hexes for the editor:** orange `#E4671F` · wine `#44161E` · cream `#FCF7F8` · charcoal `#1A1518` (suggested near-black).

---

## 5. Music (your real edge — don't skip this)

Score the reel with a **Chordential original**: start sparse and atmospheric under the opening
(single piano/pad + sub), build rhythm and orchestration through Capabilities/Process, swell to a
full hybrid-orchestral peak across Results, and resolve to a single warm chord on the closing
wordmark. Cut the picture **to the music**, not the other way around — the track is the hero, the
visuals are the frame. (This is literally your value proposition: human craft over generated audio.)

---

## 6. How to actually generate it

- **Easiest — Google Flow** (`labs.google/flow`): create a project, paste each Shot block, set
  aspect `16:9`, generate, pick the best take per shot, extend/re-roll as needed. Flow also lets you
  stitch clips on a timeline.
- **Gemini app** (Veo built in): paste a block, generate an 8s clip, download, repeat.
- **Vertex AI / Gemini API** (`veo-3.0-generate-preview`): for batch generation from a script —
  needs a Google Cloud project with Veo access + an API key. (See §8 — I can write that script.)

Generate **2–3 takes per shot** and keep the best; that's normal for Veo. Budget for it — each shot
is a few generations.

---

## 7. Post / stitch checklist

1. Import all chosen plates into the editor; lay them on the timeline in order (§2).
2. Drop the Chordential music track; nudge cuts to land on musical beats.
3. Add the title cards (§4) with the brand fonts/colors; keep motion subtle and consistent.
4. Overlay the real logo on Shot 11.
5. Grade for a consistent warm-charcoal look across all shots (shots from Veo will vary — a unifying
   LUT/grade is what makes it feel like one film).
6. Add a light film-grain + subtle vignette over the whole timeline for cohesion.
7. Export 1080p (or 4K up-res), plus a 9:16 cutdown for social.

---

## 8. Want me to script the Veo API calls?

I can write a `scripts/gen_capabilities_film.py` using `google-genai` that submits all 11 prompts to
`veo-3.0-generate-preview`, polls the long-running operations, and saves each MP4 — **if** you give
this environment (a) a Google API key / Vertex credentials with Veo access and (b) network egress to
Google's API is permitted by the environment's network policy. This sandbox currently has neither, so
the package above is the deliverable you can run today in Flow/Gemini.
```
# sketch of what the script would do:
#   for shot in SHOTS: op = client.models.generate_videos(model="veo-3.0-generate-preview",
#       prompt=shot.prompt, config=GenerateVideosConfig(aspect_ratio="16:9", ...))
#   poll op until done; download op.response.generated_videos[0] -> shots/NN.mp4
```
Say the word and I'll add it.

> **Done — the script now exists:** `scripts/gen_capabilities_film.py` (`pip install '.[veo]'`,
> set `GEMINI_API_KEY`, then `python scripts/gen_capabilities_film.py --shots all`).

---

## 9. Hero loop (website background)

A separate, short, **seamlessly looping** plate for the landing-page hero — darker and lower-contrast
than the film shots, with the center kept clean so headline text reads over it. These live in the
script as `LOOP_SHOTS`; generate them with `--shots loop` (or one at a time, e.g. `--shots loop-a`).

**Loop A — `loop-hero` (the recommended hero plate):**
```
[Global style §1] Slow continuous abstract motion in deep charcoal and wine: warm amber
audio-waveform light ripples drifting left to right, fine glowing particles and soft volumetric haze
orbiting gently, a faint cream bloom pulsing slowly like a breathing light. No focal subject, endless
flowing seamless texture. The frame stays mostly dark with light low and to the sides so the center
remains clean for headline text. 16:9, 1080p.
[+ negative prompt §1]
```
Alternates: `loop-b1` defocused brand bokeh · `loop-b2` abstracted score/MIDI light · `loop-b3`
audio-reactive waveforms. Generate a couple and pick the one that sits best behind the headline.

**Making it loop seamlessly — two options:**
- **In Google Flow:** use **Frames to Video** and set the *same* image as both the first and last
  frame, so the clip ends where it began.
- **From the script (no Flow):** generate `loop-a`, then crossfade the tail back into the head with
  ffmpeg, e.g. for an 8s clip with a 1s blend:
  ```
  ffmpeg -i loop-a_loop-hero.mp4 -filter_complex \
    "[0]split[a][b];[a]trim=0:7,setpts=PTS-STARTPTS[main];\
     [b]trim=7:8,setpts=PTS-STARTPTS[tail];\
     [main][tail]xfade=transition=fade:duration=1:offset=6" hero-loop.mp4
  ```
  Then drop `hero-loop.mp4` (+ a `hero-poster.jpg` still) into `static/` and I'll wire the hero.

For a web background, a clean crossfade loop is indistinguishable from a "true" seam — don't
over-engineer it.


---

## 9. Loop version — seamless hero background (15–30s)

A **continuous, no-beginning / no-ending** loop that lives behind the hero headline on the site/PWA.
Different rules from the linear film: it must be **seamless**, **muted-autoplay-safe**, **subtle
enough that cream text reads on top**, and **web-light** (a few MB).

### Two ways to make it actually seamless
- **Best — same first & last frame (forced loop):** in Veo, use **image-to-video** with the *same*
  reference image as both the **start frame and the end frame**. The clip returns to where it began,
  so it loops with no visible cut. Generate one strong 8s plate this way and just loop it — a hero
  background doesn't need length, it needs to never seam.
- **Fallback — crossfade loop in the editor:** generate 15–24s of *cyclical* motion (drifting
  particles, flowing ink, slow orbit), then overlap the last ~1.5s onto the first ~1.5s with a
  crossfade. Hides the seam for any abstract texture.

### Plate prompts (text-free, dark, loopable)
Keep these **darker and lower-contrast** than the film shots so headline text stays legible.

**Loop A — single hero plate (simplest, 8s, looped):**
```
Slow continuous abstract motion in deep charcoal and wine: warm amber audio-waveform light ripples
drifting left to right, fine glowing particles and soft volumetric haze orbiting gently, a faint
cream bloom pulsing slowly like a breathing light. No focal subject, no hard movement, endless
flowing texture that feels seamless. Dark, premium, atmospheric, understated. The frame stays mostly
dark with light concentrated low and to the sides so the center remains clean. Silent. 16:9, 1080p.
[+ negative prompt §1]
```

**Loop B — 24s triptych (more variety; 3 × 8s loopable plates, crossfaded):**
```
B1: Blurred, bokeh-soft commercial film footage and brand color washes drifting slowly past, heavily
defocused so it reads as warm abstract light in charcoal and amber. Continuous gentle parallax. Dark
and clean in the center. No text. 16:9.

B2: A glowing orchestral score and slow-scrolling MIDI piano-roll light, abstracted and out of focus
into flowing amber and cream streaks over black; subtle particle drift. Endless motion. No readable
text. 16:9.

B3: Soft audio-reactive waveforms and equalizer light pulsing slowly in wine and amber over deep
charcoal, fine embers rising. Hypnotic, seamless, low-contrast. No text. 16:9.
[+ negative prompt §1 on each]
```

### Text — rotate the words *in HTML/CSS*, not in the video
Keep the loop **text-free** and animate the words over it in the page. That keeps type crisp,
accessible, selectable, and lets you change copy without re-rendering. Fade each in/out (~2.5s each),
then hold the last:
```
Original Composition  →  Production  →  Sound Design  →  Creative Music Solutions
```
(Brand: cream `#FCF7F8` text, orange `#E4671F` emphasis, on the darkened loop.)

### Wiring it into the hero (when you have the file)
```html
<video class="hero-bg" autoplay muted loop playsinline
       poster="/static/hero-poster.jpg" aria-hidden="true">
  <source src="/static/hero-loop.webm" type="video/webm">   <!-- VP9, smallest -->
  <source src="/static/hero-loop.mp4"  type="video/mp4">    <!-- H.264 fallback -->
</video>
<div class="hero-scrim"></div>   <!-- dark gradient so text reads -->
<div class="hero-words"><!-- the rotating words, animated in CSS --></div>
```
- `muted` + `playsinline` are **required** for autoplay on iOS — without both, the loop won't play.
- Add a `hero-scrim` (e.g. `linear-gradient(rgba(26,21,24,.45), rgba(26,21,24,.75))`) so headline
  contrast holds over any frame.
- Provide a `poster` still (first frame) so something shows before the video loads / if it's blocked.
- Optimize for web: 1080p, short loop, VP9 `.webm` + H.264 `.mp4`, target a few MB; respect
  `prefers-reduced-motion` (fall back to the poster image).

**Want me to wire this into the actual hero** (add the `<video>` + scrim + CSS word-rotation to the
landing template, with a `prefers-reduced-motion` fallback) once you've dropped `hero-loop.mp4/.webm`
+ `hero-poster.jpg` into `static/`? Say go and I'll build it.
