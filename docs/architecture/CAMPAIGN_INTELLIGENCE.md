# Campaign Intelligence — the Canonical Parent Object

*Design spec (no code). Campaign Intelligence is the single, living, provenance-tracked
record of everything known about one engagement. It is born immediately after a discovery
call, enriched continuously through the campaign's life, and is the object every downstream
module inherits from and contributes back to. This document designs its **schema,
lifecycle, ownership, and provenance model** before any code is written.*

**Date:** 2026-07-02 · **Supersedes the "Discovery Intelligence" naming** in
`DISCOVERY_INTELLIGENCE_LINEAGE.md` (the trace that motivated this). · **Reads with:**
`CONSTITUTION.md` (§6 the moat, §10 one source of truth per fact, §4.1 machine proposes /
human disposes), `campaign-workspace-prd.md`.

---

## 0. The shape of the idea

```
        DISCOVERY CALL            ← the birth event (the call is captured, structured)
              │
              ▼
     ┌───────────────────────────────────────────────┐
     │           CAMPAIGN INTELLIGENCE                │  ← the canonical parent object
     │  one living, provenance-tracked record per      │     (1 per engagement)
     │  engagement. Every fact has {value, sources[],  │
     │  status}. Owns nothing it can inherit; unifies  │
     │  demand + buyer intel + creative direction.     │
     └───────┬───────────────────────────┬────────────┘
             │ inherits ▲ contributes-back │
             ▼          │                  ▼
        PROPOSAL ───────┘        CAMPAIGN WORKSPACE
             │                          │
             ▼                          ▼
        (reads CI to draft)      PRODUCTION      CREATIVE
                                     │              │
                                     └──────┬───────┘
                                            ▼
                                        DELIVERY
                                            │
                                            ▼
                             contributes outcomes back to CI
                             → rolls up to Agency Intelligence (the moat flywheel)
```

**The one rule this object exists to enforce:** *no module recreates what it can inherit.*
Every surface reads its facts **from** Campaign Intelligence and writes its enrichments
**back to** it — carrying provenance — so the engagement has exactly one source of truth
that gets smarter with every step (Constitution §10 + §6).

---

## 1. What Campaign Intelligence is (and is not)

**Campaign Intelligence is a *living* object.** It is not created once at intake and frozen.
It is **continuously enriched across the entire engagement lifecycle** — Campaign Intake seeds
it, then Proposal, Campaign Workspace, Production, Creative, Client Success, Delivery, and the
post-project retrospective each contribute new facts, insights, recommendations, and open
questions through the *same* provenance model. That is what makes it the **institutional
memory** of the engagement — and, on confirmation, the source that enriches **Agency
Intelligence** so the next opportunity for that buyer starts smarter (the moat flywheel,
Constitution §6). No module owns a private copy; every module reads from and writes back to
this one object.

**It is** the canonical, per-engagement intelligence record: a stable spine that outlives
the opportunity → project → campaign transitions and unifies four bodies of knowledge that
today live in disconnected universes:

- **Demand** — what the client asked for (from the opportunity + qualification).
- **Buyer** — who they are and how they work (from Agency/Company Intelligence, reachable
  via the `agency_id` link built in Step 1).
- **Creative direction** — the sound they want (from the discovery call, enriched).
- **Commercial + outcome** — budget, rights, revisions, and what actually happened.

**It is not:**
- **not the opportunity** — the opportunity is demand-side and can predate the call; CI is
  born *at* the call and links to the opportunity.
- **not the campaign** — the campaign (workspace) is born at *win*; CI exists before it,
  and the campaign's creative-direction cards become a *projection of CI*, not their own
  store.
- **not a copy of Agency Intelligence** — CI *inherits* buyer facets (by snapshot + link);
  the agency record remains their owner. CI never re-authors what an engine already knows.

One CI per engagement. Opportunity, campaign, and project each carry a
`campaign_intelligence_id`; the agency is reached through it.

---

## 2. Schema

Three tables. The design principle: **provenance is per fact**, so facts are rows (not
columns) — that is the only shape that can carry `{value, sources[], status}` per field and
render the provenance card. Additive + migration-safe (ADR-0007), backend-portable.

### 2.1 `campaign_intelligence` — the root

The identity + links + coarse lifecycle. Holds *no facts* itself (facts live in fields).

| Column | Purpose |
|---|---|
| `id` | PK |
| `opp_id` | the demand link (1:1, nullable — a call may precede a formal opp) |
| `agency_id` | the buyer link (from Step 1's thread) |
| `campaign_id` / `project_id` | the workspace/production links, set at win (nullable) |
| `title`, `brand`, `agency_client` | denormalized labels for lists (the truth is in fields) |
| `state` | coarse lifecycle: `seeded` \| `active` \| `delivered` \| `archived` |
| `discovery_call_at` | the birth timestamp (when the call was captured) |
| `created_at`, `updated_at`, `archived_at` | |

### 2.2 `campaign_intelligence_field` — the provenanced facts (the heart)

One row per canonical fact. This is what every card renders and every module reads/writes.

| Column | Purpose |
|---|---|
| `id` | PK |
| `ci_id` | → campaign_intelligence |
| `facet` | the group: `engagement` \| `buyer` \| `direction` \| `commercial` \| `relationship` \| `outcome` (see §3) |
| `key` | the canonical field key within the facet (e.g. `emotional_arc`) |
| **`kind`** | **the epistemic type: `fact` \| `insight` \| `recommendation` \| `open_question` (see §4bis) — what *kind* of knowledge this is** |
| `value` | the text value (short/rendered) |
| `value_json` | structured value when the fact is a list/object (references, decision makers) |
| `sources` | JSON list of producers supporting this value — the card's ✓ list (§4) |
| `status` | the disposition (kind-aware — §4bis): facts `needs_review→confirmed`, recommendations `open→accepted/deferred/declined`, questions `open→answered`, insights `noted→acknowledged/dismissed` |
| `origin` | the primary producer that last authoritatively set it |
| `confidence` | 0–100, optional |
| `is_concern` | flag: this insight/question is a **risk** the producer flagged (surfaced prominently) |
| `contributed_by` | last writer (`operator` \| `ai` \| module name) |
| `updated_at` | |
| — | UNIQUE(`ci_id`, `facet`, `key`, `kind`) — a fact and an insight can co-exist on the same key (e.g. the *stated* brief vs. the producer's *read* of it) |

### 2.3 `campaign_intelligence_event` — the enrichment log (append-only)

Every inherit/contribute/confirm is an event. This is the audit trail **and** the moat feed
(revision-by-segment, direction→approval, reference effectiveness all derive from it).

| Column | Purpose |
|---|---|
| `id`, `ci_id` | |
| `actor` | `operator` \| `ai:<employee>` \| module name |
| `verb` | `seeded` \| `inherited` \| `proposed` \| `enriched` \| `confirmed` \| `superseded` \| `conflicted` |
| `facet`, `key` | which fact |
| `from_value` / `to_value` | the change (audit) |
| `source` | the producer |
| `created_at` | |

**Reconciliation with today's tables:** the increment-1 `campaign_direction` table (section,
body, complete) becomes the *seed* for `field` rows under `facet='direction'` (source =
`workspace`); the workspace then reads CI. `campaigns`, `opportunities`, `projects` each gain
a nullable `campaign_intelligence_id`. Nothing is rewritten in place — CI is **lazy-created
and back-filled** (§5), exactly as `campaigns` was.

---

## 3. The field catalog (facets → keys → their real source)

The canonical facts, each mapped to the **module that actually produces it today** — so the
catalog is implementable against the current codebase, not invented. `⟳` = inherited from an
engine (CI references, doesn't author). `✎` = authored in the engagement (call/operator/AI).
`↩` = contributed back during production/delivery.

| Facet | Key | Primary source (today) | Kind |
|---|---|---|---|
| **engagement** | `brand`, `agency`, `budget_band`, `deadline`, `contact`, `primary_discipline`, `deliverables_scope` | Opportunity + `qualification` (discipline, team_shape) | ⟳ / ✎ |
| **buyer** | `brand_history`, `music_characteristics`, `previous_campaigns` | Agency **enrichment** (`AgencyProfile`: portfolio, clients, awards, music characteristics) | ⟳ |
| **buyer** | `agency_notes`, `production_complexity`, `buying_tendencies`, `typical_clients`, `campaign_types` | Agency **Company Intelligence** (`intel_json`: executive_summary, production_complexity, music_usage, typical_clients, campaign_types) | ⟳ |
| **buyer** | `decision_makers` | `decision_makers` engine | ⟳ |
| **direction** | `emotional_arc`, `reference_playlist`, `tone`, `do_list`, `dont_list`, `agency_intent`, `producer_notes` | **Discovery call** + operator + AI (A&R / proposals) | ✎ |
| **commercial** | `estimate`, `contracted_revisions`, `license_terms`, `rights_scope` | `estimation` + proposal + `delivery` license | ⟳ / ↩ |
| **relationship** | `prior_outcomes`, `communication_style`, `cadence` | Buyer graph (`buyer_intel`, won deals, `agency_outreach`) | ⟳ |
| **outcome** | `approved_direction`, `actual_revisions`, `references_that_landed`, `delivered_versions`, `final_rights` | Production + review + `delivery` | ↩ |

The `direction` facet is the heart of the workspace and the one with **no current source
object** — which is exactly why the discovery-call capture (§5.1) must exist for CI to be
born complete. The `buyer` facet is the moat, now reachable via Step 1's `agency_id`.

---

## 4. Provenance model

Every fact carries **who says so** (`sources`) and **how settled it is** (`status`). This is
the model behind the requested card and the literal implementation of "one source of truth
per fact" + "machine proposes, human disposes."

### 4.1 Sources — *who supports this value* (multiple allowed)
`transcript` · `producer_debrief` · `rfp` · `email` · `notes` · `agency_intelligence` ·
`opportunity` · `qualification` · `proposal` · `workspace` · `ai` · `production` ·
`creative` · `client_success` · `delivery` · `retrospective` · `operator`

A field can have several (the card's ✓ list): e.g. `emotional_arc` supported by
`transcript` + `agency_intelligence` + `ai`. The **`producer_debrief`** source is
special: it carries the human's *interpretation*, so it predominantly backs `insight`,
`recommendation`, and `open_question` fields — never dressed up as objective `fact`
(§4bis). Sources map to the Campaign Intake capture modalities (`campaign-intake-prd.md`).

### 4.2 Status — *how settled it is* (the disposition gate)

| Status | Meaning | Who sets it |
|---|---|---|
| `empty` | no source yet — shown honestly as "not yet observed," never guessed | — |
| `proposed` | a machine/AI or a non-owner module proposed a value | AI / contributor |
| `needs_review` | inherited or contributed; awaiting a human's disposition | inherit / contribute |
| `confirmed` | a human disposed it — the authoritative value | **operator only** |
| `superseded` | replaced by a newer confirmed value (kept in the event log) | system |
| `conflicted` | a new contribution differs from a `confirmed` value — surfaced, never silently clobbered | system |

**The gate (Constitution §4.1):** machines and non-owner modules can only ever reach
`proposed`/`needs_review`. **Only the operator confirms.** A contribution that would change a
`confirmed` value becomes `conflicted` (a human resolves it), never a silent overwrite. This
is how "continuously enriched" stays safe — enrichment proposes; the human disposes.

### 4.3 Ownership — *who is authoritative for a facet*

Inherit-and-contribute-back only works if each facet has a clear owner; everyone else is a
contributor who proposes.

| Facet | Owner (authoritative) | Contributors (propose → review) |
|---|---|---|
| `buyer` | Agency / Company Intelligence engines | operator annotations |
| `direction` | discovery call + operator | AI (A&R, proposals), agency feedback |
| `engagement` | opportunity + qualification | operator |
| `commercial` | estimation + proposal | delivery (final rights ↩) |
| `relationship` | buyer graph | operator |
| `outcome` | production + delivery | AI summaries |

**Rule:** an owner writing its *own* facet may auto-`confirm`; any *cross-module*
contribution lands `needs_review`. This keeps the engines authoritative for what they know
while letting every module enrich without stepping on each other.

### 4.4 The provenance card (the concrete UI mapping)

Every direction/buyer card on any surface is a render of one `campaign_intelligence_field`:

```
 Emotional Arc                         ← facet=direction, key=emotional_arc
 "Warm nostalgia at open, building
  to a triumphant, communal release."  ← value
 Source:                               ← sources[]
   ✓ Discovery Call
   ✓ Agency History
   ✓ AI Generated
 Status:  ⟳ Needs Review               ← status ; the [Confirm] button is the disposition
```

`[Confirm]` flips `status → confirmed`, writes a `confirmed` event, and (for `buyer`/`outcome`
facets) can **contribute back to Agency Intelligence** — the flywheel that makes the next
campaign for this buyer start smarter (Constitution §6).

---

## 4bis. Epistemic kinds — *what kind of knowledge is this?*

Provenance answers *who says so*. **Kind** answers *what kind of knowledge it is* — and the
two are orthogonal. This is the distinction the Producer Debrief exists to preserve: an
engagement is not just a pile of facts. It is facts **plus** a producer's read of them,
**plus** what we should do, **plus** what we still don't know. Collapsing those into one
undifferentiated "notes" field destroys the most valuable, least-captured asset in a
creative-service business — human judgment — and it lets inference masquerade as fact.

| Kind | What it is | Typical source | Disposition lifecycle | How downstream treats it |
|---|---|---|---|---|
| **`fact`** | An objective statement grounded in a source ("budget is $18–24k") | `transcript`, `rfp`, `email`, `notes`, `opportunity` | `needs_review → confirmed` (or corrected) | **Asserted.** The proposal states it; delivery relies on it. |
| **`insight`** | An inferred human interpretation ("*warm* means nostalgic, not saccharine"; "the real approver is the CD") | **`producer_debrief`**, `ai` | `noted → acknowledged` (or `dismissed`) | **Weighed, never asserted as fact.** Shapes direction; shown as a read, attributed. |
| **`recommendation`** | A proposed course of action ("lead with Direction A; don't show the orchestral option") | **`producer_debrief`**, `ai` | `open → accepted / deferred / declined` | **A choice.** Surfaced to the operator as an option to act on. |
| **`open_question`** | An acknowledged unknown or risk ("unclear if they have final sign-off"; "brand team hasn't been in the room") | **`producer_debrief`**, gap-analysis | `open → answered / dropped` | **Drives follow-ups + risk surfacing.** A blocker to be closed, not a fact. |

Rules:
- **Kind is never silently promoted.** An `insight` does not become a `fact` because it feels
  true; a producer or a corroborating source must assert it as fact. Inference stays labeled
  as inference (honesty rule, §7).
- **A key can hold more than one kind** (the UNIQUE constraint includes `kind`): the *stated*
  emotional arc (a `fact` from the transcript) and the producer's *read* of it (an `insight`
  from the debrief) coexist and are shown side by side — the objective and the interpreted,
  never conflated.
- **Risks** are `insight` or `open_question` fields flagged `is_concern` — surfaced
  prominently (the producer's "watch out for X" is first-class, not buried).
- **Disposition is kind-aware but still one gate:** in every case a *human* moves it from its
  open state (machine proposes, human disposes, §4.1). Facts get confirmed; recommendations
  get accepted/deferred/declined; insights get acknowledged; questions get answered.
- **The card renders the kind**, so a reader instantly knows what they're looking at:
  `✓ Fact` · `◈ Insight (producer's read)` · `→ Recommendation [accept · defer]` ·
  `? Open question / ⚠ Risk`. The objective and the interpreted never look the same.

This is what lets every downstream module behave correctly: the proposal **asserts** facts,
**weighs** insights, **surfaces** recommendations as choices, and **flags** open questions as
risks — instead of treating one producer's hunch as gospel or losing it entirely.

---

## 5. Lifecycle — born at the call, enriched to delivery, archived as precedent

### 5.1 Birth — via Campaign Intake (the capture experience, designed separately)
CI is born from a **Capture** — see the full experience spec in
`docs/campaign-intake-prd.md`. Two refinements that spec settled and this model adopts:
**(a)** CI is born at the *first capture of ANY modality* (voice, transcript, RFP, email,
or auto-seed from an opportunity) — not specifically "a discovery call." **(b)** A
**Capture** is an *immutable evidence record* (one per input, holding the raw source + its
extraction); **Campaign Intelligence** is the *living synthesis* enriched by one or many
captures. Each CI field cites the capture(s) it came from — source attribution for free.

A capture, once ingested, seeds/enriches CI in one transaction:
1. creates the `campaign_intelligence` root (`state=seeded`, `discovery_call_at=now`),
2. links the `opp_id` and resolves/links the `agency_id` (reusing Step 1's matcher),
3. **seeds `direction.*` fields** from the call (`sources=[discovery_call]`,
   `status=needs_review`),
4. **snapshots `buyer.*` fields** from the linked agency's enrichment + intel
   (`sources=[agency_intelligence]`, `status=needs_review`),
5. **pulls `engagement.*` fields** from the opportunity + qualification
   (`sources=[opportunity, qualification]`),
6. lets the AI **propose** any empty `direction` gaps (`sources=[ai]`, `status=proposed`) —
   never buyer facts (those must be real intel).

> An engagement that reaches production without a captured call still gets a CI —
> **auto-seeded** at project creation from the opportunity + agency (see §5.6). A discovery
> call is the *ideal* birth; a CI for *every* engagement is the *requirement*.

### 5.2 Proposal — reads CI, drafts from it, writes refinements back
The capabilities/first-touch/proposal doc renders from CI (`engagement` + `direction` +
`commercial`). Any edit the operator makes writes back to CI (`source=proposal`), so the
proposal stops being a dead-end that strands data in `doc_overrides`.

### 5.3 Win → Campaign Workspace inherits (stops recreating)
At win, the campaign is created linked to CI. Its creative-direction cards become a
**projection of CI.`direction`.*** — pre-filled, each showing its sources + `needs_review`.
The increment-1 `campaign_direction` rows migrate into CI `direction` fields
(`source=workspace`). No more empty cards; no more recreation.

### 5.4 Production / Creative — contribute back
As directions are chosen, versions submitted, and feedback given, the modules **contribute
back**: `outcome.approved_direction`, `outcome.actual_revisions`,
`outcome.references_that_landed` (`source=production`, `status=needs_review`). The Feedback
Analyst AI proposes summaries (`source=ai`, `proposed`).

### 5.5 Delivery — finalize + capture outcomes
Delivery writes `commercial.final_rights`, `outcome.delivered_versions`, and confirms the
cue-sheet metadata back to CI. On completion, outcome facets **roll up to Agency
Intelligence** and the buyer graph — the moat metrics (revision-by-segment, direction→
approval, reference effectiveness) are computed from the CI event log.

### 5.6 Coarse `state` machine (the CI record itself)
`seeded` (post-call) → `active` (in production) → `delivered` → `archived`. This is
intentionally coarse; the real disposition lives in per-field `status`. An archived CI is
retained permanently as the engagement's record **and** as reusable precedent for the next
campaign with that buyer.

---

## 6. Ownership & governance (who may write what, safely)

- **Every write is provenanced and gated.** No module writes a bare value; it writes a
  `{value, source, status}` through the CI API, which enforces §4.2 (non-owners can't reach
  `confirmed`; a change to a `confirmed` value → `conflicted`).
- **The operator is the sole confirmer** — the human disposition the constitution requires.
- **The engines own what they compute** (buyer intel, estimate) and may auto-confirm their
  own facet; they never author `direction` (the craft brief is human).
- **AI never confirms and never authors buyer facts.** It proposes `direction` drafts and
  `outcome` summaries, always labeled `ai` + `proposed`.
- **Nothing is silently overwritten.** Conflicts surface; the event log is append-only; the
  record is auditable end to end (who/what/when for every fact).

---

## 7. Inherit + contribute-back mechanics (the anti-recreation contract)

The whole point, stated as a contract every downstream module honors:

1. **Read-through, never copy.** A surface renders a fact by reading its CI field. It does
   **not** keep its own store. (The workspace's `campaign_direction` becomes a projection.)
2. **Write-back, always provenanced.** A surface that learns something writes it to CI as a
   contribution (`{value, source, status}`), never to a private column.
3. **One canonical value per fact** (the UNIQUE constraint) — additional supporters add to
   `sources`, they don't fork the value.
4. **Confirm enriches upward.** Confirming a `buyer`/`outcome` fact can feed Agency
   Intelligence + the buyer graph — the flywheel.

This is exactly the fix for the lineage breaks: the modules that today *recreate* (empty
campaign cards) or *strand* (proposal → `doc_overrides` on the opp) instead **inherit** and
**contribute back** through one object.

---

## 8. Constitutional alignment

- **§10 one source of truth per fact** — CI *is* that source; the field store makes it
  literal.
- **§4.1 machine proposes, human disposes** — the `status` gate; only the operator confirms.
- **§6 the data flywheel is the moat** — contribute-back rolls outcomes into Agency
  Intelligence; the event log is the moat's raw material.
- **§7 evidence-first / honesty** — every field cites its `sources`; an `empty` field reads
  "not yet observed," never a guess.
- **Additive / migration-safe (ADR-0007), backend-portable (ADR-0006)** — new tables +
  nullable FKs + lazy backfill; no rewrite. Warrants a new **ADR** when built (CI as the
  canonical parent is a binding decision).

---

## 9. Open decisions for Jon (needed before code)

1. **Birth trigger.** Ideal = "Log discovery call" (requires building the call-capture
   intake). Requirement = every engagement has a CI. *Recommendation: build the call intake
   as the primary birth, AND auto-seed a CI at project creation so nothing is left without
   one (backfill covers existing campaigns).*
2. **Buyer facets: snapshot vs. live read-through.** *Recommendation: **snapshot** the agency
   intel into CI at birth (+ a "refresh from agency" action), so a delivered campaign's record
   is stable and auditable and doesn't mutate when the agency is re-enriched later — but can
   be pulled forward on demand.*
3. **Field store vs. structured columns.** *Recommendation: the **field store** (§2.2) —
   per-field provenance is the entire point; columns can't carry it.*
4. **AI ambition at birth.** *Recommendation: AI proposes only `direction` gaps + a first-draft
   emotional arc from the call notes (clearly `ai`/`proposed`); never buyer facts.*
5. **Confirmation load.** *Recommendation: owner-module writes to their own facet auto-confirm;
   cross-module + AI contributions need review — so the operator confirms what matters, not
   everything.*

## 10. Migration-safe build sequence (once approved)

1. **Tables** — `campaign_intelligence`, `_field`, `_event`; nullable
   `campaign_intelligence_id` on opportunities/campaigns/projects (additive).
2. **Lazy create + backfill** — a CI for every campaign on open, seeded from opportunity +
   agency (Step 1 link) + the increment-1 `campaign_direction` rows. Every existing campaign
   gets a CI; nothing is lost.
3. **Point the workspace at CI** — direction cards render CI fields with the provenance card
   (sources + status + Confirm). `campaign_direction` becomes a projection.
4. **Discovery-call capture** — the birth intake; seeds `direction.*`.
5. **Proposal + production + delivery read/write CI** — inherit + contribute-back wired
   module by module; buyer-facet snapshot + refresh.
6. **Flywheel** — confirmed `buyer`/`outcome` facts roll up to Agency Intelligence + the buyer
   graph.

Each step ships behind the workspace flag, dogfood-first, and passes the anti-generic-PM and
constitutional gates. Step 1 (the `agency_id` thread) is already in place and feeds step 2
directly.

---

*This is a design, not a commitment to code. It answers schema, lifecycle, ownership, and
provenance so the build can begin from a settled parent-object model rather than discovering
it mid-implementation. The naming decision — **Campaign Intelligence** — is adopted here and
should be reflected in the lineage doc and the roadmap.*
