# Architecture Decision Record (ADR) — ChordOS

*The permanent log of binding technical/architectural decisions and their rationale.
Read this to understand **why the code is shaped the way it is** before you change
its shape. The Constitution (`CONSTITUTION.md`) states the principles; this document
records the specific decisions that serve them.*

## How to use this log

- Each decision is numbered, dated, and has a **status** (Accepted · Superseded ·
  Reversed). Superseded decisions are kept, not deleted — the history is the value.
- **Before you reverse one of these, add a new ADR that supersedes it** with the
  reasoning and the authority. Do not silently contradict an Accepted decision in
  code; the next contributor will trust this log.
- New binding decisions append here. Tactical, reversible choices do not need an ADR —
  reserve this for decisions that would be expensive or dangerous to reverse blindly.

The entries below were **reverse-engineered from the ratified strategy docs and the
existing codebase (2026-07-02)** to give the historical decisions a durable home.
Their dates reflect when the decision was effectively made; earlier deliberation
lives in the cited `docs/*.md`.

---

### ADR-0001 — A→B→C, dogfood-first go-to-market
**Status:** Accepted (2026-06-16, CEO ruling) · Source: `docs/company-strategy.md`
**Decision.** Build the studio force-multiplier (A) first as deliberate data
manufacturing, then the procurement-intelligence platform (B), then the buyer-side
OS/marketplace (C). Self-funded; each rung funds the next; do not skip A for C's
optics, do not raise on an inflated B TAM.
**Why.** The durable moat is the proprietary data (qualification labels, estimation
actuals, win/loss, the buyer↔creator graph), which is only manufactured by operating
a real studio. B and C are defensible only *after* that data exists.
**Consequences.** Internal-first is the default for every feature. Capital discipline
is a hard constraint. Win/loss capture is mandatory from day one.

### ADR-0002 — Deterministic engines; the web layer adds no business logic
**Status:** Accepted · Source: `src/chordential_oia/`, `docs/build-loop-charter.md`
**Decision.** The mission spine is implemented as pure Python engines (`scoring.py`,
`qualification.py`, `estimation.py`, `strategic.py`, `prepare.py`, `outreach.py`,
`delivery.py`, `matching.py`, …). The FastAPI/Jinja web layer renders and routes; it
contains **no** scoring, qualification, estimation, or decision logic.
**Why.** Determinism makes the business analyzable, testable, and cacheable, and keeps
the cost model legible. It also keeps the engines reusable as the product is exposed
to B/C users without a rewrite.
**Consequences.** Any new business rule goes in an engine with tests, not in a route.
A route that computes a decision is a defect.

### ADR-0003 — "The machine proposes, the human disposes," enforced by the flow
**Status:** Accepted · Source: Constitution §4.1; `web/app.py`
**Decision.** No engine auto-commits a business outcome. Qualify, assign, approve,
publish, release, and send are human actions. Where feasible the gate is enforced by
the route wiring (a strategy must be approved before the composer unlocks; a creator
submission is `pending_version` until a human publishes it), not by convention.
**Why.** Trust, cost control, and honesty all depend on a human owning every outward
or committing action.
**Consequences.** Never add an auto-decide path. When you add a decision surface, wire
the gate into the flow so it cannot be bypassed.

### ADR-0004 — Provider seams: null by default, real when configured, never blocking
**Status:** Accepted · Source: `mailer.py`, `payments/`, `web/webpush.py`, LLM seam
**Decision.** Every external-world dependency (mail, payments, web push/ntfy, storage,
LLM) is a seam with a no-op default and a real implementation selected by a
`CHORDENTIAL_*` env var. Seams are best-effort: they never raise and never block a
request.
**Why.** The product must run end-to-end with zero credentials (dev, tests, demos);
production lights up the seams. A slow or dead provider must never fail a user action.
**Consequences.** New outward integrations follow this shape. Outbound calls that can
block the event loop are offloaded off the request thread (see ADR-0010).

### ADR-0005 — Gated, deterministic AI; no live agent swarm; no AI-generated craft
**Status:** Accepted · Source: `docs/company-strategy.md` (CTO ruling), Constitution §8
**Decision.** LLMs are used only for discrete, cacheable, human-gated steps and only
after a human "pursue" spends money — never an open-ended agent swarm in production,
never before the pursue gate. The core creative deliverable (music) is human-made;
AI never synthesizes the craft.
**Why.** Cost discipline, inspectability, and the honesty constraint. Expensive
generation on unqualified leads is a margin leak; fabricated craft breaks trust.
**Consequences.** Keep expensive generation behind qualification. Label AI assistance
honestly. Do not put an LLM on a hot, ungated path.

### ADR-0006 — Backend-portable storage: SQLite for dev/tests, Postgres for production
**Status:** Accepted (code ready; ops cutover pending) · Source: `web/db.py`,
`docs/zero-downtime-cutover.md`
**Decision.** One DB layer, two backends, selected by the connection string. A
`postgresql://` URL routes through a psycopg shim that adapts placeholder style and
row access so the ~100 query functions are untouched. SQLite remains the dev/test
default.
**Why.** Enables the zero-downtime deploy story (remove the single-attach disk) while
keeping local dev and the test suite fast and credential-free.
**Consequences.** Keep new SQL portable across both backends (the `count_*`/selector
LIKE-marker pattern is portable; avoid backend-specific idioms like `json_extract` on
shared paths). Verify dbperf changes on both backends before relying on
backend-specific semantics (e.g. `rowcount`/`RETURNING`).

### ADR-0007 — Migration-safe, additive schema
**Status:** Accepted · Source: `web/db.py` (`_*_COLUMNS` dict + `ALTER TABLE` loop)
**Decision.** Schema evolves by adding columns to the `_*_COLUMNS` map and the
`ALTER TABLE` migration loop (fresh DBs get the full `CREATE TABLE`; existing DBs are
migrated in place). No destructive migrations; old databases upgrade without data loss.
**Why.** The production database holds real pipeline and payment records; migrations
must be non-destructive and safe to run on every boot.
**Consequences.** Add columns; don't drop or rewrite. Per-record editable state uses
the JSON-blob pattern (`doc_overrides`, `delivery_json`) with merge-one-key helpers.

### ADR-0008 — Fail-soft; hostile work runs in killable, out-of-process workers
**Status:** Accepted · Source: `web/_enrich_worker.py`, `web/scheduler.py`
**Decision.** Parsing hostile external pages (enrichment) runs in a separate,
killable subprocess with a hard timeout and a watchdog. A runaway parse dies alone;
the web server is never frozen. Any queue that re-selects the earliest unresolved item
must mark a crashed/timed-out item terminal so it can't wedge the queue forever.
**Why.** A pathological page can drive a C-level regex into a runaway that holds the
interpreter lock and cannot be interrupted from a thread — in-process that is the
"wheel of death." Out-of-process is the only real cure.
**Consequences.** Any new hostile-input processing follows the killable-worker
pattern. Queue selectors advance past terminal (error) items. (The auto-fetch/discovery
path is a known remaining in-process parser — see PROJECT_STATE deferred items.)

### ADR-0009 — Human-gated discovery crawler ("machine proposes where to look")
**Status:** Accepted (2026-06-17, CEO override of the earlier no-scraping stance) ·
Source: `docs/company-strategy.md`
**Decision.** ChordOS may crawl for discovery (demand and supply) under strict
governance: the system deterministically *proposes* targets; a human explicitly
approves each; only approved targets are fetched; results land in a review queue as
Pending. Public pages only, robots.txt respected, rate-limited, identified UA,
fail-soft, PII delete path, behind an env flag.
**Why.** Preserves the moat as *curation and qualification* (not volume) while
allowing real discovery. Supersedes the blanket "no mass scraping" line for the gated
crawler only; unsupervised mass scraping remains rejected.
**Consequences.** No crawl auto-enters the pipeline or the matchable roster. The human
gate is the whole point — do not automate past it.

### ADR-0010 — Never block the event loop; offload outbound I/O
**Status:** Accepted (2026-07-02) · Source: `web/app.py`, product-efficiency audit
**Decision.** `async def` route handlers must not perform blocking network I/O
(SMTP/push loops). Such work is offloaded (`run_in_threadpool`) or fired off the
request thread (`signals.fire_and_forget`). uvicorn runs one event loop; a blocking
send would stall every user, including health probes.
**Why.** A single slow provider inside an async handler is a full-site outage window.
**Consequences.** Best-effort notifications are fire-and-forget; blocking sends in
async handlers are threadpooled. New outbound I/O follows this rule.

### ADR-0011 — Token-gated public surfaces, separate from the admin gate
**Status:** Accepted · Source: `web/app.py` (`_is_public_path`, `_REVIEW_ACTIONS`)
**Decision.** Client and creator surfaces (first-touch, delivery portal, creator
portal, review actions) are reached by an unguessable per-record token validated in
the route, and are exempted from the internal admin login gate. The exemption list is
derived from a single source so it cannot drift from the actual routes.
**Why.** External users must reach their surfaces without an internal login, while the
internal dashboard stays gated. A drift between the exemption and the routes silently
bounces real clients to the admin login (this happened; ADR records the fix).
**Consequences.** New client/creator routes token-validate in-route AND are added to
the single exemption source. Never gate a token surface behind the admin login.

### ADR-0012 — One source of truth for legally-/operationally-material copy
**Status:** Accepted (2026-07-02) · Source: `delivery.py` (`CONTENT_ID_HONEST`, cert),
product-efficiency audit
**Decision.** Legal and rights copy shown to clients has exactly one home (a constant
on the cert object / a module constant) and is referenced by both the browser-rendered
document and the ZIP's self-contained document. The delivery ZIP builders remain
stdlib-only (no Jinja) so the package builds without the web extra.
**Why.** For a procurement-grade product, the paperwork the client downloads must not
diverge from the document they reviewed. Duplication of legal copy is a real
credibility/legal exposure.
**Consequences.** Never re-hardcode a legal sentence in a template; reference the
constant. Keep the stdlib-only constraint on the ZIP path.

### ADR-0013 — Campaign Intelligence is anchored to the Opportunity; the Campaign inherits it
**Status:** Accepted (2026-07-03, Jon) · Source: `campaign_intelligence.py`,
`campaign_intake.py`, `docs/campaign-intake-prd.md` §18
**Decision.** A Campaign Intelligence record is born on and anchored to the **Opportunity**
— the stage where the discovery call, RFP, and qualification actually happen — not on the
Campaign (which exists only after Won). Campaign Intake ("Update Intelligence") is a
first-class component of the Opportunity page. When an Opportunity converts to a Project,
the existing CI is **adopted in place** (its `campaign_id`/`project_id` are set on the same
row) — nothing is recreated or re-entered. The lifecycle is:
`Lead → Opportunity → Campaign Intake → Campaign Intelligence (living) → Proposal → Won →
Project → Campaign Workspace`, with one CI carried unbroken across the Won boundary.
**Why.** The most valuable, most-refined intel is gathered *while qualifying and pursuing*,
not after the deal is won. Anchoring CI to the Campaign stranded intake behind the Won gate
and forced re-entry. Anchoring to the Opportunity makes the Opportunity the single working
source of truth throughout the sales process, and makes "inherit, never recreate" (§7 of
CAMPAIGN_INTELLIGENCE.md) literal.
**Consequences.** CI is keyed by `opp_id` first; `ci_for_opportunity` / `ensure_for_opportunity`
are the entry points; `ensure_for_campaign` **adopts** the opp's CI rather than creating a
new one. A **human edit is authoritative** — it sets the field value, marks it human-owned,
and a later machine contribution to a human-owned field never overwrites it: it lands as a
*proposed* value surfaced as a conflict for the operator to resolve (machine proposes, human
disposes, §4.1). Confirmed engagement facts (budget/deadline/discipline) **write back to the
Opportunity's own columns**, so every downstream engine (qualification, estimate, brief,
outreach) recomputes from the same source with no separate "refresh."

### ADR-0015 — The Meeting is the business object; providers sit behind two seams
**Status:** Accepted (2026-07-03, Jon) · Source: `meetings/` (base/null/zoom/recall),
`web/meetings_service.py`, `campaign_intake.ingest_transcript`, `docs/discovery-call-intake-design.md`
**Decision.** A **Meeting** is a first-class domain object; hosting it (Zoom/Meet/Teams) and
capturing it (Recall.ai/Zoom AI Companion/Fireflies) are **two independent provider seams**,
null by default. The chain is `Meeting → MeetingProvider → CaptureProvider → Transcript →
Campaign Intake → Campaign Intelligence`. Everything downstream consumes the **Meeting** and a
**normalized Transcript** — never a provider-specific event. Provider webhooks are normalized
into domain **MeetingEvents** (`transcript_ready`/`failed`/…) in exactly one place (the
provider's `parse_webhook`); `campaign_intake.ingest_transcript(meeting, transcript)` is the
boundary and knows nothing about Zoom or Recall.
**Why.** The meeting is what the business cares about; a vendor is an implementation detail.
Coupling Campaign Intelligence or Campaign Intake to Zoom/Recall would make every future
provider a pipeline change. Abstracting at the Meeting keeps the intelligence pipeline stable
while providers come and go.
**Consequences.** New providers touch only their seam file (`meetings/zoom.py`,
`meetings/recall.py`, …) plus the env selector — never Campaign Intake or Campaign Intelligence.
Seams are null-by-default (ADR-0004): with nothing configured a Meeting is still real
(scheduled manually, transcript via the paste lanes) and the notetaker honestly reads "not
connected." The capture webhook (`/webhooks/capture/{provider}`) is signature-verified in the
provider parser, idempotent, and non-blocking (offloaded); a scheduler tick is the fetch-later
fallback and is fully gated (no-op without a provider). Transcripts land as **proposed** CI
fields (machine proposes, human disposes, §4.1); confirmation propagates downstream (ADR-0013).

### ADR-0016 — Clients REQUEST; the operator SCHEDULES; one Meeting Scheduler, two initiators
**Status:** Accepted (2026-07-03, Jon) · Source: `web/meeting_scheduler.py`, `meetings/` seams,
`docs/discovery-call-intake-design.md` §7bis, `docs/discovery-setup-guide.md`
**Decision.** Clients **do not book onto the operator's calendar**. The Campaign Brief ends with
**"Request a Discovery Call"** → a lightweight form (name, email, company, preferred type
**Zoom | Phone**, optional message) that creates a **Discovery Request** attached to the
Opportunity and notifies the operator. It schedules nothing. The **operator** then reviews the
request and, on accept, drives the **Meeting Scheduler** (pick type + date + time). The scheduler
is the ONE engine, reached two ways — **from a client request** or the operator's **"Schedule
Discovery"** on any Opportunity (referrals, conferences, inbound calls). The only difference is
who initiated it. By type: **Zoom** → create the Zoom meeting, arm Recall, send the calendar
invite, associate the Meeting with the Opportunity; **Phone** → a phone Meeting record + a
confirmation email, **no Recall**. Everything external (Zoom, Recall, Calendar, email) sits
behind a null-by-default seam.
**Why.** The operator must stay in control of their calendar — clients requesting (not booking)
removes double-booking and calendar-exposure risk, keeps the human decision ("the machine
proposes, Jon disposes"), and still means the client never has to email asking for a time. One
engine for both initiators keeps request-driven and manual scheduling identical downstream.
**Consequences.** A `discovery_requests` record is the client's ask; a `meetings` record is the
scheduled call (typed `zoom`|`phone`, linked back to its request + Opportunity, with client
identity and who initiated it). Phone meetings never arm Recall. **Campaign Intelligence and
Campaign Intake stay provider-agnostic** — they receive only Meeting events (ADR-0015); the
Scheduler is the only place Zoom/Recall/Calendar are orchestrated, so a new provider touches only
its seam file. With nothing configured the Scheduler degrades honestly: Zoom/Calendar/email/Recall
no-op and the operator still gets a real Meeting record (manual link, "not connected"). The
optional availability engine (`meetings/availability.py`) is an operator-side conflict check, not
a client-facing calendar.

### ADR-0017 — Campaign Intelligence is the single source of truth for every artifact
**Status:** Accepted (2026-07-07, operator directive) · Source: `capabilities.py`,
`web/campaign_intelligence.py`, `web/app.py` (brief/compose routes)
**Decision.** Once Campaign Intelligence exists for an Opportunity, no downstream artifact may
regenerate its content from stock templates. Every artifact — Campaign Brief, email preview, PDF,
proposal, and future production documents — renders **CI first**, engine/template content only as
fallback for slots CI does not yet fill, with `doc_overrides` reserved for presentation-only
concerns (chip visibility, links, uploads, template pick). Editing an artifact field that maps to
a CI canonical slot writes **to CI** (`edit_or_create`), never to a parallel copy; the artifact
then re-renders from the updated intelligence. Sending an artifact freezes a **snapshot** of the
rendered content; the recipient sees the snapshot, not a live re-render.
**Why.** The product's philosophy is an operating system where information flows forward from
discovery. Duplicate copies (template regeneration, page-local edit blobs) made the brief read
like marketing collateral that forgot the meeting, and made operator edits silently revert. One
canonical store means the operator never re-enters information; every screen already knows what
happened in the meeting.
**Consequences.** The brief builder takes a `ci` view and prefers it slot-by-slot; blanking an
override reverts to *CI-derived* content, never to stock copy. "Email This" persists a
`brief_snapshots` row and mails a link that renders that snapshot verbatim. New artifact surfaces
must consume `fields_view`/canonical CI rather than re-deriving from opportunity columns. When CI
changes, downstream artifacts pick it up on next render because nothing caches template output.
Scheduling writes a CI event (the Opportunity timeline) so meetings are part of the same record.
Client-facing times render in **America/New_York** (correct EST/EDT label via zoneinfo) — UTC is
storage, never display.

### ADR-0018 — The Client Workspace is the durable destination; commitment is a first-class lifecycle layer
**Status:** Accepted (2026-07-07, operator directive — the "ten principles") · Source:
`web/app.py` (opp `share_token` brief + project `share_token` delivery portal), `capabilities.py`,
`docs/client-workspace-principles.md`
**Decision.** A client relationship has exactly ONE durable, token-gated destination — the
**Client Workspace** — and its URL never changes across the lifecycle. The workspace token is
minted once and **inherited forward**: the opportunity mints it, the project it becomes inherits
the same token, so `/workspace/{token}` resolves the same deal from first contact through archive.
The workspace's *contents* change by **phase** — a single computed lifecycle state
(`intro → discovery → brief → commercial → kickoff → production → delivery → archive`) — but the
destination does not. A **Commercial Commitment layer** sits between the Campaign Brief and
Production: a **Commercial Review** generated entirely from Campaign Intelligence (scope, pricing,
deposit, payment schedule, producer-voiced terms, procurement checklist), whose **client approval
is the primary award trigger** — the machine prepares, the human commits, and that commitment (not
an operator button) advances the state. A **Kickoff** phase follows approval and precedes
production ("here's how we'll work together": contacts, cadence, revision/delivery expectations,
team, escalation). **Approval is captured electronically in the workspace by default** (name,
email, timestamp, IP, user-agent, and the approved scope/pricing/terms snapshot = the audit
record); DocuSign is an *optional* path only when a client's procurement requires it. **Procurement
is adaptive capture, never integration** (ADR aligns with the seam philosophy): ChordOS discovers
how each organization buys (PO / vendor portal / Coupa / Ariba / Oracle / W-9 / COI / ACH /
procurement contact) as CI facts and **generates the artifacts**, rather than connecting to P2P
suites. The **PDF is demoted to a downloadable artifact** rendered from the workspace; the
workspace is the product.
**Why.** The product is not proposal/CRM/PM/procurement software — it is the operating system for
the entire lifecycle of a commercial music engagement, and the Constitution's promise that the
business *compounds over time* only holds if the client has one home that grows rather than a
series of systems they are handed off between. Two tokens and a URL that changes at award
(opportunity brief → project portal) directly break "one link, forever." Operator-button state
advance inverts the intended causality: the client's commitment should move the work forward.
**Consequences.** New client-facing surfaces resolve under `/workspace/{token}` and route by the
computed phase; the phase engine is the single answer to "where is this deal," and downstream
features (commercial, kickoff, production, delivery) are *views* of the workspace, not separate
destinations. The project **must** inherit the opportunity's `share_token` at creation (never mint
a fresh one) so the URL survives award. Everything renders from Campaign Intelligence (ADR-0017);
the commercial section currently embedded in the Brief migrates to the Commercial Review (the Brief
answers "what are we making," the Review answers "what are we agreeing to"). Approval writes an
immutable, snapshot-anchored audit record and a CI event, and transitions phase into Kickoff.
**Campaign Intelligence accumulates into Relationship Intelligence**: CI must not die with a
campaign — creative/communication/revision/budget/decision-maker/procurement/rights history rolls
up to the client so future campaigns begin with accumulated knowledge. The durable token is
per-deal today; its north star home is per-*client* (a relationship with many campaigns under one
workspace), and the token-resolution layer is built so that promotion is a later ADR, not a
rewrite. Manual operator controls remain as fallbacks everywhere, but the primary path is
client-driven.

---

## Adding a new ADR

Copy the template. Keep it short — the decision, the why, and the consequences a
future contributor must honor.

```
### ADR-NNNN — <short title>
**Status:** Accepted (<date>, <authority if strategic>) · Source: <files/docs>
**Decision.** <what was decided, in the imperative>
**Why.** <the reasoning that must survive>
**Consequences.** <what future contributors must do / not do>
```
