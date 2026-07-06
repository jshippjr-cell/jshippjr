# Build scope — Production-Readiness panel ("Campaign Readiness")

Turn the STUDIO LIGHT *Campaign Readiness* mock into a live product surface: a
deterministic readiness engine + a proof-forward panel (the arc diagram + the
readiness ledger + the one ember decision), computed from data the app already
holds. This is the council's Decision #1 — *make production-readiness visible as
proof* — shipped.

**Positioning it serves:** *Chordential is the operating system where creative
campaigns become production-ready.* This panel is that sentence, rendered from real
state — the single clearest expression of the promise inside the product.

---

## 1. Architecture — a pure engine + a partial

Mirror the existing deterministic "engines" pattern (no LLM, `delivery.py`-style):

**`src/chordential_oia/readiness.py`** — a pure function:

```
readiness_view(project, estimate, delivery, assignments) -> ReadinessView
```

`ReadinessView` = `{ checks: [Check], cleared: int, total: int, pct: int,
arc: [Stage], decision: Decision | None }`.

`Check` = `{ id, label, status, provenance, kind }` where
`status ∈ {cleared, locked, in_scope, pending, attested, n_a}` and `provenance` is
the short mono record line (e.g. `cleared · worldwide · certificate on file`).

No new heavy schema. It reads `projects.delivery_json` (+ the estimate the delivery
console already loads). One optional small key is added for attestations (below) via
the existing `update_delivery` merge-one-key helper — no migration.

**Deterministic + honest:** every check is derived from real fields; nothing is
inferred or guessed. Unprovable claims are *operator-attested*, never auto-asserted.

---

## 2. Check catalog — each mapped to a real source

| # | Check | Data source (already exists) | Auto? | Cleared when |
|---|-------|------------------------------|-------|--------------|
| 1 | Creative direction locked | version ladder ≥ `v2 Direction-lock` (`delivery.versions`) / `brief` present | auto | version 2+ reached |
| 2 | Composition final | latest version state `FINAL` or `released_at` set | auto | v3 FINAL / released |
| 3 | Revisions within scope | `delivery.revision_status()` `{scoped, used, remaining}` | auto | `remaining ≥ 0` (used ≤ scoped) |
| 4 | Rights &amp; clearance | `delivery_json['license_confirmed']` `{by, date}` | auto | confirmed present |
| 5 | Deliverables assembled | `build_manifest()` coverage vs `delivery.assets` | auto | every manifest line matched |
| 6 | Versioning locked | deterministic `version_name()` on the versions | auto | ≥1 version, named |
| 7 | Cue sheet generated | `build_cue_sheet()` rows non-empty | auto | rows exist |
| 8 | Sample-free &amp; original | **not tracked** → operator attestation | attested | operator ticks it |
| 9 | Final approval (release) | `delivery_json['released_at']` | **the decision** | released |

**Honesty guardrails (binding):**
- A check is `cleared`/`locked` **only** when its real field says so — otherwise
  `pending`. Never render a green mark the data can't back (the seal-fraud rule from
  the council).
- Check 8 (sample-free) has no field, so it is **attested**, visibly labelled
  "attested by operator," stored as `delivery_json['attest_original'] = {by, date}`.
  It never shows as machine-proven. If un-ticked, it reads `pending`, not cleared.
- `pct` counts only *provable* checks; attestations are shown but flagged so the
  score can't be gamed by ticking a box.

---

## 3. The arc (the signature diagram)

Stages map to real milestones, one node `live` at the current frontier:

`Brief → Direction → Composition → Variation → Cleared → Approve → Delivered`

Derived from: intake exists · version ≥ v2 · version FINAL · `revisions_used` ·
`license_confirmed` · `released_at`. The first not-yet-done stage is the `live`
(ember) node; everything left is solid, everything right is dashed/future. Exactly
one ember, and it's always the human's next move.

---

## 4. The one decision (ember)

The pending human disposition is **Release** — it already exists as the delivery
console's release action (`released_at`). The panel surfaces it as the single ember
CTA ("Approve &amp; release →"), enabled only when every *auto* check is cleared.
Reuses the existing route; no new write path. This is "machine proposes, human
disposes," made literal.

---

## 5. UI surfaces (proof at equal weight — Decision #1)

- **Primary — Delivery console** (`delivery_console.html`): the full panel at the
  top — readiness summary (`8 / 9`), the arc, the ledger, the ember release. Styled
  in STUDIO LIGHT (warm cards, mono provenance, wine bar, one ember).
- **Compact — Project + Opportunity headers:** a small **readiness pill**
  (`● 8/9 ready`) linking to the console — proof visible before you drill in.
- **Client-facing (later, optional):** a trimmed, reassuring readiness strip on the
  delivery portal ("cleared · versioned · certified") — proof for the buyer. Gated
  to a later increment; internal proof lands first.

Dual type throughout: serif for the human statements, mono for every record.

---

## 6. Increments (each shippable, suite green)

- **I1 — Engine + tests.** `readiness.py` pure function + `test_readiness.py`
  (each check's cleared/pending logic, the pct honesty rule, arc frontier, attest
  handling). No UI. ~½ day.
- **I2 — Delivery-console panel.** Wire `readiness_view` into the console route +
  the STUDIO LIGHT partial (summary + arc + ledger + ember release). Dogfood on the
  seeded delivered/in-progress projects. ~1 day.
- **I3 — Compact readiness pill** on project + opportunity headers. ~½ day.
- **I4 — Attestation control** for check 8 (tick → `attest_original`), operator-only.
  ~¼ day.
- **I5 (optional, later) — client-facing readiness strip** on the delivery portal.

---

## 7. Non-goals / guardrails

- No new tables, no migration (reads `delivery_json`; one optional merged key).
- No LLM — fully deterministic, testable, offline.
- Never auto-assert an unprovable check; attestations are labelled and score-neutral.
- One ember per surface (the release); the readiness bar is wine, statuses are
  semantic green/amber — the voltage stays reserved.
- Reuses the existing release action; introduces no second "deliver" path.

## 8. Verification

- `test_readiness.py` green + full suite green.
- Dogfood: the seeded Northwind (delivered) project reads `9/9 · delivered`; an
  in-progress project reads the correct partial with the right live arc node.
- Spot-check honesty: a project with no `license_confirmed` must show Rights as
  `pending`, never cleared.
