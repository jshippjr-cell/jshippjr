# Campaign Workspace — Product Requirements Document

*The Creative OS module of ChordOS. The single source of truth for an entire campaign
music project — brief, creative direction, team, timeline, references, cues, versions,
stems, reviews, approvals, rights, and delivery — on one screen, one campaign,
everything.*

**Status:** Architecture / PRD (no code yet) · **Author:** ChordOS product architecture
· **Date:** 2026-07-02 · **Reads with:** `docs/architecture/CONSTITUTION.md`,
`docs/architecture/ARCHITECTURE_DECISIONS.md`, `docs/product-roadmap.md`.

---

## 0. Framing — the third OS, and the law that governs it

ChordOS is becoming three systems stacked on one spine:

```
                 ChordOS
   ┌───────────────────────────────────┐
   │  Intelligence OS   (BUILT)         │  discover, understand, qualify, reason,
   │                                    │  CRM, opportunity, proposal
   ├───────────────────────────────────┤
   │  Workflow OS       (PARTIAL)       │  projects, tasks, production, delivery,
   │                                    │  status, approvals, QA, rights
   ├───────────────────────────────────┤
   │  Creative OS       (THIS MODULE)   │  the campaign music workspace —
   │                                    │  where the work actually gets made
   └───────────────────────────────────┘
```

Intelligence OS wins the work. Workflow OS tracks the work. **Creative OS is where the
music is made** — and it is the layer that makes ChordOS impossible to copy, because it
encodes something no horizontal tool understands: *how original campaign music actually
gets from a brief to an approved, cleared master.*

### The governing law of this module

> **Before any feature is designed, built, or accepted, it must pass one test:**
> *"Does this make ChordOS feel more like the operating system for campaign music — or
> am I recreating a generic project-management app?"*
> If it feels like generic PM software, **stop and re-evaluate.**

This is not a slogan; it is an acceptance criterion. Section 21 turns it into a
per-feature smell test. Every object, state, and automation below is chosen because it
is *native to campaign music* — not because a PM tool would have it.

**What makes this a music OS and not Asana:**
- The atoms are **musical** — cues, versions, stems, mixes, references, cue sheets,
  clearances — not generic "tasks" and "files."
- The timeline is a **creative arc** (Ideation → Directions → Reviews → Revisions →
  Approval), not a todo board with columns.
- The team is a **music crew** (composer, orchestrator, mixer, contractor, supervisor,
  session players), each with a real role in how music is produced.
- The AI employees **organize, document, and summarize the craft — they never make it**
  (Constitution §8: no AI-generated craft).
- It inherits the **procurement-grade** spine (rights, cue sheets, versioned masters,
  approval packages) that agencies actually require — the thing generic PM never has.
- It is fed by **Intelligence OS** — the brand history, the agency's notes, the previous
  campaigns — so creative direction starts informed, not blank.

### Alignment with the Constitution (non-negotiable inheritances)
- **The machine proposes, the human disposes** (§4.1) — every AI output and every
  automation is a proposal a human accepts; nothing auto-decides a creative outcome.
- **No AI-generated craft** (§8) — the music is human-made; AI reads, summarizes,
  documents, and plans around it.
- **Procurement-grade, evidence-first** (§7) — every asset and clearance is real,
  documented, and traceable.
- **Honesty** (§4.3) — demos use invented brands; nothing implies real client work.
- **One source of truth per fact** (§10) — the campaign is *the* record; nothing about a
  campaign lives in someone's head or a side channel.

---

## 1. Business purpose

**Turn "managing a music project" into "opening one campaign and seeing everything."**

Today, a single campaign's music lives scattered across email threads, a DAW on someone's
laptop, a Dropbox of exports, a spreadsheet of revisions, a separate delivery portal, and
the producer's memory. The producer is the integration layer — a bottleneck and a single
point of failure. The Campaign Workspace replaces that scatter with **one durable,
shared, source-of-truth surface per campaign**, so that:

1. **Nothing is lost or re-improvised.** Brief, direction, references, decisions,
   versions, feedback, and deliverables live in one place, versioned and attributed.
2. **The work compounds.** Every campaign captures structured creative and operational
   data (directions tried, revisions by segment, reference→approval patterns, cue
   metadata) that feeds the ChordOS moat (Constitution §6) and makes the *next* campaign
   faster to direct, staff, and deliver.
3. **The studio operates above its size.** A two-person studio presents like a
   twenty-person one: procurement-grade, organized, on-time, with a clear paper trail.
4. **The client and creators experience the same truth.** The agency reviews and approves
   inside the workspace (token-gated); the composer works and submits inside it. One
   record, three windows — no divergence.

**Business outcome metrics (Phase A / dogfood):** cycle time from win→first direction and
direction→approval; revisions per approval; on-time delivery rate; "context re-asked"
count (should trend to zero); and moat growth — structured directions, reference→outcome
links, and revision-by-segment data captured per campaign.

---

## 2. Primary users

| # | User | Where they live | What the workspace is *to them* |
|---|---|---|---|
| **P1** | **Operator / MD / Producer** (Jon) | Internal, full access | Mission control. Sets direction, staffs the crew, runs internal review, drives the agency approval, presses every decision button. |
| **P2** | **Composer / Creator** (assigned talent) | Token-gated creator view of the campaign | Their studio-in-a-browser: the brief + direction + references they need, where they submit versions and stems, and read the client's timecoded feedback. |
| **P3** | **Agency reviewer / Client** (buyer) | Token-gated agency review view | A clean, procurement-grade window: hears the current direction, leaves timecoded notes, requests changes, and gives final approval — never sees the machinery. |
| **P4** | **Supporting crew** (mixer, orchestrator, contractor, session players, supervisor) | Token-gated, role-scoped creator view | Their slice: the cue and stems they touch, their tasks, their deliverables. |

Secondary (future phases): **P5 — the paying operator** (Phase B: another studio running
its campaigns on ChordOS) and **P6 — the buyer as platform user** (Phase C).

**Rule:** P2–P4 reach the workspace by unguessable per-record token (ADR-0011), never a
shared login; each sees only their scoped slice (Section 19).

---

## 3. User stories

**Operator / Producer (P1)**
- As the producer, when I win a music opportunity, I want a campaign workspace to open
  pre-populated with everything Intelligence OS already knows (the brief, the brand
  history, the agency's notes, our previous campaigns with them), so creative direction
  starts informed, not blank.
- I want to define the creative direction (emotional arc, reference playlist, agency +
  producer notes) as a structured, checklist-able thing, so the composer inherits a
  complete brief and I can see at a glance what direction is still missing.
- I want to assemble the music crew (composer, mixer, orchestrator, contractor) from our
  roster with one click each, and have each person notified with their scope.
- I want to move the campaign along a creative timeline (Ideation → Direction A/B →
  Internal Review → Agency Review → Revisions → Approval) and always know exactly what
  stage it's in and what it's waiting on.
- I want to run an internal review *before* anything reaches the agency, so we never
  show the client unvetted work (Constitution §4.1; publish gate).
- I want to send the agency a clean review link, collect their timecoded feedback, and
  have an AI employee summarize it into a concrete revision plan I approve.
- I want to see, in one place, every version, stem, and deliverable, with rights and cue
  sheets attached, and release the final package with one button.

**Composer / Creator (P2)**
- As the composer, I want to open the campaign and immediately see the direction,
  references, and notes — not hunt through email — so I can start writing.
- I want to submit a version (and its stems) into the campaign and have it wait for the
  producer's internal review, not go straight to the client.
- I want the client's feedback shown to me pinned to the exact second, grouped and
  de-duplicated into what actually needs to change, so I revise once, correctly.
- I want to see my revision count against what's contracted, so scope is never a surprise.
- I want my credit and payment tracked on the deliverable I made.

**Agency reviewer / Client (P3)**
- As the agency producer, I want one link that opens the current direction, lets me play
  it and leave notes at exact moments, and request changes or approve — without an
  account, without seeing anyone's internal process.
- I want to compare Direction A vs Direction B, and later v2 vs v3, so I can make a real
  choice.
- I want the final delivery — masters, stems, cutdowns, cue sheet, rights summary —
  organized and downloadable the moment I approve.

**Supporting crew (P4)**
- As the mixer, I want to see only the cue and stems I'm mixing, the mix notes, and where
  to drop my exports — not the whole campaign.

---

## 4. Core workflows

Each is a first-class flow the workspace is built around (detailed state machines in
Sections 14–17).

1. **Open a campaign.** A won opportunity → "Open campaign workspace" → a campaign is
   created and hydrated from Intelligence OS (brand, agency notes, prior campaigns,
   estimated roles). *Machine proposes the hydration; producer confirms/edits.*
2. **Set creative direction.** Producer fills the Creative Direction card (emotional arc,
   references, agency/producer notes, brand history) — the composer's brief.
3. **Staff the crew.** Producer assigns roles from the roster; each creator is notified
   with scope (reuses the signing-scope email). *Producer assigns; nothing auto-assigns.*
4. **Explore directions.** Composer submits Direction A / Direction B as cue versions.
   Internal review first.
5. **Internal review → agency review.** Producer vets, then publishes the chosen
   direction(s) to the agency review surface. *Publish gate (ADR-0003).*
6. **Collect + summarize feedback.** Agency leaves timecoded notes; the Feedback Analyst
   AI employee summarizes into a proposed revision plan; producer approves it.
7. **Revise.** Composer works the approved revision plan; submits the next version;
   internal → agency review; repeat within the contracted revision budget.
8. **Approve.** Agency gives final approval on the current version per cue.
9. **Clear + document.** Rights/clearance certificate, cue sheet, metadata, version
   naming, folder org assembled (the Delivery OS agents).
10. **Deliver.** The delivery room presents masters, stems, cutdowns, rollout matrix,
    approval package, rights summary — released on approval + payment gate.
11. **Capture + learn.** Outcomes (revisions used, directions tried, reference→approval,
    estimate-vs-actual) write back to the moat.

---

## 5. Objects that belong inside the workspace

The nouns of the Creative OS. Each is a real, versioned, attributed object — never a
freeform note.

- **Campaign** — the workspace root (the engagement: "Nike Holiday 2027"). Holds status,
  agency/brand link, budget, deadline, contracted terms.
- **Creative Direction** — the structured brief: **emotional arc**, **reference
  playlist**, **agency notes**, **producer notes**, **brand history**, **previous
  campaigns** (each a checklist-able, evidence-linked section).
- **Cue** — a distinct piece of music in the campaign (the :60 anthem, the sonic logo,
  the :30 cutdown if scored separately). *This is the key elevation: a campaign has many
  cues; each cue has its own versions, stems, reviews.*
- **Creative Direction Option** — a *Direction A / Direction B* — a proposed creative
  approach, realized as a cue version, that the agency chooses between.
- **Version** — a numbered iteration of a cue (v1 Concept → v2 Direction-lock → v3 FINAL),
  each with an audio file, label, state, and provenance (who submitted).
- **Stem** — a component export of a version (drums, brass, strings, vocal, FX…), named
  and typed.
- **Asset** — any file in the campaign, typed: **DAW session**, **reference track**,
  **export**, **version master**, **stem**, **mix notes**, **document**.
- **Reference** — a reference track/playlist entry with *why it was chosen* and what it
  informs (an evidence object, not a loose link).
- **Creative Team member** — a roster creator in a music role (composer, mixer,
  orchestrator, contractor, supervisor, session player), scoped to cues.
- **Task** — a *musical* unit of work tied to a cue/role/stage (e.g. "orchestrate brass
  for v2 anthem"), never generic. Kept lightweight and subordinate to the creative
  timeline.
- **Review thread** — timecoded comments/change-requests/approvals on a specific cue
  version (reuses `review_comments`, now cue-scoped).
- **Revision** — a bounded round: the approved change plan + the version that answers it,
  counted against the contract.
- **Approval** — an internal or agency sign-off on a cue version, attributed and dated.
- **Clearance / Rights** — the cue/campaign clearance certificate (chain of title,
  license grant, Content-ID state).
- **Cue sheet** — the procurement document (per cue / per campaign).
- **Deliverable** — a scoped output (master :60, cutdown :30, social 9:16, stems pack,
  sonic logo) with a status and a delivered file.
- **Delivery package** — the assembled, rights-attached ZIP + the delivery room.
- **Activity event** — one entry in the unified campaign timeline.
- **AI employee output** — a stored, human-reviewable artifact (suggested references,
  cue sheet draft, feedback summary, revision plan, version comparison).

---

## 6. States of a campaign

The campaign's life is a **creative arc**, not a kanban. Two levels: the **campaign
phase** (where the whole engagement is) and, beneath it, each **cue's version state**
(the existing v1→FINAL ladder) and each **deliverable's status**.

**Campaign phase (the creative timeline as a state machine):**

```
 Briefing ─▶ Direction ─▶ Internal Review ─▶ Agency Review ─▶ Revisions ─▶ Approved ─▶ Delivered ─▶ Archived
     │           │              │                  │              │            │            │
   (set        (A/B          (producer          (client        (bounded    (final       (package
    creative    directions    vets before        timecoded      rounds,     sign-off     released,
    direction)  submitted)    client sees)       feedback)      counted)    per cue)     paid)
                                                      ▲              │
                                                      └──────────────┘  (revise → re-review loop)
```

- **Briefing** — creative direction being assembled; crew being staffed.
- **Direction** — composer exploring; Direction A/B versions submitted (internal only).
- **Internal Review** — producer vets a version before any client exposure (publish gate).
- **Agency Review** — a published version is with the agency for timecoded feedback.
- **Revisions** — approved change plan in progress; loops back to review; bounded by the
  contracted revision count (surfaced, never silently exceeded).
- **Approved** — agency final approval captured (per cue; campaign is Approved when all
  in-scope cues are approved).
- **Delivered** — rights + cue sheet + package assembled and released (payment-gated).
- **Archived** — closed; retained as moat data and reusable reference.

**Transitions are human-driven** (Constitution §4.1). The system *proposes* the next
state ("all cues approved — ready to assemble delivery?") but a person advances it. Every
transition writes an activity event and can fire notifications.

Health flags overlay the phase (not new states): **overdue** (past deadline),
**revision-budget-at-risk** (rounds ≥ contracted), **stalled** (no activity N days),
**awaiting-you** (a decision is parked on a specific user).

---

## 7. Required database tables

Additive and migration-safe (ADR-0007), backend-portable (ADR-0006). The existing
`projects` row is **elevated into a campaign** (compat path in Section 22); new child
tables add the creative layer. JSON blobs are used only for genuinely freeform state
(mirroring `delivery_json`), structured rows where we need to query or checklist.

| Table | Purpose | Key columns |
|---|---|---|
| **`campaigns`** | The workspace root. (Elevates/wraps `projects`.) | `id`, `project_id` (compat link), `opp_id`, `agency_client`, `brand`, `title`, `phase`, `budget_min/max`, `deadline`, `contracted_revisions`, `share_token`, `status`, `created_at`, `archived_at`, `creative_json` (freeform direction blob) |
| **`campaign_direction`** | Structured creative-direction sections (checklist-able). | `id`, `campaign_id`, `section` (emotional_arc \| agency_notes \| producer_notes \| brand_history \| previous_campaigns), `body`, `complete`, `source` (manual \| hydrated), `updated_at` |
| **`campaign_references`** | Reference tracks/playlists with rationale. | `id`, `campaign_id`, `cue_id?`, `url`, `title`, `why`, `informs` (mood \| tempo \| instrumentation \| structure), `added_by`, `created_at` |
| **`cues`** | Distinct pieces of music within the campaign. | `id`, `campaign_id`, `name`, `kind` (anthem \| cutdown \| sonic_logo \| bed \| stinger), `length_sec`, `state` (the v-ladder state), `current_version_n`, `sort`, `created_at` |
| **`cue_versions`** | Version ladder per cue (moves `delivery_json.versions` under cues). | `id`, `cue_id`, `n`, `label`, `direction_tag` (A \| B \| null), `url`, `filename`, `stem_of?`, `submitted_by` (talent_id), `pending` (publish gate), `state`, `created_at` |
| **`stems`** | Component exports of a version. | `id`, `cue_version_id`, `name`, `kind` (drums \| bass \| brass \| strings \| vocal \| fx \| synth \| other), `url`, `filename`, `created_at` |
| **`assets`** | Typed file registry for the whole campaign. | `id`, `campaign_id`, `cue_id?`, `type` (daw_session \| reference \| export \| master \| stem \| mix_notes \| document), `url`, `filename`, `label`, `uploaded_by`, `created_at` |
| **`campaign_team`** | Music crew ↔ campaign/cue, with music roles. | `id`, `campaign_id`, `cue_id?`, `talent_id`, `role` (composer \| orchestrator \| mixer \| contractor \| supervisor \| session), `rate`, `rate_unit`, `scope_note`, `status` (invited \| active \| done), `created_at` |
| **`campaign_tasks`** | Music-scoped work items (subordinate to the timeline). | `id`, `campaign_id`, `cue_id?`, `assignee_talent_id?`, `title`, `stage` (which timeline phase), `status`, `due_at`, `created_at` |
| **`review_comments`** *(existing, extended)* | Timecoded feedback/approval/change per cue version. | *add* `cue_id`, `cue_version_id`; keep `t_seconds`, `author`, `email`, `body`, `kind`, `resolved`, `parent_id`, `verified` |
| **`revisions`** | Bounded revision rounds per cue. | `id`, `campaign_id`, `cue_id`, `round`, `plan_json` (the approved change list), `requested_by`, `from_version_n`, `to_version_n?`, `status` (planned \| in_progress \| answered), `created_at` |
| **`approvals`** | Internal + agency sign-offs per cue version. | `id`, `campaign_id`, `cue_id`, `cue_version_n`, `level` (internal \| agency), `by_name`, `by_email`, `verified`, `decision` (approved \| changes), `note`, `created_at` |
| **`deliverables`** | Scoped outputs and their status. | `id`, `campaign_id`, `cue_id?`, `spec` (master_60 \| cutdown_30 \| social_916 \| stems_pack \| sonic_logo…), `status` (scoped \| produced \| approved \| delivered), `asset_id?`, `created_at` |
| **`clearances`** | Per-cue/campaign rights certificate state. | `id`, `campaign_id`, `cue_id?`, `warranty`, `license_json`, `content_id_state`, `signatory_json`, `confirmed_by`, `confirmed_at` |
| **`campaign_activity`** | The unified event timeline (elevates `project_updates`). | `id`, `campaign_id`, `cue_id?`, `actor` (talent_id \| 'operator' \| 'agency' \| 'ai:<employee>'), `verb`, `object_type`, `object_id`, `body`, `visibility` (internal \| creator \| agency), `created_at` |
| **`ai_outputs`** | Stored, reviewable AI-employee artifacts. | `id`, `campaign_id`, `cue_id?`, `employee` (a&r \| feedback_analyst \| revision_planner \| version_analyst \| documentarian), `kind`, `input_ref`, `output_json`, `status` (proposed \| accepted \| dismissed), `created_at`, `decided_by`, `decided_at` |

Existing `delivery_json` (per-project) is **retained** as the delivery-room state and
re-homed conceptually under the campaign; its `versions`/`assets`/`reviewers`/`license`
machinery is superseded by the structured tables above over time (compat, Section 22).

---

## 8. Relationships between tables

```
opportunities ─1:1─ campaigns ─1:1─ projects (compat/delivery state)
                       │
    ┌──────────────────┼───────────────────────────────────────────┐
    │                  │                                             │
 campaign_direction  cues ─1:N─ cue_versions ─1:N─ stems         campaign_team
 (sections)            │             │                            (crew ↔ cue)
 campaign_references   │             ├─1:N─ review_comments
 (rationale)           │             ├─1:N─ approvals
                       │             └─ referenced by revisions (from/to version)
                       ├─1:N─ revisions (bounded rounds)
                       ├─1:N─ deliverables ─0:1─ assets
                       └─1:N─ clearances
    assets (typed files) ─N:1─ campaign  (and 0:1 cue)
    campaign_tasks ─N:1─ campaign (0:1 cue, 0:1 assignee)
    campaign_activity ─N:1─ campaign (0:1 cue)  ← every mutation writes here
    ai_outputs ─N:1─ campaign (0:1 cue)         ← proposals awaiting human disposition
```

Cardinalities that matter:
- **campaign 1:N cues** — the elevation that separates "engagement" from "piece of music."
- **cue 1:N cue_versions 1:N stems** — the real music hierarchy.
- **cue_version 1:N review_comments / approvals** — feedback and sign-off attach to a
  *specific* version, so history is exact (who approved which second of which version).
- **campaign 1:1 project** — a compatibility bridge to the existing delivery machinery;
  new campaigns may eventually not need a `projects` row at all.
- **talent N:M campaigns/cues** via `campaign_team` — a composer can be on many
  campaigns; a campaign has many crew.

Referential rules: deleting a campaign cascades to its children; a `talent` row is never
hard-deleted while referenced (payment/credit history). PII from any external creator has
a delete path (ADR-0009).

---

## 9. UI pages

The workspace is **one page with tabs** (the "one screen, one campaign, everything"
principle), plus the token-gated external windows.

**Internal (operator, full):**
1. **Campaign Home** — the command view. Header (brand · agency · phase · deadline ·
   health flags), the Creative Direction summary, the Creative Timeline rail, the crew,
   the cue list with per-cue state, "what's waiting on whom," and the AI proposals inbox.
2. **Creative Direction** — the structured brief editor (emotional arc, references,
   agency/producer notes, brand history, previous campaigns), each section checklist-able
   and evidence-linked to Intelligence OS.
3. **Cue view** — per cue: the version stack (with waveform players), Direction A/B
   compare, stems, mix notes, the review thread, revision rounds, approval state.
4. **Team** — the crew board (roles ↔ people ↔ cues), assign/scope/notify, rates, credit.
5. **Assets** — the typed file library (DAW sessions, references, exports, versions,
   stems, docs), filterable by cue/type.
6. **Reviews & Approvals** — internal-review queue and the agency-review status per cue;
   the approval ledger.
7. **Delivery** — the delivery room assembly (masters/cutdowns/stems, cue sheets, rights,
   rollout matrix, approval package, release + payment gate). *(This is today's delivery
   console, now a tab of the campaign.)*
8. **Activity** — the full campaign timeline (filterable by actor/visibility/cue).

**External (token-gated):**
9. **Agency Review window** — the client's view of a published cue version: play, compare
   directions/versions, timecoded notes, request changes, approve. Procurement-grade,
   no machinery.
10. **Creator Workspace window** — the assigned creator's scoped view: their cues, the
    direction + references, submit version/stems, read the summarized client feedback,
    revision count, credit + payment.
11. **Delivery Room** — the client's final delivery surface (existing), now the campaign's
    delivered face.

---

## 10. Components

Reusable, music-native building blocks (many already exist and are elevated):

- **`<cue-player>`** — waveform + click-to-seek + version chip + rights badge (exists;
  shared across internal cue view, agency review, creator window, delivery room).
- **Timecoded comment layer** — pins notes to waveform positions; groups/threads;
  resolve toggle (exists; extended to cue-scoping).
- **Direction A/B compare** — two players side-by-side with a "choose this direction"
  action for the agency.
- **Version stack** — the v1→FINAL ladder with state chips, provenance, and pending-badge
  for un-published creator submissions.
- **Creative Direction card** — the checklist-able brief sections with completeness meter
  and evidence links to Intelligence OS.
- **Creative Timeline rail** — the horizontal phase rail (Briefing→…→Delivered) with the
  current phase lit and the "waiting on" callout.
- **Crew board** — role→person tiles with scope, rate, status, and assign/notify.
- **Reference list** — reference tracks with *why chosen* and *informs* tags.
- **Stem grid** — per-version stem inventory (named/typed, upload/download).
- **AI Proposal card** — a stored AI output (references / feedback summary / revision plan
  / cue sheet / version compare) with **Accept / Edit / Dismiss** — the human-disposition
  control.
- **Revision plan** — the structured, approved change list per round, with progress.
- **Rollout matrix** — deliverables × placements grid (spec spec-grid, from the plan).
- **Rights/clearance card** — chain of title, license grant, Content-ID state, signatory.
- **Delivery room** — the assembled client delivery surface (exists).
- **Activity feed** — unified, filterable event stream.
- **Notification bell / phone push** — the alerting surface (exists; extended to campaign
  events).

---

## 11. AI employees that operate inside this workspace

The Creative OS extends the Delivery OS "five agents" (Rights, Revisions, Metadata,
Approvals, Assets) with **creative-stage AI employees**. Every one obeys the constitution:
**it proposes; a human disposes** (each output lands in `ai_outputs` as `proposed` with an
Accept/Edit/Dismiss control), it is **cost-gated** (ADR-0005), and it **never generates
the music** (§8). Where an output can be deterministic, it is; LLM calls are targeted and
cacheable.

| AI employee | Job | Input → Output | Honesty boundary |
|---|---|---|---|
| **The A&R** *(Reference Scout)* | Propose reference tracks/playlists for a brief. | Brief + brand history + agency's prior campaigns + discipline → a ranked list of *candidate references with rationale*. | Suggests **existing** references to listen to; does **not** create music. Human curates into `campaign_references`. |
| **The Feedback Analyst** *(Score Reader)* | Turn raw agency feedback into structured, actionable items. | Timecoded `review_comments` on a version → grouped, de-duplicated change items with timecodes, contradictions flagged. | Summarizes human feedback; adds no creative opinion of its own. |
| **The Revision Planner** | Turn approved feedback into a concrete plan. | Accepted feedback summary + cue/stem structure → a per-cue, per-stem revision plan (what changes, who does it). | Plans the work; the composer executes it. Human approves the plan (becomes a `revisions` row). |
| **The Version Analyst** | Compare versions honestly. | Two versions' change logs + review deltas + (if a real audio-analysis seam exists) waveform/loudness metadata → a "what changed" summary (structure/timing/instrumentation/loudness). | Reports differences from **recorded** data; does not invent musical analysis it can't substantiate (evidence-first, §7). |
| **The Documentarian** *(Metadata/Rights, elevated)* | Generate procurement docs. | Campaign + cue + team + license → cue sheet, metadata, version naming, folder org, clearance draft. | Assembles from real campaign data; a human confirms the clearance (ADR-0003). |
| **The Continuity Scout** | Surface the next best action per campaign. | Activity + stalls + revision budget + deadlines → "this campaign is waiting on X / at revision risk / ready to deliver." | Recommends; the producer acts. |

Explicitly **not** an AI employee (constitution boundary): anything that *composes,
arranges, mixes, or masters*. The craft is human. AI is the studio's clerk, analyst, and
librarian — never its artist.

---

## 12. Automations

Deterministic, event-driven, and always **proposing or documenting — never deciding a
creative or outward outcome** without a human (Constitution §4.1). Each is a rule over
campaign events, not an "agent."

- **On win → open campaign:** hydrate a new campaign from the opportunity + buyer graph
  (brand, agency notes, prior campaigns, estimated roles/cues); *producer confirms*.
- **On crew assignment:** send the scope email to the creator (exists), add a
  `campaign_team` row, write activity.
- **On creator version submit:** store as `pending` (publish gate), notify the producer,
  write activity — never expose to the agency automatically.
- **On producer publish to agency:** notify the agency reviewer(s) with their link, flip
  the version visible, advance phase to Agency Review.
- **On agency feedback received:** run the Feedback Analyst → post a *proposed* revision
  plan to the AI inbox; notify the producer.
- **On revision-budget threshold:** flag the campaign "revision-budget-at-risk" and
  surface it (never silently exceed the contract).
- **On all in-scope cues approved:** propose "assemble delivery package?" to the producer.
- **On approval + payment cleared:** unlock the delivery room downloads (payment gate).
- **On stall (no activity N days):** flag and surface via the Continuity Scout.
- **On any mutation:** write a `campaign_activity` event (the timeline is a side effect of
  everything, not a manual log).
- **On delivery:** capture outcomes to the moat (revisions used, directions tried,
  reference→approval, estimate-vs-actual).

Automations are **best-effort and fail-soft** (ADR-0004/0008): a failed notification or AI
call never blocks the underlying human action.

---

## 13. Notifications

Routed by role and channel; every notification ties to a campaign event and deep-links to
the exact place. Channels reuse the existing seams (in-app, web push, ntfy, email —
ADR-0004), fired **off the request thread** (ADR-0010).

| Event | Operator (P1) | Creator (P2/P4) | Agency (P3) |
|---|---|---|---|
| New version submitted | 🔔 push "review + publish" | — | — |
| Published to agency | — | — | ✉ "new version to review" |
| Agency left feedback / requested changes | 🔔 push + AI summary ready | — (after producer relays plan) | — |
| Revision plan approved | — | ✉ "your revision plan is ready" | — |
| Agency approved | 🔔 push | ✉ "your work was approved" | — |
| Delivery released | — | ✉ credit/payment note | ✉ "your delivery is ready" |
| Stall / revision-risk / overdue | 🔔 digest | — | — |
| Payment cleared | 🔔 | ✉ payout note | — |

**Principles:** high-signal only (precision over recall, §4.4) — batch low-priority into a
digest; every notification is actionable and deep-links; the agency and creator only ever
receive notifications about *their* scope; nothing notifies before a human has disposed
the underlying decision.

---

## 14. Approval workflow

Two levels, always **internal before agency** — the publish gate is the spine (ADR-0003):

```
Composer submits version ──▶ [PENDING]  (creator cannot expose to client)
                                 │
             Producer INTERNAL REVIEW (vets quality, direction fit)
                                 ├─ request internal changes ─▶ back to composer
                                 └─ PUBLISH to agency ─▶ [AGENCY REVIEW]
                                                              │
                        Agency reviewer (verified ?r= link) ──┤
                                                              ├─ request changes ─▶ Revisions
                                                              └─ APPROVE ─▶ [APPROVED] (per cue)
                                 All in-scope cues APPROVED ─▶ propose delivery assembly
```

- **Internal review** is mandatory and enforced by the flow (a creator submission is
  `pending` until the producer publishes) — the machine cannot show the client unvetted
  work (§4.1).
- **Agency approval** requires a **verified reviewer** (`?r=` token, locked roster
  identity) — a generic share link can view/comment but not approve (existing rule).
- Approvals are **per cue version**, attributed and dated (`approvals` table). The
  campaign is Approved when every in-scope cue is approved.
- Every approval/rejection writes activity and can fire notifications.
- **No auto-approval, ever** — not even on timeout. Silence is not consent.

---

## 15. Revision workflow

Revisions are **bounded, planned, and counted** — the anti-scope-creep discipline that
agencies respect and generic PM ignores.

```
Agency requests changes ─▶ Feedback Analyst proposes a revision plan (AI inbox)
                         ─▶ Producer ACCEPTS/edits the plan  ─▶ creates a [REVISION round]
                         ─▶ Composer works the plan          ─▶ submits next version
                         ─▶ internal review ─▶ publish ─▶ agency review ─▶ (approve | changes)
                         ─▶ round++ (checked against contracted_revisions)
```

- A revision **round** is a real object (`revisions`): the *approved change plan*, the
  from/to version, its status.
- The plan is **structured** (per-cue, per-stem change items with timecodes), derived from
  the agency's timecoded notes by the Feedback Analyst, then **approved by the producer** —
  the composer never guesses what "make it punchier" means; they get a concrete list.
- The **contracted revision count is always visible**; crossing it flags the campaign and
  surfaces a scope conversation — it is **never silently exceeded**.
- Each round links its feedback → plan → version → outcome, so revision-by-segment data
  (the moat metric: healthcare 2.7 / automotive 4.1 / tech 1.3) accrues automatically.

---

## 16. Version management

The v1→FINAL ladder, elevated **per cue** (not per project):

- **Numbered, labeled versions** per cue (`cue_versions`): v1 Concept → v2 Direction-lock
  → v3 FINAL, with a `direction_tag` (A/B) during exploration.
- **Provenance** on every version (who submitted, when) and a **pending flag** — creator
  submissions are pending until the producer publishes (publish gate).
- **Current version** = the latest *published* version the agency sees; internal drafts and
  pending submissions never count as current to the client.
- **Compare** any two versions (Direction A vs B; v2 vs v3) with the Version Analyst
  summary of what changed.
- **Approval locks FINAL** per cue; a new version after approval **reopens** review (a new
  master supersedes prior sign-off) — existing behavior, now per cue.
- **Immutable history:** versions are never overwritten; a superseded version stays
  playable and attributable (audit + rights integrity).
- **Naming is enforced** by the Documentarian (procurement-grade version names), not left
  to whoever exports.

---

## 17. Deliverable management

A **deliverable** is a scoped output the campaign owes the client — distinct from a
version (an iteration). One approved cue can yield many deliverables.

- **Scoped from the brief:** the required deliverables (master :60, cutdown :30, social
  9:16 vertical, stems pack, sonic logo) are enumerated per campaign/cue (`deliverables`),
  each with a status: **scoped → produced → approved → delivered**.
- **Completeness gate:** delivery does **not** silently ship a partial package as
  "everything" — if scoped deliverables aren't produced, the package is labeled partial
  and requires an explicit opt-in (existing delivery-completeness gate).
- **Rollout matrix:** deliverables × placements rendered as a spec-grid (broadcast :60/:30,
  social 9:16, cutdowns, stems) — operational clarity as the deliverable.
- **Every deliverable carries its paperwork:** cue sheet, rights summary, enforced naming,
  folder organization — assembled by the Documentarian, confirmed by a human.
- **Release is human + payment-gated:** the producer releases; downloads unlock when the
  invoice clears (existing payment gate).

---

## 18. Activity timeline

**Every mutation writes an event** (`campaign_activity`) — the timeline is a side effect
of the system operating, not a manual log. It is the campaign's memory and its audit
trail.

- **One unified stream** merging: direction edits, crew changes, version submissions,
  publishes, feedback, approvals, revisions, deliverable status, AI proposals + human
  dispositions, deliveries, payments.
- **Attributed** to an actor: a creator (talent_id), the operator, the agency reviewer,
  or an AI employee (`ai:<name>`) — so "who did what, when" is always answerable,
  including which AI proposed what and which human accepted it.
- **Visibility-scoped:** each event has `visibility` (internal / creator / agency); the
  agency and creator windows show only events they're entitled to (Section 19).
- **Filterable** by actor, cue, and visibility; deep-links to the object.
- **Feeds the moat:** the structured event history is the raw material for
  revision-by-segment, direction→approval, and cycle-time intelligence.

---

## 19. Permissions

Token-scoped, role-scoped, cue-scoped — never a shared login for external users
(ADR-0011). Three trust tiers:

| Capability | Operator (P1) | Creator (P2/P4) | Agency verified (P3, `?r=`) | Agency guest (`?k=`) |
|---|---|---|---|---|
| See full campaign (all cues, internal notes) | ✅ | — | — | — |
| See scoped cue(s) + direction + references | ✅ | ✅ (their cues) | ✅ (published only) | ✅ (published only) |
| Submit version / stems | via console | ✅ (their cues) | — | — |
| See internal (unpublished) versions | ✅ | own submissions | — | — |
| Leave timecoded feedback | ✅ | — | ✅ | ✅ |
| Request changes | ✅ | — | ✅ | ✅ (attributed) |
| **Approve** a version | ✅ | — | ✅ (verified only) | — |
| Publish creator work to agency | ✅ | — | — | — |
| Assign crew / edit direction / release delivery | ✅ | — | — | — |
| See other creators' rates / internal activity | ✅ | — | — | — |
| Accept/dispose AI proposals | ✅ | — | — | — |

- **Creators** see only their assigned cues and the direction/references for them — never
  the whole campaign, other creators' rates, or internal notes.
- **Agency** sees only *published* versions and agency-visibility activity — never
  internal review, pending submissions, crew rates, or the AI machinery.
- **Every decision button belongs to the operator** (§4.1). Approve is the one external
  action, gated to a *verified* reviewer.
- **PII delete path** for any external creator/reviewer (ADR-0009).

---

## 20. Future expansion

Held loosely (Constitution §11) — direction, earned not assumed.

- **Campaign templates & the direction library** — reuse successful directions and
  reference sets from past campaigns (the moat becomes a creative accelerant: "brands like
  this, in this vertical, approved directions like these").
- **Deeper agency integrations** — real DAW-session handoff, Frame.io/asset-manager
  bridges, calendar/scheduling for session players and studios (Production Scheduling).
- **Live session coordination** — booking rooms, contractors, and session musicians against
  a cue's needs (the "Contractor" role becomes a scheduling surface).
- **Rights & royalties depth** — PRO registration, split sheets, sync-license generation,
  Content-ID lifecycle (Rights Management matures from certificate → active administration).
- **Real audio intelligence seam** — a genuine analysis provider behind the Version Analyst
  (loudness, key, tempo, structure) — *analysis, never generation* (§8).
- **Multi-operator (Phase B)** — the workspace as the product other studios run their
  campaigns on; tenancy, roles, billing.
- **Buyer-side (Phase C)** — agencies opening campaigns *to* ChordOS and sourcing vetted
  creators through the graph; the workspace becomes the shared operating surface between
  demand and supply.
- **Cross-campaign creative analytics** — direction→approval rates, revision-by-segment,
  reference effectiveness, per-creator throughput — the Creative OS's own intelligence
  layer feeding back into Intelligence OS.

---

## 21. The anti-generic-PM doctrine (acceptance gate)

Every feature ships only if it passes the governing test. Applied to the core objects:

| Feature | Generic-PM version (❌ reject) | Creative-OS version (✅ ship) |
|---|---|---|
| The unit of work | A "task" on a board | A **cue** with versions, stems, and a review thread |
| Progress | % complete / columns | A **creative timeline** (Ideation→Directions→Reviews→Approval) |
| The brief | A description field | Structured **creative direction** (emotional arc, references, brand history) checklist-able and evidence-linked |
| Files | A generic attachment list | **Typed music assets** (DAW sessions, stems, masters, mix notes) |
| Feedback | Comments | **Timecoded** notes → AI-summarized → **bounded, counted revision rounds** |
| Approval | A checkbox / status | **Internal-then-agency**, verified-identity, per-cue, rights-attached |
| "Done" | Archived card | A **delivered, cleared, cue-sheeted, rights-summarized package** in a delivery room |
| AI | "Summarize this task" | Named **AI employees** that document/analyze the craft — never make it |
| The team | Assignees | A **music crew** (composer/orchestrator/mixer/contractor/supervisor) scoped to cues |

If a proposed feature can't be expressed in the right-hand column, it doesn't belong in the
Creative OS.

---

## 22. Migration & compatibility (from `projects`/`delivery_json`)

Additive and safe (ADR-0007). No big-bang rewrite.

1. **Introduce `campaigns` alongside `projects`.** Each existing project backfills one
   campaign (`campaigns.project_id` link); the campaign is the container, the project row
   keeps powering today's delivery/review machinery.
2. **Elevate cues.** New campaigns model music as `cues` + `cue_versions`; existing
   single-ladder projects map to a **single default cue** so nothing breaks.
3. **Extend `review_comments`** with `cue_id`/`cue_version_id` (nullable → backfill to the
   default cue) — the timecoded-review + audio-playhead work already built carries over.
4. **Re-home activity** from `project_updates` into `campaign_activity` (superset), keeping
   the old feed readable.
5. **Delivery room stays** — it becomes the campaign's Delivery tab; `delivery_json` is
   retained and gradually superseded by the structured tables as features move over.
6. **Feature-flag the workspace** (`CHORDENTIAL_CAMPAIGN_WORKSPACE`) so it ships behind a
   flag, dogfooded on one real campaign first (Constitution §4.2), before it replaces the
   project console.

---

## 23. Open questions for Jon (decisions needed before build)

1. **Campaign vs. Cue granularity:** confirm the campaign→cues model (a campaign can hold
   the anthem + sonic logo + cutdowns as separate cues), vs. keeping today's one-ladder
   project. *Recommendation: adopt cues — it's the elevation that makes this a music OS.*
2. **Directions as versions vs. a distinct object:** model Direction A/B as tagged cue
   versions (recommended, simpler) or as their own first-class object?
3. **AI employee ambition at launch:** ship the Feedback Analyst + Documentarian first
   (highest leverage, lowest risk) and add A&R / Version Analyst later — confirm the order.
4. **Where the workspace replaces vs. wraps** the existing project/delivery console: ship
   as a wrapping tabbed surface first (recommended), or rebuild the delivery console inside
   it immediately?
5. **Revision-budget enforcement:** hard-block past the contracted count (requires an
   explicit override), or flag-and-allow? *Recommendation: flag-and-surface, never
   silently exceed; overage is a human scope decision.*

---

*This PRD is a plan, not a commitment to code. Build order, once approved, is sequenced in
`docs/product-roadmap.md`, and every build cycle names the stage it advances and passes the
§21 doctrine before it merges.*
