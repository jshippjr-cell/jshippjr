# Discovery Intelligence — the Lineage Trace

> **Naming update (2026-07-02):** the parent object this trace calls for is now named
> **Campaign Intelligence** and is fully designed in
> [`CAMPAIGN_INTELLIGENCE.md`](./CAMPAIGN_INTELLIGENCE.md) (schema, lifecycle, ownership,
> provenance). This document remains the *trace of the breaks*; that document is the
> *design of the fix*. "Discovery" now refers to the **call** (the birth event), not the
> object.

*An architectural trace of how information should flow from a discovery call to a
Campaign Workspace, and where — today — the chain is broken. No code was changed to
produce this; it is a map of the current reality against the intended architecture.*

**Date:** 2026-07-02 · **Reads with:** `CONSTITUTION.md`, `campaign-workspace-prd.md`,
`../company-strategy.md` (the moat = proprietary intelligence + the buyer↔creator graph).

---

## 0. The thesis (and the finding)

**Thesis (correct, and load-bearing):** *Discovery Intelligence is the parent object of
every campaign.* Every downstream module — Proposal, Project, Campaign Workspace —
should **inherit and enrich** this object, never recreate its information. The Campaign
Workspace is the first **consumer** of Discovery Intelligence, not its first **creator.**

**Finding:** Today the chain does not hold. There is **no Discovery Intelligence object**;
the intelligence that should be one inherited spine is fragmented across **three
disconnected universes**, the project-creation step is a **lossy funnel** that keeps only
five scalar fields, and the Campaign Workspace's creative-direction cards are created
**empty and hand-filled** — so the workspace *is* currently the first creator of creative
direction, exactly the anti-pattern the thesis warns against. The richest sources (Agency
/ Company Intelligence, and the history of past campaigns for the same buyer) are
architecturally **unreachable** from the campaign, because a campaign references its
client only by a free-text **name**, not by a link to the intelligence record.

---

## 1. The three disconnected universes

The information that *should* compose one Discovery Intelligence object lives in three
places that do not reference each other:

| Universe | Where it lives | What it holds | Keyed by |
|---|---|---|---|
| **A. Opportunity** (demand) | `opportunities` table (+ `doc_overrides` JSON) | client **name**, need, description, buyer_type, music_requirement, budget, qualification cache (qualified/discipline/alignment/action/confidence/gaps), score/tier, strategic value, contact, and the proposal's `understanding`/`compose`/`relevant_links`/`relevant_uploads` | `id`; client is **TEXT** |
| **B. Agency / Company Intelligence** (buyer) | `agencies` table + `intel_json` (+ signals, decision_makers) | services, industries, offices, leadership, awards, portfolio, decision-makers, **music characteristics**, production style, signals | `agencies.id` |
| **C. Buyer graph** (relationship) | `buyer_intel.py` aggregates by client **name** + `companies` table | relationship stage, touch history, won deals, next-best-action | client **name** |

**The central break:** A ↔ B ↔ C are **not linked.** An opportunity's `client` is a text
string; there is **no `agency_id` foreign key** from an opportunity (or project, or
campaign) to the Agency Intelligence record. Universe B — the one that should populate
*brand history, agency notes, music characteristics, previous campaigns* — is unreachable
from the object that becomes a campaign. C is a third, name-keyed representation that also
doesn't join to B. So the single most valuable asset (the moat: the buyer's intelligence)
never reaches the surface that most needs it.

---

## 2. The lineage as it actually runs

```
  DISCOVERY CALL
     │  ✗ NOT CAPTURED as a structured object. CHORDENTIAL_DISCOVERY_CALL_URL is just a
     │    booking link. Emotional arc / references / agency notes said on the call have
     │    NO capture surface — at best they land in opp.notes or doc_overrides freeform.
     ▼
  OPPORTUNITY  (opportunities row)                      ┌─ doc_overrides (JSON on the OPP):
     client(name), need, description, buyer_type,       │    understanding, compose,
     music_requirement, budget, qual{discipline,        │    relevant_links, relevant_uploads,
     alignment,gaps,team_shape}, score, strategic       │    support_chips …
     value, contact …                                   └─ (partial "creative" data lives here,
     │  opp_id ───────────────────────────┐                 but ON THE OPPORTUNITY)
     ▼                                     │
  PROPOSAL  (build_capabilities_doc)       │  RENDER-ONLY: reads opp + qual + estimate +
     assembles a doc; new edits →          │  doc_overrides. Creates NO new persistent object;
     doc_overrides ON THE OPP              │  its additions live back in the opp's doc_overrides.
     │                                     │
     ▼                                     │
  PROJECT CREATION  (_ensure_project_for_opp → insert_project)
     KEEPS: opp_id, client(name), need, budget_min, budget_max, roles(=qual.team_shape)
     ✗ DROPS: description, discipline, alignment, gaps, buyer_type, music_requirement,
       contact, strategic value, doc_overrides (understanding/references/compose),
       and deadline (not passed → NULL).  Only opp_id survives as a pointer —
       and nothing downstream follows it to re-inherit the lost data.
     │
     ▼
  CAMPAIGN CREATION  (ensure_campaign_for_project)
     HYDRATES: title=project.need, brand=project.client, agency_client=project.client,
       budget, deadline, opp_id(via project)
     ✗ brand == agency_client (both = the client name string; no brand/agency entity)
     │
     ▼
  CAMPAIGN_DIRECTION  (the workspace's reason to exist)
     emotional_arc, reference_playlist, agency_notes, producer_notes,
     brand_history, previous_campaigns
     ✗ ALL created EMPTY. Hand-typed by the operator. None inherit from ANYTHING upstream.
```

Every `✗` is a break. The load-bearing ones are numbered in §4.

---

## 3. Field-by-field trace of the Campaign Workspace

For every field: **(1)** what object *should* populate it · **(2)** does that object exist ·
**(3)** is the data stored today · **(4)** is the field *mapped* (wired to flow) · **(5)**
if not, why not.

### Campaign header

| Field | (1) Should come from | (2) Exists? | (3) Stored? | (4) Mapped? | (5) Why not |
|---|---|---|---|---|---|
| `title` | Discovery Intel → opp.need | ✅ | ✅ | ✅ | — (hydrated from project.need) |
| `brand` | a **Brand** entity | ⚠️ only as opp.client **name** | name only | ⚠️ conflated | No brand/agency entity separation — `client` is one free-text string used as both brand *and* agency |
| `agency_client` | **Agency Intelligence** (agencies row) | ✅ (agencies table) | ✅ (intel exists) | ❌ | **No `agency_id` FK** from opp/project/campaign — the agency record is unreachable; the name is copied instead |
| `phase` | lifecycle / delivery state | ✅ (`delivery_json.state`) | ✅ | ✅ | — (weak: derived from delivery state) |
| `budget_min/max` | Estimate / opp budget | ✅ | ✅ | ✅ | — |
| `deadline` | Discovery Intel (call timeline) | ⚠️ | ⚠️ often NULL | ❌ | Opportunities have **no deadline column**; `insert_project` omits deadline → it's NULL unless typed later |
| `contracted_revisions` | Estimate / Proposal | ⚠️ (estimate has revision multipliers; `delivery_json.revisions_included` exists) | partial | ❌ | Revisions live in `delivery_json`, set by hand in delivery — never threaded from the estimate/proposal into the campaign |
| `opp_id` | the lineage pointer | ✅ | ✅ | ✅ | — (present, but **unused** downstream — nobody follows it to enrich) |

### Creative direction (the heart of the workspace)

| Field | (1) Should come from | (2) Exists? | (3) Stored? | (4) Mapped? | (5) Why not |
|---|---|---|---|---|---|
| `emotional_arc` | **Discovery Intelligence** (the call) | ❌ | ❌ | ❌ | The discovery call is **not captured** as a structured object anywhere — there is no field, table, or intake for the creative content of a call |
| `reference_playlist` | Discovery Intel + `doc_overrides.relevant_links`/`relevant_uploads` | ⚠️ partial (relevant_links exist **on the opp**) | ✅ (on the opp) | ❌ | The references live in `opportunities.doc_overrides`, are **never carried into the campaign**, and the "why chosen" rationale is not captured |
| `agency_notes` | **Agency Intelligence** + the call | ✅ (agency intel) / ❌ (call) | ✅ (intel) | ❌ | Agency intel unreachable (no FK); call not captured |
| `producer_notes` | workspace-origin (legitimate) — could seed from `opp.notes` | ✅ (opp.notes) | ✅ | ❌ | The one field that may legitimately *originate* here — but even the opp's existing notes don't seed it |
| `brand_history` | **Agency/Company Intelligence** (music characteristics, portfolio, production style) | ✅ (`agencies.intel_json`) | ✅ (when enriched) | ❌ | The exact data exists in Universe B but is **architecturally unreachable** (no agency link) and there is no enrichment step to pull it |
| `previous_campaigns` | Buyer graph / **past projects & won deals for this buyer** | ✅ (prior opps/projects/won_deals) | ✅ | ❌ | Never queried into the campaign; and matching would rely on the fragile client-**name** string, not a buyer entity |

**Summary of the table:** header fields mostly map (through the lossy funnel), but **every
creative-direction field is unmapped**, and the four that have a real upstream source
(`reference_playlist`, `agency_notes`, `brand_history`, `previous_campaigns`) are blocked
by two root causes: **the discovery call is never captured**, and **the client is a name,
not a linked intelligence entity.**

> The PRD's fuller workspace (cues, team, versions, stems, assets, activity) is not built
> yet; the **same lineage question applies to every future field** — e.g. the creative
> **team** should inherit `qual.team_shape` (which *does* flow to `project.roles`), so
> that one is already half-wired and is the model for how the rest should behave.

---

## 4. The breaks, in priority order

1. **No parent intelligence object (it doesn't exist).** There is no single record that
   unifies the demand facts, the buyer intelligence, and the call. Each downstream module
   re-derives or re-enters what it needs. *This is the root break; the others are its
   symptoms.* → **DESIGNED (2026-07-02):** the parent is **Campaign Intelligence**, spec'd
   in `CAMPAIGN_INTELLIGENCE.md` (schema/lifecycle/ownership/provenance); not yet built.
2. ~~**No agency link (`opp.client` is a name, not an `agency_id`).**~~ **✅ CLOSED
   (Step 1, 2026-07-02).** `agency_id` now threads Opportunity → Project → Campaign
   (additive columns + carry-through + a name-match source), so a campaign can *reach*
   the Agency/Company Intelligence record. The campaign home surfaces the link and
   whether intelligence is available to inherit. This is the thread only — the
   *inheritance* of `brand_history`/`agency_notes`/`previous_campaigns` from that record
   is the next step (the parent object + provenance model).
3. **The discovery call is not captured.** The single richest source of `emotional_arc`,
   references, and agency intent has no structured intake — it evaporates into freeform
   notes or nothing.
4. **Project creation is a lossy funnel.** `insert_project` keeps 5 scalars + `opp_id` and
   drops everything else; nothing follows `opp_id` back to re-inherit. The proposal's
   `doc_overrides` (understanding, references) never travel past the opportunity.
5. **The campaign recreates instead of inherits.** `campaign_direction` rows are created
   empty; hydration copies only `need`/`client`/`budget`/`deadline`. The workspace has no
   inheritance step at all.
6. **No brand/agency separation.** One free-text `client` is used as brand *and* agency —
   so an agency commissioning for a brand (the real case) can't be represented, and
   neither can be linked to intelligence.
7. **No provenance/source model.** Even where a field is filled, nothing records *where it
   came from* or *whether it's been reviewed* — which is exactly what the target
   provenance card (§6) needs.

---

## 5. The dependency map — target vs. broken

```
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │                         DISCOVERY INTELLIGENCE  (the parent — DOES NOT EXIST)   │
   │  one object per engagement, that every downstream module inherits & enriches:  │
   │   • demand facts        ← Opportunity + Qualification                          │
   │   • buyer intelligence  ← Agency/Company Intelligence  (needs agency link)      │
   │   • relationship        ← Buyer graph / past campaigns  (needs buyer entity)    │
   │   • the call            ← Discovery Call capture         (needs an intake)      │
   └───────────────┬──────────────────────────────────────────────────────────────┘
                   │ inherits (read) + enriches (write-back), with PROVENANCE per field
   DISCOVERY CALL ─┼─✗ (4) not captured
        ▼          │
   OPPORTUNITY ────┤   A. demand universe  (has the data; is the de-facto parent today)
        │  ✗ (2) no agency_id → B unreachable
        ▼          │
   PROPOSAL ───────┤   render-only; writes back to opp.doc_overrides (stays on the opp)
        │  ✗ (4) lossy funnel: keeps 5 fields + opp_id, drops the rest
        ▼          │
   PROJECT ────────┤   opp_id survives but is never followed to re-inherit
        │  ✗ (5) recreates, doesn't inherit
        ▼          │
   CAMPAIGN ───────┘   direction cards created EMPTY  ✗ (1)(3)(6)(7)
```

**Every arrow marked `✗` is a break.** The fix is to invert the flow: make Discovery
Intelligence a real object that the opportunity *is/points to*, give it the agency link
and a call-capture intake, and have each downstream module **read from it and write
enrichments back to it** — carrying provenance — instead of copying scalars forward and
losing the rest.

---

## 6. The target: an inherited object with per-field provenance

Every creative-direction card should render its **lineage**, not just its text — exactly
the model in the request:

```
 Emotional Arc
 ┌──────────────────────────────────────────┐
 │ "Warm nostalgia at open, building to a    │
 │  triumphant, communal release."           │
 │                                           │
 │ Source:                                   │
 │   ✓ Discovery Intelligence   (the call)   │
 │   ✓ Agency History           (intel_json) │
 │   ✓ AI Generated             (proposed)   │
 │                                           │
 │ Status:  ⟳ Needs Review                   │
 └──────────────────────────────────────────┘
```

This requires three things that do not exist yet:

1. **A Discovery Intelligence record** (the parent) that unifies A + B + C + the call, so
   each field *has* a source to cite. Realistically: elevate the opportunity into (or link
   it 1:1 to) a `discovery_intelligence` object, add the **`agency_id` link**, and add a
   **discovery-call capture** intake (structured fields for emotional arc, references,
   agency intent).
2. **A per-field provenance model** — each direction field stores `{value, sources[],
   status}` where `sources ∈ {discovery_intelligence, agency_history, ai_generated,
   producer}` and `status ∈ {inherited, needs_review, confirmed}`. (Today
   `campaign_direction` stores only `body` + a boolean `complete` — no sources, no
   review state.)
3. **An inheritance + enrichment step at campaign creation** — instead of empty cards, the
   campaign *reads* Discovery Intelligence to pre-fill each field, tags each with its
   source(s) and `needs_review`, and lets AI *propose* (never decide — Constitution §4.1)
   the rest. The operator reviews and confirms; confirmations enrich the parent, so the
   next campaign for that buyer starts smarter (the moat compounds).

**Constitutional fit:** this is the constitution's own principle made literal — *"one
source of truth per fact"* (§10), *the data flywheel is the moat* (§6), *machine proposes
/ human disposes* (the provenance `Needs Review` status is the disposition gate), and
*evidence-first* (every field cites its source). The provenance card is not a UI flourish;
it is the visible proof that the workspace **inherited** rather than **recreated.**

---

## 7. Recommended sequence to close the chain (no code here — the order of the fix)

1. **Link the buyer.** Add `agency_id` to the opportunity (and carry it → project →
   campaign). This alone unstrands `brand_history` / `agency_notes` / `previous_campaigns`.
   *Highest leverage, unblocks the moat.*
2. **Name the parent.** Define the Discovery Intelligence object (elevate/point-to the
   opportunity) as the thing the proposal, project, and campaign all read from and write
   back to — stop copying scalars forward.
3. **Capture the call.** Add a structured discovery-call intake (emotional arc, references,
   agency intent) so `emotional_arc` and `reference_playlist` have a real source.
4. **Inherit at creation.** Make `ensure_campaign_for_project` (and the direction model)
   pre-fill each card from Discovery Intelligence with `sources` + `needs_review`, instead
   of empty rows. Carry `doc_overrides.relevant_links` into `reference_playlist`.
5. **Add provenance + AI proposals.** Extend `campaign_direction` to `{value, sources[],
   status}`; let the AI employees (Feedback Analyst / A&R / Documentarian) *propose*
   values tagged `ai_generated, needs_review`. Confirmations write back to the parent.

Until step 1 lands, the Campaign Workspace will keep being the first *creator* of what it
should *inherit*. The workspace built in increment 1 is correct as a **surface**; this
trace defines the **spine** it must be plugged into next.
