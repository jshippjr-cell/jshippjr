# Sound guide

How a project gets its sound in videos rendered by `scripts/video/render.js`.
`short-form-video` and `/marketing-skill:marketing-setup` read this file to
propose a **sonic identity**: one genre, tempo, key, energy, and signature
hook, saved in `references/brand-voice.md` and used for every video. Hearing
the same hook and sound video after video is what makes it recognizable,
the way a jingle works.

## The genres

The renderer composes original music in eleven genres (`<body data-music>`).

| Genre | What it sounds like | Tempo (default) | Mode | Fits |
|---|---|---|---|---|
| `pop` | Bright plucked synth chords, punchy kick and clap, a plucked lead | 110–124 (118) | major | Consumer apps, DTC brands, lifestyle, broad audiences |
| `house` | Four-on-the-floor kick, offbeat open hats, organ stabs, offbeat bass | 120–126 (124) | minor | Fitness, fashion, nightlife, launches, energetic 18–34 audiences |
| `hiphop` | Half-time trap groove, 808 bass, hi-hat rolls, a bell lead | 130–150 (140) | minor | Gen Z, streetwear, gaming, creators, music |
| `acoustic` | Strummed guitar, shaker, snaps, a harp-like lead | 90–110 (100) | major | Food and drink, local business, wellness, travel, handmade |
| `cinematic` | String swells, low impacts, toms, a slow build | 70–100 (90) | minor | Big launches, brand stories, nonprofits, fundraising |
| `tech` | Clean arpeggios, steady kick, an electric-piano lead | 105–120 (112) | major | B2B SaaS, developer tools, fintech, productivity, explainers |
| `lofi` | Dusty electric piano, swung boom-bap drums, vinyl crackle | 75–90 (84) | minor | Study and productivity, creators, coffee and cozy brands |
| `calm` | Soft keys and pad, a held bass, light shaker, a bell lead | 80–96 (88) | major | Testimonials, healthcare, finance, team intros, sensitive topics |
| `phonk` | Cowbell hook, distorted 808 slides, hard hats with rolls, dark strings | 130–150 (140) | minor | Gen Z and Gen Alpha feeds, gaming, cars, fitness, meme edits |
| `jersey` | Jersey club's bouncing kick, chopped synth stabs, tom fills | 135–145 (140) | minor | Dance and trend formats, fashion, beauty, nightlife, Gen Z |
| `funk` | Brazilian funk's tamborzão groove, booming 808, synth stabs, cowbell | 125–135 (130) | minor | High-energy trend formats, sports, streetwear, Gen Z and Alpha |

`data-music="none"` keeps only the sound effects.

## Picking a sonic identity from the project

Read the project's audience, tone, and product (from `brand-voice.md` and
the project's README) and match them:

| Signal in the project | Leans toward |
|---|---|
| Young, trend-driven audience (Gen Z, gaming, streetwear) | `hiphop` or `house`, energy 4 |
| Very online Gen Z or Gen Alpha audience, memes welcome in the voice | `phonk`, `jersey`, or `funk`, energy 4 |
| Broad consumer audience, playful or upbeat tone | `pop`, energy 3–4 |
| Professional or technical buyers, "confident, plain-spoken" tone | `tech`, energy 3 |
| Warm, human, local, or handmade | `acoustic`, energy 2–3 |
| Trust-first (health, money, care) or a reassuring tone | `calm`, energy 2 |
| Relaxed, cozy, or creator-focused | `lofi`, energy 2 |
| Mission-driven, or a big moment | `cinematic`, energy 3 |

- **Mode:** major reads upbeat and warm; minor reads serious, driven, or
  edgy. Use the genre's default unless the tone clearly says otherwise.
- **Energy (1–5):** 1–2 is sparse, sitting under talking-head-style text;
  3 is the default; 4–5 adds hats, open hats, fills, and doubles the hook
  for hype. A single video can move energy up or down one step for its
  type, e.g. +1 for an announcement. The rest of the identity stays fixed.
- **Key:** any; pick one and keep it. Changing key between videos weakens
  recognition more than any other setting.
- **Testimonials and sensitive topics** use `calm` whatever the identity
  says, so the music never undercuts what someone said. Keep the
  project's key and hook.

Propose two identities, each with one line on why it fits. Render a
preview of each so the user can listen before choosing:

```
node scripts/video/render.js --sample tech preview-a.m4a --motif "1 5 3 5 | 6 5 3 2" --key C --mode major --energy 3
node scripts/video/render.js --sample acoustic preview-b.m4a --motif "1 2 3 5 | 3 2 1 -" --key A --energy 2
```

Each preview takes a few seconds. Claude can't hear audio, so the user's
ear decides; never call a hook "catchy" on Claude's say-so.

## The hook (`data-motif`)

Two bars of scale degrees. Each bar's notes share it equally, so four
notes are quarter notes and eight are eighths. `'` raises a note an octave,
`,` lowers it, `-` holds the previous note, and `.` is a rest. Bars are
separated by `|`.

The hook is the melody at the drop, answered by a variation every four
bars. It closes every video as a sonic logo: its first three notes, then
home on the final beat. What makes a hook stick:
- Short (two bars), and heard more than once.
- Mostly steps, with one leap for character.
- A rhythm you could clap: a rest or held note helps.
- It ends on a stable note (1, 3, or 5), or on 2 if it should feel
  unresolved until the logo.

A library to start from (each genre's default is marked):

| Hook | Character |
|---|---|
| `1 3 5 3 \| 6 5 3 -` | Bright, rising, friendly (`pop` default) |
| `1 . 3 5 \| 4 3 1 -` | Driving, club (`house` default) |
| `5 . 3 1 \| 2 . 1 -` | Dark, laid back (`hiphop` default) |
| `1 2 3 5 \| 3 2 1 -` | Warm, simple, folk (`acoustic` default) |
| `1 - 5 4 \| 3 - 2 -` | Epic, open-ended (`cinematic` default) |
| `1 5 3 5 \| 6 5 3 2` | Busy, optimistic (`tech` default) |
| `3 . 1 5, \| 1 - . .` | Lazy, nostalgic (`lofi` default) |
| `5 3 2 1 \| 2 - 1 -` | Gentle, reassuring (`calm` default) |
| `1 1 3 1 \| 4 3 1 5,` | Menacing, chant-like (`phonk` default) |
| `1 . 1 3 \| 5 . 4 3` | Bouncy, call-and-response (`jersey` default) |
| `1 3 1 . \| 5, 1 3 .` | Punchy, stop-start (`funk` default) |
| `1 1 5 5 \| 6 6 5 -` | Playful, sing-song (kids, games) |
| `5 6 5 3 \| 2 3 1 -` | Confident, jingle-like (retail, food) |
| `3 5 6 1' \| 6 5 3 -` | Soaring, aspirational (education, travel) |
| `1 3 2 4 \| 3 5 4 -` | Curious, stepwise (explainers, science) |

Write your own if none fits. The renderer warns and falls back to the
genre's default if a hook can't be read.

## Everyday and FYP posts

The everyday formats in `fyp-formats.md` (POV, tier lists, text skits) each
suggest a genre that suits the format: `phonk` under a "nobody: / me:"
reveal, `lofi` under a text-message skit. They can borrow that genre, but
keep the identity's **key and hook**, so the sonic logo at the end still
sounds like the brand. Stay inside what the brand voice allows: a
trust-first brand keeps `calm`, `lofi`, or `acoustic` even on a meme
format, and `phonk`, `jersey`, and `funk` only suit a voice that already
welcomes memes.

## Sound effects

`data-sfx` cues place these on the page's own timing. All are synthesized
originals, so there's nothing to license.

| Sound | What it is | Use it for |
|---|---|---|
| `pop` | A short note that climbs the chord when cues land close together | Words or items appearing |
| `swish` | A quick airy sweep | A card or caption sliding in |
| `whoosh` | A longer sweep | Scene changes, a wipe |
| `tick` | A tick that climbs a scale across a run | Checklists, timers counting down |
| `click` | A UI click | A tap or button press |
| `chime` | Two bell notes in the project's key | A done moment, a soft CTA |
| `ding` | A clean bell | A right answer, a green flag, an S-tier pick |
| `buzzer` | A game-show buzzer | A wrong answer, a red flag, a D-tier pick |
| `boom` | A deep impact with a reverb tail | The punchline, a reveal, a 10/10 |
| `bass` | A sub drop | Under a big moment, with or instead of `boom` |
| `scratch` | A record scratch | The turn in expectation vs reality, "wait, what?" |
| `horn` | An air horn | A hot take, a hype moment; use sparingly |
| `rimshot` | Ba-dum-tss | The joke's last line |
| `fail` | A sad-trombone slide down four notes (about 2s) | A plan going wrong |
| `drumroll` | A 1.5s snare roll | Before a reveal: cue it 1.5s before the hit |
| `ping` | A message notification | Chat bubbles, notifications, comments |
| `typing` | A few keyboard taps | Text being typed, renamed, or edited |
| `shutter` | A camera shutter | Timestamps in a day-in-the-life, photo dumps |
| `cash` | A ka-ching | Getting paid, a sale, a price |
| `glitch` | A digital stutter | An error, a crash, a "system overload" bit |

One or two meme cues per video is plenty; the rest should be the quiet
ones (`pop`, `swish`, `tick`). Under a voiceover, use fewer still: scene
changes and one or two key moments, about one every 3 seconds at most. Every cue is mixed under the music, and the
whole mix lands at about -14 LUFS, so a cue never jumps out of a feed.

## Licensed tracks instead

The generated music is written for 10 to 30 second videos: it repeats the
same few bars, which works in a short and wears thin past about 45
seconds. For anything longer, use a licensed track; the renderer warns
when a long video doesn't.

For real produced music, put the file in the page's `assets/` folder and
set `<body data-music-src="assets/track.mp3" data-music-start="12">`
(seconds into the track). `data-music-at="4"` brings the music in 4
seconds into the video instead of at the start: for an opening line that
plays alone, or a track shorter than the video, so it can still end with
it. The renderer trims it to the video, fades it in
and out, dips it a few dB under each sound effect, and mixes it to the same
loudness as everything else.

### Cutting to the track's beat

`scripts/video/beats.js` reads a track's rhythm with ffmpeg, locally:

```
node scripts/video/beats.js assets/track.mp3 --align 2.2 --duration 24
```

It prints the tempo, a confidence from 0 to 1, the biggest lifts (a
drop, a chorus, the beat coming in), the `data-music-start` that lands the
biggest lift at `--align` seconds into the video, and every beat and bar in
video time. Use it like this:

- **Confidence 0.5 or more:** set `data-music-start` from it, align the
  lift with the end of the hook, and put scene changes (`--out`) and key
  cues (`--in`) on the printed bar times, or on beats when it says the bars
  are a guess.
- **Under 0.5:** the track has no steady beat (ambient, cinematic, free
  tempo). Don't snap anything to it; time scenes to the voiceover or to
  reading pace.

It was checked against this plugin's own music in eight genres (exact
tempo and beats within a few milliseconds in seven, and a low confidence on
the eighth), plus noise and a sustained pad. You can't hear the result, so
send the user an `--audio-only` render or a short preview to check the
sync.

Only use a track the user has a license for, and record where it came
from, so the credits stay with the video:

```
node scripts/video/media.js credit assets/track.mp3 --source "Pixabay Music" --license "Pixabay Content License" --link "<track page>"
```

Places to get one (check each track's own terms; they vary):
- **Openverse, from here:** `node scripts/video/media.js search "<mood>"
  --type music --out <assets>` finds Creative Commons tracks that allow
  commercial use and changes, saves each one's credit line, and reports
  its tempo and beat confidence, ready for `beats.js`.
- **YouTube Audio Library:** free, in YouTube Studio. Some tracks require a
  credit line, and the license is meant for YouTube.
- **Pixabay Music:** free under the Pixabay Content License, including
  commercial use.
- **Paid libraries** (Epidemic Sound, Artlist, Musicbed): a subscription
  covers social posting for the subscribed accounts.
- **AI music services** (Suno, Udio, ElevenLabs Music): commercial use
  depends on the plan; free tiers often exclude it.
- **Creative Commons** (ccMixter, Free Music Archive, Openverse): needs a
  credit line, and avoid NC (non-commercial) licenses for a business
  account.

Never use a popular song without a license. Platforms mute or claim the
video, even if the clip is short.

**Trending sounds** only exist inside each app. If the user would rather
post with one, they add it in the app and turn the video's own audio down.
Posting through an API can't add one.

## Voiceover

A voice goes on top of the music and effects. Only use the user's own
recording, or a voice they generate with a service they have their own
key for. Never imitate a real person's voice without their permission, and
if the voice is AI-generated, check whether the platform asks for an
AI-content label.

- **One line per file:** record each line of the script separately
  (`voice-1.m4a`, `voice-2.m4a`, ...), put them in `assets/`, and add
  `data-voice="assets/voice-1.m4a"` to the element the line belongs to.
  It plays at that element's `--voice` time, or `--in`. A flubbed line is
  then one quick re-record, and each scene can be timed to its line.
- **One continuous take:** `<body data-voice-src="assets/voice.m4a"
  data-voice-start="0.5">`.
- **What the renderer does:** trims the silence at both ends of each line
  (it starts on its cue, and its length is the speech itself), filters low
  rumble, compresses lightly, and levels every line to the same loudness. The music and effects sit about 7 dB
  under the voice and duck about 10 dB more while someone is speaking.
  The whole mix still lands at -14 LUFS.
- **Recording:** a quiet room (a closet full of clothes works well), the
  phone about 20 cm away and a little off to the side, and the phone's
  voice memo app. Any format ffmpeg reads is fine.
- **Timing:** `render.js <page> --voice-lengths` lists each line's start,
  length, and the room its scene leaves; give each scene its line plus a
  beat. The renderer warns when lines overlap, run past their scene, or run
  past the end. `compose.js` does all of this for a narrated video.
- **Captions:** most people watch muted, so every voiced line should be
  captioned. `<div class="say auto" data-voice="...">` shows the line word
  by word, timed to the clip (see `video-rendering.md`), and the render
  writes an `.srt` file for the platforms' own caption tracks.

### A free generated voice

When the user would rather not record, `scripts/video/voice.js` reads the
script with Kokoro, an open-source model (Apache-2.0) that runs locally:
no account, no API key, no cost. One-time setup is `npm install
kokoro-js` in `scripts/video` (about 600 MB), and the first run downloads
the model (about 90 MB) from Hugging Face; after that it works offline.

```
node scripts/video/voice.js --audition samples "The first line of the script."   # four voices, same line
node scripts/video/voice.js script.md --out assets --voice af_heart               # voice-1.wav, voice-2.wav, ...
```

The script file takes numbered lines (`1. ...`) or one paragraph per line.
`--voices` lists all 28 voices with a quality grade; the best are
`af_heart` and `af_bella` (American, female), then `am_michael` and
`am_fenrir` (American, male) and `bf_emma` (British, female). `--speed`
sets the pace (1 is normal). You can't hear the result, so send the
audition files to the user and let them pick. These are synthetic stock
voices, so if a platform asks whether a video uses AI-generated audio, the
answer is yes.
