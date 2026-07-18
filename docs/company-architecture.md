# Chordential / ChordOS — Company Architecture

*Company Architecture Mode deliverable. Commissioned by Jon Shipp (Founder/CEO),
2026-07-18. A first-principles redesign of Chordential as a company — the software
exists only to enable it. Grounded in the full repository record (Constitution, ADRs,
PROJECT_STATE, strategy docs, councils, PRDs, agency reviews) digested by four parallel
research passes; every major claim cites its source. Where this document contradicts
ratified strategy or the Constitution, the contradiction is explicit and framed as a
**proposed amendment** for the founder to ratify or reject — the machine proposes, Jon
disposes, including here.*

---

## 1. Executive Summary

Chordential is an extraordinary machine attached to no market. The record says this
itself, in its own words: *"a superb machine for processing deal flow we do not yet
have… the plumbing is gorgeous; the faucet isn't connected to a customer"*
(`market-entry-healthcheck-council.md`), and *"we have made $0. Every one of those
[features] is a cost center until a customer pays"* (`revenue-drive-council.md`).

The redesign in this document rests on five findings that recur independently across
every slice of the record:

1. **The company's scarcest resource is Jon's hours, and they are the least
   systematized part of the business.** Every gate — qualify, outreach, discovery call,
   proposal, reel review, assignment, CI confirmation, release — terminates in one
   person with a day job. The software optimizes everything *around* the bottleneck and
   almost nothing *inside* it. The company must be rearchitected as a system for
   maximizing the yield of roughly **5–10 founder-hours per week**, because that is the
   entire real capacity of the firm.

2. **Two companies coexist in the record and compete for those hours.** One sells
   *Music Opportunity Intelligence* software (`cmo-positioning-brief.md`); the other
   sells *clearance-certified original music* (`product-spec-clearance-certified.md`,
   `sonic-signature-sales-playbook.md`). The council's Question 1 — which goes to
   market first — was never answered. This document answers it: **Chordential is a
   music company. The software is not for sale.** (§17, Amendment A-1.)

3. **The moat's foundation is missing its legal floor.** The product's core promise —
   clean chain of title, one-signature rights — is currently enforced by *nothing*:
   no composer agreements, no rates on assignments, no payout ledger, no W-9s
   (`talent-recruiting-council.md`: *"Money flows IN only. There is ZERO talent
   payout"*). The company's hero claim outruns its supply chain. Fixing this is not a
   feature; it is the difference between a real company and a liability generator.

4. **The demand engine is pointed at the wrong market and is partially broken.** The
   wired channels source $500–2k indie-game briefs while the strategy's beachhead is
   agency producers buying $2.5k–15k engagements; the discovery scanner is bot-blocked;
   the qualification gate strangles its own supply on keyword technicalities
   (`funnel-recall-audit-and-gmail-mcp-plan.md`, `revenue-drive-council.md`,
   `lead-sources-research.md`). Meanwhile the *actual* beachhead motion — founder-led
   relationship selling — has no system behind it at all.

5. **The recurring failure mode is spec-ahead-of-build.** Per-asset approval was
   promised twice before it shipped; indemnification is promised in the product spec
   and deliberately absent from the shipped certificate; the demo seed contradicts the
   rebuilt engine; outbound client email — the one channel the "replaces email" thesis
   depends on — is an honest TODO (`delivery-os-agency-review-2.md`). The company
   writes checks in documents faster than the build cashes them.

**The redesign in one paragraph.** Chordential becomes a **founder-taste,
AI-operated music studio**: one identity (clearance-certified original music for
agencies and brands), one wedge offer (Sonic Signature), one selling motion (Jon's
relationship hours, prepared and multiplied by an AI staff), one production model
(bench composers under real agreements, Jon as taste gate, margin on delegation), and
one operating system (ChordOS) that runs every department *as an AI department head*
that prepares decisions so completely that Jon's entire job compresses into a daily
**Disposition Queue** — a single surface where every pending decision in the company
arrives pre-analyzed with a recommended action, and every decision he takes is captured
as labeled training data. The org chart is AI; the taste, relationships, and signature
are Jon's; the moat is the data the operation manufactures by running.

The $1M path (§20) is honest about arithmetic: at a $6–8k average engagement, $1M is
125–165 engagements a year — impossible solo. $1M therefore *requires* the delegated
production model (bench composers at 40–50% fee share), 2–4 agency retainers, and the
licensing-renewal annuity. The roadmap sequences so each phase self-funds the next and
the first 90 days have exactly one success metric: **a signed deposit from a real
client.**

---

## 2. Current State Assessment

**What genuinely exists and works (verified by the record):**

- **A hardened deterministic demand spine** — Identify → Rank → Qualify → Estimate →
  Prepare → Outreach → Win/Loss — with a precision-biased qualification gate
  (junk gate + discipline classification + 0–100 alignment scoring), expert-prior
  estimation, and deterministic proposal/brief builders (`qualification-spec.md`,
  `product-roadmap.md`; ~915 green tests).
- **A review-hardened delivery core.** The narrow real thing: one token-gated review
  link with timecoded comments, verified-reviewer approval, an auto-assembled
  clearance package (masters/stems/cue sheet/rights certificate/manifest, one ZIP),
  and a server-gated release requiring license confirmation. Two simulated agency
  reviews drove real fixes: cookie identity, reply/resolve, playable version history,
  signatory block, honest Content-ID language (`delivery-os-agency-review-2.md`).
- **A serious intelligence architecture.** Campaign Intelligence: one living record
  per engagement, per-field provenance (`{value, sources[], status}`), epistemic kinds
  (`fact/insight/recommendation/open_question` — judgment never laundered into fact),
  immutable Captures as evidence, a 10-worker extraction crew with deterministic
  validation and a recall auditor, and a Producer Learning ledger capturing every
  human disposition (`CAMPAIGN_INTELLIGENCE.md`, ADR-0021/0023).
- **A ratified commercial model of unusual sophistication.** 50% non-refundable
  deposit, net-7 balance, release gated on payment; Creative Lock as the scope hinge;
  conform-vs-revision distinction; the round ledger; the free-extra ledger; the
  license as a living object with a renewal calendar (`billing-lifecycle-council.md`,
  `production-lifecycle-model.md`).
- **A disciplined governance culture.** 23 ADRs, a Constitution with an amendment
  procedure, a build loop with QA gates and recorded CEO rulings, and an honesty rule
  enforced down to watermarked demo artifacts.

**What exists on paper only:** the Campaign Workspace/Creative OS (cues, phases,
AI employees), most of the Client Workspace sequence past P0/P1/P4, the multi-lane
intake framework, Legal Intelligence (unratified), Relationship Intelligence, Phase
B/C anything (`campaign-workspace-prd.md`, `PROJECT_STATE.md`).

**What is broken or missing in the live path:** durable object storage (ZIPs die
on deploy); Postgres cutover (ops not run; every deploy is a ~2-min outage);
DocuSign (placeholder); the bot-blocked discovery scanner.

*Correction (2026-07-18, verified against code after this document was first
written — the docs lagged the build):* agency-direction reviewer emails
(`_notify_reviewers_new_version`), the payout ledger (`talent_payouts` + W-9
gate), and the funnel audit's B0 filter fixes (`_MONEY_RE`, tightened
`_COLLAB_MARKERS`) were **already built and tested**. Since ratification, the
remaining true gaps have been closed: composer agreements + the assignment gate
shipped as **ADR-0024** (Amendment A-3, founder-ratified hard block), the
**Disposition Queue v1** shipped at `/queue`, and the **ADR-0014 log hole** was
formally reconstructed.

**Commercial state: $0 revenue, zero pipeline, zero case studies, no demand-gen
motion** (`market-entry-healthcheck-council.md`, `revenue-drive-council.md`). All
delivery surfaces have been exercised chiefly against seeded fiction (AURORA, Vance
Athletic) — honest fiction, but fiction.

---

## 3. Critical Weaknesses

Ranked by how directly each blocks the first $1M.

1. **No demand.** No leads arrive by any defined path. The wired channels source the
   wrong market at the wrong price point. The founder-led motion (named list of 30,
   10 conversations/week) exists as a playbook, not a practice, and nothing in the
   system prepares, schedules, or follows up those conversations for him.
2. **Founder-hour famine, structurally guaranteed.** The disposition load scales with
   data manufactured (every extracted fact wants confirmation), not with deals won.
   The machine generates more decisions per hour than the decision-maker has hours.
3. **The supply-side legal void.** No composer agreement, no assignment-of-rights
   instrument, no rates, no payouts, no W-9s — while the product's entire premium is
   rights certainty. One delivered deal under this gap is an unlimited-liability event
   (`talent-recruiting-council.md`, `LEGAL_INTELLIGENCE.md` collision noted by the
   architecture research pass).
4. **The hero guarantee may be undeliverable as marketed.** Indemnification and
   Content-ID safelist registration are promised in `product-spec-clearance-certified.md`
   and deliberately absent from the shipped instrument. Selling the spec risks the
   trust the whole positioning rests on (Head of Production, unresolved Question 4).
5. **Spec-ahead-of-build as culture.** The gap between the described company and the
   real one is itself a liability — internally (misallocated build hours) and
   externally (a client who buys the description).
6. **Single-point-of-failure identity.** Taste, relationships, signature, legal
   signatory, sole seller: all Jon. The company cannot currently survive a bad month
   of his attention, let alone scale past it.
7. **Infrastructure debt on the trust path**: local-disk deliverables, deploy
   downtime, no e-signature, no outbound email — each small, all sitting directly on
   client-facing promises.
8. **A time-limited wedge.** The AI-scarcity thesis (uncopyrightable AI output) is
   partly hostage to 2026 litigation and major-label licensing deals
   (`market-research.md`). The window is real but not permanent.

---

## 4. Critical Strengths

1. **The positioning thesis is genuinely differentiated and legally grounded.**
   "Music your legal team can defend" attacks a documented, growing pain (Content-ID
   claims, the creator-licensing trap, ~$140M Marriott-class exposure anecdotes) that
   libraries and AI structurally cannot solve. The USCO/appeals-court rulings make
   human authorship a *procurement requirement*, not a preference (`market-research.md`).
2. **The delivery moment is real and reviewers loved it.** *"Approve → the package
   assembles itself → download everything… the thing no AI tool or library gives me"*
   (`delivery-os-agency-review.md`). This is the demo that sells.
3. **The intelligence architecture is ahead of anyone in this niche.** Per-fact
   provenance with epistemic kinds, human-authoritative merges, and a disposition
   ledger is CRM-grade infrastructure no boutique studio has. It is premature for
   today's deal flow — which means it is *ready* for tomorrow's.
4. **The governance culture is an asset.** Constitution, ADRs, honesty rule, QA
   gates: this is what lets one founder safely operate an AI staff at all. Most solo
   founders have no such rails.
5. **Deterministic engines + provider seams = near-zero burn.** The whole system runs
   without credentials and costs almost nothing idle. Capital discipline is already
   architecture (Constitution §4.5).
6. **The commercial model is pre-litigated.** Deposit law, Creative Lock, conforms,
   round ledgers, renewal annuities — most studios learn these by being burned;
   Chordential has them ratified before its first deal.
7. **The founder holds real domain authority** — composer credibility, agency-side
   fluency, and taste — which is the one thing in this company AI cannot replace and
   competitors cannot copy.

---

## 5. Complete End-to-End Operating Model

The redesigned company runs as **one loop with four beats**, replacing the current
two-sided spine-plus-portals sprawl. Every beat is owned by AI department heads; every
decision lands in one place.

**Beat 1 — KNOW (always on).** The intelligence departments maintain living dossiers
on a *named, bounded* target market: ~100 agencies/brand teams in the beachhead
(Southeast/US, $2.5k–25k music spend), each with decision-makers, observed campaigns,
signals, and relationship state. Discovery is re-aimed: agency/brand signals first
(new campaigns, account wins, hires, awards), gig boards demoted to background. The
output is not "opportunities ingested" but a daily **Why-Today shortlist**: at most
3–5 reasons to touch a specific human today, each with a drafted touch.

**Beat 2 — WIN (Jon's hours, multiplied).** The selling motion is founder-led by
design, not by failure. The system's job is to make every founder-hour a prepared
hour: research briefs before calls, drafted first-touches (his voice, one track, one
soft link), scheduled follow-ups queued as one-tap dispositions, discovery calls
recorded → extracted → confirmed same-hour into CI, proposals assembled from CI and
sent for one-click client acceptance → deposit link → paid. **Target: a founder-hour
spent selling touches only humans, never software.** Everything else — logging,
drafting, scheduling, chasing — is staff work, done by the AI org.

**Beat 3 — MAKE (delegated craft under a taste gate).** Won work is staffed from a
small bench (3–7 active composers) under a standing **Composer Agreement** (work
assignment + rights conveyance + rate + credit + payment-on-client-payment), matched
deterministically, assigned by Jon. Composers work against the locked brief;
submissions hit the publish gate; Jon's taste review is the *only* internal review;
the client sees nothing unvetted. Creative Lock, the round ledger, and
conform-vs-revision run as contractual mechanics surfaced to both sides. Jon composes
only when he chooses to — his scarce contribution is direction and taste, not hours
at the piano.

**Beat 4 — PROVE (the flywheel).** Delivery assembles the clearance package
(rights chain now *real*, backed by the composer agreements from Beat 3); release is
payment-gated; the license terms enter the renewal calendar (the annuity); win/loss,
estimate-vs-actual, revision-by-segment, and buyer preferences write back to CI →
Agency/Relationship Intelligence. Every delivered job makes the next one for that
buyer measurably cheaper to win and safer to price. A case study (with permission) is
manufactured as a *deliverable of the engagement itself*, not an afterthought.

**The connective tissue: the Disposition Queue.** One surface, mobile-first, where
every pending decision in the company arrives as a card: *recommendation + evidence +
one-tap actions (approve / edit / defer / reject)*. Qualification confirms, outreach
sends, reel verdicts, assignment pushes, CI conflicts, release buttons — all of it,
ranked by revenue-weighted urgency, budgeted to Jon's declared hours. This is the
machine-proposes law made *ergonomic* instead of merely legal. (Today those
dispositions are scattered across a dozen pages; the law is honored but the throughput
is starved.)

**Handoffs eliminated** (per the question-every-handoff mandate): opportunity→project
recreation (already fixed by CI adoption-in-place — keep); brief-token→delivery-token
URL break (fix via ADR-0018's durable workspace token — build); manual link-sharing on
every version (dies with outbound email — build first); the two upload forms (merge);
proposal→invoice→payment (already one chain — keep); operator-relay of client feedback
to composers (dies with the creator portal's feedback view — shipped; keep);
"log the touch" as separate work (dies — touches are logged by the tools that send
them); win/loss capture as a form (dies — outcome capture is embedded in the
close/release flows it describes).

---

## 6. Organizational Structure

The company is **one human + an AI staff org + a contractor bench**.

- **Jon — Founder/CEO/Executive Producer.** Owns: taste, relationships, signature,
  price, and every constitutional decision button. Time budget: explicit and declared
  (e.g., 7 h/week: 4 selling, 2 dispositions, 1 taste review). The org is *sized to
  the budget* — departments may not generate more dispositions than the budget clears
  (excess auto-defers by ranked priority; the queue is honest about what it starved).
- **The AI Executive Staff** (§7–8): twelve department heads, each a defined role with
  a mission, owned decisions (recommendations only, per the machine-proposes law),
  KPIs, and an escalation contract. They are today implemented as deterministic
  engines + gated LLM steps (ADR-0005) surfaced through the Disposition Queue; the
  *org design* is real even where the implementation is a Python module.
- **The Composer Bench** (contractors, not employees): 3–7 active, tiered
  Core/Roster (priority-first-look, never cash retainers — CFO ruling honored,
  `talent-recruiting-council.md`), under standing agreements, paid from landed cash on
  client payment, W-9 before first payout.
- **On-call professional seams** (bought, not hired): entertainment counsel (one
  engagement: the Composer Agreement + license templates + certificate review — this
  unblocks Legal Intelligence ratification); a bookkeeper-in-a-box (Stripe + ledger
  export); no other humans.

No departments merge because none exist to merge; the design *prevents* future
departments by making each AI head absorb what a hire would have done.

---

## 7. AI Agent Organization Chart

```
                         Jon — Founder / CEO / EP
                    (all decision buttons; taste; signature)
                                   │
                        ┌──────────┴──────────┐
                        │  Chief of Staff /   │
                        │  Disposition Queue  │  ← the only surface Jon must visit
                        └──────────┬──────────┘
      ┌───────────┬───────────┬───┴───────┬───────────┬───────────┐
   KNOW        WIN         MAKE        PROVE       MONEY       GUARD
      │           │           │           │           │           │
 • Market     • Business  • Production • Delivery  • Finance  • Legal Ops
   Intelligence  Development  Ops         Ops         (AR/AP,     (rights chain,
 • Buyer      • Relationship• Talent    • Quality     ledger,     agreements,
   Research     Management    Ops         Assurance   renewals)   compliance)
 • Signal     • Proposal   • Composer  • Knowledge             • Continuity
   Detection    Desk         Relations   & Learning              (risk, backup,
                                                                  escalation)
```

Twelve heads, six clusters. Each behaves as the head of its department: it watches
its domain continuously, prepares complete decision packages, executes approved
actions, measures itself, and files an honest weekly self-report into the queue.

---

## 8. Department Responsibilities

Format per department: **Mission · Owns (decisions it prepares) · Inputs → Outputs ·
KPIs · Escalates when · Improvement loop · Today's substrate** (the existing module
it grows from — mapped honestly; "new" where nothing exists).

**8.1 Chief of Staff (Disposition Queue).** Mission: convert the whole company's
pending state into the smallest ranked set of founder decisions that fit the declared
time budget. Owns: ranking, batching, deferral. Inputs: every department's proposals →
Outputs: the daily queue, decision receipts, a starvation report (what was deferred
and the estimated cost). KPIs: dispositions/founder-hour; median decision latency;
starved-item revenue-at-risk. Escalates: any item aging past its SLA; any week the
budget is exceeded 2×. Improves via: ADR-0021's Producer Learning ledger — every
disposition is a labeled example that tightens the next recommendation. Substrate:
**new surface** over existing per-page gates (`next_action.py`, dashboard queues).

**8.2 Market Intelligence.** Mission: maintain the living map of the bounded target
market (~100 named buyers) and the industry conditions (AI-law shifts, pricing norms).
Owns: target-list composition proposals; source on/off recommendations. Inputs:
crawls, signals, F5Bot, manual → Outputs: agency dossiers, market-condition briefs,
quarterly wedge-health review (is the AI-scarcity window moving?). KPIs: dossier
freshness; % of won deals that were on the map ≥60 days prior. Escalates: legal/market
shifts that touch positioning (e.g., the fair-use ruling). Substrate:
`discovery.py`, `enrichment.py`, `intelligence.py`, `signals` — **re-aimed** from gig
boards to the named-buyer map.

**8.3 Buyer Research (Decision-Maker Intelligence).** Mission: know the humans — who
signs, who influences, what they've shipped, what they care about. Owns: contact
recommendations, multi-thread maps (the playbook's 3+ stakeholders). Inputs: dossiers,
LinkedIn (manual-assist per ADR-0009), call extracts → Outputs: per-buyer relationship
cards with next-best-action. KPIs: % of active deals multi-threaded; contact-data
accuracy. Substrate: `decision_makers.py`, `buyer_intel.py`.

**8.4 Signal Detection.** Mission: answer *why today* — detect the change that makes
this the day to touch this buyer. Owns: Why-Today shortlist composition (max 5/day).
Inputs: all sources → Outputs: signal cards with evidence links. KPIs: **precision of
acted signals** (Constitution §4.4: one junk alert costs more than ten misses);
signals→conversation conversion. Escalates: never autonomously contacts anyone.
Substrate: `opportunity_signals.py`, `signal-engine-plan.md`. **Fix ordered by the
record:** relax the PURSUE gate's keyword technicalities (dollar-amount pay signals,
collab-list false kills — `funnel-recall-audit-and-gmail-mcp-plan.md`) so the queue,
not the filter, applies judgment.

**8.5 Business Development.** Mission: fill Jon's selling hours with prepared
conversations from the named list; run the founding-client sequence
(`sonic-signature-sales-playbook.md`) as a system. Owns: outreach drafts (his voice,
mailto-send preserved), cadence scheduling, follow-up chases, call-prep briefs
(one page: who/why-now/what-to-play/likely objections). Inputs: Why-Today list,
relationship cards, CI → Outputs: scheduled touches, prep briefs, the pipeline truth
board. KPIs: **real conversations/week** (target 10); touch→call rate; call→proposal
rate. Escalates: pipeline below 3 active conversations (the starvation alarm).
Substrate: `outreach.py`, first-touch composer, follow-up queue — plus the Gmail
triage lane (design exists) for inbound.

**8.6 Relationship Management.** Mission: institutional memory and continuity — no
relationship ever goes cold by accident. Owns: next-best-action per relationship,
dormancy alerts, post-deal nurture cadence. Inputs: every touch/call/outcome, CI
rollups → Outputs: relationship stages, renewal/reactivation prompts. KPIs: % of
relationships with a live next action; repeat-rate. Substrate: `relationships.py`,
`buyer_intel.py`, ADR-0018's Relationship Intelligence (build the CI→RI rollup —
it's the moat's compounding step).

**8.7 Proposal Desk.** Mission: from confirmed CI to a signed deposit with zero
founder document labor. Owns: proposal/Commercial Review assembly (three-option
structure per the playbook), price recommendation (band from `estimation.py` +
strategic lens), terms voice. Inputs: CI, estimation, production model → Outputs:
frozen Commercial Reviews, one-click acceptance → deposit invoice → paid webhook →
project. KPIs: call→proposal latency (<24h); proposal→deposit rate; realized vs.
recommended price. Escalates: any discount beyond policy; any non-standard term.
Substrate: `proposals.py`, `commercial.py`, `invoicing.py`, Stripe seam — **wire the
last mile live** (Phase-0 manual payment link until then, per
`billing-lifecycle-council.md`).

**8.8 Production Ops.** Mission: run engagements on the ratified lifecycle model so
scope never leaks silently. Owns: kickoff readiness, direction/version spine, round
ledger, Creative-Lock and conform determinations (recommend; Jon rules), court-state.
Inputs: approved Review, CI, submissions → Outputs: the workspace production view,
revision plans from timecoded feedback, the free-extra ledger. KPIs: on-time
delivery; rounds-vs-contract; margin-vs-estimate (feeds estimation priors).
Escalates: any post-lock change request (scope conversation, never absorbed); any
round starting on unconsolidated feedback. Substrate: `production.py`, `kickoff.py`,
`delivery.py` — the PRD's six "AI employees" fold in here as functions, not new heads.

**8.9 Talent Ops & Composer Relations.** Mission: a small bench of respected, promptly
paid composers under real agreements — the supply chain the rights promise stands on.
Owns: sourcing recommendations (demand-pulled: the next ~10 likely briefs), reel-queue
prep, match rankings (60/30/10 deterministic — keep), Core/Roster tiering, payout
scheduling. Inputs: `/apply`, talent sources, project needs → Outputs: signed
Composer Agreements (counsel template; assignment-primary per `LEGAL_INTELLIGENCE.md`),
rates on every assignment, the `talent_payouts` ledger (triggered on client-invoice-
**Paid**, W-9 first — exactly as the council recommended). KPIs: bench readiness for
next-10 briefs; payout latency after landed cash (target: <7 days; *this number is
the composer-side brand*); composer NPS. Escalates: any assignment without an
agreement+rate (**hard block — this is the one new machine-enforced gate this
document proposes**, because it protects the client-facing warranty). Substrate:
`talent.py`, `matching.py`, `recruiting.py` + **new**: agreements, rates, payouts.

**8.10 Delivery Ops & QA.** Mission: the delivery moment stays the best demo in the
industry, and nothing releases unproven. Owns: package assembly, certificate
generation (honest instrument, not the marketing spec), release gating
(license-confirmed + paid + rights-chain-complete), notification sends. Inputs:
approved finals, rights chain, payment state → Outputs: the clearance package, the
approval/release record, the case-study raw material. KPIs: zero client-visible
defects; approval→package latency (minutes); % deliveries with complete rights chain.
Escalates: any gap on the blocking list (Legal Ops' output). Substrate: the five
Delivery-OS agents (Rights/Revisions/Metadata/Approvals/Assets) — consolidated under
one head. **Build first: outbound email** (the reviews' #1 gap), then S3/R2 storage.

**8.11 Finance.** Mission: cash truth and the annuity. Owns: AR (deposit/balance,
branded dunning from the house scheduler — CEO tiebreak honored), AP (composer
payouts from landed cash), the renewal calendar (license expiries as dated revenue
events; the "silent renewal" chase), unit economics per engagement. Inputs: Stripe
webhooks, ledger, licenses → Outputs: cash position, per-deal P&L, renewal
pipeline. KPIs: DSO; % renewals collected; gross margin per engagement (target ≥50%
after composer share). Escalates: any balance past net-7+3; any deal priced below
margin floor. Substrate: `invoicing.py`, `payments/`, `billing-lifecycle-council.md`
decisions — plus **new**: the renewal calendar (ratified in
`production-lifecycle-model.md`, unbuilt).

**8.12 Legal Ops & Continuity (GUARD).** Mission: the rights chain is real, the
claims are honest, and the company survives its founder's bad month. Owns: the
blocking-gap list wired into the release gate (Legal Intelligence's crown jewel —
ratify and build the minimal core); claim-vs-capability audits (the spec-ahead-of-build
police: no surface may promise what the instrument doesn't deliver); backup/continuity
(DB snapshots, credential escrow, a documented "if Jon is unavailable" protocol).
Inputs: agreements, certificates, marketing copy, infra state → Outputs: the gap
list, the honesty audit, the continuity runbook. KPIs: zero unbacked claims live;
zero releases with open blocking gaps. Escalates: everything it finds — this
department only escalates. Substrate: `LEGAL_INTELLIGENCE.md` (proposal → ratify
minimal core), the honesty rule (Constitution §4.3) operationalized. Also owns
closing the **ADR-0014 hole** (reconstruct or formally re-issue the captures ADR —
the governance log must not cite a missing ruling).

**Knowledge & Learning** is deliberately not a thirteenth head: per ADR-0021 and the
CI design, learning is every department's write-back duty, audited by QA. A separate
knowledge department is where knowledge goes to die.

---

## 9. Data Architecture

Keep the spine — it is right — and finish it where it is hollow.

- **One canonical object per engagement: Campaign Intelligence** (ADR-0013/0017),
  born on the opportunity, adopted in place at Won, per-field provenance, epistemic
  kinds preserved, human edits authoritative. *Unchanged.*
- **Immutable evidence: Captures** (every input — call transcript, email, note,
  RFP — normalized to one envelope, cited by every CI field). *Unchanged; close
  ADR-0014.*
- **Rollups that compound:** CI → Agency Intelligence (buyer facts) → **Relationship
  Intelligence** (per-client, cross-campaign — ADR-0018's later phase; build it in
  Phase 2, it is the compounding step the moat depends on).
- **New first-class records (the redesign's additions), all additive-schema
  (ADR-0007):**
  1. `composer_agreements` (party, instrument type, rights conveyed, executed date,
     document ref) and `assignment_rates` — the legal floor (§8.9).
  2. `talent_payouts` ledger (assignment, amount, trigger-invoice, W-9 ref, paid
     date) — the council's design, verbatim.
  3. `licenses` as living objects (term/media/territory/expiry) + the renewal
     calendar — the annuity (§8.11).
  4. `dispositions` (already designed as Producer Learning, ADR-0021) promoted to the
     company-wide decision receipt — every queue action lands here.
  5. `time_budget` + queue state — the Chief of Staff's substrate.
- **Storage/infra debts on the trust path, ordered:** outbound mail (seam exists —
  configure and use it for delivery/review notifications), S3/R2 object storage
  (deliverables must survive deploys), Postgres cutover (ops-ready; run it before any
  client depends on uptime). All three are configuration/ops, not architecture.
- **Deletions (data that must justify itself):** the unbounded signal "seen" set and
  gig-board raw sweep get retention windows; demo seed data becomes incapable of
  contradicting live engines (regenerate from the current builders at seed time —
  the review's "demo argues against your own improvement" bug class dies
  structurally).

---

## 10. Intelligence Architecture

Three layers, each with an explicit honesty contract:

1. **Deterministic layer (the floor).** Scoring, qualification, matching, estimation,
   court-state, phase engine — same input, same output, inspectable, testable. This
   layer may *act* (compute, rank, assemble) without review because it cannot invent.
2. **Extraction layer (gated LLM).** The 10-specialist crew + recall auditor
   (ADR-0023) over every Capture; producer priors (ADR-0021) tune prompts per field.
   Contract: proposes only; every write lands `proposed`; evidence cited or the field
   stays empty ("not yet observed", never a guess — Constitution §7).
3. **Advisory layer (the department heads' voice).** Drafts, briefs, recommendations,
   rankings of the queue. Contract: every artifact traces to CI facts; cost-gated
   behind qualification and pursue (Constitution §4.5); no outward action without a
   disposition receipt.

**The learning loop, made total:** every disposition (accept/edit/reject, with the
edit diff) is labeled training data — for extraction priors today, for the
qualification/estimation models the strategy names as moat asset #1 tomorrow. The
KPI that matters: **% of company actions that produced a labeled example.** A
workflow that lets an outcome escape uncaptured is a defect (Constitution §4.6).

**Where intelligence replaces documents** (per the mandate): the proposal, brief,
Commercial Review, cue sheet, and certificate are all *renders of CI + engines*, not
authored files — this is already the ratified direction (client-workspace principle
6, ADR-0022); the redesign extends it to the case study (rendered from outcome facts
+ client permission) and the call-prep brief (rendered from dossier + relationship
card). Documents become views; the record is the asset.

---

## 11. Customer Journey

Redesigned end-to-end; each stage names its owner and what died to make it simple.

1. **Discovered** (Market/Signal Intelligence): the buyer is on the named map before
   they know Chordential exists; a signal makes today the day. *Died: waiting for
   RFPs; gig-board roulette.*
2. **Touched** (BizDev + Jon): a short, obviously-human note from Jon — one relevant
   track, one soft link to the branded first-touch page. *Died: ESP blasts (ruled
   out); founder drafting from scratch.*
3. **In conversation** (Jon, prepped): the discovery call runs the playbook arc;
   recorded → extracted → Jon confirms same-hour. The client experiences a studio
   that listens once and never asks twice. *Died: re-asking; notes rotting in an
   inbox.*
4. **Proposed** (Proposal Desk): within 24h, a three-option Commercial Review renders
   from CI on the **one durable workspace URL** the client will keep for the entire
   engagement (ADR-0018). One-click approval; the approval *is* the award trigger.
   *Died: PDF attachments; the URL that changes at the moment of commitment.*
5. **Committed**: deposit link on acceptance; 50% in; kickoff appears on the same URL
   as a concierge readiness page. *Died: invoice email archaeology; "what happens
   now?" anxiety.*
6. **In production**: the workspace answers the only client question — *whose court
   is it in, and what happens next* — plus the round ledger ("Round 2 of 3") in plain
   sight. Timecoded review on drafts; consolidated feedback starts a round. *Died:
   status-update emails; surprise scope fights (the ledger pre-empts them).*
7. **Delivered**: approve → the package assembles → everything downloadable, cue
   sheet fileable, certificate signed and honest. Balance net-7; full-res release
   gates on payment. *Died: the file-chase; the rights mystery.*
8. **Remembered** (Relationship Management + Finance): the license enters the renewal
   calendar; the relationship gets a next action; the case study renders for
   approval; the next engagement starts pre-loaded from Relationship Intelligence.
   *Died: the silent renewal; the cold restart.*

Every stage is on one URL, notified by the house's own outbound email, and the
client never sees the machinery — only a studio that is impossibly organized
(Constitution §5).

---

## 12. Composer Journey

The supply-side promise, made structural: **chosen, not bidding; respected, not
managed; paid promptly from landed cash.**

1. **Found**: demand-pulled sourcing against the next ~10 likely briefs; personalized
   invite in Jon's voice (never volume spam — the council's churn warning honored).
2. **Vetted**: one reel review by Jon (the taste gate is the brand); binary verdict,
   fast, with a respectful no.
3. **Signed**: the standing Composer Agreement executes *at onboarding, not at first
   assignment* — rights conveyance (assignment-primary), rate card, credit policy,
   payment terms (on client payment, target <7 days after landed cash), W-9 captured.
   *This single step converts the rights certificate from marketing into fact.*
4. **Matched & assigned**: deterministic ranking; Jon pushes the button; the composer
   sees the brief, the locked direction, references, and the round budget — complete
   context, no archaeology.
5. **Creating**: submissions land pending (publish gate); Jon's taste review is the
   only internal loop; client feedback arrives structured (timecoded, consolidated,
   with the revision plan), never as a forwarded email thread.
6. **Credited & paid**: cue sheet carries their writer's share (they keep it —
   `LEGAL_INTELLIGENCE.md`); payout auto-schedules on client payment; the ledger is
   visible to them. *Died: invoice-chasing; the 90-day mystery.*
7. **Growing**: Core tier = first-look priority on fitting briefs; their outcome
   history (on-time, rounds, client reactions) builds a private track record that
   earns better matches. *Died: the bench that is "a list of people we're
   disappointing" — the roster is small on purpose.*

---

## 13. Internal Operations Journey (Jon's week)

The founder's operating rhythm the whole architecture exists to protect:

- **Daily (~20 min): the Disposition Queue.** Ranked cards, one-tap actions, budget
  honest. Nothing else demands a visit.
- **2–3 selling blocks (~4 h total): prepared conversations.** Calls prepped by
  BizDev; notes captured by the meeting seam; zero logging labor.
- **One taste block (~1–2 h): reels + submissions + directions.** The creative gate,
  batched.
- **Weekly (~30 min): the honest dashboard.** Cash, pipeline truth, starved items,
  department self-reports, one number in red if the week starved revenue.
- **Monthly: the amendment hour.** ADR/Constitution rulings, price policy, target-map
  revisions — the CEO layer, deliberately rationed.

Everything else — drafting, chasing, assembling, filing, scheduling, reconciling —
is department work that surfaces only as receipts.

---

## 14. Information Flow

One direction of truth, no copies:

```
Sources (calls, emails, crawls, forms, webhooks)
   → Captures (immutable evidence)
      → Extraction crew (proposes)
         → CI fields (proposed → Jon confirms → confirmed)
            → writes back to operational columns (opportunity, project)
            → renders every artifact (brief, Review, proposal, certificate, cue sheet)
            → rolls up (Agency Intelligence → Relationship Intelligence)
   → Dispositions (every decision, with diff) → Producer Learning → better proposals
   → Outcomes (win/loss, actuals, rounds, payments) → priors (estimation, qualification)
```

Rules: a fact lives in exactly one place and is referenced everywhere (Constitution
§10); human edits are authoritative and machine never clobbers (ADR-0013);
disagreements surface as conflicts, not overwrites; every artifact a client sees is a
frozen snapshot with a live source (ADR-0017); every send/release writes a receipt.
The Disposition Queue is the only place state changes by human hand; the event logs
are the only history anyone trusts.

---

## 15. Automation Opportunities

Ranked by founder-hours returned per unit of build, honoring the machine-proposes
law throughout:

1. **The Disposition Queue itself** — collapses a dozen review surfaces into one;
   the single highest-leverage build in the company. (Mostly assembly of existing
   gates.)
2. **Outbound email, wired** — kills manual link-sharing, version notifications,
   dunning, and follow-up chases in one stroke; the seam already exists.
3. **Call → CI, live** — the meeting/capture seams are built and proven with a fake
   webhook; flipping real credentials (Zoom/Recall/Calendar) turns every discovery
   call into confirmed intelligence with near-zero founder labor.
4. **Proposal Desk end-to-end** — CI → three-option Review → acceptance → deposit
   link → paid → project, with Jon touching only "send" and any discount.
5. **Follow-up autopilot** — drafted, scheduled, queued as dispositions; the playbook
   cadence as a system. (The record: follow-up failure is named leakage.)
6. **Renewal calendar** — dated license expiries surfacing as revenue dispositions;
   pure found money.
7. **Payout autopilot** — client-paid webhook → scheduled payout disposition →
   ledger entry; the composer-brand number.
8. **Case-study renderer** — outcome facts + permission → draft study; proof
   manufacturing as a byproduct.
9. **Qualification-gate repair** — the ordered fixes (dollar-signals, collab-list
   false kills, confidence relaxation into the queue) so the top of funnel stops
   self-strangling.
10. **Claim-vs-capability audit as CI** — Legal Ops diffing live copy against shipped
    instruments on every deploy; spec-ahead-of-build caught mechanically.

Explicitly *not* automated (constitutional): sending to a human, pricing outside
policy, assignment, release, taste, and anything spending real money.

---

## 16. Revenue Optimization Opportunities

1. **Pick the service identity and sell it** (Amendment A-1) — the largest revenue
   act available is focus: every founder-hour on the Sonic Signature founding-client
   sequence until three case studies exist.
2. **The ladder, priced for ascent:** Sonic Signature ($3.5–6k, founding rate
   $2,950 honored) → :30 Spot Score ($6–12k) → Brand Anthem ($12–25k) → **Agency
   Retainer** (first-look + N engagements/quarter + priority SLA; only after
   delivery capacity is proven — the council's drowning warning stands).
3. **The annuity nobody collects:** term/territory renewals from the license
   calendar; the record calls the silent renewal named lost revenue. At maturity
   this is 10–15% of revenue at ~100% margin.
4. **Conform-vs-revision enforcement** — categorical protection from the industry's
   default margin leak ("houses that don't distinguish them give away free work
   forever").
5. **The free-extra ledger** → priced into the next Commercial Review; generosity
   becomes visible and reciprocated instead of silent and expected.
6. **Deposit discipline** (50%, non-refundable, before work) + **sequential-liability
   defense** (vendor onboarding started in parallel with the creative conversation —
   procurement paperwork gates first payment; start it at *proposal*, not award).
7. **Delegated-production margin:** bench composers at 40–50% fee share puts gross
   margin ≥50% while multiplying capacity beyond Jon's hours — the only structure
   under which $1M is arithmetic instead of fantasy.
8. **Win/loss debriefs as priced intelligence:** every loss interrogated for the
   pricing/positioning delta; estimate-vs-actual tightening the band that lets
   Chordential quote same-day (speed is a price premium in this market).

---

## 17. Competitive Moat Analysis

**What is defensible, in order of durability:**

1. **The rights-certainty position** — structural vs. AI (uncopyrightable output
   cannot be safely licensed; a procurement requirement post-USCO) and vs. libraries
   (blanket licenses die on paid spend). *Time-limited caveat:* majors licensing AI
   and the 2026 fair-use ruling could narrow the wedge; Market Intelligence owns the
   quarterly wedge-health review, and the fallback position — *provenance +
   procurement-grade delivery + relationship memory* — survives even a
   copyright-clarified AI world.
2. **The manufactured data** (strategy asset #1): labeled qualification calls,
   estimation actuals, win/loss, revision-by-segment, disposition diffs. Nobody can
   buy this; it only accrues by operating. The redesign's total learning loop (§10)
   maximizes its accrual rate.
3. **The buyer↔creator relationship graph** (strategy asset #2): Relationship
   Intelligence across campaigns + a bench with outcome histories. This is the Phase
   C seed and the reason the Core tier and prompt payouts matter beyond ethics.
4. **The delivery experience** — copyable in features, but the *trust receipts*
   (approval records, certificates, renewal history with real clients) are not.
5. **The founder's taste and credibility** — unreplicable, and the reason the org
   design protects rather than replaces him.

**What is *not* a moat and must stop pretending:** the scraper, the scoring engine,
the proposal generator — all rebuildable in weeks (the strategy says so itself). The
software is moat *infrastructure*, not moat.

**Proposed Amendment A-1 (resolves the record's open fork).** *Chordential's product
is clearance-certified original music. ChordOS is not for sale in Phase A; Phase B
(selling the software) is deferred until ≥$250k service revenue and ≥10 delivered
engagements, and will be re-evaluated then against a direct-to-Phase-C alternative —
the CMO's capped-TAM objection is preserved as a standing caution.* This amends the
A→B→C ladder's implied B-timing, not its logic: A funds everything; B must re-earn
its place.

**Proposed Amendment A-2 (the disposition budget).** *The machine-proposes law gains
an ergonomic corollary: departments may not generate more dispositions than the
declared founder time budget clears; excess defers by ranked priority, and the queue
reports what it starved.* This preserves "Jon disposes" while ending the silent
assumption that his hours are infinite.

**Proposed Amendment A-3 (the supply-side floor).** *No assignment without an
executed agreement and rate; no release with an open blocking gap on the rights
chain.* One new machine-enforced gate — justified because it protects the client
warranty, exactly as the payment gate already protects revenue (both are receipts of
promises, not creative decisions).

---

## 18. Risks

1. **The founder-capacity risk (severity: existential).** 10 conversations/week +
   flawless delivery + a day job may simply not fit. Mitigations: the time budget is
   declared and the queue enforces it; the founding sequence is *sequential* (one
   client at a time); delegation to the bench starts at deal #2, not at scale.
2. **The undelivered-guarantee risk (severity: trust-fatal).** Selling the spec's
   indemnification/safelist promises before counsel and process exist. Mitigation:
   Legal Ops' claim audit; sell the shipped instrument ("documented, original,
   delivery-ready"), not the aspiration — the honesty rule applied to marketing.
3. **The wedge-erosion risk** (AI law stabilizes): quarterly wedge review; fallback
   positioning pre-written (§17.1).
4. **The single-human risk**: continuity runbook, credential escrow, DB snapshots
   (Legal Ops/Continuity — cheap insurance, currently absent).
5. **The build-reflex risk** (the record's own diagnosis: *"procrastination
   disguised as progress"*): the roadmap below hard-caps build hours until revenue
   gates open; every cycle names its roadmap stage (build-loop charter, kept).
6. **The composer-churn risk** (over-promising income): small bench, first-look
   honesty, prompt payment as the brand; never recruit on volume promises.
7. **The infrastructure-embarrassment risk** (deploy blips, lost ZIPs, no
   notifications, during a live client engagement): the trust-path debts are
   sequenced *before* the first retainer, after the first deposit (a founding client
   at a discount tolerates scrappiness; a retainer does not).
8. **The governance-drift risk**: ADR-0014's hole shows even good governance leaks;
   Legal Ops owns log integrity henceforth.

---

## 19. Recommended Priorities

**The one metric that governs everything: signed deposits from real clients.**

1. **P0 — Sell (this week, no build):** name the 30; send the first five
   first-touches by hand; book conversations. The Phase-0 Stripe payment link
   already ratified means a deposit can be taken *today*.
2. **P0 — The legal floor (parallel, one counsel engagement):** Composer Agreement +
   license template + certificate review. Unblocks honest selling of the hero claim
   and the entire supply side. Budget item, not build item.
3. **P1 — The founder-leverage builds (weeks, not months):** Disposition Queue v1
   (assemble existing gates); outbound email wired; call→CI credentials flipped;
   Proposal Desk last mile (acceptance→deposit live).
4. **P1 — Qualification-gate repair** (the ordered fixes from the funnel audit) +
   re-aim discovery at the named-buyer map.
5. **P2 — First-delivery hardening (before client #2):** payout ledger + rates;
   S3/R2 storage; Postgres cutover; renewal calendar v1.
6. **P2 — The compounding step:** Relationship Intelligence rollup; case-study
   renderer; disposition-learning fully wired.
7. **P3 — Scale prerequisites (gated on 3 case studies + $10k/mo):** retainer offer;
   bench to 5–7; the Campaign Workspace increments *only as live engagements demand
   them* — the anti-generic-PM law holds, and so does the sell-first doctrine.

Everything not on this list — new intelligence surfaces, Phase B tooling, the
marketplace, more delivery polish — is explicitly deferred. The factory is good
enough to serve the first ten customers. Go get them.

---

## 20. Phased Roadmap — to $1M ARR under real constraints

*Arithmetic first, honestly.* At the current offer ladder, $1M/yr ≈ $83k/mo. No
version of that is solo-composed or solo-sold at 7 h/week. The model that closes:
**retainers + ladder engagements + renewals, produced by the bench, sold by Jon,
operated by the AI org.** Each phase self-funds the next (Constitution A→B→C
discipline, applied inside Phase A).

**Phase 0 — First Dollar (months 0–3). Target: 1 founding client delivered; ≥$3k
collected.**
Sell by hand from the named 30 (founding rate, case-study clause). Counsel engagement
executes the legal floor. Build only P1 founder-leverage items. Gate to Phase 1:
one delivered, paid, documented engagement + signed case-study permission.
*Failure information: if 90 days of real selling yields zero deposits, the offer or
the list is wrong — iterate the offer with call evidence before building anything.*

**Phase 1 — Repeatability (months 3–9). Target: $8–12k/mo; 3 case studies; bench
of 3 signed.**
Two engagements in flight at once (bench-produced, Jon-gated). First-delivery
hardening lands. The funnel runs re-aimed; the queue runs the week. Gate: 3
references + delivery without founder heroics.

**Phase 2 — The Machine Sells With You (months 9–18). Target: $25–40k/mo run rate.**
First agency retainer (proof of delivery capacity precedes it). Renewals begin
paying. Relationship Intelligence compounds repeat business (target: ≥40% of revenue
from repeat/renewal by month 18). Bench 5–7, Core tier live. Estimation/qualification
priors now trained on real actuals — quoting same-day with confidence bands becomes a
sales weapon.

**Phase 3 — $1M Run Rate (months 18–36). Target: $83k+/mo.**
Composition at maturity: 3–4 retainers (~$25–35k/mo) + 6–8 ladder engagements/mo
(~$40k/mo, bench-produced at ≥50% gross margin) + renewals/licensing (~$8–12k/mo).
Jon's role: relationships, taste, price — the EP of a studio that runs itself.
*Only now* re-open the Phase B question (Amendment A-1's re-evaluation), from a
position of proof: real win-rate data, real actuals, real references — the moat the
strategy always said would make B defensible, finally existing because A was run to
$1M first.

**Naturally evolving into the $20M future without designing for it:** the Relationship
Intelligence graph, the bench with outcome histories, the labeled decision corpus,
and the procurement-grade delivery record *are* the Phase C assets. Reaching $1M this
way doesn't postpone the platform vision — it manufactures the only thing that vision
was ever going to be built from.

---

*Sources: `docs/architecture/CONSTITUTION.md`, `PROJECT_STATE.md`,
`ARCHITECTURE_DECISIONS.md` (ADR-0001…0023), `CAMPAIGN_INTELLIGENCE.md`,
`LEGAL_INTELLIGENCE.md`, `EXTRACTION_ENGINE.md`, `DISCOVERY_INTELLIGENCE_LINEAGE.md`;
`docs/company-strategy.md`, `company-definition.md`, `product-roadmap.md`,
`market-research.md`, `cmo-charter.md`, `cmo-positioning-brief.md`,
`market-entry-healthcheck-council.md`, `revenue-drive-council.md`,
`billing-lifecycle-council.md`, `production-lifecycle-model.md`,
`qualification-spec.md`, `funnel-recall-audit-and-gmail-mcp-plan.md`,
`first-touch-email-council.md`, `lead-sources-research.md`,
`sonic-signature-sales-playbook.md`, `sales-discovery-playbook.html`,
`product-spec-clearance-certified.md`, `delivery-os-plan.md`,
`delivery-os-user-manual.md`, `delivery-os-agency-review.md`,
`delivery-os-agency-review-2.md`, `delivery-package-council.md`,
`campaign-workspace-prd.md`, `campaign-intake-prd.md`,
`client-workspace-principles.md`, `talent-recruiting-council.md`,
`build-loop-charter.md`, `mcp-architecture-council.md`, and the
`src/chordential_oia/` module inventory.*

*Status: proposal. Amendments A-1/A-2/A-3 await founder ratification per the
Constitution's amendment procedure. Nothing in this document modifies ratified canon
by itself.*
