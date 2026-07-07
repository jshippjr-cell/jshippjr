# Campaign Intelligence as Single Source of Truth — trace, gaps, fixes

Operator directive (2026-07-07): "We are no longer designing isolated pages. Every artifact
should inherit from Campaign Intelligence. There should only be one source of truth."
Binding rule: ADR-0017. This doc records the trace that motivated it and the fix plan.

## The trace (what was actually happening)

**Discovery Call → CI** (works): meeting capture → `meetings_service.poll_and_ingest` →
Campaign Intake lanes → `campaign_intelligence.contribute` with provenance. CI is real and
confirmed on the Opportunity page.

**CI → Campaign Brief** (broken): `capabilities.build_capabilities_doc()` (capabilities.py)
never reads CI. Zero references. Sections come from: opportunity columns (`client`, `need`),
qualification/estimation engines (team, price band), hardcoded constants (`VALUE_PROP`,
`DELIVERY_TEMPLATES`, `_RIGHTS_SUMMARY`, rollout), and the `doc_overrides` JSON blob.
`business_objective`, `campaign_objective`, `emotional_arc`, `deliverables`, `deadline`,
`budget_band`, `decision_makers`, `brand_notes`, `agency_notes`, `reference_playlist`, risks
(`is_concern`), and open questions — all present in CI's canonical catalog — were never
consulted.

**Brief Edit → Apply** (broken): every edit route (`doc_field`, `doc_chip`, `doc_link`,
`doc_pill`) writes only `opportunities.doc_overrides`. Nothing writes CI. Blank value =
override deleted (db.update_doc_override) = next render falls back to **stock template
copy** — the "everything reverts to template defaults" bug.

**Email This** (broken): the compose flow sends a plain-text email with a token **link to the
live brief route**, which rebuilds the doc from scratch at open time. No snapshot exists.
"PDF" is `window.print()` on the live page. What the client opens is whatever the template
produces later, not what the operator approved.

**Scheduling** (incomplete): operator picks ONE hand-typed time; no multi-option proposal, no
client slot-pick page, no lock/expire, no timeline event. Confirmation emails format times as
hard-coded UTC (`meeting_scheduler._fmt`). The availability engine exists but nothing calls
it. Manual path exists (`/opportunity/{id}/schedule` with no `req`) but hides once a meeting
exists.

## The fixes (implemented in this pass)

1. **Meeting proposals** — new `meeting_proposals` table (slots_json ≤3, client identity,
   token, status draft→sent→booked/expired). Operator picks up to three ET times in the
   Schedule drawer → ChordOS composes the client email → operator reviews and presses Send
   (machine proposes, Jon disposes) → client opens `/meet/{token}`, sees the options in
   Eastern time, picks one → transactional lock: chosen slot books through the existing
   `meeting_scheduler.schedule` engine (Zoom create, Recall attach, Google calendar invites
   both sides, confirmations), remaining options expire, CI timeline event recorded. The
   same drawer runs from the "Create discovery call" button on every Opportunity — brief or
   no brief — and the button no longer disappears once a meeting exists.
2. **Eastern time everywhere client-facing** — `fmt_et()` renders `Tuesday · July 14 ·
   10:00 AM EDT` (correct summer/winter label via zoneinfo America/New_York). UTC remains
   storage. `_fmt` fixed. Future: per-client timezone detection.
3. **Brief renders CI** — `build_capabilities_doc` takes a `ci` view; every section prefers
   confirmed CI slot-by-slot (objective, emotional arc, creative direction, deliverables,
   timeline, budget, decision makers, brand/agency notes, reference playlist, risks, open
   questions), engines/templates only as fallback for empty slots. Meeting-summary tone:
   the brief opens "After meeting with your team…" when a discovery meeting exists.
4. **Edit writes CI** — CI-backed brief fields save through
   `campaign_intelligence.edit_or_create`; the brief re-renders from updated intelligence.
   `doc_overrides` keeps only presentation concerns. Blanking reverts to CI-derived
   content, never stock copy.
5. **Email This sends the document you are looking at** — sending freezes a
   `brief_snapshots` row (full doc JSON); the mailed link renders the snapshot verbatim.
   Preview, PDF, and sent doc share the snapshot.
6. **Commercial close** — the brief ends with a commercial summary (pricing, scope,
   deliverables, terms, timeline, revisions, deposit, estimated completion) built from the
   estimation/proposal engines + CI budget — part of the proposal, not a separate document.

## Still open (honest gaps)

- Qualification / Buyer Profile / Opportunity Score reading CI directly (they still read
  opportunity columns; CI write-back covers shared fields like budget).
- Client-timezone auto-detection (ET default shipped).
- Availability-engine-sourced slot suggestions in the drawer (operator types times; the
  conflict check is wired, suggestions are not).
