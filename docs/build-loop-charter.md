# Chordential — Hourly Build-Council Charter

*Established 2026-06-16 from Jon's onboarding interview. Each hourly cycle reads
this file for its operating parameters.*

## Mandate (from the CEO interview)

| Dimension | Decision |
|---|---|
| **North star** | **Expand the vision** — build toward the procurement OS (estimation, prepare/proposals, outreach, buyer graph). |
| **Autonomy** | **Approve-then-build** — the council presents the agreed plan/requirements for Jon's OK *before* the engineer builds. (Reconciled with the repo's stop-hook policy, which requires every commit to be pushed: pausing *after* a build would leave uncommitted work the hook rejects, so the pause moves to the plan stage. Once approved, the engineer builds → QA → commit → push.) |
| **Scope** | **Intelligence engine** — sources, qualification, estimation, the data moat. |
| **QA bar** | **Tests + screenshot + acceptance** — full suite green, a rendered screenshot of any affected screen, and a written check against the cycle's agreed requirements. |

## The council
CEO (Jon) · COO · CTO · CMO · Creative Director → agree the next build →
hand requirements to the Engineer → Engineer builds → QA agent verifies →
**pause for Jon's approval** → publish on OK.

## Per-cycle process
0. **Name the roadmap stage** — every cycle states which stage of
   `docs/product-roadmap.md` it advances. A build that maps to no stage is out of
   scope (or the roadmap is updated first). The roadmap is the decision anchor;
   the CMO gate (`cmo-charter.md`) and a named roadmap stage are checked together.
1. **Council dialogue** (short) — agree the single highest-value next build within scope.
2. **Requirements + plan** — written acceptance criteria.
3. **Pause for approval** — present the plan to Jon. **Wait for his OK before building.**
4. **Build** — implement on branch `claude/admiring-mayer-u241h5`.
5. **QA** — run `pytest`; render a screenshot of any affected screen; check each acceptance criterion.
6. **Publish** — commit + push (satisfies the stop-hook policy).
7. **Log** — append the cycle outcome below.

## Cycle log

### Cycle 1 — 2026-06-16 ~14:25 UTC — Promote Estimation to a first-class engine
- **Build:** new `src/chordential_oia/estimation.py` (Phase-1 expert engine + `EstimationEngine`), added an uncalibrated **confidence band** (±35%) to every estimate, collapsed `web/estimate.py` into a thin shim, exported from the package, surfaced the band on the dashboard estimate page.
- **Acceptance:** engine returns point + band; team derived from discipline; web delegates to engine (no duplicate logic); existing numbers unchanged; all tests green.
- **Status:** ✅ published (commit `781076e`).

### Cycle 2 — 2026-06-16 ~15:05 UTC — The Prepare layer (Pursuit Brief)
- **Build:** new `src/chordential_oia/prepare.py` — deterministic `PursuitBrief` generator (the fifth mission verb) assembling qualification + estimate + strategic value into a ready brief with a suggested response outline; new dashboard "Pursuit brief" tab + plain-text/copy export; exported from the package.
- **Acceptance:** brief assembles from existing engines (no LLM); `render_text()` copy-paste output; new tab + `.txt` route render; full suite green.
- **QA:** 79 tests pass; brief + brief.txt routes 200; screenshot verified; 3/3 acceptance.
- **Status:** ✅ published.

### Cycle 3 — 2026-06-16 — Product Roadmap + the Outreach-to-Win layer
- **Roadmap stage:** Demand side → **Outreach-to-win** (the sixth mission verb). Also establishes `docs/product-roadmap.md` as the exec decision anchor.
- **Build:** (A) new `docs/product-roadmap.md` — the two-track (demand/supply) roadmap with status per stage and the talent-matching decision (profile + credits + Jon-reviewed demo reel, no audio AI); governance rule added (every cycle names a roadmap stage). (B) new `src/chordential_oia/outreach.py` — deterministic `OutreachPlan` (recommended contact, urgency, buyer-tuned cadence, first-touch message); persistence for contact + next-action/due + an outreach event log with a non-destructive DB migration; new "Outreach" tab + `.txt` export; dashboard "Follow-ups due" queue.
- **Acceptance:** plan assembles from existing engines (no LLM); contact + next action persist; events log and stamp last-contacted; follow-ups surface on the dashboard; old databases migrate without data loss; full suite green.
- **QA:** 91 tests pass; outreach + outreach.txt routes 200; screenshots of the Outreach tab and the dashboard follow-up queue verified; migration test green.
- **Status:** ✅ published.

### Cycle 4 — 2026-06-16 — Buyer Graph (buyer relationship intelligence)
- **Roadmap stage:** Demand side → **Buyer Graph** (the moat asset; built on the Outreach layer's contacts + touch log).
- **Council:** CMO + Creative Director + COO argued the relationship — not the single pursuit — is the moat and must be browsable with a next-best-action; CTO scoped it to deterministic aggregation over existing data (no new infra/LLM); CEO approved.
- **Build:** new `web/buyer_intel.py` — deterministic `BuyerRelationship` (stage Cold/Warming/Engaged/Client, 0-100 score, signals, next-best-action); `db.py` aggregations (`all_buyers`, `buyer_touch_summary`, `buyer_contacts`); new `/buyers` directory ranked by relationship then strategic value + "Buyer Graph" nav; buyer profile relationship panel + known-contacts list.
- **Acceptance:** deterministic engine with correct stage rules; directory + profile render and rank; relationship reflects outreach + wins; built only from existing data; full suite green.
- **QA (independent QA agent):** 101 tests pass; engine stage/boundary/determinism checks pass; `/buyers` + buyer profile 200 with expected content; end-to-end (contact → touch → Won ⇒ "Client") verified; clean working tree. 5/5 acceptance, no defects. Screenshots of the directory + profile verified.
- **Status:** ✅ published.

### Cycle 5 — 2026-06-16 — Talent Roster (supply-side foundation)
- **Roadmap stage:** Supply side → **Recruit talent** (the first supply-side stage; everything downstream needs a person model).
- **Council:** CEO reaffirmed match-on-profile-and-credits + a Jon-reviewed demo reel (no audio AI); Creative Director owns the reel gate; CMO defined the Prospect→Invited→Joined funnel; CTO reused `MusicDiscipline` for talent skills and kept it to a new table + migration, reel as a link (no file-hosting infra).
- **Build:** new `talent.py` (Talent model, ReviewStatus/InviteStatus, profile_completeness, matchable rule); `db.py` talent table + CRUD (migration-safe); `seed.py` starter roster; `/talent` roster + filters, add/edit, demo-reel review action, invite funnel; new Supply nav section.
- **Acceptance:** matchable = approved reel + ≥1 discipline; roster/detail render; review + invite persist; seeded roster present; migration-safe; full suite green.
- **QA (independent QA agent):** 112 tests pass; domain rules (matchable cases, completeness) verified; `/talent` + `/talent/new` 200 with seeded creator; review gate end-to-end (Pending⇒not matchable, Approve⇒Matchable) verified; migration idempotent; clean tree. 5/5 acceptance, no defects. Screenshots verified.
- **Status:** ✅ published.
