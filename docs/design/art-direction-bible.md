# Chordential — Art Direction Bible
### Codename: **STUDIO LIGHT**
*The visual language of a premium creative-technology company whose product is human craft.*

> This is a visual identity system, not a component library. It defines how
> Chordential should **feel** — the light, the materials, the motion, the moments.
> Implementation comes later; this is the north star everything is measured against.

---

## 0. The one idea

**Warm light on real materials.**

Chordential runs a music studio *and* the operating system beneath it. The product
is human taste; the software is the proof. So the aesthetic can never read as
machine-made, cold, or generic. It must feel **authored** — like a boutique
mastering room: low warm light, honest materials (paper, sand, ink, brushed
metal), one confident accent, and nothing on screen that wasn't put there on
purpose.

Everyone else in "premium SaaS" reaches for the same midnight-blue glass and neon.
Chordential's premium is the opposite move: **analog warmth executed with digital
precision.** Restraint is the flex. The screen should feel like it has a
temperature.

Three words govern every decision: **Warm. Precise. Made.**

**The North-Star test.** Before shipping any surface, ask: *"Does this feel like it
came from a studio with taste, or from a component library?"* If it could belong to
any B2B tool, it's wrong.

---

## 1. Palette — the emotional map

The palette is already warm and editorial. Art direction's job is to assign each
color a **role and an emotion**, and to hold the discipline of one voltage.

| Token | Hex | Role | Emotion |
|---|---|---|---|
| Cream | `#FCF7F8` | The page. The paper everything sits on. | Calm, gallery, breathing room |
| Sand | `#D8CDB6` | Warm structure — hairlines, stickers, edges | Craft, tactility, analog |
| Panel | `#F5EFE6` | Recessed surfaces (inputs, tracks) | Quiet, held |
| Olive | `#737469` | Muted text, secondary voice | Editorial, understated |
| Slate | `#546671` | Information, links, cool counterweight | Trust, clarity |
| Ink | `#1F1E1E` | Primary text; the grand-piano black | Authority, gravity |
| Wine | `#44161E` | Rich / special / ceremony | Depth, luxury, occasion |
| **Ember** (orange) | `#E4671F` | **The one voltage** — go, live, decision | Heat, action, life |
| White | `#FFFFFF` | Floating cards lifted off the cream | Focus, elevation |

**The discipline:** *one voltage per view.* Ember is the only saturated color and
it appears **once or twice per screen, never more** — the live dot, the single
primary action, the moment that matters. Wine is for gravity and ceremony (a
delivered package, a signed agreement), never for routine chrome. Everything else
is the warm neutral field. When two things both want to be orange, one of them is
wrong.

**What we never do:** pure `#000` or `#FFF` as a field color (too cold — always the
cream/ink pairing), rainbow status systems, gradients that introduce a hue not in
the palette, or a second accent competing with ember.

---

## 2. Lighting system

Light is the soul of STUDIO LIGHT. The mental model is a **listening room lit by
one warm source** — soft, low, directional, never fluorescent.

- **Ambient glow.** Light is *warm* (biased toward cream/ember), never blue. A
  glow is a low-opacity ember or wine radial bloom (4–8% max) behind a hero object
  or a live element — felt, not seen. Think of the lamp just off-frame, not a
  neon sign.
- **Directional key light.** A consistent top-left key light governs every shadow
  and highlight. Cards catch a 1px lighter top edge; shadows fall soft and warm
  down-right. This single rule makes the whole UI feel like one physical space.
- **Bloom.** Reserved for the live/active state only — the breathing ember dot, the
  active reel card, a "sending" pulse. Bloom is a privilege earned by importance;
  static chrome never blooms.
- **Edge lighting.** Premium elevation comes from a **warm hairline**, not a heavy
  border: a `sand`/`border2` 1px edge plus an inner top highlight (`rgba(255,255,255,.6)`).
  This is the single most important premium tell — objects are *lit*, not outlined.
- **Shadows.** Two-layer, warm-tinted (never gray): a tight contact shadow
  (`rgba(31,30,30,.05)`) + a soft ambient drop (`rgba(31,30,30,.07)`). Wine-tinted
  shadows for ceremony surfaces. Shadows say "this is a real object on real paper."

**Gradients.** Almost never linear "brand gradients." When used: (a) a **cream→sand
vertical warmth** on large fields to fake room light, (b) a **wine→ember diagonal**
only on ceremony CTAs (deposit paid, package delivered), (c) an **ink→wine** for a
premium dark ceremony surface. Every gradient stays inside the palette; no
off-palette hue ever appears. Gradients are ≤12% contrast — a whisper of depth, not
a poster.

---

## 3. Material system

Every surface is one of five honest materials. Materials are consistent — a "paper"
element behaves like paper everywhere.

1. **Paper (cream).** The ground. Matte, warm, slightly imperfect (a faint grain).
   The letterhead, the page, the brief. This is home base.
2. **Card (white, lifted).** A clean sheet floated above the paper by warm shadow +
   top-edge highlight. Where work happens. Radius `13px`, generous internal padding.
3. **Panel (sand-tint, recessed).** Inputs, tracks, wells — materials that sit
   *into* the surface, not on it. Slightly darker than the page, no shadow, inner
   hairline. The inverse of a card.
4. **Glass (rare, purposeful).** Translucent, warm-tinted blur (`backdrop-filter`,
   cream-biased, ~10–14px). **Only** for transient overlays — the command drawer,
   scrims, the docked player. Never a decorative material; glass means "this is
   floating above and temporary." Always with a warm scrim behind it, never a
   cold frost.
5. **Metal / ink (ceremony).** Brushed graphite / grand-piano black for moments of
   authority — the delivered package header, a signed agreement, the wordmark
   lockup. Subtle vertical sheen, wine undertone. Used sparingly; metal is the
   tuxedo.

**Rule:** a surface's material is determined by its *job in the hierarchy*, not by
taste-of-the-day. Floating/temporary → glass. Where-you-work → card. Type-into →
panel. Ceremony → metal. Ground → paper.

---

## 4. Surface hierarchy

Depth is legible and consistent — you always know what's on top and why. Four
strata, from back to front:

```
Z0  PAGE / PAPER      cream field, warm grain, room-light gradient
Z1  PANELS            recessed sand wells (inputs, tracks, tables)
Z2  CARDS             white sheets, warm shadow, top-edge highlight
Z3  FLOATING          drawers, popovers, docked player — glass + scrim
Z4  CEREMONY / TOASTS ink/metal moments, the one ember voltage, live dots
```

- Elevation is expressed by **light and shadow depth**, never by stacking borders.
- Only **one** Z3 floating element at a time (a drawer OR a popover, never both).
- The active object rises and its siblings **dim** (`--dim-sibling: .55`) — attention
  is a spotlight, and the rest of the room politely steps back. This is the core
  "focus" gesture of the whole system.
- Never more than **three depth cues** on one element (shadow + highlight + scale is
  the ceiling). Piling on effects is how premium dies.

---

## 5. Typography — the editorial voice

Type is where "creative company" is won or lost. STUDIO LIGHT is **editorial**, not
techy: think a design monograph or a liner-notes booklet, not a dashboard.

- **Display / headlines.** Large, tight, confident. A high-contrast serif or a
  refined grotesque with real personality (editorial weight 700–780, letter-spacing
  slightly negative at large sizes). Headlines are *statements* — short, declarative,
  never a UI label dressed up. The wordmark and hero heads carry the studio's voice.
- **Body / UI.** A clean, humanist sans (the current system stack is fine as a
  floor; a licensed humanist grotesque is the ceiling). Comfortable line-height
  (1.5–1.65), generous measure, ink on cream.
- **Micro-label / eyebrow.** Uppercase, tracked (`.08–.14em`), small, olive/muted.
  The "credit line" voice — section kickers, provenance pills, metadata.
- **Numerals.** **Tabular** everywhere numbers align or change (prices, scores,
  timers, counts). Non-negotiable — misaligned numbers read as amateur.
- **The pairing tension:** an editorial display voice + a quiet functional body +
  a tracked credit-line micro voice = the three registers of a well-made record
  sleeve. Never more than these three.

**Rhythm.** A real type scale (roughly 1.25 ratio), consistent vertical rhythm, and
**white space as a material** — premium is mostly the confidence to leave room.

---

## 6. Image direction — photography

Chordential's honesty rule forbids stock cliché and fake clients. Imagery must feel
**authored and true**: real rooms, real hands, real instruments — the *craft*, not
the corporate.

- **Subject.** Instruments and the studio at rest; hands on keys/strings/faders;
  paper scores; the room. **Never** headset stock, laptop-and-coffee, or "diverse
  team high-fiving." If we can't shoot it true, we don't fake it — we defer to
  typographic or material treatment instead.
- **Composition.** Editorial and negative-space-forward. Off-center subjects,
  generous margins, one clear focal point. Rule-of-thirds with room to breathe —
  the image is framed like an album cover, not filling a hero slot.
- **Depth of field.** Shallow, cinematic. A single plane in focus, warm bokeh
  falling off. The eye is directed, the rest is atmosphere.
- **Light in-frame.** Match the UI: **warm, low, directional, single-source.** Golden
  key, soft shadow. No cool daylight, no ring-light flatness.
- **Color grade.** Graded into the palette — warm shadows (ink/wine in the blacks),
  cream in the highlights, ember only where something is truly hot (a glowing tube
  amp, a record light). Desaturated by ~10–15%; nothing garish. The grade is the
  same LUT as the UI's light.
- **Treatment.** Images sit on the paper with a **1px warm inset outline + soft
  shadow** (never a hard rectangle floating in space), often with a faint duotone
  wash toward wine for ceremony imagery.

---

## 7. Illustration language

Illustration is used sparingly and only where a photograph can't be honest (empty
states, concept diagrams, the "how it works" spine). The language is **line-drawn,
warm, and diagrammatic** — the feel of margin sketches in a well-made manual.

- **Style.** Fine single-weight ink line on cream, with one ember or wine fill for
  emphasis. Loose but precise — a studied hand, not a mascot. No gradients, no 3D
  blobs, no generic "SaaS people."
- **Motifs.** The waveform, the staff line, the signal path, the console, the
  helix/reel, the hairline grid. Chordential's world is *sound made legible* —
  illustrations visualize signal and structure.
- **The signature device: the hairline diagram.** Data and process rendered as thin
  ink lines and small nodes on paper — a schematic aesthetic (procurement-grade,
  engineering-honest) that doubles as brand. The pipeline, the delivery graph, the
  buyer↔creator map all speak this one visual language.
- **Never:** flat corporate vector illustration, isometric city scenes, gradient
  mesh blobs, emoji-as-illustration.

---

## 8. Iconography

- **Grid & weight.** 24px grid, ~1.75px stroke, rounded joins/caps. One weight
  system-wide. Icons are quiet line marks, not filled glyphs — they match the
  hairline illustration language.
- **Personality.** Precise but warm — the corners are softened, the geometry is
  honest. A tuning-fork, a waveform, a stamp/seal (for certified rights), a helix
  (the reel) form a small set of **proprietary marks** that only Chordential uses.
- **Color.** Icons are ink or olive by default; ember **only** when the icon is the
  live/primary action. An icon is never decoratively colored.
- **Rule:** an icon always pairs with a label in product surfaces (icon-only is for
  the most learned controls). Recognition over cleverness.

---

## 9. Motion language

Motion is already codified in the system (`--ease-spring`, `--t-micro/react/move/panel`).
The art direction: **physical, warm, and calm.** Things move like well-damped
studio gear — weighted, settled, never bouncy-cartoonish, never robotic-linear.

- **Physics vs. optics.** Physical properties (position, size, inset) use the spring
  ease; optical properties (opacity, color) use the smooth `ease-out`. Motion
  obeys mass.
- **Every exit = 0.6× its entrance.** Things arrive with presence and leave
  discreetly. Nothing lingers.
- **Duration ladder.** `micro .15s` (press, focus, icon swap) → `react .25s` (hover,
  dim, flip) → `move .4s` (content/row/card arrival) → `panel .6s` (drawers, covers).
  Never improvise a duration; pick a rung.
- **Choreography, not events.** When many things change, they **stagger** (40–60ms
  offsets) so the eye reads sequence, not chaos. Arrival is a phrase, not a flash.
- **Restraint.** No parallax carnival, no spinning loaders, no attention-seeking
  wiggles. The most premium motion is the motion you feel but don't notice.
- **Reduced motion is first-class.** Every motion has a dignified `prefers-reduced-motion`
  collapse — instant, no transform — that still looks intentional.

---

## 10. Background treatments

The cream field is never dead-flat — flatness reads as cheap. But texture is
**felt, not seen.**

- **Grain.** A very fine, low-opacity film grain (~2–4%) over the paper — the
  tooth of real stock. Static, warm-toned. This is the single biggest "made-not-
  generated" tell on a large empty field.
- **Room-light gradient.** A barely-there cream→sand vertical warmth (≤8% contrast)
  suggesting a light source above — the page has a top and a bottom.
- **Structural whisper.** For data-dense or ceremony surfaces, a faint hairline grid
  or staff-line motif at 3–5% — the engineering paper / manuscript paper reference.
- **Never:** visible noise, busy patterns, dot-grids that fight the content, or
  animated background particles.

The rule: at arm's length the background looks like clean warm paper. Only up close
do you notice it has a surface.

---

## 11. Hero moments — one per major surface

Each major page earns a single, memorable **hero gesture** — the thing you'd
screenshot. One per page; heroes don't compete.

- **Front-of-house (home).** A warm, low-lit film of the studio/instrument at rest,
  graded into the palette, with an editorial headline arriving in a staggered phrase
  over it. The room breathes; the type states the promise.
- **The Reel.** The signature interactive moment — the **helix of tracks in warm
  space**, one confident ember-lit card popped forward, the rest receding into
  soft bokeh. Sound made spatial. This is Chordential's "wow."
- **Dashboard / Today.** Quiet authority: the pipeline as a **living hairline
  diagram**, one ember "next action" glowing, everything else calm. The hero is the
  *calm* — a founder's command deck that doesn't shout.
- **Opportunity.** The **Campaign Intelligence** panel treated as a living record —
  a warm document that fills in as understanding accrues, provenance pills reading
  like margin annotations. The hero is watching intelligence compound.
- **Campaign Brief (client-facing).** The **threshold cover** — a cream page that
  opens attended-to, wordmark and client name arriving in a soft stagger, "scroll ↓"
  drifting. It should feel like being handed a bound proposal, not loading a webpage.
- **Delivery package.** The **ceremony surface** — ink/metal header, wine accents,
  the certified-rights seal. Occasion. This is where the work is *delivered* and it
  should feel like a signing.
- **Simulator.** A focused, low-light "booth" — attention on one exchange, the coach
  panels arriving like margin notes after a take.

---

## 12. Micro-interactions — earned delight

Delight is small, warm, and rewards real actions — never decorative.

- **The live dot.** A slow ember breath (2s) on anything genuinely live — a real-
  time signal, a call in progress, a send firing. Presence, felt.
- **Press.** Every button gives a `.15s` weighted press (scale ~.98 + shadow
  compress) — the feel of a real key. Tactility is the premium.
- **Confirm.** A decision (qualify, assign, approve, release) resolves with a brief
  ember pulse + a settled checkmark — the machine acknowledging the human's call.
  Ceremony proportional to consequence.
- **Provenance pills.** Where a value came from is a tiny tracked "credit line" that
  flips with a `.25s` react ease when it changes — the record staying honest.
- **Copy / send.** Label morphs ("Copy" → "Copied ✓") and settles; never a toast for
  a trivial act.
- **Hover.** A warm 1px edge brightens and the card lifts a hair — light responding
  to attention, nothing more.

**The rule:** if a delight doesn't correspond to a real state change, cut it.
Delight is a *reward*, not decoration.

---

## 13. Scroll choreography

Scroll is directed like a film edit — the page reveals itself as a sequence, at the
reader's pace.

- **Arrival on scroll.** Sections rise + fade once (`translateY(12px)` → settle,
  `.4s` move ease) as they cross into view, then stay. Staggered children for lists.
  Content *arrives*; it doesn't pop.
- **The threshold.** Long client documents (the Brief) open with a full-height cover;
  the first scroll is **consent** — the reader chooses to begin. Never dump the whole
  doc at once.
- **Spatial scroll (the Reel).** Scroll drives *travel through space* along the
  helix, not a scrollbar — one lerped parameter, momentum, decay. The rare place
  scroll becomes the instrument.
- **Anchored calm.** Everywhere else, scroll is quiet and honest — no hijacking, no
  scroll-jacking parallax olympics. Position is preserved across form posts (a long
  doc never jumps to the top). Respect the reader's place.
- **One choreographed moment per page, maximum.** The rest is just clean, calm
  reading.

---

## 14. Empty states — the studio at rest

Empty is an opportunity, not an error. Each empty state is **warm, composed, and
directive** — a quiet room waiting, with one clear next move.

- **Voice.** Honest and human ("Nothing waiting — you're all caught up," "No touches
  logged yet"), never cute error-speak, never a shrug.
- **Form.** A single hairline illustration (the relevant motif — an empty console, a
  blank staff, a quiet signal path), generous space, and **one** ember primary
  action. Calm, not busy.
- **Never:** a sad mascot, a big gray "no data" void, or three competing CTAs. An
  empty state is the studio between sessions — orderly and ready.

---

## 15. Loading experiences — anticipation, not waiting

Loading is where cheap tools reveal themselves. STUDIO LIGHT never shows a spinner.

- **Skeletons in warm paper.** Content-shaped placeholders in `panel`/sand with a
  slow warm shimmer sweeping left→right — the layout is promised before it arrives.
- **The hairline progress.** A 2px ember progress line for known-duration work
  (analyzing intel, generating a brief) — eased, honest, never a fake crawl.
- **The considered pause.** For real work ("✨ Analyzing…"), a brief labeled beat
  that says *the machine is thinking*, then a settled result. The delay is framed as
  care, not lag.
- **Optimistic + honest.** Reflect the action instantly where safe; where we truly
  can't know (transcription deferred, no provider), **say so plainly** — never a
  spinner that implies work that isn't happening.
- **Never:** a centered spinning circle, a full-screen blocking overlay, or a
  progress bar that lies.

---

## 16. Premium visual effects that stay performant

The craft ceiling — every effect earns its cost or it's cut.

- **Warm edge-light + two-layer shadow** — the core elevation tell. Cheap (static
  box-shadow), enormous payoff. This alone does 80% of the premium work.
- **Backdrop blur — rationed.** Glass only on transient Z3 overlays, one at a time.
  Blur is expensive; it's a privilege of temporary floating surfaces, never a
  standing decoration.
- **GPU-only motion.** Animate `transform` and `opacity` only — never `width`,
  `top`, `background`, or box-shadow in a loop (composite the shadow onto a pseudo-
  element and fade *that*). 60fps is a requirement, not a hope.
- **Static grain over animated particles.** A fixed grain texture reads as premium
  and costs nothing; animated background systems cost battery and rarely add.
- **Bloom via opacity, not filters.** The live glow is a low-opacity radial that
  breathes on opacity — not an expensive real-time blur/`filter`.
- **Reduced-motion & low-power dignity.** Everything degrades to a clean, still,
  intentional state. The identity survives with zero motion — the light, materials,
  type, and palette carry it alone.

**The performance creed:** *If it can't hold 60fps warm on a mid-tier laptop, it
isn't premium — it's a demo. Cut it.*

---

## The whole thing in one breath

Chordential looks like a **boutique mastering studio rendered as software**: warm
paper, honest materials, one ember of heat, editorial type, light that has a
temperature, motion with real mass, and effects so restrained they read as
expensive. Apple's restraint, Linear's precision, Stripe's clarity, Framer's craft,
Arc's wit — all of it filtered through a single conviction:

**The machine proposes with precision. The human disposes with taste. And every
surface should look like taste made it.**

*Warm. Precise. Made.*
