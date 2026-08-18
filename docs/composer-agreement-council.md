# Composer Agreement v2.0 — Council Deliberation

*Board simulation. The question: **is v2.0 the agreement we put in front of the first
real composer — and what does it cost us commercially, in recruiting, and in risk?**
The lawyer pass (`docs/composer-agreement-review.md`) fixed the structural defects and
is not on trial here. This council is about whether the resulting deal is the RIGHT
one for a studio with no catalogue, no closed deals, and no reserves. Agents are
required to disagree; **consensus is explicitly not the goal**; the CEO ratifies.*

**Convened:** 2026-08-18 · **Chair:** Jon Shipp (CEO) · **Seats:** CFO, Head of Talent,
General Counsel, Head of Production.

---

## 0. What already exists (so we argue about the real document)

| Layer | Status | Where |
|---|---|---|
| The agreement text, v2.0, 12 clauses | ✅ drafted, unsigned by anyone | `composer_agreement.py` (450 lines) |
| Fee policy — 30% of net creative revenue, 40% with orchestration, $400 demo | ✅ built | `compensation.py` (ADR-0061) |
| Publishing 50/50, held-not-kept when the writer has no entity | ✅ built | `compensation.publisher_rows` |
| Deterministic signable text + SHA-256 + supersession | ✅ built | `agreement.py`, `signing.py` (ADR-0059) |
| Governing law / forum | ✅ **Florida / Miami-Dade, defaulted** — `is_signable()` returns True | `composer_agreement.py:60-63` |
| Contributor release (clause 6A requires it) | ❌ **does not exist anywhere in the repo** | — |
| A place to record the clause 6B AI-tool disclosure | ❌ **no field, no column, no form** | — |
| Talent payout ledger | ❌ deferred by the recruiting council (manual + ledger, Connect later) | `docs/talent-recruiting-council.md` §5 |

**First correction of the day, before anyone speaks.** The lawyer pass's open item #1
says the agreement "is not signable, by design" until `CHORDENTIAL_GOVERNING_LAW` is
set. That is **stale**. `DEFAULT_GOVERNING_LAW = "the State of Florida"`,
`DEFAULT_FORUM = "Miami-Dade County, Florida"`, and `is_signable()` is True in normal
use. The document is live. Anyone reading the review doc thinks there is a safety
catch on this thing. There isn't.

---

## 1. CFO — the 120-day backstop is the most expensive sentence in the document

**CFO:** Clause 3B:

> *"The studio pays the writer within 30 days of the client settling that invoice, and
> in any event within 120 days of the client accepting delivery, whether or not the
> client has paid."*

Read the last five words again. That is the studio taking the client's credit risk
onto a balance sheet that does not have one. Let me put numbers on it, using ours, not
invented ones.

From `compensation.py`'s own worked examples:

| Engagement shape | Price | Session cost | Net creative revenue | Writer 30% | Writer 40% (orchestrates) |
|---|---|---|---|---|---|
| :30 national spot | $11,133 | ~$1,200 | $9,933 | **$2,980** | — |
| 3-min film (Larkspur) | $10,300 | — | $10,300 | **$3,090** | — |
| Orchestral anthem | $76,191 | $32,125 | $44,066 | **$13,220** | **$17,626** |

Now lay the cash timeline over it. Billing council: **50% deposit at acceptance,
balance net-7 on delivery.**

- **:30 spot.** Deposit $5,566 in hand. Writer owed $2,980 at day 120. Covered, $2,586
  spare. Fine.
- **Orchestral anthem.** Deposit $38,095 in hand. Against it: session cost $32,125 —
  paid to players and a room *long before* day 120 — plus the writer's $13,220.
  **$45,345 out against $38,095 in. We are $7,250 underwater on one job before the
  client's balance arrives**, and clause 3B says we pay the writer anyway.

The exposure per concurrent engagement is roughly **$3,000 on spot-shaped work and
$13,000–$17,600 on anything with an orchestra.** Three concurrent spots is ~$9k of
unhedged liability. One anthem is worse than all three. And the trigger is not "the
client paid" — it is *"the client accepting delivery"*, which is a clause 2A event
that happens **by our silence for five working days.**

Then read the sentence after it: *"If the studio has not invoiced within 30 days of
acceptance, the writer is paid as though it had."* So a missed invoice does not delay
the clock, it starts it. That is correct discipline and I am not asking to remove it.
I am pointing out that we have written ourselves a **120-day unsecured note, payable
in cash, issued automatically, with no cap on how many are outstanding at once.**

Add clause 3A while I have the floor:

> *"If the price the client finally pays is lower, the writer's fee is not reduced
> below the estimate without the writer's written agreement."*

`market-pricing-research.md` §1 tells us exactly what is coming: Swell publishes
**$10,000 all-in** and we quote a creative fee *plus* a licence fee — "a buyer
comparing like for like sees $10,000 against our $14,000–28,500." We are going to
discount. When we do, **100% of that discount comes out of studio margin**, because
the writer's number is a floor. On the Larkspur job, a 20% concession is $2,060 off a
gross that already owes $3,090 to the writer.

**My position:** the 120-day backstop is right in principle and reckless in this form.
I want it **conditioned or funded**, not deleted.

---

## 2. Head of Talent — the backstop is the entire pitch, and you are proposing to sell the one thing we have

**Head of Talent:** I want to be precise about what the CFO is asking to trade away.

Chordential is unknown. We are recruiting people who can work anywhere, and the
recruiting council already ruled we cannot promise volume — *"the pitch promises
respect, fairness, and first-look, never a salary."* Strip volume out and what is
left in the invite? **How we treat them.** The 120-day backstop is not a clause, it is
the proof. Every composer with five years of experience has been pay-when-paid'd by a
house that then went quiet. Clause 3B is the sentence that says we are not that.

The CFO's own numbers cut the other way, too. **Three concurrent spot engagements =
$9k of exposure.** That is what it costs to be the studio that pays. Nine thousand
dollars is not an existential number; it is a *marketing budget* that happens to be
paid to the people making the product. I would rather spend $9k on that than on
anything the CMO could buy with it.

On which clause a good composer stalls on: **it is not the backstop and it is not the
indemnity. It is clause 5.**

> *"The writer assigns to Chordential Music the whole of the copyright in the
> composition — the publishing — for the life of copyright, throughout the world."*

Life of copyright, worldwide, no reversion, on a first engagement with a studio that
has never shipped anything. Any composer with representation strikes at that first.
Our answer has to be ready and it has to be the 50/50 in the next paragraph, plus
clause 3C's *"for as long as the work earns. This does not stop when this agreement
ends."* That is a genuinely unusual pairing and it is the argument that wins clause 5.

**Head of Talent's lead-with list, in order:** (1) 120-day backstop, (2) 50/50
publishing when *"most advertising houses take 100%"*, (3) 3C's perpetual share of
renewal and expansion income, (4) *"The writer keeps the writer's share of public
performance income… It is not the studio's to take, and this agreement does not take
it"*, (5) the audit right, (6) `ACCEPTANCE_LIMITS` — a signed document that tells you
it guarantees you nothing.

---

### ⚔ Fight 1 — the 120-day backstop (CFO vs Head of Talent)

**CFO:** Then let me condition it. Three options, cheapest first: **(a)** backstop
applies only where the studio has actually invoiced and the client is in default —
i.e. we carry *our* failure, not the client's; **(b)** backstop stays absolute but is
**capped per engagement at the deposit we hold**, with the balance following on
collection; **(c)** the backstop day count scales — 120 days on engagements under
$5,000 of writer fee, 180 on anything above.

**Head of Talent:** (a) is the pay-when-paid clause with a new hat. A composer reads
*"whether or not the client has paid"* and then reads a carve-out for the case where
the client has not paid, and closes the tab. (b) is worse — it makes the composer's
certainty depend on a deposit percentage they never see and cannot verify. (c) is the
only survivable one, and only because it is honest: bigger job, longer clock. But
$5,000 of writer fee is a $16k+ engagement. **That threshold means the backstop is
absolute for essentially every job we will actually book in year one.** Which means
(c) buys the CFO nothing except a clause that reads worse.

**CFO:** It buys me the orchestral case, which is the one that kills us.

**Head of Talent:** Then fix the orchestral case where it actually breaks — the
*session cost*, which is $32,125 of third-party cash leaving before day 120 and has
nothing to do with clause 3B. **Do not solve a session-financing problem with a
composer-payment clause.**

**CFO (concedes the clause, not the risk):** That is fair and I take it. The
composer's 30% is not what breaks the anthem; the players are. **I withdraw (a), (b)
and (c).** But I am not leaving without a control: the backstop stays as written and
we add an **operating rule outside the paper** — no engagement is accepted whose
session cost plus writer fee exceeds the deposit we will hold, unless Jon signs off
specifically. That is a gate in the system, not a clause in the contract.

**Head of Talent:** Agreed, and I will say so to composers. "We do not take a job we
cannot pay you for" is a better sentence than anything we would have put in 3B.

> **Resolution:** clause 3B **ships unchanged**. The CFO's concern moves to a
> **deposit-coverage gate** at engagement acceptance. Head of Talent wins the clause;
> CFO wins the control. Neither conceded on principle — they found different objects.

---

## 3. General Counsel — what is still exposed, and what is over-lawyered

**GC:** Three findings, then a fight.

**Finding 1 — clause 6A is currently unperformable.** It requires the writer to get
each contributor to *"sign the studio's contributor release before the recording is
delivered."* **That document does not exist.** I grepped the repository; clause 6A is
the only place the phrase appears. We are about to sign a composer to an obligation we
cannot let them discharge. Every delivery under this agreement is technically in
breach of 6A from day one, which means either we never enforce it — and an unenforced
warranty is not a warranty — or we enforce it selectively, which is worse. And 6A is
load-bearing: clause 6 says *"This clause is what the studio's clearance certificate
to the client stands on."* The clearance claim in the Constitution is the product.
This is not paperwork; it is the thing we sell.

**Finding 2 — clause 10 is harsher than anyone in this room has noticed.**

> *"…will help the studio deal with the claim — answering questions, producing session
> files, and telling the truth about how the work was made — **at no charge and for as
> long as it takes**."*

Unpaid, unlimited in duration, surviving termination, and — read the trigger — it
attaches when *"a claim is made against the studio or its client"*, not when the
warranty is proven untrue. A writer who did nothing wrong owes us unpaid labour for as
long as a plaintiff wants to keep the matter alive. That is the least defensible
sentence in the document and it survived the lawyer pass untouched.

**Finding 3 — over-lawyered for our size.** The audit right in 3B (annual, accountant,
30 days' notice, 5% shortfall shifting cost, 24-month statement finality) is a major-
label clause on a business with zero closed deals. I am **not** asking to remove it —
Head of Talent will correctly say it is a recruiting asset — but understand that it
obliges us to keep records to a standard we currently do not, and that clause 3C
(*"for as long as the work earns. This does not stop when this agreement ends"*) has
**no de minimis floor and no end date**. A $60 territory extension in 2034 triggers a
full statement under 3B: client, engagement, creative fee invoiced, each deduction and
who it was paid to, share applied, resulting fee. Forever. For $18.

**On the open items the lawyer pass listed:** §203 reversion at ~35 years is real but
academic for campaign advertising — it should be a *recorded decision*, not an open
question, because it qualifies the word "Perpetuity" in `delivery.DEFAULT_LICENSE` and
a procurement lawyer on the client side may one day ask. Assignment-vs-WFH was decided
correctly and for the right reasons. **The genuinely material open item is that
nothing here has been through retained counsel**, and my professional position is that
signing composer #1 on an unreviewed instrument is an acceptable risk *only* because
the alternative — no paper at all — is strictly worse, and because clause 12 lets a
later version govern later engagements (*"A new version applies only to engagements
accepted after the writer signs it"*).

---

### ⚔ Fight 2 — the capped indemnity (GC vs Head of Talent)

**GC:** Clause 10 caps the writer at *"the greater of $25,000 and 3 times the fees the
studio has paid the writer for that engagement."* I want to defend $25,000 as a floor
and I expect to be attacked for it.

**Head of Talent:** You will be. Do the arithmetic against our own fee policy. A :30
spot pays the writer **$2,980**. Three times that is $8,940, so the cap is the
$25,000 floor — **8.4× the fee**. We are asking a stranger to accept, on a three-
thousand-dollar job, personal exposure equal to a used car. And we are asking it in a
document that also tells them, in `ACCEPTANCE_LIMITS`, that we guarantee them no work
at all. That pairing is what a composer's lawyer will read aloud.

**GC:** And what is the alternative? Uncapped is market for this warranty and it is
what a major would hand them. The cap exists *because* of that: the code comment says
it plainly — *"An uncapped warranty against a few thousand dollars of fee is one an
experienced composer strikes and a naive one signs without reading — neither is worth
having."* $25,000 is not a punishment number, it is a **defence-costs** number. If a
library owner asserts an uncleared loop in a national spot, our outside costs pass
$25,000 before anyone reaches the merits. Set the floor at 3× fee — $8,940 — and the
composer's cap does not even cover the letter we have to write.

**Head of Talent:** Then the studio should carry that, not the composer. The risk is
priced into what we charge the client for clearance; that is literally the moat
thesis. Make the floor **$10,000**, keep uncapped for knowing breach, and buy E&O
insurance when we can afford it.

**GC:** $10,000 is a number chosen because it feels kinder, not because it corresponds
to anything. And note what the cap is *not*: it is not a claim we would ever actually
collect from a freelancer. It is a **statement of seriousness that makes clause 6
credible to a client**. Lower it and I lose the argument to the *buyer*, not the
composer.

**Head of Talent (does not concede):** Then say that out loud in the recruiting
conversation, because right now the document does not. I will accept $25,000 shipping
**only** if we pair it with something the composer can see: **the studio pays for the
defence of any claim where the warranty turns out to have been true.** Which brings me
to GC's own Finding 2.

**GC (concedes on cooperation, not on the cap):** Accepted, and it is a better fix
than the one I was going to propose. **Clause 10 changes:** cooperation is unpaid
where the warranty was in fact untrue; where a claim is made and the warranty holds,
the writer's cooperation is **paid at their engagement day rate** and the studio bears
its own costs. *"For as long as it takes"* becomes *"for as long as the claim is
live"*. The **$25,000 floor ships unchanged.**

> **Resolution:** cap **ships as-is** (GC wins). Clause 10's cooperation obligation
> **changes** (Head of Talent wins). Head of Talent explicitly did not concede that
> $25,000 is right — she conceded that it is survivable once the innocent-writer case
> is paid for.

---

## 4. Head of Production — will any of this survive a real session week?

**Head of Production:** I am going to be blunt: **two of these clauses will be
ignored in week one, and an ignored clause is worse than no clause**, because it
teaches the composer which parts of our paper are decorative.

**Clause 6A — the contributor release.** In a real session week the writer books a
vocalist on Tuesday for Thursday, a remote violinist sends a part on Wednesday night,
and a friend plays tambourine because it was there. Clause 6A demands each of them
sign a document *"before the recording is delivered"* — *"paid or unpaid, stranger or
friend, in the room or over the internet."* The scope is right. The mechanism does not
exist. There is no form, no link, no field, no signing flow. What actually happens is
the writer says "yeah, they're fine" over email, we ship, and clause 6A becomes a
thing we both pretend about.

**Clause 6B — the AI disclosure.** *"On delivery the writer lists which of these were
used"* — pitch correction, time alignment, de-noising, separation, AI-assisted
mastering. **There is nowhere to list them.** No column, no upload field, no prompt in
the delivery portal. I searched. On a real delivery the writer uploads WAVs and a
tempo/key note and moves on, and we will have a signed warranty about disclosure with
zero disclosures on file.

**Clause 2A — 5 working days to accept, 5 to fix.** This one is genuinely workable and
I want it noted as such, with one caveat: *"Silence for 5 working days is acceptance"*
is a **liability trigger** now, not just a courtesy — it starts the CFO's 120-day
clock. Nobody in this company currently has "check the delivery inbox" as a named
duty. That is how we will accidentally accept a defective delivery.

**The delivery spec itself** — 48/24 WAV, stereo master, stems *"printed from the same
session and time-aligned to it"*, tempo and key — is exactly right and is the least
controversial thing in the document. It is what a competent writer already does.

**The one I want changed on commercial grounds:** clause 2 says revisions *"within the
rounds stated for that engagement are part of the fee."* `market-pricing-research.md`
§3 says the plain thing: *"most composers include one or two revision rounds; Swell
includes five. We currently promise two. That is a real competitive gap and it is
cheap to close."* It is only cheap to close **on the client side**. If we sell five
rounds and the engagement doc silently states five to the writer, the writer absorbs
150% more revision work inside the same 30% share. Whoever writes the engagement doc
must state the composer's rounds *deliberately*, not inherit the client's.

---

### ⚔ Fight 3 — are 6A and 6B operationally real? (Production vs GC)

**GC:** I am not deleting either. Clause 6B is the *only* thing standing between our
marketing copy and a lie. The Constitution: *"No AI-generated craft… Say so honestly
in the copy."* CLAUDE.md: *"No AI-generated audio."* The delivery package ships a
Clearance Certificate that warrants original authorship. **If we drop 6B because it is
inconvenient to collect, we are selling a certificate we cannot support.** Same for
6A: clause 6 says the certificate *stands on* it. These are the load-bearing clauses.

**Head of Production:** I did not ask you to delete them. I said they are **not real
yet**, and you are treating "it is written down" as if it were "it happens." A
warranty nobody can discharge produces exactly one artefact: a composer who has
learned that our contract is theatre. Then the day it *matters* — a client's
procurement team asks who played on the track — we have a signed 6A and no releases.

**GC:** The warranty still does work you are discounting. Clause 6B ends *"A breach of
this clause is a breach of the whole agreement,"* and clause 6 says *"Telling the
studio honestly is never itself a breach."* That combination changes behaviour on its
own — it makes disclosure the safe move. That is not theatre.

**Head of Production:** It changes behaviour *if the writer is asked at the right
moment*. Right now they are asked once, at signing, months before the session. Ask
them at **delivery**, in the flow, or accept that you have a moral gesture.

**GC (concedes the mechanism, not the clause):** Then the clauses ship and we make
them real. **Blocking, before composer #1 signs:** the **contributor release document
must exist** — it is one page and it is the studio's own paper, not counsel's. **Not
blocking, but next:** an AI-tool disclosure field and a contributor list on the
delivery submission, both landing on the **Rights agent** in the Delivery OS where
they belong.

**Head of Production (does not fully concede):** I accept that split, and I record my
dissent on sequencing: **if the disclosure field is not built before the third
delivery, clause 6B should be cut**, because by then we will have proven we do not
mean it. I would rather have a shorter honest contract than a longer one with a dead
limb.

> **Resolution:** 6A and 6B **ship** (GC wins the clauses). The contributor release
> becomes a **blocking build** (Production wins the gate). Production's dissent on the
> 6B field is recorded and unresolved — see the CEO ruling.

---

### ⚔ Fight 4 — clause 3A, the estimate as a floor (CFO vs Head of Talent, unresolved before the chair)

**CFO:** *"A discount the studio chose to give is not a fact about the writer's work
either."* Elegant sentence, expensive rule. Given `market-pricing-research.md`'s
finding that we present $14,000–28,500 against Swell's published $10,000, discounting
is not a risk, it is the plan. Every dollar of it lands on us.

**Head of Talent:** That is the correct place for it to land. **The person who chose
to discount should carry the discount.** If the writer's number moves because we
negotiated badly, the writer is underwriting our sales skill, which they cannot see,
influence, or verify. And 3A is symmetric — *"If the price the client finally pays is
higher, the writer's fee rises with it."* You do not get to keep the upside clause and
sell the downside one.

**CFO:** I keep the upside because the upside is *earned by the work* and the downside
is caused by *the market*. Those are not the same fact.

**Head of Talent:** They are the same fact from where the writer sits: a number they
were given in writing at acceptance. **Neither concedes.**

---

## 5. Decisions

| # | Item | Ruling | Seat that won | Why |
|---|---|---|---|---|
| 1 | Clause 3B — 120-day backstop | **Ships as-is** | Head of Talent | It is the single most credible recruiting sentence we own; the risk it creates is real but is not what breaks the cash case. |
| 2 | Deposit-coverage gate at acceptance | **New control, outside the paper** | CFO | No engagement accepted where session cost + writer fee exceeds the deposit held, without a named CEO override. |
| 3 | Clause 10 — $25,000 / 3× fee cap | **Ships as-is** | General Counsel | The floor is a defence-costs number; lowering it weakens clause 6 in front of the *buyer*, not the composer. |
| 4 | Clause 10 — *"at no charge and for as long as it takes"* | **Changes** | Head of Talent | Unpaid, unlimited cooperation triggered by a claim being *made* punishes a writer who did nothing wrong. Paid at day rate where the warranty holds; "as long as the claim is live". |
| 5 | Clause 2B — no cure period, no force majeure | **Changes** | Head of Production | *"If the writer withdraws or fails to deliver, nothing is due"* has no cure window and no illness case. Add a 5-working-day cure and pro-rata payment for material actually delivered and used. |
| 6 | Clause 6A — contributor release | **Clause ships; the document is a BLOCKING build** | GC on the clause, Production on the gate | A warranty nobody can discharge is a warranty we have taught the composer to ignore. |
| 7 | Clause 6B — AI human-made warranty | **Ships as-is** | General Counsel | It is the only thing supporting the Constitution's no-AI claim and the Clearance Certificate. |
| 8 | Clause 6B — the disclosure list at delivery | **Changes: build the field on the Rights agent** | Head of Production | Nowhere to list them today. Dissent recorded that 6B should be cut if the field is not live by the third delivery. |
| 9 | Clause 3A — estimate as a floor | **Ships as-is** | *Unresolved; chair* | See CEO ruling. |
| 10 | Clause 3C — perpetual share, no de minimis, no end | **Changes** | General Counsel | Add a de minimis: amounts under $250 accrue and are paid with the next statement or annually. A full 3B statement for $18 is a promise we will break by accident. |
| 11 | Clause 5 — publishing assignment, life of copyright | **Ships as-is** | Head of Talent | It is the clause they stall on and the 50/50 + 3C pairing is the answer. Do not weaken it; **rehearse it**. |
| 12 | Clause 12 — notices effective *when sent* | **Changes** | General Counsel | An email that never arrives should not start a clock. "When sent, and acknowledged or 3 working days, whichever is earlier." |
| 13 | Clause 3B audit right + statements | **Ships as-is** | Head of Talent over GC | Over-lawyered for our size and worth it anyway — it is checkable proof, which is what an unknown studio trades in. |
| 14 | §203 reversion at ~35 years | **Deferred — but recorded as a decision, not an open question** | General Counsel | Academic for campaign advertising; it qualifies "Perpetuity" in `DEFAULT_LICENSE` and a buyer's counsel may ask. |
| 15 | Retained-counsel review | **Deferred, explicitly and with the risk named** | CEO | Signing composer #1 on unreviewed paper beats signing them on none; clause 12 lets v2.1 govern later engagements. |
| 16 | Non-solicitation | **Stays out** | Head of Talent | Unchanged from the lawyer pass: at this stage recruiting is worth more than the protection. |
| 17 | Composer revision rounds vs client rounds | **Operational rule** | Head of Production | The engagement doc states the writer's rounds deliberately. Closing the client-side gap to five rounds must not silently pass through. |
| 18 | Review doc's open item #1 (governing law) | **Correct the record today** | General Counsel | It says the agreement is unsignable by design. It is signable, Florida / Miami-Dade, by default. |

---

## 6. Below market or unfair — said plainly

Four things, and the council does not want them softened in the retelling.

1. **Clause 10's unpaid cooperation.** *"At no charge and for as long as it takes"*,
   triggered by a claim being **made** rather than proven. The harshest sentence in the
   document, aimed at a person who may be entirely innocent. **Changed** (decision 4).
2. **Clause 2B's zero.** *"If the writer withdraws or fails to deliver, nothing is due
   for that engagement."* No cure period. No illness. No force majeure clause exists
   anywhere in v2.0. A writer who delivers a usable 90% and is hospitalised gets
   nothing while we keep the material. **Changed** (decision 5).
3. **The indemnity floor against a spot fee.** $25,000 against a $2,980 engagement is
   **8.4× the fee**, and the council ships it. Head of Talent's dissent stands on the
   record: this is the term we are choosing to be below market on, deliberately,
   because the clearance claim needs it. Say that to the composer rather than hoping
   they do not do the multiplication.
4. **Clause 6A as it stands today.** Asking someone to obtain signatures on a document
   that does not exist is not a hard term; it is an unfair one, because only one side
   knows it cannot be complied with.

*(No market data exists for composer indemnity caps or backstop periods at this tier —
`market-pricing-research.md` prices client-facing work only, and §5 records that
nothing in it is calibrated on Chordential actuals. The council's "below market"
judgements above are reasoned, not sourced, and are labelled as such.)*

---

## 7. Above market — what recruiting leads with

Ordered as Head of Talent will actually say them:

1. **"We pay you within 120 days whether or not the client has paid us."** Clause 3B.
   The industry default is pay-when-paid and silence.
2. **50/50 publisher split** — the review doc: *"Most advertising houses take 100%."*
   And `compensation.py` refuses to file a share to an entity that cannot collect it:
   *"The studio does not keep it by default and does not keep it by silence."*
3. **Clause 3C — the share does not end.** *"For as long as the work earns. This does
   not stop when this agreement ends."* Extensions, territory, exclusivity upgrades,
   buyouts — same 30%.
4. **Your PRO money is yours.** *"It is not the studio's to take, and this agreement
   does not take it."*
5. **Net of session cost.** *"Booking an orchestra is not a fact about the writer's
   work."*
6. **Clause 3A — the estimate is a floor**, and a discount we chose does not touch it.
7. **A statement with every payment, a closed deduction list, and an audit right.**
   *"Nothing else is deducted — not the studio's own time, overhead, software,
   insurance, commission, travel, or any payment to a person or company connected with
   the studio."*
8. **$400 for a demo that loses** — top of the $200–500 range, because *"the thing
   being bought is a stranger's willingness to take it seriously."*
9. **Clause 4B, the reel.** You can show the work and say you wrote it.
10. **Clause 6C's second paragraph.** *"This agreement claims no exclusivity over the
    writer's time and never will."*
11. **`ACCEPTANCE_LIMITS`.** A signed document that tells you it guarantees you nothing.

---

## 8. What we are choosing not to do, and the risk we accept

- **Not putting this through retained counsel before composer #1.** *Risk:* an
  unreviewed instrument governs our first real chain of title, and the clearance
  certificate we sell stands on clauses 6/6A/6B inside it. *Why anyway:* the
  alternative is signing on nothing, and clause 12 confines a defect to engagements
  accepted under this version.
- **Not building the AI-disclosure field before signing.** *Risk:* clause 6B becomes
  the first clause the composer learns is decorative. *Mitigation:* Production's
  three-delivery deadline, recorded as a dissent that expires into a change.
- **Not conditioning the 120-day backstop.** *Risk:* we owe cash on a schedule the
  client does not share. *Mitigation:* the deposit-coverage gate, which is a gate in
  the flow rather than words on paper.
- **Not lowering the indemnity floor.** *Risk:* a good composer's lawyer strikes it and
  we lose a week, or a candidate. *Why anyway:* it is what makes clause 6 credible to
  the buyer, and the buyer is who pays.
- **Not adding non-solicitation.** *Risk:* a composer we introduce to a client is hired
  around us. *Why anyway:* unchanged — recruiting is worth more than the protection at
  this stage.
- **Not building a payout ledger before the first signature.** *Risk:* the 120-day
  obligation exists in the contract and nowhere in the system; nothing tells Jon what
  is owed and when. *This is the gap the council likes least.* The recruiting council
  already scoped it (`talent_payouts`, triggered on invoice-Paid, W-9 first). Clause 3B
  turns it from a nice-to-have into a **liability tracker**.

---

## 9. CEO ratification

> **Ratified. v2.0 goes in front of composer #1, with the five changes in the decision
> table and two overrides.**
>
> **On the backstop (Fight 1).** Upheld as written, and I want the reasoning recorded
> because it will be tested the first time cash is tight: we do not get to write the
> Constitution's promise that a creator is *"treated with respect and paid promptly"*
> and then means-test it in the paper. The CFO is right that the anthem breaks, and
> right that it breaks on the session, not the writer. The deposit-coverage gate is
> approved and it is **mine to override, per engagement, in writing** — the machine
> proposes, I dispose, and that includes disposing badly on purpose with my name on it.
>
> **Override 1 — clause 6A is blocking, and so is the record.** No composer signs this
> until the **contributor release exists**. GC and Production agreed on that; I am
> making it a gate rather than a priority. I will not put my signature under a
> clearance certificate that rests on a document we never wrote. And **correct
> `composer-agreement-review.md` today** — telling counsel the agreement is unsignable
> when it is signable by default is exactly the kind of quiet drift the honesty rule
> exists to catch, and it was in a document whose whole job is to be the true record.
>
> **Override 2 — Fight 4 goes to Head of Talent, and further than she asked.** Clause
> 3A ships as-is. The CFO's distinction between earned upside and market downside is
> intellectually correct and operationally invisible to the person holding the number.
> Adding to it: when we discount below the estimate, **the writer is told** — not asked
> to agree, just told, in the statement, that the price moved and their number did not.
> The clause already protects them; the disclosure is what makes it feel like a
> promise instead of a technicality.
>
> **On the indemnity.** $25,000 stands. Head of Talent's dissent stands with it, and it
> goes in the recruiting conversation out loud: *"this number is bigger than your fee,
> here is why it exists, and here is what we pay for if the claim is wrong."* We do not
> get to be the studio that treats composers well and also the studio that hopes they
> do not read clause 10.
>
> **On Production's dissent.** Accepted with the deadline. If the 6B disclosure field
> is not live by the third delivery, **6B gets cut, not carried** — a dead clause in an
> honesty-critical document is worse than a shorter one, and I would rather explain a
> narrower warranty than defend one we never collected under.
>
> **Sequencing:** contributor release (blocking) → the five text changes → v2.1 rebuilt
> and re-hashed through `signing.py` → composer #1 → the AI-disclosure + contributor
> fields on the Rights agent → the payout ledger, because clause 3B just made it a
> liability tracker and not a convenience.

---

*Recorded 2026-08-18. Seats: CFO, Head of Talent, General Counsel, Head of Production.
Chair and ratification: Jon Shipp. Unresolved on the record: Head of Talent does not
concede the $25,000 floor; Head of Production does not concede that clause 6B should
survive an unbuilt disclosure field; the CFO does not concede clause 3A.*
