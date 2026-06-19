# Funnel Recall Audit + Gmail MCP Plan

**Context:** Jon reports the funnel is *starving* (too few qualified opps). The
council recommended a recall play (Gmail MCP), preceded by a near-free audit of
whether the existing gate is strangling supply. This document is both halves:
the audit findings (with fixes) and the Gmail MCP implementation plan.

---

## Part 1 — Recall audit: where opps die today

### Finding 0 — Qualification *routes*, it does not *delete*
`qualification.py` never discards an opportunity. Stage 0 hard-disqualifiers
aside (cover bands, karaoke, lessons — correctly killed), everything else is
**routed**: `PURSUE` (alignment ≥ 70 **and** HIGH confidence), else `REVIEW`
(≥ 50 or needs-review), else `WATCH`. All three are stored. So the database
isn't the leak — **the loud surface is.**

### Finding 1 — The PURSUE gate rarely fires, so the radar *feels* empty
`_route()` requires **HIGH confidence** for PURSUE, and `_confidence()` needs
**≥ 3 explicit signals** among {music requirement explicit, buyer type known,
budget disclosed, commercial/sonic flag}. A typical raw gig post discloses one or
two. Result: most genuine opps land at MEDIUM → **REVIEW**, which doesn't push an
alert. The funnel isn't empty — the *alerting tier* is starved by design
("precision-biased routing").
**Lever (tuning, not a bug):** add a quieter "worth-a-look" surface for REVIEW-
grade items, or relax PURSUE to `alignment ≥ 70 AND confidence ≥ MEDIUM`. Reclaims
volume Jon never sees today. Zero new data.

### Finding 2 — `is_music_gig()` drops *paid* gigs that signal pay with money, not keywords ⚠ highest-impact
`signals.py` strict filter (`is_music_gig`, used for F5Bot/keyword alerts — likely
a primary cheap source) requires `intent() == "demand"`, and `intent()` only
returns "demand" when a word from `_DEMAND_MARKERS` is present ("needed",
"hiring", "seeking", "budget"…). A real post like **"Composer for mobile game —
$500/track, DM me"** has the role marker but **no demand keyword**, so
`intent()` → "unknown" → **dropped**, despite obviously being paid.
**Fix (near-zero risk):** treat the presence of a **money/price pattern**
(`$`, "per track", "/track", "paying", "rate", "USD", "k budget") as a demand
signal inside `intent()`. Recovers paid gigs phrased in dollars, not verbs.

### Finding 3 — `_COLLAB_MARKERS` is over-broad and kills legit paid work ⚠ medium-impact
The collab/hobby exclusion includes `"partner"`, `"royalty"`, `"be a part of"`.
A legit brief — *"Seeking a composer to partner with our agency on a paid
campaign"* — contains "partner" → **dropped**. Likewise "royalty" false-matches
"royalty-free" commercial asks.
**Fix:** tighten to phrases that are unambiguously hobby/unpaid
(`"rev share"`, `"revshare"`, `"unpaid"`, `"no pay"`, `"no budget"`,
`"passion project"`, `"for fun"`), and drop the bare `"partner"`/`"royalty"`
tokens (or require them to co-occur with an unpaid marker).

### Audit verdict
The gate **is** contributing to "starving" — but mostly by **dropping paid gigs
on keyword technicalities (Findings 2-3)** and **hiding REVIEW-grade volume
(Finding 1)**. Findings 2 and 3 are *zero-LLM, same-day* recall wins. They also
make the case for Gmail MCP: an LLM *reading* the email would never drop a $500
gig for lacking the word "hiring." The filters are a brittle proxy for
comprehension — which is exactly what an agent supplies.

---

## Part 2 — Gmail MCP implementation plan

**Goal:** recover the long tail the keyword filters drop, and let *many*
saved-searches forward to one inbox **without writing a parser per source**.

### The one architectural decision
This introduces the **first LLM dependency** into a deterministic codebase.

- **Option A — autonomous triage (recommended).** A scheduled in-app agent reads
  unread mail via the Gmail MCP server, uses Claude to judge & extract, and
  writes opportunities into the review queue. Always-on; right for a starving
  funnel. Cost is controlled (below).
- **Option B — interactive only.** MCP server alone; a human drives triage from
  Claude Desktop/Code. No server-side LLM cost, but not always-on. Weaker fit for
  "starving."

Recommend **A**, built so the LLM piece is lazy/optional (like `pywebpush`), so
CI/sandbox stay LLM-free and deterministic.

### Components
1. **Gmail MCP server** (`src/chordential_oia/mcp/gmail_server.py`)
   - Tools: `list_unread(label?)`, `get_message(id)`, `search_messages(query)`,
     `mark_processed(id)` (apply a "Chordential/Processed" label).
   - Auth: Gmail API via OAuth refresh token in secrets (`GMAIL_CLIENT_ID/SECRET`,
     `GMAIL_REFRESH_TOKEN`); read scope + label-modify.
2. **Triage agent loop** (`src/chordential_oia/web/triage.py` + scheduler hook)
   - On interval: pull unread candidates → coarse pre-filter → for each, Claude
     decides *is-this-an-opp?* and extracts {client, need, budget, location,
     contact} → `db.insert_opportunity(...)` in a **gated REVIEW state**.
   - Idempotent: dedupe on Gmail message-id + `external_ref`.
3. **Gated write path (reuse what exists)**
   - Land agent-created opps as `needs_review`, status `New` — **never
     auto-pursue** (preserves "machine proposes, Jon disposes"). Surfaces in the
     existing `/leads` or signals review queue.
4. **Cost controls (CFO's concern)**
   - Pre-filter to an "Alerts" Gmail label (only forwarded saved-searches), so
     personal mail is never sent to the model.
   - Two-stage: a cheap model (Haiku) for the binary opp/not-opp gate; escalate
     to extraction only on "yes." Per-run cap.
5. **Feedback loop (ties into existing moat)**
   - Jon's accept/reject in review feeds `qualification.record_label()` — the
     JSONL training moat already in the codebase — so triage accuracy compounds.
6. **Config & safety**
   - `ANTHROPIC_API_KEY`, `GMAIL_*`, `CHORDENTIAL_TRIAGE_ENABLED` (default off),
     interval, label names. Lazy imports; best-effort; never blocks the app.
7. **Tests**
   - Mock Gmail + mock LLM: extraction → gated opp in review; idempotency on
     re-run; **never-auto-pursue invariant**; pre-filter excludes non-Alerts mail.

### Phasing (each independently shippable)
- **B0 — same-day, zero-LLM:** ship Findings 2-3 filter fixes. Immediate recall,
  no dependencies. *(This is the cheapest win on the board.)*
- **B1:** Gmail OAuth + MCP read tools + a manual `POST /triage/run` (no
  autonomy). Verify extraction quality against the real inbox.
- **B2:** wire the scheduler for autonomous interval triage with cost caps.
- **B3:** feedback loop into `record_label`; tune.

### Dependencies & risks
- First LLM + first Google-OAuth dependency. Keep both lazy/optional.
- Per-email cost — bounded by label pre-filter + cheap binary gate.
- Gmail refresh-token setup is a one-time operator step (documented at B1).

---

## Recommendation
Ship **B0 (the filter fixes) immediately** — it's same-day recall with no new
dependencies and directly addresses "starving." Then build **B1** to prove Gmail
MCP extraction quality before turning on autonomy. The filters are a keyword proxy
for comprehension; Gmail MCP replaces the proxy with the real thing.
