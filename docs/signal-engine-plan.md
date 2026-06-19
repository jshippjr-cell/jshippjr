# Signal Engine — Opportunity Detection Layer (Plan)

**Convened:** 2026-06-19 · **Chair:** Jon Shipp (CEO) · **Mandate:** digest the
"information latency is the moat" thesis and produce a build plan.

> **Thesis (ratified):** Chordential is a trading desk. The winning system has the
> **lowest information latency**, not the best dashboard. The moat becomes: *we
> find relevant opportunities 6–24 hours before everyone else.* Detection becomes
> its own product layer.

---

## Architecture shift

Old: **Find → Parse → Score**
New: **Detect → Capture → Parse → Score → Pursue**

"Detect" gets its own layer: a **`signals`** table that sits *before* leads/
opportunities — the trading-desk tape. A signal is promoted into an Opportunity
through the same human gate leads use today.

### The `signals` model
| field | meaning |
|---|---|
| source, source_weight | where it came from + its priority (table below) |
| external_ref | dedupe key (URL / post id / email msg-id) |
| title, body, url | the raw posting |
| **posted_at** | when the opportunity went live (the clock that matters) |
| **found_at** | when *we* learned of it |
| **age** | found_at − posted_at → our latency, measured per source |
| score | opportunity score (reuse `qualification`) |
| status | New / Reviewed / Promoted / Dismissed |

### The ranking that matters
The Radar sorts by **freshness × score**, not score alone:

```
rank = opportunity_score × exp(−age_hours / τ)      (τ ≈ 12h)
```

A fresh B-tier outranks a day-old A-tier — because you can still be the first
email in the inbox. Latency per source is tracked so we know which feeds are slow.

## Ingest adapters (pluggable — one `signals` table, many feeders)
- **email-in** — instant saved-search alerts (Mandy/ProductionHUB/Hitmarker) + F5Bot/Google Alerts, forwarded to an intake address → parsed by the existing `intake.py`. *The backbone.*
- **RSS poll** — scheduler polls configured feeds every ~5 min (no email delay).
- **paste** — forward an alert to yourself, paste it → parsed now (zero infra).
- **API / bot** *(later)* — anything with an open API; a Discord watcher.
- **launchpad** — today's manual-assist capture becomes one signal source.

Reuse: `intake.py` (parse, multi-job, budget/buyer inference) + `qualification`
(score). Detection is new; parsing/scoring already exist.

## Source weighting (config-driven)
ProductionHUB 10 · Mandy 10 · Agency Intelligence 10 · Hitmarker 9 · Staff Me Up
8 · LinkedIn 7 · The Dots 7 · Behance 6 · Upwork 5 · SoundBetter 4.

## Honest buildability (latency × value × effort)
| Tier | Channel | Latency | Build | Reality |
|---|---|---|---|---|
| 1 | Mandy / ProductionHUB / Hitmarker **instant email** | <5 min | email-in + their saved searches | Highest value; needs a mail service |
| 2 | **RSS** feeds | <5 min | scheduler poller | Best in-app automation *if a feed is public & not bot-blocked* |
| 6 | **F5Bot / Google Alerts** | <10 min | email-in | Free; same pipe as Tier 1 |
| 3 | **Agency wins / new productions** (the predictive moat) | <1 day | scrape/feeds + heuristics | High effort, highest edge — "music spend incoming" before the brief |
| 4/5 | **LinkedIn / Discord** | <10 min | bots / paid data | Real but heavy; ToS/auth friction — last |

## Phased build
- **Phase 1 — Foundation + fastest wins (build first):** `signals` model; the
  **Signal Radar** page ranked by freshness × score; **RSS poller** in the
  scheduler for configured feeds; **paste-an-alert** intake (uses `intake.py`);
  an **email-in webhook** endpoint ready for a mail service. Latency stamping.
- **Phase 2 — Instant email backbone:** stand up inbound email (Mailgun/SendGrid)
  → webhook → signals. Jon sets Mandy/ProductionHUB/Hitmarker/F5Bot to *instant*
  alerts forwarded in.
- **Phase 3 — Leading indicators (the moat):** agency new-business + new-production
  signals → "music spend incoming" before the brief exists.
- **Phase 4 — Harder channels:** LinkedIn signal detection, Discord watchers.

## Recommendation
Build **Phase 1** now — it establishes the Detection layer, ships the freshness ×
score Radar, and turns `intake.py` into a live tool via paste + RSS + an email-in
endpoint. Jon wires the external feeds (saved searches → instant, F5Bot, RSS URLs)
in parallel; Phase 2 makes it hands-free.
