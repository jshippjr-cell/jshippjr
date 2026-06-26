# Efficiency Report — How We're Working, and How to Get More

*A retrospective on the Chordential engagement: ~10 days, 184 AI-co-authored commits.
The question: is the setup maximizing what Claude can output for you? Honest answer —
**the working *patterns* are strong; the *setup* is leaving real time on the table.**
Three changes would meaningfully raise throughput.*

---

## 1. The record (grounding)

| Measure | Value |
|---|---|
| Span | 2026-06-17 → 2026-06-26 (~10 days) |
| Commits (AI co-authored) | **184** |
| App code | ~18,100 lines |
| Test code | ~8,700 lines · **515 tests** · 43 files |
| Decision / plan / review / manual docs | **34** |
| Tests at start → now | ~330 → **515** (suite stayed green throughout) |

The arc of directions: Postgres-capability + zero-downtime cutover → dashboard/back-
office consolidation → editable client document → first-touch composer + tailored page
→ tactful intake + outreach → talent recruiting + per-talent rates → strategy health
check (the pivot) → the full **Delivery OS** (5 agents, 12+ passes) → adversarial agency
reviews → manual + this report. A lot shipped, and `main`/the branch never broke.

---

## 2. What's working (keep doing)

These patterns are *why* the output was high and reliable:

- **Decompose → spec → background agent → test-gate → commit → push, repeated.** Each
  feature became a tightly-scoped agent task with a written spec, gated on the test
  suite, committed atomically. This is the engine behind 184 clean commits.
- **Decision docs before building.** The council/deliberation pattern surfaced the real
  forks (the A→B→C strategy, the clearance wedge, the delivery-OS scope) and got crisp
  founder rulings *before* code — avoiding expensive rework.
- **Commit-per-pass + push.** Atomic, reviewable, revertible history; every reversal
  (e.g. the hero loop) was a one-line flip because nothing was entangled.
- **Adversarial review loop.** The "Dana" agency-buyer reviews caught real defects
  (open-approve risk, hollow demo ZIP) that internal tests never would — a genuine
  quality multiplier.
- **Honest scoping.** Deferring what couldn't be done well (DocuSign, durable storage,
  outbound email) instead of faking it kept trust and avoided dead-end code.

---

## 3. Where efficiency leaks (the fixable gaps)

Grounded in the repo state, in priority order of time recovered:

### A. No parallel test runner — the single biggest *time* sink ⏱️
The full suite is **515 tests, ~3 minutes**, and it was run **after almost every one of
the ~30+ passes** (correctly — to stay green). `pytest-xdist` is **not installed**, so
every run is single-core. That's well over **an hour of cumulative wall-clock** spent
waiting on serial test runs.
- **Fix:** install `pytest-xdist`, run `pytest -n auto` (4–8× faster → ~30–45s), and
  adopt **two tiers**: a fast *targeted* subset between passes, the full suite only at
  phase boundaries. Likely the largest raw-minutes win available.

### B. No `CLAUDE.md` — repeated re-learning of the codebase 🧭
There is **no `CLAUDE.md`**. Every exploration agent re-discovered the same facts: the
architecture, the test command, the "machine proposes, Jon disposes" rule, the
deterministic-engine pattern, the branch to develop on, the `CHORDENTIAL_SEED_DEMO`
flag, the deploy setup. That re-discovery cost tokens and time *every session*, and its
absence caused real misses (an early agent committed to a stray branch; the manual's
"back-office"/demo-data confusion).
- **Fix:** a `CLAUDE.md` at the repo root capturing architecture, the test/run commands,
  conventions, the governing rules, branch discipline, env flags, and deploy notes →
  every future agent starts informed and consistent. **Highest *consistency* win.**

### C. No `.claude/settings.json` — the permission-prompt friction 🔐
There is **no `.claude/` config**, so file writes and test/git commands hit the default
permission flow — which is exactly the "Allow once… and it keeps asking" frustration you
hit when a background agent was writing a template repeatedly.
- **Fix:** a project `settings.json` allowlist for `Edit`/`Write` in the repo and for
  `python -m pytest` / `git`, or default to accept-edits. Then agents (background or not)
  run smoothly without pestering you. **Highest *your-time* win.**

### D. Serial agent execution (smaller, structural)
Agents ran **one at a time** because they shared core files (`app.py`, `db.py`,
templates). Much of the work *was* genuinely sequential/dependent, so this was often
correct — but where work is independent, **worktree-isolated parallel agents** (or the
Workflow tool's fan-out) would run concurrently. Net: structure features as separate
modules where possible so parallelism is available.

### E. Ceremony not always matched to stakes
34 docs is a lot. The full council deliberations earned their keep on real forks; some
smaller decisions could have been a quick `AskUserQuestion` instead of a written
deliberation, and purely-mechanical work needs no doc at all. **Calibrate the ceremony
to the weight of the decision.**

---

## 4. Recommendations, prioritized by leverage

| # | Change | Effort | Payoff |
|---|---|---|---|
| 1 | **Add `CLAUDE.md`** (architecture, commands, rules, branch, env flags, deploy) | 10 min | Every future session faster + consistent; fewer agent misses |
| 2 | **Add `.claude/settings.json`** permission allowlist (or accept-edits) | 5 min | No more per-file prompts; smooth background agents |
| 3 | **Install `pytest-xdist`** + two-tier testing (smoke between, full at boundaries) | 5 min | ~4–8× faster gates; biggest raw-minutes win |
| 4 | **Calibrate ceremony** — council for forks, `AskUserQuestion` for quick calls, no doc for mechanical work | ongoing | Less overhead per decision |
| 5 | **Structure for parallelism** — independent modules / worktrees so agents can fan out | ongoing | Wall-clock on independent work |
| 6 | **Reuse the adversarial-review loop deliberately** (it found the best bugs) | ongoing | Quality per unit effort |

**The top 3 are the whole game** — they're cheap, one-time, and compound on every future
session.

---

## 5. The honest bottom line

You are **already getting high output** — the patterns (spec'd agents, test-gating,
atomic commits, decision-first, adversarial review) are close to best-practice for
agent-driven development, and the volume proves it. The gap isn't *how* the work is
done; it's that the **project isn't yet *configured* to let Claude run at full speed**:
no memory file, no permission allowlist, no parallel tests. Fix those three and the same
working style ships meaningfully faster, with fewer interruptions to you.
