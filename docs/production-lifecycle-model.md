# The Production Lifecycle of a Commercial Music Engagement

*The business model behind the Production OS — mapped before any software is designed
(operator directive, 2026-07-08). Voice: an Executive Producer at a world-class music house.
Companion to ADR-0018 and `docs/client-workspace-principles.md`. Nothing here is a feature
spec; when we agree on this model, the software gets designed around it.*

---

## 0. The shape of the work (read this first)

From Kickoff to release, a commercial music engagement is **two tracks running in parallel
that must converge at delivery**:

- **The Creative Track** — translate the brief → write → present → revise → lock → produce →
  mix → version. Its currency is *versions* and *feedback*; its rhythm is the *round*.
- **The Business Track** — composer agreements, clearance, license terms, union paper, cue
  sheets, invoicing. Its currency is *signatures and registrations*; its rhythm is *gates*.

The creative track gets all the attention; the business track is where lawsuits, lost backend
royalties, and unpaid invoices live. A world-class house is distinguished less by its demos
than by the fact that **both tracks arrive at delivery on the same day, complete**.

Three structural truths shape everything below:

1. **Music is subordinate to picture.** The spot's edit (the "cut") is an external, *moving*
   dependency owned by someone else (the editor/post house). Music is written to picture,
   timed to picture, and re-conformed when picture changes. Half of all production pain is
   downstream of a picture change. A *conform* (adjust to a new cut) is categorically
   different from a *revision* (creative change) — houses that don't distinguish them give
   away free work forever.
2. **The client approves a direction, then a version, then a mix — never "the music."**
   Approval is staged and cumulative, and each stage narrows what may still change. The
   pivotal gate is **Creative Lock**: after it, melody/structure/arrangement are frozen and
   any change is a scope conversation, not a revision.
3. **Delivery is not the end.** The license has a term, media, and territory. Term expiry and
   usage expansion are *revenue events* with dates. The archive plus the renewal calendar is
   the annuity most small houses forget to collect.

---

## 1. The phase map

### Phase A — Internal Kickoff & Creative Translation
*The client's kickoff said "everything is under control." This is where we make that true.*

- **The work:** The EP/producer translate the approved brief into a creative plan: 2–3
  distinct musical *territories* (directions) worth demoing; who writes (one composer, or a
  bake-off of several); the production schedule computed backward from the air date; and the
  picture question — is there an edit or animatic, at what duration, and is it locked?
- **Stakeholders:** EP, producer/coordinator, composer(s). (Client is absent — this is the
  house's room.)
- **Decisions:** territory selection · composer casting (single vs. bake-off) · live vs.
  programmed instrumentation (drives budget + schedule) · union vs. non-union posture.
- **Gate:** *Creative plan set* (internal).
- **Assets created:** internal creative brief (the translation of the client brief into
  musician language) · reference/tone set · production schedule · composer assignment(s).
- **Risks:** mistranslating the brief (everything downstream inherits the error) ·
  over-scoping directions (burning demo budget) · no picture yet (writing blind) · air date
  math that doesn't close.
- **Dependencies:** the approved Commercial Review (scope/rounds/term) · picture/animatic
  from post · composer availability.

### Phase B — Sketch & Demo Development
*The writing room. The client never sees 80% of what happens here — that's the point.*

- **The work:** Composers write demos per territory, to picture where it exists. Then the
  house's **internal taste gate**: the EP/producer review everything *before the client sees
  anything*, kill weak directions, tighten the survivors, and decide what is
  presentation-worthy. This invisible curation IS the house's reputation.
- **Stakeholders:** composers, EP, producer.
- **Decisions:** which demos survive · whether a territory needs a re-write before showing ·
  sequencing (which demo plays first — presentation order is persuasion).
- **Gate:** *Presentation-worthy* (internal — the taste gate).
- **Assets:** demo v1 per territory · internal review notes · the presentation sequence.
- **Risks:** demos converging (three directions that all sound alike) · composer slippage ·
  unpaid demo cost exposure (demos are usually absorbed by the house — a real COGS risk on
  spec-heavy clients).
- **Intelligence:** which composers deliver on-brief first pass (talent intelligence) ·
  demo-cost-per-win by client (commercial intelligence).

### Phase C — The First Presentation
*A staged event, not a file drop. Demos are performed — played against picture, framed with
rationale — because unframed music gets judged as taste, framed music gets judged as strategy.*

- **The work:** Present 2–3 directions against picture, each with a one-breath frame ("this
  one leans wonder; this one leans confidence"). Capture *exactly* what was said, by whom.
- **Stakeholders:** agency CD + agency producer (always) · brand marketer (sometimes — and
  whether brand is in this room or not is the single best predictor of late-stage surprises).
- **Decisions (client):** pick a direction · hybrid two · re-demo · (rare) kill.
- **Gate:** **Direction Selected** — the first client-facing creative gate.
- **Assets:** the presentation package (demos-against-picture + frames) · the feedback record
  (verbatim, attributed).
- **Risks:** no decision (stall — schedule eats itself) · "one more direction?" (scope) ·
  brand absent → second-hand feedback arrives days later and contradicts the room ·
  the *silent stakeholder* (someone not in the room holds the real veto).
- **Intelligence:** the client's reference vocabulary · who actually decided vs. who spoke
  most · time-to-decision.

### Phase D — Revision Cycles → Creative Lock
*The loop that defines the relationship. Feedback → interpretation → new version → re-present.*

- **The work:** Each round: receive feedback (often ambiguous — "can it feel more premium?"),
  **interpret** it into concrete musical moves (tempo? arrangement density? instrumentation?
  mix brightness?), produce the next version, re-present. The interpretation step is the
  craft; getting it right in one round is what clients pay houses for.
- **Stakeholders:** agency CD/producer (feedback) · composer + producer (interpretation) ·
  increasingly the brand as stakes rise.
- **Decisions:** per round — does the client accept, or go again? Internally — does this
  feedback *mean* what it says? Does this round **count** against the included rounds
  (contractual)? Is this note a *revision* or a *conform* (picture changed) or a *scope
  change* (new direction)?
- **Gate:** **Creative Lock** — melody, structure, arrangement approved. The single most
  important gate in the lifecycle: it converts future changes into scope conversations and
  authorizes real production spend (players, studio, vocalist).
- **Assets:** version chain v2…vN · attributed, timecoded feedback per version · conform
  versions (tied to cut IDs, not creative rounds) · the round ledger against the included
  count.
- **Risks:** ambiguous feedback misread (burns a round + trust) · **stakeholder
  proliferation** (a new voice — usually brand-side — enters at round 3 and relitigates the
  direction) · picture re-cuts mid-round (sync points invalidated) · round-count disputes ·
  death by a thousand tiny notes.
- **Dependencies:** *picture lock* (the biggest) · feedback consolidation (ONE thread, not
  four emails and a text).
- **Intelligence:** the client's **feedback dictionary** ("more energy" = tempo for this CD,
  arrangement for that one) · typical rounds-to-lock · whether their "final" picture ever is.

### Phase E — Production & Record
*Making it real. For a composer-produced track this phase is a day; for live players and a
vocalist it's a project inside the project.*

- **The work:** Book studio/players/vocalist(s); casting the **vocalist often needs its own
  client approval** (send 2–3 voices, client picks); run sessions; comp takes; union paper if
  union (AFM/SAG-AFTRA session reports, contractor, payroll house).
- **Stakeholders:** session musicians, vocalists, studio, engineer, union contractor/payroll —
  plus the client for voice casting.
- **Decisions:** casting (client-facing) · live/programmed finalization · session plan.
- **Gate:** *Record complete* (internal) · *Vocalist approved* (client, when applicable).
- **Assets:** session recordings + comps · talent agreements · union session reports ·
  session docs for the archive (re-use value at renewal).
- **Risks:** talent availability vs. air date · vocalist rejected after the session · session
  overruns (real money, already committed) · union/non-union mismatch with the media buy.
- **Dependencies:** Creative Lock (never spend on players pre-lock) · deposit received.

### Phase F — Mix, Versions & Conform
*Finishing. Where "the track" becomes "the deliverables."*

- **The work:** Final mix against FINAL picture; a small mix-notes round; loudness/spec
  mastering per medium (broadcast/streaming/social have different targets); then the version
  family — cutdowns (:30/:15/:06), verticals, lifts, instrumental, and the stem package cut
  to the *post house's* preferred splits.
- **Stakeholders:** mix engineer, composer, agency/post (mix notes) · the spot's audio-post
  mixer (a DIFFERENT person who will re-balance music under VO — deliver stems they can use).
- **Decisions:** mix approval (client) · stem split spec (post) · version list finalization
  (against the Commercial Review's deliverables).
- **Gates:** **Mix Approved** → **Masters Approved**.
- **Assets:** final master · alt mixes · the cutdown/vertical family · stems · instrumentals.
- **Risks:** spec surprises at the end (stem splits, sample rates, loudness) · late VO/edit
  changes ("final" picture v3) · the version list quietly growing past scope.
- **Dependencies:** final picture + VO from post · delivery specs (get them at KICKOFF, not
  at delivery — almost nobody does; it's free excellence).

### Phase G — Clearance & Business Affairs *(parallel track, converges here)*
*Started at kickoff, finishes before delivery. Invisible when done right; existential when not.*

- **The work:** composer/writer agreements (WFH or license + splits) · sample/interpolation
  audit (should be "none," must be *verified* none) · soundalike risk review when the brief
  said "like [famous track]" (the industry's lawsuit magnet) · the license itself — term,
  media, territory, exclusivity — matched to what the client actually bought · cue sheet ·
  PRO registration (broadcast backend is real money) · union payroll finalization.
- **Stakeholders:** house BA/EP · agency business affairs · brand legal (sometimes) · PROs.
- **Gate:** **Rights Cleared / License Executed** — delivery must not happen without it.
- **Assets:** executed license/WFH · rights certificate · cue sheet · publishing splits ·
  registration confirmations.
- **Risks:** soundalike claim · usage exceeding licensed term/media (client runs the :06 on
  TV when they licensed digital) · unregistered cues (backend silently forfeited) · splits
  disputes with co-writers.
- **Intelligence:** the client's standard term/media appetite (informs future pricing) ·
  their BA's turnaround speed.

### Phase H — Delivery & Acceptance
*The package, the manifest, the receipt.*

- **The work:** assemble the delivery package (masters, version family, stems, instrumentals,
  cue sheet, rights certificate, metadata/naming to spec); deliver via the workspace; get
  explicit acceptance; final invoice; **full-resolution release gated on payment** (already
  ChordOS law).
- **Gate:** **Client Acceptance** · **Balance Received**.
- **Assets:** the delivery package + manifest · acceptance record · final invoice/receipt.
- **Risks:** the 11pm stem emergency (post discovers a missing split on mix night — have a
  same-day escalation lane) · PO/invoice mismatch stalling payment · "accepted" implicitly
  but never explicitly (kills the warranty/renewal clock).

### Phase I — Archive, Backend & the Relationship Tail
*Where the engagement compounds — or evaporates.*

- **The work:** archive sessions + stems + masters (re-use at renewal is high-margin) ·
  **renewal calendar**: license term expiry is a dated revenue event; usage-expansion
  requests (new media/territory) are priced events · PRO royalty tracking · the post-mortem:
  what did we learn about this client → Relationship Intelligence · the case-study/reel asset.
- **Gate:** *Post-mortem done; renewal calendar armed* (internal).
- **Assets:** archive · renewal calendar entries · post-mortem record · reel candidate.
- **Risks:** the silent renewal (client keeps running the spot past term — lost revenue AND
  a compliance conversation nobody wants cold) · archive rot (can't find stems in 18 months).

---

## 2. The stakeholder census (and the approval truth)

| Side | Role | What they actually control |
|---|---|---|
| Brand | CMO / brand manager | The *real* veto, often exercised late and second-hand |
| Brand | Brand legal | Clearance posture, soundalike tolerance |
| Agency | Creative Director | Direction selection; the taste authority |
| Agency | Agency producer | Process, schedule, round-counting, the money |
| Agency | Music supervisor (if any) | Reference vocabulary, shortlist gatekeeping |
| Agency | Business affairs | License execution |
| Post | Editor / post producer | **Picture — the master dependency** |
| Post | Audio-post mixer | Stem spec; how the music actually airs |
| House | EP | Taste gate, scope defense, escalation |
| House | Producer/coordinator | The two-track convergence; the schedule |
| House | Composer(s)/arrangers | The work |
| House | Musicians/vocalists | Sessions (union implications) |
| House | Mix/mastering | Finishing |
| Third | Union contractor/payroll, PROs, studios | Paper + backend |

**The approval truth:** the *presented-to* approver (agency producer) is rarely the *real*
approver (CD, or brand). Every engagement has a de-jure and a de-facto approval chain, and
learning a client's real chain is among the most valuable Relationship Intelligence there is.

---

## 3. The gates, in one list

Internal: creative plan set → presentation-worthy (taste gate) → record complete →
post-mortem done.
Client-facing: **Direction Selected → (rounds) → Creative Lock → Vocalist Approved (when
applicable) → Mix Approved → Masters Approved → Acceptance**.
Business: deposit received (pre-spend) → rights cleared/license executed (pre-delivery) →
balance received (pre-release).

Creative Lock is the hinge of the whole lifecycle: it ends the revision economy, starts the
production-spend economy, and defines what "in scope" means forever after.

---

## 4. Asset genealogy (everything that gets made)

brief translation → territories → demos(v1…) → presentation package → feedback records →
versions(v2…vN) + conforms(per cut) → locked track → session assets (recordings, comps,
agreements, union paper) → mix(es) → masters → version family (cutdowns/verticals/lifts/
instrumentals) → stems → cue sheet → rights certificate → license → delivery package +
manifest → acceptance record → invoice/receipt → archive → renewal calendar entries →
post-mortem.

Every asset above is either **presented** (needs framing + a decision), **executed** (needs
signatures), or **delivered** (needs spec + manifest). That three-way split matters more than
file type.

---

## 5. The risk register (the ones that actually happen)

1. **Picture changes after Creative Lock** — the #1 recurring fight. Defense: the
   conform-vs-revision distinction, in writing, at Commercial Review.
2. **Stakeholder proliferation** — the round-3 brand veto. Defense: ask at kickoff "who else
   sees this before final?" and put the answer in the plan.
3. **Ambiguous feedback misread** — burns rounds and trust. Defense: the feedback dictionary
   (RI) + restating interpretation before executing ("we heard X, we'll do Y — confirm").
4. **Soundalike exposure** — "make it feel like [hit song]" is a plaintiff's exhibit.
   Defense: reference-distance review at the taste gate; never in writing say "copy."
5. **Spec surprise at delivery** — stems/loudness/naming. Defense: collect delivery specs at
   kickoff (it's a kickoff checklist line, not a delivery scramble).
6. **Round-count drift** — free work by inattention. Defense: the round ledger, visible to
   both sides.
7. **Silent renewal** — spot runs past term. Defense: the renewal calendar with dates armed
   at delivery.
8. **Union/media mismatch** — non-union session under a broadcast buy. Defense: posture
   decision at Phase A, tied to the media plan in CI.
9. **Talent unavailability against air date** — defense: casting held until lock, but
   *scouted* from kickoff.
10. **Payment stall on PO mechanics** — defense: procurement capture (Phase 5 of the
    commercial OS) done before delivery week.

---

## 6. Dependency map

- **Picture lock** → gates writing-to-time, mix, versions, conforms. (External, volatile.)
- **Delivery specs** (stems/loudness/naming) → gates Phase F; should be captured at kickoff.
- **Creative Lock** → gates production spend (Phase E).
- **Deposit** → gates any real spend; **Balance** → gates full-res release.
- **Rights cleared** → gates delivery.
- **VO stems from post** → gates final mix.
- **Media plan** (from CI) → drives union posture + license scope.
- **Composer/talent availability** → drives the whole calendar backward from air date.

---

## 7. What becomes Campaign Intelligence vs. Relationship Intelligence

**Campaign-scoped (CI — this engagement):** chosen territory + why · the version chain + per-
version feedback (attributed, verbatim) · round ledger state · picture-cut history · casting
decisions · mix notes · delivery specs · license terms as executed · acceptance + dates ·
every gate's timestamp.

**Client-scoped, durable (RI — compounds across campaigns):**
- the **feedback dictionary** (their words → the musical move that satisfied them)
- the **real approval chain** (de facto vs. de jure; does brand appear late?)
- rounds-to-lock norm · decision latency · picture-stability track record
- reference vocabulary and taste map · vocalist/genre preferences
- delivery-spec preferences (their post house's stem splits — reusable verbatim)
- standard term/media appetite → future pricing posture
- payment behavior (PO mechanics, days-to-pay)
- renewal calendar + usage-expansion history (the annuity)
- composer↔client chemistry (which writer lands with this CD first-pass)

---

## 8. The abstractions we're missing (named, not designed)

1. **The Presentation** — a staged event with framing and a captured decision; not a file
   upload. First-class moments: demos presented, revisions re-presented, casting presented.
2. **The Round** — feedback + interpretation + response as one countable unit with
   contractual meaning (the included-rounds ledger).
3. **Creative Lock** — a real gate between "revising" and "producing," with economic
   consequences on both sides of it. Today the OS has approval only at delivery review.
4. **Conform vs. Revision** — changes caused by *picture* are a different species from
   changes caused by *taste*, and only one of them is scope-bearing.
5. **The Taste Gate** — internal presentation-worthiness review; the house sees everything,
   the client sees the survivors.
6. **The Two Tracks** — creative and business as parallel lanes with a convergence gate at
   delivery; today rights are a delivery-time document rather than a lane that started at
   kickoff.
7. **The License as a living object** — term/media/territory with expiry dates that generate
   renewal revenue events. Delivery arms a calendar; it doesn't close a file.
8. **Feedback as intelligence** — verbatim, attributed, mapped to the change that resolved
   it; the raw material of the feedback dictionary and the next campaign's head start.
9. **The Version chain as the spine** — the atomic unit of production isn't the milestone or
   the task; it's the version, with its feedback, its round, its cut-ID, and its gate.
10. **The Renewal Calendar** — dated future revenue born at delivery; the compounding tail.

---

## 9. Ratified production principles (operator, 2026-07-08)

1. **ChordOS is not project management software.** It removes uncertainty for agencies; it
   does not manage tasks. Every screen must answer: *"what uncertainty did we remove?"* The
   client feels things simply becoming true.
2. **Production revolves around Versions, not tasks.** The Version is the atomic unit;
   Presentation, Feedback, Decision, Round, Approval, Conform, and Creative Lock all attach
   to it. The system keeps the history of creative thinking, not a task list.
3. **Direction is a first-class object** above the Version chain: a campaign explores
   Directions; each carries its own versions and its own fate — and a rejected Direction
   records *why* (rejection reasons feed the feedback dictionary).
4. **Relationship Intelligence explains the client; Campaign Intelligence explains the
   project.** Rounds-to-lock norms, the real approver, the feedback dictionary, composer
   chemistry, delivery/payment/procurement/renewal history — every new engagement begins
   already knowing how this client likes to work.
5. **The client never thinks about software.** They progress through a relationship, not an
   application. Every page reads "someone already thought of this," never "complete step 4."

## 10. Second pass — what still lived only in the EP's head

*The audit of 2026-07-08: tacit knowledge identified for the model, in three families.*

**A. The state the EP always knows (uncertainty machinery)**
1. **Whose court is the ball in** — every engagement, at every instant, is exactly one of
   *we-owe-them / they-owe-us / nothing-until-a-scheduled-date*, each with an AGE. The EP's
   entire mental dashboard; the operational form of "what uncertainty did we remove."
2. **The two calendars** — the published (client-facing, padded) schedule vs. the real
   (internal, buffered) one. Buffer burn-down — not milestone status — is schedule health.
3. **The chase protocol** — client silence is a STATE with an age and an escalation ladder,
   tone-calibrated per client. Silence-watching is machine work currently done by anxiety.

**B. The judgment calls (decision points the first pass missed)**
4. **Defend or comply** — feedback triage is three-way: take literally / interpret / push
   back ("protecting the work"). The pushback is a decision point with relationship stakes;
   its outcome is high-grade RI.
5. **The reconciliation demand** — conflicting stakeholder notes do not start a round; the
   round clock starts at CONSOLIDATED notes. Near-contractual; belongs in Terms language.
6. **Fidelity calibration** — how finished a version should SOUND for this client at this
   stage (too polished invites premature mix notes; too rough invites misjudgment). Per-
   client RI dial.
7. **Presentation strategy** — play order as persuasion; the deliberate contrast direction;
   play-it-twice; and the per-client fact of decides-in-the-room vs. listens-alone
   (present-live vs. send-ahead).
8. **Start-before-paper** — the per-client trust posture that gates beginning work before
   the PO/deposit clears. Quantifiable from payment history + relationship depth.

**C. The memory that compounds (RI gaps)**
9. **People move** — RI must anchor to PEOPLE, with employer as a mutable attribute. The CD
   who champions the house will change shops; that migration is the warmest lead in the
   business. (Amendment to the agency-anchored buyer graph.)
10. **The free-extra ledger** — what was given away free last time (extra cutdown, mercy
    round) is priced-in intelligence for the next Commercial Review. Production feeds
    Commercial.
11. **The hero element** — the one musical element that IS the idea, named at Direction
    selection ("the thesis of this track is X"), defended through rounds, preserved through
    conforms.
12. **Aftercare & the usage watch** — post-delivery watch conditions: the aircheck, usage-
    vs-license compliance, award windows, and reactivation triggers (new campaign, award
    win, the CD moves). The renewal calendar is one member of this family, not the whole.

**Ranking (load-bearing first):** the ball-in-court state (#1), person-anchored RI (#9), and
the round-clock rule (#5) are structural; several others (two calendars, fidelity
calibration) live as single CI/RI fields long before they deserve machinery. Resist building
all twelve at once.

---

*Next step (after agreement): design the Production OS around this model — phases as the
workspace's production-era content, the version chain as the spine, the round ledger and
Creative Lock as first-class state, the business track as a parallel lane, and the RI capture
points wired into the places the information already flows.*
