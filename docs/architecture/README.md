# ChordOS — Architecture (the canonical source of truth)

This directory is the **permanent architectural source of truth** for ChordOS. It is
deliberately small and curated. Everything here is meant to be *current and
authoritative* — unlike the rest of `docs/`, which is a chronological archive of
deliberations, plans, and reviews.

> **New here — human or AI? Read `CONSTITUTION.md` first.** It teaches you what
> ChordOS is and why, before you make a single decision.

## The canonical set (read in this order)

1. **[`CONSTITUTION.md`](./CONSTITUTION.md)** — *what ChordOS is, why it exists, and
   the enduring principles.* The tiebreaker for any ambiguous decision. Changes
   rarely. **Read before making architectural, product, or design decisions.**
2. **[`ARCHITECTURE_DECISIONS.md`](./ARCHITECTURE_DECISIONS.md)** — *why the code is
   shaped the way it is.* The numbered log of binding technical decisions and their
   rationale. Read before changing a load-bearing pattern; append a new ADR before
   reversing one.
3. **[`PROJECT_STATE.md`](./PROJECT_STATE.md)** — *you are here.* What exists, what's
   in flight, what's deferred. Read to orient; update when the state materially
   changes.

## How this relates to the rest of the repo

| File | Scope | Changes | Read it for |
|---|---|---|---|
| `CONSTITUTION.md` | The **why** and enduring principles | Rarely (amendments only) | Decisions, direction, tiebreaks |
| `ARCHITECTURE_DECISIONS.md` | Binding **technical** decisions | On new/reversed decisions | Why a pattern exists |
| `PROJECT_STATE.md` | Current **state** | Often | What's built / deferred now |
| `/CLAUDE.md` | Tactical **how** (commands, conventions, branch, env) | As tooling changes | Getting work done today |
| `docs/*.md` | Deliberation **archive** (councils, plans, specs, reviews) | Append-only history | The record of how we got here |

**The layering, stated plainly:** the Constitution holds the reasons (change almost
never) → the ADRs hold the decisions (change rarely) → PROJECT_STATE holds the state
(changes often) → CLAUDE.md holds the tactics (changes with tooling) → `docs/` holds
the history (append-only). When two layers seem to conflict, the higher, slower layer
wins, and the lower one is corrected.

## For every future session

Before doing substantive work in this repository:

1. `/CLAUDE.md` is auto-loaded and points you here. **Read `CONSTITUTION.md`** to
   inherit the reasoning.
2. Skim `PROJECT_STATE.md` so you know what already exists and what's deferred.
3. Consult `ARCHITECTURE_DECISIONS.md` if you're about to change a core pattern.
4. Then follow `/CLAUDE.md` for how to build, test, and commit.

Keep these documents honest and current. They are the memory that lets a five-year
team — and every AI session in between — work as if they had been here the whole time.
