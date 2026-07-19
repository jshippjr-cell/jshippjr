# Master Review — The Scoring Stage (the composer Session Room)

*Executive-panel review of the completed four-phase build. Conducted 2026-07-19 by
four independent lenses on Sonnet — CTO (technical soundness), CPO (product), CXO
(experience/craft), CEO/founder (commercial/strategic) — each exercising the live
demo and the code. This synthesis is deliberately unflinching; the panel's job is to
find what the phase gates couldn't.*

## The build under review

Four phases, each gate-passed by the standing 4-agent panel (Engineering / Design /
Composer / Executive Producer) before the next began:

1. **The Room** — the audio-and-notes stage: one shared playhead, timecoded client
   notes, summoned Brief / Notes / Takes layers.
2. **The Picture** — the client's cut becomes the stage; video master clock; a new
   cut is a *conform* (free), not a revision; drop-to-upload.
3. **The Cue Layer** — named/timed cues + hit diamonds on the spine; per-cue
   human-pressed approval; conform anchored to the cue that changed.
4. **Flow polish** — arrival house-lights, ⌘K command bar, mini mode, range notes,
   private Capture shelf, mobile companion, tablet grammar.

1,119 tests green. ADRs 0024–0027 on record.

## The four verdicts

| Lens | Verdict | The one thing they'd change |
|---|---|---|
| **CTO** | ship-with-caveats | A gate-exemption regex broke three composer routes in prod — *found and fixed this review.* |
| **CPO** | ship-with-caveats | No hard stop when contracted revision rounds run out. |
| **CXO** | ship-with-caveats | A mojibake em-dash reached the client portal (demo-seed artifact). |
| **CEO** | **not-ready** | *Strategic, not technical:* stop polishing the room — go sell. |

## What the panel agreed is genuinely good

- **The craft ceiling is high.** The arrival sequence and the ⌘K command bar were
  named by three of four lenses as the standout — "Raycast-grade," "could not exist
  in any competitor's generic project portal." Mini mode is a real differentiator
  (a reference instrument beside the DAW).
- **One truthful data spine, three honest views.** The composer room, operator
  console, and client portal share one state — round chips, notes, cues render
  consistently across all three. Not three products stitched together.
- **The Constitution is enforced in code, not convention.** "Machine proposes, Jon
  disposes" is structural: `set_cue_state` has one call site, admin-gated; the
  publish gate is a genuine human step; no fake capabilities; demo uses invented
  brands. The blob-pattern discipline, additive migrations, token-gate regime, and
  stored-XSS/private-shelf/internal-reply boundaries all held up under adversarial
  code review.

## What the panel found — and the disposition

### Fixed this review
- **P0 (CTO) — the admin gate broke three composer routes in production.**
  `_CREATOR_PORTAL_RE` only exempted `version`/`deliverable`, so with
  `CHORDENTIAL_ADMIN_TOKEN` set (as it is in prod) the composer's mark-addressed,
  AJAX reply, and Capture all 303'd to `/admin/login` on their own token-gated page.
  **Fixed**: regex extended to cover `capture` + `note/*/{reply,address}`, plus a
  drift-guard test asserting every registered `/creator/*` POST is exempt. This is
  the same bug class CLAUDE.md documents (the `_REVIEW_ACTIONS` drift) — it had
  recurred on the composer side and survived all four phase gates because no test
  exercised the gate-on × composer-route intersection.
- **Demo mojibake (CPO/CXO).** A double-encoded em-dash in a seeded note reached the
  client portal — a `curl -d` seeding artifact, not an app bug (the write path
  stores UTF-8 cleanly, verified). Demo data corrected.

### Accepted as roadmap (not built now — see the CEO note)
- **Round-exhaustion hard stop / conform-spam throttle (CPO, CTO, EP).** The round
  ledger displays but never *gates* — a client can run unlimited "revisions" with no
  signal that they're off-contract. Named in Phase 2's carryover, it silently
  dropped from the Phase 3/4 notes. This is a genuine **commercial guardrail** and
  belongs on the roadmap explicitly (restored to the deferred list below).
- **`_mutate_cues` is cue-only (CTO).** The lost-update race ADR-0027 closed for cues
  is still open for the other `delivery_json` sub-keys (`add_capture`, reviewer
  add/remove, asset approval) and the lock is **SQLite-only** — it no-ops on the
  planned Postgres cutover. Generalize the primitive + make it Postgres-safe before
  cutover day.
- **Mobile Companion is a squeezed desktop, not the §13 three-screen build.**
  Honestly deferred already; the panel confirms it under-serves "the couch listen."
- **Demo uses SMPTE color bars, not footage (CPO/CXO).** Undercuts "the picture is
  the hero" in the one room built to prove it. A demo-data fix — swap in one
  rights-clear cut before any external walkthrough.
- **Density + debounce (CXO).** The WRITING-state transport cluster exceeds the
  spec's own seven-element rest law; the ⌘K/⌘M toggles self-cancel on a double-press.
  Both small, both real.

## The CEO dissent — the most important finding

The CEO lens declined to grade the software and instead graded the *decision to build
it*: `docs/company-architecture.md` — the founder's own commissioned strategy audit —
was committed the same day this build began and states plainly that the company has
**$0 revenue, zero pipeline**, that the P0 is "sell, no build," and that "more
delivery polish" is *explicitly deferred*. The four-phase Session Room is, by that
document's own words, the deferred work — built by the exact "build-reflex" pattern
the audit named as the company's #5 risk. Meanwhile outbound email and the Proposal
Desk's deposit last-mile — the actual blockers between a lead and cash — remain
unbuilt.

The panel does not resolve this tension; it surfaces it. The software is real and
good. Whether it was the right thing to build *now* is a founder's call, and the
honest record is that one of four executive lenses believes it was not.

## Panel disposition

**Technical/product/experience: ship-with-caveats** — the build is sound, the one
production-blocking bug is fixed, and the remaining caveats are a known, documented
roadmap (chiefly the round-exhaustion gate and the Postgres-safe/generalized blob
lock). **Strategic: contested** — proceed to real client acquisition and the
Proposal Desk deposit path before further Session Room investment; do not resume this
track until there is a paying engagement to dogfood it against.

## Restored to PROJECT_STATE's deferred list (so they aren't lost a third time)
- Round-exhaustion hard stop + conform-spam throttle (a commercial guardrail).
- Generalize `_mutate_cues` to all `delivery_json` sub-keys + make it Postgres-safe.
- Purpose-built §13 mobile Companion (Listen / Capture / Know).
- Real demo footage; transport density; ⌘K/⌘M debounce.
