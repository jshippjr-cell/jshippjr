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
