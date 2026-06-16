# Chordential — Qualification Layer Spec

*Owner: Head of Music Production. Board simulation; required objections
documented. Authored against CEO Decision #6 (2026-06-16): **Qualification
Accuracy is the #1 objective, ahead of Estimation Accuracy.***

> Strategy-altitude spec (the "#1 then #2" path). This document is the contract
> the build implements next. No code here — but every section names the data
> shape and threshold the engine will need.

---

## 1. Why Qualification is its own layer (not part of Rank)

The shipped engine (`src/chordential_oia/scoring.py`) answers **"how attractive
and winnable is this opportunity?"** — a 0–100 opportunity score and an A/B/C/Watch
tier. That is **Rank**. It assumes the thing is already music work.

It does **not** answer the Head of Production's question: **"Is this real,
original, *Chordential-shaped* music craft at all — and how well does it fit what
we actually do?"** Today nothing hard-rejects a cover band, a karaoke host, a DJ,
a "needs a playlist" request, or a wedding act. Those can still draw a non-trivial
opportunity score from commercial/budget signals. **That is the #1 false-positive
risk, and it erodes trust in every score downstream.**

So Qualification is a **separate stage that runs before Rank is trusted**:

```
Ingest → QUALIFY (gate + classify + align) → Rank (order the qualified) → Estimate → Prepare
            └── hard disqualify ──→ Drop / Watch (full recall retained in DB)
```

- **Qualify** decides *whether* and *how well* something fits, and **can hard-reject**.
- **Rank** decides *priority order among things that already passed qualification*.

The two scores are different and both appear in the CEO's target output:

> *"This RFP is **87% aligned** with Chordential's capabilities. Estimated budget
> $5k–$10k. Requires composer, mixer, and music editor. **Moderate competition.
> Recommended pursuit.**"*

**87% aligned** = the Qualification **alignment score** (this spec).
**Recommended pursuit / moderate competition** = the Rank **tier + opportunity
score** (existing engine). Estimate band = the hybrid estimator (separate spec).

---

## 2. Output contract — `QualificationResult`

Every ingested opportunity produces exactly one of these. This is the interface
the build (#2) implements and that alerts, the review queue, and the moat-capture
log all read from.

| Field | Type | Meaning |
|---|---|---|
| `qualified` | bool | Passed the hard gate (Stage 0). `False` ⇒ disqualified. |
| `discipline` | enum | Primary music discipline (Stage 1), or `NON_CRAFT`. |
| `alignment_pct` | 0–100 | How well it fits Chordential's capabilities (Stage 2). |
| `fit_summary` | str | One human sentence — the "87% aligned…" line. |
| `fit_reasons` | list[str] | Why it fits (positive qualification signals). |
| `disqualifiers` | list[str] | Hard-fail reasons, if any. |
| `gaps` | list[str] | What's missing/uncertain (drives review + questions to ask). |
| `confidence` | High/Med/Low | How much was explicit vs inferred from text. |
| `needs_human_review` | bool | True when confidence is low or signals conflict. |
| `recommended_action` | Pursue / Review / Pass / Watch | The routing decision. |

`recommended_action` is what the COO workflow and the alert gate consume.

---

## 3. Stage 0 — Hard disqualifiers (the junk gate)

A **binary, deterministic, cheap** gate. If any disqualifier fires with high
confidence, short-circuit to `qualified = False`, `recommended_action = Pass`,
and **store the record anyway** (full recall — it may inform future signal). No
LLM spend on obvious junk.

**Hard NO (not Chordential-shaped craft):**
- Cover band / tribute act / wedding or party band
- Karaoke host / sing-along service
- DJ booking / playlist curation / "needs a playlist" / "make me a Spotify list"
- Music lessons / teaching / tutoring
- Pure live-performance booking with **no creation** (gig with no composition)
- Gear / instrument / equipment sale or rental
- Already-finished music that only needs distribution or a publishing admin
- Pure cover/re-recording of an existing song with no original work

**Soft flag (not auto-fail, but caps alignment and forces review):**
- Licensing-only / pre-existing sync with no original component
- Music buried as <10% of a much larger non-music contract
- No describable deliverable ("looking for music people", vague)

These mostly correspond to `MusicRequirement.NONE` plus a junk-keyword set the
build will own (mirroring the existing keyword-fallback pattern in `scoring.py`,
but as **exclusion** lists). Deterministic first; LLM only adjudicates genuine
ambiguity (Stage 2 escalation), never the obvious cases.

---

## 4. Stage 1 — Music-discipline classification

What *kind* of craft is this? Drives both alignment weighting and the team the
estimator will later assemble.

| Discipline | Fit | Notes |
|---|---|---|
| **Original composition / scoring** | Core | The bullseye. Film/TV/ad/trailer/branded original music. |
| **Sonic branding / audio identity** | Core (high value) | Mnemonics, sound logos — proprietary, sticky work. |
| **Sound design** | Core | Often bundled with composition; real craft. |
| **Arrangement / orchestration** | Core-adjacent | Real craft; usually a component, not the whole job. |
| **Music supervision / sync placement** | Adjacent | Lower margin, relationship value; qualify but weight down. |
| **Licensing-only (pre-existing)** | Weak | Soft-flag; alignment capped — not original craft. |
| **Non-craft** | Disqualify | Routed out by Stage 0. |

A single opportunity may carry more than one discipline (e.g. composition +
sound design); record the **primary** plus any secondary tags.

---

## 5. Stage 2 — The qualification rubric (scored)

The Head of Production's five gate questions become five scored dimensions.
Each yields a 0.0–1.0 signal + a human-readable note (same shape as the existing
`Scorer` contract, so it slots into the codebase cleanly). The weighted sum is
the **alignment score (0–100)**.

| # | Dimension | Question | Weight | What scores high |
|---|---|---|---|---|
| 1 | **Real brief** | Is there a concrete creative deliverable? | 25 | Described spot/scene/format, duration, intent — not "need music guy" |
| 2 | **Craft fit** | Original / Chordential-shaped craft? | 30 | Original composition / sonic branding / sound design (Stage 1 core) |
| 3 | **Budget signal** | Is there money, and does it clear the floor? | 20 | Disclosed or strongly inferable budget ≥ A-tier floor ($5k) |
| 4 | **Clearable** | Are the rights/licensing realistic? | 15 | Clean original work; no impossible third-party clearances or master rights |
| 5 | **On-craft buyer** | Buyer type consistent with real music spend? | 10 | Agency / brand / production company with creative intent |

**Weighting rationale (Head of Production):** Craft fit (30) outweighs budget (20)
on purpose. Per CEO Decision #6, we optimize qualification accuracy first — a
perfectly-budgeted job that isn't real craft is a **false positive**, which is the
exact failure mode we are protecting against. Money without craft is not our work.

**Alignment score** = Σ(weight × normalized) → the "87% aligned" number.
Weights are **versioned, editable config** (like `config/weights.*.json`), so the
Head of Production can retune the gate without a code change.

---

## 6. Fit explanation — the human sentence

`fit_summary` is generated, not hand-written, and is the qualification layer's
headline output. Template (deterministic skeleton; LLM may polish prose only when
a record reaches the review queue, to control cost):

> *"{alignment_pct}% aligned — {primary_discipline} for a {buyer_type}.
> {budget_phrase}. {craft_phrase}. {top_gap_or_strength}. → {recommended_action}."*

The point (CEO directive): **explaining *why* it's a fit is itself the value**,
independent of estimation precision. `fit_reasons` and `gaps` give the human the
evidence to confirm or override in one glance.

---

## 7. Confidence & human-in-the-loop (earning trust)

The classifier does **not** get to alert on its own authority until it has earned
trust. `confidence` is **High** when the deciding signals were explicit in the
source, **Low** when they were inferred from free text or signals conflict.

- **Low confidence or conflicting signals ⇒ `needs_human_review = True`** →
  routed to the review queue, never auto-alerted.
- Every **human confirm or override is captured as a labeled training example**
  (see §9). Until the classifier's agreement-with-human rate clears a bar the
  Head of Production sets, **human confirm is required before any A-tier alert** —
  exactly the "human confirm until the classifier earns trust" rule from the board
  record.

---

## 8. Precision-biased alert gate (implements CEO Decision #3)

`recommended_action` routing — precision-biased by construction:

| Condition | Action | Alert? |
|---|---|---|
| `qualified` ∧ `alignment_pct ≥ ALERT_FLOOR` ∧ (`confidence=High` ∨ human-confirmed) | **Pursue** | **Yes — real-time A-tier alert** |
| `qualified` ∧ alignment in review band, or `needs_human_review` | **Review** | No — review queue / digest |
| `qualified` ∧ low alignment | **Watch** | No — DB only, full recall retained |
| `¬qualified` | **Pass** | No — stored for recall, never alerted |

`ALERT_FLOOR` starts conservative (high precision) and is tuned **down** only as
the human-agreement rate proves the classifier. We would rather miss a borderline
lead (it still sits in Watch/Review with full recall) than fire a false A-tier
alert and burn trust. **Recall is never destroyed — it is retained in the DB; only
*alerting* is precision-gated.** (This answers the RFP Intelligence objection:
early-development signals are kept, just not alerted.)

---

## 9. Moat capture (implements CEO Decision #1)

This layer is **data manufacturing**, not just filtering. Mandatory writes:

- Every `QualificationResult` is persisted with its **inputs and rubric version**.
- Every **human confirm/override** is stored as a **labeled qualification example**
  (`predicted` vs `corrected`), with the reason. This labeled set is the
  proprietary asset that lets qualification accuracy compound over time — the same
  way Phase 3 actuals improve the estimator.
- Track **agreement rate** (classifier vs human) per discipline and buyer type;
  it is the metric that governs when alerts can run unattended (§7).

---

## 10. Required objections (board sim)

- **CTO:** the hard gate (Stage 0) and the five scorers (Stage 2) must be
  **deterministic and cheap** — they run on *every* ingested opportunity. Reserve
  LLM calls for (a) genuinely ambiguous classification and (b) prose polish on
  review-queue items only. **No full-LLM qualification on all ~2,000 opps/mo.**
- **CFO:** agreed and stronger — under the lean/not-raising constraint, per-opp
  qualification cost must stay near-zero. If a record is obvious junk (Stage 0),
  it must cost a keyword scan, not a token. Gate every LLM dollar behind ambiguity.
- **RFP Intelligence:** precision-biased *alerting* is fine **only because recall
  is preserved in the DB**. Do not let the gate delete or hide early-stage signals;
  they must remain queryable in Watch.
- **Founder's Advocate:** §9 is non-negotiable. If we filter without capturing the
  human-label deltas, we built a junk filter, not a moat. The labels are the asset.
- **Estimation Agent:** discipline + team hints from Stage 1 are my hand-off inputs
  — qualification must emit the **team shape** (composer/mixer/editor/…) so I can
  produce the budget band without re-deriving it.

---

## 11. Build hand-off (what #2 implements)

1. `QualificationResult` model (§2) alongside the existing `ScoredOpportunity`.
2. Stage 0 disqualifier gate — exclusion keyword sets + `MusicRequirement.NONE`,
   deterministic, short-circuiting.
3. Stage 1 discipline classifier — explicit-field-first, text-fallback (mirrors
   the resolver pattern already in `scoring.py`).
4. Stage 2 rubric — five `Scorer`-shaped functions + versioned weights config →
   `alignment_pct`.
5. `fit_summary` generator (deterministic skeleton).
6. Confidence + `needs_human_review` logic and the review-queue routing.
7. Alert gate (§8) with a configurable `ALERT_FLOOR`.
8. Moat-capture log (§9): persist results, capture human overrides as labels.
9. Wire qualification **before** Rank in the pipeline; Rank orders the qualified set.

**Acceptance bar (per Decision #6):** qualification correctly **disqualifies the
junk list (§3)** and produces a defensible `fit_summary` for genuine craft work —
*before* we invest further in estimation precision.
