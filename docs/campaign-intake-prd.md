# Campaign Intake — PRD & UX Specification

*How everything learned about an engagement enters ChordOS with the least possible work
from the user. Campaign Intake is the front door; it produces and enriches the canonical
**Campaign Intelligence** object (`docs/architecture/CAMPAIGN_INTELLIGENCE.md`) — but the
user never thinks about that object. They just tell ChordOS **what happened.***

**Status:** PRD / UX spec (no code) · **Date:** 2026-07-02 · **Reads with:**
`docs/architecture/CAMPAIGN_INTELLIGENCE.md` (the object this creates), `CONSTITUTION.md`,
`campaign-workspace-prd.md`.

---

## 0. The vocabulary decision (and a naming recommendation)

You proposed renaming "Discovery Capture" → "Campaign Intake." **Adopt it — but layer the
vocabulary in three, and never leak the bottom layer to the user:**

| Layer | Name | Who sees it | What it is |
|---|---|---|---|
| **The action** | **Capture** ("+ Capture" · *"What happened?"*) | the **user** | a verb — tell ChordOS what happened |
| **The module** | **Campaign Intake** | us (docs, nav, settings) | the front door + the ingestion/extraction pipeline |
| **The object** | **Campaign Intelligence** | the **system** only | the canonical, provenance-tracked record it produces |

The user experiences a *verb* ("Capture"), not a module and never an object. "Intake" is the
right module word — it's the front door — and it stays honest even for engagements that never
become campaigns (they're intake that didn't convert). *"Discovery" was too narrow: it implies
a call, but half the entry points (RFP, email, opportunity) aren't calls.*

---

## 1. Three challenges to the framing (you asked me to)

I was told to optimize for the best OS for campaign music, not to implement the idea as
drawn. Three places I'd push:

### Challenge 1 — The best capture is *no capture.* Optimize for passive ingestion first.
The "pull out my phone, tap Capture, record a voice memo" flow is excellent — **as the
fallback.** The *lowest-work* capture is the one the user never performs because the Fathom /
Fireflies / Zoom transcript **already flowed into ChordOS on its own.** So the module's
primary investment should be **passive ingestion** (transcript integrations + an email-forward
address + calendar awareness), with the beautiful manual capture as the graceful fallback for
when there's no integration or the user wants to add color in the moment. *Design the ambient
inbox first; the tap-and-talk second.* (This reframes "Discovery Capture" from a screen you go
to into an inbox that comes to you.)

### Challenge 2 — Intake is not a workflow step. It's a universal front door + an ambient inbox.
A discovery call isn't a fixed point between "opportunity" and "proposal." Discovery happens
at many moments: a cold meeting that *becomes* a lead, a known opportunity, a follow-up call, a
relationship lunch, an RFP that arrives by email with no call at all. So Capture must be
reachable **everywhere** — the global "+", a specific opportunity, mobile in-the-moment — and
**arrive on its own** via integrations. The system decides where the capture belongs; the user
never navigates to a "capture step." *Don't bury it in the pipeline; make it omnipresent.*

### Challenge 3 — Campaign Intelligence is born at *first capture of any modality*, not "the
discovery call" — and there are **two records, not one.**
"Born at the discovery call" is too narrow (RFP-only and email-only engagements have no call)
and slightly wrong in shape. The cleaner model:

- A **Capture** is an **immutable evidence record** — one per input (this transcript, this RFP,
  this voice memo). It holds the raw source + the AI's extraction of it.
- **Campaign Intelligence** is the **living synthesis** — one per engagement — enriched by one
  *or many* captures (call + RFP + a follow-up email all feed the same CI).

So CI is born at the *first* capture of *any* modality (or auto-seeded from an existing
opportunity), and each CI field cites the capture(s) it came from. This gives **source
attribution for free**, keeps captures as tamper-proof evidence, and models the real world
(engagements are learned in pieces, over time). *One capture ≠ one CI; captures are evidence,
CI is the synthesis.*

**Net:** the module you described is right; I'd make it (a) integration-first, (b) omnipresent
rather than a step, and (c) built on a Capture-vs-Intelligence split. The rest of this spec
assumes those three.

---

## 2. Design principles

1. **The user tells ChordOS what happened. Full stop.** No form, no field names, no "which
   agency is this." The system infers, and asks only what it truly can't.
2. **Least work is the whole game.** Rank every design choice by *seconds of user effort.*
   Passive ingest (0s) > forward an email (5s) > tap + talk (90s) > paste notes (2m) >
   answer a form (∞, banned).
3. **Capture is instant; understanding is async.** Recording ends the moment the user is done.
   Extraction happens in the background; ChordOS pings them when it's ready to review — often
   by the time they've reached their car.
4. **Ask only material gaps, and never block.** A follow-up is asked *only* when the next step
   (the proposal) actually needs it. Questions are deferrable; CI exists immediately at
   whatever confidence.
5. **Every fact cites its evidence.** Extracted values quote the source span (evidence-first,
   Constitution §7). Nothing is asserted the system can't point at.
6. **Capture flows into value, not into "saved."** Intake ends on *"here's your drafted
   proposal / your workspace,"* never *"Campaign Intelligence created."*
7. **Honest about what it doesn't know.** A thin transcript yields "I didn't get much from
   this — want to add a note?", not fake confidence.

---

## 2bis. Two capture stances — *"What happened?"* and *"What's your read?"*

Campaign Intake supports **two fundamentally different kinds of capture**, and keeping them
distinct is an architectural decision, not a UX nicety:

| Stance | **Objective capture** | **Producer Debrief** |
|---|---|---|
| The question | *"What happened?"* | *"What's your read?"* |
| Modalities | transcript · notes · RFP · email · voice recap of the meeting | voice (usually) · typed |
| What it captures | the **facts** of the meeting — what was said, asked, agreed | the **human layer** — interpretation, intuition, risks, observations, what to recommend, what's still unclear |
| Where it comes from | the meeting/document itself | the producer's judgment, which is **not in the transcript** |
| Produces (kinds) | mostly **`fact`** | mostly **`insight`**, **`recommendation`**, **`open_question`** (`CAMPAIGN_INTELLIGENCE.md` §4bis) |
| Provenance source | `transcript` / `rfp` / `email` / `notes` | **`producer_debrief`** (attributed to the human, dated) |

**Why this is a first-class distinction, not just another modality:** a transcript tells you
*they said they want "warm."* Only the producer knows *"warm" means nostalgic-not-saccharine,
the CD is the real approver even though the producer ran the call, and I'm worried the brand
team hasn't weighed in.* That interpretive layer — the most valuable, least-recorded knowledge
in a creative-service business — is **structurally absent from the meeting** and would be lost
forever without a place to put it. The Producer Debrief is that place, and Campaign
Intelligence preserves it **labeled as interpretation**, never laundered into fact.

**The Debrief is a companion, not a replacement.** The ideal engagement has both: the
objective capture (the Fathom transcript → facts) **and** a 30-second debrief (the producer's
read → insights/recommendations/questions), feeding the *same* Campaign Intelligence,
distinguished by `kind`. A debrief can also stand alone (a relationship lunch with no formal
transcript), and it can be added anytime — right after the meeting, or a day later when a
worry crystallizes.

**How the Debrief behaves differently in the pipeline:**
- **Prompt.** Not "what happened" but *"What's your read?"* — with gentle, skippable sub-nudges
  the AI offers only if the debrief is thin: *what stood out · what worries you · what would you
  recommend · what's still unclear.* Never a form; a producer thinking out loud for 30 seconds.
- **Extraction classifies by kind.** The AI tags each extracted item `insight` /
  `recommendation` / `open_question` and flags risks `is_concern`. A debrief is subjective *by
  design* — if the producer asserts something as fact, it's captured and attributed to them,
  but it does **not** get objective-fact confidence or displace a source-quoted fact
  (honesty: inference stays labeled as inference).
- **No follow-up interrogation.** The Debrief never triggers the "you're missing 4 fields"
  questioning — that gate is about *facts the proposal needs*. A debrief is a gift of judgment,
  not a checklist; the system takes whatever the producer offers.
- **It surfaces differently downstream.** Insights are *shown* beside the facts they interpret;
  recommendations become *choices* the operator accepts/defers; open questions + risks are
  *flagged* (they can even seed follow-ups on the objective side).

---

## 3. User journey (the four archetypes)

**A. Mobile, in-the-moment (the hero flow).** Jon leaves an agency, opens ChordOS on his
phone, taps **+ Capture → 🎙 Record voice debrief**, talks for 90 seconds ("Just met Halcyon
about the holiday spot, they want something warm and nostalgic, budget's around eighteen to
twenty-four, need it by early November, two rounds…"), taps done. He drives home. Ten minutes
later: a push — *"Halcyon holiday spot — I understood 83%. 4 quick things when you have a
sec."* He taps, answers four one-tap/one-line questions from the couch. Done. A CI exists, a
proposal is drafted.

**B. Desktop, passive (the ideal).** Jon's Fathom auto-syncs the Halcyon call transcript to
ChordOS. He never captured anything. He gets a notification: *"New call captured — Halcyon
holiday spot. Review?"* The CI is already drafted from the transcript; he reviews the gaps.

**C. RFP arrives (no call).** An agency emails an RFP. Jon forwards it to
`intake@chordential.com` (or drags the PDF into Capture). The AI extracts budget/deliverables/
timeline (RFPs are structured) and drafts a CI — often at high confidence, few gaps.

**D. On a known opportunity (enrichment).** Jon's already tracking a Halcyon opp. From the
opportunity he taps **Capture** to add the call he just had; the system *enriches the existing
CI* rather than creating a duplicate, pre-loaded with what the opp already knows so he adds
only what's new.

---

## 4. Screen flow

```
  ┌────────────────────────────────────────────────────────────────────────┐
  │  Everywhere: global "+", an opportunity, mobile, OR it just arrives      │
  │  (integration / forwarded email) — no navigation to a "capture step."    │
  └───────────────┬────────────────────────────────────────────────────────┘
                  ▼
  ①  ONE QUESTION:  "What happened?"           (skipped entirely for passive ingest)
       📄 Upload transcript   📋 Paste notes   📎 Upload RFP   📧 Import email thread
       🎙 Voice recap                        ← objective ("what happened")
       ── or ──
       ◈ Producer Debrief  ("What's your read?")  ← interpretive (§2bis) — pairs with any above
                  ▼
  ②  CAPTURE  (modality-specific, seconds)  → "Got it. I'll listen and come back to you."
                  ▼   (async — the user is free to leave)
  ③  UNDERSTAND  (background AI: ingest → extract → gap-analyze)
                  ▼
  ④  REVIEW  ("I understood 83%.  Confirmed 12 things.  4 quick questions:")
       • confident facts, collapsed (glance, bulk-confirm)
       • the material gaps, asked conversationally, one at a time, deferrable
       • any conflict/low-confidence, flagged for a look
                  ▼
  ⑤  FLOW INTO VALUE:  "Draft the proposal →"  /  "Open the workspace →"
       (CI already exists; this is the next action, not the end)
```

The user's *required* path is ①→②. Everything after is async and optional-to-defer. A passive
capture starts at ③ and pings the user at ④.

---

## 5. UX detail

- **The entry is a verb, not a form.** A single sheet: *"What happened?"* + five big modality
  tiles. No agency picker, no project picker, no fields. (On an opportunity, the same sheet,
  pre-scoped to that engagement.)
- **Capture is modality-native and fast:**
  - 🎙 *Record* — a big record button + a live waveform; tap to stop. Works offline (uploads
    when back online). This is the hero; make it one-tap from the home screen.
  - 📄 *Transcript* / 📋 *Notes* — a paste box or file drop; zero formatting required.
  - 📎 *RFP* — drag a PDF/DOCX; a thumbnail confirms.
  - 📧 *Email* — paste, or (better) *"forward to intake@…"* shown as the zero-work path.
- **"I'll come back to you."** After capture, the user is released immediately with a friendly
  ack and a background job. No spinner they must watch.
- **Review is a glance, not an audit.** The review screen leads with the **understanding %**
  and *what's confirmed* (collapsed: "12 things I understood ✓ — tap to see"), then spends the
  user's attention only on **the gaps and the conflicts.** Confident facts are bulk-confirmable
  with one tap ("Looks right").
- **Questions look like a chat, not a CRM.** Each follow-up is a single bubble with the
  easiest possible answer affordance (a few tap-chips for budget bands, a date picker for
  timeline, a one-line field for a name), and a **"skip / answer later."**
- **Evidence is one tap away.** Every extracted fact has a small "why" that reveals the quote
  it came from ("Budget $18–24k — *'somewhere between eighteen and twenty-four for music'*").
- **Mobile-first, desktop-equal.** The hero flow is designed for a phone in a parking lot;
  the desktop version is the same flow with bigger targets.

---

## 6. AI workflow

The pipeline is **shared across every modality** — the front door differs, the brain doesn't.

```
 INGEST      any modality → normalized text + context
   voice → transcribe · file → OCR/parse · email → thread reconstruct · opp → seed context
      ▼
 RESOLVE     which engagement is this?  (create new CI vs. enrich existing — §7)
      ▼
 EXTRACT     map text → CI field candidates {facet, key, value, evidence_span, confidence}
      ▼
 GAP-ANALYZE compare filled fields vs. the REQUIRED set for the next step (the proposal)
      ▼
 QUESTION    generate follow-ups ONLY for material gaps (§6 logic) — minimal, ordered
      ▼
 WRITE       upsert CI fields (source = the capture; status = proposed/needs_review) + log
      ▼
 PRESENT     understanding % + confirmed facts + the gaps + conflicts → review (§10)
```

**Constitutional guardrails (non-negotiable):** the AI **extracts, structures, and asks — it
never decides.** It writes `proposed`/`needs_review` fields only; the operator confirms
(§4.1). It never invents a value it can't quote (evidence-first). It never fabricates buyer
facts. It is a targeted, cacheable step, cost-gated (ADR-0005) — one pass per capture, not a
live agent loop.

---

## 7. Conversation model

- **Turn 1 is the user's monologue** (the recording / paste / upload). The AI listens fully
  before it speaks — it does not interrupt to ask clarifying questions mid-capture.
- **The AI's first reply is a status, not an interrogation:** *"I understood 83%. Confirmed
  12 things. Four quick questions when you have a sec."* — it leads with what it *got*, so the
  user feels heard and ahead, not quizzed.
- **One question per turn**, easiest-answer-first, each independently answerable and skippable.
  The tone is a sharp junior producer, not a form: *"What's the budget for music?"* with tap-
  chips *($5–10k · $10–20k · $20k+ · not discussed)*.
- **It accepts answers in any modality** — a tapped chip, a typed line, or *another* voice
  memo ("actually it's closer to thirty, and the deadline moved to October"). A follow-up
  answer is itself a mini-capture that re-enters EXTRACT.
- **It stops as soon as the material gaps are closed** — it never keeps asking to "complete the
  record." Non-material fields stay empty and honest.
- **It's resumable and ambient.** Unanswered questions live as a gentle to-do on the CI; the
  user can answer them now, later, or never. Nothing blocks.

---

## 8. Follow-up questioning logic

The discipline that keeps this from becoming a 30-field form in disguise:

1. **Ask only what the NEXT step needs.** The gate is the proposal's required inputs, not
   "everything about the engagement." The default required set: **budget band · timeline ·
   deliverables · decision-maker** (exactly your four), plus **primary discipline** and
   **agency identity** *only if unresolved.*
2. **Ask only real gaps.** A field that was extracted with high confidence is *not* asked —
   even if it's "required" — it's just shown for confirmation. A question is generated only
   when a required field is **missing or low-confidence.**
3. **Rank by leverage, ask the highest first,** and **cap the set** (target ≤ 4; hard stop at
   ~6). If more than ~6 are missing, that's a signal the capture was thin — offer *"want to add
   a quick note?"* instead of a barrage.
4. **Prefer the cheapest answer affordance** (chips > picker > one-line > open text) and always
   offer **defer.**
5. **Never re-ask a deferred question unprompted** within a session; surface it later as a soft
   nudge on the CI ("2 open questions") tied to the moment it matters (e.g. when Jon opens the
   proposal).
6. **A conflicting fact is a question, not a silent overwrite** (ties to the CI `conflicted`
   status): *"The RFP says $15k but on the call you heard $20k — which should I use?"*

---

## 9. Campaign Intelligence creation (the system side, kept invisible)

The user does nothing here; the system does all of it, silently:

- **Resolve create-vs-enrich.** From the capture's content + context, the system decides
  whether this belongs to an **existing** engagement (enrich its CI) or is **new** (create a
  CI). Signals: an explicit opportunity context (captured *from* an opp → that CI); a strong
  agency + brand + recency match to an open CI → propose enrich ("Looks like the Halcyon
  holiday spot — add to it?"); otherwise create new. *When ambiguous, it asks one question;
  it never silently merges or forks.*
- **Create/seed the CI** (`CAMPAIGN_INTELLIGENCE.md` §5.1): link the opportunity + resolve the
  agency (Step 1's matcher), then write extracted facts as CI fields.
- **Write via the provenance model.** Each extracted fact → a `campaign_intelligence_field`
  with `source = <capture>`, `status = proposed`/`needs_review`, `confidence`, and a pointer to
  the capture's evidence span. Confirmed answers → `confirmed`. Buyer facets are snapshotted
  from the linked agency; direction facets come from the capture; engagement facets from the
  opp/qualification.
- **Immutable captures.** The raw capture + its extraction are stored once and never mutated;
  re-processing creates a new extraction version, so the evidence trail is intact.
- **The user sees none of this.** They see "understood 83%," four questions, and "draft the
  proposal." The words *Campaign Intelligence* never appear in the UI.

---

## 10. Confidence scoring

- **Per-field confidence** comes from the extraction (how directly the value was stated +
  source reliability: an RFP's explicit "$18,000" scores higher than a hedged aside on a noisy
  transcript). Stored on the CI field.
- **Overall "understanding %"** = a *weighted* coverage of the **required set**, not a count of
  all fields. Budget / timeline / deliverables / decision-maker carry most of the weight
  (because the proposal needs them); nice-to-haves barely move it. So "83%" means *"I have most
  of what I need to move you forward,"* not "83% of all possible fields." This is the honest,
  useful number — and it's what decides whether follow-ups are even asked.
- **Thresholds tune behavior:** high-confidence required fields → shown for one-tap confirm;
  low/missing → a question; a value below a floor → treated as absent. Tunable, not hardcoded.
- **Source reliability weighting** feeds confidence (RFP > transcript > voice memo > pasted
  fragment for *structured* facts like budget; the reverse can hold for *creative* nuance,
  where a voice debrief beats a dry RFP).

---

## 11. Source attribution

- **The capture modality is the `source`** in the provenance model (`transcript`, `voice`,
  `rfp`, `email`, `notes`, `opportunity`, `operator`, `ai`). A CI field supported by several
  captures lists several sources — the card's ✓ list.
- **Every fact points at its evidence.** A CI field stores which capture + which span/quote it
  came from, so review and the provenance card can show *"Budget $18–24k — from the transcript:
  '…eighteen to twenty-four for music…'."* This is the honesty rule made visible and the reason
  a user can trust the extraction without re-reading the transcript.
- **Attribution survives forever** (immutable captures + append-only CI event log), so months
  later "why does the record say the deadline is November?" is answerable to the exact sentence.

---

## 12. Review & confirmation workflow

The moment the user's judgment is actually needed — kept as light as possible:

- **Lead with the win, not the work:** understanding %, then *"Confirmed 12 things"* collapsed.
  The user can glance, trust, and move on.
- **Spend attention only on gaps + conflicts.** The four questions, one at a time, cheap
  answers, deferrable. Conflicts shown as a pick-one.
- **Bulk-confirm the confident.** One "Looks right" flips the high-confidence `needs_review`
  fields to `confirmed`; spot-edit any that's wrong (which corrects the field + logs it).
- **Confirmation is the human disposition gate** (Constitution §4.1): nothing the AI extracted
  is `confirmed` until a human says so — but the CI is fully usable *before* confirmation
  (proposal can draft from `needs_review` values, clearly marked).
- **It ends on the next action, not on "saved":** *"Draft the proposal →"* or *"Open the
  workspace →."* Capture that doesn't flow into value is a dead-end the module refuses to be.
- **Confirmed buyer/outcome facts enrich upward** — they can be pushed back to Agency
  Intelligence + the buyer graph (the flywheel), so tomorrow's capture for this buyer starts
  smarter.

---

## 13. Entry points & modalities (ranked by user effort)

| Modality | Stance | Enters via | AI handling | User effort | Priority |
|---|---|---|---|---|---|
| **Transcript integration** (Fathom/Fireflies/Zoom/Meet) | objective | passive auto-sync | transcribe→extract facts | **0s** | ★ build first |
| **Email / RFP forward** | objective | `intake@…` address | thread/PDF parse→extract facts | ~5s | ★ build first |
| **Existing Opportunity** | objective (seed) | seed, not a capture | pre-load known facts | ~0s | ★ (already have the data) |
| **🎙 Producer Debrief** | **interpretive** | mobile/desktop record | transcribe→classify **insight/rec/question** | ~30s | ★ the differentiator |
| **Voice recap** | objective | mobile record | transcribe→extract facts | ~90s | ★ hero fallback |
| **Paste notes** | objective | paste box | extract facts | ~1–2m | ✓ |
| **Upload transcript/recording** | objective | file drop | transcribe/parse→extract facts | ~15s | ✓ |
| **Manual RFP/email upload** | objective | file/paste | parse→extract facts | ~15s | ✓ |

The **Producer Debrief** is the one modality no competitor thinks to build — it captures the
producer's judgment, which is *why* ChordOS accumulates intelligence a transcript tool never
can. Objective capture answers *what happened*; the Debrief answers *what it means*.

**The strategic point:** the top three are *near-zero effort* and cover the majority of real
discovery. Investing in **integrations + email-forward + opportunity-seed first** delivers the
"least work" north star far more than polishing the manual screens. The voice debrief is the
beloved fallback for the parking-lot moment — build it, but don't mistake it for the primary.

---

## 14. Where Campaign Intake lives in the product

Not a pipeline step — an **omnipresent front door + an ambient inbox:**
- **Global "+ Capture"** in the top bar / mobile home — capture anything, anytime; the system
  routes it.
- **On an opportunity** — "Capture" enriches *that* engagement's CI.
- **Ambient inbox** — integrations + the forward address deposit captures that appear as
  *"New captures to review"* — the user is pulled to review, not pushed to create.
- **Mobile home = the record button.** The hero flow is one tap from launch.

---

## 15. Constitutional alignment

- **§4.1 machine proposes, human disposes** — the AI extracts + asks; confirmation is the
  human gate; CI fields sit `needs_review` until a person confirms.
- **§7 evidence-first / honesty** — every fact quotes its source; empty stays empty; thin
  captures are admitted, not faked.
- **§6 the moat flywheel** — confirmed facts enrich Agency Intelligence + the buyer graph; the
  capture corpus itself becomes proprietary training data over time.
- **§10 one source of truth** — captures are evidence; Campaign Intelligence is the single
  synthesis; the user never creates a competing record.
- **Least-work = the product thesis** — "remove the work of managing music" starts at the very
  first minute after the meeting.

---

## 16. Open decisions for Jon (before build)

1. **Integrations vs. manual, first.** *Rec: ship the manual voice/paste/RFP capture as the MVP
   (self-contained, no third-party deps), then the transcript integrations + email-forward — but
   design the pipeline integration-first so manual is just one source among many.*
2. **The required set that gates follow-ups.** *Rec: budget · timeline · deliverables ·
   decision-maker (your four) + discipline + agency-identity-if-unresolved. Tunable.*
3. **Auto-confirm threshold.** Should very-high-confidence required fields auto-confirm, or
   always wait for a human tap? *Rec: never auto-confirm (§4.1) — but make bulk-confirm one tap.*
4. **Create-vs-enrich when ambiguous.** *Rec: ask one question ("add to the Halcyon holiday
   spot, or start fresh?") — never silently merge or fork.*
5. **Voice/transcription provider.** A real dependency + cost. *Rec: a provider seam (ADR-0004),
   null/manual-paste default, real transcription behind an env flag — consistent with every
   other outward integration.*

---

## 17. Build sequence (once approved)

1. **The Capture record + the shared pipeline** (ingest→extract→gap→question→write), with
   **paste-notes** as the first modality (zero deps) writing to Campaign Intelligence.
2. **Voice debrief** (record + transcription seam) — the hero fallback.
3. **RFP + email** parsing; the **`intake@` forward** address.
4. **The review UX** (understanding % + confirm + conversational gaps) — the disposition gate.
5. **Transcript integrations** (Fathom/Fireflies/Zoom) — the passive ideal.
6. **Opportunity-seed + create-vs-enrich resolution**, and **flow-into-value** (draft proposal /
   open workspace).

Each ships behind the workspace/intake flag, dogfood-first, and every step writes through the
Campaign Intelligence provenance model — so the UI can evolve dramatically without ever
changing the underlying object. *That separation is the architecture's whole point.*

---

*This is a design, not a commitment to code. It specifies the experience (Campaign Intake) and
its contract with the domain object (Campaign Intelligence) so the two can be built and evolved
independently. The user tells ChordOS what happened; ChordOS does the rest.*

---

## 18. Revision (2026-07-03) — Campaign Intake is anchored to the Opportunity (ADR-0013)

The first build shipped Campaign Intake inside the **Campaign Workspace**, which exists only
*after* an opportunity is Won. That is too late: the discovery call, the RFP, and the
qualification conversation — where the richest, most-refined intel is gathered — all happen
**while pursuing the opportunity.** So Campaign Intake becomes a **first-class component of
every Opportunity**, and the lifecycle is explicit:

```
Lead → Opportunity → Campaign Intake → Campaign Intelligence (continuously updated)
     → Proposal → Won → Project → Campaign Workspace (inherits the same CI)
```

### 18.1 Where it lives
The **"Update Intelligence"** panel sits at the top of the Opportunity page — **above the
Opportunity section and the tabs.** One prominent panel, always available while qualifying.

### 18.2 Input methods (one panel, many modalities)
- Paste discovery notes · Paste meeting transcript · Upload/record a voice memo (Producer
  Debrief) · Upload an RFP · Paste an email thread.
- Two **stances** stay orthogonal to modality: *objective* ("what happened?" → facts) and
  *Producer Debrief* ("what's your read?" → insight / recommendation / open_question / risk).
- Voice + binary uploads use a **transcription/extraction seam** (ADR-0004, null-by-default):
  text modalities work with zero deps today; audio is stored as evidence and marked *awaiting
  transcription* until a provider is configured — never faked.

### 18.3 Analyze = read-new, merge, preserve, never-clobber
When the operator presses **Analyze**, the pipeline:
1. reads **only the newly submitted** capture,
2. **merges** it into the existing CI through the one provenance API (§9),
3. **preserves provenance** for every touched field (sources[] append, event logged),
4. **never overwrites a confirmed human edit** — a machine value that disagrees with a
   human-owned field lands as a **proposed** value and is **surfaced as a conflict** to resolve,
5. **generates follow-up questions** for any still-missing required fact.

### 18.4 Everything editable; human edits are authoritative
Every CI field is inline-editable — plus the **title** and **buyer name** (which write to the
Opportunity's own `need`/`client`). A human edit **becomes the authoritative value**, is
marked human-owned, appends `operator` to the field's provenance, and is logged in the event
history — so nothing is lost and the machine can never silently overwrite it afterward. The
canonical editable set: Campaign Objective · Business Objective · Budget · Timeline ·
Deliverables · Decision Makers · Emotional Arc · Reference Playlist · Brand Notes · Agency
Notes · Producer Debrief · Risks · Recommendations · Open Questions (extensible).

### 18.5 Downstream refresh (the Opportunity is the source of truth)
Because the existing engines read from the **Opportunity's own columns**, confirmed
engagement facts (budget → `budget_min/max`, timeline → `deadline`, discipline → `discipline`)
**write back to the opportunity** on ingest/edit. Qualification score, buyer profile,
opportunity summary, proposal draft, pursuit brief, and outreach recommendations therefore
recompute from the same source on next render — **no separate "refresh" and no divergent
copy.** The Opportunity becomes the single working source of truth across the sales process.

### 18.6 Won → inherit, never recreate
Marking the Opportunity **Won** creates the Project and Campaign Workspace, which **adopt the
existing CI in place** (`ensure_for_campaign` resolves the opp's CI and sets its
`campaign_id`/`project_id`; it never creates a second CI). Nothing is re-entered after
conversion.

---

## 19. Revision (2026-07-03) — Intake becomes a multi-lane framework; the meeting is the source

The primary source of Campaign Intelligence is the **client meeting**, not typed notes. Intake
is re-architected as an **extensible framework of intake lanes** (discovery-call scheduling,
paste notes, paste transcript, producer debrief, RFP, email thread, client brief, and future
Meet/Teams/Slack/CRM) — **none primary** — all normalizing to one Capture envelope and one
shared pipeline into the single CI object. The hero lane schedules a Zoom call, invites a
recording bot, ties the meeting to the Opportunity before it starts, and **auto-ingests the
transcript** when it ends; the user just reviews the proposed changes. Full architecture, UX,
integrations, event flow, and data model: **`docs/discovery-call-intake-design.md`** (proposes
ADR-0014). Design only — not yet built.
