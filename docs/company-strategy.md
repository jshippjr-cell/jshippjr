# Chordential — Company Design (Executive Deliberation)

*Board simulation. Founder/CEO: Jon Shipp (final decision-maker). Agents are
required to disagree; objections are documented; consensus is not required.*

**Mission:** Identify, rank, qualify, estimate, and prepare responses to music
production opportunities for film, TV, advertising, gaming, trailers, streaming,
branded content, and media.

---

## Founder's Advocate — opening frame (the north star)

Chordential is **not** trying to become Upwork. It is **not** trying to become a
generic RFP scraper. It is trying to become **the intelligence layer between
creative buyers and music creators** — long term, *the operating system for
commercial music procurement.*

The durable asset is therefore **not** the scraper and **not** even the scores.
It is two things:

1. **Proprietary qualification + estimation models** trained on real money
   (real briefs, real labor, real win/loss, real margins).
2. **The buyer↔creator relationship graph.**

Every roadmap item gets one test: *Does this accumulate proprietary procurement
intelligence or buyer relationships?* If not, it is a feature, not a moat.

**Three drifts to refuse:** (a) becoming a labor marketplace (Upwork),
(b) becoming a commodity RFP scraper (no moat — anyone can poll SAM.gov),
(c) becoming a profitable-but-capped services shop with a lead tool bolted on.

---

## The product spine (mission verbs → system)

| Mission verb | Function | Owner |
|---|---|---|
| **Identify** | Ingest from APIs/RSS/email-alerts/manual | COO + RFP Intelligence |
| **Rank** | Weighted scoring + A/B/C/Watch tiers (built) | RFP Intelligence |
| **Qualify** | Is this real, Chordential-shaped music work? | Head of Music Production |
| **Estimate** | Team, hours, cost, price, margin | Estimation Agent |
| **Prepare responses** | Auto-draft brief + proposal skeleton | COO + CTO (LLM) |

The engine we already built covers **Rank**. The company-defining work is
**Qualify**, **Estimate**, and **Prepare** — because those are where the
proprietary data and the moat live.

---

## The central strategic fork — what do we sell *first*?

| Model | What it is | Revenue | Ceiling | Risk |
|---|---|---|---|---|
| **A — Studio Force Multiplier** (internal) | Software powers Chordential's own studio to win more $2.5k–15k jobs | Chordential services | Modest alone | Looks like a services business |
| **B — Procurement Intelligence SaaS** | Sell the platform to studios/composers/supervisors/agencies | Subscription + seats | Mid (niche TAM) | Feature is copyable without data moat |
| **C — Procurement OS / Marketplace** | Sit between buyers and creators; facilitate + take a cut | Take-rate on GMV / buyer-side SaaS | High (the real vision) | Chicken-and-egg liquidity |

**Recommended sequence: A → B → C**, but executed deliberately. Model A is not
"a studio with a lead tool" — it is **data manufacturing**. Every dogfooded job
produces qualification labels, estimation actuals, and win/loss outcomes that
become the moat that makes B defensible and C possible.

This is contested below.

---

## Executive positions (with required objections)

### COO — operational workflow
- **Intake:** one unified queue fed by SAM.gov API, RFPDB/Campaign US RSS,
  email-alert intake (Mandy/ProductionHub/Hitmarker saved-search alerts forwarded
  to an intake inbox), manual paste, and inbound-email parsing.
- **Categorize:** auto-classify music type (composition / licensing / sonic
  branding / sound design / supervision / none) + buyer type + tier, with
  human-in-the-loop confirm on borderline cases.
- **Alerts:** real-time in-app + email for A-tier; daily digest for B; weekly for
  C/Watch; routed by role (composer/engineer/editor/lead).
- **Briefs:** auto-generated opportunity brief = scorecard + estimate + suggested
  response outline, gated by Head of Production sign-off before outreach.
- **Proposals:** pipeline stages new → qualified → brief → drafted → submitted →
  won/lost, with **win/loss capture mandatory** (it feeds the moat).
- **OBJECTION (to CTO):** "Every source must have an owner and an SLA or it rots.
  If a connector can't be operationally supported, we don't ship it. Reject broad
  scraping we can't maintain."

### CTO — architecture
- Reuse the existing Python OIA engine. FastAPI backend, Postgres (Supabase),
  scheduled ingestion workers + a **lightweight task queue** (not Kafka-grade
  infra until volume demands it).
- **AI orchestration:** Claude for discrete, cacheable steps — (1) normalize
  messy RFP text → structured signals, (2) qualify, (3) estimate, (4) draft
  brief/proposal. **Not** an open-ended live agent swarm in production.
- **DEFENDS:** narrow, durable connectors + email-alert intake. Scraping
  ToS-gated sites is a legal + maintenance liability, not an asset.
- **OBJECTION (to the "swarm" framing):** a literal multi-agent swarm running per
  opportunity is expensive and flaky. Use a deterministic pipeline with targeted
  LLM calls. Documented objection to over-engineering.

### CFO — capital
- **Build:** low — the engine exists; MVP web app is a few focused weeks. Managed
  services ~$0–150/mo at pilot scale.
- **Operate:** dominant variable cost = LLM calls per opportunity. Rough order:
  ~$0.05–0.30 per fully processed opportunity (normalize+qualify+estimate+draft).
  At ~2,000 opps/mo ≈ $100–600/mo.
- **CHALLENGE (to CTO, "scrape 10,000 sites"):** No. Cost per incremental scraped
  source (build + maintain + legal) rarely beats free email-alert intake. **~95%
  of A-tier value concentrates in a handful of agency/production channels.** Cap
  automated sources at the ~6 with clean access; everything else manual/alerts.
- **CHALLENGE (to scope):** auto-drafting full proposals for *every* lead burns
  money on leads that never convert. **Gate expensive generation behind
  qualification** — only draft for A-tier and human-marked "pursue."
- **HONESTY FLAG:** standalone intelligence TAM is modest (recorded-sync ≈ $650M).
  The venture-scale case rests on Model C. Do not raise on an inflated Model B TAM.

### CMO — customer acquisition
- **Who buys (B):** boutique/mid studios, composers, music supervisors, agency
  producers, branded-content production companies.
- **Why buy:** they lose winnable work because they find out too late or can't
  respond fast. The wedge is **"qualified, estimated, response-ready,"** not "more
  leads."
- **Problem solved:** qualification + speed-to-response + estimation confidence —
  not lead volume (that's a commodity with free alternatives).
- **CHALLENGE:** every feature must answer "will customers pay?" Auto-proposal &
  estimation: yes. Generic scraping: no.
- **OBJECTION:** selling SaaS to small studios is slow and low-WTP. The
  better-paying customer may be the **buyer side** (agencies/brands paying to
  source vetted music partners) — which argues for accelerating toward Model C.

### CRO — revenue
- **A (internal):** ROI = incremental win-rate × deal size on Chordential's own
  services.
- **B (SaaS):** value-based tiers — e.g. Solo $49–99/mo, Studio $299–499/mo,
  Agency/Enterprise custom + seats; priced against *one won deal/month*.
- **C (marketplace):** take-rate (~5–15% of project value) and/or buyer-side
  procurement SaaS.
- **CHALLENGE:** every feature must raise win rate. Estimation, auto-proposal, and
  ranking do; raw scraping doesn't. Price on value (deals won), not seats.
- **OBJECTION:** per-seat SaaS in a small market caps ARR. The real unlock is
  owning the buyer side. Aligns with CMO toward C.

### Head of Music Production — the quality gate (the role founders forget)
- Filters garbage: composition vs licensing vs sonic branding vs sound design vs
  supervision vs noise (cover bands, karaoke, DJs, "needs a playlist"). **Most
  "music" hits are NOT Chordential-shaped.**
- Owns the **qualification rubric** Estimation and RFP agents must honor: real
  creative brief? original work? budget signal? clearable? on-craft?
- **OBJECTION:** "If we optimize for lead volume, we drown the team in junk and
  burn trust in the scores. An A-tier score with no real music craft is a false
  positive." Demands the quality gate precede alerting, with human confirm until
  the classifier earns trust.

### RFP Intelligence Agent — domain/source expert
- Owns SAM.gov, GovWin, ProductionHub, agency & commercial channels; outputs the
  opportunity score.
- **DISAGREES with Head of Production on volume:** breadth catches early signals
  (productions entering development) that pay off later. Wants to ingest more, tag
  confidence, and let scoring sort.
- **Documented tension — Recall vs Precision.** Recommendation: **precision-biased
  alerts**, full recall retained in the database (low-confidence surfaces as
  "Watch," never alerts). CEO sets the target.

### Estimation Agent — labor / cost / margin
- For each qualified opp: predicts team (composer/arranger/mixer/sound designer/
  music editor), hours, cost, price, margin → turns a lead into a go/no-go and a
  proposal skeleton. **This is both a differentiator and the data-moat engine.**
- **OBJECTION (gating risk):** estimation is only as good as historical data;
  cold-start is weak. **Requires Jon to seed real past-project actuals** (hours/
  cost/margin) or early estimates will mislead.

---

## Documented Objections Log

1. **CFO vs CTO** — scraping breadth → resolved toward narrow connectors + email
   alerts; cap at ~6 automated sources.
2. **CMO/CRO vs COO/CFO** — SaaS-first (venture optics) vs dogfood-first (capital
   efficiency + data moat) → **escalated to Jon.**
3. **Head of Production vs RFP Intelligence** — precision vs recall →
   recommend precision-biased alerts, full recall in DB.
4. **CFO vs Mission scope** — auto-draft proposals for all leads → gate behind
   qualification + human "pursue."
5. **Founder's Advocate vs drift** — keep building the procurement OS and the data
   moat, not a scraper or a lifestyle services shop.
6. **CFO/CRO honesty** — venture scale needs Model C; don't over-raise on Model B.

---

## CEO SUMMARY

**Problem:**
Chordential can profit today from commercial music work, but the *company* is only
venture-grade if it becomes the intelligence layer / operating system between
creative buyers and music creators. The risk is drifting into a commodity RFP
scraper or a capped services business. We must choose what to sell first and how
to manufacture a defensible data + relationship moat.

**COO Recommendation:**
Build the smallest reliable pipeline (unified intake → classify → tier →
qualify → estimate → brief), every source owned with an SLA, mandatory win/loss
capture. Reject anything ops can't maintain.

**CTO Recommendation:**
Reuse the engine; FastAPI + Postgres + light queue + cacheable Claude steps.
Narrow durable connectors + email-alert intake. No live agent swarm, no mass
scraping.

**CFO Recommendation:**
Cheap to build, cheap to run if disciplined. Cap automated sources (~6), gate
expensive AI drafting behind qualification, price on value. Don't raise on
inflated TAM — the venture case is Model C.

**CMO Recommendation:**
Sell the outcome (won, response-ready deals), not the tech. Wedge = qualified +
fast + estimated. The higher-WTP customer is ultimately the buyer side.

**CRO Recommendation:**
A→B→C revenue ladder; value-based pricing tied to deals won; real upside is the
buyer-side take-rate, not per-seat SaaS.

**Head of Production + Estimation:**
Quality gate before alerts; precision-biased. Seed estimation with real
Chordential actuals or it misleads.

**Founder's Advocate:**
Endorse A→B→C **only if** Model A is run as deliberate data manufacturing and
buyer-relationship building — otherwise it's just a studio with a lead tool.

**Risks:**
- Niche TAM; venture scale depends on the hard Model C marketplace.
- Estimation cold-start without seed data.
- Lead-quality false positives eroding trust.
- Source access fragility (ToS/paid gates) if we over-rely on scraping.
- Drift into commodity scraper / Upwork / lifestyle business.

**Decision Required From Jon:**
1. **GTM sequence:** approve A→B→C (dogfood-first), or push SaaS (B) first?
2. **Fundraising posture:** bootstrap to a data moat then raise, or raise now on a
   SaaS thesis?
3. **Alert bias:** precision-biased alerts (recommended) or high-recall?
4. **Proposal drafting:** gate full auto-drafts behind human "pursue"
   (cost-safe), or auto-draft all A/B leads?
5. **Estimation seed:** will you provide real past-project actuals to train the
   estimator?

---

## CEO DECISIONS — Ratified by Jon Shipp, 2026-06-16

1. **GTM sequence — APPROVED: A→B→C (dogfood-first).** Model A is run as
   deliberate data manufacturing: capture qualification labels, estimation
   actuals, and win/loss on every internal job.
2. **Fundraising — APPROVED: keep it lean / not raising (for now).** Run as a
   profitable, software-leveraged services business; no outside capital and no
   raise process at this stage. Revisit only from a position of proven traction
   and a real data moat. This is firmer than "bootstrap then raise": the default
   is self-funded, capital-disciplined growth.
3. **Alert bias — APPROVED: precision-biased.** Alert only on high-confidence,
   Chordential-shaped opportunities; retain full recall in the DB as "Watch."
4. **Proposal drafting — APPROVED: gate full auto-drafts behind human "pursue."**
   Always produce the cheap brief + estimate; spend on full proposals only after
   a human commits.
5. **Estimation seed — OPEN.** Pending: Jon to provide real past-project actuals
   (hours/cost/margin) to train the estimator and avoid cold-start error.

### What these lock in
- **Build priority:** Qualify → Estimate → Prepare (gated), on top of the
  existing Rank engine. These produce the proprietary data moat.
- **No premature scale:** ~6 clean automated sources max; email-alert intake +
  manual for the rest; no mass scraping; no live agent swarm.
- **Capital discipline is now a hard constraint** (not raising): every operating
  dollar — especially LLM spend — must justify itself against won revenue. This
  reinforces the gated-proposal and precision-alert decisions.
- **Win/loss capture is mandatory** from day one — it is the moat, not a metric.
- **Internal-first product:** the first "customer" is Chordential's own studio;
  every feature must raise Chordential's win rate before it is sold to anyone.
