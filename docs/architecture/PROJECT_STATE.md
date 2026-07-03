# ChordOS — Project State

*The "you are here." A living snapshot of what exists, what's in flight, and what's
deferred — so a new session orients in one read without spelunking. Update this when
the state materially changes; keep it short and current. For the enduring **why**,
read `CONSTITUTION.md`; for **binding decisions**, `ARCHITECTURE_DECISIONS.md`; for
**commands/conventions**, `/CLAUDE.md`.*

**Last updated:** 2026-07-02 · **Phase:** A (studio force-multiplier, dogfood-first)

---

## What ChordOS is today

A single-operator, internally-used operating system running the Chordential music
studio end to end — demand side (find/qualify/estimate/prepare/outreach/win) and
supply side (recruit/match/assign/produce/review/deliver). Deployed on Render;
FastAPI + Jinja + SQLite; ~915 tests, must stay green before commit.

## The three-OS model (the architectural pivot)

ChordOS is resolving into three stacked systems:
- **Intelligence OS** — ✅ built. Discover, understand, qualify, reason, CRM,
  opportunity, proposal.
- **Workflow OS** — 🔨 partial. Projects, tasks, production, delivery, status,
  approvals, QA, rights.
- **Creative OS** — 🔨 building; **increment 1 shipped and flag ON in prod**. The
  **Campaign Workspace** — one screen, one campaign, everything (brief, direction,
  team, timeline, references, cues, versions, stems, reviews, approvals, rights,
  delivery). This is the layer that makes ChordOS impossible to copy. **Fully
  specified in `docs/campaign-workspace-prd.md`.** Increment 1 (the campaign
  container + structured creative direction + creative-timeline phases) is live
  behind `CHORDENTIAL_CAMPAIGN_WORKSPACE=1` (dogfooding). Governing law: every
  feature must make ChordOS feel more like the OS for campaign music, never like
  generic project management.

## The three mechanisms — current maturity

| Mechanism | State | Notes |
|---|---|---|
| **Intelligence** | ✅ engines built; presentation partial | Agency discovery, enrichment (micro-agents), decision-makers, company intelligence, signal detection, opportunity scoring all exist. The control-room UI in `platform-website-plan.md` is planned, not built. |
| **Relationship** | ✅ built | Buyer graph, relationship stages, outreach drafting **+ real branded sending / copy / open-in-mail**, follow-up continuity, institutional memory. `/relationships` batched to O(1) queries. |
| **Delivery** | ✅ built (flagship) | Delivery OS (Rights/Revisions/Metadata/Approvals/Assets), token-gated review portal with **timecoded feedback + audio-playhead persistence**, creator portal with **client feedback shown + publish gate**, clearance-certified delivery package (browser + ZIP, single-source legal copy), payment gate. |

## Mission spine — implementation map

Demand: `intake.py` · `scoring.py` · `qualification.py` · `strategic.py` ·
`estimation.py` · `prepare.py` · `outreach.py` · win/loss in `web/db.py` ·
`web/buyer_intel.py`.
Supply: `talent.py` · `matching.py` · projects/assignments + `delivery.py` +
`web/decision_makers.py` · `web/enrichment.py` · `web/intelligence.py` ·
`web/opportunity_signals.py` · `web/music_opportunity.py`.
Web/OS surface: `web/app.py` (routes) · `web/public.py` (front-of-house) ·
`web/scheduler.py` (background engines) · `web/db.py` (storage, backend-portable).

## Recently completed (this working stretch)

- **Product efficiency audit** (`docs/product-efficiency-audit.md`): 43 verified
  findings, ranked P0–P3.
- **P0:** admin-gate/portal-route drift fixed; event-loop-blocking sends offloaded;
  first-touch dead-end + favicon fixed.
- **P1:** SQL queue selection (was O(table×batch)); live status polling (replaced
  blind reload); review-portal audio playhead persistence.
- **P2:** composer feedback loop (client notes on the creator portal + decision
  emails); **publish gate** on creator uploads (pending until a human publishes);
  outreach draft send/copy/open-in-mail; `/relationships` N+1 elimination.
- **P3 (partial):** hero video `preload=metadata`; single-source CSS cache-buster;
  single-source delivery-doc legal copy.

## In flight / next candidates

- **Campaign Workspace (Creative OS)** — the strategic pivot, now building. Increment
  1 shipped (campaign container + structured creative direction + creative timeline),
  flag **ON in prod** (`CHORDENTIAL_CAMPAIGN_WORKSPACE=1`) for dogfooding.
  ⚠️ **Architectural spine (in progress):** the workspace must *inherit* creative
  direction, not *recreate* it (lineage: `DISCOVERY_INTELLIGENCE_LINEAGE.md`). Progress:
  **✅ Step 1 done** — `agency_id` threads Opportunity→Project→Campaign so Agency/Company
  Intelligence is reachable. **✅ Parent object designed** — **Campaign Intelligence**
  (`CAMPAIGN_INTELLIGENCE.md`): the canonical per-engagement record with a per-field
  provenance model (`{value, sources[], status}`), born at the discovery call, inherited
  and contributed-back by every module. **Next (awaiting Jon's §9 decisions):** build CI
  tables + lazy backfill → point the workspace's direction cards at CI with the provenance
  card → discovery-call capture → proposal/production/delivery read+write CI → flywheel to
  Agency Intelligence. Then the PRD's cues/team/AI-employee increments on top. Each stays
  flagged, dogfood-first, and passes the anti-generic-PM gate.
- **Platform UI** — realize `platform-website-plan.md` (control-room theme, Why-Today
  queue, Strategy Card gating outreach, `/today` continuity queue, timecoded review as
  the hero).
- **Zero-downtime cutover** — run the SQLite→Postgres ops (code ready, see ADR-0006 /
  `docs/zero-downtime-cutover.md`).

## Known deferred / not-yet-built (do not assume these exist)

- **Postgres cutover ops** — code ready, not run; prod is still SQLite on a
  single-attach disk (every deploy ~2-min blip).
- **DocuSign e-signature** — placeholder only.
- **Durable object storage** — uploads are on local disk (S3/R2 seam not wired).
- **Server-side PDF rendering** of branded docs — best-effort/print-to-PDF only.
- **Scheduler-internals hardening** (from the audit's P3 tail, deliberately left for a
  dedicated pass): auto-fetch/discovery still parses hostile HTML **in-process**
  (unlike enrichment — see ADR-0008); per-agency manual actions bypass the heavy lock;
  lock-busy cycles reset their interval timer; engine stats zero on deploy. All LOW
  severity, most only active under `CHORDENTIAL_AUTONOMOUS=1` (off by default).
- **DBperf micro-opts** (LOW): signal insert is SELECT-then-INSERT; signal "seen" set
  grows unbounded. Flagged as needing a Postgres test target before relying on
  `ON CONFLICT`/`rowcount` semantics (ADR-0006).
- **Phase B/C** — multi-tenant accounts and the buyer-side marketplace are horizon,
  not started.

## Where the real record lives

- **Strategy & philosophy:** `docs/company-strategy.md`, `docs/company-definition.md`,
  `docs/product-roadmap.md`, `docs/cmo-charter.md`.
- **Deliberation archive:** the `*-council.md` files and build plans in `docs/`
  (chronological decision record — not canonical reference).
- **Design direction:** `docs/platform-website-plan.md`,
  `docs/storyboards/chordential-experience-storyboards.html`.
- **Operations:** `docs/delivery-os-user-manual.md`, `docs/zero-downtime-cutover.md`,
  `docs/efficiency-report.md`, `docs/product-efficiency-audit.md`.
