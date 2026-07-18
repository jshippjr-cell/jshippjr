# The Session Room — Design Brief

*Portal overhaul brief, 2026-07-18. The place where client, studio, and composer meet
around the work. Companion to `docs/platform-website-plan.md` (Element 9/10) and the
Campaign Workspace PRD; supersedes the current creator portal's presentation (not its
server mechanics, which are sound). Inspiration research: Frame.io (review room,
frame-anchored threads), Notetracks Pro (range comments on waveform), DISCO (delivery
elegance), Copilot/Assembly (portal-as-product polish), and the spotting-session
workflow (cues, hit points, SMPTE timecode) that none of them speak.*

---

## 1. The one-sentence vision

**A dark, cinematic room where the client's picture, the brief, and every note live on
one timeline — and the composer walks in to find the work already waiting for their
talent.**

Not a form. Not a document. A *room*: the picture playing, the cues marked, the notes
pinned to moments, the brief one glance away, the upload slot open.

## 2. Why (the honest gap)

Today's portals are procurement-grade *documents* — light, single-column, list-based
(`creator_portal.html`: 239 lines, audio-only; `delivery_portal.html`: custom audio
player + timecoded comment threads). Server mechanics are genuinely good: token-gated
access, timecoded feedback with resolve/reply, version ladder, publish gate, payment
gate. But:

- **No video, anywhere.** The client cannot upload picture; the composer scores blind
  or receives video off-system (email/WeTransfer) — the exact handoff ChordOS exists
  to kill.
- **Notes are a list, not a timeline.** Timecoded feedback renders as text rows; the
  composer maps "0:38" to the picture in their head.
- **No cue vocabulary.** The system speaks "versions and comments," not "cues, hit
  points, in/out, free timing" — the native language of scoring to picture.
- **It reads as paperwork, not craft.** The client's first feeling should be "this is
  a serious studio"; the composer's should be "everything I need is already here."

## 3. The three doors into one room

One Session Room per engagement (per cue, eventually — Campaign Workspace PRD's
campaign→cues elevation), three token-gated views of the same state. Same room,
different permissions — never three separate products.

| Door | Who | They can | They cannot |
|---|---|---|---|
| **Client door** (`?k=`/`?r=` tokens, existing) | agency producer / CD | upload picture + reference assets, play versions, pin notes to timecode/regions, approve | see unpublished takes, see composer identity pre-kickoff if withheld, touch cues/structure |
| **Composer door** (portal token, existing) | assigned talent | see picture + brief + all published notes as a timeline, download assets, upload takes (→ publish gate), mark notes addressed | publish to client, see commercial terms |
| **Studio door** (admin, existing console) | Jon | everything: publish gate, cue markup, note triage, release | — (machine proposes; this door holds every disposition) |

## 4. The room, screen by screen

### 4.1 The Stage (center, dominant)
- **Video player** as the room's centerpiece: the client's picture, dark chrome,
  SMPTE-style timecode readout (monospace), keyboard transport (space, J/K/L, arrows).
- **The strip beneath the picture is the room's spine — three stacked lanes:**
  1. **Cue lane** — cue regions (`m01`, `m02`…) as labeled spans; **hit points** as
     diamond markers the music must land on. Studio-editable; client-visible;
     composer-navigable (click a hit → playhead jumps).
  2. **Note lane** — every note as a pin (point) or span (range, Notetracks-style).
     Color by author-side (client = wine, studio = slate, composer = orange). Click →
     the note card opens; the playhead moves. Resolved notes dim.
  3. **Waveform lane** — appears when a take is loaded; the composer's current version
     under the picture, so *music-against-picture is the default view, not a feature.*
- **A/B version scrub**: version chips (v1 · v2 · v3-FINAL) above the stage; switching
  swaps the waveform + note set, picture stays. (Version ladder exists server-side.)

### 4.2 The Brief rail (left, collapsible)
- The Campaign Brief, folded in (stage-partial pattern exists) — direction, references,
  tone words, instrumentation notes, deadline, rounds state ("Round 2 of 3" chip).
- **Cue sheet view**: each cue with in/out, duration, hit list, status
  (sketch → take → published → approved). The composer's to-do list *is* the cue list.
- Assets drawer: every client upload (picture cuts, boards, VO, temp refs) with
  version-safe names; "new cut" uploads mark prior picture superseded → triggers the
  **conform** flow (`production-lifecycle-model.md`: a new cut is never a revision).

### 4.3 The Notes rail (right)
- The same notes as the note lane, as a scrollable thread — filter by cue / author /
  open-resolved. Reply + resolve (exists). Range notes show their span.
- **Consolidation state** (the round ledger's law): notes land as *individual*; the
  studio marks a set **consolidated** → that starts a round. The rail shows which
  world you're in ("collecting notes" vs "Round 2 brief locked").

### 4.4 The Drop (client first-run)
- Before any picture exists, the client door opens on one beautiful action: a
  full-stage dropzone — "Drop the cut here" (+ boards, VO, references). Uploading
  builds the room around the asset. Progress is honest (real bytes); formats stated
  plainly.

### 4.5 The Waiting Room (composer first-run — Jon's line, literally)
- The composer's first entry shows the room *already dressed*: picture loaded, cues
  marked, notes pinned, brief in the rail, an empty waveform lane labeled
  **"Waiting for your music."** One primary action: Upload your first take.
- This moment is the product's promise to the supply side made visible: chosen, not
  bidding; everything prepared; respected.

## 5. Interaction grammar (the rules of the room)

1. **Everything anchors to time.** A note, a hit, a cue, an approval — all address
   moments or spans. If it has no timecode, it belongs in the brief, not the room.
2. **Point vs. span.** Click the lane = point note; drag = range note. Both render in
   lane + rail identically.
3. **The playhead is shared state.** Clicking anything time-anchored moves it; deep
   links carry `?t=` (and `?cue=`) so an email can open the room at the moment.
4. **Publish gate is sacred** (exists — keep): composer uploads are invisible to the
   client until the studio publishes. The room shows the composer their take's state
   honestly (pending review → published → in revision).
5. **Approval is per-cue and whole-spot** (per-deliverable approval exists), by
   verified reviewer identity (`?r=`, exists); approving stamps the version + snapshot.
6. **Conform ≠ revision** — new picture triggers conform labeling on affected cues,
   surfaced in lane ("picture changed under m02"), never counted against rounds.
7. **Motion is state** (Living-OS law): playhead glide, a note pin materializing
   (`Live.halo`), upload progress — nothing decorative; reduced-motion collapses all.

## 6. Design language

- **Control-room dark** (platform-website-plan Part 2): ink `#191817` surfaces, cream
  92% text, sand hairlines at ~16% opacity, orange as the *only* action color, wine =
  client-side accents, slate = studio-side. Never pure black.
- **Monospace for anything technical**: timecode, cue IDs, filenames, durations —
  instrumentation, not marketing (the honesty rule, typographically).
- Serif display voice for the brief's narrative only (the one warm surface).
- The client door and composer door share the dark theme — this room is deliberately
  the "edit bay," distinct from the daylight front-of-house. (The workspace/brief
  documents stay daylight; the *room* is dark. Two moods, one palette — Constitution §7.)

## 7. What exists vs. what's built new

| Capability | State | Notes |
|---|---|---|
| Token doors (client `?k`/`?r`, composer portal, admin) | ✅ exists | keep exactly |
| Timecoded comments + reply/resolve + attribution | ✅ exists | re-render as lanes/pins |
| Version ladder + publish gate + payment-gated release | ✅ exists | keep; new chrome |
| Round ledger / conform / creative lock (ADR-0019) | ✅ exists (data) | surface in room |
| Campaign Brief inline (stage partial) | ✅ exists | becomes left rail |
| **Video upload + storage + playback** | ❌ new | biggest new build; needs the S3/R2 seam (deferred infra debt — this is what finally forces it) |
| **Cue model (regions, hits, in/out)** | ❌ new | per Campaign Workspace PRD §cues; additive tables |
| **Lane timeline UI (cue/note/waveform strips)** | ❌ new | the centerpiece build |
| **Range (span) notes** | ❌ new | extends existing comment schema additively |
| **Client asset dropzone flow** | ❌ new | upload exists for audio; generalize + video |
| Waveform rendering | ◑ partial | custom bar player exists; upgrade path: precomputed peaks (wavesurfer-style), stored at upload |

## 8. Constitutional constraints (non-negotiable)

- Machine proposes, Jon disposes: publish, rounds, conform determinations, release —
  all studio-door buttons. Nothing auto-publishes.
- No AI-generated audio, ever; the room organizes and presents human craft.
- Honesty: demo rooms use invented brands (AURORA); progress bars reflect real bytes;
  empty states say what's actually missing ("No picture yet — waiting on the client's
  cut"), never fake life.
- Fail-soft: a missing video, a huge file, a dead seam — the room degrades to the
  audio-and-notes view that works today; never a broken stage.

## 9. Phasing (each ships green)

1. **P0 — The prototype** (this pass): a clickable visual prototype of the composer
   door (the Waiting Room + dressed Session Room) on demo data — validate the feel
   before any build.
2. **P1 — The room, audio-first**: rebuild composer + client doors in the room layout
   with today's capabilities (audio versions, timecoded notes as lanes, brief rail) —
   no new storage needed. Ships value immediately.
3. **P2 — Picture**: video upload (forces S3/R2), player stage, notes-on-picture,
   client Drop flow.
4. **P3 — The cue layer**: cue regions, hit points, per-cue approval, conform surfacing.
5. **P4 — Polish**: A/B scrub, deep links, keyboard transport, precomputed waveforms.

## 10. Success criteria

- A client can go from "here's our cut" to pinned, timecoded, consolidated notes
  without an email.
- A composer's first login contains *everything* needed to write: picture, cues,
  hits, brief, references — zero archaeology. Their words, not ours: "I just started
  writing."
- The room is the studio's best sales demo — the thing a producer shows their CD.
