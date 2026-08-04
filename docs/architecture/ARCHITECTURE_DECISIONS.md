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
keeps assuming `:30` for pricing; naming may not. Both upload paths (the admin Assets
agent, the composer portal) go through one helper, `app._master_stem()`; the manifest
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
if the two upload paths call `version_name` directly instead of sharing `_master_stem`.
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
