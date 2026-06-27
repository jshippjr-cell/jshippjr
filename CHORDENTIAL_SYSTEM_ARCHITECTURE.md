# CHORDENTIAL — System Architecture

> **Status:** Living document · v1.1 · 2026-06-27 (ADR-0008: multi-tenant + UUID foundation shipped)
> **Authority:** This is the architectural **constitution** for Chordential. Every
> future development chat, implementation agent, and human contributor treats it as
> authoritative. Code that contradicts this document is a bug in the code *or* a
> proposal to amend this document via an ADR (§13) — never a silent divergence.
> **Companion files:** [`AGENTS.md`](AGENTS.md) (the live agent manifest), `CLAUDE.md`
> (working guidance for agents in this repo), `docs/` (strategy + decision record).

---

## 0. How to read this document

This document describes **two layers at once**, and always labels which is which:

- **TARGET** — the architecture we are building toward (a multi-tenant SaaS platform
  hosting dozens of small, governed agents).
- **CURRENT** — what exists in the repository today (a single Python package
  `src/chordential_oia/` — deterministic engines + a FastAPI/SQLite web app).

The honesty rule from `CLAUDE.md` applies to architecture too: **we never describe a
capability as built when it is planned.** Status is marked throughout:

| Mark | Meaning |
|------|---------|
| 🟢 | **Production** — exists, tested, in use today |
| 🟡 | **In development** — partially built / behind a flag |
| ⚪ | **Planned** — designed here, not yet implemented |

The gap between CURRENT and TARGET is not failure; it is the **migration backlog**.
§7 and §13 own that backlog. Nothing here authorizes a big-bang rewrite — we evolve
toward the target one ADR-sized step at a time.

---

## 1. Vision

### What Chordential is
Chordential is a **procurement-grade music studio plus the operating system that runs
it.** The product the market pays for is the *music service*: clearance-certified,
human-composed original music delivered with the documentation and rigor a
procurement department expects. The software — qualification, estimation, the
buyer↔creator graph, discovery, and the Delivery OS — is the **internal moat** that
lets a tiny team operate like a large, dependable vendor.

### The problem it solves
Buyers of original music (agencies, brands, production companies, game studios) face
a market that is **slow, opaque, and risky**: hard to find vetted composers, hard to
price fairly, hard to guarantee rights/clearance, and hard to manage delivery. Music
creators face the mirror problem: opportunity is scattered and unqualified.
Chordential closes that gap by **industrializing the unglamorous parts** — finding and
qualifying demand, estimating accurately, matching the right creator, and delivering
with airtight provenance — so that the creative work itself can be reliably sold.

### Who the users are
- **The operator (today: Jon).** Runs the studio. Presses every decision button. The
  whole system is built so one trusted human can run the throughput of a team.
- **Buyers / clients.** Receive proposals, capability docs, and the delivery portal.
- **Creators / composers (talent).** Discovered, vetted, matched, and assigned.
- **Reviewers / stakeholders.** Approve deliverables through token-gated portals.
- **TARGET ⚪ Teams, vendors, agency & client portals, composer network** — multiple
  authenticated users with roles (§12).

### Long-term vision
A platform where **dozens of small, governed agents** continuously find demand,
enrich it, qualify it, price it, match it to creators, and shepherd it through
delivery — with a human holding the decision authority that matters and a full audit
trail behind every action. Chordential becomes the **system of record and system of
action** for procurement-grade music, expandable into adjacent creative-services
procurement without redesign.

### Non-goals (what we will *not* build)
- **No AI-generated audio, ever.** The music is human/composer-made. The system
  organizes, documents, packages, and delivers — it never generates the creative
  good. This is a permanent product invariant, not a phase.
- **No fully-autonomous decisioning** on the things that bind the business (who to
  qualify, what to send, what to approve, what to pay). Agents *propose*; the human
  *disposes* (§2).
- **No fake capability or fabricated client work** in any surface, demo, or document.

---

## 2. Design Philosophy

These are binding engineering principles. "Every future contributor must follow"
means: a change that violates one needs an ADR explaining why.

1. **Single Responsibility.** Every module/agent does one nameable thing. If you need
   "and" to describe it, split it.
2. **Modular architecture, never monolithic.** Small, focused components with explicit
   boundaries. New capability = new module/agent, not a new branch inside an old one.
3. **API-first thinking.** A module's *interface* (its public functions / future HTTP
   contract) is the product; its internals are private. Design the contract first.
4. **Separation of concerns.** Discovery never scores. Scoring never sends email.
   Delivery never qualifies. Cross-cutting needs go to **Shared Services** (§11), not
   into a feature module.
5. **Configuration over hardcoding.** Behavior that varies (URLs, weights, providers,
   thresholds, feature flags) is config/env, not literals. See `CHORDENTIAL_*` env
   conventions (§8).
6. **Provider seams.** External dependencies (payments, email, storage, LLMs, search)
   sit behind a null-by-default interface that becomes real when configured, and
   **never raises into the caller**. Pattern already live in `payments/` and
   `mailer.py`.
7. **Human approval where it binds.** *"The machine proposes, Jon disposes."* Engines
   analyze and recommend; a human presses qualify / assign / approve / release / send.
   This is a first-class architectural constraint, enforced by the **Governance Layer**
   (§2.1), not a UI nicety.
8. **Observable systems.** Every agent run is logged, counted, and inspectable
   (progress, counters, failures, timing). If you can't see what an agent did, it
   isn't done. (Reference implementation: the Agency Discovery `agency_runs` +
   structured run log.)
9. **Fail gracefully.** A connector/agent failure degrades to empty/partial results
   and a recorded reason — it never crashes the request or the platform. Best-effort,
   never blocking, for all side-effects (push, email, export).
10. **Idempotent workflows.** Re-running a workflow must not duplicate data. Dedupe on
    stable keys; "insert if new" everywhere ingest happens.
11. **Resume interrupted work.** Long/multi-step jobs checkpoint progress and resume
    from the last good step. (Reference: Agency Discovery resume-from-last-page.)
12. **Every module independently testable.** Pure functions for parsing/scoring (no
    network), seams for I/O, deterministic outputs. The suite stays green before any
    commit. Network is flag-gated OFF in tests/sandbox.
13. **Determinism in the spine; AI at the edges.** The decision/estimate/delivery
    spine is deterministic and explainable. LLM/AI assistance is **advisory only,
    optional, behind a seam, and never in the audio path or the decision-of-record.**
14. **Provenance by default.** Every ingested record carries where it came from
    (`source`, `source_url`, timestamps). Trust requires traceability.

### 2.1 The Governance & Trust Layer (the principle most platforms add too late)
Because Chordential's value *is* trust (clearance, honesty, human judgment), the rules
in #7, #13, and #14 are not left to each module's goodwill — they are a **cross-cutting
layer** every agent runs inside:

- **Decision gates** are explicit states in the data model (e.g. `Proposed → Approved`,
  `New → Qualified`, `Pending → Approved`). No agent may advance a record past a gate
  that the platform marks human-owned.
- **Action authorization.** Outbound/irreversible actions (send, charge, release,
  delete) require an authorized actor. Agents enqueue them; the gate releases them.
- **Audit trail.** Who/what changed a record, when, and why is recorded (§6).
- **Provenance & honesty checks.** Discovered data is labeled, demo data uses invented
  brands, and "AI-assisted" is disclosed wherever true.

This layer is the reason "dozens of autonomous agents" is **safe** rather than
reckless: autonomy is bounded by governed gates, not by hope.

---

## 3. Core Platform Modules

A **module** owns a domain and exposes an interface; **agents** (§4) are the runnable
units that live inside a module. Modules never overlap responsibilities; when two
modules need the same capability, that capability moves to **Shared Services** (§11).

Legend: *Owner* names the responsible domain; *Today* maps to current code; *Must not*
states the boundary it may not cross.

| # | Module | Single responsibility | Today (code) | Status |
|---|--------|----------------------|--------------|--------|
| 1 | **Agency Discovery** | Find prospective agencies/buyers from directories; dedupe; queue for review | `web/agency_discovery.py`, `web/discovery.py`, `web/discovery_sources.py`, `web/crawl_adapters.py` | 🟡 |
| 2 | **Company Intelligence** | Enrich a discovered org into firmographics (size, sector, locations, signals) | `web/buyer_intel.py` (seed) | ⚪ |
| 3 | **Contact Discovery** | Find decision-makers/contacts at a known org | — | ⚪ |
| 4 | **Relationship Intelligence** | Maintain the buyer↔creator↔contact graph; surface warm paths | `matching.py` (partial), buyer graph routes | 🟡 |
| 5 | **Opportunity Intelligence** | Detect/ingest live opportunities & RFPs from signals/inbound | `web/signals.py`, `web/triage.py`, `web/rss.py`, `intake.py` | 🟢 |
| 6 | **Music Opportunity Scoring** | Qualify + score + rank an opportunity; strategic value | `qualification.py`, `scoring.py`, `strategic.py`, `web/evaluate.py` | 🟢 |
| 7 | **Estimation** | Turn a qualified need into a defensible price/effort estimate | `estimation.py`, `web/estimate.py` | 🟢 |
| 8 | **Proposal Generation** | Assemble client-facing proposals & capability docs from engine data | `proposals.py`, `capabilities.py`, `prepare.py` | 🟢 |
| 9 | **CRM** | System of record for orgs, contacts, opportunities, interactions, pipeline | `web/db.py` (opportunities, companies, outreach_events), pipeline routes | 🟢 |
| 10 | **Outreach** | Plan and record buyer communications; sequences; channels | `outreach.py`, `web/compose`, `mailer.py`, `web/gmail_client.py` | 🟢 |
| 11 | **Campaign Tracking** | Group outreach into campaigns; track touches, status, attribution | outreach_events + source attribution (partial) | 🟡 |
| 12 | **Delivery OS** | Run a won project to delivery: rights, revisions, metadata, approvals, assets | `delivery.py`, delivery/review routes + portals | 🟢 |
| 13 | **Talent / Supply** | Discover, vet, match, assign creators | `talent.py`, `matching.py`, `talent_sources/`, roster routes | 🟢 |
| 14 | **Reporting** | Compose read-models: Morning Brief, Weekly Refresh, dashboards, run reports | dashboard, `web/showcase.py`, agency report | 🟡 |
| 15 | **Notification System** | Deliver alerts across channels (push, email, ntfy) from platform events | `web/webpush.py`, `web/signals.py` push, `mailer.py` | 🟡 |
| 16 | **Scheduler** | Time/trigger-based orchestration of recurring agent runs | `web/scheduler.py` | 🟢 |
| 17 | **Administration** | Operator config, source health, feature gates, seed/data tools | `web/sources.py`, `web/seed.py`, admin gate | 🟡 |
| 18 | **Authentication & Authorization** | Identify actors; enforce roles/permissions and token-gated access | admin token + `share_token`/`?r=` portals | 🟡 |
| 19 | **Shared Services** | Reusable platform primitives (logging, config, storage, search, cache, metrics) | scattered (§11) | 🟡 |
| 20 | **Governance & Trust** | Decision gates, action authorization, audit, provenance, honesty | implicit across modules (state machines) | 🟡→🟢 |

**Mission spine.** Modules 1–12 compose Chordential's deterministic **mission spine**:
**Identify → Enrich → Contact → Rank → Qualify → Estimate → Prepare → Outreach →
Win/Loss → Deliver.** Each arrow is a typed handoff between modules (§9), never a
reach-in.

---

## 4. AI Agent Registry

The **authoritative, living registry lives in [`AGENTS.md`](AGENTS.md)** (the manifest).
This section defines the *schema* and *governance tiers* for that registry; the
manifest is the control panel that must be updated **before** an agent is built.

### 4.1 Agent definition schema
Every agent entry declares:

- **Name** — unique, verb-first where possible (e.g. *Agency Discovery Agent*).
- **Status** — Planned ⚪ / In development 🟡 / Production 🟢.
- **Tier** — see §4.2.
- **Purpose** — one sentence; one responsibility.
- **Inputs** — typed entities/config it reads.
- **Outputs** — typed entities/events it writes.
- **Owner module** — the §3 module it belongs to (exactly one).
- **Dependencies** — modules/services/agents it calls (through interfaces only).
- **Frequency** — manual / on-trigger / scheduled (cron) / continuous.
- **Trigger conditions** — what causes a run.
- **Governance** — Autonomous, Human-gated (proposes only), or Action-authorized.

### 4.2 Agent tiers (reconciling "AI agents" with our determinism rule)
Not every agent is an LLM. We run three tiers, all called "agents" because they are
small, independently-runnable units with a manifest entry:

- **T1 — Deterministic engines.** Pure, explainable logic (qualification, scoring,
  estimation, proposal assembly, the Delivery OS checklists). No network, no LLM.
  These are the decision-of-record. *Most of the spine is here.*
- **T2 — Connectors / crawlers / jobs.** I/O against the outside world (discovery,
  signal ingestion, email send, enrichment fetch, scheduler). Flag-gated, fail-soft,
  idempotent, resumable.
- **T3 — Assistive AI.** Optional LLM-backed helpers (draft an outreach note, classify
  a messy signal, summarize a brief). **Advisory only**, behind a provider seam,
  output always reviewed at a gate, never writing a decision-of-record or audio.

### 4.3 Governance modes
- **Autonomous** — may complete without a human (T2 ingestion into a *review queue*,
  T1 computing a score). It still cannot cross a human-owned gate.
- **Human-gated** — produces a proposal that a human approves (qualify, assign,
  release). The default for anything that binds the business.
- **Action-authorized** — performs an outbound/irreversible action, allowed only when
  an authorized actor has released the gated action (send, charge, delete).

> **Rule:** Adding a capability = (1) add the agent to `AGENTS.md` as Planned, (2) write
> an ADR if it introduces a new gate/tier/dependency, (3) implement, (4) flip status.
> *Manifest first, code second.*

---

## 5. Data Model

Entities are the lingua franca between modules — agents communicate **through shared
data models**, not through each other's internals (§9). Each entity below lists
*Purpose, Primary identifier, Key relationships, Lifecycle, Ownership.* Current tables
are named where they exist.

> **Identity note (🟢 shipped — ADR-0008):** every primary entity carries a stable
> **`uuid`** (auto-stamped) *and* a **`tenant_id`** (defaulted to the single default
> tenant) **today**, even though the platform is single-tenant in practice. Integer PKs
> remain the internal FK keys; UUIDs are the stable external/cross-tenant identifier.
> Tenant **scoping of queries** is deferred behind the `current_tenant_id()` seam until
> the Auth layer exists — flipping it on is additive, not a redesign.

| Entity | Purpose | Primary id | Key relationships | Lifecycle (states) | Owner module |
|--------|---------|-----------|-------------------|--------------------|--------------|
| **Tenant** 🟢 | The isolation/ownership root every business row belongs to | `tenants.id` (UUID) | owns every tenant-scoped entity; will own Users/Teams | `active → suspended` | Governance / Auth |
| **Agency / Organization** | A buyer org (discovered or known) | `agencies.id` + `uuid` | belongs to Tenant; has many Contacts; raises Opportunities; subject of Intelligence | `New → Reviewed → Dismissed` (discovery); promote → CRM org | Agency Discovery → CRM |
| **Company (CRM)** | Canonical org record in the pipeline | `companies.client` | parent of Opportunities/Projects | implicit (active) | CRM |
| **Contact** ⚪ | A person at an org | `contacts.id` | belongs to Agency; party to Interactions | `Discovered → Verified → Engaged → Dormant` | Contact Discovery / CRM |
| **Opportunity** | A potential deal/need | `opportunities.id` | belongs to Org; scored; → Proposal; → Project | `New → Pursuing → Submitted → Won / Lost / Passed` | Opportunity Intelligence / Scoring |
| **Inbound Lead / Signal** | Raw demand before qualification | `inbound_leads.id`, `signals.id` | promotes → Opportunity | leads `New→Reviewed→Qualified→Dismissed`; signals `New→Reviewed→Promoted→Dismissed` | Opportunity Intelligence |
| **Interaction** | One recorded touch (email, call, note) | `outreach_events.id` (→ `interactions`) | belongs to Opportunity/Contact; part of Campaign | append-only event | Outreach / CRM |
| **Campaign** ⚪ | A grouped outreach effort | `campaigns.id` | has many Interactions; targets Orgs | `Draft → Active → Paused → Done` | Campaign Tracking |
| **Proposal** | Client-facing offer | `proposals.id` | of Opportunity/Project; spawns Invoices | `Draft → Sent → Accepted → Declined` | Proposal Generation |
| **Project** | A won engagement in delivery | `projects.id` | from Opportunity; has Assignments, Milestones, Assets | `Active → Delivered` | Delivery OS |
| **Music Brief** | The creative spec for a project | `brief_progress` + `doc_overrides` | of Opportunity/Project; drives Matching | step-completion | Proposal / Delivery |
| **Creative Asset** | A delivered/work-in-progress music file + metadata | uploads + `delivery_json` | of Project; reviewed; rights-checked | `Pending → Approved → Changes requested` | Delivery OS |
| **Talent / Creator** | A music creator | `talent.id` | matched to Opportunities; assigned to Projects | review `Pending…`; invite `Prospect…` | Talent/Supply |
| **Assignment** | Talent ↔ Project role binding | `assignments.id` | links Talent + Project | created/active | Delivery OS |
| **Relationship** ⚪ | Edge in the buyer↔creator↔contact graph | `relationships.id` | connects two parties with type/strength | `weak → warm → strong` | Relationship Intelligence |
| **Document** | A generated artifact (capability doc, delivery package, report, export) | path/`doc_overrides` | of Opportunity/Project/Run | versioned/best-effort PDF | Proposal / Reporting |
| **Task / Job** ⚪ | A unit of agent work | `tasks.id` / `agency_runs.id` (pattern) | produced/consumed by agents | `queued → running → completed / interrupted / failed` | Scheduler / Shared |
| **Notification** | An alert to a user/channel | `push_subscriptions` + events | of an event; to a User | `created → sent → read` | Notification System |
| **User** ⚪ | An authenticated actor | `users.id` (UUID) | belongs to Tenant; has Roles; owns actions | `invited → active → suspended` | Auth |
| **Audit Record** ⚪ | Immutable change log entry | `audit_log.id` | references any entity + actor | append-only | Governance |
| **Run / Agent Execution** | One observable agent run | `agency_runs.id` (pattern to generalize) | of an Agent; checkpoints | `running → completed / interrupted` | Shared (Observability) |

**Reference patterns already in the codebase (reuse, don't reinvent):**
- **Per-record JSON state blobs** for display/workflow data: `opportunities.doc_overrides`,
  `projects.delivery_json` with merge-one-key helpers.
- **Token-gated client surfaces:** `share_token` + per-reviewer `?r=` tokens.
- **Additive column migrations:** `_*_COLUMNS` dict + `ALTER TABLE` loop in `db.py`.
- **Checkpointed run state:** `agency_runs` (generalize into a platform `runs` table).
- **Tenancy + identity (🟢 ADR-0008):** new tables register in `_ENTITY_TABLES`
  (gets `uuid` + `tenant_id`) or `_TENANT_ONLY_TABLES` (gets `tenant_id`) in `db.py`;
  the migration stamps columns, backfills, indexes `tenant_id`, and installs the UUID
  trigger. **Every new table must join one of these lists** — that is the rule that
  keeps the platform tenant-safe as it grows.

---

## 6. Database Philosophy

- **Engine strategy.** **SQLite-first (CURRENT 🟢), Postgres-ready (🟡).** The `db.py`
  layer is already Postgres-capable — a `postgresql://` URL switches it. **TARGET:**
  Postgres as the system of record once concurrency/multi-tenancy demands it; keep the
  schema portable (no SQLite-only features in new code). See `docs/zero-downtime-cutover.md`.
- **Normalization.** Normalize the **relational core** (orgs, contacts, opportunities,
  interactions, proposals, projects) to ~3NF so facts live in one place. **Denormalize
  deliberately** for two things only: (a) cached evaluations (score/tier alongside the
  opportunity, always recomputable by the engines) and (b) per-record JSON blobs for
  pure display/workflow state. Denormalization is a performance/UX choice, never the
  source of truth.
- **Indexing strategy.** Index every foreign key, every dedupe key (`company_key`,
  `external_ref`), every state column used for queue filtering (`status`), and
  time columns used for ordering (`created_at`, `*_at`). Add composite indexes for the
  hot read-models (e.g. `(status, created_at)` on queues). Measure before adding more.
- **Deduplication philosophy.** **Idempotent ingest is law.** Every ingest path computes
  a **stable normalized key** and inserts only if new (`agency_exists`/`company_key`,
  `inbound_lead_exists`, `crawl_target_exists`, talent dedupe). Dedupe is *within the
  store the agent owns*; cross-entity identity resolution (same org from two sources)
  is an explicit **Identity Resolution service** (⚪), not an accidental merge.
- **Audit logging.** **TARGET ⚪:** an append-only `audit_log` (actor, action, entity,
  before/after or diff, timestamp, source) for every state transition through a
  governance gate and every outbound action. This is the backbone of the Trust Layer.
  CURRENT: state columns + event tables (`outreach_events`, `project_updates`,
  `agency_runs`) provide partial history.
- **Soft deletion.** **Never hard-delete business records.** TARGET ⚪: `deleted_at`
  (nullable) + `deleted_by`; reads filter it out; the row and its audit survive.
  Dismissals already model this softly (`Dismissed` states) — generalize to a uniform
  `deleted_at` for true deletes.
- **Timestamps.** Every row carries `created_at`; mutable rows carry `updated_at`;
  lifecycle rows carry event timestamps (`decided_at`, `fetched_at`, `finished_at`).
  **UTC, ISO-8601, always.** (Already the convention via `datetime.now(timezone.utc)`.)
- **Migrations.** Additive and idempotent: extend the `_*_COLUMNS` + `ALTER TABLE`
  pattern; `CREATE TABLE IF NOT EXISTS` for fresh DBs. No destructive migrations
  without an ADR and a backup/rollback note.
- **Multi-tenancy & identity keys (🟢 ADR-0008).** Every business row carries a
  **`tenant_id`** (constant column DEFAULT = the seeded default tenant; backfilled on
  ALTER; indexed). Every **primary entity** also carries a stable **`uuid`** (backfilled
  for existing rows; stamped on insert by an `AFTER INSERT` trigger — so insert helpers
  stay untouched). Integer PKs remain internal FK keys; UUIDs are the external/
  cross-tenant identifier. **Query-level tenant scoping is deferred** behind the
  `current_tenant_id()` seam (returns the default tenant until Auth exists); turning it
  on is additive. Postgres cutover swaps the SQLite triggers for column defaults
  (`gen_random_uuid()` / constant `tenant_id`). *Rule: a new table is not done until it
  joins `_ENTITY_TABLES` or `_TENANT_ONLY_TABLES`.*

---

## 7. Folder Structure

### 7.1 TARGET ⚪ — the repository we are growing toward
```
chordential/
├── agents/          # T2/T3 runnable agents, one package per agent (manifest-backed)
│                    #   thin: parse inputs, call core/services, emit outputs. No domain logic.
├── core/            # T1 deterministic domain engines + entities (the mission spine)
│   ├── models/      #   shared data models (the lingua franca of §5/§9)
│   ├── scoring/  qualification/  estimation/  proposals/  delivery/  matching/
│   └── governance/  #   gates, action authorization, provenance, honesty checks (§2.1)
├── api/             # transport layer: HTTP/route handlers, request/response schemas
│                    #   (FastAPI today) — calls core/services, never embeds logic
├── database/        # persistence: schema, migrations, repositories, db connection
├── services/        # Shared Services impls (logging, scheduler, notify, storage, search…)
├── shared/          # cross-cutting utils, types, constants, errors (no I/O, no domain)
├── config/          # configuration + feature flags + provider selection (env-driven)
├── frontend/        # templates / web UI / static (and future SPA / mobile clients)
├── tests/           # mirrors the tree; unit (pure) + integration (seams) + e2e
├── docs/            # strategy, ADRs, runbooks, this constitution, user manuals
└── scripts/         # operational + dev scripts (seed, migrate, one-off jobs)
```

**Why each directory exists**
- **agents/** — the platform's "many small units." Each agent is a folder with its
  manifest entry, its trigger, and its thin orchestration. Keeping agents *out* of
  `core/` enforces "agents are replaceable; engines are stable."
- **core/** — the durable IP: deterministic, explainable, testable domain logic and the
  shared entities. The thing we protect most. **core/ depends on nothing above it.**
- **core/governance/** — elevates the Trust Layer (§2.1) to a real package so gates and
  audit aren't sprinkled through features.
- **api/** — one transport adapter. Swapping/ adding transports (HTTP, CLI, queue) must
  not touch core. Today `web/app.py`; tomorrow possibly a separate service API.
- **database/** — isolates persistence so the SQLite→Postgres move and the repository
  pattern live in one place. Today `web/db.py`.
- **services/** vs **shared/** — services have lifecycle/state and I/O (scheduler,
  storage); shared is pure helpers/types. Different change rates, different testing.
- **config/**, **tests/**, **docs/**, **scripts/** — explicit homes for the things that
  otherwise rot in the wrong place.

**Dependency rule (one direction):**
`agents → core/services/database → shared`. `core` never imports `agents` or `api`.
`api` never embeds domain logic. Violations are caught in review and ADR'd if intended.

### 7.2 CURRENT 🟢 — what exists, and how it maps
```
src/chordential_oia/
├── models.py, qualification.py, scoring.py, strategic.py, estimation.py,
│   proposals.py, capabilities.py, delivery.py, prepare.py, outreach.py,
│   matching.py, talent.py, intake.py, invoicing.py        → core/ (engines + models)
├── payments/, mailer.py                                   → services/ (provider seams)
├── sources/, talent_sources/                              → agents/ + core/models
├── cli.py                                                 → api/ (a transport)
└── web/
    ├── app.py                       → api/            (route layer)
    ├── db.py                        → database/
    ├── agency_discovery.py, discovery*.py, crawl_adapters.py,
    │   signals.py, triage.py, rss.py, buyer_intel.py     → agents/
    ├── scheduler.py, webpush.py, gmail_client.py         → services/
    ├── seed.py, sources.py, showcase.py, public.py       → admin/reporting/frontend
    └── templates/, static/                               → frontend/
```
> **CURRENT reality:** this is effectively a **modular monolith** — one package, clear
> internal module boundaries, no network calls between components. That is the *correct*
> stage for the team size. The TARGET tree is the **refactor target**, approached by
> moving one module at a time behind its interface (ADR-gated). **We do not adopt
> microservices until module boundaries, load, or team size demand it** (§14).

---

## 8. Coding Standards

Binding for every human and agent contributor.

- **Naming.** `snake_case` functions/modules, `PascalCase` classes, `UPPER_SNAKE`
  constants. Names state intent (`agency_exists`, not `check`). Agents are nouns
  ("Agency Discovery Agent"); engine functions are verbs (`build_estimate`).
- **Logging.** Use the stdlib `logging` module with a namespaced logger
  (`chordential.<area>`). Every agent run logs start, per-step progress + counters, and
  outcome. No `print` in library code. Logs are structured enough to reconstruct a run.
- **Error handling.** Domain/core code raises typed errors for programmer mistakes
  (e.g. `ValueError` for an unknown state). **I/O and side-effects fail soft**: return
  empty/partial + a recorded reason, never crash the request. A connector that can't
  reach the network returns a diagnosable outcome, not an exception to the caller.
- **Retries.** External fetches retry with **exponential backoff** (e.g. 2s/4s/8s),
  bounded, with the sleep injectable for tests. A terminal failure is *recorded*
  (failed-page/outcome), and the work is left **resumable**, not silently dropped.
- **Configuration.** All tunables via `config/`/env. No magic literals for URLs,
  weights, thresholds, providers. Defaults are safe (provider seams null; scraping OFF).
- **Secrets.** Only via environment / secret store. Never in code, logs, fixtures,
  commits, or generated docs. Provider creds are app-level, never a user's password.
- **Environment variables.** Namespaced `CHORDENTIAL_*`. Documented in `CLAUDE.md`/
  `config/`. A missing optional var disables its feature gracefully (no crash).
- **Comments.** Explain *why*, not *what*. Match surrounding density. Document the
  contract and the invariant a function protects (especially gates and dedupe).
- **Testing expectations.** Pure logic is unit-tested with no network; I/O is tested via
  monkeypatched seams; the full suite runs (parallel) and **must be green before
  commit.** New behavior ships with tests in the same change. Network stays OFF in CI.
- **Documentation expectations.** A new module/agent updates: its manifest entry
  (`AGENTS.md`), this document if it changes architecture, and an ADR (§13) for any
  significant decision. *Undocumented architecture change = incomplete change.*
- **Commits/branches.** Per `CLAUDE.md`: develop on the designated branch, atomic
  commits, keep the suite green, ADR significant decisions.

---

## 9. Agent Communication Standards

**Core rule: agents communicate through interfaces and shared data models — never by
manipulating another agent's internal logic or state.**

- **Shared data models are the contract.** Agents read/write **entities** (§5) with
  well-defined shapes and lifecycles. An agent that needs another's result reads the
  entity the other produced, not its internals.
- **Module interfaces are the only entry points.** To use another module's capability,
  call its **public function/service** (e.g. `estimation.build_estimate(opp)`,
  `scoring.rank(opps)`) — not its private helpers, not its database tables directly
  when a method exists.
- **Hand-offs are typed and one-directional** along the mission spine. Discovery writes
  Agencies; Intelligence reads Agencies and writes enrichment; Scoring reads
  Opportunities and writes evaluations. No back-reaching.
- **Asynchronous work goes through the Task/Job queue (⚪).** An agent that wants work
  done later **enqueues a Task** (typed payload) rather than calling a peer inline. The
  Scheduler/orchestrator dispatches it. CURRENT: direct calls + DB review queues +
  `agency_runs`-style state; TARGET: a first-class `tasks` table + dispatcher, then an
  event bus when scale warrants.
- **Events for fan-out (⚪).** Significant state changes (e.g. *Opportunity Won*,
  *Agency Discovered*) emit a typed **domain event**; interested modules subscribe
  (Notification, Reporting, Campaign). Producers don't know their consumers. This keeps
  modules decoupled as agent count grows.
- **No shared mutable globals.** State lives in the database or is passed explicitly.
- **Governance is in the path, not around it.** Cross-gate transitions and outbound
  actions go through the Governance Layer's authorized interface, which records audit
  and enforces human ownership — an agent cannot bypass it by writing the row directly.
- **Idempotency keys on messages.** Tasks/events carry a stable key so redelivery or
  re-run is safe (ties to §2 #10).

> **Anti-pattern (forbidden):** Agent A importing Agent B's module to flip B's internal
> flags, or two agents writing the same table with different dedupe rules. If two agents
> need the same write, that write belongs to one owner module with one interface.

---

## 10. Workflow Orchestration

A **workflow** is a named, ordered composition of module/agent steps, run manually or on
a trigger, **idempotent and resumable** end-to-end. The orchestrator (CURRENT:
`web/scheduler.py` + explicit routes; TARGET ⚪: a workflow service over the Task queue)
sequences steps, passes typed results, and records a run.

| Workflow | Trigger | Participating modules (in order) | Output | Governance |
|----------|---------|----------------------------------|--------|------------|
| **Run Discovery** | Manual / scheduled | Agency Discovery → (Identity Resolution) → CRM review queue | New Agencies (review) | Human-gated (review/import) |
| **Run Intelligence** ⚪ | After Discovery / scheduled | Company Intelligence → CRM enrich | Enriched Orgs | Autonomous (into review) |
| **Run Contacts** ⚪ | After Intelligence | Contact Discovery → Relationship Intelligence → CRM | Contacts + graph edges | Human-gated (verify) |
| **Run Opportunities** | Continuous / inbound | Opportunity Intelligence (signals/intake/RFP) → Scoring → CRM | Ranked Opportunities | Human-gated (qualify) |
| **Generate Outreach** | Manual per opp/campaign | Scoring → Proposal/Capabilities → Outreach planner → (Notification) | Drafted touches/docs | Action-authorized (send) |
| **Run Delivery** | On Won | Delivery OS (Rights→Revisions→Metadata→Approvals→Assets) | Delivered project | Human-gated (release) |
| **Morning Brief** | Scheduled (daily) | Reporting reads CRM/Opportunities/Delivery/Runs → Notification | Brief doc + alert | Autonomous (read-only) |
| **Weekly Refresh** | Scheduled (weekly) | Discovery + Intelligence + Scoring re-runs → Reporting | Refreshed pipeline + report | Mixed; gated where it binds |

**Orchestration invariants:** every workflow (1) checkpoints between steps and resumes
from the last good one; (2) dedupes so re-running is safe; (3) emits a run record
(observable §2 #8); (4) degrades gracefully if a step's connector fails (the workflow
records the failure and continues or stops resumably); (5) honors gates — a workflow
**stops at a human-owned gate** and waits, it does not force through.

---

## 11. Shared Services

Reusable platform primitives. **A feature module must never re-implement these.** Each
is a seam: a stable interface with a null/local default and a real impl when configured.

| Service | Responsibility | Today | Status |
|---------|----------------|-------|--------|
| **Configuration** | Resolve env/flags/provider selection; safe defaults | `CHORDENTIAL_*` envs | 🟡 |
| **Logging** | Namespaced structured logs per run/agent | stdlib `logging` (e.g. `chordential.agency_discovery`) | 🟡 |
| **Scheduler / Jobs** | Run agents on time/trigger; dispatch Tasks; backoff; resume | `web/scheduler.py`, `agency_runs` | 🟢→🟡 |
| **Notification** | Multi-channel alerts from events (push/email/ntfy) | `web/webpush.py`, `mailer.py`, signals push | 🟡 |
| **File Storage** | Durable artifact store (docs, assets, exports) | local disk `UPLOAD_DIR`/`EXPORT_DIR` | 🟡 (S3/R2 ⚪) |
| **Search** | Query/index across entities | SQL queries (no engine yet) | ⚪ |
| **Caching** | Memoize expensive reads/enrichment | none formal | ⚪ |
| **Authentication** | Identify actor; sessions/tokens | admin token + share tokens | 🟡 |
| **Authorization** | Roles/permissions; tenant scoping | implicit | ⚪ |
| **Monitoring** | Health, error tracking, run dashboards | `/healthz`, run reports | 🟡 |
| **Metrics** | Counters/timings/attribution for agents & funnel | per-run counters, source attribution | 🟡 |
| **Email/Payments providers** | External seams, null-by-default | `mailer.py`, `payments/` | 🟢 |
| **Identity Resolution** | Cross-source entity dedupe/merge | per-store dedupe only | ⚪ |
| **PDF/Doc rendering** | Deterministic doc → PDF | browser print-to-PDF (best-effort) | 🟡 |

**Known gaps (do not assume these exist):** durable object storage (S3/R2 — local disk
today), server-side PDF rendering (best-effort/print-to-PDF), DocuSign e-sign
(placeholder), the Postgres cutover (code ready, ops not run), a formal RBAC/tenant
layer, a real search/cache engine, an event bus.

---

## 12. Future Expansion

The architecture must absorb these **without redesign** — each has a pre-planned seam:

- **Multiple users / Teams / Role permissions** → the **`tenant_id` scope column and the
  `tenants` root already exist on every table (🟢 ADR-0008)**, so this reduces to: add
  `User`, `Team`, `Role` entities, wire `current_tenant_id()` to the authenticated
  session, and enforce scoping centrally in the repository layer. *The painful part —
  the schema — is already done; what remains is Auth + a seam flip, not a migration of
  every table.*
- **Composer network / Vendor management** → extend Talent/Supply module + portals;
  vendors are orgs with a supply role in the same graph.
- **Agency portals / Client portals** → new `frontend/` surfaces over existing
  token-gated patterns (`share_token`, `?r=`), authorized by the Auth service.
- **RFP ingestion** → an Opportunity Intelligence connector (T2 agent) feeding the same
  Opportunity entity + Scoring; no spine change.
- **Music asset management** → formalize Creative Asset entity + File Storage (S3/R2) +
  metadata/rights from Delivery OS.
- **Contract / Invoice generation** → Proposal/Invoicing modules + the Doc service +
  e-sign/payment provider seams (already stubbed).
- **Analytics dashboards** → Reporting module over read-models + Metrics service.
- **API integrations / Email / Calendar** → provider seams + connector agents; never in
  core. Inbound integrations land as typed events/Tasks.
- **Cloud deployment / Mobile apps** → `api/` is the single contract; web, mobile, and
  integrations are clients of it. Deployment is config (Render today; portable schema).

**The expansion test:** a new capability should require *adding* an agent + maybe an
entity + a manifest entry + an ADR — and **touching no existing module's internals.**
If it forces edits across modules, the boundary was wrong; fix the boundary first.

---

## 13. Architectural Decision Log (ADRs)

Every major decision is recorded here with **Decision · Reasoning · Alternatives ·
Consequences · Date.** New ADRs append; superseded ones are marked, never deleted.

**ADR-0001 — Modular monolith first, microservices later.** *(2026-06-27)*
- **Decision:** Stay a single deployable modular monolith (`core` + `api` + `database`)
  with strict internal boundaries; defer service extraction.
- **Reasoning:** One operator, one small team. Microservices' coordination cost dwarfs
  its benefit at this scale; clean module boundaries capture most of the upside now.
- **Alternatives:** Microservices-from-day-one (rejected: premature, operationally
  heavy); unstructured monolith (rejected: rots into a ball of mud).
- **Consequences:** Fast iteration; must *enforce* boundaries in review to keep future
  extraction cheap. Revisit when load/team/agent-count demands isolation.

**ADR-0002 — Deterministic spine, AI only at the edges.** *(2026-06-27)*
- **Decision:** Decisions/estimates/delivery are deterministic engines; LLM/AI is
  advisory, optional, seamed, and never a decision-of-record or in the audio path.
- **Reasoning:** Trust/explainability is the product; "no AI-generated audio" and human
  authority are permanent invariants.
- **Alternatives:** LLM-driven decisioning (rejected: unexplainable, unsafe for a
  procurement-grade promise).
- **Consequences:** Predictable, testable, auditable core; AI features must justify a
  seam and a review gate.

**ADR-0003 — Human-gated governance as a first-class layer.** *(2026-06-27)*
- **Decision:** "Machine proposes, human disposes" is enforced by a Governance Layer
  (gates as data states + action authorization + audit), not per-feature goodwill.
- **Reasoning:** Makes "dozens of autonomous agents" safe; centralizes the trust rules.
- **Alternatives:** Convention-only gating (rejected: erodes as agent count grows).
- **Consequences:** Slight extra plumbing per state transition; large payoff in safety,
  auditability, and the ability to autonomize T2 ingestion safely.

**ADR-0004 — Idempotent, resumable, observable agents.** *(2026-06-27)*
- **Decision:** Every agent dedupes on a stable key, checkpoints + resumes, and records
  an observable run. Pattern reference: Agency Discovery (`agency_runs`).
- **Reasoning:** Re-runs are routine; interruptions happen; "if you can't see it, it
  isn't done."
- **Alternatives:** Fire-and-forget jobs (rejected: dupes, silent loss, no audit).
- **Consequences:** A small `runs`/`tasks` substrate to generalize; uniform operability.

**ADR-0005 — SQLite-first, Postgres-ready, portable schema.** *(2026-06-27)*
- **Decision:** Ship on SQLite; keep `db.py` Postgres-capable; no engine-specific
  features in new code; cut over when concurrency/multi-tenancy demands.
- **Reasoning:** Zero-ops self-contained dev/prod now; clean path to scale later.
- **Alternatives:** Postgres-from-day-one (rejected: premature ops); SQLite-forever
  (rejected: blocks multi-tenant concurrency).
- **Consequences:** Discipline to stay portable; a planned cutover (code ready).

**ADR-0006 — Provider seams, null by default.** *(2026-06-27)*
- **Decision:** External deps (payments, email, storage, LLM, search) sit behind
  null-default seams that never raise.
- **Reasoning:** Keeps core testable/offline; features degrade gracefully; swappable.
- **Alternatives:** Direct SDK calls in features (rejected: untestable, brittle).
- **Consequences:** A little interface overhead; large testability/robustness gain.

**ADR-0007 — Manifest-first agent development (`AGENTS.md`).** *(2026-06-27)*
- **Decision:** No agent is built before it exists in `AGENTS.md` (Planned), with
  purpose/inputs/outputs/owner/deps. Status advances as it ships.
- **Reasoning:** As we go 5→50 agents, the manifest is the control panel that prevents
  overlap and orphan agents.
- **Alternatives:** Agents-as-code-only (rejected: no platform-level visibility).
- **Consequences:** One doc to keep honest; huge clarity dividend at scale.

**ADR-0008 — Multi-tenant + UUID-keyed from day one.** *(2026-06-27)* 🟢 *Foundation shipped*
- **Decision:** Introduce a `tenants` table with a single seeded **default tenant**, add a
  `tenant_id` column to **every business table** (defaulted + backfilled to the default
  tenant), and a stable **`uuid`** to **every primary entity** (backfilled for existing
  rows; auto-stamped on insert) — *now*, while still single-tenant. Query-level tenant
  **scoping** is deferred behind a seam (`current_tenant_id()` returns the default
  today; the Auth layer resolves a real tenant later). Integer PKs stay as internal FKs;
  UUIDs are the stable external/cross-tenant identifier.
- **Reasoning:** Retrofitting tenancy is the single most painful database migration a
  SaaS does (it touches every table and query). Making the *columns and conventions*
  exist from the beginning turns "future multi-tenancy" from a redesign into an additive
  change + a seam flip. UUIDs give stable, non-guessable, merge-safe identifiers needed
  for cross-tenant references, external APIs, and identity resolution.
- **Implementation:** Additive and safe — `tenant_id` populated by a constant column
  DEFAULT (existing rows backfilled by the ALTER); `uuid` backfilled via SQL and stamped
  on new rows by a per-entity **AFTER INSERT trigger**, so the ~13 insert helpers were
  **not** touched (uniform coverage, minimal churn). `tenant_id` is indexed on every
  table for future scoping. SQLite-only migration (PRAGMA + triggers); the Postgres
  cutover uses column defaults `gen_random_uuid()` / constant `tenant_id` instead.
- **Alternatives considered:** (a) *Defer tenancy entirely* — rejected: the retrofit cost
  is exactly what we're avoiding. (b) *Enforce tenant scoping in every query now* —
  rejected: pure overhead with one tenant and one operator; risk without benefit until
  Auth exists. (c) *Edit every insert helper to mint UUIDs in Python* — rejected for now:
  more churn/risk across 13 hot functions; triggers give uniform coverage. `new_uuid()`
  exists for app-side minting where explicit. (d) *Integer-only keys* — rejected: not
  safe for cross-tenant/external identifiers.
- **Consequences:** Every row is tenant-stamped and every entity UUID-keyed from v1, so
  multi-user/teams/portals (§12) become a migration + a seam flip, not a redesign. Cost:
  two extra columns + an index + a trigger per entity table, and the discipline that
  **new tables follow the same pattern** (add to `_ENTITY_TABLES` / `_TENANT_ONLY_TABLES`).
  Open follow-ups: wire `current_tenant_id()` to real auth; enforce scoping in
  repositories at that time; validate the trigger approach at the Postgres cutover.

> **ADR process:** propose → discuss → record here with the five fields → implement.
> Significant = changes a boundary, a gate, a shared service, a data-model entity, or a
> cross-module contract. When in doubt, write the ADR.

---

## 14. Architectural Critique & Refinements

*(The CTO's adversarial self-review, as instructed — assumptions challenged, weaknesses
named, refinements folded back in. This section keeps the document honest.)*

**Challenge 1 — "Dozens of autonomous AI agents" is a liability, not a goal.**
Unbounded autonomy contradicts the product's trust promise. **Refinement:** reframed
"autonomous" via the **Governance Layer (§2.1)** and **agent tiers/governance modes
(§4.2–4.3)** — agents are small and many, but autonomy is *bounded by gates*. Agent
count is a means (modularity), never an end. Adopted into ADR-0003.

**Challenge 2 — "AI agents" vs. the "no-LLM-in-the-spine" rule.** The brief says AI
agents; the product says deterministic engines. Left unreconciled this breeds confusion
and scope-creep toward LLM decisioning. **Refinement:** the **three-tier model (§4.2)**
makes most "agents" deterministic engines or connectors, with LLMs explicitly advisory
and seamed. Adopted into ADR-0002.

**Challenge 3 — The TARGET folder tree implies a rewrite the team can't afford.**
Presenting `agents/core/api/...` as the structure risks an implementation agent
"helpfully" restructuring the repo and breaking everything. **Refinement:** §7 now
labels CURRENT vs TARGET, provides an explicit **mapping + one-module-at-a-time
migration**, and ADR-0001 forbids premature service extraction. The doc designs the
destination without authorizing a big-bang.

**Challenge 4 — Microservices everywhere is premature.** Generic "never monolithic"
advice would push us into distributed-systems overhead at single-operator scale.
**Refinement:** distinguished **modular monolith (correct now)** from microservices
(later, demand-driven) — ADR-0001. "Never monolithic" is honored as "never a *ball of
mud*," which is the real intent.

**Challenge 5 — Identity resolution is the silent killer.** Per-store dedupe (§6) does
not stop the *same* org arriving from Discovery, an RFP, and an inbound lead as three
records. At 50 agents this fractures the CRM. **Refinement:** named **Identity
Resolution** as an explicit Shared Service (⚪, §11) distinct from per-store dedupe, and
flagged it as a near-term priority. *This is the #1 thing to build before scaling
ingestion.*

**Challenge 6 — Audit/observability claimed but uneven.** We assert "observable" but
only some flows record runs, and there is no uniform audit log. **Refinement:** §6
specifies an append-only `audit_log`; ADR-0004 generalizes the `agency_runs` pattern
into a platform `runs`/`tasks` substrate. Until then, do not claim full auditability.

**Challenge 7 — Communication standard lacks teeth without a bus.** "Agents talk via
data models" is good, but inline direct calls will quietly couple agents as they
multiply. **Refinement:** §9 stages the path — **direct calls → Task queue → event
bus** — and forbids the cross-agent-internal anti-pattern explicitly. Build the Task
queue before agent count outgrows direct calls.

**Challenge 8 — Multi-tenancy retrofits are notoriously painful.** Adding `tenant_id`
late means touching every query. **Refinement (✅ acted on — ADR-0008, shipped):** rather
than wait for the first second user, the `tenants` root + `tenant_id` on every table +
`uuid` on every entity were built **now**, while single-tenant. The expensive,
touches-everything part (the schema) is done; what remains is wiring `current_tenant_id()`
to real auth and enforcing scoping in repositories — additive work, not a redesign.

**Remaining known weaknesses (tracked, not yet solved):** no formal RBAC; storage on
local disk (durability risk for assets/exports); PDF rendering best-effort; no
search/cache engine; event bus and Task substrate still conceptual; the Postgres
cutover unrun. These are the honest edges of the platform and belong on the roadmap,
not in marketing.

**Net assessment:** with the Governance Layer, the tier model, the CURRENT/TARGET
honesty, identity resolution named, and the staged communication path, this reads as a
**production-grade SaaS architecture with a credible migration backlog** rather than a
prototype's wishlist. The biggest near-term risks are *identity resolution* and the
*Task/audit substrate* — build those before scaling agent count.

---

## 15. Governance of this document

- **This document is authoritative.** Implementation agents and future chats must read
  it (and `AGENTS.md`) before non-trivial work and must not contradict it silently.
- **Amend via ADR.** Architectural changes are proposed as ADRs (§13), then folded into
  the relevant sections. The ADR log is the changelog.
- **Manifest-first.** New agents land in `AGENTS.md` (Planned) before implementation
  (ADR-0007).
- **Keep CURRENT honest.** When code ships, update the status marks here from ⚪/🟡 → 🟢.
  A status mark that overstates reality is a bug to fix.
- **Cadence.** Review at each major milestone (new module, new shared service, the
  Postgres cutover, first multi-user). Stale constitutions are dangerous; this one is
  maintained.

*End of constitution v1.0.*
