# ChordOS — Project State

*The "you are here." A living snapshot of what exists, what's in flight, and what's
deferred — so a new session orients in one read without spelunking. Update this when
the state materially changes; keep it short and current. For the enduring **why**,
read `CONSTITUTION.md`; for **binding decisions**, `ARCHITECTURE_DECISIONS.md`; for
**commands/conventions**, `/CLAUDE.md`.*

**Last updated:** 2026-07-18 · **Phase:** A (studio force-multiplier, dogfood-first)

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

## In flight — the Client Workspace + Commercial Commitment layer (ADR-0018)

The product is being reframed (operator directive, the "ten principles" in
`docs/client-workspace-principles.md`) as the OS for the **entire lifecycle of a
commercial music engagement**: one durable **Client Workspace** (one token-gated URL
that never changes), contents evolving by a computed **phase**
(`intro → discovery → brief → commercial → kickoff → production → delivery → archive`).
Client **commitment drives state** (approval of the Commercial Review is the primary
award trigger; operator buttons are fallbacks). Building foundation-first:
- **P0 (done):** durable workspace token (project inherits the opp token), the phase
  engine (`web/workspace.py`), `/workspace/{token}` shell, and the **Campaign Brief folded
  inline** via the stage-partial pattern (`_brief_document.html` + static `brief.css`). The
  workspace is the canonical client link (emailed link → `/workspace/{token}`).
- **P1 (done):** the **Commercial Review** (`web/commercial.py`) — the formal agreement,
  projected entirely from CI + estimation/proposals, **frozen at operator release**
  (`commercial_reviews`), rendered inline in the workspace as the brief's continuation, with
  a client electronic approval (`commercial_approvals`) that advances the phase to Kickoff.
  Operator decision: freeze-at-release + operator-released (see ADR-0018).
- **P4 (done):** **Kickoff — the Production Readiness Workspace** (`web/kickoff.py`). The
  client's Commercial approval is the **award trigger**: it creates the project and the
  workspace enters KICKOFF (gated from PRODUCTION by `projects.kickoff_completed_at`, which the
  operator stamps via "Start production"). A concierge handoff, not a form — campaign summary,
  production checklist, team, communication, milestones, and a "everything is ready" state,
  all projected from CI + the approved Review + the project. Legacy won projects (no approved
  review) skip Kickoff → Production, unchanged.
- **Production OS increment 1 (done, ADR-0019):** the Direction→Version spine on the
  EXISTING delivery machinery (`web/production.py`, no new tables): `directions` (territories
  with thesis + fate + rejection reasons), `round_log` (the ledger behind `revisions_used`,
  fed by review/changes, post-lock rounds stamped), `creative_lock` (a record, not a label),
  and the computed **court-state** (client|studio|scheduled + age). The Workspace PRODUCTION
  phase now answers the court question in concierge voice + shows the creative journey; the
  delivery portal remains the listening room. Operator: Directions card + lock on the
  delivery console. Business model: `docs/production-lifecycle-model.md` (agreed, both
  passes).
- **P2, P3, P5 (planned):** producer-voiced Terms engine (basic shipped in P1) →
  commitment/audit enrichment + DocuSign seam → adaptive procurement + delivery unification.
  See `docs/client-workspace-principles.md`; ADR-0018 for decisions.
- **Later:** CI → Relationship Intelligence (CI accumulates per client across campaigns).

## Recently completed (this working stretch)

- **The company architecture** (`docs/company-architecture.md`, 2026-07-18): the
  20-section first-principles redesign of Chordential as a company (AI-executive org,
  Disposition Queue doctrine, $1M roadmap). Amendments A-1/A-2 remain proposals;
  **A-3 was founder-ratified as a hard block → ADR-0024.**
- **ADR-0024 — the supply-side floor**: `talent.agreement_executed_at`/`agreement_ref`
  (additive), the Agreement block on the talent page, and a server-side refusal on both
  assign paths until agreement + rate are on file. Demo seed models the compliant state.
- **Disposition Queue v1** (`/queue`, `web/queue.py`): every pending founder decision on
  one deterministic, ranked surface (discovery requests → invoices → payouts →
  follow-ups → deal moves → taste-gate submissions → REVIEW-tier opps → reels → floor
  gaps → CI housekeeping). Pure aggregation; zero new decision logic; surfaces the
  funnel audit's hidden REVIEW volume without touching the precision-biased alert tier.
- **ADR-0014 reconstructed** in the ADR log (the captures-envelope ruling was cited by
  0021/0023 but its entry was missing).
- **The Scoring Stage — the composer's Session Room** (spec:
  `docs/design/chordos-studio-experience.md`; ADR-0025/0026). Phases 1–2 built and
  phase-gate reviewed by the standing 4-agent panel (Engineering / Design / Composer /
  Executive Producer). Phase 1: `creator_portal.html` rebuilt as the Session Room —
  one dark room per engagement, one shared playhead, summoned sheets (Brief/Notes/
  Takes on B/N/V, Esc), client feedback threaded with composer-addressed vs
  client-resolved separation, internal Ask-the-studio replies, publish-gated
  deliverables, needs-first room sort + `?p` doors (ADR-0025). Phase 2 (The Picture):
  the client's cut is the stage — client Drop upload with byte progress
  (`delivery_portal.html`), video master clock with audio follower + drift snap,
  timeline pins from timecoded notes (beyond-cut pins badge at the edge), new cut =
  **conform** event (free, per-note `conform · free` species chip, operator species
  toggle, cut ledger in the console), hearable references with rights-honest copy,
  storage per **ADR-0026** (disk + ≤64MB DB mirror, 512MB cut cap, chunked reads),
  stored-XSS serving policy on `/uploads` (inline media allowlist, attachment +
  nosniff otherwise, blocked markup extensions on references).

- **The Campaign Intelligence Extraction Engine (ADR-0023)** — extraction into CI is now
  an orchestrated system (`src/chordential_oia/extraction/`): ten parallel domain
  specialists over every artifact → deterministic validation (dedupe / flagged conflicts
  / impossible values) → a bounded recall loop ("what was missed?") → a merge that
  preserves evidence + alternates in `value_json`. Plugs into `campaign_intake`'s
  existing LLM seam; everything still writes through `contribute()` with capture stamps;
  null provider → deterministic heuristics unchanged. Design:
  `docs/architecture/EXTRACTION_ENGINE.md`.
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
  provenance model (`{value, sources[], status}`), inherited and contributed-back by every
  module. **✅ Campaign Intake designed** (`campaign-intake-prd.md`) — the *capture
  experience* that creates/enriches CI (user says "what happened"; AI extracts, asks only
  material gaps, produces CI invisibly). Two records: immutable **Captures** (evidence) →
  living **Campaign Intelligence** (synthesis). Vocabulary: *Capture* (user verb) /
  *Campaign Intake* (module) / *Campaign Intelligence* (system object, never shown).
  Two capture stances — **objective** ("what happened") + a first-class **Producer Debrief**
  ("what's your read?"). CI preserves the **epistemic kind** of every field —
  `fact` / `insight` / `recommendation` / `open_question` (+ risk flag) — so inferred
  judgment is never laundered into fact and the producer's read is a preserved asset.
  **✅ CI-1 built** — the living Campaign Intelligence object exists: tables
  (`campaign_intelligence` + `_field` with the epistemic `kind` + `_event` log),
  lazy-created + seeded per campaign from the opportunity (engagement facts), the linked
  agency (buyer facts — the moat, via the Step-1 thread), and the direction cards; the
  provenance panel on the campaign home renders every fact/insight/recommendation/
  open-question with its kind + sources + disposition, and the workspace now writes
  *through* CI (editing a direction contributes a fact — no private copy). Migration-safe
  (verified on an increment-1 DB).
  **✅ Intake-1 built** — the capture pipeline (paste-notes + Producer Debrief →
  extract/classify by kind → write through CI, with gap follow-ups).
  **✅ Opportunity-anchored (ADR-0013)** — Campaign Intake is now a first-class panel on
  the **Opportunity** page (above the Opportunity section + tabs), not gated behind Won.
  CI is born on and keyed by the opportunity; **"Update Intelligence"** ingests multiple
  modalities (notes / transcript / voice memo / RFP / email; audio behind a transcription
  seam); every CI field + the title + buyer name are **inline-editable and human edits are
  authoritative** (machine never clobbers a human-owned field — disagreements surface as
  **conflicts** to resolve); confirmed engagement facts **write back to the opportunity's
  own columns** so qualification/estimate/brief/outreach recompute from one source; and at
  Won the Project/Campaign Workspace **adopt the same CI in place** (nothing recreated).
  **✅ Intake framework (Increment 1, ADR-0014)** — Campaign Intake is now an extensible
  framework of **intake lanes** (`intake_lanes.py`, the single registry: discovery call,
  producer debrief, meeting notes/transcript, RFP, email thread, client brief), none
  privileged. Every lane normalizes to the ONE Capture **envelope** (`captures` gains
  lane/provenance_source/opp_id/metadata/artifact/external/status) and funnels through the
  ONE shared pipeline; every CI field + event now **cites its raw-evidence `capture_id`**
  (answers "why did this change?"). The discovery-call lane is present but honestly disabled
  until its notetaker seam is configured. `review_batch(capture_id)` derives a capture's
  proposed changes (feeds the Increment-2 review surface). Full design:
  `docs/discovery-call-intake-design.md`.
  **✅ Meeting domain (ADR-0015, increments 4-5)** — a **Meeting** is the business object;
  hosting (Zoom/Meet/Teams) and capture (Recall/Zoom AI/Fireflies) are two null-by-default
  seams (`meetings/` package). Everything downstream consumes a Meeting + a normalized
  **Transcript**, never a provider event: provider webhooks normalize into domain MeetingEvents
  in one place, and `campaign_intake.ingest_transcript(meeting, transcript)` is the boundary.
  The `/webhooks/capture/{provider}` receiver (signature-verified, idempotent, offloaded) +
  a gated scheduler fallback drive `Meeting → Transcript → Campaign Intake → CI`. Proven
  end-to-end with a fake Recall webhook (no creds); live Zoom/Recall HTTP is the credential
  flip. The Campaign Brief is the primary client artifact and carries the discovery CTA; the
  opp page shows an "Upcoming Discovery" panel only when a meeting exists.
  **Next (Increment 2):** the batched review surface ("review this call's updates" — the
  diff + confirm-all + projected downstream impact) over every lane; then the document/RFP/
  email parsers (3), and the live Zoom + Google Calendar + Recall credentials flip. Each stays
  flagged, dogfood-first, anti-generic-PM.
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
