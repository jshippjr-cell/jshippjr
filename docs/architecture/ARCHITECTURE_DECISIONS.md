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

### ADR-0014 — Captures are the one evidence envelope (reconstructed entry)
**Status:** Accepted by practice; entry reconstructed 2026-07-18 (governance repair) ·
Source: `web/intake_lanes.py`, `captures` table in `web/db.py`, `campaign-intake-prd.md` §19,
`EXTRACTION_ENGINE.md`, PROJECT_STATE "Intake framework (Increment 1)"
**Decision.** Every intake lane (discovery call, producer debrief, meeting notes,
transcript, RFP, email thread, client brief) normalizes to ONE immutable **Capture
envelope** (`captures` with lane / provenance_source / opp_id / metadata / artifact /
external / status) and funnels through ONE shared pipeline; every CI field and event cites
its raw-evidence `capture_id`.
**Why.** One envelope means one pipeline, one provenance trail, and no privileged lane —
"why did this change?" is always answerable from the capture it cites.
**Consequences.** New input modalities are new LANES over the same envelope, never new
pipelines. *Governance note:* this ruling was cited by ADR-0021/0023 and the extraction
design but its log entry was missing (the log jumped 0013→0015); this entry reconstructs
it from the shipped system so the log no longer references a ruling it doesn't contain.

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

*Implementation note (P0 completion).* Stage surfaces fold into the workspace via the
**stage-partial pattern**: one shared template partial holds the stage's markup (the brief lives
in `_brief_document.html`, its CSS in static `brief.css`), rendered in two frames — the standalone
route wraps it in its own `<html>` + operator toolbar (kept for backward compatibility, operator
edit, and PDF); the workspace includes the *same* partial inline (`embedded=True` suppresses the
standalone threshold cover). One source of markup, two frames — the pattern every later stage
(Commercial Review, Kickoff) follows. Corollary on snapshots: the workspace always renders **live**
CI (the relationship grows, nothing resets), so a send-time brief snapshot is no longer how a
client *views* the brief — it is the **approval/audit record and the PDF source** (its real job in
Phase 3). Legacy emailed `?v=snapshot` links keep rendering the frozen doc on the standalone route.

### ADR-0019 — The Production OS: the Direction→Version spine, the court-state, and the round ledger
**Status:** Accepted (2026-07-08) · Source: `docs/production-lifecycle-model.md` (the agreed
business model), existing machinery in `delivery.py` / `delivery_json` / `review_comments`
**Decision.** Production is built on the EXISTING version machinery, not a parallel one: the
`delivery_json['versions']` ladder remains the Version chain; `review_comments` remains the
feedback tape; the creator publish gate remains the taste gate's seam. On top of it, three
first-class pieces of state land in the same per-project blob (house JSON pattern, no new
tables): **`directions`** (the creative territories — name, thesis/hero element, status
exploring|selected|rejected with a rejection *reason*; versions stamp a direction id),
**`round_log`** (one entry per change-request round: when, by whom, the note, against which
version — the ledger behind the flat `revisions_used` counter, which stays as the total), and
**`creative_lock`** (`{version_n, at, by}` — the gate that ends the revision economy; changes
after lock are scope/conform conversations). The **court-state** is *computed, never stored*:
every project is always in exactly one of `client` / `studio` / `scheduled` (derived from
pending_version, delivery state, and lock), each with an age — and the Workspace's PRODUCTION
phase renders it in the concierge voice ("Version 2 is ready for you" / "We're composing —
nothing needed from you"). The delivery portal remains the listening/feedback room; the
workspace is the calm layer above it.
**Why.** The agreed model (production-lifecycle-model.md): the Version is the atomic unit of
production; Direction preserves the creative journey for Relationship Intelligence; the round
has contractual meaning; and the ball-in-whose-court state is the operational form of "what
uncertainty did we remove." Philosophy is stable — implementation over abstraction; each of
these three earns its place by replacing something implicit and load-bearing (labels, a bare
counter, inference) with something honest.
**Consequences.** No new SQL tables; `revision_status()` and the review/changes route feed the
round_log; "Direction-lock"/"FINAL" version *labels* stay for display but the lock is a
record, not a string. The client-facing production experience must always answer the court
question first. Deferred deliberately (not lost — see the model doc): the reconciliation
round-clock rule, the two calendars, fidelity calibration, person-anchored RI migration.

### ADR-0020 — One commercial approval; the invisible Executive Producer
**Status:** Accepted (2026-07-08, operator directive) · Source: the end-to-end walkthrough audit
**Decision.** The sales flow has exactly ONE commercial commitment. Sequence: discovery call →
CI generated (no client interaction) → **Discovery Summary** ("what we heard" — the client's
FIRST touch, introducing their permanent Workspace URL; no pricing, no terms, no deposit; one
action: *"Yes, this reflects our project"* + comments) → confirmation advances the workspace
and notifies the operator → operator reviews and **releases the proposal** (the Commercial
Review) → the client's single approval (scope · pricing · timeline · terms) is the award →
Kickoff, automatically, with nothing further from anyone. Supporting rules: (1) **operator
actions collapse** — Assign Composer is one decision that automatically mints the portal,
sends the email with brief/deliverables/timeline, logs, and notifies; (2) **Directions are
born in Discovery** — CI seeds them; production inherits; no one creates or renames them
later; (3) **Creative Lock is a state, not a button** — recorded automatically when the
client approves a version; (4) **email is the notification layer, the Workspace is the
truth** — every lifecycle event notifies the right person and points them to their permanent
URL; (5) **one obvious Next Action per deal** for the operator (decision-oriented, not
page-oriented); (6) hide the operating system: portal generation, workspace creation,
notification dispatch, lifecycle transitions are ChordOS's job, never the human's. Benchmark:
Apple/Linear/Superhuman/Frame.io — one thoughtful decision, twenty quiet operations.
**Why.** The walkthrough exposed two approval moments where the business has one, and an
operator forced to navigate eight rooms and remember system logistics. The client already got
the court-state courtesy; the operator and the flow itself must get it too.
**Consequences.** The brief stage is renamed Discovery Summary and carries a scope-confirm
gate (per-opp state + CI event); the commercial phase opens on confirmation (with a
"preparing your proposal" state until release); the approval records timeline consent; the
directions add/rename UI and the lock button are removed; releases/approvals/confirmations
send workspace-pointing emails. Test seams may keep internal routes; UI never shows them.

### ADR-0021 — The Producer Learning System: EP-completeness extraction, Observed Facts, and the learning ledger
**Status:** Accepted (2026-07-08, operator directive) · Builds on ADR-0013/0014 (Campaign Intelligence + captures)
**Decision.** Three changes to how a discovery transcript becomes Campaign Intelligence, so
ChordOS gets better at discovery after every campaign — not by fine-tuning, not by vector
memory, but by learning what an Executive Producer consistently values.
(1) **EP-completeness extraction.** The extraction prompt (`_build_extraction_prompt`) now
reads the transcript as an experienced EP — "if I walked out and had to brief my team, what
would I write down?" — optimizing for COMPLETENESS over minimality, enumerating every relevant
field across all facets, merging multiple statements into richer values, and — when confidence
is medium/high — PROPOSING the fact, but when low, emitting a follow-up `open_question` rather
than staying silent. `max_tokens` 1600→4000; the coerce cap 50→150.
(2) **Observed Facts scratchpad.** A new open facet `observed` — the EP's working memory —
holds every meaningful observation that has no dedicated slot yet (facet added to `FACETS`/
`FACET_LABEL`, peeled into an `observed` bucket in `fields_view`, rendered as its own block on
the CI panel). Ambition is no longer gated by the schema; facts can graduate into first-class
slots later without losing the original observation.
(3) **The Producer Learning ledger** (`web/producer_learning.py`, `producer_learning_event`
table). Every operator disposition of a proposed field — confirm / edit / reject / add — is
recorded with the AI's original value, the final value, edit distance, confidence, and the
capture citation. Those events roll up into a transparent, count-based per-field **prior**
(`field_prior` → stance trusted|expand|contested|learn) that `priors_summary` renders into the
next extraction prompt: fields the producer always confirms are proposed confidently; fields
they consistently expand get the fuller read; fields the AI keeps missing (added-from-nothing)
get actively watched; fields they keep rejecting are demoted. Priors are global (the producer's
consistent taste across campaigns), advisory, and never block capture.
**Why.** The extractor was too conservative — only the easy entities. A producer listens for
everything that changes how a campaign is planned, staffed, priced, scheduled, delivered, or
approved. And the governing law made literal: the machine proposes, Jon disposes, and the
machine learns from the disposition — auditable, reversible, not a black box.
**Consequences.** No destructive schema change (one new facet, one new table, both additive).
The four CI disposition routes now log learning events. Per-fact speaker/timestamp/verbatim-
span is still capture-level only (deferred — would need columns threaded from
`TranscriptSegment`). The deterministic no-LLM fallback is unchanged (still ≤5 fields); EP-
completeness is an LLM-path gain.

### ADR-0022 — Procurement Intelligence: ChordOS prepares clients for procurement (it never integrates)
**Status:** Accepted (2026-07-08, operator directive) · Phase 5 of ADR-0018 · Builds on ADR-0013/0021
**Decision.** The governing principle: **ChordOS does NOT integrate with procurement systems —
it prepares clients for procurement, as an intelligent coordinator.** Never build for Ariba/
Coupa/Oracle/SAP/Jaggaer. Five parts, all provider-agnostic (`web/procurement.py`):
(1) **Discovery, never hardcoded.** Requirements are DISCOVERED from Campaign Intelligence (the
EP extractor's `procurement_requirements` fact + any procurement signal in captures) and
normalized against a known VOCABULARY (~23 types: W-9, ACH, COI, NDA, MSA, PO, Net-30/60,
vendor portal/code/registration, security questionnaire, diversity, banking, tax docs,
compliance, procurement/AP/legal contacts, company overview). Two clients get two different
checklists because they said two different things; a client who mentioned nothing gets none.
(2) **The Company Profile** (`company_profile`, one row) — legal name/DBA/addresses/EIN/bank/
remittance/insurance/contacts/website/capabilities/NAICS/UEI/DUNS — entered ONCE, the source
for every generated document.
(3) **The Document Generation Engine** — deterministic artifacts from the profile (W-9, ACH
auth, remittance, banking, vendor profile, company overview, cover letter, vendor info,
contact sheet). When ChordOS can't legally auto-produce a document (COI, MSA, NDA, security
questionnaire), it generates a **professional placeholder requesting the missing info** —
never a fake official form.
(4) **The Procurement Workspace** — an adaptive checklist grouped by category, per-requirement
Generate/Upload/Replace/View/Mark-complete/Waive, a readiness ring, and — when a vendor portal
is required — a guided **"upload these to the client's portal"** action (docs, missing, order,
ETA), never an integration. Every action lands in a `procurement_event` audit timeline.
(5) **Learning.** On completion the requirement set is snapshotted to `client_procurement_history`;
a future campaign for the SAME client pre-loads it (`seed_from_history`) — onboarding compounds.
The Kickoff checklist and Commercial Review consume this real state, replacing their hardcoded
"Nothing required" placeholders.
**Why.** Procurement was a stub ("Phase 5 captures + fills this"). It's first-class studio
work — and the scalable version is capture → adapt → generate, not enterprise P2P integration
(which would kill a boutique studio's OS). A specific connector only ever slots behind a seam
if a real customer's money forces it (payments/calendar/Recall pattern).
**Consequences.** Additive schema (4 tables). Requirements discovered on workspace/Kickoff
load (idempotent). e-signature (DocuSign) stays deferred behind its seam. Per-fact provenance
is capture-level. The Company Profile stores sensitive fields (EIN/bank) for the studio's own
document generation only.

---

### ADR-0023 — The Campaign Intelligence Extraction Engine: an orchestrated specialist crew, not one prompt
**Status:** Accepted (2026-07-11, operator directive) · Source: `src/chordential_oia/extraction/`, `web/extraction_bridge.py`, docs/architecture/EXTRACTION_ENGINE.md · Builds on ADR-0013/0014/0021
**Decision.** Extraction into Campaign Intelligence is an ORCHESTRATED SYSTEM, not one
prompt: ten independent domain specialists (budget, timeline, deliverables, stakeholders,
creative, campaign, rights, technical, opportunity, risk) each read EVERY available
artifact (transcript, notes, metadata, RFP, brief, opportunity + relationship intel,
prior captures) and extract only their domain, in parallel; a deterministic validation
pass dedupes, surfaces conflicts as flagged `confirm_*` open_questions (ambiguity
preserved as `value_json.alternates`, never guessed away), and drops impossible values; a
Recall Auditor re-reads the artifacts against the full inventory ("what was missed?") in
a bounded loop until dry; a deterministic merge folds everything — evidence, speakers,
timestamps, source artifacts, corroboration — into the EXACT candidate shape intake
already writes. The board is never redesigned: every fact enters through
`campaign_intelligence.contribute` via the capture envelope, steered onto the existing
canonical keys, landing OPEN for the human gate; per-fact evidence rides in `value_json`;
the structured run report is preserved on the capture (`metadata.extraction_run`). The
engine package is PURE (no DB/web imports); `web/extraction_bridge.py` is the impure
edge; `campaign_intake._apply_capture`'s existing LLM seam is the single integration
point. Null provider → the engine steps aside entirely (single-prompt seam, then
deterministic heuristics — regression-pinned). The Producer Debrief lane is excluded by
design: it is subjective, kinds-only (§2bis); fact-hunters would launder interpretation
into fact. The engine never writes downstream documents.
**Why.** Every downstream module (brief, proposal, estimate, cue sheet, rights, timeline,
CRM) reads only the board, so extraction RECALL is the ceiling on the whole OS — a missed
budget/rights/deadline fact costs more than the ~10× token multiple of specialist
fan-out. One generalist prompt plateaus; specialists with a domain fence, an adversarial
recall pass, and deterministic (testable, free, honest) validation/merge maximize what
reaches the board while the human disposition gate keeps it safe.
**Consequences.** New domains = append one `WorkerSpec`; new artifact sources = one block
in the bridge. Validation/merge stay deterministic — any future LLM adjudicator must be
proposal-only. Env: `CHORDENTIAL_EXTRACTION_ENGINE` (kill switch),
`CHORDENTIAL_EXTRACTION_MODEL`, `CHORDENTIAL_EXTRACTION_RECALL_ROUNDS`,
`CHORDENTIAL_EXTRACTION_WORKERS`; honors `CHORDENTIAL_INTAKE_LLM=0` and requires
`ANTHROPIC_API_KEY`. Cost guards: bounded artifact bundle, bounded recall, pool-capped
parallelism. Never block a capture: provider/worker/recall failures degrade to the
existing extractors and are recorded in the run report.

### ADR-0024 — The supply-side floor: no assignment without an executed agreement + rate
**Status:** Accepted (2026-07-18, founder ratification of company-architecture Amendment
A-3, hard block) · Source: `web/db.py` (`talent_assignment_blockers`,
`set_talent_agreement`, `agreement_executed_at`/`agreement_ref` columns), the two assign
routes in `web/app.py`, `docs/company-architecture.md` §17
**Decision.** A creator may not be assigned to a project until a standing **Composer
Agreement is executed** (`talent.agreement_executed_at`) **and a rate is on file**
(`talent.rate`). Both assign paths (`/project/{id}/assign`, `/matchboard/assign`) refuse
server-side, before any side effect, and surface an actionable banner naming the creator
and linking the fix. The demo seed models the compliant state for approved creators.
**Why.** The client-facing rights certificate warrants a clean chain of title; that chain
begins at the composer's rights conveyance. An assignment without an executed instrument
makes the company's hero claim unenforceable — the talent council's finding ("money flows
IN only") named this the moat's missing legal floor. This is the second machine-enforced
gate (after the payment gate on release): both are receipts of promises, not creative
decisions, so blocking is consistent with §4.1 (the machine refusing to let a promise be
broken is not the machine deciding).
**Consequences.** Never add an assign path that skips `talent_assignment_blockers`. The
queue surfaces approved-but-unsigned creators as floor gaps. When counsel's real agreement
template lands, `agreement_ref` points at the executed instrument; the gate's shape does
not change.

### ADR-0025 — One composer token; every engagement gets its own door (?p)
**Status:** Accepted (2026-07-19) · Source: `web/app.py` creator_portal route,
`creator_portal.html` roomnav, `docs/design/chordos-studio-experience.md` §2
**Decision.** A composer has ONE portal token. Their Session Rooms stack on one page
sorted **needs-me-first** (rooms owing the composer work → in-motion → delivered), and
each engagement is individually addressable as its own door via `?p=<project_id>` —
the link the award email carries. Deep links compose (`?p=…&t=…`).
**Why.** The spec's "three engagements get three doors, not a portfolio manager" is
about *experience*, not credentials: separate tokens per engagement would multiply
links to lose and revoke. One token + per-room doors + needs-first ordering delivers
the same focus with one credential. Both persona reviewers validated the stacked page
for a multi-gig week; keyboard scoping (nearest room owns the keys) is the accepted
mechanism.
**Consequences.** Award emails link `?p=`; never mint per-project composer tokens;
any future room-level feature must work in both the stacked and single-door views.

### ADR-0026 — Video storage: local disk + capped DB mirror until object storage
**Status:** Accepted (2026-07-18) · Source: `web/app.py` (`_store_picture`,
`_read_capped`, `_persist_upload`), `docs/design/chordos-studio-experience.md` §12
**Decision.** The Picture phase ships on the EXISTING storage seam — uploads land on
local disk (`CHORDENTIAL_UPLOAD_DIR`), with a DB blob mirror ONLY for files
≤ 64 MB (`CHORDENTIAL_CUT_MIRROR_MB`); larger cuts are disk-only. Cuts are capped at
512 MB (`CHORDENTIAL_CUT_MAX_MB`), references at 128 MB, both read in 1 MB chunks
(`_read_capped`) so an oversized body never buffers unbounded. Durable object storage
(S3/R2) stays DEFERRED; when it lands it replaces the disk path behind
`_persist_upload` without changing routes, templates, or the mirror policy.
**Why.** The experience spec named object storage as this phase's infrastructure
price, but a solo-founder deploy on Render with a persistent disk already survives
restarts, and the DB mirror was silently ballooning SQLite with video blobs — the
64 MB mirror cap keeps the rehydrate safety net for briefs/audio while excluding
exactly the payloads that break it. Re-deferring with caps is honest fail-soft
(Constitution: defer what can't be done well); re-deferring silently was the sin —
this ADR is the record.
**Consequences.** Do not raise the mirror cap to accommodate video — flip to S3/R2
instead (the seam is `_persist_upload`/`serve_upload`). Any new upload route must go
through `_read_capped` with an explicit cap and the extension policy
(`_VIDEO_EXTS` whitelist for cuts, `_REF_BLOCKED_EXTS` blacklist + inline-serving
allowlist for everything else — the stored-XSS fix in `serve_upload` depends on it).
Prod backups must include the upload dir, not just the DB, until object storage.

### ADR-0027 — The Cue Layer: cues + hits as a delivery_json blob, per-cue human approval
**Status:** Accepted (2026-07-19) · Source: `web/db.py` (cue helpers), `web/app.py`
(`/delivery/cues/*` routes, creator/console views), `creator_portal.html`,
`delivery_console.html`, `docs/design/chordos-studio-experience.md` §Phase 3
**Decision.** Scoring cues live as `delivery_json['cues']` — a per-project list of
`{id, code, name, t_in, t_out, direction, state, hits:[{id,t,name}]}` — mirroring the
`references`/`pending_assets` blob pattern rather than new tables (CLAUDE.md: "mirror
this for new per-record editable state"). A cue's `state` runs
`open → take → published → approved`; **every advance, including approval, is a
human button press** (Constitution §4.1) — the machine never self-approves a cue.
Timecodes accept `m:ss` / `h:m:s` / raw seconds through one guarded parser
(`_num_or_none`, finite + non-negative + a 24h sanity cap). Conform surfacing is
**anchored to the cue that changed**: the console tags each timecoded change request
with the cue its timecode falls under (`cue_for_time`) and names the cues the current
cut touches (`cues_touched_by_cut`, span overlap; whole-timeline recut → all cues), so
the operator classifies conform-vs-revision against the cue that moved, not from
memory. Cue mutations are serialized through `_mutate_cues` (an `BEGIN IMMEDIATE`
critical section) so concurrent writers can't lose an update or land an approval on
the wrong cue. The composer
gets the cue list **read-only**: regions + hit diamonds on the spine (state as border
weight, not color noise) and a readable direction list in the Brief; Jon owns the
list. Fail-soft: no cues → the audio-and-notes room, unchanged.
**Why.** The blob pattern keeps cues additive, per-project, and editable with zero
schema migration and no new join surface — the same reasoning that put picture,
references, and pending assets on `delivery_json`. Cue approval is modeled as its own
state (not folded into the per-deliverable approval records) because a cue and a
deliverable are different objects: a cue is a span of the picture the music honors, a
deliverable is a file the client signs off. Conflating them would make "approve m02"
and "approve the TV mix" the same row, which they are not.
**Consequences.** New cue mutations go through the `db.py` cue helpers (never write
`delivery_json['cues']` inline) so the timecode guard and id assignment stay in one
place. The legacy `/delivery/cue` route (licensing `cue_meta`: ISRC/ISWC/duration) is
a different concept and stays separate — the scoring Cue Layer is namespaced under
`/delivery/cues/…`. If per-cue approval ever needs to gate delivery, map it *onto* the
deliverable approval at read time; do not merge the two stores.

### ADR-0028 — One pricing voice: the public band is the prior, the engine is calibrated to it
**Status:** Accepted (2026-08-04, operator directive) · Source: `docs/launch-review.md`
finding 7 · `estimation.py`, `capabilities.py`, `public/commission.html`
**Decision.** The researched, operator-ratified **public planning band** is the market
prior. `estimation.PUBLIC_BANDS` / `PUBLIC_LENGTHS` / `PUBLIC_USAGE` are its single
definition, rendered into the `/commission` estimator rather than hardcoded there, and the
cost engine is calibrated so its suggested price lands **inside** that band for the common
briefs. Three structural corrections make that possible: role hours describe one campaign
cue end to end (not one demo); **session cost is a real line** — players and the room,
selected by instrumentation — instead of a ×4 on desk hours that paid no one; and
**usage/licence is a fee on price, not a cost of production**. Every `Multiplier` declares
where it lands (`applies="desk"|"price"`), and `multiplier_total` is exactly the product of
the desk factors.
**Why.** The same buyer was shown $9,000–18,000 on the site and quoted from an engine that
costed the job at $4,847, with a client-facing band of ≈$3,100–6,600 — three disjoint
numbers for one brief. The engine was low because it priced a demo, never paid a musician,
and treated a wider licence as a production cost. Calibrating the engine to the band (not
the band to the engine) keeps the public promise and fixes the model that was wrong.
**Consequences.** Rate/hour changes must be re-checked against `test_pricing_voice.py`,
which asserts the engine lands inside the public band and that the page renders the engine's
own constants. Do not reintroduce a pricing constant in a template. Instrumentation beyond
what the public tool can express (a 30-piece orchestra) may legitimately exceed the band —
that is why the page says the real number comes out of the discovery call. `ROLE_RATES` and
`SESSION_PACKAGES` remain placeholders until AFM / SAG-AFTRA rate-card data replaces them.

### ADR-0029 — One "waiting on you" authority; the recorded stage floors the next-action ladder
**Status:** Accepted (2026-08-04, operator directive) · Source: `docs/launch-review.md`
findings 6 + the dashboard duplicate · `web/queue.py`, `web/next_action.py`, `web/app.py`
**Decision.** `queue.compute_queue()` is the **only** computation of "what is waiting on
me". The dashboard reports its length and links to `/queue` for the detail; the inline sum
that used to live in the dashboard route is deleted. The duplicate "▶ Your move" table is
removed — the Mission Control hero features the top move, the queue is the full ranked
list, one module per question. Separately, `next_action.compute()` treats the **recorded
stage as a floor**: a deal that is Won, or that has a project, can never be offered a
discovery or commercial rung.
**Why.** The dashboard said **2** decisions waiting while `/queue` said **11** on the same
database — two independently-coded aggregators, visibly disagreeing on the operator's most
-looked-at number. And the ladder infers position from *artifacts* (meeting rows, a brief
snapshot, a commercial review), which is right when a deal was worked through the system
and wrong the moment it was not: a Won deal, staffed and in delivery, was featured as
"Schedule the discovery call". Winning is a decision a human recorded; it outranks a
missing artifact.
**Consequences.** Do not add a second count of pending decisions — extend the queue's
rungs instead, and every surface inherits it. `compute_queue` now runs on the dashboard
too, so its cost matters: the batching work in the review's Phase 3 should cover both.
`tests/test_one_aggregator.py` fails if the two numbers ever diverge again, or if any Won
deal or any deal with a project is offered a discovery-stage move.

### ADR-0030 — One open-pipeline number, with its provenance
**Status:** Accepted (2026-08-04, operator directive) · Source: `docs/launch-review.md`
finding 6 (money ledgers) · `web/db.py`
**Decision.** `db.open_pipeline(conn, statuses=None)` is the **only** valuation of open
pipeline. One precedence, best evidence first: (1) what we actually bid
(`outcome_value`), (2) the **midpoint** of the disclosed budget, (3) nothing — counted as
`unknown`, never guessed at. It returns the composition alongside the total, and surfaces
render that provenance. The dashboard KPI, the Tentative column subtotal and
`/revenue`'s Open pipeline all read it. Open = `Pursuing` + `Submitted`; `New` is an
unworked lead, not pipeline.
**Why.** Three surfaces asserted three different pipelines on one database: the KPI summed
`budget_max` (the client's *ceiling*, which flatters every disclosed range), the Tentative
column summed `outcome_value`, and `/revenue` read the `proposals` table — where
`insert_proposal` requires a `project_id`, so a row cannot exist until the deal is already
**won**. Open pipeline there was structurally always $0. A money figure with no stated
provenance is what let three of them coexist unnoticed.
**Consequences.** Do not add another pipeline sum — extend the precedence here and every
surface inherits it. The `proposals`-derived figures survive as `proposed_sent` /
`proposed_accepted`, which are post-award proposal values and must not be relabelled as
pipeline. If a future stage belongs in the pipeline, add it to `OPEN_PIPELINE_STATES`.
`tests/test_one_pipeline_number.py` fails if the surfaces diverge, if open pipeline reads
a post-award table again, or if the ceiling is used in place of the midpoint.

### ADR-0031 — The cue sheet's composer column is a legal claim, not a credits list
**Status:** Accepted (2026-08-04, operator directive) · Source: `docs/launch-review.md`
finding 8 · `delivery.py`, `talent.pro`
**Decision.** Only `WRITER_ROLES` (composer, co-composer, arranger, orchestrator,
topline/topliner, songwriter, lyricist) are credited in a cue sheet's composer column.
Writer share and publisher share are **separate columns**; the writer share splits evenly
across credited writers. PRO affiliation is carried **per writer** on `talent.pro` — blank
when unknown, never assumed. Usage is derived from whether the brief indicates a vocal
(`BV`) or not (`BI`) and is operator-overridable per cue via
`delivery_json['cue_meta'][cue]['usage']`; the system never claims a **visual** code
(`VI`/`VV`), because nothing here knows whether a performer is on camera.
**Why.** A PRO pays royalties on the composer column — it is an assertion of authorship,
not a thank-you list. The generated sheet credited *every* assignment, so a mix engineer,
a music editor and the project manager were all filed as authors of the work
(reproduced: `composers='Maya Chen, Leo Park, Ana Ruiz, Sam Diaz'`). It also carried one
`100%` share (meaningless across two accounts), hardcoded `BMI` for every writer whatever
their actual affiliation, and hardcoded the main cue to `VV` — Visual Vocal — asserting a
sung on-camera performance for every campaign bed ever delivered. A sheet like that is
rejected on filing, and the rejection lands on the client.
**Consequences.** New creative roles must be added to `WRITER_ROLES` deliberately — the
default is *not* a writer. Do not reintroduce a single share column. `talent.pro` is
additive (idempotent column migration) and editable on the talent page; leaving it blank
is correct when unknown. `tests/test_fileable_cue_sheet.py` fails if a non-writer is
credited, if the shares are conflated, if a PRO is assumed, or if a visual usage code is
claimed. **Still open (finding 8):** the rights model itself — a full buyout /
work-made-for-hire default coexisting with Chordential-as-100%-publisher and
category-limited exclusivity — and the missing `media` dimension on the licence.

### ADR-0032 — One rights basis: the master is bought out, the publishing is retained
**Status:** Accepted (2026-08-04, **operator ruling** — this is a commercial decision,
not an engineering one) · Source: `docs/launch-review.md` finding 8 · `delivery.py`,
`capabilities.py`
**Decision.** The client buys the **recording (master) outright** and receives a
**perpetual sync licence across every campaign medium**, worldwide, exclusive in the
campaign category. The **composition's publishing is retained by Chordential Music** —
which is what the cue sheet files, and what performance royalties are collected against.
`DEFAULT_LICENSE` gains an explicit `publishing` term and the previously missing `media`
dimension; the certificate prints both. Per-deal overrides still win — this fixes the
*default*, which has to be internally consistent.
**Why.** The package asserted three mutually exclusive positions at once: a licence typed
"Full buyout / work-made-for-hire", a cue sheet filing Chordential as **100% publisher**,
and a **category-exclusivity** clause. Under work-made-for-hire the *client* is the author
and owns the publishing, so we cannot also collect a publisher share; and exclusivity is
meaningless on rights you no longer hold. Any agency business-affairs reviewer catches
that on one read, and it lands on the certificate that is the product's whole promise.
Of the three coherent structures, this is the standard one in advertising music, the only
one that makes the existing cue sheet correct, and the one that preserves a recurring
royalty line. The sales copy moved to match: "you own it" → "you own the recording and the
right to use it forever, in every campaign medium", and "no PRO surprises" (which sat
beside a cue sheet we file *with* a PRO) → "nothing to clear but ours".
**Consequences.** Never reintroduce "full buyout" or "work-made-for-hire" as the type —
`tests/test_rights_model.py` fails on both, and on marketing that promises publishing we
do not convey. If the business ever moves to a true buyout, the cue sheet's publisher must
move to the client in the same change. Composer agreements (ADR-0024) must convey the
master and grant the sync licence while leaving the writers' and publisher's shares
intact; that instrument is outside this repo and should be checked against this ADR.

### ADR-0033 — One estimate call path: `web.estimate.estimate_for`
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` finding 9 ·
`web/estimate.py`, `web/app.py`, `web/public.py`, `web/seed.py`
**Decision.** The web layer turns an opportunity into an estimate through exactly one
function — `web.estimate.estimate_for(opp, *, conn=None, project_id=None, qual=None)`.
It owns the discipline fallback, the team shape, and the assigned-rate lookup. No module
outside `web/estimate.py` calls `build_estimate` directly. `estimation.build_estimate`
remains the intelligence-layer engine and is unchanged; this ADR governs how the web
layer *reaches* it.
**Why.** The four lines that resolve a discipline, derive a team shape, fetch rate
overrides and call the engine were copy-pasted at **nine** call sites — in **three**
versions. Seven applied a qualified-fallback (price an unqualified deal as
`COMPOSITION`); two — the dashboard KPI's `_suggested_price` and the project estimate —
used `qual.discipline` raw. Because `NON_CRAFT` carries an *empty* team shape, the same
disqualified opportunity priced at **$7,810 on the dashboard and $8,350 on its own
estimate page**. Separately, only the project estimate resolved
`assigned_rate_overrides`, so the number a client approved could differ from the proposal
generated after assignment. Nine copies of a rule is nine places for it to drift, and it
had already drifted twice before anyone was looking.
**Consequences.** New pricing surfaces call `estimate_for`; pass `conn=` + `project_id=`
whenever a project exists so assigned rates apply, and pass `qual=` when you already hold
one. `tests/test_one_estimate_path.py` fails if any web module calls `build_estimate`
directly, if the fallback idiom spreads back across the layer, or if the dashboard and
the estimate page price the same deal differently. The discipline fallback may still
appear once more — in `_ensure_project_for_opp`, which uses it to derive project *roles*,
not a price. Changing the fallback (e.g. to refuse to price a disqualified deal at all)
is now a one-line change in one file, which is the point.

### ADR-0034 — One quote authority: `capabilities.quote_band`
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` finding 7 (the open
thread) · `capabilities.py`, `web/commercial.py`, `prepare.py`, `outreach.py`,
`proposals.py`, `web/app.py`
**Decision.** `capabilities.quote_band(opp, estimate, *, ci_fields, commercial_overrides)`
is the **only** thing that answers "what number do we put in front of this buyer." Its
precedence, unchanged from ADR-0020: an explicit operator override (`fee_low`/`fee_high`)
→ the **discovered budget** (CI `budget_band`, then the opportunity's own budget columns)
→ the estimator's price band. It returns `(None, None)` rather than inventing a figure.
Every surface renders it and derives nothing: the client's Campaign Brief, the client's
Commercial Review, the pursuit checklist, the outreach cadence, and — via
`build_proposal(..., quote_band=)` — the generated proposal's **total** and the brief's
**Pay-deposit** amount. `_price_band` is demoted to what it always was: the last leg of
the precedence, not a quote.
**Why.** Four surfaces computed a quote four ways. The two the **same buyer reads** were
the worst: the Campaign Brief reached straight for `_price_band` while the Commercial
Review quoted to the disclosed budget, so on the seeded book Brightline was shown
**$7,200–$15,100 in the brief and $20,000–$40,000 in the review** — and Halcyon the
reverse, $8,600–$18,000 against $6,000–$10,000. Internally it was worse than inconsistent:
the pursuit checklist printed `estimate.cost_range` — *what production costs us* — under
the label "Provide an indicative quote", instructing Jon to quote **$4,342** to a client
who had disclosed $20,000–$40,000; and the outreach cadence quoted the estimator's point
`suggested_price`, which on the seeded book ran from 58% under a client's own floor to 33%
over their ceiling. And it reached the money: the project's Generate-proposal button
totalled `estimate.suggested_price`, producing a **$9,712** proposal on a deal whose
Commercial Review had told the client a deposit implying **$8,000** — while the *other*
proposal path (`_ensure_proposal_from_review`) correctly rewrote the money from the
approved review. Two proposal paths, two totals, one deal. The brief's Pay-deposit figure
had the same fault, disagreeing with the band printed directly above it on the same page.
The estimate is an internal cost-plus-margin read; the quote is a commercial decision
about a specific buyer. Conflating them is what produced every one of these.
**Consequences.** Never render `_price_band`, `estimate.cost_range` or
`estimate.suggested_price` as a client-facing figure — `tests/test_one_quote.py` fails on
each, and asserts every surface agrees on every seeded deal with a disclosed budget.
`build_proposal` without a `quote_band` still totals the estimator's number, which is
correct for callers that only want `.terms`; any caller producing a *client* proposal
must pass the band. The frozen review snapshot still wins in
`_ensure_proposal_from_review` — what the client approved binds, even if CI has moved since.
`prepare` and `outreach` take the band as a parameter (resolving it needs the DB); the web
layer resolves it once in `app._quote_band_for`. A deal with only one disclosed figure
quotes that figure — the brief template renders a single number, not `$12,000–$12,000`.
The pursuit brief's `budget_line` keeps the internal read ("Estimated $X–$Y; suggested
price $Z at 40% target margin") — that is honest analysis, explicitly labelled, and it is
the one place cost belongs.
**Also removed here.** `PursuitBrief.response_outline` and `.next_steps` are deleted. The
brief carried **three** action lists with the same steps worded differently; the HTML page
rendered only `checklist` while `brief.txt` rendered only the other two, so one brief gave
two different instruction sets depending on how it was opened — and the wrong quote line
sat in all three, which is how it survived. `checklist` is the single list; `render_text`
prints it.

### ADR-0035 — A nav slot is for a destination, not a saved search
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` Phase 2 (console nav
diet) · `web/templates/base.html`, `web/app.py`, `web/db.py`, `detail.html`
· **Supersedes** the `/lanes`-related parts of `docs/dashboard-consolidation-council.md`
**Decision.** The console sidebar carries **destinations only** — a page that answers a
question no other nav page answers. Two classes of link are removed and must not return:
a second rendering of a table another nav entry already lists, and a pre-filtered URL or
in-page anchor into a page already in the nav. Concretely: **`/lanes` is deleted** (route
+ template), and the four "queue" quick-links (`/inbox?action=Pursue`,
`/inbox?action=Review`, `/dashboard#followups`, `/inbox?status=Won`) are removed. 21
links → 16.
**Why.** Measured on the seeded book, `/lanes` and `/inbox` rendered the **identical**
18 opportunities — the same table, the same one-click advance, different clothes. Its
only unique control was a "Won" button that POSTed `status=Won` with **no**
`outcome_value`, booking a won deal at **$0** in every revenue read and contradicting the
rule documented six lines above `_NEXT_STATUS` in the same file: *"Won is intentionally
omitted — closing a deal goes through the win/loss form so the value is captured."*
Closing two deals through the board summed to $13,325; the same two through the form,
$25,325. The four quick-links were saved searches: `action` offers Pursue/Review and
`status` offers Won in `/inbox`'s own dropdowns, and `#followups` is an anchor on the
dashboard, which is the first nav item. None of them was a place; all four cost a
permanent slot.
**Consequences.** `tests/test_console_nav.py` fails if a nav link is a filter over
another nav page, if two nav entries share a path, if the nav exceeds 16 links, or if any
template can POST `status=Won` without an `outcome_value` field in the same form. The
dashboard's "in flight" KPI now links to **`/inbox?status=open`**, a filter that reuses
`OPEN_PIPELINE_STATES` (ADR-0030) rather than restating which stages count — so the
number and the list beneath it cannot disagree, as they did when it opened a board
showing Won and Closed deals too. The detail page's stepper hands a win to the win/loss
card (`#winloss`) instead of recording it blind; that was the second surface with the
same hole, and it is closed here. The friendly stage vocabulary (`stage_label`) outlived
the board and is asserted on `/inbox`.
**Note on the superseded council.** `docs/dashboard-consolidation-council.md` reached the
opposite split — keep Pipeline, demote Inbox — on the same premise ("three tabs are three
renderings of one table"). Two things changed since: `/queue` became the "waiting on you"
authority (ADR-0029), and `/inbox` is load-bearing (the topbar search posts to it), while
`/lanes` had no inbound link but the nav and two KPI cells. The council's own acceptance
test — *"no two tabs may show the same cards"* — is what this ADR finally enforces.

### ADR-0036 — The client portal answers the court question first, and orders itself by it
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` Phase 2 (portal
ordered by court-state) · **Implements** ADR-0019's unmet consequence ·
`web/production.py`, `delivery_portal.html`, `web/app.py`
**Decision.** The delivery portal renders `production.court_state()` — the badge, the
client-voice sentence — as the **first thing in the hero**, and lays its cards out by the
answer: with the client, the review leads; with the studio, sending us the cut leads;
delivered, the package leads. The engine gains a `badge` (`YOUR MOVE` / `WITH THE STUDIO`
/ `DELIVERED`) so the wording has one home and the portal and the workspace cannot drift.
Reordering is done by placing a Jinja macro, not by CSS `order` — the DOM order stays the
reading order. And **no card may invite a decision about a version that does not exist**:
with no track to hear, the section is "The listening room", it carries no version label,
no round counter, and no Approve / Request-changes row.
**Why.** ADR-0019 ratified that "the client-facing production experience must always
answer the court question first" and built `court_state()` to compute it. The portal
rendered none of it. Measured on the seeded book, **Lumen Health** (court=`studio`,
nothing owed) and **Vance Athletic** (court=`client`, v2 waiting) produced the *identical*
page — card order `[picture, review, brief]`, the same "Review & approve" call to action —
differing only in a hero chip reading our internal state machine: *"In production · v1
Concept"* against *"In review · v2 Direction-lock"*. Neither answers "what do I need to
do?", and the first is worse than unhelpful: **Lumen has zero versions**, and `v1 Concept`
is `revision_status`'s *default label*, not a fact. The portal named a version that had
never been delivered, told the client to "leave time-stamped notes, then approve or
request changes", and offered a Request-changes form — which writes to the `round_log`,
opening a contractual revision round against work that does not exist. That is an
honesty-rule violation on the surface the client actually reads.
**Consequences.** `tests/test_portal_court_state.py` fails if a portal omits the badge or
the engine's sentence, if two court states render the same page, if the review does not
lead when it is the client's move, if a track-less project names a version or shows a
round counter, or if Approve / Request-changes is offered with nothing to decide on.
Never render `version_state` as though it described a delivered version — it is a default
until one exists. The gate is **`review_track`, not the version ladder**: a Phase-0
project can carry commentable audio with no version logged (that fallback is deliberate
in `app.py`), and gating on the ladder wrongly silenced those. Scope discipline worth
keeping: what was removed is the *decision* row and the phantom label, not the client's
ability to talk to the room — the timecoded comment form was already track-gated before
this change, for the good reason that a note needs a timeline to land on.

### ADR-0037 — A delivery filename asserts only what the brief states
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` Phase 2 (naming
system) · `estimation.py`, `delivery.py`, `web/app.py`, `web/seed.py`
**Decision.** The stem contract `CAMPAIGN_CUE_LEN_ROLE_vN_STATE` stands, with two rules
added: **every token is optional and a blank one is skipped** (no placeholder is ever
substituted), and **the length token comes from `estimation.stated_length()`** — the
duration the brief actually says — and is omitted when the brief says none. `_infer_duration`
keeps assuming `:30` for pricing; naming may not. Both upload doors (the operator's console, the
composer's portal) park a file as a **pending submission**, and one function names it on
publish — `project_routes._publish_pending_submission` via `_master_stem()`; the manifest
renders the stem a version was **written with** rather than recomputing one.
**Why.** Both upload paths called
`version_name(campaign, "Master", 60, "Master", n, f"v{n}")`, producing
`SUMMER_Master_60_MASTER_v1_V1` — three fabrications in a filename the client receives.
The **`60`** was hardcoded: of four seeded projects, three have briefs that never say :60,
and one says ":06/:15/:30 cutdowns" — a **:30** master. **`Master` appeared twice**
because the caller filled the CUE slot with it as well as the ROLE slot (and a blank cue
fell back to the literal placeholder `Cue`). **`_v1_V1`** was the version number again,
because `f"v{n}"` landed in the STATE slot, which exists for `FINAL`. Separately the
manifest *recomputed* a stem instead of reading the stored one, so it could list a file
the package does not contain. A delivery filename is the most-copied artefact we produce
— it goes into the client's DAM, their edit bay, and their PRO paperwork; asserting a
duration nobody measured is the honesty rule applied to the smallest surface we own.
**Consequences.** `tests/test_naming.py` fails if a stem names a length its brief never
stated, if a stem repeats `MASTER` or ends `_vN_VN`, if a blank token is substituted, or
if the namer calls `version_name` directly instead of going through `_master_stem`.

**Amended 2026-08-05 — the guard was half-fictional.** The "two upload paths sharing one
helper" was asserted by reading the source of two functions, and **one of them had no
callers anywhere, since the repository's first commit**: `_append_version_from_bytes`,
whose own docstring claimed to be "shared by the admin Assets agent and the composer
portal". So half the contract was pinned on unreachable code while the live path was
checked only indirectly. The function is deleted (36 lines) and the guard is now two
tests that cannot be satisfied by dead code: one walks the whole `web` package and fails
unless **exactly one** function writes a `name` into the version ladder, and one is
**behavioural** — it uploads through the operator's console and through the composer's
portal, publishes each, and compares the stems the client actually receives
(`SUMMER_30_MASTER_v1` from both). Reintroducing the original defect makes the
behavioural test print the historical filename verbatim: `SUMMER_Master_60_MASTER_v1_V1`.
Note the deliberate asymmetry: pricing MUST put a number on an unstated brief (a quote
needs one), so `_infer_duration` still assumes and still treats "anthem" as :60; naming
abstains, and "anthem" alone is not a duration. When a length genuinely is stated it does
reach the filename — the seeded CPG project names `ORIGINAL_30_MASTER_v1`. Existing
delivered files keep their stored names; nothing renames retroactively.

### ADR-0038 — One declarative uploader; progress means bytes
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` Phase 2 (real
byte-progress on console uploads) · `static/live.js`, `static/style.css`,
`delivery_console.html`, `_brief_document.html`, `compose.html`
**Decision.** A form marked **`data-upload`** sends over XHR and renders a rail driven by
`ev.loaded / ev.total` — percent and megabytes, nothing else. The behaviour lives once in
`live.js`; templates add an attribute, never a script. `data-think` wins when a form has
both: that veil belongs to forms whose wait is the *server* thinking, and two capture-phase
handlers calling `preventDefault` on one submit is a bug waiting to happen. Applied to the
delivery console's four uploads (picture, reference, asset, version) and the two
`audio/*` attachments on `_brief_document.html` / `compose.html`.
**Why.** The console carries the largest files in the system — a picture cut or a stem
package is hundreds of MB — and all four of its upload forms were **naked synchronous
multipart POSTs**: a blank tab, no feedback, and no way to distinguish a stalled upload
from a slow one. Both *client-facing* surfaces already had real byte progress (the
portal's Drop, the creator portal's master upload), so the operator moving the biggest
files had strictly the worst experience in the product. A third copy-paste of those twenty
lines was the obvious fix and the wrong one — hence one behaviour, three surfaces.
**Consequences.** `tests/test_upload_progress.py` fails if a console upload form loses
`data-upload`, if the upload path grows a `setInterval`/`setTimeout`/`Math.random` (a bar
that animates on a clock while bytes may not be moving is decoration, and worse than
none), if the failure path stops preserving the chosen file, if the `data-think` guard is
removed, or if the console grows its own `XMLHttpRequest` instead of using the behaviour.
Verified in Chromium against a throttled 24 MB upload: `0 of 24 MB` → `13% · 3.1 MB of 24
MB`, tracking real loaded bytes; the abort path shows *"Connection lost — the file is
still chosen, try again"* with the button re-enabled and the file still selected; and with
JavaScript disabled the form still posts normally. **Not** applied to the AI intake form
(`detail.html`, `data-think`) — its wait is the 10-agent extraction, not the voice memo's
bytes — nor to the small procurement document upload. The creator portal keeps its own
inline uploader: it is standalone and does not load `live.js`, so migrating it would mean
pulling the whole living-OS module onto a page that needs one behaviour; that duplication
is known and deliberate.

### ADR-0039 — A client link can be cut
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` Phase 2 (share-token
rotation) · `web/db.py`, `web/app.py`, `delivery_console.html`
**Decision.** `db.rotate_share_token(conn, *, opp_id=|project_id=)` mints a fresh token
for a deal and **rotates both records** — the opportunity's (brief / first-touch) and the
project's (delivery portal) — stamping `share_token_rotated_at` on each (additive column
migration, the house pattern). One operator route,
`POST /project/{id}/delivery/rotate-link`, behind a `data-confirm`, logged to the
project's history. Reviewer `?r=` links are a separate credential with their own
revocation and are **not** touched.
**Why.** The share token is the *only* credential on the delivery portal. Measured
against a gated instance, a bare `?k=` opens the unreleased master (streamable), the
client's brief and scope, the deliverables list — and the Request-changes form, which
writes the `round_log` and therefore **spends a contractual revision round** (ADR-0019).
Without the token the portal 404s, so the URL *is* the credential. `ensure_share_token`
minted once and returned the same value forever: there was no rotate, no revoke and no
expiry anywhere in the codebase, so a forwarded email, an exported Slack channel or a
departed employee's inbox was permanent access. The console's own copy told the operator
to "treat it as forwardable" while offering no remedy — this is the remedy.
**Consequences.** `tests/test_share_token_rotation.py` fails if the old link survives, if
**either** record keeps its old token (rotating half a credential is not rotating it —
the two can and do diverge on the seeded book, which is the trap these tests exist for),
if a reviewer's personal link is revoked as collateral, or if anything other than the
operator's route calls `rotate_share_token`. Rotation is **never automatic**: a token
that rotated on a schedule would break a client's bookmark with no human deciding to,
which is the opposite of "the machine proposes, Jon disposes". Deliberately out of scope:
expiry dates, per-recipient share links, and signed download URLs — each is a separate
decision and none is what "the link leaked" needs. `share_token_rotated_at` is additive
and nullable, so pre-existing rows read as "never rotated".

### ADR-0040 — The front door plays music
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` finding 3 ("hear the
work") · `public/commission.html`, `web/public.py`, `web/showcase.py`
**Decision.** The homepage carries a **Listen** section rendering the real capability
demonstrations — title, the brief each answers, and a native `<audio>` control — from the
same `showcase.DEMOS` list `/samples` renders, so the two surfaces cannot describe the
same track differently. The hero's listen CTA points there. Demo audio is served from our
own `/static/public/`, not a third-party CDN. The homepage's synth keeps its place as an
interactive demonstration of the **note mechanism** and now says that is what it is.
**Why.** The hero promised *"written and recorded in house by people — never AI-generated
audio"* and, two lines beneath it, offered a button reading **"Hear the score"** that
scrolled to a player driven by a **WebAudio oscillator**. There was no `<audio>` element
and no recording anywhere on the page — the only `.mp3`-ish match in the whole template
was `o.type = t.wave`. So the one button inviting a visitor to hear the product played a
machine, on the page that had just promised the opposite. Meanwhile four real
demonstrations existed with audio attached and honest framing, and `showcase.DEMOS_INTRO`
already carried a `home_title`/`home_cta` written for a home section nobody had built.
**Consequences.** `tests/test_hear_the_work.py` fails if the homepage has no audio, if a
player points at something that isn't a served `audio/*`, if a track is off-site, if two
cards play the same recording (compared on the audio payload with the ID3 tag stripped,
so retagging cannot disguise a duplicate), if the hero CTA stops leading to recordings,
if the "never AI-generated audio" promise is dropped, if the synth stops disclosing that
its tone is browser-generated, or if the template hardcodes an `.mp3` instead of
rendering from `showcase`. **Native controls on purpose:** this section's job is to get
music playing, not to be another mechanism — the native transport is familiar,
keyboard-navigable and screen-reader-friendly, and it needs no JS. `preload="metadata"`
rather than `none`, because `none` renders "0:00 / 0:00" and reads as broken. Chromium
ignores `color-scheme: dark` on media chrome, so the control renders light against the
dark page; that is a browser limitation and not worth a `::-webkit-media-controls` hack
or a bespoke player. Swapping a track is a file swap at the path in `showcase.py` —
nothing else changes. The current files are the operator's demo uploads, to be replaced
with final masters.

**Amendment (2026-08-12) — the placeholders disclose themselves.** The tracks this ADR
wired are **AI-generated placeholders**, standing in until real sessions are recorded.
Every served demo carries the ID3 artist tag `Generated by ACE Studio` — `TPE1` on all
four wired files and all ten unreferenced `exp-*` files — readable with a right-click in
any player or a drag into a DAW. This ADR was ratified on the assumption they were real
recordings, and the assumption was never checked.

That put the page in the shape this ADR exists to correct, one layer down: the hero
promised *"never AI-generated audio"* two lines above audio whose own metadata said the
opposite. The promise is **true of what we deliver** and was **false of what the page
plays**, and a visitor cannot tell those apart from a hero.

**What changed.** The promise comes off the hero. Every surface that plays a demo — `/`,
`/samples`, `/showreel` — renders `showcase.PLACEHOLDER_AUDIO_NOTICE`, one string, at
reading weight beside the players rather than as fine print. The consequence above, *"if
the 'never AI-generated audio' promise is dropped"*, is **inverted**: the suite now fails
if that promise appears over placeholder audio, and fails if a surface plays a demo
without the disclosure.

**Explicitly not done: the tags were not stripped.** They are accurate. Editing a true
tag so a claim survives is falsification, and it is the move the honesty rule exists to
prevent. The tags stay until the files they describe are replaced.

**When real sessions land,** the placeholders are replaced, `PLACEHOLDER_AUDIO_NOTICE`
and the tests asserting it come out **together**, and the human-authorship promise
returns to the hero — where it will then be true of both what we deliver and what the
page plays. Not one of those steps without the others.

**Amendment (2026-08-12) — the front door moved, the guarantees moved with it.** `/`
now serves the **score page**: 728 pieces of engraved notation converging into the
cube as the visitor reads, the recordings reached by pressing a lit piece of the
score, and the delivery package written by `delivery.build_manifest`. The Commission
stays at `/commission`.

This ADR's promise is unchanged — **the front door plays music** — but its shape
was written for a page with a row of native players, and the score page reaches its
recordings differently. So the assertions were **re-expressed, not relaxed**, and
every guarantee still fails the build:

| Guarantee | Where it is asserted now |
|---|---|
| Four **distinct** recordings on the front door | `test_the_front_door_plays_four_different_recordings` — compared on the audio payload with ID3 stripped, so a retag cannot disguise a duplicate |
| Served from our own origin, never a CDN | `test_the_front_doors_tracks_are_served_by_us` |
| Each one actually serves `audio/*`, not a 404 | `test_the_front_door_offers_real_recordings` |
| No track hardcoded in the template | `test_the_front_door_does_not_hardcode_a_track` |
| The front door and `/samples` tell one story | `test_the_front_door_and_samples_render_the_same_records` |

The Commission's own guarantees — its `#work` section, its `#take` synth disclosure,
its hero CTA, its no-JS degradation — **followed it to `/commission`** rather than
being deleted. They are about that page's markup and they still hold there.

**What is deliberately different.** The score page has no row of players, so it
carries no placeholder-audio disclosure beside them; that notice remains on
`/commission`, `/samples` and `/showreel`, which do. Provenance of the demo
recordings is the operator's call and is tracked outside this ADR.

`/` and `/score` share one renderer (`_render_score`), asserted by
`test_the_score_page_and_the_front_door_are_one_page` — two addresses for the front
door that could drift into different pages is the defect this codebase keeps
removing everywhere else.

### ADR-0041 — `--olive` darkens to clear AA
**Status:** Accepted (2026-08-04, **operator ruling** — a brand token's value is a
palette decision, not an engineering one) · Source: `docs/launch-review.md` Phase 2 (the
deferred contrast item) · `static/style.css`, `static/public/site.css`, `static/brief.css`,
`first_touch.html`, `commission.html`, `campaign_home.html`
**Decision.** `--olive` moves from `#737469` to **`#65665B`** — in OKLCH, lightness
`0.555 → 0.505` with **hue and chroma untouched**. Both palettes move together (the
console's hex and the public site's OKLCH are the same colour and must stay so), as do
the two standalone client-document palettes that define the same value as `--muted`, the
one hardcoded literal on the homepage's paper card, and all fourteen
`var(--olive, …)` fallbacks.
**Why.** The launch review flagged `#737469` at 4.47:1 as body text and deferred it,
correctly, as a palette call. Measured properly it was worse than filed: **4.47:1** on
`--bg`, **4.15:1** on `--panel`, **3.89:1** on `--panel2` — under AA on *three* of the
four console surfaces it types on. And the earlier Phase-1 contrast pass had fixed
`site.css`'s `--muted` while missing the same value in **`brief.css`** and
**`first_touch.html`** — two documents a *client* reads — at 4.47:1 on the page and
3.86:1 on the body, plus a raw `#737469` on the homepage's paper card at 3.84:1 against
the dark end of its own gradient. Self-contained palettes are exactly how a sitewide
colour fix misses surfaces. Worst case is now **4.78:1**.
**Consequences.** `tests/test_olive_contrast.py` **computes** the ratios from the
stylesheets rather than asserting a hex, so the palette may move again as long as it
keeps passing; it fails if any surface drops under 4.5:1, if the two palettes' lightness
diverges, if `#737469` reappears anywhere (including as a `var()` fallback — a page that
renders before the palette must not land on the failing value), or if the "darkening"
ever changes the hue enough to stop being an olive. When adding a surface colour, check
type against it rather than assuming the token is safe: this token passed on `--card`
the whole time, which is why it survived a review pass.

### ADR-0042 — The intake asks what the project is worth to the client
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` Phase 2 (brand-unified
intake with a budget field) · `public/start.html`, `web/public.py`,
`static/public/site.css` · **Amends ADR-0034's scope**
**Decision.** `/start` renders an **optional** budget field. `public_price_band` prefers a
stated budget through `capabilities.quote_band`, so the range shown at intake is the range
quoted later. With nothing stated, behaviour is unchanged — ADR-0028's public voice.
**Why.** The page promised *"a few details is all we need to come back with an approach
and a price range"* and never asked what it was worth to them. Not for want of plumbing:
the POST handler already accepted `budget_text`, `promote_lead` already ran it through
`extract_budget` into `opportunities.budget_min/max`, and those columns are **leg 2 of
`quote_band`**. The form simply never asked, so the field was empty on every real
submission and the chain behind it ran dry. Measured end to end: a lead that would have
said **$25,000–$40,000** was quoted **$7,200–$15,100** — our cost model, **3.4× under**, on
exactly the deals that arrive through the front door. Capturing it then exposed the next
link: `public_price_band` still ignored the budget, so a visitor would see $7,200–$15,100
at intake and be quoted their own $25,000–$40,000 later — a jump that reads as a
bait-and-switch on the surface where trust is cheapest to lose. ADR-0034 had deliberately
left that function alone **because intake captured no budget**; that reasoning is now
retired, which is the amendment.
**Consequences.** `tests/test_intake_budget.py` fails if the field disappears, if it
becomes required (a mandatory budget on a first contact costs more leads than it saves),
if a validation bounce eats what was typed, if a stated budget stops reaching
`budget_min/max`, or if the intake band and the later quote diverge. Unparseable input
("we're flexible", "TBD") falls back to the estimator rather than breaking —
`extract_budget` returning nothing is the normal case, not an error. The brand half of
this backlog item needed no work: `/start`, `/book` and `/thanks` already share the
wordmark, serif, ember and warm palette, and all six front-of-house routes resolve —
checked before changing anything, and left alone.

### ADR-0043 — Client media lives behind a storage seam
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` Phase 3 (object
storage) · `storage/`, `web/app.py`, `web/seed.py`, `render.yaml`, `pyproject.toml`
**Decision.** Every write and read of client media goes through
`storage.get_object_store()` — the same provider-seam shape as payments and mail:
**local disk by default** (behaviour unchanged), S3-compatible when
`CHORDENTIAL_STORAGE=s3`. `_persist_upload` is the only writer; no route may open a file
under `UPLOAD_DIR` for writing. The SQLite mirror is written **only when the store is not
durable** — it is the net under the disk, and with a bucket configured it would double
every master into the database for no benefit. A remote store serves by **presigned
redirect** so bytes never stream through the app and Range/seek stay the bucket's job;
local keeps serving `FileResponse` off a real path. Selecting `s3` without full
credentials **falls back to disk and says so at boot**.
**Why.** The cutover runbook is blunt: *"migrate uploads to object storage first or the
cutover destroys every client cut, master and stem."* Measured on a seeded instance,
**four of five uploaded files had exactly one copy** — because three routes wrote straight
into `UPLOAD_DIR`, bypassing the helper whose own docstring claimed to be *"the single
place that persists media, so every write site is durable"*: the intake artifact (a voice
memo, a transcript, an RFP), the procurement document (a W-9, a COI), and the opportunity
doc upload (the audio on the client-facing brief). A false claim in a docstring is worse
than no claim, because it stops anyone checking.
**Consequences.** `tests/test_object_storage.py` fails if any route opens `UPLOAD_DIR`
for writing, if an upload route stops leaving a second copy, if a durable store still
gets mirrored, if a remote store streams instead of redirecting, or if the payment-gated
`.zip` becomes reachable through `/uploads`. `_safe_upload_path` is deleted — its
traversal guard now lives in `LocalObjectStore._path`, travelling with the store that
needs it. `boto3` is the optional `s3` extra, imported lazily.
**What is NOT done, and must not be assumed.** No bucket has ever been written to from
this code — there are no credentials in the build environment, so the S3 backend is
covered by its contract, its configuration logic and a fake store, never by a live
round-trip. **Before the cutover:** copy `/var/data/uploads` into the bucket, set
`CHORDENTIAL_STORAGE=s3` plus the four secrets, confirm the boot line reads *"object
storage active"*, verify a real upload and a real download, and only then remove the
disk. The existing files are not migrated by this change; the seam is the prerequisite,
not the migration.

**Amended 2026-08-05 — the seam was only as durable as the image, and the image was
missing the SDK.** `render.yaml` installed `.[web,gmail,ai,stripe,postgres]` — **no `s3`
extra**, so production had no `boto3`. With the four credentials set, `S3ObjectStore`
reported `configured` → `durable = True`, every `put()` returned False because the client
could not be built, and `durable` is precisely what tells `persist_upload` to skip the
SQLite mirror. Reproduced end to end: an uploaded master ended up with **zero copies** —
not in the bucket, not on disk, not in the mirror — while the boot line printed *"object
storage active — uploads are durable."* Following the cutover runbook as written would
have hit this at the exact moment the operator believed durability had been turned on.

Two fixes: `configured` now requires the SDK as well as the credentials (no SDK →
half-configured → falls back to the disk and says so loudly), and the build installs the
`s3` extra **while still on local**, so the package is present before anyone can flip the
switch. Both are pinned by tests, one of which asserts on `render.yaml` itself.

The runbook also gained the step it never had: `scripts/migrate_uploads_to_object_store.py`
reads **both** the upload directory and the `media_blob` mirror — after a redeploy some
keys exist only in the mirror, and a `cp -r` would leave them behind — writes each object,
then **reads every one back and compares SHA-256**, because `put()` returning True is not
evidence. It is idempotent and exits non-zero on any mismatch. The uploads migration is now
**Step 1**, ahead of the database copy: it is independent, it carries the irrecoverable
failure mode, and the database copy is a snapshot that should happen immediately before the
flip rather than hours before it.

**Amended 2026-08-05 (second) — "every write goes through the door" was still not true,
and "the file exists" was never the question.** The live migration moved 12 objects and
verified every one; a client version then played back as silence, and three rounds of
reading counters off a page could not name the file. The page now audits what the
**database references** — every version, pending submission, asset, picture and delivery
package — against the bucket and the mirror, and names what it cannot find. Run against
production it named two files, and neither had been uploaded by anyone: the seeded demo
master and the demo's delivery ZIP.

Both were written by `seed.py` — one with `shutil.copyfile`, one by calling
`store.put()` directly — so neither ever reached the SQLite mirror. Seeding is
idempotent, so it never ran again; the first redeploy wiped the ephemeral disk and the
demo campaign's *":60 master"* and *"Download everything"* had been dead ever since. The
guard test that was supposed to make this impossible only matched `open(…, "wb")`, so it
watched two doors out of four. A text scan cannot enforce this claim; the replacement is
behavioural — seed an instance, delete the upload directory, assert the audit finds
nothing missing — and it fails on the pre-fix tree naming exactly the two production
files. The delivery-package builder had the mirror-image bug: it wrote the ZIP to disk
and called `db.save_media_blob` directly, so with a bucket configured the one artefact
the client pays for was the one piece of media that never reached the bucket — it sat in
a SQLite blob, which is the bloat the Postgres cutover exists to end, on the largest file
in the system.

The seam also gained a fifth verb, `size()`. Existence and playability are different
claims and the audit was only checking one: a **zero-byte object is present**, answers
`exists()` with True, survives a SHA-verified migration, and plays as silence —
indistinguishable from a missing file to whoever pressed play, and its opposite to anyone
reading a checkmark. Every audited row now carries its size and where it would be served
from, and an empty file is reported as broken rather than fine.

**The read path was the last one.** `/uploads/{name}` handed a durable store the redirect
unconditionally, and `url()` signs a key without asking the bucket anything — so a missing
object was answered with a 307 to a presigned URL the bucket replies to with a 404, which
an `<audio>` element renders as **silence, with no error anywhere**. Returning there also
skipped the DB-mirror fallback below it, so a key existing only in the mirror was
unreachable — and that is precisely the state `persist_upload` leaves behind when a bucket
write fails, having logged a warning and saved the bytes so they would not be lost. They
were not lost; they were unplayable, while every existence check said fine. The redirect
is now offered only for an object the store confirms it has (one HEAD), and a mirror-only
key serves from the mirror and repairs itself into the bucket on the way past.

**Amended 2026-08-05 (third) — and the silence was none of the above.** Every fix above is
real and every one of them was found by chasing a client's report of "I press play and hear
nothing". None of them was the cause. The cause was the waveform: `wave-live.js` called
`ctx.createMediaElementSource(audio)`, which does not *observe* an element — it **captures**
it. From that call on, the element's only route to the speakers is through the Web Audio
graph. The context was built inside the `play` event handler, which is not reliably inside
the user-gesture window, so Chrome started it suspended; `resume()` returned a promise
nobody awaited, and by then the audio had already been taken. Measured in a browser:
element playing, `audio.paused` false, no `MediaError`, `ctx.state` suspended, the graph's
clock frozen at 0, `currentTime` stuck at 0 — and **not one visible signal on any surface**.

The lesson is not about Web Audio. A **decoration was allowed to sit in the signal path of
the product's core act** — a client listening to the work — and its failure mode was
indistinguishable from a healthy system. Every honest instrument we built (the store audit,
the size check, the read-path guard, the player's error handler) correctly reported that
everything was fine, because everything *was* fine everywhere they could see. The Living OS
rule already said motion must communicate state and never decorate; it now also says
motion may never sit between the client and the sound. The context is built and resumed
from the **click**, and nothing is tapped unless `ctx.state` is genuinely `"running"` — not
resuming, not a promise of running. A still waveform is a decoration we can lose.

**And that was still not the whole of it — the cause was CORS.** The suspended-context
path above is real but needs unlucky timing. The one that actually silenced production
needs nothing: a `MediaElementAudioSourceNode` fed by **cross-origin** media that is not
CORS-approved **must output silence by spec**, so the analyser cannot be turned into a way
to read bytes across origins. Measured on one page, two elements, identical code:
same-origin peak 222 / energy 8564; cross-origin peak **0** / energy **0** — both
reporting `playing`, `currentTime` advancing, `error` null.

`/uploads/{name}` 307s to a presigned bucket URL whenever a durable store is active. So
**switching the bucket on silenced every client's review player at once**, including files
uploaded months earlier — which is exactly what was reported and exactly why chasing the
newest upload found nothing: the newest upload was never the variable. The redirect cannot
be detected from the browser (the element keeps the requested URL in `currentSrc`), so the
server stamps the script tag (`wave-live.js?…&offsite=`) and the tap is refused for any
`/uploads` element on such an instance. It **fails closed**: only an explicit `offsite=0`
opens the tap, so a template that forgets the flag costs a still waveform, never a silent
client. Verified under the production shape — a real cross-origin 307 with the real script:
`offsite=1` → never tapped, element plays; `offsite=0` → tapped, waveform works.

The durable fix, when someone wants the waveform back on a bucket instance, is CORS on the
bucket plus `crossorigin="anonymous"` on the element — deliberately NOT done here, because
a bucket without the CORS rule would then fail the media outright instead of merely
dropping the decoration.

**Amended 2026-08-05 (fourth) — the wave is back, and it has to EARN the audio.** Operator
asked for the animation back. Cross-origin media can be analysed with a CORS rule on the
bucket plus `crossorigin="anonymous"` on the element, but that attribute is exactly the
trap described above: set against a bucket with no rule it does not degrade to a still
wave, it makes the media fail to load outright — trading the client's playback for a
decoration, which is the mistake this whole incident was, made deliberately.

So nothing is assumed. Each player PROVES the bytes are CORS-readable before touching the
element: a one-byte `Range` GET shaped exactly like the request the media element will
make (a rule that allows a bare GET but not the `range` header would pass a lazier probe
and then fail the real load), `no-store` so the answer is never a response cached from
before the rule existed, fired at page load while `preload="none"` means nothing has
loaded yet and the attribute can still be added without a reload. Only a proven-readable
response earns `crossorigin` and the tap. If the media fails anyway, the element drops the
attribute, reloads, resumes, and gives up the wave permanently — and a `data-wave-cors`
handshake stops the player reporting "this file did not load" during a recovery that is
about to succeed.

Verified in a browser across four bucket configurations: rule present → tapped, playing,
signal peak 211; no rule → untapped, playing; same-origin → tapped, peak 216; rule present
but broken for the real load → recovered, untapped, playing at 1.15s. **A misconfigured
bucket costs the animation and never the audio.** Turning the wave on for an instance is
therefore an ops action with no downside: add the CORS rule to the bucket and the players
pick it up by themselves.

### ADR-0044 — `app.py` comes apart one measured slice at a time
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` Phase 3 (`app.py`
into modules) · `web/shell.py`, `web/agencies_routes.py`, `web/app.py`
**Decision.** Route groups move out of `app.py` into `*_routes.py` modules as
`APIRouter`s, **one group per pass**, each pass ending with the full suite green.
`shell.py` holds the few genuinely shared web primitives — the Jinja environment,
`render`, `public_base` — and knows nothing about routes or domain engines. The
environment is **created** in `shell.py` and still **decorated** in `app.py`: every
`templates.env.filters[...] = ...` line stays put, operating on the same object.
Dependencies point one way only: `app.py` → route module → `shell.py`.
**Why.** `app.py` reached **9,133 lines and 251 routes**. The blocker for moving *any*
route was that `render` and the template environment lived in `app.py`, so a router
importing them and `app.py` importing the router was a cycle. `/agencies` went first on
measurement, not taste: **26 routes (10% of the file) referencing only four `app.py`
helpers**, against 23 for `/opportunity` and 29 for `/project`; no route-pattern
collision with any other group; and only one route (`/relationships`) interleaved in its
span, so the block could move without changing which handler answers any URL. The two
helpers used only here moved with it, and `_profile_from_row` — shared with one
`/sources` route — now lives in the router with `app.py` importing it back, which is the
allowed direction.
**Consequences.** `tests/test_app_structure.py` fails if a route module imports `app.py`,
if `shell.py` grows a route or reaches into an engine, if a moved group is still declared
in `app.py`, if `app.py` grows past 8,600 lines, or — the failure this pass actually hit —
**if a moved module uses a name it neither defines nor imports.** Two module-level
constants stayed behind, so the module imported cleanly and raised `NameError` on the
first request: import success is not evidence that a move is complete, and that test is
the evidence. **225 routes remain in `app.py`** (8,545 lines). `/opportunity` (58) and
`/project` (57) are the large, tightly-coupled pair and want their shared helpers
(`_load`, `_brief_for`, `_outreach_for`, `_quote_band_for`) relocated before their routes
follow — that is a later pass, not an afterthought to this one.

**Slice 2 (2026-08-04) — the discovery surface.** `/signals` (10), `/discovery` (7),
`/sources` (4) and `/leads` (4) → `discovery_routes.py`: **25 routes with zero references
to any `app.py` helper**, and a group the console's own nav already treats as one section.
Unlike `/agencies` these were **not** contiguous — ten unrelated routes (the dashboard,
the admin login, `/incoming`, an opportunity delete) were interleaved through their span —
so the extraction was per-route rather than one cut, with relative order preserved.
`_safe_local` moved to `shell.py` as `safe_local`: an open-redirect guard is a web
primitive, it is shared by `/admin`, `/opportunity` and `/talent`, and leaving it in
`app.py` would block every future slice that accepts a `return_to`. The unresolved-name
guard earned its place again immediately — `os` and `Optional` were missing from the new
module, which imports cleanly and would have raised `NameError` on a request.
**app.py: 8,545 → 8,051 lines; 201 routes remain.** `/talent` (11) + `/payouts` (4) are
the next natural group but their routes are scattered across ~4,000 lines rather than
clustered, so that pass is a gather rather than a cut and is deliberately not bundled
here.

**Slice 3 (2026-08-04) — the supply side.** `/talent` (11) + `/payouts` (4) →
`talent_routes.py`: the console's **Supply** section, minus the Match Board, which
reaches into the opportunity helpers and waits for that pass. **The "scattered across
4,000 lines" note in slice 2 was wrong** — measured, both are *contiguous blocks*
(`/talent` at 3751–4043, `/payouts` at 7847–7901); 4,000 lines was the gap *between* the
groups, not scatter within them, so this was a straightforward cut. `_parse_rate` and
`_clean_rate_unit` were defined inside the talent block and moved with it, along with
`FORM_DISCIPLINES`, `_SOURCE_CHANNELS` and `_ADD_SOURCES`; `app.py` imports `_parse_rate`
back for `/opportunity` and `/proposal`, the direction `_profile_from_row` already
travels. **app.py: 8,051 → 7,662 lines; 186 routes remain** — down from 251 and 9,133
lines, so a third of the file and a quarter of the routes have moved. What is left is
dominated by the coupled pair: `/opportunity` (58) and `/project` (57) are 62% of the
remaining routes and need `_load`, `_brief_for`, `_outreach_for` and `_quote_band_for`
relocated first.

**Slice 4 (2026-08-04) — the helper layer, not a route group.** The "four shared helpers"
this ADR named twice (`_load`, `_brief_for`, `_outreach_for`, `_quote_band_for`) **were the
wrong four.** Measured: of the 46 `app.py` helpers `/opportunity` and `/project` reach for,
only `_load` and `_persist_upload` are shared between *those two* — `_brief_for` and
`_outreach_for` are `/opportunity`-only and `_quote_band_for` is `/project`-only, so none
of the last three blocks anything. The real blockers are the **16 helpers called by two or
more route groups**, whose transitive closure is **31 functions and 5 constants**. Those
moved; the single-group helpers stay to travel with their own routes later.

The closure was not filed by taste. Its call graph has **ten connected components**, and
they sort into four modules with no component straddling a boundary: `uploads.py` (the
write door), `billing.py` (proposal → invoice → payment → receipt), `delivery_ops.py`
(approve → package → finalize → notify), `opportunity_ops.py` (open a record, reconcile a
stage, assemble a buyer). The admin-auth trio (`_admin_secret`, `_admin_cookie_value`,
`_admin_authed`) went to `shell.py` — an env var and a cookie, the same category as
`safe_local`; the gate *middleware* and the public-path allowlist stay in `app.py` because
they are properties of the application object. Imports flow one way: `delivery_ops` →
`billing`/`uploads`, nothing back, enforced by a test.

Every name is imported back into `app.py` under its original spelling, so **not one of the
186 remaining handlers was edited** — a relocation that renames is two changes wearing one
commit. **`UPLOAD_DIR` is the exception, and the one real trap:** a dozen test modules set
`CHORDENTIAL_UPLOAD_DIR` and reload only `db` and `app`. A module-level constant in
`uploads.py` would never see the new value, because `from .uploads import UPLOAD_DIR` binds
a *value* and reloading `app` does not re-execute `uploads`. So `uploads.upload_dir()` reads
the environment per call and `app.UPLOAD_DIR` is computed from it at app-import time. The
frozen-constant shape was built deliberately to confirm the new test catches it: it fails,
and it silently redirects writes into the installed package directory — which is the
`/var/data` persistence bug of ADR-0043 all over again.
**app.py: 7,662 → 6,917 lines; 186 routes remain** (this pass moved no routes — 745 lines
of helpers, which is what unblocks the next two). Suite 1,321 → 1,356 tests.

**Slice 5 (2026-08-04) — the opportunity surface.** `/opportunity` (58 routes) →
`opportunity_routes.py`, the largest group in the file and the one the previous slice
existed to unblock. The measurement says so plainly: before slice 4 these routes reached
21 `app.py` helpers; after it, the number they reach that is **shared with any other
group is zero**. All twelve remaining helpers (`_brief_for`, `_outreach_for`,
`_build_review_for_opp`, `_compose_state`, `_save_proposal_edits`, …) and four constants
are used by this group and nothing else, so they travelled with it. Like the discovery
slice this was **not** one block — 31 unrelated routes (the client workspace, the creator
portal, the Match Board, the buyer pages, `/uploads`) sit inside its span — so the
extraction was per route in source order. Zero route-pattern collisions against the other
212 routes, checked before moving anything.

**One correction to slice 4.** It recorded `_quote_band_for` as "/project-only … blocks
nothing." That was measured at *route* level only, and it was wrong: `/opportunity`
reaches it through `_brief_for`, so the moment `_brief_for` left, `_quote_band_for` became
cross-module and had to move — it now sits in `opportunity_ops.py` with the rest of the
shared layer. The lesson is specific: **for "is this helper shared?", direct callers are
not enough; the transitive closure is the answer.** Slice 4 computed that closure to
decide what to move and then used a direct-callers count to decide what was safe to leave.

**The bug this pass hit** was in the extraction itself, not the code: `ast` puts `.lineno`
on the `def`, **not** on the decorators above it, so slicing a route by `.lineno` leaves
`@app.post(...)` behind in `app.py`, bound to whatever definition follows. Here it failed
loudly (a `SyntaxError` on the first import) but the dangerous shape is silent — a
decorator sliding onto a neighbouring function registers a real URL against the wrong
handler. Two tests now pin it: each router carries its whole group and nothing outside its
prefix, and the **total route count across `app.py` plus the routers is conserved at 252
with no (method, path) declared twice.**

Equivalence was proved by comparison, not assertion: a git worktree at the previous commit
ran the old tree on one port and this one on another, against identically seeded
databases. All 58 routes returned the same status, every GET returned a **byte-identical**
response, twenty neighbouring pages likewise, and the same three writes produced the same
stored rows on both. **app.py: 6,917 → 5,204 lines; 128 routes remain** — from 9,133 lines
and 251 routes. Suite 1,356 → 1,365.

Four test files stopped reaching engines and `/opportunity` helpers through `app_mod` and
now import the module that owns the code. That is the point rather than a side effect:
`app.py` should not be a namespace for the package.

**Slice 6 (2026-08-04) — the project surface, and the end of the large groups.**
`/project` (57 routes) → `project_routes.py`: the operator's delivery console, the
client's review portal, the session room and the payment door. **app.py: 6,917 → 2,725
lines; 71 routes remain** — from 9,133 lines and 251 routes, so **70% of the file and
72% of the routes have moved.**

Measured as a **transitive closure from both sides**, since slice 5 proved direct callers
insufficient: everything reachable from a `/project` route, minus everything reachable
from any other route. That left 25 names exclusive to the group (609 lines, including the
277-line `_delivery_view`), and three shared only with `/creator`, which went into the
helper layer instead — `uploads._read_capped`, `delivery_ops._project_estimate`,
`delivery_ops._sync_role_milestones`.

Two measurement bugs surfaced and both are worth keeping:
* the closure must exclude **local** bindings. `_delivery_view` assigns
  `manifest = build_manifest(...)`, and a naive walk read that as a reference to the
  module-level `/manifest.webmanifest` **route handler** — which would have moved that
  route out of `app.py` by accident.
* the collector must handle **`AnnAssign`**. `_PRESENCE: dict = {}` is annotated, so a
  collector that only understood `ast.Assign` never saw it, and the module would have
  raised `NameError` on the first session-room poll.

**A finding, reported rather than acted on** *(closed 2026-08-05 — see the amendment to
ADR-0037; the function is deleted and the naming contract is now guarded behaviourally).*
`_append_version_from_bytes` (40 lines) has **no callers anywhere** — not before this slice
either. Its docstring claims it is "shared
by the admin Assets agent and the composer portal"; both call sites were rewritten at some
point and this was left behind. `tests/test_naming.py` inspects its *source* to assert the
master-naming scheme, so a test is keeping dead code alive while the live write path goes
unguarded. It moved with the group unchanged; deleting it means first repointing that test
at the real path, which is a deliberate piece of work and not a refactor footnote.

**A guard that had gone blind.** Three drift guards enumerate `app.app.routes` — the
review-action gate exemption, the creator-POST gate exemption, and the duplicate-Stripe-
webhook check. This FastAPI version wraps an included router in an `_IncludedRouter` with
no `.path`, so those loops stopped seeing every group the breakup moved: **81 routes
visible where there are 274.** `tests/conftest.registered_routes()` now flattens included
routers and all three use it. The review guard's own "test wiring is stale" assertion is
what caught it.

Equivalence was again proved by side-by-side comparison against a worktree at the previous
commit: all 57 routes the same status, every GET **byte-identical** (including the client
delivery portal at 34,372 bytes and the 402 payment gate), seventeen neighbouring pages
identical, and the same writes producing the same rows. The one apparent difference — the
delivery ZIP, 299,635 vs 299,636 bytes — was opened and diffed entry by entry: identical
except `metadata.json`'s `generated_at`, five seconds apart. Suite 1,365 → 1,372.

**Slice 7 (2026-08-04) — the creator portal.** `/creator` (6 routes) →
`creator_routes.py`. **The cleanest extraction of the series, and only because the earlier
ones did their job:** one contiguous block (L1891–L2126), **zero** interleaved routes, and
**zero** helpers shared with any other group — everything it reached that another group
also uses had already moved into the helper layer in slices 4 and 6 (`_read_capped`,
`_store_pending_submission`, `_project_estimate`, `_sync_role_milestones`). Four names
were exclusive and travelled with it (152 lines). Zero route-pattern collisions against
the other 264 routes.

Equivalence was proved on the **happy path**, not just the error paths, which took
setting up the data: the seeded book has no creator carrying a `portal_token`, so the
first comparison run agreed only on 404s and 422s — a green result that proved nothing.
Minting an identical token on both trees produced the real check: the portal renders
**byte-identical at 80,734 bytes**, a version submission through
`uploads._store_pending_submission` stores the same `pending_version` (`by='Devin Park'`,
`orig='take.mp3'`, url present) on both, the portal re-renders identically at 81,146
bytes afterwards, and a note reply + address pair matched.

**app.py: 2,725 → 2,326 lines; 65 routes remain** — from 9,133 and 251, so **75% of the
file and 74% of the routes have moved.** What is left is the application object itself
(lifespan, middleware, the admin gate, the PWA endpoints) plus seven small groups —
`/campaign` (7), `/simulator` (7), `/workspace` (5), `/admin`, `/matchboard`, `/invoice`,
`/push` (3 each) — and the singletons.

One test followed the code: `_SUBMISSION_MAX_BYTES` moved with the group, and the cap test
patched it on `app`. That one failed loudly (`monkeypatch.setattr` raises on a missing
attribute), unlike slice 6's `_notify_operator_review`, where the name still existed on
`app` as a re-export and the patch silently stopped affecting the route. **A re-export is
what makes a stale patch site quiet** — worth knowing for the remaining slices.

**Slice 8 (2026-08-05) — the campaign workspace.** `/campaign` (7 routes) →
`campaign_routes.py`. One contiguous span (L1836–1985), zero interleaved routes, one
exclusive helper (`_campaign_view`), zero shared, zero collisions against the other 263
routes. Every route is behind `campaigns.workspace_enabled()`, so with the flag off the
whole module answers 404 and can move without touching any other surface.

Equivalence again needed real data before it meant anything: the seeded book has **no
campaigns**, so the first comparison run agreed on 404s and 400s. Creating an identical
campaign on both trees gave the real check — Campaign Home renders **byte-identical at
28,630 bytes**, three writes (direction, phase, agency) return identical status and
identical byte counts, the phase advances to `Direction` on both, and the direction text
appears twice in the rendered page on both. **That is now the second slice running where a
green first pass proved nothing; the seeded dataset does not cover every surface, so
"identical error pages" has to be recognised as a non-result.**

**Dead imports, cleaned and counted.** Comparing against a *stale* pyflakes baseline had
been hiding what earlier slices left behind: `app.py` carried **39 unused imports**. 17
were genuinely dead — five `..delivery` engine names, `Opportunity`, `Talent`,
`normalize_url`, `_profile_from_row`, `File`, `UploadFile`, `Jinja2Templates`, `List`,
`_AUDIO_EXTS`, `_CUT_MIRROR_BYTES`, `directory_crawl`, `outreach_engine`, `campaign_intake`
— and are gone. **22 remain, deliberately, and they are a finding rather than a tidy
result:** 15 are helper re-exports pinned by `test_a_moved_helper_is_defined_once_and_still_reachable`,
and 7 are engine modules (`decision_makers`, `directory_parsers`, `enrichment`,
`intelligence`, `music_opportunity`, `opportunity_signals`, `signals`) that only *tests*
reach through `app_mod`. Both groups exist so tests can use `app.py` as a namespace for
the package — the exact pattern slice 5 corrected for `procurement` and
`producer_learning`. The re-exports were justified when `app.py` still held 186 routes and
editing no handler was the point; with 58 routes left, that justification has expired.
Closing it means repointing the test sites, which is its own pass.

**app.py: 2,326 → 2,128 lines; 58 routes remain** — from 9,133 and 251, so **77% of the
file and 77% of the routes have moved.** Suite 1,376 → 1,380.

**Slice 9 (2026-08-05) — the objection simulator.** `/simulator` (7 routes) →
`simulator_routes.py`. **No helpers at all** — the whole surface delegates to
`web/simulator.py`, so the module is the thinnest of the series: open a connection, call
the engine, render. One contiguous span, zero interleaved routes, zero collisions against
the other 263.

**Declaration order is load-bearing here and nowhere else in the breakup.**
`GET /simulator/library` and `GET /simulator/{session_id}` both match the URL
`/simulator/library`; the literal wins only because it is registered first. The extraction
preserved source order for exactly that reason, and a new test pins it — verified by
swapping the two declarations, which fails the test, and confirmed live on both trees
(the library page renders at 30,131 bytes with objection content on each). Reorder them
in a later pass and the library silently becomes a session lookup for a session named
"library".

Equivalence was proved through the whole flow rather than the landing page: start a
session (identical id 1 on both), GET it (16,664 bytes each), say a line (16,940 each),
end it (16,330 each), and re-read — with the stored transcript matching on persona, mode,
status and turn count. A library status write stored `'confirmed'` on both. The first
attempt used an invalid persona and silently redirected to the home page on both trees —
another green-but-empty result, caught by checking that a session row actually appeared.

**app.py: 2,128 → 2,004 lines; 51 routes remain** — from 9,133 and 251, so **78% of the
file and 80% of the routes have moved.** `.simulator` left `app.py`'s import list
entirely: no test reached it through `app_mod`. Suite 1,380 → 1,385.

**Slice 10 (2026-08-05) — the client workspace.** `/workspace` (5 routes) →
`workspace_routes.py`: the durable token-gated URL (ADR-0018), the client's scope
confirmation, the court-state poll and the two approval doors. One contiguous span, zero
interleaved routes, three exclusive helpers (121 lines), zero shared, zero collisions
against the other 265 routes.

**This is the surface where the client's own action drives state** — approving the
Commercial Review is the award trigger that creates the project — so the equivalence run
had to reach that write, and the first attempt did not. With no released review the
approve route is a no-op: 200 and byte-identical on both trees, and empty as evidence,
exactly the pattern of the last three slices. Releasing an identical review on both made
it real: **opp → Won, review → approved, project id 5 created with the same client, need
and inherited share token, workspace re-rendering byte-identical at 11,679 bytes, and
matching court signatures (`Won:proj:approved:sc::0:`).**

The workspace was also compared at three lifecycle phases by minting deterministic tokens
on both trees — New (6,476 bytes), Submitted (6,485), Won-with-project (5,782) — all
byte-identical, with `court.json` matching down to the signature string, an unknown token
404ing on both, and ten neighbouring pages identical.

**app.py: 2,004 → 1,574 lines; 46 routes remain** — from 9,133 and 251, so **83% of the
file and 82% of the routes have moved, and `app.py` is under 2,000 lines for the first
time.** `commercial` and `workspace` left its import list entirely. Suite 1,385 → 1,389,
with no test needing a change — the first slice of the series where nothing was reaching
through `app_mod` into what moved.

What is left is the application object (lifespan, middleware, the admin gate, the PWA
endpoints) and 46 routes across 30 tiny groups, none larger than three.

**Slice 11 (2026-08-05) — the remainder, and the end of the breakup.** The last 31
routes left `app.py` in three modules, chosen by what they are rather than by size:
`console_routes.py` (19 — the dashboard, both inboxes, the buyer directory and profile,
the Match Board, the project index, revenue, the queue, the company profile, the triage
and chips triggers), `billing_routes.py` (7 — proposal price, invoice status, checkout,
the pay return and the Stripe webhook), and `meetings_routes.py` (5 — the client's pick
page, the operator's manage view, the capture hook). Zero shared helpers between the
three; three helpers travelled with the console and nothing else moved.

**`app.py` is now 655 lines and 15 route declarations, and every one of them belongs to
the application object:** the admin-gate middleware and its public-path allowlist,
`/healthz`, `HEAD /`, the four PWA endpoints, the three Web Push endpoints, the three
admin doors, and `/uploads/{name}`. From **9,133 lines and 251 routes** — 93% of the file
and 94% of the routes have moved, into a shell, nine route modules, three more, and a
four-module helper layer.

**The re-export debt is paid, and it was larger than it looked.** With the routes gone,
`app.py` was importing **55 names it does not use** — every one there so a test could
reach it through `app_mod`. 35 were pure dead weight and 20 were reached by tests, 104
references across 28 files, all now pointed at the module that owns the code.
`test_a_moved_helper_is_defined_once_and_still_reachable` was replaced by
`test_a_moved_helper_lives_in_exactly_one_place` (a name → owning-module map) plus
`test_app_py_imports_only_what_it_uses`, which is the exact instrument: **an unused import
IS a re-export.**

**The re-export debt was also hiding two dead tests.** `test_client_payment` patched
`app_mod.get_payment_provider` and then posted to `/webhooks/stripe` — a route that had
just moved. Both tests failed loudly once the re-export went, which is the good case;
the point is that they were only ever one re-export away from passing while testing
nothing. Every remaining `monkeypatch` through `app_mod` was checked: the rest mutate a
module *object* (`app_mod.mailer.send_email`), which works regardless of who imported it.

Equivalence: all 31 routes identical against a worktree at the previous commit, and the
writes exercised with real records — a buyer website set, a Match Board assign creating
the same project id 5 and the same assignment row on both, the matching unassign, and a
meeting cancelled through its manage token (`scheduled → canceled` on both, wrong token
404 on both). Ten neighbouring pages identical. **Route declarations across the whole web
package: 252, distinct 252 — the same number this ADR started with.** Suite 1,389 → 1,405.

One process note worth keeping: the scripted import insertion put a line **inside a
parenthesised import** in `test_delivery.py`, which is why the sweep ends with an AST parse
of every file it touched rather than a grep. A mechanical edit needs a mechanical check.

### ADR-0087 — A client can hear what they are asked to approve
**Status:** Accepted (2026-08-21, operator directive) · Extends ADR-0068 (subtractive
room) and ADR-0043 (the write door) · Source: `room.route_media` / `room_view(media_token=)`,
`room_routes.one_room`, `project_routes._is_stream_request` / `delivery_download`,
`db.delete_project(force=)` / `PROJECT_DELETE_OVERRIDE`, `delivery_console.html`,
`tests/test_the_client_can_hear_what_they_sign.py`,
`tests/test_one_history_and_a_door_out.py`

**Decision.** Three rules.

1. **A client's room routes every media URL through the client's own door.**
   `/uploads/{name}` is behind the admin gate; the buyer travels
   `/project/{id}/dl/{name}?k=…&stream=1`. Done as a **blanket walk** of the finished room
   (`route_media`), not field by field — the surfaces carrying media keep multiplying, and
   a per-field list is one someone has to remember to extend. It runs **after** the
   subtraction, so a URL that was removed cannot be routed back in.
2. **Streaming is not the paywall's business.** A valid client token plays media inline
   whether or not the balance is settled. The package and every real download stay gated —
   that is what the balance buys.
3. **A delete refusal must name a door that exists.** Each refusal is overridable with an
   explicit second press that states what it destroys (`PROJECT_DELETE_OVERRIDE`).

**Why.** *"I pushed the approved newly uploaded stems from the studio to the client, and i
dont see the clients ability to download or listen to the new uploads that were pushed."*
Measured, it was worse than the stems: **every media URL in the client's room 303'd to the
admin login**, so a buyer's player rendered silence for the master they were reviewing as
well as the deliverables they were signing off. Timed notes still worked, which is what hid
it — you can leave a note at 0:12 on a player that never played.

The second half was the paywall. `/dl/` answered a client token with 402 for everything
until the balance was settled, while its own message read *"You can still stream and review
the work."* You could not. **Asking someone to approve a file they are forbidden to hear is
not a paywall, it is a broken review.** The trade is deliberate and worth stating: a
determined listener can capture a stream, every review platform in this industry accepts
that, and the alternative is a client approving work unheard.

The third came from the same screen: *"what does it mean to reopen, i dont know how to do
that and this is a demo project if i want to delete it, let me delete it."* The refusal for
a Delivered project advised reopening it first. **There is no reopen.** Advice naming an
action the product does not have reads as though the door exists and the reader is too
stupid to find it. The refusals are a speed bump, not a wall: each protects a record that
matters on a real deal, and each is wrong about a rehearsal.

**And one history.** The console carried an Activity feed and a Campaign timeline — the
same events twice, differing only in that the timeline also named the version uploads. Two
renderings of one history is how they drift (ADR-0029, ADR-0033), and the page had grown
long enough that neither could be read to the bottom. One list now, folded by the version
each note was left against, current take open, counts on every shut summary — because a
collapsed section that hides its own count is why people stop opening them.

**Consequences.** `dl_url` is deliberately excluded from the rewrite: it is the real
download and must not become a streaming URL. The stream mode relaxes the paywall, never
the credential — a bad token still 404s. And a forced delete is still a second, deliberate
press: overridable is not the same as absent.

### ADR-0086 — Every send is recorded, sent or not
**Status:** Accepted (2026-08-21, operator directive) · Extends ADR-0066 (the branded
shell IS the email) · Source: `mailer.set_recorder` / `_record`, `web/outbox.py`,
`db.record_outbound` / `list_outbox` / `OUTBOX_STATUS`, `signals._record_alert`,
`console_routes.outbox_page` / `outbox_one` / `outbox_clear`,
`tests/test_what_the_client_actually_receives.py`

**Decision.** Every outbound message — email and phone/web alert alike — is recorded to an
`outbox` table with its recipient, subject, plain text, **rendered branded HTML**, status
and attachment count, whether it was actually sent (`sent`), recorded only because no
provider is configured (`logged`), attempted and failed (`error`), or had no channel at all
(`unset`). `/outbox` reads them; one message can be previewed exactly as it lands.

Storing the HTML is the load-bearing part. The branded shell is what the recipient sees
(ADR-0066); keeping only the plain text would answer *"what does my client receive?"* with
something the client never sees — the original defect, one layer down.

The recorder is **injected, not imported**: `mailer` is the engine layer and must not reach
up into `web` (ADR-0044), so it exposes `set_recorder` and `web.outbox.install()` fills it
at boot — the same shape as `room_view(build=…)` and `final_invoice_block(heal=…)`.
`outbox.py` sits at the bottom of the helper DAG beside `uploads`, reaching only `db`,
because it is written from a fire-and-forget mail thread and must not drag a higher helper
into one.

**Why.** Asked how to test the product end to end without borrowing a person to play the
client: *"will this rehearsal console demo emails sends, and alerts?"* It could not have.
**Twenty-seven call sites send mail and nothing recorded any of them.** On the null
provider — the default, and what any rehearsal runs on — a send was one line of
`logger.info` carrying a recipient and a subject and no body at all.

So the emails were the one part of the client's experience that could not be looked at.
Every other defect in that experience this month was found by sitting a real person in
front of a real screen; the emails could only be inspected by configuring SMTP and mailing
a real inbox, which during a rehearsal is worse than not testing — a rehearsal deal that
borrowed a real contact would mail a real client. And in production, *"did the pay link go
out, and to whom?"* had no answer at all: a notification is best-effort and silent by
design, which is right for the request and wrong for the record.

**Consequences.** The outbox holds every client's address and the full text of what we told
them, so it stays behind the admin gate; the preview is framed with `sandbox`, a
`default-src 'none'` CSP and `nosniff`, because replaying stored content is not the same as
rendering a page we wrote today. Clearing is manual — a record that tidies itself is not a
record — and says plainly that it does not unsend anything. Recording may never fail a
send: every path swallows its own errors, the same rule `_log_decision` follows.

### ADR-0085 — A success URL is not a receipt, and a refusal is not a network error
**Status:** Accepted (2026-08-20, operator directive) · Extends ADR-0068 (capability
gating) and ADR-0072 (the taste gate carries a reason) · Source:
`payments.base.PaymentProvider.verify_return`, `payments/stripe.py`, `payments/null.py`,
`billing_routes.pay_return` / `pay_confirming`, `project_routes.review_asset`,
`project_routes.delivery_publish_asset`, `delivery.owner_for_asset_label`,
`tests/test_a_success_url_is_not_a_receipt.py`,
`tests/test_sending_a_deliverable_back_reaches_someone.py`

**Decision.** Three rules.

1. **Only the provider that issued a checkout may say it was paid.** `verify_return` joins
   the provider contract; Stripe's `success_url` carries `{CHECKOUT_SESSION_ID}` and the
   session is retrieved server-side. The invoice id is taken from the **verified session**,
   never from the query string. Anything unproven — no session, unpaid status, unknown id,
   network error — returns `{}` and applies nothing. The signature-verified webhook remains
   the authoritative door, so an unconfirmed landing costs seconds, never a payment.
2. **An unverified return is told nothing and given nothing.** It lands on `/pay/confirming`,
   which holds no token, names no project and reads no database. It must also never read as
   a failure: the common case is a real payer whose webhook is a second behind their browser.
3. **A refusal must be legible as a refusal.** Every press the room makes over `fetch`
   answers in JSON with a reason. A redirect or an HTML 404 is indistinguishable from a
   dead connection once `fetch` has followed it.

**Why.** `GET /pay/return?invoice=7` was exempt from the admin gate and applied the payment
on sight — marking it Paid, unlocking the client's downloads, queueing the crew's payouts
and emailing a receipt, for anyone who typed a small integer. The same request answered with
a redirect whose `Location` carried `ensure_project_share_token(pid)`, so guessing a number
also handed out the credential that opens that client's delivery portal. One request, two
holes, same cause: **input the payer controls was treated as proof of something only the
provider knows.**

The third rule came from the operator, twice in two days: *"Im still getting this error
trying to approve a composer's upload and push to client"* — **"That didn't go through.
Check your connection and try again."** There was no connection problem. The client's
per-deliverable sign-off form rendered for **every role with no capability check**, though
`sign_off_asset` is client-only in `room.CAPS`; the studio pressed a button that was never
theirs, the token-gated route answered 404, and `fetch` had no vocabulary but the network.
The control is now subtracted for anyone without the capability and replaced with the honest
state — *published, waiting on the client* — which is what the studio actually wanted to know.

**And the rejection nobody heard.** The master's send-back has carried a reason since
ADR-0072. The DELIVERABLE gate had not: `discard` deleted the mixer's stems from both copies,
wrote a line only the studio reads, and told the mixer nothing. It now takes a reason,
records a `sent_back` event the creator's room shows (audience `operator,talent` — the buyer
never sees us rejecting our own supplier), and emails the craft that owns the lane.

Wiring that surfaced an **older, silent defect**: `deliverable_owner` keys off *(asset,
group)*, but both callers passed the lane's label — the asset alone — so every lookup
returned `""`. The ADR-0075 hand-off telling the editor their mix had landed had therefore
**never fired since the day it shipped**. `owner_for_asset_label` resolves the label through
the project's scoped list, where the group lives, and both callers use it.

**Consequences.** Checkout sessions created before this change land unverified and settle via
the webhook — correct, a few seconds slower. The Null provider never vouches, which is right:
it never takes a payment and no payer is ever sent to a success URL under it. The room's
error vocabulary now distinguishes *refused*, *not yours*, *already handled* and *actually
offline*; a fourth press that cannot be honoured should add a reason, not reuse "network".

### ADR-0084 — Whatever we accept, we must be willing to keep
**Status:** Accepted (2026-08-20, operator directive) · Supersedes the ceiling set by
ADR-0026 · Extends ADR-0043 (the write door) · Source: `uploads.mirror_cap` /
`Stored` / `media_durable` / `boot_line`, `db.save_media_blob` / `media_blob_size` /
`is_postgres`, `tests/test_the_storage_you_already_have.py`,
`tests/test_postgres_dialect.py::test_a_large_take_survives_a_deploy_on_real_postgres`

**Decision.** The database mirror's ceiling is no longer one hardcoded number. It is
`uploads.mirror_cap(conn)`, decided in one place, and on Postgres it equals **the largest
file the upload doors will accept** (512 MB). The rule it expresses:

> Whatever we are willing to accept, we must be willing to keep.

Three consequences follow. `_persist_upload` returns `Stored(ok, durable, reason)` instead
of a bare bool, so the one door every upload passes through can finally answer *will these
bytes survive a deploy?* — a question nothing in the system could previously ask. A file
over the ceiling is still **stored** (refusing real work to protect a policy is worse) but
is announced at the moment it happens and marked on the surface while it is still there to
save. And durability is **measured** (`media_durable`), never stamped: the ceiling can be
raised and a bucket can be configured, so a flag written at upload time would eventually
warn about a file that is fine and stay silent about one that is not.

On SQLite the old ceiling and ADR-0026's reasoning both stand — a feature-length cut
blobbed into a SQLite file really is worse than the risk it covers. The number was never a
fact about Postgres.

**Why.** *"i dont want to take the steps to setup more storage i want to use the storage i
have and not lose files."* The durable store was already there and only half-wired.
Measured against a real Postgres 16, with the container's disk removed the way Render
removes it:

| | before the deploy | after |
|---|---|---|
| 5 MB stem | 200 | **200 — every byte back** |
| 70 MB cut | 200 | **404** |

Both were accepted by the same door, on the same day, with the same success message.
ADR-0026 set the ceiling at 64 MB and said why: *SQLite*. Production cut over to Postgres
on 2026-08-06; the premise died and the number outlived it. That gap is where the files
went.

Two things were found on the way and are part of this decision. `save_media_blob` caught
`sqlite3.Error`, which on Postgres catches **nothing** — psycopg raises its own hierarchy —
so a mirror failure in production would have escaped into the upload route as a 500 with
the connection left poisoned for the rest of the request; both are caught now, rolled back,
and reported. And it returned nothing at all, so "mirrored" was an assumption: it now
confirms by reading the stored size back, because the caller stamps durability on the
strength of that answer.

**Consequences.** Everything the doors accept now survives a deploy on the storage already
being paid for, and object storage (S3/R2) stays deferred rather than urgent — it remains
the better answer for egress and for files beyond 512 MB, and the seam is still there. The
cost moves onto the Postgres bill, which is metered and more expensive per GB than a
bucket; `CHORDENTIAL_MIRROR_MB` is the dial if that becomes the binding constraint. The
boot line stops advising an operator to prepare for a cutover that already happened and
names the ceiling instead, because that is the number that decides whether their work
survives the night.

### ADR-0083 — A link is only a link if something is behind it
**Status:** Accepted (2026-08-20, operator directive) · Extends ADR-0043 (the write door)
and ADR-0074 (a lane holds a folder) · Source: `uploads.media_present` /
`uploads.forget_media`, `db.media_blob_exists`,
`project_routes.delivery_remove_asset` / `_asset_answer`,
`tests/test_a_lane_full_of_dead_links.py`

**Decision.** Three rules about a file in a deliverable lane.

1. **Presence is measured against BOTH copies.** `media_present(conn, name)` asks the
   object store and the durable DB mirror, because `serve_upload` answers from either. A
   row whose bytes are in neither is rendered struck through and unlinked, saying *"file
   is no longer on the server"* — never as a download.
2. **A file can be taken off a lane**, published or waiting, by the studio only. The row
   leaves `assets` and `pending_assets`, its per-asset approval goes with it (an approval
   of a file that no longer exists is the sign-off rollup counting nothing, and that
   rollup opens the paywall), the bytes are forgotten from both copies through the one
   door out (`forget_media`), and the project log says what went and why.
3. **A per-file press ANSWERS, truthfully, in the shape the caller can read.** The room
   vets over `fetch`; a press the server could not honour now returns `409` with
   `{"ok": false, "reason": "gone"}` instead of a redirect. A plain form post still gets
   its 303.

**Why.** Two reports, one sitting. *"it is still listing the individual track but they are
links to an empty container … i need a way to delete these useless links if they dont have
a function anymore."* And, pressing ✓ on a stem as the studio: **"That didn't go through.
Check your connection and try again."**

Both are the same defect. Production's disk is rebuilt on every deploy, so a lane
accumulates rows whose bytes are gone; nothing could remove one, because the per-file gate
only ever existed on files still WAITING and a published row had no control at all. And
when the studio pressed a row that had already moved on, the route answered with a
redirect — which `fetch` follows to an HTML page, so the JSON parse threw and the page
blamed the network. The operator went looking for a connection problem that was never
there. **A surface that reports the wrong cause is worse than one that reports nothing**:
it spends someone's afternoon.

**Consequences.** A gone file is not publishable — approving it would put a dead link in
front of a client — so its only press is remove. Send-back now forgets the mirror too; it
unlinked the disk path and left the mirror, and `serve_upload` reads the mirror, so a
rejected deliverable kept downloading. `_missing_asset_files` learned the same lesson in
reverse: it asked only the store, so a file that survives a redeploy in the mirror and
downloads perfectly was listed as lost and offered for re-upload. Presence is checked once
per render and cached per key — twelve stems are twelve rows and a key can appear in more
than one lane. On a durable store each check is a HEAD; if that ever bites, cache it, do
not stop asking.

None of this makes the underlying problem go away: **durable object storage is still
deferred**, and until it lands the disk keeps eating files on every deploy. This makes the
loss legible and clearable instead of silent.

### ADR-0082 — The mixer is not the writer, and signs a different document
**Status:** Accepted (2026-08-20, operator directive) · Extends ADR-0024 (the assignment
gate) and ADR-0059 (signatures) · Source: `service_agreement.py`, `agreements.py`,
`signing.DOC_SERVICE_AGREEMENT` / `DOC_SERVICE_COUNTERSIGN`,
`tests/test_the_agreement_a_mixer_should_be_asked_to_sign.py`,
`tests/test_a_mixer_signs_the_right_document.py`

**Decision.** The studio has TWO standing agreements, and **which one governs a creator is
decided in exactly one place** — `agreements.kind_for`, read from their disciplines.

- **Composer Agreement** — anyone who authors music (composition, sonic branding,
  arrangement). Unchanged.
- **Service Agreement** — anyone paid for craft on music somebody else wrote (mixing,
  sound design, supervision, licensing). New. No publishing; a fee stated per engagement;
  a grant of only what they themselves make; the production chain as a clause; an AI
  warranty that forbids *generating* and names the permitted processing chain explicitly.
- **Neither, when nothing says which.** A creator with no craft recorded gets no document
  and the surfaces say what is missing.

Any authoring discipline wins over a service one: the writer's agreement is the broader
instrument, it is what the Clearance Certificate stands on, and it does not stop someone
being booked to mix. The reverse cannot work — a Service Agreement carries no publishing.

Every reader of "has this person signed?" goes through `agreements`; a grep tripwire fails
the build if a surface pins itself to `DOC_COMPOSER_AGREEMENT` again.

**Why.** *"do i need to build out agreements for the audio engineers and editors for them
to sign?"* Yes — and the honest answer was worse than a gap.
`db.talent_assignment_blockers` is **role-blind**, refusing every assignment without
`agreement_executed_at`, and the only thing that set that field was the Composer
Agreement. Measured on a mixer's own row: a document naming them "the writer" on 45 lines,
conveying a **30% publishing share**, and landing clause 6A — collect a release from
everyone who *played* — on someone who engaged nobody. Not a missing feature. The wrong
instrument, required. Signing it would have handed publishing to a non-author and put a
grant of rights they do not hold into the chain of title the certificate warrants.

The Contributor Release already existed and its `ROLES` already contained "Engineer", but
it is the wrong shape: composer-issued, per project, about a performance on a recording,
and explicitly not about money. It is not a standing engagement agreement.

**Consequences.** Two documents means two ways to be wrong about which, so the routing is
a single function with a tripwire rather than a convention. The commercial terms shared by
both — the acceptance window, the kill fee, the 120-day payment backstop, the liability
cap, the governing law — are **imported from `composer_agreement`, never restated**; two
copies of a backstop is one backstop and one drift. The Service Agreement's clause 5 is
the deliberate soft edge: a sound designer who invents original material HAS authored
something, so they raise it before delivering and it is settled as authorship under the
Composer Agreement or it is not used — never quietly absorbed, because an unclaimed writer
on a cue sheet is a defect in our own chain of title. Known rough edge: `MusicDiscipline`
has no EDITING value, so a music editor is recorded under mixing or sound design today;
adding one touches `label`/`fit_weight`/`team_shape` and is a separate pass. Like the
Composer Agreement, this is plain-language standing terms and **not counsel-reviewed** —
that review is the operator's to commission.

### ADR-0081 — A record, not a flag; and a board you can take something off
**Status:** Accepted (2026-08-20, operator directive) · Extends ADR-0043 (the write door)
and ADR-0059 (signatures are append-only) · Source: `db.set_talent_w9_file`,
`talent_routes.talent_set_w9`, `creator_routes.creator_sign_agreement`,
`db.project_delete_block` / `PROJECT_DELETE_BLOCK` / `delete_project`,
`shell.templates.env.globals["delete_refusal"]`,
`tests/test_the_w9_is_a_document_not_a_date.py`, `tests/test_deleting_a_demo_project.py`

**Decision.** Three rules, one shape.

1. **Compliance state names the artefact, never asserts it.** The W-9 is a FILE, written
   through `_persist_upload` like every other piece of media, and `w9_received_at` is
   stamped from its arrival. Marking it received by hand stays — one that came by post is
   still a W-9 — and the surface says which of the two it is rather than showing one
   green tick for both. The stored form lives at `/uploads/{name}`, which is behind the
   admin gate: a document carrying a taxpayer ID never travels the token-scoped
   `/project/{id}/dl/` road that client media takes.
2. **A funnel stage is moved by the act that changes it.** Signing the standing agreement
   IS joining the roster — it is the moment a creator becomes assignable — so the
   signature advances `invite_status` to `Joined`. It never demotes.
3. **Anything that can be created can be removed, and the refusals are the feature.**
   `delete_project` refuses on `paid` (a paid invoice is an accounting record), `signed`
   (ADR-0059) and `delivered` (the record of work a client holds), and says which. It
   takes the project's own children and **keeps the opportunity** — a project is one
   delivery of a deal, and clearing the delivery must not clear the deal. The sentence
   explaining a refusal lives beside the check that produces it (`*_DELETE_BLOCK`),
   reported to templates through one `delete_refusal` global.

**Why.** *"is there a way for me to store the w-9 attached to each particular talent?
right now i just see a button. after the talent has signed their agreement shouldn't the
recruiting funnel move to 'joined'. I need a way to delete demo projects."* All three were
the same defect wearing different clothes: a **flag standing in for the thing itself**.
`w9_received_at` was a date the operator typed, proving nothing at the moment a payment is
questioned, and reading as done. `invite_status` was written only by the seeder, so a
creator with a signature on file sat in the funnel as someone we were still chasing. And
the board had no delete at all, so every rehearsal of the funnel left a demo in the
pipeline looking exactly like work.

**Consequences.** A "received" tick with no file behind it is now a legible state, not an
invisible one. Delete is deliberately narrow: it clears rehearsals, and the moment a
project acquires a real record it stops being deletable — which means the way to remove a
delivered project is to reopen it first, on purpose. The same refusal grammar now serves
the roster and the board, so a third one has a pattern to copy rather than a template to
paste.

### ADR-0080 — Chordential signs its own Clearance Certificate
**Status:** Accepted (2026-08-20, operator directive) · Extends ADR-0059 ·
Source: `signing.DOC_CLEARANCE_EXECUTED`, `ClearanceCertificate.executed` /
`execution_state`, `project_routes.delivery_execute_certificate`,
`tests/test_the_certificate_is_actually_signed.py`

**Decision.** The studio EXECUTES the certificate it hands over, under
`DOC_CLEARANCE_EXECUTED`, held to the same standard as the client's acceptance
(`DOC_CLEARANCE`): consent unticked by default, bound to `cert.signable_text()` at the
instant of signing, append-only, reported `SUPERSEDED` the moment a term changes. The
certificate prints the signer, the timestamp and the SHA-256 in place of the blank
line — and an UNSIGNED certificate says "NOT YET EXECUTED" rather than ruling a line that
reads as executed.

Operator-only, behind the admin gate: there is no token that should ever produce
Chordential's signature on Chordential's own warranty.

Reported as a hold AFTER the licence, deliberately — confirming the licence changes the
document, so asking for the signature first would guarantee a superseded one.

**Why.** *"Dont i need to have an actual clearance signature on the certificate? i was
never asked for that in the whole process."* Right on both counts. The certificate is the
studio warranting the chain of title — the thing that makes the delivery worth what a
client pays for it — and it shipped with `Signature: ____________` printed on it, with
nothing in the flow ever asking anyone to fill it. A warranty nobody signed is a
letterhead, and a ruled blank beneath one reads as executed.

**Consequences.** The signatures table stays the record (ADR-0059); the summary on
`delivery_json['certificate_executed']` exists only so the packager — which has no
database connection — can print what was signed. Any new operative term added to
`signable_text` will supersede existing signatures, which is the point: if it can change
what the studio warranted, it belongs in the digest. And the studio never gets a weaker
signing standard than the client it is asking to sign.

### ADR-0079 — The package is rebuilt when it is older than the work
**Status:** Accepted (2026-08-20, operator directive) · Source:
`delivery_ops._package_is_stale` / `delivery_held_by` / `DELIVERY_HELD`,
`delivery._seal_word`, `tests/test_the_package_the_client_paid_for.py`

**Decision.** (1) `_maybe_finalize_delivery` **rebuilds the ZIP when it predates its own
contents** instead of returning early on an already-Delivered project. The descriptor
records `asset_count` and `referenced_count`, so a package with holes is countable.

(2) A **seal states what the thing it is stamped on IS** — `DELIVERED` on a delivered
package — and carries the wordmark, not the studio's name typed in 9px caps.

(3) `delivery_held_by` names what is stopping a delivery, `licence` last and
**non-blocking**: the console and the queue say the Clearance Certificate reads DRAFT.

**Why.** *"I downloaded everything and it doesnt have the audio files in there."* The
packager was never the fault — it bundles every asset whose file is on disk. It only ever
RAN ONCE: the early return on `state in (Delivered, Released)` meant the ZIP was assembled
at whatever moment the delivery first reached that state, and every asset published
afterwards stayed outside it, listed in the manifest as delivered and absent from the
file. A client paid thousands and downloaded documents.

**Amended (2026-08-20, same day).** Rebuilding on finalize was not enough: an
already-Delivered project has no NEXT approval to trigger it, so the client went on
downloading the same hollow ZIP however many times they tried. The **download itself**
rebuilds a stale package before handing it over. And the counts are PERSISTED onto
`delivery_json['delivery_zip']` — they were computed and dropped, which is why a ZIP
holding only documents looked identical to a finished delivery on every screen. A package
with `referenced_count > 0` is not offered to the client as "Download everything"; they
are told it is being re-assembled, and the operator gets a queue card and a console
warning naming how many files are missing.

**Amended again (2026-08-20).** Rebuild re-zips what the system still HAS; when the files
themselves are gone it produces the same package of documents, and the operator is left
pressing a button that cannot help — *"im clicking rebuild package and nothing comes up
for me to input the assets"*. The console now NAMES the missing files and takes them
back: `POST /project/<id>/delivery/asset/restore`, multi-file, matching each upload to
the deliverable it belongs to by its original name (then in order), editing the asset row
IN PLACE and **moving the client's approval to the new key** — `db.asset_key` is the
filename, so a naive replace silently un-approves a deliverable they already signed. It
rebuilds the package on the way out.

**Consequences.** Anything that changes what a delivery CONTAINS must leave the package
stale-able — compare against `built_at`, never assume the file on disk matches the record.
And the licence hold is deliberately a REPORT, not a gate: confirming it gates Release
(a tested contract), and hard-gating Delivered on it would have stranded every delivery
already in flight the moment it shipped. The operator is told loudly instead, in both
places they look.

**Still open after this** (named so it is not mistaken for done): the Clearance
Certificate's signature line is a wet-sign blank, not the in-house electronic signature
ADR-0059 already provides; the branded HTML docs are not rendered to PDF unless a
headless browser happens to be importable; a lane holding twelve files shows twelve
identical labels in the manifest rather than their filenames; and `Docs/For-filing/`
lands a client in a folder of raw .txt/.csv before they find the branded documents one
level up.

### ADR-0078 — A delivery nobody can be billed for must say so, and be billable
**Status:** Accepted (2026-08-19, operator directive) · Extends ADR-0077 ·
Source: `billing.final_invoice_block` / `INVOICE_BLOCK_CLIENT` / `INVOICE_BLOCK_OPERATOR`,
`project_routes.project_raise_balance`, `tests/test_a_delivery_nobody_can_pay_for.py`

**Amended the same day (ADR-0078a).** The first answer — type the amount by hand — was
answering the wrong question. *"i thought that was already agreed upon when i got the
signature."* It was: the signed Discovery Summary carries the fee and the deposit, and
ADR-0067 writes them into `proposals` at countersign. A deal countersigned BEFORE that
code landed has the document and no row. So `billing._heal_proposal` writes it from the
SIGNED band via the same `_ensure_proposal_for_project`, a **Delivered** room raises and
issues its own Final invoice on open, and the hand-raise control is left for the case it
was actually for — a deal whose summary was never priced. The healer is **injected**
(`heal=`), because `billing` sits below `opportunity_ops` in the helper DAG and reaching
up would make the load order load-bearing again; every route surface passes it, and the
nav badge deliberately does not — a badge is the wrong place to be writing rows.

**Decision.** (1) `billing.final_invoice_block` names why a finished delivery cannot be
paid for — `noproposal`, `draft`, `zero`, or `""` for none. One derivation; the room and
the delivery console both read it and say it in their own words.

(2) The client is told the TRUTH ("Chordential is preparing your invoice for the
balance"), never our plumbing and never a comfortable lie about assembly.

(3) The operator can **raise the balance by hand** (`POST /project/<id>/invoice/balance`)
for a delivery with no proposal to raise it from. The amount is TYPED. Nothing infers a
price from the budget, the estimate or the quote.

**Why.** *"everything was approved by the client but nothing came up for the client to pay
remaining balance."* Reproduced exactly: creative lock ✓, every scoped deliverable
uploaded ✓, every file signed off ✓, `_ready_to_deliver` True, state **Delivered**,
package assembled — and then nothing. Every invoice path derives its amount from a stored
proposal and returns SILENTLY when there is none (`_ensure_final_invoice_issued`,
`project_create_invoice`, `client_pay`). A project that reached delivery any other way —
a deal entered by hand, a signature path that never wrote a proposal — locks its download
behind a balance that cannot exist and tells the client their files are "being assembled",
forever.

**Consequences.** The price is the operator's decision and stays that way; a route that
invents an amount to unblock itself would be the constitution's one prohibition
(§"the machine proposes, Jon disposes") broken at the exact place it matters most. Any
new state that stops a client paying belongs in `final_invoice_block` with words for both
sides — a delivery that cannot be billed is a business failure, and the only thing worse
than reaching it is reaching it quietly.

### ADR-0077 — A payment that cannot start says so
**Status:** Accepted (2026-08-19, operator directive) · Extends ADR-0076 ·
Source: `billing.PAY_NOTICES` / `pay_notice`, `project_routes.client_pay`,
`tests/test_pressing_pay_says_something.py`

**Decision.** (1) `/project/<id>/pay` needs a PROPOSAL only to raise an invoice that does
not exist yet. An invoice already issued (which is what `_ensure_final_invoice_issued`
does at ship time) is enough on its own.

(2) **Every bounce off that route has a sentence**, in one place (`billing.PAY_NOTICES`,
exposed as the `pay_notice` Jinja global), rendered by the room, the delivery portal and
the workspace: `unavailable`, `already`, `noinvoice`, `error`. An unknown flag says
nothing rather than guessing.

(3) A Pay pressed in the room returns to the room (`origin=room`).

**Why.** *"when it click it it does nothing."* Two faults compounding: the route required
a proposal unconditionally, so a delivery that had reached the paywall the normal way
bounced off that check — and it bounced with `pay=error`, which nothing anywhere
rendered. The client pressed Pay, the page reloaded, and not one thing on it had changed.

**Consequences.** On a payment button, silence is the worst possible reading: it is
indistinguishable from a broken system and from a charge that may or may not have
happened. Any new failure path off a payment route adds its flag to `PAY_NOTICES` in the
same commit, and the message says whether money moved — every one of these four says
plainly that it did not.

### ADR-0076 — The client signs off and settles in the room
**Status:** Accepted (2026-08-19, operator directive) · Extends ADR-0068, ADR-0074 ·
Source: `delivery_ops.scoped_signoff`, `creator_routes._room_fields`,
`room.CAPS['see_invoice','sign_off_asset']`,
`tests/test_the_client_signs_off_and_pays_in_the_room.py`

**Decision.** The delivery stage finishes where the work is heard.

(1) **`delivery_ops.scoped_signoff` is the one derivation** of "what is scoped, what has
landed, and has the client signed it off". The delivery console, the client's portal and
the room all read it — extracted verbatim from `_delivery_view`, which now calls it.

(2) **The client's room carries the sign-off**, keyed by `sign_off_asset`, IN THE ROOM
and not inside a sheet: every scoped deliverable with Approve / Request changes on the
ones delivered, "not delivered yet" on the ones outstanding. A lane shows EVERY file it
holds — each auditionable and named — and one press signs off all of them, because "I
approve the stems" is the decision a person is making, not twelve of them. A lane counts
as approved only when every file in it is, since that rollup drives the paywall. This is the OTHER HALF of `deliverables`, which is the lane view
(specs, craft, upload boxes) and is correctly subtracted from the buyer.

(3) **`see_invoice` is the client's and the studio's**, never a creator's. What the buyer
owes is not a creator's business and the package is not theirs to hand out. It is not
`see_money` — what the work cost us is a different fact and stays with the studio.

(4) **An approved version is not a button.** Once the creative lock is set the room says
so; **Request changes stays**, because approval is reversible on purpose and taking the
only way back would be worse than a stale button.

(5) **Vetting answers in place.** `delivery/asset/publish` returns JSON to an
`X-Requested-With: fetch` press so the Takes sheet stays open — approving four stems must
not mean opening it four times. No JS still posts and still redirects.

**Why.** *"The studio approved deliverables to push to the client but nothing went to the
client in the room view. also the room view still has an approve v2 button active … We
should be at the stage where the client clicks approve on the deliverables and they get
prompted to pay the remaining deposit."* All of it existed on the delivery portal; none
of it existed in the room, which is where ADR-0068 put the client. And the client's Takes
window was still showing the loading dock — the composer's private capture shelf,
labelled "yours alone, never the client's", and instructions for uploading into lanes.

**Consequences.** Money in the room is `see_invoice`-gated and shows only the buyer's own
outstanding balance and their package — never our cost, never to a creator. New copy in
the deliverables area asks which of the two views it belongs to: the lane (studio +
crafts) or the sign-off (the buyer). A second derivation of scoped sign-off state is a
defect: three surfaces agreeing about whether a delivery is finished is the whole point.

### ADR-0075 — Composer → mixer → editor is a chain, and the room knows it
**Status:** Accepted (2026-08-19, operator directive) · Extends ADR-0074 ·
Source: `delivery.role_key` / `deliverable_owner` / `owed_after`,
`creator_routes._room_fields`, `project_routes.delivery_publish_asset`,
`tests/test_the_chain_composer_mixer_editor.py`

**Decision.** The production model, in the engine (ADR-0002 — a fact about how the studio
makes records is not template logic):

| craft | owes | works from |
|---|---|---|
| composer | the master (version ladder) + the **stem package** | the brief and the picture |
| mixer / audio engineer | **instrumental / TV mix**, VO-safe, loudness + codec per medium | the **approved master** |
| editor | **cutdowns**, **social verticals** | the mixer's **published mix** |

`role_key` reads the craft out of a free-text assignment role ("Mixer", "Audio Engineer",
"Mix engineer" are one job). `deliverable_owner` says whose lane a row is.
`owed_after` says the editor waits on the mixer, and nobody else waits on anyone.

Three surfaces read it. The room shows **every** lane to everyone — the editor needs to
know a mix is coming — and offers the upload box only on lanes your craft owns. A lane
whose upstream has not been PUBLISHED yet says so ("waiting on the mixer — you'll be
emailed when it's published") instead of showing an empty box. Publishing the first file
of the mix emails the editor, and only the editor.

**Why.** *"The Composer writes the music, and upload the stems. The audio Engineer or
mixer mixes the composer's work … Editor makes the cutdowns and the verticals from the
mix engineer's final work."* Every creator saw every lane with an open box on all of
them, so the editor was invited to deliver cutdowns of a mix that did not exist — and an
empty upload box on work nobody can start reads as a missed deadline rather than a queue.

**Consequences.** The room GUIDES; the taste gate DECIDES. The upload route deliberately
does **not** refuse a lane your craft does not own: one person wearing three hats is the
normal case in a small studio, and a hard refusal would block a composer who also mixes,
or the studio uploading on someone's behalf. Nothing reaches the client either way until
the studio publishes it, which is where a mislabelled file is caught. A room whose roles
map to no craft offers every lane, exactly as before this ADR — an unrecognised role must
never produce a room where nobody can upload anything.

### ADR-0074 — A deliverable lane holds a folder, and the hand-off starts with the master
**Status:** Accepted (2026-08-19, operator directive) · Extends ADR-0068 ·
Source: `creator_routes.creator_submit_deliverable`, `creator_routes._room_fields`,
`delivery_ops._approve_version_core`, `tests/test_a_stem_package_is_not_a_file.py`

**Decision.** (1) A scoped deliverable is a LANE, not a file. Each lane accepts many
files — chosen or **dropped on the row** — in as many batches as it takes, and stays open
for the life of the delivery; the row reports how many are in it and **lists them by
name**, because a count answers "did anything land" and not "did I send all twelve". One
press sends every lane that has files queued. A file that fails to read is skipped and the
rest of the batch still lands — the response reports what actually persisted.

(1b) **The gate reaches the deliverables.** Files waiting are counted in the Queue nav
badge, carry their own card in the queue, are named in the operator's room whisper, and
can be published or sent back **from the room**, on the file, where they sit.

(2) The APPROVED MASTER is downloadable from the room by anyone holding `download_source`
(operator + talent), and `room_view` removes it for the client. The creative-approval
email names the locked version, lists what is still owed and to what spec, and carries
each creator's own room link.

**Why.** *"The mix ready stems, cues, cuts, mixes are going to be multiple files because
they're stems. so each lane will need to be able to house multiple files."* The lane took
one upload and then closed itself, so a twelve-stem package was a row reading "with the
studio · under review" with one stem in it and nowhere to put the other eleven.

And: *"if i had individual people assuming the individual role its at this point where
they will be invited to download the composer's approved final version and mix it … i
want to make sure that has been built."* Most of it was — per-role assignment, a room and
token each, the uniform publish gate on every deliverable, per-asset client sign-off, and
delivery that ships only when all of it is approved. What did not exist is the first step:
the room knew which version was approved and offered no way to get it, so a mixer was
being asked to mix something they could only stream.

**Consequences.** `pending_assets` may hold many entries under one label; anything
counting deliverables counts FILES, not lanes, and `pending`/`uploaded` booleans are kept
beside the counts rather than replaced. The source master is `download_source`-gated
everywhere: a client receives what they signed off, in the package, once it is paid for.

**Update (same day):** the open item — lanes not scoped to a role — was closed by
**ADR-0075**, after the operator stated the production model.

### ADR-0073 — The room speaks to whoever is in it
**Status:** Accepted (2026-08-19, operator directive) · Extends ADR-0068 ·
Source: `creator_portal.html` (the `voice` variable),
`tests/test_the_room_speaks_to_whoever_is_in_it.py`

**Decision.** Copy is capability-gated like everything else in the room. `voice`
(operator / talent / client) is set once where the room opens, and every line addressed
to a particular reader branches on it: the whisper, the cut's download link, the sheet
titles, the empty states, the phone note, the brief's closing line. The drag-and-drop
upload target is not rendered at all for a role that may not upload.

**Why.** *"I entered the room as a client and the note at the bottom left of the video is
'the room is current. write' … that is not how we speak to our clients. im sure that was
not meant for the client it was meant for the composer, but even that is not a nice
message to send to someone who is working for you."*

Both halves. The first is the ADR-0068 leak one layer up from data: the buyer was handed
a line addressed to someone else, telling them to write music. The second is the sharper
one — it was an imperative, to a person doing the work, from the people paying them. A
studio talks to the writers it hires the way it wants to be talked to.

And it was never one line. The template was written in the composer's voice and then
started serving three roles, so a client on their own cut was offered "⇓ DOWNLOAD FOR
YOUR DAW", told a room was "waiting for your music", shown "Your takes", and given the
composer's working-state vocabulary in a sheet titled "Client feedback" about their own
notes.

**Consequences.** A new line of copy in the room asks who is reading it before it is
written. The gate is `voice`, not a `{% if %}` on some other fact that happens to
correlate. Tone is part of the product: an imperative to a contractor and a leaked
instruction to a buyer are the same defect wearing different clothes, and neither shows
up in a test that only checks what data a role receives — this one reads the words.

### ADR-0072 — The taste gate has a door where the listening happens
**Status:** Accepted (2026-08-19, operator directive) · Extends ADR-0003, ADR-0068 ·
Source: `project_routes.delivery_publish`, `creator_portal.html` (the `.gate` block),
`tests/test_the_taste_gate_has_a_door.py`

**Decision.** The studio's disposition of a creator's submission — **publish to the
client** or **send it back** — is available in THE ROOM, gated on `room.CAPS['publish']`,
as well as on the delivery console. And denying a take is a send-back that carries a
REASON to the people who made it: an email to the assigned crew and an event in the room,
audience `operator,talent`. It spends no client revision round; nobody outside the studio
has heard it. `discard` is kept as an alias and behaves identically — it no longer has a
silent form.

**Why.** *"I don't see a way for me to push a version out to the client after review, nor
how to deny it and send it back to the composer, am i missing something?"* Not missing it
— it was somewhere else. Publish lived only on the console, so the operator auditioned a
take in the room, against picture, with the notes on the lane, and then had to leave the
room to act on what they had just heard. A judgement made in one place and recorded in
another is a judgement people stop making, and this is the judgement the whole publish
gate exists for (ADR-0003).

The second half did not exist at all. The console's other button was **Discard**: it
cleared the submission, wrote a line into the project's own updates, and told the composer
nothing. Their take stopped existing — no reason, no request, no email. The one action in
the system whose entire point is a judgement was the one that never reached the person
being judged.

**Consequences.** Publish stays operator-only: a client publishing to themselves makes the
gate decorative and a creator publishing their own take is not a review. Any new
disposition of someone's work must reach them — a state change a person cannot see is a
message we decided not to send. The client is deliberately NOT told about a send-back:
they never heard the take, and watching a studio reject its own work is not information
they asked for.

### ADR-0071 — A take and its notes are one thing
**Status:** Accepted (2026-08-19, operator directive) · Extends ADR-0068 ·
Source: `creator_routes._creator_feedback`, `room.priced_notes_only`,
`db.pending_submission_count`, `project_routes._review_redirect`,
`tests/test_the_room_opens_on_the_newest_take.py`

**Decision.** Four rules, from one round of live testing.

(1) **A note belongs to the TAKE it is about**, and the room selects takes.
`_creator_feedback` stamps every note with its version and returns the current version's
notes plus an `archive` of the rest; the room renders all of them and shows only the
selected take's. Selecting a take brings its conversation; a take nobody has heard yet
opens on an empty pane, which is where the next round gets written. A NEW note lands on
the take that is playing — the room sends it and `_note_version` **validates** it, since
a version string from a form is not a fact: any take in the ladder, plus the number the
pending take will get on publish and only for a caller who may see it; anything else
falls back to the version under review. A reply inherits its parent's take, because a
reply answers that note and moving it would split one conversation across two versions.

The room also **speaks a note as the playhead reaches it** (`.pin-peek`): a point note
holds for ~2.2s past its mark, a range for the stretch it covers, and neither shows while
parked — paused, a pin is a thing you click.

(2) **The newest take is the one loaded** — the pending submission when the role may see
it, carrying the label it will get on publish (`v2 …`), not "with the studio". The old
default existed because an undecodable bounce could kill the room; the `audio.error`
fallback now covers that, so the newest take can lead.

(3) **Selecting and auditioning are different intentions.** Clicking a take row loads it
and its notes and stays where you are; ▶ loads and plays. One control that did all three
meant the only way to look at a take was to start it.

(4) **A verdict given in the room stays in the room** (`origin=room`), and **a submission
waiting at the taste gate is visible from every page** (the Queue nav badge). Both are
the same rule: the surface where the work is heard is where the decision is made, and a
queue nothing moves through without the operator has to be legible from wherever they
are standing.

**Why.** *"when i logged into 'the room' V1 was loaded, and the notes from V1 was there,
V2 should be loaded and labelled as v2 with a fresh pane for new notes"*; *"it requires me
to click play in order for v2 to be loaded, and it instantly starts playing"*; *"it took
me out to the client workspace, im not entirely sure that necessary"*; *"the alert went
out to approve which is great, no badge showed up in the dashboard"*. Underneath all four
is one idea the room had not been built on: notes were filtered to the version under
review and rendered once, so there was nothing for selecting a take to select — and with
no per-take notes, the newest take could not lead without appearing to lose the
conversation.

**Consequences.** `feedback["notes"]` still means *the take under review* — every counter,
badge and existing reader depends on that and must not be widened to the archive. Any
surface that filters or subtracts notes must handle `archive` too — `priced_notes_only`
and both `room_view` subtractions do. The room's `sr-notes-data` payload is now a
CLIENT-FACING rendering of note text: it carries `author` and `body`, both `|tojson`'d,
and `author` is the subtracted name. A version accepted from a form goes through
`_note_version` and nowhere else; do not add a second path that trusts one.

### ADR-0070 — The roster is not the client's, and the room says what its playback is
**Status:** Accepted (2026-08-19, review panel + operator directive) · Extends ADR-0068 ·
Source: `room.attribute`, `room.CAPS['see_who']`, `project_routes.session_room_poll`,
`db.review_comments.author_role`, `uploads._store_pending_submission`,
`tests/test_what_the_panel_would_not_sign_off.py`,
`tests/test_the_room_answers_to_one_hand.py`

**Decision.** Four rules closing the panel's findings on the one room.

(1) **A client sees the studio, never the roster.** `see_who` is an operator/talent
capability. Without it, `room.attribute` signs every note, reply and live-feed event
from our side of the room as **Chordential**; the presence roster collapses our side to
ONE participant; and the version ladder's `from_creator` is emptied before any template
reaches for it. The client's own side keeps its names. Which side
a note came from is RECORDED at the write (`review_comments.author_role`); rows predating
the column are inferred from evidence — the author's email against the project's assigned
creators — and an unattributed row is treated as ours, because guessing wrong that way
costs a little readability and guessing wrong the other way costs a name.

(2) **A take is bound to the cut it was written against.** The picture's cut number is
stamped on the submission and carried into the version ladder; chips read `v2 · cut 1`,
and a take playing against a different cut raises an out-of-conform band. Legitimate —
it is what you do while working out how far the picture moved — but never silent.

(3) **Sync is measured every frame and corrected RARELY.** Under ~8ms it is locked and
any trim is released; 8–30ms is a deadband; past ~30ms a fixed ±0.5% `playbackRate` trim
engages, with `preservesPitch` off so it resamples rather than time-stretches; past
~150ms it seeks. Corrections are floored at one per 250ms and seeks at one per 800ms,
and none is issued while a seek is in flight. The measured offset is on screen.

The old rule — sample four times a second, hard-seek past three frames — both
under-measured the drift and announced its own correction with a click. The first fix
then moved BOTH remedies into the frame loop and made it far worse: *"the audio playback
is clipping, it sounds like the audio is chopped in milliseconds"* (operator,
2026-08-19). A hard `currentTime =` restarts the decoder and every `playbackRate` write
rebuilds the time-stretcher, so a persistent gap became sixty restarts a second instead
of four. **Measuring continuously is not correcting continuously** — only the
measurement wanted the frame rate.

(4) **The room states what its playback is.** Timing, structure and intent: yes. Level,
low end and stereo width: not judgeable in a browser on an unknown device.

**Why.** The exec team's condition on putting this page in front of a real client was
blunt: the room named the freelancers — presence roster, note authors, every event in the
live feed — and the roster IS the business. A buyer who can read it can hire around us.
Everything else here is the same species of defect the room already fixed once: a surface
presenting a number, a name or a sound as more certain than it is. A composer reading a
late hit cannot tell a bad bounce from a moved picture; a client approving a mix on laptop
speakers believes they judged it. The honesty rule applies to our own surfaces first.

**Consequences.** Subtraction stays SERVER-SIDE and by absence (ADR-0068): a template
that forgets an `{% if %}` must leak nothing, and `attribute` fails closed on an
unrecorded side. Any new surface that shows a name, an author or a participant to a
client goes through `room.attribute`. Any new writer of a note or event must record its
side; a route that knows the role and drops it is a defect, which is exactly how
`actor_role="client"` came to be hardcoded on every note in the room.

### ADR-0069 — A note is not work until a human has priced it, and a cut is not loaded until it is conformed
**Status:** Accepted (2026-08-19, review panel + operator directive) · Extends ADR-0068 ·
Source: `room.priced_notes_only`, `db.set_comment_disposition`,
`project_routes.review_note_disposition`, `project_routes.project_conform`,
`campaign_intelligence.composer_brief`,
`tests/test_a_note_is_not_work_until_it_is_priced.py`

**Decision.** Four rules, from a six-seat review of the room (composer, audio engineer,
picture editor, agency EP, software engineer, executive team).

(1) **Every client note is classified before it becomes work** — `conform` (the picture
moved; free), `revision` (counts a round), or `out_of_scope` (quoted separately). An
unclassified note sits in the operator's queue and is **absent** from the creator's list.
A change request arrives already priced as a revision, because pressing that button IS
the client spending a round.

(2) **A cut carries its own clock.** `fps` and `tc_start` are stated when the picture is
delivered and the room reads them. With no declared rate the room says *seconds from
head* rather than inventing frames.

(3) **A new cut is PARKED until conformed.** The room keeps playing the cut the notes were
written against; the studio states how far the picture moved and every note moves with
it, or discards the cut. Notes are shifted, never deleted, and clamp at zero.

(4) **Approve states what it commits** — what it locks, whether it spends a round, and
the licence being granted — and confirms before it fires. The FEE stays operator-only.

**Why.** "Request changes" cost a revision round and a plain note cost nothing, yet both
reached the composer and both got worked on: an unpriced revision channel running beside
a counter reading "Round 1 of 2". The buyer learns which lane is free within one project.
Timecode was hardcoded to 24fps at hour zero, so every number the composer read back was
wrong on a 23.976 or 25 cut — and that number is what goes into notes and cue sheets. A
re-cut replaced the picture silently, leaving each pin at its old second while the ground
moved. And the EP would not press Approve at all: *"approve for what — that the music is
locked, that a round is burned, that I owe money?"*

**Consequences.** "The machine proposes, Jon disposes" now governs FEEDBACK, not only
buttons: `priced_notes_only` is the one rule and both the room and the composer's own
portal read it. Do not add a path that hands a creator an unpriced note. When the room
cannot know something — where a note moved to, what frame rate a cut is — it must SAY so
rather than compute a plausible answer; a wrong timecode is worse than an honest one.
Money shown to a client is still only what they signed: the grant is visible in the room,
the fee is not.

### ADR-0068 — One room, capability-gated by who holds the link
**Status:** Accepted (2026-08-18, operator directive) · Source: `web/room.py`,
`web/room_routes.py`, `creator_routes._room_fields`, `tests/test_the_one_room.py`

**Decision.** One engagement is ONE room, at `/room/<project_id>`, and four credentials
reach it: a creator's portal token (`?t=`), the client's share token (`?k=`), a named
reviewer's link (`?r=`), or an authenticated admin session. Which one you hold decides
your ROLE; `room.CAPS` decides what the room is built with. `creator_routes._room_fields`
builds the engagement once, in full, and `room.room_view` SUBTRACTS what the role may not
have. The client's copy carries **published versions only**.

**Why.** One engagement had three surfaces — the composer's Session Room, the client's
delivery portal, the operator's console — each with its own template and its own idea of
what a version is. Three renderings of one thing is how they drift, and the drift showed:
a creator with three hats got three rooms, and a client got a page that looked nothing
like the room the work happens in. The operator asked for the Google Docs shape — *"one
central doc but different user accessing the same doc"* — which is one document with
viewer/commenter/editor permissions, not three documents.

**Consequences.** The gate is **subtractive and server-side**: content a role may not see
is absent from the dict, never hidden by an `{% if %}`. A template that forgets a guard
then leaks nothing, which is the only arrangement worth trusting. An unknown role gets
the empty capability set — a typo fails closed. **A route exempted from the admin gate
must make its own, stricter check**: `_session_role` reads "no token" as *operator*,
which is safe only behind the gate, so the room verifies an admin session itself for the
tokenless arm. That hole was live for the length of one commit and was caught by its own
test; do not exempt a path without asking what its no-credential branch assumes.

Not yet done: the client's delivery portal and the composer's `/creator/<token>` are
still their own doors. They keep working, and flipping them onto `/room` is a separate,
reversible step — one that should follow somebody looking at the merged room first.

### ADR-0067 — Closing by signature takes the same road as closing by review
**Status:** Accepted (2026-08-18, reported live) · Extends ADR-0065 · Source:
`opportunity_ops._ensure_proposal_for_project`, `workspace_routes._workspace_signals`,
`kickoff.build_readiness`, `tests/test_the_client_has_something_to_do.py`

**Decision.** A countersigned proposal is commercially approved, full stop. Countersigning
writes the project's `proposals` row from the **signed** agreement's own band, and
`_workspace_signals` reports `commercial_approved` for a countersignature exactly as it
does for an approved Commercial Review. Kickoff asks the client for the picture as well as
the deposit, and every client action that can be taken carries the link that takes it.

**Why.** ADR-0065 gave the deal a second way to close — the client signs the Discovery
Summary, we countersign — but every client-facing obligation still hung off the first way.
Three consequences, one root: no `proposals` row (only `_ensure_proposal_from_review` ever
wrote one), so `proposal_for_project` returned None, the owed deposit read as 0, and the
Pay button never rendered; no `commercial_approved`, so `compute_phase` sent a signed deal
past KICKOFF into PRODUCTION, and Kickoff is the only surface that asks the client for
anything; and nothing anywhere requested the picture, though the composer's session room
renders "picture arrives with the client's cut" and waits, and the delivery portal has
always had the Drop that receives it. A client signed, was promised a deposit invoice in
the acceptance text, and was shown a room that said **Everything is ready**.

**Consequences.** A new way to close a deal is not finished when the signature is stored.
Walk the client's path afterwards — money, phase, and the things we need FROM them — and
make it converge with the existing one rather than run beside it. The picture is never
gated on the deposit: it costs the client nothing to send early and is the most useful
thing they can do while the composer is being assigned. Money shown to a client comes from
what they SIGNED, never a quote recomputed afterwards.

### ADR-0066 — A link in an email is anchored, and a token never ends in punctuation
**Status:** Accepted (2026-08-18, reported live) · Source: `mailer.send_email`,
`web/db.public_token`, `web/meeting_scheduler.py`, `web/project_routes.py`,
`tests/test_a_link_that_survives_the_inbox.py`

**Decision.** Two rules, both enforced at the floor rather than at each call site.
(1) `send_email` wraps any body containing a URL in `branded_html`, so every link ships
as a real `<a href>`. A caller may pass its own `html`, but it must be built with
`branded_html`; a test refuses any that is not. (2) Every token that appears in a link is
minted by `db.public_token`, whose alphabet is letters and digits only. `token_urlsafe`
is banned outside `accounts.py`, where the token is a cookie and never retyped.

**Why.** A composer opened his portal link from the Gmail app and got 404; the same link
worked on a desktop. Neither the gate nor the token was at fault — `/creator/<token>`
returns 200 with no cookie at all. The email was plain text, so the mail client had to
find the URL and guess where it ended, and the token was `ouLvIvWMxli-zHT-`. A linkifier
reads that trailing hyphen as sentence punctuation and trims it, and a token one
character short belongs to nobody. `token_urlsafe` draws from base64url, so **about one
link in thirty** ended in `-` or `_`: composer portals, client workspaces, reviewer
sign-off links, contributor releases. Five client- and creator-facing sends were bare
text — the proposal-ready notice and the countersigned notice among them — which is
five chances to remember a rule, and the reason the rule now lives in `send_email`.

**Consequences.** Do not call `secrets.token_urlsafe` for anything that reaches a URL;
call `db.public_token(n)`. Do not pass a hand-rolled `html` to `send_email`. **Tokens
already issued are left as they are** — re-minting would break every link sitting in
somebody's inbox, which is a worse failure than the one being fixed; the anchor makes
the existing ones work. Two characters of alphabet cost ~0.05 bits each, which is not a
security trade worth discussing.

### ADR-0065 — The summary is the proposal, the licence is the price, and the budget is only a check
**Status:** Accepted (2026-08-16, operator directive) · Supersedes one clause of ADR-0020 ·
Source: `agreement.py`, `pricing.py`, `signing.py`, `client_voice.client_assumptions`,
`web/workspace_routes.py`, `docs/market-pricing-research.md`,
`tests/test_pricing_is_not_the_clients_budget.py`, `tests/test_a_signature_you_can_draw.py`

**Decision.** Three changes to how a deal is closed.

(1) **The Discovery Summary carries the commercial close and can be signed.** Once a
discovery call has happened (`met`), the client's summary shows scope, fee, terms and an
Agreement block. Accepting it is a real signature bound to a SHA-256 of
`agreement.signable_text()` — one deterministic text that is both what the client reads
and what the digest covers, rebuilt on the sign path so what is stored is provably what
the page showed. A drawn mark (finger or mouse) may accompany it but is never the
evidence: it is optional, validated as a base64 PNG or dropped, and excluded from the
digest, so a browser where the canvas fails can still sign. Signing does not award the
deal — it records the client's half and leaves countersigning to a human.

(2) **Price is a creative fee plus a licence fee.** The creative fee is cost at target
margin (`estimation`, unchanged). The licence fee is media × territory × term ×
exclusivity, capped at `LICENCE_FACTOR_CAP`. The client's stated budget NEVER sets the
price; it produces a verdict — below floor, in band, above band.

(3) **The prep sheet prices its own questions.** Each licence answer is costed against
the live deal, loudest first, through the same `build_quote` the proposal uses.

**Why.** ADR-0020 held that the Summary carries no pricing and that the commercial
conversation happens later at a released proposal. Its underlying rule — the deal has
exactly ONE commercial commitment — is untouched and better served: the client used to be
asked twice (confirm the summary, then approve a proposal) and now commits once. The half
of ADR-0020 that was right survives as the `met` gate: before the call there is no
scoping, so no honest number, so the summary still shows none.

The pricing change answers a live report — *"I have no idea how I am pricing the
product… that is a name-your-price on my service."* `quote_band`'s second tier was the
client's disclosed budget, which fires on every deal that has had a discovery call,
because discovering the budget is what a discovery call does. Measured on one film: cost
$4,062–$8,435, quoted $6,000 to a client who said $6,000 and $90,000 to one who said
$90,000. Two real engines sat underneath and reached nobody.

Splitting creative from licence is specific to music: production cost is nearly flat with
respect to usage and value is not. The same ninety-second cue is $14,000 or $28,500 on
the licence alone. Those four inputs were already questions on the prep sheet, whose own
copy already promised they were priced.

**Consequences.**
- The signable text is the DOCUMENT. Anything that changes it changes every existing
  signature's verdict, so acceptance copy lives in Python (`agreement.ACCEPTANCE_TEXT`),
  not in a template where it could be edited without a signature noticing.
- A signature may hang off an opportunity (`opportunity_id`) or a project, never both.
- Never print internal assumptions on a client document. `client_voice.client_assumptions`
  is the gate; the estimator's own list states our target margin.
- Never quote below `pricing` floor, built on the HIGH end of the cost band.
- Licence factors are **priors**, ratified against `docs/market-pricing-research.md` and
  not calibrated on Chordential actuals. Re-read that document before changing one.
- `estimation.suggested_price` still folds a usage factor into the creative number and
  therefore now DISAGREES with `pricing`. `build_quote` deliberately ignores it. It is a
  legacy figure pending retirement.
- **`quote_band` is wired** (2026-08-17, operator directive). Its tier 2 — the disclosed
  budget — is gone; the price is `pricing.build_quote`. `capabilities.quote_for` is the
  richer authority (the whole `Quote`: itemisation, floor, verdict) and `quote_band` is
  its tuple view, so the number on the proposal and the warning on the deal page cannot
  come from two calculations. An operator override still wins, via `Quote.rescaled_to`,
  which rescales the two lines so an overridden document still adds up.
- **Any surface a BUYER sees must build its estimate through `opportunity_ops.
  _estimate_for_row`.** `estimate_for` was already the one path (ADR-0033) but left each
  caller to decide whether to pass `project_id`, and that choice swaps global role rates
  for the assigned creators' real ones — changing the client's price. The Commercial
  Review used one convention and the project's proposal the other; the budget-as-quote
  hid it, because the budget won whatever estimate fed it. Wiring the price to the work
  surfaced it immediately as the two documents disagreeing on the deposit.
- **A caller renders the authority; it never adjusts it.** `public.public_price_band` was
  converting `quote_band`'s result at margin, correct when that result was a cost band
  and a double mark-up the moment it became a price.

### ADR-0064 — A canonical key has exactly one home, so its facet is derived, never accepted
**Status:** Accepted (2026-08-14) · Source: `web/campaign_intelligence.py` (`canonical_slot`),
`web/campaign_intake.py` (`_canonicalise`), `web/db.py`
(`refile_ci_fields_to_canonical_slots`), `tests/test_a_canonical_key_has_one_home.py`
**Decision.** `canonical_slot(facet, key, kind)` snaps **both halves** of a proposed field
onto the canonical slot it means, and every intake candidate passes through it. A canonical
key belongs to exactly one facet — that is what makes it canonical — so the facet is
computed from the key rather than taken from the extractor. Only **facts** are moved: an
open question about the budget is an open question, and filing it as the value would be
worse than losing it. A key with no canonical meaning passes through untouched, facet and
all — the dynamic field must keep working. Facts already stored under the old behaviour are
repaired once at boot, for free, and the repair **never** overwrites a slot that already
holds a value.
**Why.** Two live discovery calls failed the same way, and the second failure was the first
fix applied to half the address. On call one the answers were filed under names of the
model's own choosing — $45,000 into "Production Budget", the conditional launch into
"Seasonality" — while Budget and Timeline sat empty; snapping the KEY fixed that. On call
two the budget was read perfectly, spoken correction and all — *"the number I've been given
is roughly 25. No, no, 30,000. And that's all in including any licensing"* — and filed as
**`commercial/budget_band`**. The key was already canonical. The facet was not, and the slot
is `(engagement, budget_band, fact)`, so the lookup missed by one column and the Budget
field showed its placeholder with the correct answer visible in the evidence list beside it.
Deliverables went the same way. The estimate, the brief and the proposal all read the
canonical slots, so a perfect read filed next to them is worth nothing — and the operator
had paid a ten-agent engine for that read.
**Consequences.** Never widen `CANONICAL_FIELDS` without remembering that its key set is now
also an address book: adding a key claims that name everywhere. Do not "fix" extraction by
instructing the model more firmly — steering is a prior, `canonical_slot` is the guarantee,
and the two live failures were both of a model that had been steered. Repairs of stored
intelligence follow the same rule as this one: conservative, idempotent, free, and never
destructive of a human's value — a collision leaves both rows visible for a person to
settle rather than picking a winner.

### ADR-0063 — Creating an event and inviting someone to it are two different questions
**Status:** Accepted (2026-08-14) · Source: `meetings/calendar.py`, `meetings/google.py`,
`web/meeting_scheduler.py`, `mailer.py`, `tests/test_the_block_lands_without_a_click.py`
**Decision.** The calendar seam answers **`invites_attendees()`** — does `create_event`
actually invite the people it is handed? — and the scheduler decides **per recipient**, in
`invites_for`, who still needs an `.ics`: nothing connected → both; OAuth-as-the-operator →
neither (Google invited them, ours would duplicate); service account → the client only (it
booked the operator natively and invited nobody). Alongside that, an invitation
is built so that nothing has to be pressed for it to take effect: the operator appears as
`ROLE=CHAIR; PARTSTAT=ACCEPTED; RSVP=FALSE` (they are the `ORGANIZER`, not a guest of their
own meeting), `SENT-BY` authorises a sending address that differs from the organiser, every
change carries a **monotonically increasing `SEQUENCE`** persisted on the meeting row, and
content lines are folded to 75 octets.
**Why.** "A calendar event exists" was standing in for "both parties were invited", and the
two came apart in the configuration this repo recommends. A Google **service account** cannot
invite guests on a consumer calendar without domain-wide delegation, so `create_event` is
deliberately called with no attendees — and the scheduler, seeing an event id come back,
withheld the client's `.ics` on the strength of an invitation nobody had sent. The operator
got a block; the client got an email announcing an invitation that was not there. The question
has three answers and the code had two, so answering it either way got one configuration
wrong: the client loses their only route to a block, or the operator is double-booked by a
second invitation for the event they already hold. Each of the
other three defects fails the same way — **silently, with every log line green**: an
organiser listed as a guest sees their own call greyed out awaiting a reply they were never
meant to give; an invitation whose `ORGANIZER` is unrelated to its sender reads as forged and
is shown but not booked; and a calendar **discards** an update whose `SEQUENCE` does not
exceed the one it holds, so under a hardcoded `1` the first reschedule moved the block and
no later one did. Nothing anywhere reports any of these.
**Consequences.** Any new `CalendarProvider` must answer `invites_attendees()` honestly;
answering yes when it does not invite costs the client their calendar block. Never hardcode a
`SEQUENCE` — call `db.bump_ical_sequence`, which increments in one statement for the reason
`merge_json_key` does (ADR-0049): a repeated sequence is not a collision that raises, it is a
change that vanishes. The honesty rule reaches the copy too: the confirmation email says a
block is on the calendar only in the branch that actually carried one, and the client's
wording claims what an invitation can do (ask) rather than what it cannot (write to a
stranger's diary). The operator-facing banner now reports the **route** a block takes —
Google invites both / Google books yours and the client is invited by email / both invited by
email — because "Calendar: not connected" was read as "no block will appear", which was never
true. Truly zero-click on **both** sides requires the OAuth-as-the-operator path, where Google
adds the guest itself; that remains a deliberate trade against its 7-day Testing-mode token
expiry (`meetings/google.py`), not an oversight.

### ADR-0062 — The world has one recipe, and everything in it stays inside the box
**Status:** Accepted (2026-08-12) · Source: `scripts/score_scene/recipe.py`,
`scripts/score_scene/pack.py`, `scripts/build_score_scene.py`,
`scripts/blender_score_cube.py`, `web/static/public/score-gl.js`,
`tests/test_score_scene.py`
**Decision.** The front door's world — 728 pieces of engraved notation that scatter,
reassemble into a cube, and then fold into a delivery package — is **described once**, in
`scripts/score_scene/recipe.py`, and reported to a **recorder**. `build_score_scene.py`
records instanced marks and ships `score-scene.{json,bin}` to the browser;
`blender_score_cube.py` records real geometry and renders the still the look is judged
in. Adding a surface means adding a recorder, never a second copy of the layout. Every
run of notation is placed through `fit`/`seat`, which intersect it with the cube and
**slide it inward**, shortening only when the box is genuinely narrower — so containment
is a property of the placement, not of luck. The generator, its glyph sources and the
Leland outlines live in the repo.
**Why.** This layout existed as three divergent copies in an ephemeral scratch directory.
They had already drifted: in the shipped web scene **150 of 728 pieces finished
assembling outside the cube, the worst by 125 units — 42% of the cube's own width** —
staves projecting through the faces and fragments floating clear of the corners, while
the Blender file the model was judged in was fine and had never been changed. Nobody
compared them because comparing them was not possible: the only artifact under version
control was the output. Extracting the recipe made the two recorders comparable, and the
first comparison found a second defect on the Blender side — assigning `matrix_world`
straight after re-parenting resolves it against a stale parent matrix in background mode,
so **every glyph in the offline model sat at exactly double its offset**.
**Consequences.** Do not add a fourth walk of this layout. `fit` slides and only then
shortens, and **drops nothing** — a change that achieves containment by discarding runs
makes the cube tidy and empty, which `test_score_scene.py` fails on both counts (it also
fails if the model stops touching its own walls, and if `score-scene.bin` is stale
against a regenerated build). The scene is a **build artifact**: change the recipe, run
`python3 scripts/build_score_scene.py`, commit the regenerated pair. The extraction was
proved behaviour-preserving — the regenerated scene was byte-identical.

The package is the same principle applied to the ending. `pack.py` gives every piece a
second target (position, scale, quaternion about its own centroid — exactly the transform
the renderer already applies, so the morph needed no new machinery), and then a third with
the lid shut. **80 of the pieces lay themselves along the 24 edges of a shipping carton,
so its outline is literally staff paper; the other 648 stack flat inside it.** Nothing is
discarded and nothing is invented: "One delivery. Nothing missing." is the sentence beside
it, and the picture has to be able to make the same claim. The gauge, the manifest list
and the carton all report the same scalars (ADR-0029's rule, applied to a picture).
ADR-0040 still holds through the fold — the four ember notes ride their own pieces into
the package and take its four corners, so the front door is still playing music at the
point where it asks for the brief.

**Every act is MEASURED from the beat it illustrates, not written down.** A beat occupies
a different stretch of the scroll on a phone than on a desktop, so a single set of
constants can only ever be a compromise between them. They were hand-fitted to measured
windows three times before this; the third time — making the handoff beat tall enough to
hold its model in view on a phone — left the two layouts sharing a window of 0.039 for
four notes to light in. That is not a number worth tuning, it is a sign the number should
not exist. `pinActs()` now measures the beats at boot and on resize and derives each act
from the one it belongs to: the cube closes just before the review beat, the notes light
across its first two thirds, the carton builds as the handoff beat rises and is finished
early in it, the lid shuts as that beat gives way to the last. A phone and a desktop
derive different fractions from the same rule, and re-laying out a section re-pins its act
instead of quietly dragging the beat out from under it. The beats are found by what they
CONTAIN, never by index, and the orderings the acts depend on are clamped, because derived
numbers come from whatever the layout turns out to be. This is ADR-0029's rule reaching
the last place on the page that still had a second copy of an answer. The fold has to FINISH early in its beat, not
at the end of it: the middle of a fold is a transitional cloud, and it is standing beside
a manifest of what is in the box under the words "everything arrives together" — a fold
still running while that is being read is the picture contradicting the sentence for the
whole time anyone looks at it. The real length of the fold is the stagger's tail, not the
window: a piece staggered to 0.75 has not begun to move when the fold is three quarters
done, which is how the model came to be still assembling long after its section was on
screen. The manifest itself waits for something to describe (it reveals past halfway),
and the line "One delivery. Nothing missing." waits for the manifest, because it is a
claim about that list. `test_score_page.py` holds each act inside its
own beat window rather than checking bare numbers, because a nudge to any one constant is
exactly how a picture drifts off the sentence it was drawn for. The lid is a genuine
rotation — sliding each piece straight between the two states cuts the chord of a
122-degree swing and the flaps visibly buckle inward instead of folding — and its four
hinges are **shipped, not deduced**. They were first recovered in the renderer from the
open and shut states alone, which is sound in principle (a rigid rotation is determined by
its endpoints) but requires choosing which side of the chord the centre of the swing falls
on; where that choice went wrong the panel was left standing, so half the lid folded and
half did not, which reads as a tent rather than a closed box. The packer knows every hinge
exactly, four of them cost nothing to send, and a test now turns each piece about the
hinge it names and checks it lands on its shut position.

**The fold is a compression, not a dissolve.** Given a free choice of destination the
packer sent every piece across the model to somewhere unrelated — nearest-free-edge for
the outline, a random spot for the contents — so the middle of the fold, which is the part
you actually scroll through, was an unreadable cloud: the cube dissolved and a carton
condensed out of it. Each destination is now taken from the source (the nearest edge that
fits; contents keep their own footprint and their own stacking order, by rank so the stack
still fills evenly), which halves the median trip from 257 units to 110 and makes the same
fold read as the cube settling into the box. This is a LOOK held in a number, because if
it regresses the picture still ends in exactly the right place and nothing else notices.

### ADR-0061 — A writer's fee is a share of net, and their publishing is only theirs if it can be paid
**Status:** Accepted (2026-08-06) · Source: operator decision on supply-side terms ·
`compensation.py`, `estimation.py`, `delivery.py`, `web/db.py`
**Decision.** A writer is paid **30% of net creative revenue** (price − pass-through
session costs), **40%** when they also orchestrate. Un-awarded demo submissions are paid
a flat **$400**. **Publishing is split 50/50 with the writers**; the writer's share stays
100% to writers. The estimate carries the fee (`Estimate.writer_fee`), the payout ledger
seeds a writer with no negotiated rate from the same policy, and the cue sheet renders
the publishing split — so the price quoted to a client, the number promised to a
composer, and the money the ledger owes are one arithmetic.
**Why a share of NET, not price.** On a $76,191 orchestral anthem, $32,125 is players and
a room — money that passes through the studio. A share of gross would pay a writer more
because an orchestra was booked, which is not a fact about their work.
**Why 30%.** Calibration, not invention: 30% of net on a national :30 is **$2,980**
against the **$3,000** the estimator already modelled for that job. The two agree because
they were made to agree, and the percentage then carries sensibly to jobs the old flat
line priced absurdly — that `Composer` line was a flat 20h × $150 **regardless of scope**,
which is 26.9% of an $11,133 spot and **3.9% of the $76,191 anthem**, the same money for
the harder brief.
**Why publishing is 50/50, and why now.** Backend costs the studio nothing today — there
is no aired work, so the publisher's share is worth zero this year — while cash is the
scarce thing. Trading the free asset for the scarce one is the correct trade for a studio
with no catalogue, and unlike a promise about future volume it is checkable on the cue
sheet the composer receives.
**Why a writer's publishing half is NOT written onto the sheet by default.** A composer
who has never registered as a publisher with a PRO cannot collect on a publisher line.
Putting their personal name there pays them nothing, creates an unclaimed share on a
filed legal document, and tells them falsely that they are covered. So an unknown entity
leaves the share with the house, marked `held_for` that writer and reported by
`unassigned_publishing` — a debt the console can chase, not a silent forfeit. This is
ADR-0050's rule ("a missing link is a gap; a wrong link is a lie") applied to money.
**A false reason is worse than a low rate.** The first wiring gave the 40% uplift for
"producing the session" on a **sampled** score that had no session. The rate was
arguable; the stated reason was untrue. The uplift is now for ORCHESTRATING — a second
job whether the parts are played by people or samples — and `live_session` only decides
what the fee is called.
**Consequences.** `tests/test_compensation.py` fails if the fee is taken on gross, if it
stops agreeing with the estimator's own number for a :30, if it does not scale with the
job, if the uplift claims a session that did not happen, if publisher shares do not total
100%, if a writer with no entity is written onto a cue sheet or their debt goes
unreported, if a mixer is seeded a writer's fee, if a writer with no rate is seeded at
zero, or if a negotiated rate stops beating the policy. `talent.publisher` is the new
column; blank is the honest default.

### ADR-0060 — A link has a life, and a delegate is weaker than the person who invited them
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 4 (token
lifecycle and delegated client access) · `reviewers.py`, `web/db.py`,
`web/project_routes.py`, `web/app.py`
**Decision.** A reviewer roster entry carries `created_at`, `expires_at`,
`last_used_at`, `revoked_at`/`revoked_by`, `invited_by`, and explicit
`can_sign`/`can_approve`/`can_delegate`. New links expire (dial:
`CHORDENTIAL_REVIEWER_LINK_DAYS`, default 90; `0` = never). Withdrawing **keeps** the
entry. A verified reviewer may **delegate** access to a colleague; the delegate gets
their own link, an expiry **capped at their inviter's**, and **cannot sign, approve, or
delegate on**. Expired and revoked links answer **410 with an explanation**, not 404.
**Why.** A personal link was four fields — `{token, name, email, role}`. No expiry, so
one mailed once works for ever. No record of use, so a live link and a two-year-old
thread look identical. No revocation, only deletion, which erases the fact access was
ever granted. No record of who issued it. And no statement of what it may DO, which
became load-bearing the moment ADR-0059 arrived: every link could sign the Clearance
Certificate, because nothing said otherwise.
**Why delegation is a REDUCTION in risk, not an increase.** A client with a colleague to
loop in had no supported way to do it, so the link gets forwarded. The system's real
access-control model was therefore *whoever has the URL*, while its records said one
named person — and every forwarded copy could sign. Delegation replaces that with a
named entry per person, their own name on their notes, a bounded expiry, and strictly
fewer powers. It is the existing hole, made visible and bounded.
**Why a delegate cannot sign, approve, or delegate on.** Signing and approving are the
acts that bind the deal (ADR-0020, ADR-0059), so they stay with someone the **operator**
named; otherwise a chain of forwarded invitations ends in a signature nobody at
Chordential authorised. Chains are also how a link ends up somewhere nobody intended, so
delegation does not chain. The operator can promote a delegate — "the machine proposes,
Jon disposes" applies to who may sign, too.
**Two things that had to be true for this to be safe.** Expiry is **never applied
retroactively**: entries written before these fields existed have no expiry, keep full
capabilities, and behave exactly as before — adding one would cut off live clients
mid-review to make a refactor tidy. And use is recorded at **day granularity**, because
per-request would be a JSON merge write on every refresh of a page clients leave open
while a mix plays, and "is anyone still using this link" is answered as well by a day.
**Consequences.** `tests/test_token_lifecycle.py` fails if a delegate can sign, approve
or delegate, if a delegate outlives their inviter, if a delegate of a never-expiring link
never expires, if a legacy entry loses its powers or gains an expiry, if revocation is
beaten by a future expiry, if withdrawal deletes the row or can be rewritten by a later
hand, if extending changes the URL, if a revoked link can be extended back to life, if an
expired link 404s instead of explaining itself, if opening the portal does not record the
link as alive, if the generic share link or an expired reviewer can invite anyone, or if
the operator's revoke/extend controls escape the admin gate. `/delivery/delegate` is
gate-exempt (a client act, with its own stricter check); `/delivery/reviewer/revoke` and
`/reviewer/extend` deliberately are not.

### ADR-0059 — A signature is bound to the document, or it is decoration
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 4 (real
e-signature) · `signing.py`, `signing_providers/`, `web/db.py`, `web/project_routes.py`
**Decision.** A signature stores the **SHA-256 of the exact document text** it was made
against, plus the signer, the mark they typed, the consent verbatim, the time, and a
fingerprinted address. `signing.verify` rebuilds the document from live data and
compares: `VALID`, or **`SUPERSEDED`** when a term moved after signing. Signatures are
**append-only**; withdrawing one is `void_signature`, which marks the row and keeps it.
Only a **verified reviewer** (personal `?r=` token) may sign; consent is required and
ships unticked. Voiding is **owner-only**.
**Why.** The Clearance Certificate is the one thing the market pays a premium for, and
nothing signed it. What the product called a sign-off was
`{"asset": …, "approver": "Dana Whitfield, Aurora", "date": "2026-08-06"}` — a free-text
name appended to a JSON list. **Reproduced on seeded data: a client signs off, the
operator then changes the licence from perpetual / worldwide / exclusive to one year, US
only, non-exclusive, and the approval record is byte-for-byte identical.** It survived a
change to the very terms it was a sign-off on, because it never referred to them.
**Why no DocuSign module.** Under ESIGN / UETA an electronic signature is valid without
a third party: intent, consent, attribution, association with the record, retention.
This provides all five, so the default provider is not a stub — it is the real one. What
a vendor adds is a **neutral witness and a procurement checkbox**, not validity. Writing
an OAuth + envelope client that has never run against a real DocuSign account would be a
file that looks like an integration and is not one — worse than an empty seam, because
it would read as done. `signing_providers/` is where it lands the day a buyer's
procurement requires it, with credentials to test against; an unknown provider name
**raises at boot** rather than quietly signing in-house under a configuration that asked
for someone else.
**Details that decide whether it works.** The certified DATE is excluded from
`signable_text()` — in the digest, every signature would report itself superseded by
tomorrow. Line endings and trailing whitespace are normalised and nothing else, so a
browser round-trip is not tampering but a changed word is. The signer's identity comes
from the **roster**, never the form; the typed mark is stored beside their real name,
not instead of it, because a mismatch is a fact a dispute would want. The IP is stored
as a 12-char digest — enough to link two signatures, not enough to make the delivery
database a log of clients' home addresses.
**Consequences.** `tests/test_signatures.py` fails if a changed document still verifies,
if a CRLF counts as tampering, if an empty document or empty mark produces a record, if
the consent is stored by reference, if the raw IP is persisted, if the typed mark
overwrites the real name, if the certified date enters the digest, if an operative term
is outside the signed text, if voiding deletes the row or can be repeated with a
different story, if the generic share link can sign, if consent can be skipped, if the
admin gate blocks a client from signing, or if an unknown provider falls back to
in-house. `/project/{id}/delivery/sign` is exempt from the admin gate (the client is not
an admin) and `/delivery/signature/{id}/void` deliberately is **not**.

### ADR-0058 — Scored media is priced by the minute, and the players are their own scope
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 4
(minutes-of-music estimation) · `estimation.py`, `web/estimate.py`,
`templates/estimate.html`
**Decision.** A brief that names a scored FORMAT **and** a scoring signal is priced by
`MINUTE_HOURS × minutes + CUE_HOURS × cues`, not by spot length. Duration and cutdown
factors do not apply on that path — the scope has already priced the amount of music,
and applying them would count it twice. **The recording session is separate, explicit
scope** (`Session`: live, players, dates), with its own stated/assumed flags. The
campaign path is untouched.
**Why.** The engine was blind to the amount of music. Measured before the change: one
cue and sixty cues both priced at **$57,446**; two minutes of score and ninety minutes
both priced at **$57,446**. Only the format words moved the number, and the consequence
was that **a :60 commercial with two cutdowns — ninety seconds of music — quoted at
1.33× a 28-cue, 45-minute orchestral feature score.** The product sells a film/TV
engagement it could not price. (The review recorded this as "~1.5× a :30 spot"; measured
against a format-matched comparison it is worse, because the commercial came out
*higher*.)
**Why the session is split out, on the operator's call.** Orchestral *writing* and
*hiring an orchestra* are different purchases, and the single word "orchestra" in a
brief used to buy both — the orchestration hours AND thirty players on every date. That
is why an indie feature carried a studio's budget. Instrumentation stays a desk factor;
players and dates are now read from the brief, and a **sampled** orchestral score costs
the full orchestration hours and **no session at all**, which is a real and common
delivery the engine previously could not express. The same 45-minute orchestral feature
now spans **$192,582 sampled to $493,915 with sixty players over four dates** — which is
the actual spread in the market, and was a single number before.
**What is assumed, and said so.** Minutes, cues, players, dates and live-vs-sampled each
carry a `_stated` flag; anything guessed is named in the assumptions and on the estimate
page. Stating a player count or a date IS answering the live question — asking twice is
noise, and noise teaches people to stop reading the warnings that matter. Stated ranges
("20–30 cues") are read as their **midpoint**, because quoting the top of every range
biases every estimate high.
**What is NOT yet true.** `MINUTE_HOURS` / `CUE_HOURS` / `MINUTES_PER_SESSION` are
Phase-1 expert priors on the same footing as `ROLE_HOURS` — **not operator-ratified the
way `PUBLIC_BANDS` are**, and `PUBLIC_BANDS` has no film/TV entry, so nothing anchors
this path the way ADR-0028 anchors campaign work. Per-minute hours are **linear**:
thematic reuse genuinely makes the ninetieth minute cheaper than the first, and a
decline curve invented here would be a number with nothing behind it, so the discount is
declared in the assumptions and left for calibration.
**Consequences.** `tests/test_minutes_of_music.py` fails if more music does not cost
more, if cue count over the same minutes does not, if a feature does not outprice a :60,
if a format word alone routes a campaign onto the scored model, if a stated range is not
read as its midpoint, if per-episode quantities are not multiplied out, if an assumption
is not flagged, if a sampled score is charged for players, if a stated player count does
not beat the style word, or if spot length is applied on top of the minutes. The campaign
path is pinned by **golden values measured on the engine immediately before the change**
(`$11,132.9167` / `$76,191.30` / `$22,265.8333`) rather than by a band check, which would
pass while the number drifted inside it.

### ADR-0057 — One relationship stage, over both halves of the evidence
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 4 (one
Relationship Intelligence layer) · `web/buyer_intel.py`, `web/relationships.py`,
`web/console_routes.py`, `web/opportunity_ops.py`
**Decision.** `buyer_intel` is the ONLY place a relationship stage is derived.
`relationships.STAGES` **is** `buyer_intel.STAGES` — `Cold → Warm → Engaged → Client` —
and **dormancy is a flag beside the stage, not a fifth stage.** Both surfaces feed the
same function: `/buyers` through `relationship_for` over `all_buyers` + the batched
agency outreach rollup, `/relationships` through `pipeline_stages` over the outreach
rollup + the batched deal rollup. A human override still wins, and legacy stage names
are translated on read rather than migrated.
**Why.** There were two relationship engines over the same companies and each was blind
to half the evidence. The Buyer Graph staged from `opportunities` + `outreach_events`,
so it knew we had been PAID by someone and had no concept of a relationship going quiet.
Relationship Management staged from `agency_outreach`, so it knew about dormancy and
**could not return "Client" at any input** — the value was in its `STAGES` tuple with no
code path to it, reachable only by a human override. So a company that had commissioned,
paid for and received delivered work read **"Client" on one page and "Active" — or after
a quiet quarter, "Dormant" — on the other**, on the same day, from the same database.
This is the same defect as ADR-0029's three answers to "what is waiting on me?", one
level up, and it gets the same fix: one computation, everything else reports it.
**Why dormancy is a flag.** Making it a stage is precisely what erased "Client": a
paying customer who went quiet stopped being recorded as a customer at all. *We have
been paid by these people and have not spoken in eight months* is the single most
actionable pair in the layer, and neither old engine could express it.
**Why both recency rules survive.** Fourteen days (the Buyer Graph's) and ninety —
a hundred and twenty once they have ever replied (Relationship Management's) — were
never in conflict. They answer different questions: *is this conversation live* and
*is this relationship alive*. Both are kept, on the two axes.
**Consequences.** `tests/test_one_relationship.py` fails if a second stage vocabulary
appears, if "Dormant" becomes a stage, if a won deal does not make a Client, if a quiet
quarter is invisible, if the two logs are not merged into one conversation, if the two
surfaces stage one company differently, if a human override stops winning, if a legacy
stored stage is dropped, if the override form accepts a value outside the vocabulary —
or if `pipeline_stages` exceeds five reads for twelve agencies, because reaching the
other half of the evidence must not reintroduce the per-row loop ADR-0029 removed.
Writing the derived stage now goes through `db.cache_relationship_stage`, which takes
`exists` from the batch instead of paying a `SELECT` per agency to re-learn it.

### ADR-0056 — An organisation is a name, and the name is normalised
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 4 (one
Relationship Intelligence layer) · `web/db.py`, `web/app.py`
**Decision.** `buyer_org` is the canonical organisation on the buying side, keyed by a
normalised name (`name_key`) with a UNIQUE index. `resolve_org` creates or matches;
`link_orgs` stamps `org_id` on the five surfaces that name a company — `opportunities`,
`projects`, `agencies`, `companies`, `client_procurement_history` — and runs at boot;
`org_touchpoints` answers what one organisation has with us across all of them.
`domain` and `agency_id` **enrich** the row (first non-empty wins) and never decide
identity.
**Why.** This is the half ADR-0050 deferred and named. A company was `agencies.id` in
Agency Intelligence and a bare name string everywhere else, with nothing joining them —
which is why the product grew two relationship systems over the same companies (see
ADR-0057) and why, until this existed, there was not even a join to notice it with.
**Why the name is the identity, when ADR-0050 refused names for people.** The two cases
are not alike, and the difference is the available evidence. A person has an email:
unambiguous, usually present, and two people called John Smith are two rows. An
organisation has a name and *sometimes* a website — and an organisation with no website
still has to be canonical or the layer is useless. It is also the rule the codebase had
already committed to: `match_agency_by_name` has threaded `agency_id` onto opportunities
by exact normalised name since the lineage work. This makes an existing decision
explicit rather than adding a second one.
**What it costs, stated rather than hidden.** A renamed company becomes a second
organisation, and so does a typo. Those are gaps, and a gap is recoverable. What it must
never do is MERGE two companies — that merges their deal history and their clearance
record — which is why the match is exact-after-normalisation and never fuzzy, why a
shared domain does not merge two names, and why a second, different domain under one
name is COUNTED as `domain_conflicts` rather than silently overwritten by write order.
**Consequences.** `tests/test_buyer_org.py` fails if one company written four ways
resolves to more than one org, if two different companies merge, if a nameless row
invents an organisation, if the database accepts two rows for one name key (enforced by
the index, not by the resolver being careful), if a shared website merges two companies,
if the backfill is not idempotent, if nameless rows are re-read on every boot for ever,
if a domain conflict is hidden, or if the backfill commits per row. **The boot pass now
runs AFTER seeding and purging** — both write the very rows it exists to link, and
running first left a fresh instance unlinked until its second boot. `link_people` moved
with it for the same reason. As in ADR-0050, nothing writes `org_id` at insert time; the
boot pass keeps it current, which is sufficient while the identity is read-only and is
the first thing to change when a surface starts writing it.

### ADR-0055 — Three roles, enforced in one place, with the break-glass exempt
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 4 (multi-user
auth) · `web/roles.py`, `web/app.py`, `web/accounts.py`
**Decision.** `owner` / `operator` / `viewer`, ranked. A `GET` needs `viewer`; any other
method needs `operator`; a declared list of irreversible, financial and destructive paths
needs `owner`. Enforced in the gate middleware. The first bootstrapped account is an
**owner** — an instance whose only account cannot release a delivery is worse than one
with no accounts at all.
**Why three.** A business this size has three kinds of person: the founder, a hire who
runs campaigns, and someone being shown around. More roles would be a permission system
nobody maintains; fewer would mean the first hire can assert a licence on a certificate
a client signs against.
**Two invariants, both more important than the rules.** The shared passphrase keeps FULL
access — it is the break-glass (ADR-0054), a break-glass that 403s is not one, and
restricting it would be theatre because whoever holds it can change the environment
variable. And an instance with **no accounts behaves exactly as before**: this must be
invisible until someone opts in.
**Enforced in the middleware, not at the routes**, for the reason the decision log is:
a rule applied at forty places is a rule missing from the forty-first. The cost is that
these are path patterns rather than domain calls; the mitigation is that the default is
RESTRICTIVE — a route added tomorrow is covered by its METHOD, so the failure mode is
"too strict", never "wide open". `roles.may(None, …)` returns True on purpose: an
unsigned-in caller is the passphrase or a token-gated client, both decided elsewhere, and
answering False would quietly turn this module into a second gate with different rules.
**On the password minimum.** Set to 9 at the operator's instruction, from my initial 10.
Recorded because it was a deliberate decision rather than an oversight: NIST SP 800-63B's
floor for a user-chosen password is 8, so 9 sits above the published bar, and the work
factor here is carried by scrypt rather than by length. It is now
`accounts.MIN_PASSWORD`, asserted against the constant so changing it again is one edit.
**Consequences.** `tests/test_roles.py` fails if a viewer can change anything, if an
operator can release a delivery / confirm a licence / delete an opportunity / move money,
if an owner cannot, if the first account is not an owner, if the passphrase loses access,
if an instance with no accounts is affected, if an unknown route stops defaulting to
restrictive, if the owner-only list starts matching by prefix, or if an unknown role name
grants anything.

### ADR-0054 — Accounts and sessions, added beside the passphrase and never instead of it
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 4 (multi-user
auth) · `web/accounts.py`, `web/auth_routes.py`, `web/shell.py`, `web/actor.py`
**Decision.** Real accounts (`user_account`) and real sessions (`user_session`).
`admin_authed` accepts EITHER a valid session OR the shared passphrase, and
`actor.identify` now returns the signed-in person's NAME — which is what ADR-0053 was
built as a seam for: the decision log gained names without one call site changing.
**THE INVARIANT: the passphrase keeps working, always.** It is break-glass, not legacy. A
change that could lock the operator out of the system running their business is not worth
any amount of tidiness, and the failure would arrive mid-deploy with no way back in.
Retiring it is a decision to take later, deliberately, with an account already proven —
and a test asserts it still works both with and without accounts present, and even when
session lookup raises.
**Security choices, and why each one.** `hashlib.scrypt` from the stdlib: memory-hard, and
NO new dependency, because this repo has twice shipped a declared dependency production
never installed (ADR-0043 amended, ADR-0048). The hash carries its own parameters, so the
cost can be raised later without invalidating existing passwords. Session tokens are stored
as SHA-256 digests — a session table full of live tokens is a table full of credentials,
readable from any backup. Revocation and expiry are checked on EVERY request, because a
session you cannot revoke is not a session, it is a password you cannot change; that is
also what makes disabling an account take effect immediately rather than in thirty days.
Sign-out revokes server-side rather than clearing a cookie. Authentication hashes even for
an unknown address, so response time does not enumerate who has an account.
**The first account comes from the environment.** A public sign-up page on an internal
console is an open door; a seeded default password is a published one. Env vars are set by
whoever already controls the deploy, so they prove nothing new — the right bar for a
bootstrap. It runs once and never resets an existing password, so leaving the variables set
cannot hand the account to whoever last edited the environment.
**Consequences.** Adding this pushed `app.py` to 799 lines against the 750-line guard, so
the auth routes moved into `auth_routes.py` — the guard did exactly its job, and raising the
limit instead is how a 9,133-line file happens a few lines at a time. `tests/
test_accounts_sessions.py` covers the lock-out cases first and the rest after: the
passphrase with and without accounts, a broken session lookup, a named actor in the log, a
passphrase actor that still admits it is shared, revocation, expiry, disabled accounts,
salting, a corrupt hash failing closed, and a bootstrap that never overwrites.
**Still to come:** roles (the column exists and nothing enforces it yet), and per-account
password change / invite.

### ADR-0053 — Every state change is attributable, before anyone can log in
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 4 (multi-user
auth with actor identity on every decision) — the FIRST slice · `web/actor.py`,
`web/app.py`, `web/db.py`
**Decision.** Every mutating request (`POST`/`PUT`/`PATCH`/`DELETE`) writes a row to
`decision_log`: when, who, what, and which record. The actor is derived in the gate
middleware from the request alone — admin cookie, `?k=`/`?r=` client token, or a
`/creator/<token>` path. `GET` is not logged. Writing is best-effort and off the event
loop: an audit trail that can 500 a client's approval is worse than no audit trail, and
by the time it runs the decision it records has already happened.
**Why this first, and why not login.** The launch review calls multi-user auth the
precondition for a first hire. The bottom of that is not a login form — it is knowing who
did what. Dozens of routes are decision buttons and the actor recorded on them was a
hardcoded `"Studio"`, `"ChordOS"`, or nothing. With one operator that is untidy; with two
it means **every past decision is unattributable and every future one ambiguous**. This
slice is additive, cannot lock anyone out of production, and everything the account work
will do depends on it. Doing it in the other order would mean building sessions on top of
a system that still could not say who acted.
**It records a ROLE, not a name — deliberately.** The admin gate is one shared
passphrase, so the system does not know *which human* is behind it. Writing "Jon" into an
audit trail on the strength of a shared secret would be a lie in the one record that
exists to be trusted, and it would be a lie that looks like evidence. It records which
door the request came through. When accounts arrive, the actor gains a name and **no call
site changes**.
**Recorded in the middleware, not at the routes.** Stamping forty decision routes by hand
would miss the forty-first, and the one it misses is the one someone disputes.
**Tokens are never written down.** A share token in a log is a credential in a log. The
stored value is a 12-character SHA-256 fingerprint: enough to recognise the same reviewer
across a campaign, useless to whoever reads the log.
**Consequences.** `tests/test_actor_identity.py` fails if a decision goes unrecorded, if a
page view is recorded (which would bury the record under traffic), if a FAILED attempt is
not recorded — the attempt is the interesting part, and a log holding only successes
cannot answer "who tried" — if a client on a share link is indistinguishable from the
operator, if a raw token reaches the log, if the operator is asserted to be a named human,
or if a broken log breaks the decision it was recording. `decision_log` is indexed by
subject, because "what happened to this project" must not scan every decision ever made.
**Still to come in this item:** real accounts and sessions, then roles. The actor model
above is the seam they plug into.

### ADR-0052 — The delivery lifecycle is decided in the engine, and cannot be mistyped
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 3 (domain
routers with the state machines moved into the engines) · `delivery.py`, `web/db.py`,
`web/project_routes.py`, `web/delivery_ops.py`
**Decision.** The non-obvious delivery transitions are named functions in `delivery.py`
— `state_on_version_published`, `state_on_client_approved`, `state_on_changes_requested`,
`state_on_approval_reopened`, `can_release`. They are pure functions of the delivery
record: they DECIDE, they do not write, and a human still presses the button. And
`db.update_delivery(..., "state", X)` **raises** on a state outside `DELIVERY_STATES`.
**Why.** The lifecycle lived in the route modules as **eighteen bare string literals
across three files**, so "publishing a version moves the ball to the client" was
re-decided at each call site and stated nowhere. That is not a tidiness complaint — it is
how the engine's own list drifted: **`"Approved"` was written and compared by the routes
while missing from `DELIVERY_STATES` entirely.** Anything iterating that list would have
silently omitted the state a client's sign-off produces. Found by listing every state the
code writes and diffing it against what the engine declares, which is now a test.
**A naming error caught in the writing, and worth recording.** A client requesting changes
and an operator reopening an approval are DIFFERENT events with different destinations —
`"In production"` (back to the studio) versus `"In review"` (look again at work that
exists). They were initially given one function name. Two rules behind one name is how one
gets "corrected" into the other by someone reading only the name, so they are separate
functions with the difference asserted.
**What was deliberately NOT done.** `"Delivered"` and `"Released"` stay as literals at
their call sites. `state_on_released() -> "Released"` is ceremony, not clarity; the
transitions worth naming are the ones whose destination is not obvious from the action.
Both are still covered by the write guard.
**Consequences.** `tests/test_delivery_state_machine.py` fails if any state the web layer
writes is not declared (the original defect, as a standing check), if an unknown or
mis-cased state can be written, if a *declared* state cannot be — the control, since a
guard that rejected a legitimate state would break the product where it claims to protect
it — if the change-request and reopen transitions collapse into one, or if `can_release`
stops agreeing with `license_confirmation`, which it delegates to precisely so there is
never a second definition of "confirmed".

### ADR-0051 — Ask once per render: a read memo, and batched priming
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 3 (batched
dashboard context) · `web/db.py`, `web/console_routes.py`
**Decision.** Two mechanisms, both scoped to ONE request and discarded with it. A
**memo** (`db.read_memo`) answers a repeated SELECT from memory and is invalidated by any
non-SELECT, so a handler that reads, writes and reads again cannot be served a stale row.
**Priming** (`db.prime_project_reads`) fetches in two batched queries what the render
would otherwise ask twice per project, and hands the answers to the memo *before* the loop
runs. Opt-in per handler: a cache you must ask for cannot surprise a handler that did not.
**Why.** The dashboard composes several cards from the same rows and each aggregator
fetched them for itself. Measured on the seeded demo — **four** projects — one render cost
**71 queries**, `SELECT delivery_json FROM projects WHERE id = ?` running nine times. No
individual function is wrong: `next_action.compute` and `compute_queue` are each correct
alone and each re-reads what the handler already read. Invisible on SQLite over a local
file; on Postgres every one is a network round trip, and the cost grows with the data:

| projects | batched | unbatched | saved |
|---|---|---|---|
| 4 | 51 | 71 | 28% |
| 12 | 99 | 215 | 53% |
| 38 | **255** | **683** | **62%** |

**Why priming rather than threading batched data through the callers.** Passing
pre-fetched rows into `next_action`, `compute_queue` and every future caller is a much
larger change, with the same result and more ways to be wrong. Priming leaves the per-row
code untouched — it simply stops reaching the database — so a new aggregator gets the
benefit without knowing this exists.
**Consequences.** `tests/test_dashboard_batching.py` fails if the memo serves an exhausted
cursor (a real cursor is consumed by the first `fetchall`, and handing the same one to the
second caller returns nothing — silently wrong, and worse than the duplicate query), if it
keys on SQL without parameters (which would hand every project the first project's
delivery blob — data corruption dressed as a performance fix), if a write does not
invalidate it, if a primed row still reaches the database, if a project with no row falls
through, or — the point of the whole thing — if the query count stops beating the
unbatched cost by a comfortable margin on the same data. And the page is asserted
**byte-for-byte identical** with both mechanisms disabled: a faster dashboard showing
something different is the only outcome that would make this worth reverting.

### ADR-0050 — A buyer is an email, or they are nobody
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 3 (buyer identity
as a canonical entity) · `web/db.py`, `web/app.py`
**Decision.** `buyer_person` is the canonical human on the buying side, keyed by a
normalised email with a UNIQUE index. `resolve_person` creates or matches; `link_people`
stamps `person_id` on the five tables that name a human and runs at boot;
`person_touchpoints` answers what one buyer has done with us across all of them.
**Identity is the email and only the email.** With no email, `resolve_person` returns
None — there is no canonical person and the row stays unlinked, on purpose.
**Why.** A buyer was recorded in five unlinked tables, each with its own name/email pair:
`decision_makers` (what enrichment found), `discovery_requests` (who asked for a call),
`meetings` and `meeting_proposals` (who was on it), `review_comments` (who approved the
work). The same person asks for a call, takes it, and signs off a master as three
strangers — and *"who is this and what have we done together"*, the question the business
actually has, could not be asked at all. Measured on one seeded instance: four rows, four
spellings of one name, four casings and paddings of one email.
**Why names are never matched.** Two people are called John Smith. One person is "Priya
Okonkwo", "P. Okonkwo" and "Priya". A CRM that merges humans on a name eventually
attributes one buyer's approval to another — in `review_comments`, which is the record a
client signs against. **A missing link is a gap; a wrong link is a lie.** Evidence or
nothing, and the gap is reported (`no_email`) rather than hidden.
**Scope, stated plainly.** This is the person half. **Organisations are NOT canonical
yet** — they are still `agencies.id` in some places and a bare `client` name string in
`opportunities.client`, `companies.client` and `client_procurement_history.client`, which
is the same class of defect one level up and a larger migration. Nothing here writes
`person_id` at insert time either; the boot pass is what keeps it current, which is
sufficient while the identity is read-only and is the first thing to change when a
surface starts writing it.
**Consequences.** `tests/test_buyer_identity.py` fails if one human across five tables
resolves to more than one buyer, if a name-only human is invented, if two people sharing a
name are merged, if the database accepts two rows for one email (enforced by the index,
not by the resolver being careful — it is called from request threads and a boot backfill),
if the backfill is not idempotent, if rows that can never be linked are re-read on every
boot for ever (38,924 decision makers make that expensive), or if the backfill commits per
row — which turns a one-off pass into tens of thousands of fsyncs and a boot into an
outage. Verified on real Postgres, where the duplicate is refused by the server.

### ADR-0049 — Merge one JSON key in one statement, not read-modify-write
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 3
(`delivery_json` concurrency) · `web/db.py`
**Decision.** `update_delivery` and `update_doc_override` merge a single key through
`db.merge_json_key`, which issues ONE statement — `json_set` / `json_remove` on SQLite,
`jsonb || jsonb` / `jsonb - key` on Postgres. No read-modify-write in Python. A concurrent
merge of a *different* key can no longer erase yours; a concurrent merge of the *same* key
is still last-write-wins, which is what "set this key" means.
**Why.** The old helper read the whole blob, set one key in Python, and wrote the whole
blob back. Two writers overlapping in that window and the later write carries a document
read *before* the earlier one, so the earlier change is gone — with **nothing raised and
both callers told they succeeded**. Reproduced with two threads doing what the product
does: a client approving an asset in the review portal while the operator published a
version in the console. **The client's approval vanished.** This is not an exotic
interleaving: publishing a version fires several `update_delivery` calls in a row, and the
review portal is open on someone else's screen throughout.
**Why not promote `versions` / `asset_approvals` to tables**, which is what the review
proposed. It would fix those two keys and leave `state`, `license`, `cues`,
`pending_version` and `delivery_zip` racing exactly as before — and two of those decide
what a client is looking at. It is also a large migration through the version ladder, which
is read almost everywhere. The one-statement merge fixes every key, including keys not
written yet, and keeps the per-record JSON blob that CLAUDE.md names as a pattern to reuse.
Promotion remains available later, on its own merits (queryability across projects), rather
than as a concurrency fix it only partly performs.
**Consequences.** `tests/test_delivery_concurrency.py` runs the losing pair **in rounds
behind a `threading.Barrier`**, not once with a sleep: the first version of that test
PASSED on the broken implementation whenever the interleaving happened not to occur, and a
race test that passes intermittently on broken code is worse than no test because it is
read as evidence. Measured 4/4 failing before the fix, 3/3 passing after. Also pinned: every
JSON shape round-trips (a merge that stringified a list would corrupt the ladder rather
than lose it), `None` removes exactly one key while `""` sets it (both conventions are
load-bearing — the pending slot is cleared with `""`), a hostile key is refused rather than
interpolated into a JSON path, and a column already holding non-JSON still merges by
falling back to the old rewrite instead of 500ing on a client's page.
`tests/test_postgres_dialect.py` repeats the whole thing on a real server, because the SQL
is dialect-specific and passes through the translation shim.

### ADR-0048 — Pooled Postgres connections, behind the one door
**Status:** Accepted (2026-08-06) · Source: `docs/launch-review.md` Phase 3 (request-scoped
connections / pooling), a cutover precondition · `web/db.py`, `web/app.py`, `pyproject.toml`
**Decision.** A process-wide `psycopg_pool.ConnectionPool` sits **behind** `db.connect()`,
not in front of it: every one of the 254 existing call sites is unchanged, `close()` hands
the connection back instead of tearing it down, and SQLite is untouched. Bounds are
`CHORDENTIAL_DB_POOL_MIN`/`_MAX` (1–10), kill switch `CHORDENTIAL_DB_POOL=0`, and the pool
is closed at shutdown so a draining instance stops holding a slice of a capped connection
limit the incoming one is trying to claim.
**Why.** `connect()` is called 254 times across the web layer, several per page, each
closed immediately. On SQLite that is a file open and genuinely cheap — which is exactly
why nobody noticed. On Postgres it is TCP + TLS + auth to another host before a single row
is read. Measured on a real Postgres 16 over loopback (the friendliest possible case),
25 connect/close cycles: **25 distinct server backends and 3.95 ms per connect without the
pool; 2 backends and 0.38 ms with it.**
**Why not request-scoped connections instead.** That was the review's phrasing, and it
would mean a contextvar plus touching every call site, for a benefit the pool already
delivers — and it would still open a real connection per request. Pooling is the change
that makes the connection *cheap*; scoping only makes it *rarer*. Scoping can follow later
on top of a pool, and is worth nothing without one.
**Why SQLite keeps its own path.** Its connections are cheap, and a pooled SQLite
connection shared across the handler threadpool is a hazard rather than an optimisation.
**On the optional dependency.** `psycopg_pool` arrives with the `postgres` extra
(`psycopg[binary,pool]`). It is optional, and this repo has already lost uploads to a
declared dependency production never installed — `render.yaml` carried the `s3` extra while
Render built from its **stored dashboard command**, so writes landed with zero copies while
the boot line announced durability (ADR-0043, amended). So a missing pool degrades to
exactly today's behaviour **and says so at boot**, and the cutover runbook checks for it in
the shell before the flip. It must not be possible to believe pooling is on when it is not.
**Consequences.** `tests/test_db_pool.py` asserts reuse against the SERVER's own
`pg_backend_pid()` — a pool that quietly reconnects cannot pass by claiming otherwise —
and covers what matters more than the speed: a borrowed connection never carries the
previous borrower's open transaction (with a committed-work control, because a pool that
rolled everything back would pass the isolation test and lose every write in the product),
eight threads borrowing at once, a wedged pool degrading to a direct connection rather than
a 500 on a client's review portal, and `close_pool()` actually releasing the server's
connections. `close()` rolls back before returning: `close()` on an uncommitted connection
already discarded the work, and preserving that explicitly is what keeps a pooled
connection from carrying a snapshot and its locks into the next request.

### ADR-0047 — Declared indexes, because there were none
**Status:** Accepted (2026-08-05) · Source: `docs/launch-review.md` Phase 3 (indexes —
"there are none"), a cutover precondition · `web/db.py`
**Decision.** One declared list, `db._INDEXES`, applied by `_ensure_indexes` from
`_ensure_schema` — so existing databases get them on the next boot, not only fresh ones.
`CREATE INDEX IF NOT EXISTS` on both backends, best-effort per index (one bad entry must
not stop the other fifty, and an index is never worth failing a boot over). Every entry is
a real access path in the code; an index nothing reads is pure write cost.
**Why.** `CREATE INDEX` appeared **zero times across 53 tables**. Measured on a seeded
database with `EXPLAIN QUERY PLAN`, **13 of 16 hot queries full-scanned**, including both
client-facing token lookups — the query that begins every review-portal and first-touch
page load. The three that did not scan were fast by accident: SQLite builds an autoindex
for a UNIQUE constraint, so a few access paths were covered for a reason nobody chose.
After: **0 of 16**, with 51 indexes created.
**Why it is a cutover precondition.** SQLite over a local file hides this completely — a
scan of a few hundred rows already in page cache is free, and these tables are small.
Postgres over a network is a different machine: the same scan crosses a socket page by
page, on a connection that was itself just opened (see the connection-per-call note in
ADR-0046). The cost does not appear gradually as data grows; it appears the day the
database moves, on every screen at once.
**Consequences.** `tests/test_indexes.py` asserts the ACCESS PATHS, not the index names —
an index that exists but that the planner declines to use is not a fix, and a test reading
`sqlite_master` alone would pass on one. It also fails if a declared index was not created
(creation is best-effort, which is exactly how one could silently vanish), if a name is
declared twice (IF NOT EXISTS would accept the second while it indexed something else), if
an entry names a column that has since been renamed, and if the migration path stops
applying them to a database that already exists — the one database that matters.
`tests/test_postgres_dialect.py` repeats it on a real server with `enable_seqscan = off`,
because on a seeded table Postgres correctly prefers a sequential scan regardless, so
"which plan is cheapest today" would answer the wrong question.

### ADR-0046 — One scheduler across instances, by lease and not by advisory lock
**Status:** Accepted (2026-08-05) · Source: `docs/launch-review.md` Phase 3 (scheduler
advisory locks, a cutover precondition) · `web/db.py`, `web/scheduler.py`, `web/app.py`
**Decision.** `run_loop` holds a row in `scheduler_lease` and does nothing without it.
The holder renews every base tick; the lease carries an expiry (3 ticks, floored at 90s)
so a killed instance hands the engines on by itself, and shutdown releases explicitly so
a handover costs seconds rather than a full TTL. Checked EVERY tick, never once at boot —
leadership is not a property of startup order, and the instance that wins at 09:00 may be
the one being drained at 09:02. A DB it cannot reach counts as NOT held: two instances
running everything is worse than neither running for one tick. Manual cycles from the
console are deliberately ungated — an operator pressing a button should get work on the
instance that served the request. Kill switch `CHORDENTIAL_SCHEDULER_LEASE=0`.
**Why a lease and not `pg_try_advisory_lock`**, which is what the review asked for. An
advisory lock is held by a SESSION, and this codebase opens a connection per call and
closes it — **254 `db.connect()` sites** — so a lock taken that way releases microseconds
later. Holding one would need a dedicated long-lived connection, and would still leave
SQLite, which is what production runs *today* and what every test runs, with no protection
at all. A lease row is decided by one atomic UPDATE, works identically on both backends,
and survives `SIGKILL` — which an advisory lock also does, but only because the session
dies with it, and that is exactly the property we cannot rely on here.
**Why it is a cutover precondition, not a follow-up.** Every coordination primitive in
`scheduler.py` is in-process — a `threading.Lock` and module-level monotonic timers — on
the documented assumption of a single instance. Blue-green breaks that assumption *on
purpose*: for the minutes the two services overlap, both loops run. Outreach sends twice,
meeting bots are polled twice, two enrichment batches contend for one CPU. None of it
raises, and **a second copy of an email is not an error anywhere in this system** — it is
a client receiving the same message twice from a studio that is meant to look precise.
**Consequences.** `tests/test_scheduler_lease.py` fails if two owners can both hold it, if
a holder cannot renew (which would stop the engines after one TTL and never restart them),
if an expired lease is not taken over, if a non-holder can release, if the loop does any
work without the lease — and, as the control, if it does no work *with* it. The expiry
format is asserted fixed-width, because the comparison is string-wise in SQL and
`isoformat()` drops microseconds on the exact-zero tick. `tests/test_postgres_dialect.py`
covers it on a real server, including that the LOSER's connection is still usable: Postgres
aborts a transaction on a constraint violation, so a missing rollback would turn the loser
into `InFailedSqlTransaction` and take the instance down instead of standing by. The
Discovery console shows when this instance is standing by, because "the engines are
elsewhere" and "the engines are stopped" look identical otherwise and only one is a fault.

### ADR-0045 — The Postgres path is verified against a real Postgres
**Status:** Accepted (2026-08-04) · Source: `docs/launch-review.md` Phase 3 (Postgres in
CI for the dialect shim) · `web/db.py`, `scripts/migrate_sqlite_to_postgres.py`,
`docs/zero-downtime-cutover.md`
**Decision.** The SQLite→Postgres compatibility layer is exercised against a **running
PostgreSQL server**, not reasoned about. `tests/test_postgres_dialect.py` unit-tests the
translator everywhere and runs the live path when `CHORDENTIAL_TEST_PG` is set. The
translator gains `BLOB → BYTEA` and `COLLATE NOCASE → LOWER()`; the migration script only
resets an `id` sequence for tables that have one.
**Why.** The shim was a **regex SQL translator that had never met a Postgres** —
`psycopg` was not installed, so every claim about the cutover was plausible rather than
tested. Standing up PostgreSQL 16 found three defects, each of which fails *during* the
cutover, with the disk already being decommissioned: **`BLOB` is not a Postgres type**, so
`media_blob` (the DB mirror of every uploaded master) could not be created and the app
would not boot; **`COLLATE NOCASE` does not exist**, so `/agencies`, the decision-maker
list and the roster 500 on their first query; and the **migration script called
`pg_get_serial_sequence(t, 'id')` for every table** — `media_blob` is keyed by `name` —
so it crashed mid-copy after several tables were already written, on production data.
The third is the worst: a half-migrated database is harder to reason about than a failed
one.
**Consequences.** The whole path is now verified end to end on a real server: the schema
builds, every console route serves, writes work (the shim fakes `lastrowid` with
`RETURNING id`), the migration completes with matching row counts, and an uploaded master
survives the round trip **byte-for-byte by SHA-256**. `psycopg[binary]` stays the
optional `postgres` extra. **Skipping is not passing:** the live tests skip without
`CHORDENTIAL_TEST_PG`, and a green CI run without it says nothing about Postgres — which
is precisely how the shim reached production untested. Run them against a scratch
database before the real cutover. Two things this ADR does **not** do: it does not
perform the cutover (no Render credentials here), and it does not remove the disk — the
uploads migration (ADR-0043) is still an unrun ops step and remains the gating item.




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
