# ChordOS — Chief Product Officer Review

*A product review of the whole system, conducted from the Chief Product Officer's seat.
Method: read the ratified record first (`docs/architecture/CONSTITUTION.md`,
`ARCHITECTURE_DECISIONS.md`, `PROJECT_STATE.md`, the strategy and positioning docs), then
survey the code — every client-facing surface, every operator screen, every intelligence
derivation, every scheduled job — and cite it. Nothing in this document changes a ratified
strategy, brand, messaging, content, growth, editorial, relationship or sales document.
Where a product recommendation touches one, it is flagged and deferred, not decided.*

**Date:** 2026-09-08 · **Standing:** advisory to the CEO · **Governing question:**
*"How does this strengthen the client's confidence?"*

---

## 0. The verdict, in one paragraph

ChordOS has built something genuinely rare: a delivery experience for a creative service
that a procurement department would respect, with an engineering discipline — one
derivation per fact, one authority per number, signatures bound to documents, capability
gates that subtract rather than hide — that most companies ten times its size never
achieve. **The second half of the engagement is one product.** The first half is not. A
buyer meets between nine and thirteen distinct URLs across five token families before they
reach the room where the work happens; two different commercial closes are both live and
which one they get depends on a path the operator took; three client-facing pages render
the studio's internal navigation, including the words "Buyer Graph", "Payouts" and
"Crawler"; and the front door plays AI-generated placeholder audio without the disclosure
that every other page carries. Meanwhile the operator's own product has grown to eighteen
navigation items across four groups, four red badges polling on a sixty-second timer, and
at least three separate answers to "what needs me". **The work is not to add. It is to
collapse.** One client, one link, one room; one operator, one queue, one room. Everything
else is a view.

---

## 1. Stage 1 — What I studied

### The business

Chordential sells **clearance-certified original music for brand campaigns** — human-made,
fully owned, delivered with cutdowns, stems, a cue sheet, and a certificate a legal team
can defend (`docs/product-spec-clearance-certified.md`). Anchor pricing spans ~$2,500
(Social Sprint) to ~$15,000 (Brand Anthem), sitting above royalty-free subscriptions and
below major-label sync. ChordOS is the operating system beneath it, and Chordential is
instance zero — the Constitution is explicit that the software is the moat and the music is
the revenue, and that generalization is earned, never assumed (§3, A→B→C).

The strategic wager, ratified 2026-06-16, is that **Model A is data manufacturing, not a
services business with a lead tool bolted on**. Every dogfooded job is supposed to produce
qualification labels, estimation actuals and win/loss outcomes that make Model B defensible
and Model C possible. I will return to this in Stage 5, because it is the one ratified
premise the product does not yet honor.

### The customer

Two people, and the positioning brief separates them correctly: the **user** feels the
workflow pain (an agency producer, a music supervisor, a brand marketer), while the
**economic buyer** feels the money (agency owner, EP, brand marketing director). But
Chordential's *client* — the person ChordOS's client-facing surfaces actually serve — is
narrower than the five ICPs in `docs/cmo-positioning-brief.md`. It is the agency producer
or creative director who has a campaign, a deadline, an air date, and a legal department
who will ask where the music came from.

That person's confidence is built by four things, in order:
1. **Certainty about money** — what it costs, when it is owed, what it buys.
2. **Certainty about rights** — that the music is theirs, defensible, and will not
   generate a Content-ID claim against their channel.
3. **Certainty about time** — whose turn it is, and when the next thing lands.
4. **Certainty about being heard** — that a note they left at 0:14 reached the person
   writing the music, unchanged.

Every screen in this system should be scored against those four. Most of the good ones
already are.

### The positioning

The CMO brief leads with *Music Opportunity Intelligence*, growing toward *the operating
system for commercial music procurement*, and explicitly vetoes "RFP platform", "creative
intelligence platform", "AI music tool" and "lead-gen/scraper".

**There is a live tension here I am obliged to name and not to resolve.** The positioning
documents describe a demand-side intelligence product. The software's best work — and one
hundred percent of what a client ever experiences — is the delivery half. The Discovery
navigation group (Signal engine, Crawler, Source Health, Agencies, Relationships) is five
of eighteen operator nav slots and, by the first principle, scores near zero on client
confidence: it strengthens the operator's pipeline, not the buyer's certainty. That is not
an argument to delete it — the Constitution rules it is the data-manufacturing engine of
Phase A — but it is an argument that it has been given far more of the product's surface
area than its current contribution justifies. Stage 4 makes that concrete.

### The sales process

Relationship-led, and honestly modeled: front door → intake (`/start` or `/book`) →
first-touch page → discovery call (booked, calendared, notetaker-armed, transcribed) →
Campaign Intelligence extracted by ten parallel workers → a **Discovery Summary that is the
proposal and is signed** (ADR-0065) → countersignature → project created → deposit →
production. `docs/architecture/ARCHITECTURE_DECISIONS.md` ADR-0020 ruled there is exactly
**one** commercial commitment.

There are two. See Stage 2.

### The production workflow

`docs/production-lifecycle-model.md` is the best document in this repository. It models the
engagement as two tracks — creative (currency: versions and feedback; rhythm: the round) and
business (currency: signatures and registrations; rhythm: gates) — that must arrive at
delivery on the same day, complete. It names the abstractions the software was missing: the
Presentation, the Round, Creative Lock, conform-vs-revision, the taste gate, the licence as
a living object, the renewal calendar, feedback as intelligence.

Most of the creative track shipped. `production.court_state` computes whose court the ball
is in. Directions are first-class with recorded rejection reasons. Creative Lock is state.
`room.priced_notes_only` (ADR-0069) is the rule that a client note is not work until a human
prices it `conform` / `revision` / `out_of_scope`. The round ledger exists.

**The business track shipped as documents, not as facts.** That is Stage 5's core finding.

### The delivery philosophy

Stated in the Constitution §7 and honored better than almost anything else in the system:
procurement-grade always, evidence first, the client remembers the surface not the software.
The delivery package rebuilds when it is older than its own contents (ADR-0079), the
manifest names the file you actually receive (ADR-0091), the certificate is signed by
Chordential and reports SUPERSEDED when a term moves (ADR-0059, ADR-0080), downloads unlock
on payment and the gate keys on token presence rather than admin status so a disabled admin
gate cannot silently open the paywall.

---

## 2. Stage 2 — Does this feel like one product?

**No. It feels like one product with an archipelago in front of it.**

The room — `/room/{project_id}`, one template, four credentials, capabilities subtracted
server-side (ADR-0068) — is a genuine product. Over the last three weeks of commits it has
been absorbing the surfaces that used to surround it: the picture drop moved in, the
clearance certificate moved in, the pay links were repointed at it, the workspace now 303s
into it. That migration is the single best product decision in the repository's history and
it is roughly eighty percent done.

Everything before the countersignature is still several products wearing one palette.

### The seams, named

**Seam 1 — two front doors.** `/` serves the score world (`public/score.html`); `/commission`
serves a 2,203-line film with a different offer, a live price calculator, and a hand-typed
delivery manifest at `commission.html:809-817` sitting beside the engine-generated manifest
at `score.html:617-621` that `landing.sample_package_lines()` exists to keep honest. Two
maintained copies of one promise. `/commission`, `/showreel`, `/stills`, `/delivery-sample`,
`/for-artists` and `/refer` are unreachable from the front door's own chrome — the exact
orphan-page failure `docs/launch-review.md` finding 4 was written to close, regrown in a new
shape.

**Seam 2 — the internal sidebar on client pages.** `discovery_request.html:1`,
`meet.html:1` and `meeting_manage.html:1` all `{% extends "base.html" %}`, and `base.html`
renders the operator sidebar unconditionally. A buyer picking a time for their discovery
call sees the brand tag **"Procurement OS"**, a live beacon reading *"machine running"*, and
links labelled Buyer Graph, Payouts, Talent Roster, Crawler (gated) and Call simulator.
Every one of those is admin-gated, so a curious client who clicks lands on the studio's
login screen. `PROJECT_STATE.md` records the same class of failure being caught in
production on 2026-08-17, at the moment of signature. It is still live on three pages
earlier in the funnel.

**Seam 3 — two commercial closes.** The signable Discovery Summary (`_brief_document.html`,
signing at `workspace_routes.py:360`) and the Commercial Review's four-checkbox approval
(`_commercial_document.html:88-105`, awarding at `workspace_routes.py:599`) are both fully
live. ADR-0020 ruled there is one commitment; ADR-0065 made the summary signable; nobody
retired the other path. Which experience a buyer gets — draw a signature on a document, or
tick four boxes — depends on which button the operator pressed. Two answers to the one
question a buyer's procurement team will ask about.

**Seam 4 — an entire dead stage.** `/workspace/{token}` redirects to the room the moment a
project exists (`workspace_routes.py:137-141`). So `_kickoff_document.html` (119 lines:
"Everything is ready.", "Meet your team", "Production checklist"), the workspace deposit
box, the production court card and `POST /workspace/{token}/approve-version` are unreachable
for any real client, and still maintained. The room reimplements the gate via
`kickoff.client_gate`.

**Seam 5 — a client button that posts to an admin route.** `_brief_document.html:684-687`
renders **`Pay deposit →`** posting to `/invoice/{id}/checkout`, which is not exempted in
`publicpaths.py`. Every other client payment path was migrated to `/project/{id}/pay`. This
one was not, and the failure mode is the worst one this codebase has: the admin gate answers
a client **200 with a login page**, which looks exactly like success.

**Seam 6 — the operator's own archipelago.** Eighteen navigation links across four section
headings, one of which ("Front-of-House") governs a single item while the five biggest
destinations sit under no heading at all. Four red badges — incoming, alerts, queue, signals
— polling every sixty seconds. And at least three screens answering "what needs me":
`/dashboard` ("Today"), `/queue` ("Disposition Queue"), `/incoming` ("Incoming — every new
lead, one queue"), with `/inbox` ("Opportunity Inbox") and `/inbound_queue` ("Front-of-House
· Inbound Leads") close behind. ADR-0029 fixed the *number* they disagreed on. It did not
fix that there are five of them.

The duplication here is literal, not thematic. `db.list_incoming()` (`db.py:3509-3574`) is a
union of `inbound_leads` and `signals`; `db.list_inbound_leads()` (`db.py:3482`) — which
backs `/leads` — is a strict SQL subset of it, emitting the same `/leads/{id}/promote` and
`/leads/{id}/status` actions. And `/dashboard` renders `db.list_incoming(conn)[:6]`
(`console_routes.py:129-131`). Three screens, one query, three depths.

**Seam 7 — the operator has orphan pages too.** `/leads`, `/settings/company-profile`,
`/settings/storage` and `/campaign/{id}` are all live and none is in the navigation.
`/settings/storage` — the media-bucket status and migration console — has **no inbound link
anywhere in the templates**; it is reachable only by typing the URL. Both settings routes
register `nav="pipeline"`, a key that matches no section in `base.html`, so nothing
highlights even if you arrive. `/campaign/{id}` is the flagship Creative-OS view, flagged on
by default, and reachable only by drilling through Projects. The public site's orphan
problem, which `docs/launch-review.md` finding 4 was written to close, has an exact mirror
image inside the console.

**Seam 8 — the navigation is role-blind.** `roles.py` enforces three roles at the route
layer and `base.html` hides nothing. A `viewer` sees all eighteen destinations and discovers
what they may not do by pressing a button and being refused. A role model that is invisible
until it says no is a role model the person cannot learn.

### The vocabulary problem

The same objects are named differently on adjacent screens:

| The thing | Names it goes by |
|---|---|
| A deal | Opportunity · deal · campaign · engagement · job · brief |
| The person buying | client · buyer · agency · brand · company · organisation |
| The person making it | creator · talent · composer · contributor · crew |
| The list of what needs me | Today · Disposition Queue · Incoming · Opportunity Inbox · Inbound Leads |
| This software | ChordOS · Procurement OS · Chordential |

Some of this is legitimate domain nuance — a *contributor* really is not an *assignment*,
and ADR-0082's ruling that a mixer is not a writer is precisely a vocabulary distinction
that earns its keep. But three examples are not nuance:

- **One screen, two names for one record.** `dashboard.html:97` heads a column
  `<th>Campaign</th>`; thirty-seven lines later `dashboard.html:134` heads the equivalent
  column `<th>Opportunity</th>`. Same page, same underlying row, two modules, two words.
- **Three screens called "Profile", three different referents.** `buyer.html` is the client's
  profile, `agency_detail.html` is a harvested company's profile, and `company_profile.html`
  is **Chordential's own** banking and insurance details for procurement paperwork.
- **One page, two names for itself.** `agencies.html:2-3` is titled "Agencies"; five lines
  down at `:8-9` it calls the same table *"the Master Company Database."*

And "Disposition Queue", "Signal engine", "Match Board" and "Procurement OS" are
engineering-internal names on user-visible chrome. The brand tag on every internal page says
**Procurement OS** while every strategy document says ChordOS and every client artifact says
Chordential. A product that speaks three languages to one operator will speak four to two.

**Verdict on Stage 2:** the room proves the team can build one product. The rest of the
system is the evidence of what the room was built out of, still standing.

---

## 3. Stage 3 — The customer journey, stage by stage

Scored on four questions per stage: *what confidence should be gained · what friction
exists · what feels magical · what feels manual or unfinished.*

### Landing page

- **Confidence to gain:** these people are serious about craft, and they are organized.
- **Magical:** the score world is genuinely extraordinary — 7,419 engraved marks in 728
  pieces, measured from the beat they illustrate rather than pinned to fixed scroll
  fractions, folding into a delivery carton whose outline is staff paper. And beat 06's
  manifest is generated by the real packager, so the promise on the marketing page cannot
  drift from the product.
- **Friction:** one CTA, one destination. No path to the sample package except from a
  single mid-scroll link, none at all to the showreel or the commission film.
- **Unfinished:** the recordings on this page are AI-generated placeholders
  (`showcase.PLACEHOLDER_AUDIO_NOTICE` exists and says so) and **the disclosure is not
  rendered here**. `score.html:226` defines the CSS class for it and no element uses it;
  `tests/test_hear_the_work.py:150-156` explicitly exempts the front door. `/commission` and
  `/showreel` disclose correctly. This is the honesty rule — a hard constraint, not a value
  statement — broken on the highest-traffic page in the product, two scroll-beats from a
  headline about human craft.
- **Also unfinished:** `showcase.py` carries an entire unrendered editorial layer, including
  three Field Notes marked `"status": "Coming soon"` (`showcase.py:164-168`).

### Discovery

- **Confidence to gain:** they listen, they prepare, and booking is effortless.
- **Magical:** the whole meeting chain. A booked call arms a notetaker, produces a
  transcript, and runs ten parallel extraction workers into a provenance-tracked Campaign
  Intelligence record where every fact carries its evidence and its epistemic kind — *fact*
  vs *insight* vs *recommendation* vs *open question* — so an inferred judgment is never
  laundered into a stated one. Nobody else in this market does this.
- **Friction:** the internal sidebar (Seam 2). And `POST /opportunity/{id}/request` re-sends
  the generic *"Thanks for reaching out to Chordential"* intake acknowledgment
  (`opportunity_routes.py:827`) to a prospect who is already in a live deal.
- **Manual:** every extracted CI field is disposed one at a time. The batched "review this
  call's updates" surface is designed (`PROJECT_STATE.md`, Increment 2) and unbuilt.
- **Unfinished:** the first-touch page falls back to the same undisclosed placeholder
  recordings on a page tailored to a named prospect (`opportunity_routes.py:1683-1689`).

### Proposal

- **Confidence to gain:** they heard us exactly, and the paperwork is serious.
- **Magical:** `agreement.signable_text()` is one deterministic text that is both what the
  client reads and what the SHA-256 covers, and the signed copy arrives as a PDF built from
  that exact text with the drawn mark attached. If a term moves afterward, the signature
  reads SUPERSEDED rather than appearing to cover the new terms. This is better than most
  e-signature products and it is completely undersold — the client is never told it is
  happening.
- **Friction:** Seam 3. Two closes.
- **Unfinished:** the correction loop is good (*"Not quite right? Don't sign it. Tell us
  what to fix"*), but a client who approves via the Commercial Review path receives **no
  email at all**.

### Commercial review

- **Confidence to gain:** the terms were written by an adult who has done this before.
- **Magical:** producer-voiced terms generated from scope rather than boilerplate — *"further
  rounds are scoped openly, never sprung on you"*, *"Invoiced, never chased."*
- **Friction:** the four checkboxes are a legal artifact, not a product moment. They exist
  to prove consent to four things; a signature already proves consent to one document.
- **Manual:** operator edits and releases; nothing wrong with that — it is the
  machine-proposes rule working.

### Kickoff

- **Confidence to gain:** everything is under control and I know what happens next.
- **Unfinished:** the designed kickoff document is dead code (Seam 4). What the client
  actually gets is the room's "Before we start" gate — deposit plus the picture drop — which
  is good, and materially less than what was designed. The one thing the production model
  calls *free excellence* — **collecting delivery specs at kickoff instead of scrambling for
  them at delivery** (stem splits, loudness targets, naming) — is named in
  `production-lifecycle-model.md` §6 and is not asked anywhere.

### Production

- **Confidence to gain:** my note reached the composer, unchanged, and I know whose turn it
  is.
- **Magical:** the room. Timecoded notes that pause the transport when you focus the box so
  the mark lands where you meant it; a mark you can drag afterward, but only if you wrote it;
  the verdict renamed from "Request changes" to **"Ask for a new version"** with a panel
  underneath saying what it costs — *"Approving does not spend a round … leaving notes never
  does."* ADR-0095's insight, that every one of these controls was correct and
  *unlearnable*, is the most product-mature reasoning in this repository.
- **Friction:** the client is never told whose court the ball is in, in words. ADR-0093
  ruled deliberately that the room states the court by what it *contains* rather than by
  announcing it. I disagree, and log it in §10 rather than overrule it: a buyer who opens a
  room with nothing to do cannot distinguish *on track* from *forgotten*.
- **Manual:** the studio prices every client note by hand, and states the conform offset by
  hand. Both are correct — they are contractual judgments — but the queue only recently
  learned to name an unpriced note (ADR-0096), and before that the client looked ignored and
  the composer looked idle.

### Review

- **Confidence to gain:** I can bring my team in without losing control.
- **Magical:** delegation. A verified reviewer invites a colleague who gets their own named
  link, an expiry capped at the inviter's, and no power to sign, approve or delegate onward —
  built on the observation that clients forward links anyway, so the real access model was
  already *whoever has the URL* while the records named one person (ADR-0060).
- **Friction:** doors. A five-person agency review team on a re-proposed call plausibly
  holds eight to ten live URLs across the account.
- **Unfinished:** **a named reviewer is never told when a new version lands.**
  `delivery_ops.py:209-222` carries the TODO and is honest about why — the
  agency-direction notification *"needs the deferred outbound-send infra that doesn't exist
  yet... left unimplemented rather than faked."* The refusal to fake it is correct. The
  consequence is that the client's own review team learns about a new take from a human
  telling them, which is exactly the hand-relay the timecoded review surface was built to
  end.

### Delivery

- **Confidence to gain:** this is the cleanest handoff we have ever received.
- **Magical:** the package. Rebuilt when it predates its own contents, manifest reconciled
  against the actual files, `START-HERE.txt` at the ZIP root, seals that read DELIVERED,
  contributors shown as roles rather than names because the roster is the business.
- **Friction:** the paywall copy is good and the moment is transactional. This is the
  highest-emotion moment in the engagement and it currently reads as a checkout.
- **Unfinished:** see Stage 5 — the certificate's sentence.

### Repeat client

- **Nothing exists.** No repeat-project prompt, no renewal notice, no post-mortem visible to
  anyone, no testimonial capture, no NPS. The client's last touch is a payment receipt. The
  operator's final next-action card reads *"Nothing — campaign delivered and paid. The
  archive and renewal calendar carry it from here"* (`next_action.py:193`) — **and there is
  no renewal calendar.** No table in the schema holds a licence term expiry. The system tells
  its own operator that something has them covered, and nothing does.

### Referral

- **Nothing exists on the buyer side.** `/refer` is supply-side: it refers composers into the
  talent funnel (`public.py:516`, eyebrow *"For our creators"*). The only trace of buyer
  referral in the entire codebase is one internal line on the Buyer Graph —
  *"Nurture — you've won before; pitch the next project or ask for a referral"*
  (`buyer_intel.py:203`) — which is a hint to a human, not a mechanism.

**The journey's shape, stated plainly:** confidence climbs steeply from first-touch through
delivery and then **falls off a cliff**. The two stages the business model depends on for
compounding — repeat and referral — are the two with no product at all.

---

## 4. Stage 4 — What ChordOS must never become

The Constitution already refuses several of these; this section sharpens them into tests a
reviewer can apply, and then names where the drift has already happened.

### The six refusals

1. **Never a generic CRM.** Test: *does this screen exist to hold a record, or to produce a
   decision?* A screen that lists things without proposing an action is a CRM screen.
2. **Never a project-management tool.** Test, inherited verbatim from
   `campaign-workspace-prd.md` §0: *does this make ChordOS feel more like the operating
   system for campaign music, or am I recreating Asana?* The atoms must stay musical — cues,
   versions, stems, rounds, conforms, clearances — never "tasks."
3. **Never a document repository.** Test: *is this document generated from a fact the system
   holds, or stored because someone uploaded it?* A stored document that nothing derives is
   a filing cabinet.
4. **Never a file-sharing platform.** Test: *does the file arrive inside a decision?* A
   download that is not attached to an approval, a payment or a delivery is Dropbox.
5. **Never a proposal generator.** Test: *does this proposal know what it costs us?* A
   document that renders a number it did not derive is a template with a logo.
6. **Never a music library.** Test: *is anything here reusable across clients?* The moment a
   track exists to be found rather than commissioned, the business has changed.

I would add a seventh, because it is the one this product is actually at risk of:

7. **Never an intelligence dashboard.** Test: *how many decisions did this screen produce
   last month?* A screen that produces analysis nobody disposes is a report, and reports are
   where creative-service software goes to die.

### Where feature creep has already happened

**The call simulator** (`/simulator`, 7 routes, personas, a library, sessions,
`simulator.py` at 500+ lines with AI buyer personas). It is well built and it is a **sales
training product living inside a delivery OS**. It strengthens the operator's skill, not the
client's confidence. Under the first principle it does not belong in the navigation.

**The discovery stack at its current weight.** Signal engine, Crawler, Source Health,
Agencies, Relationships — five nav slots, 51 route decorators across two modules, 11,905
agencies, 85,699 signals and 38,924 decision-makers in production — supporting a
relationship-led business that closes deals by conversation. And **six of the ten scheduled
engines that feed it are off by default** (`scheduler.py:1255-1258`), because their batches
starve the single-CPU web instance. The product ships an intelligence factory with the power
switched off, and gives it a quarter of the operator's navigation.

**Five answers to "what needs me."** `/dashboard`, `/queue`, `/incoming`, `/inbox`,
`/inbound_queue`. ADR-0035 already deleted `/lanes` for exactly this reason and recorded the
acceptance test that decided it: *"no two tabs may show the same cards."* That test has not
been applied to the remaining five.

**Two workspace surfaces, one of them dead.** Seam 4.

**The room's template.** `creator_portal.html` is **4,407 lines** serving four roles. It is
on precisely the trajectory `app.py` was on before ADR-0044 took it from 9,133 lines to 655.
The last two commits did the right thing — extracting `_client_drop.html` and
`_clearance_card.html` as shared partials rather than copying. That instinct needs to become
a rule now, not at 9,000 lines.

### What I recommend removing

| Remove | Why | Where it goes instead |
|---|---|---|
| `_kickoff_document.html` + the workspace's post-award branches | Unreachable for any real client | The room already renders the gate |
| One of the two commercial closes (retire the four-checkbox approval) | ADR-0020 says one commitment; two are live | The signable summary |
| `/simulator` from the navigation | Sales training, not client confidence | Keep the routes; reach it from `/pricing` or a tools drawer |
| `/inbound_queue` **or** `/incoming` | Two front-of-house lead lists | Whichever the operator actually opens |
| The dead editorial layer in `showcase.py` (`PROBLEM`, `STEPS`, `TRUST_CATEGORIES`, `ABOUT`, `CLOSE`, `SAMPLES`, `FIELD_NOTES`) | Rendered by nothing; includes three "Coming soon" entries | Delete, or ship |
| `/commission`'s hand-typed manifest | A second copy of a generated promise | Render `landing.sample_package_lines()` |
| The Discovery nav group, demoted from five slots to one | Weight far exceeds current contribution | One "Discovery" destination with the five as tabs |

None of this is a strategy change. Every item is a surface that already lost its argument
and was never removed.

---

## 5. Stage 5 — Intelligence

### What belongs, and is canonical

The "one derivation, many reporters" discipline is real and I verified it. Each of these has
exactly one home and every surface renders it:

| Fact | Authority | Stored or derived |
|---|---|---|
| What needs the operator | `queue.compute_queue` | derived |
| What a job costs us | `web.estimate.estimate_for` | derived |
| What a job costs the client | `capabilities.quote_for` / `pricing.build_quote` | derived |
| Where a relationship stands | `buyer_intel.assess_relationship` | derived, cached |
| Whether a project is ready | `kickoff.readiness_for_project` | derived |
| Who may see what | `room.CAPS` / `room.room_view` | derived, subtractive |
| Which agreement governs | `agreements.kind_for` | derived |
| Whose court the ball is in | `production.court_state` | derived |
| Whether a note is work | `room.priced_notes_only` | derived from a human decision |
| Everything known about an engagement | `campaign_intelligence` + `_field` + `_event` | **stored, with provenance** |

Campaign Intelligence being stored is correct: provenance cannot be recomputed. Everything
else being derived is correct for the same reason ADR-0057 exists — two stored answers to
one question means one of them is wrong on a day nobody is looking.

### What does not belong

**Proposed facts in the decision queue.** ADR-0096 already removed twenty-two "Proposed fact
to confirm" cards from one campaign that were burying five real supply-side blocks. That
ruling — *"a to-do list holds decisions only"* — is the right general principle and it
should now be applied to the dashboard, which still composes several cards from the same
rows.

**`estimation.suggested_price` on the dashboard KPI.** It folds usage into the creative
number and therefore disagrees with `build_quote`, which ignores it deliberately
(`CLAUDE.md`). One of those two numbers is the price. The dashboard shows the other one.

### What should be rendered and is stored

**The relationship-stage cache is written on a GET** (`relationships.py:107`). It is batched
into one commit and respects operator overrides, so it is a defensible cache rather than a
second authority — but a read path that writes is a pattern that gets copied.

**Qualification cache columns** on `opportunities` are indexed so list filters do not
recompute — the right trade — but they can disagree with `evaluate()` until a re-score cycle
runs, **and re-score is one of the six engines that is off by default.**

### One honesty-rule breach on the operator's side

Constitution §4.3 requires that numbers shown are *"live from the database or explicitly
labeled as demo."* With `CHORDENTIAL_SEED_DEMO=1`, seeded opportunities, talent and projects
render **identically to real records** on every operator screen — dashboard, inbox, queue,
buyers, roster, projects. `seed.py` marks them internally by `source` and `purge_demo_data()`
can find them, but no template surfaces that marker: no badge, no banner, no filter. The
operator's only removal tool is the same per-row delete used on real records. The demo
dataset is off in production, so this is not a live client-facing lie — it is a rule the
product states about itself and does not keep, on the surface where a founder judges their
own pipeline.

### What is missing — four gaps, ranked

**Gap 1 — the clearance claim is asserted where it should be computed.**

This is the most important finding in this review, because the Clearance Certificate is the
single thing the market is asked to pay a premium for.

The good news, and it is better than I expected: a **contributor release** document exists,
is token-gated and separately signable (`contributor_routes.py`), and
`db.contributor_release_gaps()` returns *"everyone named on this project who has NOT signed
their release"* with a docstring that states the point exactly — *"the list of people who
could make that false."* It gates `cert_signable` (`project_routes.py:772`), and an
unsigned certificate holds delivery (`delivery_ops.DELIVERY_HELD["unsigned"]`). The chain
closes.

Three things still do not:

1. **The gap list is only as good as the roster of people someone remembered to type.**
   Nothing derives contributors from the work. A vocalist who sang on the session and was
   never entered produces no gap, and the certificate signs clean.
2. **`clearance_line` is an unconditional constant** — *"100% original & cleared: no
   samples, no third-party masters, no PRO surprises"* (`delivery.py:492-495`). The
   underlying warranty is real: the composer agreement warrants no samples and no
   interpolations (`composer_agreement.py:286`), so the back-to-back position is legally
   sound. But **the system holds no record that the audit happened** and prints the
   conclusion regardless. Under the evidence-first rule, a warranty the system cannot trace
   is the same species of defect as a price the system cannot derive.
3. **The release gap is visible only on the delivery console** — `delivery_console.html:747`
   — and never reaches `queue.compute_queue`. The one surface promising *every decision
   waiting on you* does not name the outstanding signature that will block the delivery.

`docs/architecture/LEGAL_INTELLIGENCE.md` is explicitly not ratified and its own analysis
says Phases 0–1 — the fact spine and the deterministic gap list — need no counsel and carry
zero legal exposure. Half of Phase 1 has been built without anyone noticing it was that.
Finishing it is cheap and it converts the product's headline claim from a sentence into a
computed fact.

**Gap 2 — Relationship Intelligence does not compound across campaigns.**

The Constitution's second failure-mode ("relationships live in one head") and the CEO's
ratified Model-A thesis (dogfooding as *deliberate data manufacturing*) both depend on
Campaign Intelligence rolling up into a durable client profile.
`docs/client-workspace-principles.md` principle 4 states it; `ADR-0018` says it "must not
die with a campaign"; `production-lifecycle-model.md` §7 lists exactly what should
accumulate — the **feedback dictionary** (their words → the musical move that satisfied
them), the **real approval chain** (does brand appear at round 3?), rounds-to-lock norms,
picture-stability track record, delivery-spec preferences, payment behavior, composer↔client
chemistry.

None of it is built. It is filed as "Later ADR" in three separate documents. The workspace
token is per-deal; the north-star per-client anchor is deferred. **Every new engagement with
a returning client starts as cold as the first one**, which is precisely the failure the
Constitution says ChordOS exists to end.

**Gap 3 — the licence is not a living object, so the annuity is unbooked.**

No table holds a licence term expiry. `production-lifecycle-model.md` §1 Phase I is explicit:
term expiry and usage expansion are **dated revenue events**, and the silent renewal — a
client still running the spot past term — is both lost revenue and a compliance conversation
nobody wants to have cold. The system generates the licence, prints its term on the
certificate, and then forgets the date. And, as noted, it tells its operator that a renewal
calendar has it covered.

**Gap 4 — the estimation loop does not close.**

`estimation.py:822` says it plainly: *"Phase 1: expert priors only; NOT calibrated on
Chordential actuals."* No estimate-vs-actual write-back exists. Constitution §4.6 makes
closing the loop **mandatory, not optional**, on the stated ground that the captured outcome
*is* the moat. Every delivered job today is a data point the business throws away.

### The one intelligence I would add that nobody has asked for

**Delivery-spec intelligence, captured at kickoff.** Ask three questions at kickoff — stem
splits, loudness target, naming convention — store them on the client, and reuse them
verbatim next time. It costs one form, it eliminates the single most common late-stage
scramble in this industry, and it is the cheapest possible proof that the relationship
compounds. It is also the first brick of Gap 2 that can be laid without designing the whole
building.

---

## 6. Stage 6 — Automation

### The rule is right and it is enforced structurally

"The machine proposes, the human disposes" is not a convention here; it is wired. Every
irreversible, financial or client-visible act is a POST behind a button. `ai_budget.py`
enforces something stronger and cleverer — *nothing spends money unless a human asked for
it* — using a context variable that deliberately does not cross into a background thread, so
every unattended task sees "nobody," and that is the safe direction.

Six of ten scheduled engines are off by default. That is capital discipline as architecture,
exactly as the Constitution demands.

### What should disappear

Challenging each manual step by asking *should this exist, can it vanish, can the customer
stop thinking about it:*

| Manual step | Verdict |
|---|---|
| Approve a crawl target | **Keep.** CEO-ratified governance (2026-06-17). |
| Qualify / pursue | **Keep.** The precision gate. |
| Dispose each CI field, one at a time | **Batch it.** The designed review surface ("review this call's updates" — the diff, confirm-all, projected downstream impact) is Increment 2 and unbuilt. This is the single largest clerical load in the product. |
| Release the proposal | **Keep.** Client-facing commitment. |
| Countersign | **Keep.** |
| Create project / assign each role | **Collapse.** ADR-0020 already ruled that Assign is *one* decision that mints the portal, sends the brief, logs and notifies. Creating the project should not be a separate press from awarding the deal. |
| Price each client note | **Keep, and make it fast.** It is a contractual judgment. But it should be two keystrokes from the queue, not a visit to the console. |
| State the conform offset | **Keep.** Honest refusal to guess. |
| Publish a version (the taste gate) | **Keep.** This is the house's reputation. |
| Confirm the licence | **Keep.** |
| Sign the certificate | **Keep.** |
| Build package → Release → Ship | **Collapse to one.** Three presses, one decision: *this is ready to go to the client.* The build is bookkeeping. |
| Mark an invoice paid by hand | **Should be rare.** Stripe is live in production; a manual mark is a fallback, and it currently sits beside the automatic path with equal prominence. |
| Record AI spend | **Automate the rest of it.** Five of seven paid call sites check permission and never write the ledger, so the $10 cap under-counts — the same failure the module was written after an incident to prevent. Four `record()` calls. |

### The badge problem

Four red badges polling every sixty seconds — incoming, alerts, queue, signals — plus a
machine beacon, plus five screens that answer overlapping versions of "what needs me". That
is not reduced cognitive load; it is hidden complexity wearing an interface.

The Constitution's own design principle for the room says it: *"No badges, no red dots, no
engagement mechanics. The room tells the composer exactly one thing at a time."* The
operator deserves the same courtesy. **One number, in one place, that is always true** —
`compute_queue`'s length — and everything else reachable from it.

---

## 7. Stage 7 — Delight

Product delight, not motion. The test I applied: *would a producer mention this to a
colleague unprompted?*

### Already delightful, and undersold

1. **The signed copy.** A PDF of the exact text that was hashed, with the drawn signature
   attached, arriving in seconds. The client is never told this is what happened. One
   sentence — *"This PDF is the exact document you signed; if any term changes, your copy
   will say so"* — converts a file attachment into the reason they trust us.
2. **SUPERSEDED.** A signature that reports it no longer matches its document is a
   procurement person's dream and it is currently a status string.
3. **"What approving commits."** The block that states what a press locks, whether it spends
   a round, and what licence it grants. This is the best piece of product writing in the
   system and it should be the pattern for every irreversible control.
4. **The manifest that names the file you actually get.** Legal teams notice this.

### Six moments worth building

| Moment | What the client would say |
|---|---|
| **The one-hour summary.** The Discovery Summary lands within an hour of the call, with their own words quoted and attributed, and a line naming what we heard *and* what we still need to ask. | *"We got the recap before we got back to the office, and it was right."* |
| **The kickoff spec sheet.** Three questions at kickoff — stem splits, loudness, naming — answered once and reused every campaign after. | *"They asked our post house's stem splits at kickoff. Nobody asks that at kickoff."* |
| **The court line, said out loud.** One sentence at the top of the room: whose turn, since when, what lands next and when. | *"I always know where it is without emailing anyone."* |
| **The renewal notice.** Sixty days before term expiry, an email that states the term, what is still running, and the two options. | *"They told us our licence was expiring before our legal team noticed."* |
| **The delivery opening.** The package's first screen is a sixty-second orientation — what is in here, what to hand your post house, what to send legal. | *"The handoff took five minutes instead of a week."* |
| **The certificate their lawyer keeps.** A one-page document that names every human in the chain, their signed release, and the audit that was performed — computed, not asserted. | *"Our business affairs team asked who else works like this."* |

Note that four of the six are **not new features** — they are existing facts, said at the
right moment, to the right person. That is the cheapest delight in software and this system
is unusually rich in unsaid facts.

### The one they would actually tell coworkers about

The renewal notice. Everything else in the list improves an engagement that is already
happening. The renewal notice arrives when nothing is happening, costs the client nothing,
protects them from a compliance problem they did not know they had, and — not incidentally —
is the annuity `production-lifecycle-model.md` says most small houses forget to collect.

---

## 8. Stage 8 — Scale

**500 agencies · 5,000 campaigns · 100,000 deliverables.** Would this still feel elegant?

### What breaks first, in infrastructure

1. **The dashboard and the queue, and they break together.** `queue.compute_queue` calls
   `db.list_projects()` **four separate times** with no LIMIT (`queue.py:83, :166, :193,
   :209`) and runs `next_action.compute` per project. The read memo (ADR-0051) bounded the
   *query* count — 255 vs 683 at 38 projects, 62% fewer — but it did not bound the Python.
   At 5,000 campaigns the first screen of the day runs the full lifecycle ladder five
   thousand times. The fix is small: push the status filter into SQL (`queue.py:167` already
   discards Delivered/Complete/Archived *after* loading them) and paginate.
2. **The database as the media store.** With no bucket configured, `media_blob` **is** the
   durable store, ceiling 512 MB per file on Postgres (ADR-0084 — *whatever we accept we
   must be willing to keep*). At 100,000 deliverables that is a multi-terabyte Postgres
   table served through the app process. Object storage is built, tested, flagged
   (`CHORDENTIAL_STORAGE=s3`) and switched off, filed as *"deferred, not urgent."* At this
   scale it is the largest line item in the business.
3. **The pool ceiling of 10**, against client-portal traffic plus an `ai_budget` check that
   opens its own connection per call.
4. **One scheduler leader doing all background work**, spawning a subprocess per agency.

All four are known, none is hard, and none of them is what actually breaks.

### What breaks first, in the product

**The operator.** Every decision button belongs to one human by constitutional design. At
5,000 campaigns the first law becomes the bottleneck, and the honest answer is not "hire
operators" — it is that **the machine-proposes rule must scale by narrowing what deserves a
human, not by adding humans.** The twenty-two proposed-fact cards ADR-0096 removed from one
campaign's queue are the preview of that failure at 1× volume. Multiply by 5,000.

The design work this implies is the most important unbuilt thing in the roadmap: a
*confidence threshold* under which the machine's proposal is simply applied and reported,
and above which it waits. That is not a violation of the first law — the human still sets
the threshold and can reverse anything — but it is a constitutional amendment in substance,
and it needs the CEO, not me.

**The buyer with thirty campaigns.** The room is one project, and the Scoring Stage design
argued correctly that *"a composer with three engagements gets three doors, not a portfolio
manager."* That is right for a composer and wrong for an agency running thirty campaigns a
year. The first thing a scaled buyer asks for is a place to see all of theirs. Today the
durable anchor is per-deal and the per-client promotion is a "later ADR" in three documents.
**At 500 agencies that deferral becomes the first structural rewrite**, and it is the same
work as Gap 2 in Stage 5. Doing it once, deliberately, for both reasons, is the highest-value
architectural decision on this roadmap.

**The room's template**, at 4,407 lines, is the third thing. It is `app.py` in 2026-08.

---

## 9. Stage 9 — The roadmaps

Scoring key. **Impact** columns are High / Medium / Low. **Complexity** is
S (days) / M (weeks) / L (months). **Confidence** is my certainty that the recommendation is
correct as stated, 0–100.

### Immediate — the next thirty days

*Theme: stop contradicting ourselves. Almost none of this is building; it is deleting,
reconciling and wiring.*

| # | Recommendation | Business | User | Architecture | Cx | Conf |
|---|---|---|---|---|---|---|
| I1 | **Put the release gap in the queue and make `clearance_line` conditional** on a completed chain of title. Record that the sample audit happened, rather than printing its conclusion. | High | High | Low | S | 95 |
| I2 | **Get the operator sidebar off the three client pages** (`discovery_request`, `meet`, `meeting_manage`). Give them the standalone client shell the other surfaces already use. | High | High | Low | S | 98 |
| I3 | **Retire one commercial close.** Keep the signable Discovery Summary; remove the four-checkbox approval path. | High | High | Medium | S | 90 |
| I4 | **Fix the Pay button that posts to an admin route** (`_brief_document.html:684`), and add a test that fails when a client-facing form targets a non-exempt path. | High | High | Low | S | 97 |
| I5 | **Disclose the placeholder audio on the front door**, or replace the recordings. Remove the test exemption. | High | Medium | Low | S | 99 |
| I6 | **Delete the dead kickoff and workspace branches** and the unrendered editorial layer in `showcase.py`. | Low | Low | Medium | S | 92 |
| I7 | **Close the AI ledger** — four `record()` calls — so the cap stops being decorative. | Medium | Low | Low | S | 95 |
| I8 | **Stop the intake acknowledgment firing on an in-flight deal** (`opportunity_routes.py:827`). | Medium | Medium | Low | S | 94 |
| I9 | **Correct the two stale claims in `CLAUDE.md`** (`/pay/return` is fixed) and mark `docs/product-efficiency-audit.md` superseded — its line numbers predate the `app.py` teardown. | Low | Low | Low | S | 90 |
| I10 | **Label demo data as demo** on every operator surface, per Constitution §4.3, and give `purge_demo_data()` a button. | Medium | Medium | Low | S | 93 |
| I11 | **Give `/settings/storage` and `/settings/company-profile` a way in**, and fix the Outbox nav's `nav=='settings'` vestige. | Low | Medium | Low | S | 96 |

### Next quarter

*Theme: one door in, one door out.*

| # | Recommendation | Business | User | Architecture | Cx | Conf |
|---|---|---|---|---|---|---|
| Q1 | **One front door.** Fold `/commission`'s four demonstrations into `/`, or promote `/commission` and retire the score world's duplicate promise. Render the generated manifest in both. One nav, no orphans. *(Touches brand and content strategy — recommend, do not decide.)* | High | High | Medium | M | 80 |
| Q2 | **One client door per engagement.** Reduce nine-to-thirteen URLs to two: the room, and a named reviewer link. Everything else redirects. Finish the migration the last ten commits started. | High | High | High | M | 88 |
| Q3 | **The batched intelligence review.** "Review this call's updates" — the diff, confirm-all, projected downstream impact — over every intake lane. Removes the largest clerical load in the product. | High | High | Medium | M | 90 |
| Q4 | **The renewal calendar.** A licence-term object with dates, a sixty-day notice to the client, and a revenue event in the operator's queue. | High | High | Medium | M | 92 |
| Q5 | **Operator nav diet: 18 → 8.** The queue is the home. Discovery collapses to one destination with tabs; the simulator leaves the nav; one of `/incoming` / `/inbound_queue` goes; one badge, not four. Apply ADR-0035's own acceptance test — *no two tabs may show the same cards* — to the five "what needs me" screens. | Medium | High | Medium | M | 85 |
| Q6 | **Close the estimation loop.** Estimate-vs-actual write-back on every delivered job, per Constitution §4.6 and the Phase-3 spec in `company-strategy.md`. | High | Low | Medium | M | 93 |
| Q7 | **Delivery-spec capture at kickoff**, stored on the client and reused. The first brick of Relationship Intelligence. | Medium | High | Low | S | 90 |
| Q8 | **Bound the dashboard** — status filter in SQL, paginate the queue — before the data grows into it. | Medium | Medium | Low | S | 94 |
| Q9 | **Notify named reviewers when a version lands.** Build the transactional send lane `delivery_ops.py:209` is waiting on; the review surface is not finished until the invitation to use it arrives on its own. | Medium | High | Medium | S | 91 |
| Q10 | **Make the navigation role-aware**, so a viewer is not shown eighteen destinations that will refuse them. | Low | Medium | Low | S | 88 |

### One year

*Theme: make it compound.*

| # | Recommendation | Business | User | Architecture | Cx | Conf |
|---|---|---|---|---|---|---|
| Y1 | **Promote the durable anchor from deal to client.** One workspace per client, many campaigns under it. This is simultaneously the Relationship Intelligence prerequisite, the scaled-buyer requirement, and the ten principles' actual north star. Do it once, deliberately. | High | High | High | L | 85 |
| Y2 | **Relationship Intelligence v1:** the feedback dictionary, the real approval chain, rounds-to-lock norms, picture-stability record, payment behavior, composer↔client chemistry. Anchored to **people**, with employer as a mutable attribute — the CD who champions the house will change shops, and that migration is the warmest lead in the business. | High | Medium | High | L | 88 |
| Y3 | **Legal Intelligence Phases 0–1 in full** — the rights fact spine and the deterministic blocking gap list. No counsel required by the document's own analysis. | High | Medium | Medium | M | 87 |
| Y4 | **Object storage on, and the read paths bounded** for the 100,000-deliverable case. | Medium | Low | Medium | M | 92 |
| Y5 | **Break up the room's template** the way `app.py` was broken up, before it is 9,000 lines. | Low | Low | Medium | M | 88 |
| Y6 | **The repeat-and-referral product** the journey currently ends without: the next-project prompt, the case-study asset, the buyer referral path. | High | Medium | Low | M | 80 |

### Long term

*Theme: earn the generalization.*

| # | Recommendation | Business | User | Architecture | Cx | Conf |
|---|---|---|---|---|---|---|
| L1 | **The confidence threshold.** Design how the machine-proposes rule scales — what the machine may apply and report versus what waits for a human — so that Phase B does not require one heroic operator per instance. Constitutional in substance; needs the CEO. | High | High | High | L | 70 |
| L2 | **Phase B multi-operator**, on the discipline of a product used by someone who is not us. | High | Medium | High | L | 75 |
| L3 | **Phase C buyer-side graph** — the buyer↔creator relationship as an operating and clearing layer. | High | High | High | L | 60 |
| L4 | **Generalization beyond music, only when earned.** The spine is domain-shaped, not music-specific — but the music instance has not yet earned the right, and will not have until Y1, Y2 and Q6 are all producing data. | Medium | Low | High | L | 55 |

---

## 10. Two disagreements I am logging rather than overruling

**1. The room states the court by what it contains, rather than saying it.** ADR-0093 ruled
that the workspace's phase sentence — *"A new version is waiting for you"* — was dropped
deliberately, on the honest ground that a sentence can claim a version is waiting while the
room is empty. That reasoning is sound. My disagreement is about the empty case: a buyer who
opens a room with nothing to do cannot tell *on track* from *forgotten*, and the second
reading is the one that generates the email nobody wants to receive. A court line derived
from `production.court_state` — which already computes it, with an age — is not a claim the
room might contradict; it is the same fact the room is already made of. **Recommend
revisiting; the ADR stands until then.**

**2. The positioning leads with the demand side; the product's center of gravity is the
delivery side.** `docs/cmo-positioning-brief.md` is ratified and I may not change it. But
the product tells a different story than the positioning does, and the client — who never
sees a signal, a crawler or an opportunity score — experiences only the half the positioning
treats as downstream. This is a CEO/CMO question, not a CPO one. **Flagging it as a
positioning input, not a recommendation.**

---

## 11. The final question

> *If Apple built the operating system behind the world's best commercial music production
> company, what would they simplify before they added another feature?*

They would delete the navigation.

Not literally, and not all of it — but they would refuse to ship a product whose operator
chooses between eighteen destinations to find out what needs them, and whose client is
handed thirteen URLs to experience one relationship. Apple's actual discipline is not
minimalism; it is **insisting that a product have one object**. The iPod's object was a
song. Figma's is a canvas. Frame.io's is a shot.

**ChordOS's object is the engagement**, and the product has not yet committed to that. It
has an engagement, plus an opportunity, plus a campaign, plus a project, plus a workspace,
plus a room, plus a portal — seven names and five destinations for one thing that a client
would call *"our campaign."* Every seam in Stage 2 is a symptom of that one un-made decision,
and the room is what it looks like when the decision gets made.

So, concretely, three simplifications before any new feature:

1. **One client, one link, forever.** Not one per deal. The ten principles said this in
   2026-07-07 and the token layer was deliberately built so promoting the anchor from
   opportunity to client would be additive rather than a rewrite. Cash that option.
2. **One operator surface: the queue, and the room it opens into.** Everything else becomes a
   view reachable from a decision, not a destination competing for a nav slot. One number,
   always true.
3. **One promise, computed.** The certificate is the reason this company can charge what it
   charges. Every sentence on it should be derived from a fact the system holds, and the
   system should refuse to print one it cannot trace. That is not a legal requirement; it is
   the honesty rule applied at the exact point where the money is.

And then — the thing Apple would do that nobody asks for — they would make the **renewal
notice** the first new feature after the simplification. Because it is the only moment in
this entire journey where the product reaches out to a client who is not currently paying
attention, tells them something true and useful that protects them, and asks for nothing.
That is what a relationship that compounds actually feels like from the outside, and it is
sixty days of code.

---

*Prepared for the CEO. Recommendations in §9 are sequenced but not scheduled; every item
names the stage of `docs/product-roadmap.md` it advances or the ADR it revisits, and no
ratified brand, messaging, content, growth, editorial, relationship or sales decision is
altered by this document.*
