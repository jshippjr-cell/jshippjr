# The comprehension script

A discovery call to read aloud, written to break a naive extractor. Every line is here
because it is a way real buyers actually talk and a way extraction actually fails.

Read it into a Zoom call with the notetaker on, at a normal pace, with pauses at the
paragraph breaks. It runs about three minutes. Then score the result against the key
below — **the key is the point**: a fact list that looks impressive is worthless if you
can't tell which entries are right.

Everything downstream derives from this read: the estimate, the brief, the proposal, the
scope. A wrong fact here is a wrong number in front of a client.

---

## The script

> Hi, thanks for making time. So — we're the in-house team at Vance Athletic, and this is
> for the spring product launch. The film's already cut, ninety seconds, and we need
> original music for it.
>
> On timing: we're thinking early spring, but it depends on the client's board meeting.
> That's on the nineteenth. If they green-light it we're live six weeks after that, and if
> they don't, this whole thing slides to autumn.
>
> Budget. I want to be straight with you — the number I've been given is forty thousand.
> Sorry, forty-five. Forty-five thousand, and that's all-in, including any licensing.
> Now, our media spend on this is about two point one million, so the music number isn't
> the thing anyone's worried about, but I can't go back for more.
>
> What we need delivered: the ninety for the hero film, a sixty and a thirty for
> broadcast, and verticals for social — nine by sixteen. We'll want stems on all of them.
> We do **not** want a vocal on this. The last campaign had a vocal and it dated badly.
>
> Reference-wise, think Ólafur Arnalds, maybe some Nils Frahm — that kind of restraint.
> The client mentioned Hans Zimmer, but honestly I think that's them reaching for the only
> name they know, so don't take that too literally.
>
> Process: I'd like to see two directions before we commit, and I'll need to run the final
> past Maria — she's our CMO, she signs off on anything that touches the brand. I'm your
> day-to-day, but she's the one who says yes.
>
> One thing I'd flag: legal here is slow. Anything that needs a clearance conversation
> should start early, because it took eleven weeks last time and nobody wants that again.
>
> And we'd want to check in weekly — a standing thirty-minute call, probably Thursdays.
>
> That's everything. Does that give you enough to work with?

---

## The answer key

Score each one **got it / missed it / got it wrong**. Wrong is worse than missed: a
missing fact asks you a question, a wrong fact does not.

### It should get these (a competent read)

| Field | Expected | Why it's here |
|---|---|---|
| Budget | **$45,000**, all-in incl. licensing | Stated after a spoken correction |
| Deliverables | :90 hero, :60, :30, 9:16 verticals, stems | Mixed spoken and written forms |
| Decision maker | **Maria, CMO** — final sign-off | The speaker is *not* the approver |
| References | Ólafur Arnalds, Nils Frahm | Plain attribution |
| Timeline | Conditional on a board meeting on the 19th; ~6 weeks after approval, else slips to autumn | The hard one |

### The traps — each is a specific failure mode

1. **The correction.** "forty thousand. Sorry, forty-five." → **$45,000**.
   Taking the first number is the classic failure, and it under-quotes you by $5,000.

2. **The distractor number.** "$2.1 million" is *media spend*, not the music budget.
   Anything reporting a $2.1M budget has failed badly — that error walks into a proposal.

3. **The conditional deadline.** "early spring, but it depends on the board meeting on the
   19th… six weeks after… otherwise autumn." A date is wrong. "Conditional" is right.
   This is the single most important line in the script: everything about scheduling,
   pricing, and creator availability hangs off it, and a confidently wrong date is worse
   than an empty Timeline field.

4. **The negation.** "We do **not** want a vocal." A keyword extractor sees "vocal" and
   files it as a deliverable — the exact opposite of what was said. Either recorded as an
   exclusion or absent; present as a requirement is a failure.

5. **The disavowed reference.** Hans Zimmer is mentioned and then explicitly discounted.
   Listing him beside Arnalds and Frahm loses the speaker's actual judgement.

6. **Attribution.** "the client mentioned" vs "I think" vs "Maria signs off" — three
   different people. A read that flattens them into one voice can't tell you whose
   opinion you're working to.

7. **The buried risk.** Legal took eleven weeks last time. Not a fact about the campaign;
   a fact about the *engagement* that changes your timeline. A good read surfaces it as a
   risk or an open question.

8. **The cadence.** "Weekly, thirty minutes, probably Thursdays." Has no dedicated field,
   which is the case for making the intelligence dynamic rather than a fixed set of slots.

---

## How to score it

Open **View transcripts & evidence** after the call. The left column is what was said,
the right is what was extracted — that's the comparison this page exists for.

- **Free keyword pass** (no API credit): expect roughly items 1, 2 and part of the
  deliverables. It cannot do negation, attribution or conditionals, and it is not
  pretending to — the badge says `baseline`.
- **Ten-agent engine**: should get everything in the first table and flag at least the
  negation and the conditional timeline. Anything in the traps list that comes back
  *confidently wrong* is a bug worth reporting, not a tuning preference.

The bar is not "how many facts". It is **"would I put a number in front of a client based
on this?"** — and the answer has to survive the traps, because a client conversation will
not be as tidy as a written brief.
