# Chordential — Product Roadmap

*The single source of truth for what we build and in what order. Ratified by Jon
Shipp (CEO), 2026-06-16. Every executive decision and every build cycle cites the
roadmap stage it advances — see "How the exec team uses this roadmap" below.*

This roadmap reconciles with, and does not replace, the ratified strategy in
`company-strategy.md` (the A→B→C sequence, the mission spine, capital discipline)
and the CMO gate in `cmo-charter.md`. Where they disagree, the strategy docs win
and this roadmap is corrected.

---

## North star

Become **the intelligence layer between creative buyers and music creators** —
long term, the operating system for commercial music procurement. The durable
assets are the **proprietary qualification + estimation models** and the
**buyer↔creator relationship graph** (`company-strategy.md`). The roadmap is a
two-sided pipeline: **win the business** (demand side), then **deliver it with the
right people** (supply side).

Status legend: ✅ Done · 🔨 Building now · ⏭️ Next · 🗓️ Later

---

## Track 1 — Demand side (win the business)

The mission spine: *Identify → Rank → Qualify → Estimate → Prepare → Outreach →
Win/Loss.* This is the engine that finds the right work and wins it.

| Stage | What it does | Status | Implementation |
|---|---|---|---|
| **Identify** | Ingest opportunities (alerts, RSS, manual paste, email parse) | ✅ | `intake.py`, `sources/` |
| **Rank** | Weighted score + A/B/C/Watch tiers | ✅ | `scoring.py` |
| **Qualify** | Is this real, Chordential-shaped music craft? Fit %, discipline, gaps | ✅ | `qualification.py` |
| **Strategic value** | CMO lens — small-budget door-openers beat big one-offs | ✅ | `strategic.py` |
| **Estimate** | Team, hours, cost, price, margin (Phase-1 expert priors + band) | ✅ | `estimation.py` |
| **Prepare** | Deterministic pursuit brief + suggested response outline | ✅ | `prepare.py` |
| **Outreach-to-win** | Recommended contact, urgency, touch cadence, first-touch message, contact + next-action tracking, outreach log, follow-up queue | 🔨 | `outreach.py`, `web/` |
| **Win/Loss capture** | Pipeline status + outcome value; feeds the data moat | ✅ | `web/db.py` |
| **Buyer graph** | Buyer profiles, history, relationship value (the moat asset) | ⏭️ | `web/` buyer pages (partial) |

**Building now (this cycle): Outreach-to-win.** After Prepare produces a brief,
Outreach turns it into action — *who* to contact, *how urgently*, a *sequenced
cadence*, a *ready first-touch message*, and a place to log every touch and the
single next action with a due date. A dashboard "Follow-ups due" queue surfaces
what the pipeline is waiting on. It drafts and tracks outreach; it does **not**
send mail (yet). Every logged outcome feeds the win/loss moat.

---

## Track 2 — Supply side (deliver it with the right people)

Once we win work, we staff it. This entire track is **Later** — it begins only
after the demand side is trusted and we are winning enough work to staff. It is
the bridge toward Model C (the marketplace) in `company-strategy.md`, and must be
held to the same test: *does it accumulate proprietary intelligence or
relationships?*

| Stage | What it does | Status | Notes |
|---|---|---|---|
| **Identify required labor** | From a won/qualified project, derive the roles needed (composer, mixer, sound designer, …) | 🗓️ | The estimator already produces `team_shape` — reuse it |
| **Recruit talent** | Pipeline of skilled creators to invite into the network | ✅ | Cycle 5 — roster, profile/credits, reel-review gate, funnel |
| **Talent match** | Match creators to a project on **profile + credits**, plus a **demo-reel upload area Jon personally reviews** | 🔨 | **Decision (2026-06-16): profile + credits matching, NOT audio AI.** A demo-reel upload area is monitored/reviewed by Jon (human-in-the-loop). Audio analysis is explicitly out of scope for v1. |
| **Invite to the app** | Bring matched talent into Chordential as users | 🗓️ | First multi-user surface |
| **Assign to project** | Attach creators to a won project with roles | 🗓️ | **Jon is the decision-maker (see decision rights below).** The app does all qualification + skill matching and surfaces full buyer-side and talent-side detail; Jon pushes the button to confirm each assignment. |
| **Track progress** | Per-project task/milestone status | 🗓️ | Also feeds Phase-3 estimation actuals (`company-strategy.md`) |
| **Broadcast progress** | Push status to everyone assigned to the project | 🗓️ | Keeps the whole team in sync |

**Talent-matching decision, recorded in full:** matching is on **profile and
credits only**. Creators get an area to **upload a demo reel, which Jon monitors
and reviews** — a deliberate human-in-the-loop quality gate, consistent with the
Head of Production's role as the quality gate (`company-strategy.md`). We are not
building audio/AI analysis of reels in v1.

**Decision rights — Jon has the last say on assignment (CEO directive,
2026-06-16):** the app's job is to do *all* the work up to the decision —
qualification, skill/credits matching, ranking, and surfacing **as much detailed
information as possible on both sides** (buyer/project need, budget, deadline,
required roles; and talent disciplines, credits, reel-review status, availability,
fit score). It presents a recommended match, but **Jon always confirms the
assignment with an explicit action ("push the button").** The system never
auto-assigns talent to a project. This applies to the **Assign** stage
(Cycles 7/8) and mirrors the demo-reel review gate: machine does the analysis,
human makes the call.

---

## Sequencing rationale

1. **Demand before supply.** Win the business first; staffing a pipeline we can't
   fill is premature. The supply side only earns its cost once we are winning work.
2. **Outreach before the rest of the buyer graph.** Outreach is the missing link
   between a prepared brief and a logged win — it is what converts analysis into
   revenue, and it generates the contact/touch data the buyer graph will need.
3. **A→B→C still holds.** The demand side is Model A (dogfooding Chordential's own
   studio = data manufacturing). The supply side and multi-user surfaces are the
   on-ramp to Model C. We do not jump to C before the moat exists.

---

## How the exec team uses this roadmap (governance)

This roadmap is the **decision anchor**. To keep the council consistently pointed
at it:

1. **Every build cycle names the roadmap stage it advances** in its requirements
   and in the cycle log (`build-loop-charter.md`). A build that maps to no stage
   is either out of scope or a sign the roadmap needs updating first.
2. **Every feature passes two gates together** before entering the build queue:
   the CMO gate (*who / what pain / will they pay / how solved today* —
   `cmo-charter.md`) **and** a named roadmap stage. Both, not either.
3. **The roadmap is versioned here.** Re-sequencing is a CEO decision, recorded by
   updating this file (not in scattered notes), so there is one current picture.

---

## Changelog

- **2026-06-16** — Roadmap established. Demand side built through Prepare;
  **Outreach-to-win** is the current build. Supply side defined and sequenced as
  Later, with the talent-matching approach fixed to **profile + credits + a
  Jon-reviewed demo-reel upload** (no audio AI in v1).
