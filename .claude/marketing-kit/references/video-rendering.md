# Rendering a video locally

How `short-form-video` makes the finished video on the user's machine with
`scripts/video/render.js`. The skill reads this file when the user opts in
to a local render (its steps 3 and 6). `${CLAUDE_PLUGIN_ROOT}` is the
plugin folder, resolved the way the skill describes.

## What it makes

Motion graphics (kinetic text, shapes, UI mockups) over stock photos, stock
video clips, or AI images, with an original soundtrack in the project's
sonic identity and sound effects synced to what's on screen. It's not
filmed footage of the user's product or people, and the only voiceover is
one the user records or supplies (or a free generated one, below). It
suits the types `video-types.md` marks Render or Render + your assets, not
anything that needs real people or places on camera. It costs nothing to
run.

Check it's usable with `node --version` (18+), `ffmpeg -version`, and
`node -e "require('playwright')"` run from `scripts/video`. If anything is
missing, give the user the one-time setup from "Rendering a short-form
video locally" in `docs/video.md` rather than installing it unasked.

## A narrated video: compose.js

For a voiceover over backgrounds (an explainer, tips, a text-led brand
story, a storytime), don't hand-edit a template. Write the script as
numbered lines, one per scene, and let `compose.js` build the page:

```
---
title: late invoices
hook: you're losing money on every late invoice
cta: one money habit a week
voice: af_heart
bg: freelancer desk morning
---
1. Most freelancers lose money on invoices they send late. [bg: stressed laptop night]
2. Clients pay fastest when the invoice lands the day the work ends.
3. So send it before you close the laptop, not on Friday.
4. Follow for one money habit a week.
```

Save it as `${CLAUDE_PLUGIN_ROOT}/state/videos/<date>-<slug>.md` and run
`node ${CLAUDE_PLUGIN_ROOT}/scripts/video/compose.js <that file>`. It
voices each line (or uses the user's takes, one file per line, with
`recordings: assets/<slug>-{n}.m4a`; `state/videos/assets/` is shared by
every video, so name takes after the video), fetches a background per `[bg: ...]` (a query, or
a file in `assets/`), times every scene to its line with cuts on the
music's beat, applies the Sonic Identity one energy step lower so it sits
under the voice, puts word-by-word captions synced to the voice under each
line, and runs `--check`. The hook sits on screen from the first frame;
always set one. Keep lines short (one idea, under about 15 words) and the
hook under about 8 words. Then preview and render as below; the render
also writes an `.srt` caption file next to the MP4.

To change a line, edit the script and run `compose.js` again: the timing is
measured from the voice, so don't hand-edit it in the page. Send the user
the voice (`--audio-only`) or a render to check, since you can't hear it.

## Start the page

For everything else, copy the template `video-types.md` or `fyp-formats.md` names, from
`${CLAUDE_PLUGIN_ROOT}/scripts/video/templates/`, to
`${CLAUDE_PLUGIN_ROOT}/state/videos/<date>-<slug>.html`. There are seven
marketing templates (`promo`, `how-to`, `testimonial`, `faq`,
`announcement`, `team`, and `narrated`, which `compose.js` uses) and 22
everyday ones (`pov`, `tier-list`,
`text-chat`, `storytime`, and the rest listed in `fyp-formats.md`). Put any
images the user supplied in `state/videos/assets/`.

Rewrite its scenes to the script: one scene per beat, the hook readable
within the first second, and every line of text inside the `.scene` box
(each platform's UI covers the bottom quarter and right edge). Keep the
template's colors and type unless `brand-voice.md` says otherwise.
Everyday templates use TikTok Sans, the platform's own caption font, and
the shared pieces (captions, stickers, stamps, chat and notification
mockups, tier lists, polls, timers) documented at the top of `promo.html`.

## The sound

Set the `<body>` music attributes from the Sonic Identity in
`brand-voice.md`: `data-music`, `data-bpm`, `data-key`, `data-mode`,
`data-energy`, `data-motif`.
- Testimonials and sensitive topics use `data-music="calm"`, keeping the
  project's key and hook.
- An announcement can raise energy one step.
- An everyday post can take its template's genre (`phonk` under a
  "nobody: / me:", `lofi` under a text skit), keeping the identity's key
  and hook, within what the brand voice allows (see "Everyday and FYP
  posts" in `sound-guide.md`). Its meme cues (`scratch`, `boom`,
  `rimshot`, `ding`, `buzzer`, and the rest) are listed there; one or two
  per video is plenty.
- Add `data-break="<start>-<end>"` under a quote or any moment the words
  should carry alone.
- **No identity saved yet:** propose two from
  `${CLAUDE_PLUGIN_ROOT}/references/sound-guide.md`, each with one line on
  why it fits. Render a preview of each (`node
  ${CLAUDE_PLUGIN_ROOT}/scripts/video/render.js --sample <genre> <out.m4a>
  --motif ... --key ... --mode ... --energy ...`, a few seconds each). Send
  both to the user to listen to, and save their pick to `brand-voice.md`
  before rendering. You can't hear audio, so their ear decides.
- **Finding a licensed track:** `node
  ${CLAUDE_PLUGIN_ROOT}/scripts/video/media.js search "<mood or genre>"
  --type music --out ${CLAUDE_PLUGIN_ROOT}/state/videos/assets --count 3`
  downloads Creative Commons music from Openverse that allows commercial
  use and changes, records each track's credit line, and reports its tempo
  and how steady its beat is (from `beats.js`). Prefer a confidence of 0.5
  or more for cutting on the beat. Send the user the files to listen to;
  you can't hear them.
- **The user has a licensed track they'd rather use:** put it in
  `assets/`, set `data-music-src` and `data-music-start`, and record its
  license with `node ${CLAUDE_PLUGIN_ROOT}/scripts/video/media.js credit
  <file> --source ... --license ...`. Don't use a track without a license
  note. Then read its rhythm: `node
  ${CLAUDE_PLUGIN_ROOT}/scripts/video/beats.js assets/<file> --align <end
  of the hook, s> --duration <length>`. If the confidence is 0.5 or more,
  use the `data-music-start` it prints and move scene changes and key cues
  onto its bar (or beat) times; if it's lower, don't snap anything and time
  scenes to the voice or reading pace. Tell the user what you did ("104
  BPM, started at 0:32 so the drop hits as the hook ends, cuts on the
  bar"), and send an `--audio-only` render to check the sync, since you
  can't hear it.
- **Longer than about 45 seconds:** the generated music repeats the same
  few bars and wears thin, so ask for a licensed track instead. The
  renderer warns about it.

## A voiceover

The user's own recording, a free generated voice from
`${CLAUDE_PLUGIN_ROOT}/scripts/video/voice.js` (Kokoro, runs locally, no
key or cost; see "A free generated voice" in `sound-guide.md` for setup,
and send the user `--audition` samples to pick a voice, since you can't
hear them), or a voice they generate with a service they have their own
key for.

Write the script line by line, ask them to record each line as its own
file (`voice-1.m4a`, `voice-2.m4a`, ...), and put the files in `assets/`.
Add `data-voice="assets/voice-1.m4a"` to the element each line belongs
to; it plays at that element's `--voice` time, or `--in`. For one
continuous take, use `<body data-voice-src="..." data-voice-start="...">`
instead. The renderer trims the silence at both ends of each line, levels
the lines to match, and ducks the music and effects under the voice.
`render.js <page> --voice-lengths` lists each line's start, length, and the
room its scene leaves; time each scene to it, and the renderer warns when a
line runs past its scene. Under a voice, keep sound effects to scene
changes; the renderer warns past one every 3 seconds.

**Captions synced to the voice:** put the line's text in
`<div class="say auto" data-voice="assets/voice-2.m4a"
style="--voice:3.4s">...</div>` and the renderer shows it word by word,
in short chunks, with the word being said highlighted, timed to the clip
(`captions.js`, from the clip's pauses and the words' lengths; about 50 ms
from the true word starts on average). Most people watch muted, so caption
every voiced line. `--whisper` times them with Whisper instead, if
`kokoro-js` is installed and huggingface.co is reachable; it falls back on
its own when Whisper's timing doesn't hold up.

Never imitate a real person's voice without their permission, and if the
voice is AI-generated, have the user check whether the platform asks for
an AI-content label.

## The backgrounds

Every scene has an empty `.bg` slot timed to it.
- **What to search for:** for each scene, pick a setting or mood that fits
  the beat and the project's audience (e.g. "small bakery counter
  morning", "city at night aerial"). Not the product, a person, or a
  result.
- **Stock photos and clips:** `node
  ${CLAUDE_PLUGIN_ROOT}/scripts/video/media.js search "<query>" --out
  ${CLAUDE_PLUGIN_ROOT}/state/videos/assets [--type video]` searches Pexels
  (`PEXELS_API_KEY`) and Pixabay (`PIXABAY_API_KEY`), both free keys, and
  Openverse (photos only, no key). It downloads into `assets/` and records
  each file's license and required credit in `CREDITS.md` there. With no
  keys set, say that Openverse is the only source and it has no video
  clips, and point to the free keys rather than going without.
- **AI-generated images:** only with a connected image tool. That's Figma
  Weave once the user's Figma account is linked (find the model with
  `weave_find_model`, then `weave_run_model`, which quotes a cost first),
  or Higgsfield. Show the quoted cost and get an explicit yes before every
  run, since it spends the user's credits. Download each result into
  `assets/` and record it with `node
  ${CLAUDE_PLUGIN_ROOT}/scripts/video/media.js credit <file> --ai "<tool /
  model>" --prompt "<prompt>"`.
- **Placing:** put `<img class="bg-media" src="assets/<file>" alt="">`, or
  `<video class="bg-media" src="assets/<clip>">`, in the slot.
- **Look:** a consistent set reads as produced. Prefer the same light and
  palette across scenes. Use `class="bg blur"` on busy images, and
  `class="bg tint"` to pull mismatched ones toward the brand color. The
  renderer darkens bright backgrounds automatically; for a busy one, add
  `blur` or a heavier `--shade` on the slot.
- **People and real things:** a testimonial's or team video's person is
  always their own photo, never stock or AI.

## Timing and cues

Set `<body data-duration>` to the script's length and `data-drop` to when
the hook ends, so the beat drops as the body starts. Put `data-sfx` cues
only on moments that should land: words popping in, list items, a
checkmark, a button press, a scene change. A sound on everything reads as
noise. The comment at the top of `promo.html` documents the sounds, music
settings, background slots, and attributes, and each template's own
comment says what to replace. Replace every bracketed placeholder; never
ship one.

## Your own footage

- **Screen recordings** go straight into the how-to phone frame:
  `<video class="shot" src="assets/step-1.mp4" data-loop="false">` in a
  `.screen`. The renderer cuts a clip in a smaller box to that box's own
  shape, so a tall phone recording isn't cropped at the top and bottom.
  The product shown must be the real one.
- **A talking-head take** (filmed on a phone, one take): ask the user for
  the clip and, word for word, what they say in it. Then
  `node ${CLAUDE_PLUGIN_ROOT}/scripts/video/cut.js <take.mp4> --text "<what's
  said>" --hook "<hook>" --cta "<cta>" --page
  ${CLAUDE_PLUGIN_ROOT}/state/videos/<date>-<slug>.html` cuts out the pauses
  (`--min-pause`, default 0.35s), and writes a page with the clip full
  frame and its own sound, captions synced to it, the hook from the first
  frame, the music one energy step lower, and the brand's end card. It runs
  `--check`; render as usual. Captions use the person's real words only,
  never a tidied version, and only post people who agreed to it.
- **By hand:** `<video class="bg-media" id="take" src="assets/take.mp4"
  data-audio>` plays a clip's own sound in sync with it (from its
  `data-offset`, while the clip is on screen), leveled like a voiceover
  with the music ducked under it, and `<div class="say auto"
  data-clip="take">what's said</div>` captions it.

## The hook, the look, and the cover

- **The hook is on screen from frame 0.** The first frame is the default
  cover and the moment a viewer decides to stay. Every template's hook has
  class `now` (shown at once, with a small settle) instead of an entrance;
  keep it that way when rewriting, and `--check` fails a page whose first
  frame or first second has no text. It also fails text that leaves before
  it can be read (about four words a second), and notes stretches over 3
  seconds where nothing changes ("Pacing", advice only).
- **Hook variants.** To test hooks, put each version on the same page with
  `data-variant="a"`, `"b"`, `"c"` on the elements that differ (usually
  just the hook caption; everything else stays shared). `render.js <page>
  out.mp4 --variants a,b,c` writes `out-a.mp4`, `out-b.mp4`, ... and
  `--check` checks every variant. Write the three from different patterns
  in `hooks.md`. Instagram's trial reels, or one variant per platform, are
  ways to test them.
- **The brand's look.** Run `node ${CLAUDE_PLUGIN_ROOT}/scripts/video/brand.js
  <page>` after rewriting a template. It applies the Visual Identity from
  `brand-voice.md` (colors, display font) and, on marketing and narrated
  pages, adds a 1.6-second end card with the logo and handle after the
  last scene, landing with the sonic logo. It warns when the colors are too
  low in contrast to read. Running it again replaces what it added.
  `compose.js` does this itself. With no Visual Identity saved yet, ask
  for one (colors from their site or a description, a font, the logo, the
  handle) and save it there first, or keep the template's look.
- **The cover.** `render.js <page> --cover 0` writes the cover frame as a
  PNG next to the page and checks its text sits inside the 3:4 crop the
  profile grids show; with a render (`render.js <page> out.mp4 --cover 0`)
  it lands next to the video. Pass the time it prints to
  `publish_direct.py --cover-ms` (TikTok and Instagram), or host the PNG
  and pass `--cover-url` (Instagram). YouTube's cover is picked in its app.

## Preview, then render

The full render takes a couple of minutes, so preview first:
- `node ${CLAUDE_PLUGIN_ROOT}/scripts/video/render.js <page> --check` lints
  the whole timeline in seconds: text outside the safe area, spilling out
  of its box, clipped, or running into other text or a card. Fix
  everything it lists (usually by shortening the line) and run it again
  until it's clean.
- `node ${CLAUDE_PLUGIN_ROOT}/scripts/video/render.js <page> --slides`
  writes each scene's settled frame as a PNG to a `slides/` folder next to
  the page (`--stills <times>` picks the moments instead). Look at every
  one for what a lint can't judge: legibility over the background, emoji,
  and whether the joke reads.
- Those `--slides` PNGs double as a photo carousel (TikTok photo mode, an
  Instagram carousel). Offer that for `slideshow` and any list-style post.

Render: `node ${CLAUDE_PLUGIN_ROOT}/scripts/video/render.js <page>
${CLAUDE_PLUGIN_ROOT}/state/videos/<date>-<slug>.mp4`. The output is
1080×1920, 30fps H.264 with AAC audio mixed to about −14 LUFS, which is
what all three platforms expect. That file is what `--platform youtube`
uploads directly. Frames render in parallel (one browser per core but one,
up to four; `--workers` sets it), so a 12-second video takes well under a
minute on a laptop. For a quick look at timing and sync before the real
render, `--draft` makes a half-size 15fps version in a fraction of the
time; never post a draft. Several pages at once (a week of videos):
`render.js --batch <page> <page> ... [--outdir dir] [--cover 0]` renders
each to `<page>.mp4`, every hook variant included.

## Credits and labels

Copy the credit line from `assets/CREDITS.md` into every platform's
caption or description when it says one is required (Pexels, CC BY
photos, some tracks). If any AI image is photorealistic, tell the user to
switch on the platform's AI-content label when posting. TikTok, YouTube,
and Instagram all ask for it for realistic synthetic scenes.
