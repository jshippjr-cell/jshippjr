# The Scoring Stage — ChordOS Studio Experience Design

*The complete experience design for the composer workspace. Commissioned 2026-07-18.
Designed from zero. Supersedes the presentation layer of every existing portal screen;
inherits only the server truths (token doors, publish gate, versions, rights, rounds).
Implementation begins only after this document — see §14.*

---

## 1. UX Philosophy

**The interface is the room, not the software.**

When a composer is awarded a project, something real happened: a studio chose them.
The workspace's one job is to make that feel true the second they arrive — and then
get out of the way of the writing.

Seven products were studied for *why* they feel premium — not to copy, but to extract
the underlying law each one proves:

| Studied | The law it proves |
|---|---|
| **Frame.io** | Media is the interface. Darkness is service, not styling — the picture is the brightest thing in the room. |
| **Figma** | One canvas, infinitely capable. Tools appear at the point of intent and vanish after. Nobody "navigates" Figma. |
| **Notion** | The content *is* the chrome. Structure reveals itself on hover; at rest, only the work is visible. |
| **Apple** | Progressive disclosure. Every screen answers exactly one question; depth exists but is never shown until asked for. |
| **Linear** | Speed is an emotion. Sub-100ms response reads as *respect*. Keyboard-first isn't a power feature — it's how flow survives. |
| **Raycast** | Summon, don't park. One key conjures anything; zero pixels are spent on things you aren't using. |
| **Milanote** | Creative material wants to be *gathered*, spatially, loosely — moodboards beat lists for feeding the creative brain. |

From these, ChordOS's five laws:

1. **The picture is the hero. Always.** Every pixel not serving the picture or the
   music must justify itself or die.
2. **Zero navigation.** One engagement = one room = one URL. There is nothing to
   navigate *to*. Panels are summoned into the room and dismissed from it.
3. **Everything anchors to time.** Notes, cues, hits, approvals, versions — all live
   on the timeline under the picture. If it has no timecode, it lives in the Brief.
   There is no third place.
4. **Calm is a feature.** No badges, no red dots, no engagement mechanics. The room
   tells the composer exactly one thing at a time: *what the music needs next.*
5. **The room is always dressed before the composer arrives.** Brief in, picture in,
   cues marked, notes pinned. The composer never assembles their own workspace —
   walking in *is* the onboarding.

**The emotional target, in order:** cinematic → calm → focused. Luxury here is not
ornament; it is *absence* — of clutter, of hunting, of doubt about what's next.

---

## 2. Information Architecture

There is **one screen**. Everything else is a summoned layer over it.

```
THE STAGE  (permanent — the room itself)
├─ The Picture            (video, edge-to-edge, always present)
├─ The Spine              (timeline under the picture: cues · hits · notes · music)
└─ The Doorline           (one quiet strip: project name, deadline, round, status)

SUMMONED LAYERS  (over the stage, one at a time, dismissed with Esc)
├─ Brief        (B)       the creative direction — serif, editorial, beautiful
├─ Moodboard    (M)       references gathered spatially — Milanote lesson
├─ Notes        (N)       every timecoded note as a thread (also inline via pins)
├─ Versions     (V)       the take ladder: v1 → v2 → FINAL, with per-take notes
├─ Delivery     (D)       what's owed: cue list, stems, specs, due dates, approvals
└─ Command bar  (⌘K)      jump to any cue / note / version / action — Raycast lesson

STATES  (the room reconfigures; the composer never "goes" anywhere)
├─ ARRIVAL      first entry after award — the dressed room, once-only sequence
├─ WRITING      default: picture + spine + nothing else
├─ REVIEWING    notes emphasized: pins expanded, thread docked right
└─ DELIVERING   upload + checklist emphasized after "final" is near
```

**What was questioned and removed:** persistent sidebars (both), the dashboard
concept, project lists (a composer with three engagements gets three doors, not a
portfolio manager), settings screens, notification centers, breadcrumbs, any page
that is *about* the work rather than *being* the work. Deliverables/deadline data
lives in the Delivery layer and the Doorline — not in a fourth surface.

---

## 3. User Journey

**Act 0 — The award (email → door).**
One email: *"You're scoring AURORA 'First Light.' The room is ready."* One link. No
account creation, no password (token door — exists today). The link opens directly
into Act 1.

**Act 1 — Arrival (once per engagement).**
The room fades up from black like house lights: picture first (poster frame),
then the spine draws itself left-to-right (cues appear, hits land with a soft tick,
note pins settle), then the doorline. A single line of serif text over the picture:
*"Everything is ready. This room is waiting for your music."* One button: **Begin.**
Total: ~4 seconds, skippable with any key, never shown again. This sequence is the
product's promise made physical: *chosen, prepared, respected.*

**Act 2 — Understanding (first session).**
The composer plays the picture. Space bar. They click a cue → playhead jumps, the
Brief's relevant direction line appears as a caption-level whisper under the picture
(not a panel — a sentence). They press B once, read the full brief in editorial
serif over a dimmed stage, press Esc. They press M, absorb the moodboard, Esc.
Total interface learned: *space, click, B, M, Esc.* Nothing else is needed to start
writing.

**Act 3 — Writing (most of the engagement).**
The room in WRITING state: picture + spine. The composer works in their DAW; the
room is the reference monitor beside it. They drag a bounce onto the stage —
anywhere — and it lands as **v1** in the music lane, waveform drawn, pending the
studio's publish gate (exists). The room's one status line updates: *"v1 with the
studio."* No modal. No form. The drop zone is the entire room.

**Act 4 — The conversation (rounds).**
Client notes arrive pinned to the timeline (wine pins). The room shifts to
REVIEWING only when the composer opens it after new notes: pins expanded, thread
docked. Each note: click → picture seeks → the note's exact moment plays. "Mark
addressed" per note (exists as resolve). When the studio consolidates a round
(round ledger — exists), the room says plainly: *"Round 2 brief is locked: 3 notes,
2 cues affected."*

**Act 5 — Delivery.**
As FINAL approaches, the D layer carries the whole procurement weight: per-cue
checklist (master, stems, cutdowns), file specs stated once, drag-anywhere upload,
approval state per cue. When the last item lands: the room's only celebration —
the spine glows once, and the line reads *"Delivered. The studio takes it from
here."* The composer's payment status is visible here and nowhere else.

**Act 6 — Archive.**
The room stays alive read-only: the work, the approvals, the credits. A composer's
past rooms are their private track record (feeds matching — exists).

---

## 4. Screen Hierarchy

One screen; hierarchy is *z-depth and light*, not pages.

```
Z0  THE PICTURE      brightest object, largest object, always visible
Z1  THE SPINE        directly beneath, full width; the only permanent UI
Z2  THE DOORLINE     one 40px strip, top; project · deadline · round · status
Z3  WHISPERS         transient captions under the picture (cue direction,
                     status changes) — appear, breathe, fade
Z4  SUMMONED LAYERS  Brief/Mood/Notes/Versions/Delivery — dim the stage to 30%,
                     never fully cover the picture's position
Z5  COMMAND BAR      ⌘K — floats center, above everything
```

Visual weight budget: picture ~55% of viewport height, spine ~18%, air ~27%.
The "27% air" is non-negotiable — spaciousness is where calm lives.

---

## 5. Component System

Twelve components. If a thirteenth appears, one of these twelve was built wrong.

1. **Picture** — video surface; SMPTE timecode (mono, top-right, on-hover);
   shot-safe letterboxing; click = play/pause; J/K/L transport.
2. **Spine** — the four-lane timeline: cue lane (regions + hit diamonds), note lane
   (pins + range spans), music lane (waveform of current take), scrub lane
   (playhead track). One shared playhead across all lanes and the picture.
3. **Cue region** — labeled span (`m01 · Held breath · 0:00–0:14`) with state
   (open → take → published → approved) encoded as border weight, not color noise.
4. **Hit diamond** — a moment the music must honor; hover reveals its name;
   click seeks; the picture flashes its subject at that frame.
5. **Note pin / span** — wine (client), slate (studio), orange (composer);
   resolved = 30% opacity. Click: seek + open card inline above the spine.
6. **Whisper** — one line of text that appears under the picture and fades;
   the room's only voice. Never stacks, never persists.
7. **Layer sheet** — the summoned surface (Brief/Mood/etc.): slides up 40% height,
   stage dims behind; Esc or click-out dismisses; only one lives at a time.
8. **Take chip** — `v2` pills above the spine; A/B by clicking; the waveform and
   note-set swap; the picture never reloads.
9. **Drop veil** — drag-anything-anywhere; the whole room lowers its lights and
   draws one dashed rectangle: *"Drop your take · WAV/AIFF · lands with the studio
   first."* Progress is real bytes.
10. **Checklist row** — Delivery layer: deliverable · spec (mono) · state.
11. **Command bar** — fuzzy jump: cues, notes, versions, actions ("upload",
    "mark m02 addressed", "play from the hit").
12. **The doorline** — identity strip: wordmark, project, deadline (relative:
    "due in 11 days"), round chip, one status word.

---

## 6. Motion Language

Motion is *state made visible* — never decoration (Living-OS law, kept).

- **Physics**: one easing family — `cubic-bezier(.19,1,.22,1)` (existing
  `--ease-out`), 180–240ms for UI, 400ms for layer sheets. Exits at 0.6× entrance.
- **The Arrival sequence** (once): 4s orchestration — black → picture fade (1.2s) →
  spine draws left-to-right (1.4s, cues then hits then pins, 60ms stagger) →
  doorline settles → whisper. Skippable; never repeats; `prefers-reduced-motion`
  collapses it to a simple fade.
- **The playhead** is the room's heartbeat: glides during playback, snaps on seek
  with a 120ms settle. The waveform's played region warms (orange fill advancing).
- **Pins materialize** with a single soft ring (existing `Live.halo`) only when a
  *new* note arrives during the session — motion means *something changed*.
- **Layer sheets** rise from the spine (they belong to the timeline's world),
  never fall from the top.
- **Nothing loops. Nothing pulses idly.** One exception: the empty music lane's
  "waiting for your music" ember — a 2.2s breath — because that absence *is* the
  room's active state.

---

## 7. Typography System

Three voices, strictly cast (extends the existing brand system):

- **The narrative voice — serif display** (Iowan Old Style / Palatino stack, the
  brand's existing voice): the Brief layer, the Arrival line, whispers. This is the
  only place the room "speaks prose." 17–28px, generous leading (1.55).
- **The interface voice — system sans** (existing stack): labels, chips, buttons,
  note bodies. 11–13.5px. Weights 500/600/700 only. Uppercase labels get +0.14em
  letter-spacing and 9.5–10px sizes.
- **The instrument voice — monospace** (ui-monospace stack): timecode, cue IDs,
  durations, filenames, specs. `font-variant-numeric: tabular-nums` everywhere
  digits align. This voice is the honesty rule made visible: data reads as
  instrumentation, never marketing.

Scale: 9.5 / 10.5 / 11.5 / 12.5 / 13.5 / 15 / 17 / 21 / 28. Nothing between.
Running text max-width 65ch (Brief layer).

---

## 8. Spacing System

- Base unit **4px**; component rhythm on **8/12/16/24/40/64**.
- The room breathes at the edges: stage margin 20px minimum, 40px at ≥1440w.
- Spine lanes: 34px each, music lane 52px — thin enough to stay subordinate to the
  picture, tall enough for a fingertip (44px touch targets achieved via invisible
  expanded hit areas, not visual bulk).
- Layer sheets: 40vh height, content inset 40px, one column, 65ch.
- Density rule: **no surface ever shows more than seven interactive elements at
  rest.** (The stage at rest shows five: play, three lane groups, doorline.)

---

## 9. Color System

The control-room palette (one palette with the brand, dark mood — ratified
direction from `platform-website-plan.md` Part 2):

| Token | Value | Role |
|---|---|---|
| `--ink` | `#191817` | the room (never pure black) |
| `--panel` | `#211F1D` / `#282523` | spine, sheets (+4/+8% light) |
| `--hair` | `sand @ 16%` | every border; 1px only |
| `--text` | `cream @ 92%` | primary |
| `--dim` | `warm gray 62% / 40%` | secondary / tertiary |
| `--orange #F0772C` | action + the composer's own color | the ONLY call-to-action hue |
| `--wine #9A3A4A` | the client's presence (notes, approvals) |
| `--slate #8BA0AE` | the studio's presence |
| gold `#C8A86A` | demo/prototype labeling only (honesty rule) |

Laws: semantic state (approved/blocked) borrows no accent hues — approved is a
check + border weight, blocked is plain language. The picture is the only saturated
object in the room; UI chroma stays low so the work owns the color. Contrast floor:
4.5:1 body, 3:1 dim text. Single-theme dark **by design** — this room is the edit
bay; daylight remains the front-of-house mood (two moods, one palette).

---

## 10. Interaction Principles

1. **Space bar plays. Everywhere. Always.** Even with a layer open.
2. **Click any time-anchored thing → the playhead goes there.** No exceptions.
   Deep links carry `?t=` and `?cue=` — an email can open the room at a moment.
3. **Drag anything anywhere.** The room routes it (audio → take, image/pdf → the
   moodboard shelf, video → picture inbox for the studio).
4. **Esc always returns to WRITING.** One key, guaranteed exit, zero-state anxiety.
5. **Keyboard-first, invisible until touched**: B/M/N/V/D summon layers; ⌘K
   commands; ←/→ nudge; J/K/L shuttle. Every summon has a click path too.
6. **One decision at a time.** The room never presents parallel calls to action;
   the doorline's status word states the single next thing.
7. **Progressive disclosure**: hover reveals (timecode, hit names, pin previews);
   rest state stays clean.
8. **Undo over confirm.** Nothing in the composer's flow needs a confirmation
   modal; destructive-adjacent actions (delete a take) offer 8s undo whispers.
   The publish gate (studio-side) protects the client; the composer stays fluid.
9. **Latency budget**: seek < 50ms; layer summon < 200ms; drop-to-waveform
   < 4s with honest progress. Speed = respect (Linear's law).
10. **The machine proposes, the human disposes** — kept absolutely: nothing
    auto-publishes, auto-approves, or auto-sends. The room prepares; people decide.

---

## 11. Desktop Experience (≥1200px — the primary stage)

The full room as specified: picture 55vh, spine full-width beneath, doorline top,
layers as 40vh sheets, command bar. The composer's realistic posture: **second
monitor beside the DAW** — so the room must be legible at a glance from an angle:
big playhead, high-contrast pins, whispers readable at 2 meters. A dedicated
**mini mode** (⌘M): picture + spine collapse to a 380px strip — the room as a
reference instrument while the DAW owns the main display.

## 12. Tablet Experience (768–1199px)

The same room, touch grammar: lanes grow to 44px; pins get tap-halos; layers
become full-height sheets with swipe-down dismiss; transport gains visible
buttons (no keyboard assumption). Primary use: **the couch listen** — playing
the picture with notes, away from the desk. Upload exists but is secondary.
Nothing is removed; density adapts, capability doesn't.

## 13. Mobile Companion (<768px)

Not the stage — **the companion**. Three things only, done perfectly:

1. **Listen** — picture + audio of the current take, full-width, with the note
   pins as a vertical list beneath (tap → seek).
2. **Capture** — a voice-memo/idea inbox: hum a motif at 2am, it lands in the
   room's private composer shelf, timestamped (never visible to the client).
3. **Know** — the doorline as a card: deadline, round, status, and the one next
   thing.

No uploads of deliverables, no brief editing, no delivery checklist on a phone.
The companion respects what a phone is for.

## 14. Implementation Roadmap

*Each phase ships green and deployable; experience-first order (feel before
plumbing wherever possible). Server truths reused throughout: token doors,
publish gate, version ladder, timecoded comments + resolve, rounds/conform
ledger, rights/delivery engines.*

**Phase 1 — The Room, audio-first (feelable immediately; no new infra).**
Rebuild the composer door as the Stage: dark room, spine with note pins from the
existing timecoded comments, take chips from the existing version ladder, Brief
layer from the existing stage-partial, whispers, Esc/space/B/N/V grammar,
drop-anywhere upload (audio; existing storage). The picture position holds a
poster/artwork frame until Phase 2. *This alone replaces today's portal feel.*

**Phase 2 — The Picture (the hero arrives; forces the storage debt).**
S3/R2 object storage (the deferred seam — this is what finally pays for it),
client-side picture upload via the client door's Drop, streaming playback,
poster generation, `?t=` deep links. The client door gets the same room shell
with its permissions.

**Phase 3 — The Cue Layer (the differentiator; speaks scoring natively).**
Cue model (additive tables: cues, hits, in/out per Campaign-Workspace PRD),
cue regions + hit diamonds on the spine, per-cue approval mapped to the existing
per-deliverable approval, conform surfacing ("picture changed under m02" —
round ledger exists), Delivery layer checklist per cue.

**Phase 4 — Flow polish (the premium feel compounds).**
Arrival sequence, command bar, A/B take scrubbing, mini mode, precomputed
waveform peaks at upload, tablet grammar, mobile companion, range (span) notes.

**Phase gate discipline:** after Phase 1 ships, the composer-facing prototype is
validated with one real composer walkthrough before Phase 2 begins (dogfood-first,
Constitution §4.2). Every phase honors: publish gate, no AI-generated audio,
honest empty states, fail-soft degradation to the audio-and-notes room.

---

*Design complete. Implementation may begin at Phase 1 upon founder approval.*
