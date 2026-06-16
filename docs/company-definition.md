# Chordential — Company Definition Round

*Board simulation. Founder/CEO: Jon Shipp (final decision-maker). One full round
on six questions. Agents are required to disagree; objections are documented;
consensus is not required. Grounded in the ratified decisions in
`company-strategy.md` (A→B→C, lean/not-raising, precision-biased alerts, gated
proposals, hybrid estimation, qualification-first).*

Date: 2026-06-16.

> **Reading note.** Because GTM is A→B→C, several answers below are **staged**:
> what's true while Chordential's own studio is the only "customer" (A) differs
> from the SaaS (B) and marketplace (C) phases. Where it matters, each section
> says *Phase A / B / C* explicitly.

---

## 1. Ideal Customer Profile (ICP)

### Positions

**CMO (lead):** ICP is staged.
- **Phase A — the first customer is Chordential itself.** The studio is the user;
  the product's job is to raise *our* win rate on $2.5k–$15k commercial/branded
  music jobs. Every A-phase feature is judged on that.
- **Phase B — the paying ICP** is the *under-tooled creative shop that loses
  winnable work because it finds out too late or can't respond fast*:
  - **Primary:** boutique & mid-size music/production studios (2–25 people) doing
    commercial, branded-content, and advertising music.
  - **Secondary:** independent composers/arrangers with steady commercial flow;
    music supervisors; agency producers who source music.
  - **Firmographics:** US-first, Southeast/Miami home advantage; $250k–$5M revenue;
    already winning *some* commercial work (so they feel the loss of the rest).
  - **Trigger to buy:** "we missed a job we'd have won" / "we can't quote fast
    enough" / "we don't know what to charge."
- **Phase C — the higher-WTP buyer** is the **demand side**: agency/brand
  producers and content teams who will pay to *source vetted music partners
  quickly* (buyer-side procurement).

**Head of Production:** the ICP is defined as much by **who it is NOT**. Negative
ICP: cover/wedding bands, karaoke/DJ services, music teachers, pure performers,
hobbyists, and anyone wanting a playlist. If we let those in we drown the product
in junk (see the qualification gate). The buyer must have **real, recurring,
original-craft music spend.**

**CRO:** the sharpest paying ICP is the shop where **one won deal pays for a year
of the product**. At Studio pricing (~$299–499/mo) against a single $5k–$15k won
job, the ROI math closes on the first save. That shop — not the solo hobbyist — is
where retention lives.

### Objections
- **CFO:** solo composers ($49–99/mo) are low-WTP and high-support; treat them as
  a funnel/brand surface, **not** the revenue base. Don't over-build for them.
- **Founder's Advocate:** the *real* ICP that builds the moat is the **buyer side
  (C)**. A/B are the means; do not let "sell to small studios forever" become the
  ceiling. Keep buyer-side discovery running from day one.
- **RFP Intelligence:** ICP should be expressed as *opportunity* fit too —
  geographies/verticals where we have signal density (healthcare, automotive,
  tech, hospitality ads). ICP isn't only the buyer; it's the buyer **× the lanes
  we can actually source.**

### Synthesis
**ICP = under-tooled commercial-music shops (Phase B primary) that have real
original-craft spend and lose winnable work to speed — with Chordential's own
studio as customer-zero (Phase A) and creative *buyers* as the eventual high-value
ICP (Phase C).** Hard-excluded: non-craft music services. Refined by signal-dense
verticals, Southeast-first.

---

## 2. Revenue Model

### Positions

**CRO (lead):** the A→B→C ladder, each rung self-funding the next (lean constraint).

| Phase | Model | Mechanism | Anchor |
|---|---|---|---|
| **A** | **Services uplift (internal)** | Software raises Chordential's win rate & margin on its own jobs | Incremental won deals × margin — funds everything else |
| **B** | **Tiered SaaS** | Solo $49–99/mo · Studio $299–499/mo · Agency/Enterprise custom + seats | Priced against **one won deal/month** |
| **C** | **Buyer-side + take-rate** | Procurement SaaS for buyers and/or ~5–15% take-rate on facilitated project value (GMV) | Take-rate on the deals we source/clear |

**CFO:** under lean/not-raising, **Phase A revenue is the runway.** There is no
outside capital, so the studio's software-driven margin gains literally fund B's
build. Pricing discipline: **value-based, not seat-based** — we sell *deals won*,
not logins. Gross margin must stay high; the dominant variable cost (LLM spend) is
already gated behind qualification + human "pursue."

**CRO (pricing logic):** every tier is justified by a single sentence — *"one job
you wouldn't have won pays for the year."* That's the only pricing story that
survives a churn conversation in a small market.

### Objections
- **CMO:** per-seat SaaS in a niche TAM (recorded-sync ≈ $650M) **caps ARR**. The
  venture-scale dollars are Phase C buyer-side take-rate. Don't let B's modest
  ceiling masquerade as the business.
- **Founder's Advocate:** agreed — B is a **moat-funding and proof rung**, not the
  destination. But we do **not** raise to skip it (CEO ruling). B must pay its own
  way and generate the data that makes C credible.
- **CTO:** whatever the model, **margin protection = cost gating.** Keep expensive
  generation behind qualification; never auto-draft for unqualified leads. Revenue
  model only works if per-opportunity cost stays near-zero on the junk.

### Synthesis
**Self-funded A→B→C: services margin (A) funds tiered, value-priced SaaS (B),
which proves and funds the buyer-side take-rate business (C).** Price on deals
won, not seats. Cost discipline (gated LLM spend) is a revenue-model requirement,
not just ops hygiene.

---

## 3. Competitive Advantage (the moat)

### Positions

**Founder's Advocate (lead):** the durable asset is **not** the scraper and **not**
the scores. It is two compounding things:
1. **Proprietary qualification + estimation models trained on real money** —
   real briefs, real labor, real win/loss, real margins, real revision counts by
   segment. Nobody else has Chordential's labeled outcomes.
2. **The buyer ↔ creator relationship graph** — who buys what, from whom, at what
   price, how often.

**CTO:** the *defensible* part is the **data flywheel**, not the features. Any
competitor can build a scraper or an LLM proposal-drafter in a weekend. What they
**cannot** copy is N years of Chordential's qualification labels and estimation
actuals. The architecture exists to manufacture and compound that data (Phase 3
calibration, qualification override-labels).

**Head of Production:** the *near-term* edge is **curation quality** — we reject
junk others surface, and we explain fit. "87% aligned, here's why" beats "here are
1,000 leads." Precision is a felt advantage before the data moat fully matures.

### Competitive landscape (who we beat, and how)

| Competitor class | Examples | Why they lose to Chordential |
|---|---|---|
| **RFP/lead databases** | RFPDB, gov portals, ProductionHub feeds | Commodity volume, no qualification, no estimation, no fit explanation — anyone can poll them. |
| **Freelance marketplaces** | Upwork, Fiverr, SoundBetter | Race-to-bottom labor matching; no opportunity intelligence, no curation, no estimation. |
| **Generic AI proposal tools** | horizontal proposal/RFP-response SaaS | Domain-blind; can't qualify music craft, can't estimate music labor, no buyer graph. |
| **Music libraries / sync platforms** | production-music catalogs | Sell *existing* tracks; orthogonal to original-craft sourcing. |
| **In-house "Jon's inbox + spreadsheet"** | the status quo | Slow, unscored, unestimated, no memory, no win/loss learning. |

### Objections
- **CFO:** a moat that takes years of data to mature is a **liability in year one**
  if we over-claim it. Be honest: the *day-one* advantage is curation + speed +
  domain estimation priors; the *durable* moat is the data. Don't sell the future
  one as the present one (don't raise on it either — consistent with the ruling).
- **RFP Intelligence:** advantage is partly **source access** — clean, owned
  connectors + email-alert intake into signal-dense lanes. Fragile if we over-rely
  on ToS-gated scraping; durable if we own the channels.
- **CMO:** advantages only count if customers *feel* them. The marketable edge is
  **"qualified, estimated, response-ready,"** not "we have a data moat." Sell the
  outcome; let the moat be the reason it keeps getting better.

### Synthesis
**Day-one edge: domain-specific curation + speed + estimation priors nobody
horizontal can match. Durable moat: the compounding proprietary dataset
(qualification labels, estimation actuals, win/loss, revision-by-segment) + the
buyer↔creator graph.** The data is built by the dogfooding loop (Phase A), so the
moat is a byproduct of operating — not a thing we have to fund separately.

---

## 4. Data Sources

### Positions

**COO (lead):** split into **inputs we ingest** and **data we manufacture** — the
second is the moat.

**A. Ingested opportunity sources** (capped per CFO ruling — ~6 clean automated +
alerts + manual; every source owned with an SLA):
- **Automated/API & RSS:** SAM.gov API, RFPDB / Campaign US RSS, and a small set
  of clean agency/production channels (current `tiered` source model).
- **Email-alert intake:** Mandy, ProductionHub, Hitmarker saved-search alerts
  forwarded to an intake inbox (cheap, durable, no scraping liability).
- **Manual paste + inbound-email parsing:** the long tail the team adds by hand.
- **Explicitly rejected:** mass scraping of ToS-gated sites (legal + maintenance
  liability, not an asset).

**B. Manufactured proprietary data** (the actual moat — generated by operating):
- **Qualification labels** — every human confirm/override on the qualification
  gate (predicted vs corrected).
- **Estimation actuals** — estimated vs actual hours/cost/margin per delivered job
  (Phase 3 calibration data).
- **Win/loss outcomes** — mandatory capture on every pursued opportunity.
- **Revision counts by segment** — e.g. healthcare 2.7 / automotive 4.1 / tech 1.3.
- **Buyer↔creator graph** — relationships, repeat buyers, price points.

### Objections
- **CTO:** every ingested source needs an **owner + SLA + health check** or it
  rots silently. Cap the automated set; prefer email-alert intake over fragile
  scrapers. A dead connector that looks alive is worse than no connector.
- **CFO:** the manufactured data (B) is **free and proprietary**; the ingested data
  (A) is **commodity and costs maintenance.** Spend accordingly — minimal effort
  on more sources, maximal rigor on capturing outcomes from the work we already do.
- **Head of Production:** garbage-in poisons the labels. Source quality matters
  because the qualification gate's training data is only as honest as the human
  confirmations behind it. Keep the human-in-the-loop until agreement rate proves out.
- **Founder's Advocate:** if we only ingest and never capture B, we built a lead
  tool, not a moat. **Win/loss + override capture is non-negotiable from day one.**

### Synthesis
**Few, clean, owned ingestion sources (the commodity input) + relentless capture
of qualification labels, estimation actuals, win/loss, and the buyer graph (the
proprietary output).** The first costs maintenance; the second *is the company.*

---

## 5. User Workflow

### Positions

**COO (lead):** one unified loop, internal-first (Phase A), same spine later
exposed to B/C users.

```
1. IDENTIFY   Unified intake queue ← APIs/RSS + email alerts + manual paste
2. RANK       Existing engine: 0–100 opportunity score + A/B/C/Watch tier
3. QUALIFY    Gate junk → classify discipline → alignment % + fit summary
                 ├─ disqualified → Watch/Pass (kept in DB, full recall)
                 └─ low confidence → Review queue (human confirm)
4. ALERT      Precision-gated: real-time only for qualified + high-alignment + confident
5. ESTIMATE   Hybrid model → team shape + budget band + rough margin
6. DECIDE     Human "pursue / pass" — the gate before spend
7. PREPARE    On "pursue": auto-draft brief + proposal skeleton (cost gated here)
8. SUBMIT     Track pipeline: new → qualified → brief → drafted → submitted
9. CAPTURE    Mandatory win/loss + actuals write-back → feeds the moat (steps 3 & 5)
```

**Head of Production:** the human stays in the loop at **two gates** — confirming
qualification on low-confidence items (step 3) and the **pursue/pass decision**
(step 6). Those are where trust and cost control live; never auto-spend past step 6
without a human commit.

**CMO:** the felt experience for a B user is *"open the app, see a short ranked
list of qualified, explained, estimated opportunities, click pursue, get a draft."*
The value is the **compression** — from "scan 20 sources" to "decide on 5 ready
briefs." That's the demo.

### Objections
- **CFO:** the **pursue gate (step 6) is the cost firewall.** Steps 1–5 must be
  cheap (rules + cached priors); the expensive generation (step 7) only runs after
  a human says go. Workflow must enforce that ordering, not just suggest it.
- **CTO:** keep it a **deterministic pipeline with targeted LLM calls**, not a live
  agent swarm. Each step is inspectable and cacheable. The workflow is the cost
  model.
- **RFP Intelligence:** the Watch lane (step 3 reject / low-score) must stay
  **browseable**, not hidden — early-development signals live there and graduate
  later. Full recall in the DB, precision only at the alert.
- **Founder's Advocate:** step 9 is the point of the whole thing. A workflow that
  lets a user skip win/loss capture is a bug — the loop must close or the moat
  doesn't compound.

### Synthesis
**A 9-step loop — Identify → Rank → Qualify → Alert → Estimate → Decide → Prepare
→ Submit → Capture — with two human gates (qualification confirm, pursue/pass) and
a hard cost firewall before generation. Capture closes the loop back into Qualify
and Estimate.** Internal-first; the same spine is the B/C product.

---

## 6. Success Metrics

### Positions

**CRO (lead):** metrics ladder by phase; **leading indicators first** (they predict
the lagging ones), per Decision #6 that qualification accuracy is the #1 objective.

**Phase A — internal (the only one that matters right now):**
| Metric | Type | Why |
|---|---|---|
| **Qualification agreement rate** (classifier vs human) | Leading | **#1 metric** — gate must earn trust before it alerts unattended |
| **Alert precision** (alerted A-tier that humans confirm as real) | Leading | Protects trust; precision-biased by ruling |
| **Win-rate uplift** on pursued jobs (vs pre-software baseline) | Lagging | The reason Phase A exists |
| **Time-to-response** (opportunity seen → brief ready) | Leading | The wedge is speed |
| **Estimate accuracy** (estimated vs actual cost/margin) | Lagging | Improves over Phase 3; *secondary* to qualification at launch |
| **Margin per won job** | Lagging | Lean constraint — growth is funded from this |

**Phase B — SaaS:** activation (first "pursue" within 7 days), retention/churn,
**net revenue retention**, deals-won-attributed-to-product, payback (< one won
deal), expansion to seats/tiers.

**Phase C — marketplace:** liquidity (matches/buyer), GMV facilitated, take-rate
revenue, repeat-buyer rate, time-to-fill a buyer request.

**Head of Production:** the **only** launch-gating metric is **qualification
accuracy** — specifically *false-positive rate on the junk list*. If we alert on a
cover band even once a week, trust dies. Everything else is secondary until the
gate is trusted.

### Objections
- **CFO:** add a hard **cost metric — fully-loaded cost per processed opportunity**
  (target near-zero on junk, capped on qualified). Under lean, an un-instrumented
  cost line is an existential blind spot.
- **CTO:** instrument **source health** (freshness, error rate per connector) — a
  silently dead source tanks recall without showing up in win-rate for weeks.
- **Founder's Advocate:** the **moat metrics** are the ones nobody asks for but
  that define the company: cumulative labeled qualification examples, cumulative
  estimation actuals, buyer-graph density. If those aren't growing, we're a tool,
  not a moat — regardless of revenue.
- **CMO:** vanity metrics (leads surfaced, opps ingested) are **banned as success
  metrics.** Volume is an input, not a result. Success = qualified, won, retained.

### Synthesis
**Primary (now): qualification agreement rate + junk false-positive rate
(launch-gating), alert precision, time-to-response, and win-rate uplift — with
cost-per-opportunity and source-health as guardrails.** Estimate accuracy is a
*calibrating* metric, deliberately secondary at launch (Decision #6). Moat-growth
metrics (cumulative labels, actuals, graph density) are tracked as the real
long-term scoreboard. **Volume is never a success metric.**

---

## Open questions for the CEO (from this round)

1. **ICP focus for B:** lead with **studios** (CRO's retention case) or push toward
   **buyer-side (C)** sooner (CMO/Founder's Advocate)? Default: studios first, keep
   buyer-side discovery running in parallel.
2. **Solo tier:** ship the $49–99 Solo tier as a funnel, or **skip it** and focus
   on Studio+ where WTP and retention are real (CFO leans skip)?
3. **Launch-gating metric:** ratify **qualification agreement rate / junk
   false-positive rate** as *the* go-live bar for unattended alerting — and set the
   threshold (e.g. ≥95% agreement before alerts run without human confirm)?
4. **Vertical focus:** concentrate sourcing on 2–3 signal-dense lanes first
   (healthcare / automotive / tech / hospitality), or stay horizontal across
   commercial music?
