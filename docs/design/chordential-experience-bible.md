# THE CHORDENTIAL EXPERIENCE
### Direction codename: **THE SESSION**
*The client-facing site is not a website. It is a private studio session the visitor
is invited to attend. This document is the binding spec — implementation is reviewed
against it scene by scene, at fidelity. (Rule adopted 2026-07-06: the proof is the spec.)*

---

## 1 · Experience philosophy

**The one idea.** Visiting chordential.com is **attending a session**. The lights are
low. The room is warm. The work plays. You watch craft happen at close range, and by
the end you are not reading a services page — you have been *in the room*, and you
want your campaign to sound like this. The Executive Producer's exact thought on
leaving: *"These people care about craft as much as we do."*

**The audience.** EPs, heads of production, brand-side creative directors. They live
inside beautiful work all day; their filter for pretenders is instant. They cannot be
impressed by claims — only by **taste demonstrated under their nose.**

**The emotional arc** (the whole site is one piece of music):
*silence → first note → swell → full arrangement → resolution → invitation.*
Every scene, transition, and interaction sits somewhere on that arc. Nothing may
break it.

**Three governing words:** **Cinematic. Alive. Inevitable.**
(Inevitable = every motion feels like the only way it could have moved.)

**The anti-goals — instant failures:**
- Reads as SaaS, dashboard, CRM, or template. Death.
- Any motion that is decoration rather than meaning. Death.
- Autoplaying sound. Death (we are a music company; we *invite*, never assault).
- A section that would survive being printed. Death (Living-OS law applies here
  hardest of all).
- Fake clients or fake credentials. The work shown is our invented demo brands
  (AURORA, Vance Athletic) presented honestly as capability demonstrations — craft
  is provable without lying.

**Worlds.** The Experience lives in the **dark studio world** — ink, wine, ember,
warm smoke — with ONE deliberate excursion into the warm-paper world (The Proof
scene, §10.6), so the clearance documents feel like physical artifacts under a
reading lamp. Two worlds, one grade.

---

## 2 · The lighting bible

Light is the narrator. The visitor never watches elements appear — they watch
**light find things.**

- **The room key.** One warm key light, upper-left, consistent across every scene —
  the same lamp moving through the same studio. All shadow direction, all bloom,
  all reflection obeys it. Breaking the key = breaking the room.
- **Light reveals type.** Headlines are never faded in; they are **lit** — a soft
  beam sweeps and the letterforms catch it (mask-reveal driven by the beam's
  position), the way a music stand light finds a score.
- **Bloom is earned.** Soft bloom exists only on live things: the playing waveform,
  the active card, the record light, the CTA under the cursor. Static chrome never
  blooms.
- **The cursor is a lantern** (desktop): a subtle volumetric warm glow follows the
  pointer, brightening what it approaches — the visitor literally carries light
  through the studio. Radius ~300px, intensity ≤10%, additive. On touch devices the
  key light slowly patrols instead.
- **Atmosphere.** Every scene has depth-layered air: fine grain (2–4%), a slow
  volumetric gradient drift (90s+ loops, never perceptible as looping), occasional
  light-leak washes at scene boundaries. Backgrounds are never flat, never black —
  always **ink with warmth in it** (#141014 family with ember/wine radials).
- **Reflections.** Hero objects (the reel, the console, campaign cards) sit on an
  implied polished floor — a soft 8–12% vertical mirror fade. Studio, not void.
- **Edge light.** Depth is drawn by warm rim-light on object edges, not borders.

---

## 3 · The motion bible

**The signature law: the site has a tempo.** Chordential motion is **quantized to
96 BPM** (one beat = 625ms). Micro-reactions land on the 16th (156ms), reactions on
the 8th (312ms), arrivals on the beat (625ms), scene changes on the bar (2.5s).
Nothing animates on an arbitrary duration — everything on the site is *in time.*
Visitors will never name it; they will feel that the whole page is one piece of
music. This is our Awwwards signature.

- **Physics, always.** Every object has mass. Springs: entrances overshoot ~4% and
  settle (stiff spring, damping ~0.8); exits are ease-in and 60% of entrance time.
  Drags carry momentum and decay. Nothing appears; nothing vanishes — things
  **arrive** and **depart.**
- **Weight classes.** Type = light (fast attack, quick settle). Cards = medium
  (visible mass, small overshoot). Scenes/rooms = heavy (slow attack, long settle,
  the whole frame breathes with it).
- **Stagger is phrasing.** Grouped elements arrive as an arpeggio — 1/16th-note
  offsets (156ms), never simultaneously, never evenly robotic (±20ms humanization).
- **Idle is alive, barely.** Every scene at rest keeps exactly one pulse: the logo's
  slow breath (one breath per two bars), a waveform shimmering, air drifting.
  One. More is noise.
- **Reduced motion** collapses to full-lit, settled compositions with the grain and
  grade intact — a beautiful still film frame, never a broken animation.

---

## 4 · The interaction bible

Everything the visitor touches must feel like **studio hardware** — machined,
damped, expensive.

- **Buttons are physical.** Hover: rise 2px + bloom blooms + rim brightens (8th
  note). Press: compress scale .97 with a fast attack and a damped release — the
  feel of a console button. The primary CTA is **magnetic**: within 80px it leans
  toward the cursor (≤6px translation, spring-returned).
- **Cards tilt like faders.** Pointer position drives ≤6° perspective tilt + a
  moving specular highlight that obeys the room key. Leaving spring-settles them.
  Tilt is honest 3D (perspective transform), never a skew cheat.
- **Images shift parallax** to pointer at 2–4% — the room has depth, the visitor's
  head is moving.
- **Hover reveals meaning, not decoration:** on a campaign card, hover *starts the
  work* — the waveform stirs, the artwork breathes forward, the credit line lights.
  Hover = "may I?" and the object answers.
- **The cursor** (desktop): default is the lantern (above). Over playable things it
  becomes a small ring with a play glyph; over draggable scenes, a grab ring; over
  links, it tightens. Native cursor always visible inside it (never hidden —
  usability is craft too).
- **Focus states** are as designed as hover states: the ember ring, on-key. Keyboard
  users attend the same session.

---

## 5 · Scroll choreography

**Scroll is a dolly, not a scrollbar.** The visitor's scroll moves them *through
the studio* — scenes are rooms; the camera glides between them.

- **Scenes, not sections.** Each scene owns the full viewport and its own
  atmosphere. Scroll progress inside a scene drives its internal choreography
  (parallax layers at 3 depths minimum, type scale, light movement). Scroll between
  scenes triggers the **room transition** (§8).
- **Pinned sequences.** The two set-pieces (The Work §10.4, The Method §10.5) pin
  the viewport and convert scroll into *performance progress* — the visitor scrubs
  the moment like a jog wheel. Pin lengths ≤ 2.5 viewport-heights; never trap.
- **Momentum honesty.** Native scroll physics are respected — we choreograph *with*
  inertia (lerped catch-up, ~0.09 ease factor), never hijack to a fake smooth-scroll
  that fights the OS. A fast flick skips gracefully; choreography is interruptible
  at any frame.
- **The progress instrument.** Page progress is a thin vertical **VU-style meter**
  on the right edge — filling ember, with scene-markers like track indices. It is
  the site's table of contents and the only persistent chrome besides nav.

---

## 6 · Hero concepts (choose one; A is the recommendation)

**A · "THE FIRST NOTE" — recommended.**
Black-warm silence. A single point of ember light. On load (or first pointer
movement) one piano note sounds *only if the visitor has opted into sound* —
visually, the note happens regardless: the point blooms, a circular wave of light
expands, and as it passes across the darkness it **lights the wordmark into
existence** letter by letter. The tagline is lit next by a slower second wave.
Ambient dust drifts in the volume. The lantern-cursor now works — the visitor
realizes *they* control the light. CTA fades up on the second bar: **"Begin a
session."** The logo breathes once per two bars, forever.
*Why it wins: it is the brand — sound becoming light becoming craft — in 4 seconds,
and it hands the visitor the light.*

**B · "THE DOWNBEAT."** A conductor's baton-line draws itself across the dark,
snaps up on the prep beat, and on the downbeat the whole room illuminates at once —
type, nav, atmosphere arriving as one chord. Navigation remains a horizontal
baton-line that conducts section changes.

**C · "TAPE START."** A reel-to-reel close-up; the reel spins up from stop (real
inertia), tape hiss visualized as grain sharpening into the wordmark; the timeline
of the page is the tape.

---

## 7 · Navigation & cursor behavior

- **Nav is a program, not a menu.** Top-right, four entries max: *The Work · The
  Method · The Studio · Begin a session.* Idle: quiet ink-on-dark text. The active
  scene's entry carries a small breathing ember dot (honest position indicator).
- **Opening nav (mobile / expanded)** is a room event: the current scene dims and
  recedes 4% in depth; the program rises as a lit card stack (arpeggio stagger).
  Closing reverses at 60%.
- **The wordmark** top-left breathes (the one idle pulse of every scene) and is
  always the way home.
- **Cursor** per §4. On scene boundaries the lantern briefly flares — the visitor
  feels the door.

---

## 8 · Transition language — entering another room

Scene changes are **doorways**, one bar long (2.5s max, interruptible):

1. The current room's light **draws toward the exit edge** (bottom), compressing
   into a warm horizon line.
2. A **light-leak wash** crosses the frame (the door opening).
3. The next room's atmosphere arrives *before its content* — grade, air, key light
   first (300ms), then the content arpeggio.

Variants keyed to meaning: entering The Work = the wash is a waveform sweep;
entering The Proof = the wash brightens to warm paper (the world flips light);
entering The Invitation = the wash is the record light igniting.

---

## 9 · Sound policy (a music company's site)

- **Never autoplay. Ever.** A small, beautiful "Sound on" invitation sits in the
  hero (a breathing waveform glyph). One click arms the session soundtrack: room
  tone + the demo work + micro-UI notes (all in **D major** — the brand key,
  consistent with the product's award chord).
- With sound on: hovers tick softly (velocity-sensitive, ≤ -30LUFS), the hero note
  plays, campaign cards audition on hover, scroll positions crossfade stems.
- With sound off: every audio moment has a visual twin (the waveform IS the sound).
  The site is complete silent; it is *transcendent* loud.

---

## 10 · Section-by-section storyboard (the program)

**10.1 · DOORS — the hero ("The First Note," §6A).**
Beat count: light-bloom bar 1, wordmark bars 1–2, tagline bar 3, CTA bar 4.
Tagline: *"Original music for campaigns. Composed, cleared, delivered."*

**10.2 · OVERTURE — the claim.**
One sentence at a time, each **lit** as scroll brings it: *"Agencies don't need
more music."* → *"They need music they can ship."* → *"We compose it, clear it,
and hand you the stems."* Type scales subtly with scroll (98→102%); the air
parallaxes behind. No imagery — confidence is type and light.

**10.3 · THE ROOM — establish the studio.**
A slow cinematic pan across a warm studio still-life (real, honest imagery per the
brand: instruments at rest, consoles, paper scores — graded to the palette).
Three depth layers parallax against scroll; dust drifts through the key light.
A single caption line: *"A studio built like a production company."*

**10.4 · THE WORK — the listening room (set-piece #1, pinned).**
Campaign demo cards (AURORA · Vance Athletic · Northwind — labeled honestly as
capability demonstrations) hang in the dark like master tapes in warm air.
Scroll = the jog wheel: cards glide past in 3D, the centered card blooms, tilts to
the pointer, and **its waveform stirs alive** (audio-reactive with sound on; scroll-
reactive without). **The wow:** clicking a card **explodes it into its stems** —
the artwork splits into five hovering layers (drums / bass / strings / synths /
voice), each a floating strip with its own animated waveform, fanned in 3D. Hover a
stem to solo its motion. The delivery is *visible as parts* — that is the product,
demonstrated. A "back" gesture reassembles them with spring physics into the card.

**10.5 · THE METHOD — the signal chain (set-piece #2, pinned).**
The pipeline drawn as a **studio signal path**: Brief → Direction → Composition →
Controlled Variation → Clearance → Delivery, rendered as a patched console — thin
cables of light connect stages, and as the visitor scrolls, **a pulse of signal
travels the chain**, each stage's module lighting and its one-line promise lit with
it. At Clearance, the pulse stamps a seal. At Delivery, the pulse fans into eleven
tiny file glyphs — the package, assembling itself. (This is the Experience-grade
version of the product's arc diagram — one visual language, two contexts.)

**10.6 · THE PROOF — the paper room (the world flips).**
The doorway wash brightens and the visitor stands in the warm-paper world: a
cleared **rights certificate and cue sheet** on cream stock under a reading lamp,
rendered as physical documents — grain, ink, a wax-red "CLEARANCE CERTIFIED" seal
that **stamps down with weight** as the scene settles. Copy: *"Every note owned.
Every clearance on file. Nothing to bite you in legal."* This scene is deliberately
*still* by contrast — the confidence of paper. One motion only: the stamp, and the
lamp's warmth breathing. Then the doorway returns us to the dark.

**10.7 · THE STUDIO — who's in the room.**
The craft, human: composers' hands, sessions, scores — a slow filmic sequence with
depth parallax. Names and disciplines light as credit lines (tracked mono
eyebrows). No stock, no headshots-on-white, ever.

**10.8 · THE INVITATION — the encore.**
The room quiets. The record light ignites (the one breathing ember). Copy:
*"Your campaign, scored."* The **"Begin a session"** CTA — magnetic, physical,
bloomed — with the honest promise beneath: *"Tell us about the project. We reply
with an approach and a price range."* Footer is a single elegant program line
(condensed per the standing site rule). The final idle state: the record light
breathing in the dark. The session never quite ends.

---

## 11 · The memorable five (wow moments, ranked)

1. **The stem explosion** (10.4) — a campaign card bursts into five living stems
   and reassembles on spring physics. *The product, demonstrated in one gesture.*
2. **The First Note hero** (6A) — sound becomes light becomes the brand; the
   visitor inherits the lantern.
3. **The signal chain** (10.5) — the method as a console the visitor plays with
   scroll.
4. **The world flip to paper** (10.6) — dark cinema to warm document and back; the
   stamp with real weight.
5. **The tempo itself** (§3) — never announced, always felt: the entire site moves
   at 96 BPM.

---

## 12 · Premium interaction checklist (ship gate)

Every scene must pass ALL of these before it ships:
- [ ] Contains motion that cannot exist in print, with narrative purpose.
- [ ] Obeys the room key light; no off-key shadows or blooms.
- [ ] All durations quantized to the 96 BPM grid.
- [ ] Entrances spring-settle; exits are 60% and ease-in; nothing pops.
- [ ] Pointer changes something physical (tilt, light, parallax) — desktop.
- [ ] Holds 60fps on a mid-tier laptop: transform/opacity only in loops; canvas/
      WebGL budgeted; blur rationed; DPR capped at 2; heavy scenes lazy-armed.
- [ ] Fully interruptible — a fast scroll never traps or janks.
- [ ] Reduced-motion renders a gorgeous still frame, not a broken one.
- [ ] Keyboard path is complete and focus states are designed.
- [ ] Mobile: choreography adapts (tilt→gyro-optional, pin lengths halved,
      lantern→patrolling key light); nothing desktop-only breaks the arc.
- [ ] Silent-mode visual twin exists for every audio moment.
- [ ] Honesty holds: demo brands labeled, no fake logos, no fake numbers.
- [ ] The scene would make an EP pause. If it wouldn't — recut it.

---

## 13 · Approval & build order (after sign-off only)

Hero ("The First Note") → The Work + stem explosion → doorway transition system →
The Method → The Proof → Overture/Studio/Invitation → sound layer → polish pass
against §12 per scene. Each scene ships only at bible fidelity — *the proof is the
spec.*
