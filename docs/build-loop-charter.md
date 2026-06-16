# Chordential — Hourly Build-Council Charter

*Established 2026-06-16 from Jon's onboarding interview. Each hourly cycle reads
this file for its operating parameters.*

## Mandate (from the CEO interview)

| Dimension | Decision |
|---|---|
| **North star** | **Expand the vision** — build toward the procurement OS (estimation, prepare/proposals, outreach, buyer graph). |
| **Autonomy** | **Build, pause before publish** — do the work each cycle, run QA, then present the diff + QA report and **wait for Jon's OK before pushing.** |
| **Scope** | **Intelligence engine** — sources, qualification, estimation, the data moat. |
| **QA bar** | **Tests + screenshot + acceptance** — full suite green, a rendered screenshot of any affected screen, and a written check against the cycle's agreed requirements. |

## The council
CEO (Jon) · COO · CTO · CMO · Creative Director → agree the next build →
hand requirements to the Engineer → Engineer builds → QA agent verifies →
**pause for Jon's approval** → publish on OK.

## Per-cycle process
1. **Council dialogue** (short) — agree the single highest-value next build within scope.
2. **Requirements** — written acceptance criteria handed to the engineer.
3. **Build** — implement on branch `claude/admiring-mayer-u241h5`.
4. **QA** — run `pytest`; render a screenshot of any affected screen; check each acceptance criterion.
5. **Pause** — present diff + QA report. **Do not push.** Await Jon's "publish".
6. **Log** — append the cycle outcome below.

## Cycle log

### Cycle 1 — 2026-06-16 ~14:25 UTC — Promote Estimation to a first-class engine
- **Build:** new `src/chordential_oia/estimation.py` (Phase-1 expert engine + `EstimationEngine`), added an uncalibrated **confidence band** (±35%) to every estimate, collapsed `web/estimate.py` into a thin shim, exported from the package, surfaced the band on the dashboard estimate page.
- **Acceptance:** engine returns point + band; team derived from discipline; web delegates to engine (no duplicate logic); existing numbers unchanged; all tests green.
- **Status:** built + QA'd; **awaiting Jon's approval to publish.**
