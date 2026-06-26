# Chordential Delivery OS — Plan

*The supply/delivery counterpart to the demand-side mission spine. Five agents that
own the lifecycle **from creative brief to final delivery**, surfaced **in one place**.
Drafted 2026-06-26; pending founder ratification.*

---

## North star

> Build the **workflow, trust, documentation, and delivery system** that makes working
> with Chordential feel **fundamentally easier than working with anyone else.**

This is not a feature set — it's the **experience moat**, and it's the same wedge the
deep research (`market-research.md`) and the market-entry health check identified: the
thing AI and music libraries structurally **cannot** offer is *human-authored,
defensible, fully-documented, cleanly-delivered* music. **These five agents are the
operational form of the "Clearance-Certified" product.** Building them is not a detour
from going to market — it *is* the product going to market, and the first beautiful
delivery is the **proof of concept** the founder needs.

---

## What an "agent" means here

Consistent with Chordential's existing engines (`qualification.py`, `estimation.py`,
`outreach.py`) and the governing rule — *the machine proposes, Jon disposes* — each
**agent is a deterministic functional owner** of one category: it assembles and tracks
its domain, generates the documents, flags what's missing, and presents a recommended
state; **Jon confirms the human calls** (sign-off, release). They are modules + data +
a console surface, not autonomous black boxes. (AI assists later where it earns its
keep — e.g. drafting metadata — never as the source of truth.)

---

## What exists today (we extend, not reinvent)

- **Projects** (`projects`: opp_id, client, need, budget, deadline, status, roles),
  **crew assignments** (role → talent → rate), **per-role milestones** with progress.
- **Proposals + invoices + Stripe** (money in) and **per-talent rates → proposal math**.
- A **static delivery package** (`public/delivery_sample.html`) — manifest, music asset
  map, version tree, **rights & ownership certificate**, stem inventory, rollout map,
  **final approval certificate** — i.e. the *design* of a procurement-grade delivery.
- A **partially personalized** delivery outline in the combined client doc
  (`capabilities.py`: `Deliverable`, `rights_summary`, `rollout`).

**The gap:** all of the above is presentation. There is **no live system** that tracks
rights/chain-of-title per deliverable, manages revision rounds, generates real
metadata/cue sheets, runs an approvals workflow, or holds the actual asset files. That
live system is the Delivery OS.

---

## The five agents

Each section: **owns · inputs → outputs · the trust it creates · builds on**.

### 1. Rights Agent — *the clearance guarantee* (the differentiator)
- **Owns:** chain of title and the legal defensibility that AI/libraries can't match.
  Per project/deliverable: contributor splits, **original-work warranty**, the **license
  grant** (full buyout / cross-channel / **paid-spend-safe** / territory / term /
  exclusivity), **Content-ID safelist** status, and the **indemnification** clause.
- **Inputs → outputs:** the brief + assigned creators → the **Clearance Certificate**
  (the research's wedge), cue-sheet-ready rights data, the signed-warranty record.
- **Trust:** *"music your legal team can defend."* This is the agent that makes the
  whole product sellable.
- **Builds on:** the rights-certificate section of the delivery package + `rights_summary`.

### 2. Revisions Agent — *scope clarity, no surprises*
- **Owns:** the revision lifecycle. Rounds **scoped vs. used** (from the estimate's
  revision multiplier), structured feedback intake, and the **version states** (v1
  concept → v2 direction-lock → v3 FINAL).
- **Inputs → outputs:** the proposal's revision cap + client feedback → a live **version
  tree**, current state, and **rounds remaining** (enforced, so scope creep is visible
  before it's a fight).
- **Trust:** the client always knows where things stand and what's included — and the
  studio protects its margin without an awkward conversation.
- **Builds on:** the estimator's revision rounds + the version-tree design.

### 3. Metadata Agent — *procurement-grade documentation*
- **Owns:** the paperwork that makes delivery legible and *gets the client their backend
  money*. Generates **cue sheets** (research: *"no cue sheet, no backend"* PRO royalties),
  **asset manifests**, file naming/specs, stem inventories, ISRC/ISWC where relevant.
- **Inputs → outputs:** the project + deliverables + rights data → cue sheet, manifest,
  naming-convention doc — auto-generated, not hand-built.
- **Trust:** the client receives a package an agency's traffic/legal team can file
  without chasing. (This is research **Idea 4** — metadata-as-a-service — applied to our
  own deliveries first, sellable to other studios later.)
- **Builds on:** the manifest + cue-sheet + stem-inventory designs in the delivery sample.

### 4. Approvals Agent — *clean, accountable sign-off*
- **Owns:** the approval workflow. Routes each deliverable/version for client review,
  tracks **approval state per asset**, captures the **Final Approval Certificate** and a
  locked-version marker.
- **Inputs → outputs:** delivered versions → approval status, sign-off record, "released"
  flag (which gates final-invoice + asset handoff).
- **Trust:** no ambiguity about what's approved; a clean paper trail both sides can point
  to. **Natural home for e-signature (DocuSign)** when that phase lands.
- **Builds on:** the final-approval-certificate design; the deferred DocuSign work.

### 5. Campaign Assets Manager — *everything, in one place*
- **Owns:** the actual deliverable **files** — masters, cutdowns, social verticals,
  stems, sonic logo, docs — with the folder/naming structure, versioning, and a
  **client-facing delivery portal** ("here's exactly what you bought, organized").
- **Inputs → outputs:** uploaded/produced assets → the organized, versioned **delivery
  package** + a shareable, token-gated client **delivery page** (reuse the first-touch
  page pattern).
- **Trust:** the hand-off feels effortless and premium — the opposite of a Dropbox link
  dump.
- **Builds on:** the asset-map/manifest design; the audio upload + token-gated page we
  already built. **Needs durable object storage (S3/R2)** — the persistence gap we
  already flagged.

---

## "In one place" — the Delivery Console

One screen per won project (`/project/{id}/delivery`) showing all five agents' live
state at a glance, plus the generated, on-brand **Clearance-Certified delivery package**:

```
  PROJECT · {client} — {need}                         status: In production ▸ Delivered
  ───────────────────────────────────────────────────────────────────────────
  ⚖  Rights        Chain of title ✓  · License: buyout/paid-spend ✓ · Content-ID: pending
  ↻  Revisions     Round 2 of 3 · state: Direction-lock → awaiting v3
  🗂  Metadata      Cue sheet ✓ · Manifest ✓ · Stems 9/9 · Naming ✓
  ✓  Approvals     :60 master APPROVED · :30 cutdown awaiting client sign-off
  🎧  Assets        18 files · v3 · [Open client delivery portal ↗]
  ───────────────────────────────────────────────────────────────────────────
  [ Generate Clearance-Certified delivery package ]   [ Mark released ]
```

This is the operational twin of the demand-side dashboard: the machine assembles every
category; Jon presses the human buttons (approve, release).

---

## Cross-cutting decisions

- **Storage:** the Assets agent needs **durable object storage (S3/R2)** — local disk
  won't survive the Render disk removal. This is the one genuinely new piece of infra.
- **Pattern:** deterministic engines + human-in-the-loop, matching the codebase. No AI is
  the source of truth; AI can *draft* metadata/feedback summaries later.
- **It productizes the pivot:** a project that flows through these five agents *is* a
  Clearance-Certified delivery — and the first one, done end-to-end, is the **case-study
  / proof-of-concept** the company is missing.

---

## Phased build plan

**Phase 0 — Thin vertical slice → the proof of concept (highest priority).**
Don't build all five deep first. Build a *thin* path that touches all five just enough
to produce **one real, beautiful, fully-documented Clearance-Certified delivery** for a
single project — because that delivery *is* the founder's missing PoC and case study.
Scope: minimal rights cert + auto cue sheet/manifest + a simple approval flag + a
token-gated client delivery page with the assets. Ship the experience end-to-end once.

**Phase 1 — Rights Agent (deep).** The certificate, license terms, Content-ID safelist
tracking, indemnification — the differentiator, made real and safe to sell.

**Phase 2 — Metadata Agent (deep).** Real cue-sheet + manifest generation from project
data; the documentation that distinguishes "procurement-grade."

**Phase 3 — Assets Manager + storage.** Object storage (S3/R2), versioned asset repo,
the polished client delivery portal.

**Phase 4 — Revisions Agent.** Round tracking, version states, feedback intake, cap
enforcement.

**Phase 5 — Approvals Agent + the unified Delivery Console.** Sign-off workflow, the
one-screen console; wire e-signature (DocuSign) here when authorized.

**Reconcile into `product-roadmap.md` Track 2** as the delivery spine, and note that —
unlike the recruiting build — this is *demand-aligned*: it's the thing the buyer pays
for, not pre-staffing.

---

## Open questions for the founder (before we build)

1. **Order:** start with the **Phase-0 thin slice** (fastest path to a real delivered
   package + your PoC), or build the **Rights Agent deep first** (the differentiator,
   but no end-to-end delivery to show for a while)? *(Recommend: Phase-0 slice.)*
2. **The clearance guarantee:** are you ready to stand behind **indemnification** on
   original work (the heart of the Rights Agent), or do we scope to "documented &
   original, indemnity later"?
3. **Storage:** OK to set up **S3/R2** now (needed for real asset delivery), or keep it
   local/manual for the first PoC and add durable storage in Phase 3?
4. **DocuSign:** include real e-signature in the Approvals agent, or keep approvals as
   tracked sign-off (a logged "approved by ___ on ___") for now and add e-sign later?
5. **Scope of "agent":** confirm these are **deterministic modules + console** (the house
   pattern), not autonomous AI agents — i.e. Jon presses the release buttons.
