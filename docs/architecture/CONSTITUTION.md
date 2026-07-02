<!--
  THE CHORDOS CONSTITUTION
  The permanent architectural source of truth for this repository.
  Read this before making any architectural, product, or design decision.

  This document is deliberately stable. It changes only by a considered amendment
  (see "Amending this Constitution" at the end), never by drive-by edit. Tactical
  guidance lives in /CLAUDE.md; the current build state lives in
  docs/architecture/PROJECT_STATE.md; binding technical rulings live in
  docs/architecture/ARCHITECTURE_DECISIONS.md. This file holds the WHY and the
  enduring principles that outlast all of them.
-->

# The ChordOS Constitution

*Ratified intent, v1 — 2026-07-02. The constitution of ChordOS: what it is, why it
exists, and the principles every future contributor (human or AI) inherits before
they change a line.*

> **If you read only one paragraph.** ChordOS is an operating system for running a
> creative-service business end to end — a business whose product is human craft and
> whose real work is *finding, winning, and delivering* bespoke creative work. Its
> first and only instance today is **Chordential**, a procurement-grade music studio.
> The software does not make the art and does not make the decisions; it makes the
> business **legible to itself and compounding over time**. The one rule under which
> everything else sits: **the machine proposes, the human disposes.**

---

## 1. What ChordOS is

**ChordOS is the operating system beneath a creative-service business.**

A creative-service business sells human judgment and human craft — music, design,
film, sound, story. That work resists systematization: every job is bespoke, the
value lives in relationships and taste, and the knowledge lives in one founder's
head. So these businesses run on scattered tools, inbox archaeology, spreadsheets,
and hustle. They lose winnable work because they hear about it too late. Their
relationships evaporate when the person who held them moves on. Their delivery is
re-improvised every time. And critically — **they never compound.** The hundredth
job is no easier to find, win, or deliver than the first.

ChordOS is the system that changes that. It is not a CRM, not a project tracker,
not a lead scraper, not an AI content generator — though it touches all of those
jobs. It is the **connective operating layer** that runs the whole arc of the work
and turns each pass through that arc into durable, reusable intelligence.

It is built as three mechanisms in one product:

1. **Intelligence** — continuously discover and understand the market (who the
   buyers are, how they work, what changed, and *why today is the day to act*).
2. **Relationship** — accumulate institutional memory (every conversation,
   preference, and outcome), so the business remembers what one person's head used
   to hold.
3. **Delivery** — produce, review, and ship the work with procurement-grade proof
   (rights, cue sheets, versioned files, approval packages).

Chordential — the clearance-certified music studio — is **instance zero**: the
proof that the pattern works, run on a real business with real money at stake.
ChordOS is the pattern; Chordential is where it is earned.

**"Frame.io meets Salesforce, for running a craft business."** Frame.io taught the
world that creative review deserved a purpose-built surface. Salesforce taught the
world that relationships deserved a system of record. ChordOS is the fusion, aimed
at the whole life of a creative engagement — from the signal that an opportunity
exists to the stems in the client's folder — with the craft and the decisions left,
always, to people.

---

## 2. Why ChordOS exists

Because a creative-service business can be *profitable* on hustle but only becomes
*durable* when it becomes a system. The founder's inbox is a bottleneck, a single
point of failure, and a moat that never widens. Three specific failures recur across
every business of this shape, and ChordOS exists to end each one:

- **Work is lost to latency.** The winnable job is heard about a day too late, or
  the quote can't be produced fast enough, or nobody knows what to charge. ChordOS
  compresses "scan twenty sources" into "decide on five ready briefs."
- **Relationships live in one head.** When the knowledge of *who buys what, from
  whom, at what price, how often* lives only in memory, it cannot be leveraged,
  handed off, or compounded. ChordOS makes it a system of record with a memory.
- **The business never learns from itself.** Every won and lost deal, every
  estimate-vs-actual, every revision count is intelligence — and in the normal
  business it evaporates the moment the job ships. ChordOS captures it and feeds it
  back, so the operation gets sharper every cycle.

The deeper reason: **the durable asset was never the software features — it is the
proprietary intelligence the software manufactures by operating.** Anyone can build
a scraper or an AI drafter in a weekend. Nobody else has this business's labeled
qualification calls, its estimation actuals, its win/loss record, or its
buyer↔creator graph. ChordOS exists to manufacture and compound that asset as a
*byproduct of doing the work* — not as a thing to be funded separately.

---

## 3. Long-term vision

**Near term:** ChordOS makes Chordential the sharpest small music studio in its
market — winning more of the work it should win, remembering every relationship, and
delivering with proof that reads as procurement-grade to an agency buyer.

**Medium term:** ChordOS becomes the intelligence-and-operations layer that other
under-tooled creative shops run their business on — the same spine, exposed to
operators beyond Chordential itself.

**Long term:** ChordOS becomes the **operating layer between creative demand and
creative supply** — the graph across which buyers find vetted creators and get work
cleared, delivered, and documented. This is the endgame where the network, not any
single studio, is the product.

**The generalization is earned, never assumed.** The vision is expansive, but the
discipline is strict: *prove the pattern on Chordential before generalizing it, and
generalize only what is genuinely general.* A capability graduates from "Chordential
feature" to "ChordOS primitive" only after it has paid its way running a real
business. The music domain is not a limitation to escape — it is the crucible in
which the OS is forged honest.

The three-phase ladder that encodes this (ratified strategy): **A → B → C.**

- **A — Studio force-multiplier (now).** ChordOS runs Chordential's own studio.
  This is not "a studio with a lead tool bolted on"; it is *deliberate data
  manufacturing*. Every dogfooded job produces the proprietary data that makes the
  next phase defensible.
- **B — Procurement-intelligence platform.** The same spine, sold to other creative
  shops, priced against a single won deal.
- **C — Procurement OS / marketplace.** The buyer↔creator graph as an operating and
  clearing layer, monetized on facilitated value.

Each rung self-funds the next. We do not skip A to chase C's optics.

---

## 4. Operating philosophy

These are the load-bearing beliefs. They are older than any feature and they win
any argument a feature tries to have with them.

1. **The machine proposes, the human disposes.** This is the first law. Engines
   analyze, rank, draft, and recommend. A *human* presses every decision button —
   qualify, assign, approve, publish, release, send. Nothing that commits the
   business to an outcome, spends real money, or reaches a real person happens
   without a human hand on it. Automation that decides is a bug, not a feature.

2. **Dogfood first.** The first customer is always Chordential's own studio. A
   capability must raise Chordential's real win rate, save real time, or reduce real
   risk *before* it is generalized or sold. Internal-first is how we keep the product
   honest — we feel every defect ourselves.

3. **Honesty is a hard constraint, not a value statement.** Never imply real client
   work that didn't happen. Never fabricate a capability, a credit, a profile, or a
   metric. Demos use invented brands (AURORA, Vance Athletic), never real trademarks.
   Numbers shown are live from the database or explicitly labeled as demo. When
   something can't be done well, we defer it and say so — we do not fake it. This
   protects the one asset a procurement-grade business cannot rebuild: trust.

4. **Precision over recall, at the moment of action.** Retain everything (full recall
   in the database), but *act* only on what is high-confidence and on-craft. One
   false alert on junk destroys more trust than ten missed long-shots. The system is
   allowed to know about everything and allowed to bother a human about very little.

5. **Capital discipline is architecture.** The default posture is lean and
   self-funded. Every operating dollar — LLM spend above all — must justify itself
   against won revenue. Expensive generation is gated behind qualification and a
   human "pursue." Cost control is not ops hygiene; it is a design constraint that
   shapes the pipeline.

6. **The loop must close.** Win/loss capture, estimate-vs-actual, and outcome
   write-back are mandatory, not optional. A workflow that lets a human skip the
   capture step is broken, because the captured outcome *is* the moat. An open loop
   is a business that forgets.

7. **Volume is never a success metric.** Leads surfaced and opportunities ingested
   are inputs, not results. Success is qualified, won, delivered, remembered.

---

## 5. Primary users

ChordOS is a multi-sided system. Today three human roles matter; two more arrive
with Phases B and C.

- **The Operator / Managing Director** (today: Jon). The spine's decision-maker. Runs
  the business through ChordOS: reads the intelligence, disposes what the machine
  proposes, signs the talent, releases the work. Every "decision button" in the
  product belongs to this user. In Phase B, this becomes *any* creative-shop operator.
- **The Client / Buyer** (an agency producer, brand team, or creative director).
  Experiences ChordOS through token-gated, procurement-grade surfaces: a first-touch
  page, a review portal with timecoded feedback, a delivery room with cue sheets and
  rights. They never see the internal machinery; they see a studio that is
  impossibly organized. In Phase C, the buyer becomes a first-class platform user.
- **The Creator / Talent** (a composer, sound designer, mix engineer). Experiences
  ChordOS through a token-gated creator portal: their briefs, their submissions,
  the client's feedback, their credit and payment. Chosen, not bidding. Treated with
  respect and paid promptly — a constitutional promise to the supply side.

The **honesty rule and the machine-proposes rule apply identically to every user
surface.** A client must never be shown unvetted work as if it were approved; a
creator must never be auto-assigned; a buyer must never be told a capability exists
that doesn't.

---

## 6. Core business capabilities

The capabilities are organized as the **mission spine** (the deterministic verbs
that run the business) composed into the **three mechanisms** (the product's faces).

**The mission spine (demand side):**
`Identify → Rank → Qualify → Estimate → Prepare → Outreach → Win/Loss`
**The mission spine (supply side):**
`Recruit → Match → Assign → Produce → Review → Deliver`

**Mechanism 1 — Intelligence** *(who are they, how do they work, why now)*
- **Agency Intelligence** — living profiles of the buyer landscape (services,
  leadership, awards, portfolio, decision-makers, production style).
- **Company Intelligence** — structured "how they work" dossiers (campaign types,
  creative strengths, production complexity, buying tendencies, observed music use).
- **Signal Detection** — meaningful *change* over time (new campaigns, hires, awards,
  leadership moves, client wins), stored as structured evidence.
- **Opportunity reasoning** — the synthesis: *why is today the best day to contact
  this agency?* — combining intelligence, signals, decision-makers, and history.

**Mechanism 2 — Relationship** *(institutional memory + the outreach it drives)*
- **Relationship platform** — every note, conversation, preference, and outcome per
  agency; the business's memory.
- **Outreach strategy + content** — should we reach out, why now, to whom, with what
  objective and talking point; then the evidence-built emails, briefs, and follow-ups.
- **Continuity** — after outreach, recommend the next best action from what changed.

**Mechanism 3 — Delivery** *(produce and ship with proof)*
- **Production** — creative strategy, composition, arrangement, mix, master, stems,
  campaign versions — all human-made.
- **Review** — timecoded client feedback on the work; revisions; approvals — the
  Frame.io mechanic, for sound.
- **Delivery** — cue sheets, rights summaries, enforced version naming, folder
  organization, approval packages, rollout matrices. Operational clarity as the
  deliverable.

Underneath all three, always accruing: the **proprietary data flywheel** —
qualification labels, estimation actuals, win/loss outcomes, revision-by-segment, and
the buyer↔creator graph. *This* is what ChordOS is really building. The features are
how it gets built.

---

## 7. Design principles

- **Procurement-grade, always.** Every client-facing artifact must read as though it
  came from a company ten times the size. The paperwork is the product's handshake.
- **Evidence first.** Every claim the system makes cites its source. Intelligence
  shows the URL and date it was observed; a generated email footnotes the fact it was
  built from; an empty field says "not yet observed," never a guess.
- **Two moods, one system.** A daylight front-of-house (the public, procurement-grade
  studio) and an ink control-room platform (the internal operating surface), drawn
  from one palette. Monospace for data and evidence — instrumentation, not marketing.
- **Motion serves meaning.** Small, purposeful motion (a reveal, a waveform pulse, a
  live demo). Never decoration. Respect `prefers-reduced-motion`.
- **The client remembers the surface, not the software.** The delivery room, the
  review portal, and the first-touch page are where trust is won — they deserve the
  most craft.
- **A quality floor, unannounced.** Responsive to mobile, visible keyboard focus,
  reduced motion honored, no console errors on a client page. These are table stakes,
  not features.

---

## 8. AI philosophy

ChordOS is an AI-*assisted* operating system, not an AI-*operated* one. The
distinction is constitutional.

- **AI proposes, organizes, documents, and drafts. It never decides and never
  fabricates.** It ranks opportunities; a human pursues. It drafts an email; a human
  sends. It suggests a match; a human assigns. It assembles a document; a human
  releases.
- **No AI-generated craft.** The music — and any core creative deliverable ChordOS
  ever ships — is human-made. ChordOS organizes, documents, packages, and delivers the
  craft; it does not synthesize it. AI may *assist ideation*; it never *is* the
  artist. Say so honestly in the copy.
- **Deterministic engines first; targeted LLM calls where they earn it.** The spine
  is deterministic and inspectable — same input, same output, no black box on the
  critical path. LLMs are used for discrete, cacheable, gated steps (normalize messy
  text, draft from evidence), never an open-ended agent swarm in production, and never
  before a human "pursue" spends real money.
- **Evidence over generation.** A generated artifact must trace to real data. The
  system's credibility comes from what it *knows*, not from what it can *say*.
- **Gated by human and by cost.** Every expensive or outward-facing AI action sits
  behind the machine-proposes rule and the capital-discipline rule simultaneously.

---

## 9. Product philosophy

- **The product is the operating system, not a bag of features.** Coherence beats
  surface area. A new capability must connect the spine, not decorate it. If it maps
  to no stage of the mission spine, it is out of scope until the spine is updated to
  include it.
- **Internal-first, then earned outward.** Ship to Chordential, feel the defects,
  then generalize. The roadmap is two-sided (demand then supply) and phase-gated
  (A→B→C); every build names the stage it advances.
- **Compression is the felt value.** The user's experience of ChordOS is *less* —
  fewer tabs, fewer decisions carried in the head, fewer things re-improvised. The
  win is turning "manage the music" into "manage the campaign; the music is handled."
- **Close the loop, always.** The product exists to make the business compound.
  Every surface either captures intelligence or spends it; a surface that does
  neither is dead weight.
- **The customer promise is load-bearing copy.** *"Chordential removes the work of
  managing music so agencies can stay focused on managing the campaign."* Every
  Delivery surface must actually deliver on it, not just print it.

---

## 10. Architectural principles

These are the enduring technical commitments. Specific rulings and their rationale
live in `ARCHITECTURE_DECISIONS.md`; this section states the principles those
rulings serve.

- **Deterministic engines, no hidden state.** The business logic is pure Python
  engines that compose the mission spine — analyzable, testable, cacheable. The web
  layer adds *no* scoring or decision logic of its own; it renders and routes.
- **Provider seams, null by default.** Anything that touches the outside world —
  payments, mail, push, storage, LLM — is a seam with a no-op default and a real
  implementation selected by environment. The product runs end-to-end with zero
  credentials; production lights up the seams. A seam never raises or blocks.
- **Fail-soft at every boundary.** A broken crawl, a hostile page, a dead provider, a
  slow network — none may take down startup or the rest of the app. Hostile work runs
  in killable, out-of-process workers so a runaway can never freeze the server.
- **Migration-safe, additive schema.** Schema evolves by additive column migrations;
  old databases upgrade without data loss. The storage layer is backend-portable
  (SQLite for dev/tests, Postgres for production behind the same interface).
- **One source of truth per fact.** Legally- and operationally-material copy, config,
  and constants have exactly one home and are referenced everywhere. Duplication that
  can drift is a defect — especially where a client-facing artifact could diverge
  from what a client approved.
- **Token-gated public surfaces.** Client and creator surfaces are reached by an
  unguessable per-record token validated in the route — never by a shared login. The
  internal admin gate and the public token surfaces are separate, and must never
  drift out of sync.
- **The stdlib core is guaranteed.** Anything that must always work (the delivery
  package builders) depends only on the standard library, so it builds even when
  optional extras are absent.
- **Human gates are enforced by the flow, not by convention.** "Machine proposes,
  human disposes" is wired into the routes (a strategy must be approved before the
  composer unlocks; a creator submission is pending until published), not left to
  discipline.

---

## 11. Future direction

The horizon, held loosely — direction, not commitment. Current build state lives in
`PROJECT_STATE.md`; this is where the OS is *heading*.

- **Zero-downtime operation.** Complete the SQLite→Postgres cutover so every deploy is
  seamless — the foundation for a platform other people depend on.
- **The three-mechanism platform UI.** Realize `platform-website-plan.md`: the
  control-room theme, the Why-Today queue, the Strategy Card that gates outreach, the
  `/today` continuity queue, and timecoded review as the flagship surface — the
  Intelligence / Relationship / Delivery mechanisms made tangible.
- **Phase B multi-operator.** Expose the spine to a second operator: real accounts,
  tenancy, and the discipline of a product used by someone who isn't us.
- **Phase C buyer-side graph.** Turn the buyer↔creator relationship graph into an
  operating and clearing layer — the marketplace endgame.
- **Generalization beyond music — only when earned.** The spine (Intelligence →
  Relationship → Delivery) is domain-shaped, not music-specific. If and when the
  pattern is proven, ChordOS becomes the OS for other creative-service verticals. Not
  before the music instance has earned the right to generalize.

Every one of these is subject to the same tests as everything else: *does it
accumulate proprietary intelligence or relationships? does it keep the human on the
decision? can we operate it honestly?*

---

## How to use this Constitution

- **Read it before you make an architectural, product, or design decision** — not to
  quote it, but to inherit the reasoning behind the code you're about to touch.
- **When a choice is ambiguous, this document is the tiebreaker.** If a feature and a
  principle conflict, the principle wins; if two principles seem to conflict, the
  earlier-numbered operating-philosophy law wins.
- **It is not the tactical guide.** For commands, conventions, branch discipline, and
  env flags, read `/CLAUDE.md`. For what's built right now, read `PROJECT_STATE.md`.
  For *why a specific technical decision was made*, read `ARCHITECTURE_DECISIONS.md`.

## Amending this Constitution

This document is meant to be stable — it should change a few times a year, not a few
times a sprint. Amend it only when the *nature* of ChordOS changes (a new phase, a
new user class, a reversal of a load-bearing belief). An amendment:

1. States what changed and why, dated, in the amendments log below.
2. Is a deliberate, reviewed decision — never a drive-by edit folded into a feature.
3. If it reverses a ratified strategic decision, cites that decision and the
   authority for the reversal (the CEO ruling), mirroring the pattern already used in
   `company-strategy.md`.

Tactics change constantly; principles change rarely; the reasons change almost never.
Keep them in that order.

### Amendments log
- **v1 — 2026-07-02.** Initial ratification. Establishes ChordOS as the operating
  system beneath a creative-service business, with Chordential as instance zero;
  codifies the machine-proposes rule, dogfood-first, the honesty constraint, the
  three mechanisms, and the A→B→C horizon. Synthesized from the ratified record in
  `docs/company-strategy.md`, `docs/company-definition.md`, `docs/product-roadmap.md`,
  `docs/build-loop-charter.md`, and `docs/platform-website-plan.md`.
