# The Client Workspace — product principles, conflict review, and build sequence

Ratified by operator directive 2026-07-07 (the "ten principles"). Binding decisions live
in ADR-0018; this doc holds the north star, the honest gap analysis against today's code,
and the foundation-first sequence. ChordOS is **the operating system for the entire
lifecycle of a commercial music engagement** — not proposal, CRM, PM, or procurement
software. One client. One workspace. One URL that never changes. The relationship compounds.

## The ten principles (verbatim intent)

1. **One Client Workspace** — the permanent home for every client; not the Opportunity,
   Project, or a PDF. The URL never changes; contents evolve by phase.
2. **Approval drives state** — the client's commitment moves the campaign forward. Manual
   controls remain as fallbacks. The machine prepares; the human commits.
3. **Kickoff stage** — between Commercial Approval and Production. Approval = "we want to
   work with you"; Kickoff = "here's how we'll work together" (contacts, cadence,
   revision/delivery expectations, team, escalation).
4. **Campaign Intelligence → Relationship Intelligence** — CI never dies with a campaign;
   every campaign makes the client profile smarter (creative prefs, comms style, revision
   habits, budget history, decision makers, approval timelines, procurement, rights, music
   prefs, feedback tendencies). Future campaigns begin with accumulated knowledge.
5. **Procurement is adaptive** — discover how each org buys (PO / vendor portal / Coupa /
   Ariba / Oracle / ACH / W-9 / COI / procurement contact); generate the artifacts. Adapt
   to procurement; do not integrate into it unless a compelling business reason emerges.
6. **The PDF is no longer the product** — the workspace is; the PDF is a download rendered
   from Campaign Intelligence. No duplicate sources of truth.
7. **Commercial Review** — separates the commercial conversation from the creative. Brief:
   "what are we making." Review: "what are we agreeing to" (scope, deliverables, timeline,
   pricing, deposit, payment schedule, producer-voiced terms, procurement checklist,
   approval). Approval is the primary award trigger.
8. **Terms feel premium** — not legal boilerplate; producer-voiced, generated dynamically
   from scope/deliverables/timeline/rights/revision policy/payment schedule.
9. **Commitment levels** — electronic approval in the workspace is the default (name,
   email, timestamp, IP, user-agent, approved scope/pricing/terms = the audit record).
   DocuSign is optional, only when procurement requires it.
10. **North star** — one workspace link; everything happens there; it grows more valuable
    every week; nothing resets, moves, or gets recreated; the URL never changes.

## Where today's code conflicts with the vision

| # | Principle | Current state | Conflict | Fix phase |
|---|-----------|---------------|----------|-----------|
| 1,10 | One durable URL | Brief on opp `share_token`; delivery portal on a *separate* project `share_token`. URL changes at award. | The single biggest break. | **P0** (this pass) |
| 2 | Approval drives state | Award = operator presses "Create project". | Causality inverted. | P3 |
| 3 | Kickoff stage | Does not exist. | Missing phase. | P0 defines it in the phase enum; P4 builds it. |
| 4 | Relationship Intelligence | CI is per-opportunity/campaign; agency intelligence exists but CI doesn't roll up to a durable client profile across campaigns. | CI dies with the campaign. | Later ADR; P0 builds the token layer so per-client promotion is not a rewrite. |
| 5 | Adaptive procurement | Not built. | Missing. | P5 (capture as CI commercial facts + generate artifacts). |
| 6 | PDF demoted | Brief centers on `window.print()`. | PDF is primary. | P1 makes the workspace canonical; PDF → download. |
| 7 | Commercial Review | A "commercial picture" section was placed *inside* the Brief (interim). | Commercial not separated from creative. | P1 moves it out into the Review. |
| 8 | Premium terms | `proposals.build_proposal().terms` is a flat generic list. | Boilerplate, not scope-tailored/producer-voiced. | P2. |
| 9 | Commitment + audit | No approval/commitment/audit exists; DocuSign is a deferred placeholder. | Missing layer. | P3 (levels 1–2 + audit anchored to snapshot); DocuSign behind a seam. |

## Refactors to do now to prevent rework

- **Durable workspace token** — the opportunity mints it; the project **inherits the same
  token** at creation (never mints a fresh one). One token spans the lifecycle.
- **Phase engine** — one pure, tested function is the single answer to "where is this deal"
  (`intro → discovery → brief → commercial → kickoff → production → delivery → archive`).
  Every later feature is a *view* of a phase, not a new destination.
- **`/workspace/{token}` canonical entry** — resolves the deal, computes phase, renders the
  workspace shell. Existing token-gated routes keep working during migration; they become
  views folded under the workspace in later phases.
- **Token resolution designed for a per-client future** — lookup is written so promoting the
  anchor from opportunity to client (Principle 4) is an additive change, not a rewrite.

## Foundation-first build sequence (each phase independently shippable, all read CI)

- **P0 — Workspace foundation (this pass):** durable token (project inherits opp token),
  the phase engine, `/workspace/{token}` shell routing by phase, tests. No behavior removed.
- **P1 — Commercial Review:** a CI-generated Review view in the workspace (scope, pricing,
  deposit, payment schedule, timeline, deliverables); retire the interim commercial section
  in the Brief. PDF demoted to download.
- **P2 — Producer-voiced Terms engine:** scope/CI-tailored clause library, rendered into the
  Review and frozen into approval snapshots.
- **P3 — Commitment + audit:** levels 1 (proceed) & 2 (electronic approval) with the
  snapshot-anchored audit record; approval becomes the award trigger → Kickoff. Level 3
  (DocuSign) behind a null-default seam.
- **P4 — Kickoff phase:** the working-relationship setup between approval and production.
- **P5 — Procurement (adaptive) + Delivery unification:** capture how the org buys as CI
  commercial facts, generate the artifacts + checklist; fold the production/delivery portal
  under the same workspace URL.
- **Later ADR — Relationship Intelligence:** promote CI's durable anchor from opportunity to
  client so many campaigns share one workspace and accumulated knowledge.
