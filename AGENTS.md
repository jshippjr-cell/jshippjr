# Chordential — Agent Manifest

> **This file is the control panel for every agent on the platform.** As Chordential
> grows from a handful of agents to dozens, this manifest — not the code — is the map.
>
> **Manifest-first rule (ADR-0007):** to add a capability, **add its agent here as
> `⚪ Planned` first**, then implement it, then advance its status. An agent that exists
> in code but not here is a process bug; an agent here that overlaps another's
> responsibility is a design bug — fix the boundary, not the symptom.
>
> Governed by [`CHORDENTIAL_SYSTEM_ARCHITECTURE.md`](CHORDENTIAL_SYSTEM_ARCHITECTURE.md).
> Status legend: 🟢 Production · 🟡 In development · ⚪ Planned.
> Tier (§4.2): **T1** deterministic engine · **T2** connector/job · **T3** assistive AI.
> Governance (§4.3): **Gated** (proposes only) · **Auto** (autonomous into a review
> queue / read-only) · **Action** (performs an authorized outbound/irreversible action).

---

## Summary index

| Agent | Status | Tier | Owner module | Governance |
|-------|--------|------|--------------|------------|
| Agency Discovery Agent | 🟡 | T2 | Agency Discovery | Gated |
| Discovery Crawler (Talent + Opportunity) | 🟢 | T2 | Discovery / Talent | Gated |
| Signal Engine | 🟢 | T2 | Opportunity Intelligence | Auto→Gated |
| Triage Agent | 🟢 | T1/T3 | Opportunity Intelligence | Auto |
| Intake Parser | 🟢 | T1 | Opportunity Intelligence | Auto |
| Qualification Engine | 🟢 | T1 | Music Opportunity Scoring | Gated |
| Scoring Engine | 🟢 | T1 | Music Opportunity Scoring | Auto |
| Strategic Value Engine | 🟢 | T1 | Music Opportunity Scoring | Auto |
| Estimation Engine | 🟢 | T1 | Estimation | Gated |
| Proposal Builder | 🟢 | T1 | Proposal Generation | Action |
| Capabilities Doc Builder | 🟢 | T1 | Proposal Generation | Action |
| Outreach Planner | 🟢 | T1 | Outreach | Action |
| Talent Matcher | 🟢 | T1 | Talent / Supply | Gated |
| Delivery: Rights Agent | 🟢 | T1 | Delivery OS | Gated |
| Delivery: Revisions Agent | 🟢 | T1 | Delivery OS | Gated |
| Delivery: Metadata Agent | 🟢 | T1 | Delivery OS | Gated |
| Delivery: Approvals Agent | 🟢 | T1 | Delivery OS | Gated |
| Delivery: Assets Agent | 🟢 | T1 | Delivery OS | Gated |
| Scheduler / Auto-Fetcher | 🟢 | T2 | Scheduler | Auto |
| Notification Dispatcher | 🟡 | T2 | Notification System | Action |
| Company Intelligence Agent | ⚪ | T2/T3 | Company Intelligence | Auto |
| Contact Discovery Agent | ⚪ | T2 | Contact Discovery | Gated |
| Relationship Intelligence Agent | ⚪ | T1 | Relationship Intelligence | Auto |
| RFP Ingestion Agent | ⚪ | T2 | Opportunity Intelligence | Gated |
| Identity Resolution Agent | ⚪ | T1 | Shared / CRM | Auto |
| Outreach Composer (AI-assist) | ⚪ | T3 | Outreach | Gated |
| Campaign Tracker | ⚪ | T1 | Campaign Tracking | Auto |
| Morning Brief Agent | ⚪ | T1 | Reporting | Auto |
| Weekly Refresh Orchestrator | ⚪ | T2 | Scheduler / Reporting | Mixed |

---

## Production & in-development agents

### Agency Discovery Agent — 🟡 In development · T2 · Gated
- **Purpose:** Paginate a B2B agency directory (Clutch) and collect prospective buyer
  agencies for review.
- **Inputs:** Directory base URL + page (config); `CHORDENTIAL_ENABLE_SCRAPE`; existing
  `agencies` (for dedupe).
- **Outputs:** `agencies` rows (status `New`); a JSON export for verification; an
  `agency_runs` checkpointed run record + structured log.
- **Owner module:** Agency Discovery.
- **Dependencies:** Database (agencies, agency_runs); Config; Logging; (import step is
  human-gated).
- **Frequency:** Manual (no scheduler by decision, during pipeline validation).
- **Triggers:** Operator presses *Run discovery*; *Resume* for an interrupted run.
- **Notes:** Reference implementation of idempotent + resumable + observable (ADR-0004).
  Preview→verify(JSON/report/PDF)→import flow keeps the human in the loop.

### Discovery Crawler (Talent + Opportunity) — 🟢 Production · T2 · Gated
- **Purpose:** Fetch talent and opportunity records from an operator-approved catalog of
  industry sources into review queues.
- **Inputs:** Curated source catalog + approved `crawl_targets`; `CHORDENTIAL_ENABLE_SCRAPE`.
- **Outputs:** Pending talent; inbound leads/opportunities; target fetch outcomes.
- **Owner module:** Discovery / Talent. **Dependencies:** Database, Config, Scheduler.
- **Frequency:** Scheduled auto-fetch + manual. **Triggers:** Approved target on an
  active source; auto-fetch cycle.

### Signal Engine — 🟢 Production · T2 · Auto→Gated
- **Purpose:** Ingest opportunity signals from feeds (RSS/email/paste) and rank by
  freshness × score.
- **Inputs:** Configured feeds; forwarded alerts. **Outputs:** `signals` (status `New`);
  phone/push alerts.
- **Owner:** Opportunity Intelligence. **Dependencies:** rss, triage, Notification,
  Scheduler. **Frequency:** Scheduled poll + on-demand. **Triggers:** Poll cycle; inbound
  email webhook.

### Triage Agent — 🟢 Production · T1 (T3-ready) · Auto
- **Purpose:** Classify/score raw signals to keep the demand queue precise.
- **Inputs:** `signals`. **Outputs:** signal type/score/tier annotations.
- **Owner:** Opportunity Intelligence. **Frequency:** On ingest / scheduled.

### Intake Parser — 🟢 Production · T1 · Auto
- **Purpose:** Parse forwarded saved-search/alert emails into structured opportunities.
- **Inputs:** Email text/files. **Outputs:** Opportunity candidates / inbound leads.
- **Owner:** Opportunity Intelligence. **Frequency:** On submission.

### Qualification Engine — 🟢 Production · T1 · Gated
- **Purpose:** Apply the qualification rubric (discipline fit, disqualifiers) to decide
  pursue-worthiness.
- **Inputs:** Opportunity. **Outputs:** QualificationResult (qualified, discipline,
  action, confidence). **Owner:** Music Opportunity Scoring. **Frequency:** On evaluate.
  **Gate:** human qualifies/promotes.

### Scoring Engine — 🟢 Production · T1 · Auto
- **Purpose:** Weighted scoring + tiering + win-probability ranking of opportunities.
- **Inputs:** Opportunity (+ weights). **Outputs:** Score, Tier, breakdown.
- **Owner:** Music Opportunity Scoring. **Frequency:** On evaluate / list.

### Strategic Value Engine — 🟢 Production · T1 · Auto
- **Purpose:** Assess longer-term strategic value of a buyer/opportunity beyond raw score.
- **Inputs:** Opportunity/buyer. **Outputs:** StrategicValue. **Owner:** Scoring.

### Estimation Engine — 🟢 Production · T1 · Gated
- **Purpose:** Produce a defensible price/effort estimate (line items, band) for a need.
- **Inputs:** Qualified opportunity/brief. **Outputs:** Estimate (shown band recorded).
- **Owner:** Estimation. **Frequency:** On request. **Gate:** human approves the quote.

### Proposal Builder & Capabilities Doc Builder — 🟢 Production · T1 · Action
- **Purpose:** Assemble client-facing proposals / capability docs deterministically from
  engine data (editable via overrides).
- **Inputs:** Opportunity, Estimate, chips/overrides. **Outputs:** Proposal/Document
  (Draft→Sent). **Owner:** Proposal Generation. **Action gate:** human sends.

### Outreach Planner — 🟢 Production · T1 · Action
- **Purpose:** Plan the next buyer touches/sequence and record outreach events.
- **Inputs:** Opportunity, history. **Outputs:** OutreachPlan/steps; outreach_events.
- **Owner:** Outreach. **Action gate:** human sends; provider seam (`mailer`/gmail).

### Talent Matcher — 🟢 Production · T1 · Gated
- **Purpose:** Match qualified opportunities to suitable creators.
- **Inputs:** Opportunity/brief + talent roster. **Outputs:** TalentMatch ranking.
- **Owner:** Talent/Supply. **Gate:** human assigns.

### Delivery OS Agents — Rights · Revisions · Metadata · Approvals · Assets — 🟢 Production · T1 · Gated
- **Purpose (each, single-responsibility):** *Rights* — clearance/licensing checklist;
  *Revisions* — round tracking; *Metadata* — delivery metadata completeness; *Approvals*
  — stakeholder sign-off; *Assets* — deliverable file states.
- **Inputs:** Project + `delivery_json` + reviewer actions. **Outputs:** delivery state,
  review_comments, asset approval states. **Owner:** Delivery OS. **Frequency:** On
  project events. **Gate:** human approves/releases at each stage.

### Scheduler / Auto-Fetcher — 🟢 Production · T2 · Auto
- **Purpose:** Run recurring agents on time/trigger; dispatch due crawl/signal work with
  backoff; the orchestration substrate.
- **Inputs:** Active sources/targets, feed config. **Outputs:** agent runs + outcomes.
- **Owner:** Scheduler. **Frequency:** Continuous (cycle). **Triggers:** time + readiness.

### Notification Dispatcher — 🟡 In development · T2 · Action
- **Purpose:** Deliver alerts to channels (web push, email, ntfy) from platform events.
- **Inputs:** Domain events / new leads. **Outputs:** delivered notifications.
- **Owner:** Notification System. **Dependencies:** webpush, mailer, Config.
- **Frequency:** Event-driven. **Triggers:** new lead/signal/delivery event.

---

## Planned agents (designed, not yet built)

### Company Intelligence Agent — ⚪ · T2/T3 · Auto
- **Purpose:** Enrich a discovered agency into firmographics (size, sector, locations,
  tech/spend signals). **Inputs:** Agency. **Outputs:** enriched org fields + provenance.
- **Owner:** Company Intelligence. **Deps:** enrichment provider seam, Identity
  Resolution, CRM. **Frequency:** After Discovery / scheduled. **Trigger:** new/ stale
  Agency.

### Contact Discovery Agent — ⚪ · T2 · Gated
- **Purpose:** Find decision-maker contacts at a known org. **Inputs:** Org. **Outputs:**
  Contact rows (Discovered). **Owner:** Contact Discovery. **Deps:** provider seam,
  Relationship Intelligence. **Frequency:** After Intelligence. **Gate:** human verifies.

### Relationship Intelligence Agent — ⚪ · T1 · Auto
- **Purpose:** Maintain the buyer↔creator↔contact graph; surface warm intro paths.
- **Inputs:** Contacts, Interactions, Assignments. **Outputs:** Relationship edges +
  strength. **Owner:** Relationship Intelligence. **Frequency:** On graph change.

### RFP Ingestion Agent — ⚪ · T2 · Gated
- **Purpose:** Ingest RFPs/briefs from portals/email into Opportunities. **Inputs:** RFP
  sources. **Outputs:** Opportunity + Music Brief candidates. **Owner:** Opportunity
  Intelligence. **Gate:** human qualifies.

### Identity Resolution Agent — ⚪ · T1 · Auto · **(priority — see §14 critique)**
- **Purpose:** Resolve the *same* real-world org/contact arriving from multiple agents
  into one canonical record (beyond per-store dedupe). **Inputs:** candidate records
  across stores. **Outputs:** canonical entity + merge links + audit. **Owner:** Shared /
  CRM. **Frequency:** On ingest. **Why priority:** prevents CRM fragmentation as
  ingestion scales.

### Outreach Composer (AI-assist) — ⚪ · T3 · Gated
- **Purpose:** Draft outreach copy as a *suggestion*. **Inputs:** Opportunity context.
- **Outputs:** draft text (advisory). **Owner:** Outreach. **Gate:** human edits/sends;
  LLM behind a seam; never auto-sends.

### Campaign Tracker — ⚪ · T1 · Auto
- **Purpose:** Group touches into campaigns; track status + attribution. **Inputs:**
  Interactions. **Outputs:** Campaign rollups. **Owner:** Campaign Tracking.

### Morning Brief Agent — ⚪ · T1 · Auto (read-only)
- **Purpose:** Compose the daily operator brief from CRM/Opportunities/Delivery/Runs.
- **Inputs:** read-models. **Outputs:** Brief doc + alert. **Owner:** Reporting.
- **Frequency:** Daily (scheduled).

### Weekly Refresh Orchestrator — ⚪ · T2 · Mixed
- **Purpose:** Re-run Discovery → Intelligence → Scoring weekly and report deltas.
- **Inputs:** pipeline state. **Outputs:** refreshed pipeline + report. **Owner:**
  Scheduler / Reporting. **Frequency:** Weekly. **Governance:** gated where it binds.

---

## Manifest maintenance

- **Adding an agent:** append a `⚪ Planned` entry (all fields) **before** coding; ADR if
  it adds a gate/tier/dependency/entity (ADR-0007).
- **Shipping an agent:** advance status; ensure tests + observability + dedupe + resume.
- **No overlaps:** each agent has exactly one Owner module and one responsibility. Two
  agents wanting the same write → the write belongs to one owner with one interface.
- **Keep it honest:** a status here that overstates reality is a bug to fix, like any other.
