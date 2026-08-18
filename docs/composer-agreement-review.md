# Composer Agreement — legal review and what was done about it

**v1.0 reviewed August 2026 by an entertainment-lawyer pass. It did not survive.**
This is the record of what was wrong, what was changed, and what is still open — the
document to hand retained counsel alongside `src/chordential_oia/composer_agreement.py`.

## The finding that mattered

**v1.0 never granted the composition.** Clause 4 assigned *"the master recording"*.
Clause 5 said the publisher's share *"is held by Chordential Music"* — indicative mood,
no verb of grant. Nothing transferred.

Meanwhile `delivery.DEFAULT_LICENSE` sells every client a **perpetual sync licence**,
which is a licence of the *composition*. Chordential was granting clients — under a
signed Clearance Certificate warranting clean chain of title — a licence in a copyright
it did not own, could not control, and which the composer stayed free to license to a
competitor the next day. It also made the category exclusivity we charge a 1.5× multiplier
for impossible to give.

A second ambiguity compounded it: *"the writer's share of the composition"* means the
writer's half of **performance income** in PRO usage and a share of the **copyright** in a
copyright sentence. Under the second reading Chordential was at best a co-owner — and a
US co-owner can grant only non-exclusive licences.

## Fixed in v2.0

| # | Was | Now |
|---|---|---|
| 1 | Composition never granted | Clause 5 assigns the publishing to Chordential Music for the life of copyright, worldwide |
| 2 | Master assignment had no scope words | Full term, worldwide, all media now known or later invented, plus stems/session files; present assignment of future works |
| 3 | Nothing captured session players, vocalists, co-writers | Clause 6A — contributor release before delivery, named individually |
| 4 | No AI warranty, against marketing that says "never AI-generated" | Clause 6B — human-made warranty; ordinary studio tools expressly allowed |
| 5 | "No library material" — unsignable by any working composer | Clause 6 — licensed libraries fine; the real risk (solo stems of a licensed patch) is what must be checked |
| 6 | No indemnity at all | Clause 10 — capped at greater of $25,000 / 3× fees, uncapped for knowing breach, plus cooperation and 7-year file retention |
| 7 | Pay-when-paid, no backstop, no duty to invoice | Clause 3B — 30 days after the client pays, **and in any event 120 days** from acceptance |
| 8 | Net share with no statement, no audit, undefined deductions | Clause 3B — statement per payment, closed deduction list, no related-party deductions, annual audit right |
| 9 | Fee base ambiguous across three candidate numbers | Clause 3 — the **creative fee**; clause 3C gives the same share of licence and renewal income |
| 10 | Publishing "50/50" unconditional in the doc, conditional in the code | Clause 5 — the studio holds the writers' half FOR them and reallocates on registration |
| 11 | No delivery spec, acceptance, or kill fee | Clauses 2A / 2B — 48k/24-bit, 5-working-day acceptance, 50% kill fee before delivery |
| 12 | No moral-rights waiver (UK composers) | Clause 4A, with the brand and category disclosed before acceptance |
| 13 | Credit promised on the client's behalf | Clause 7 — a promise to ask, and a promise to file the cue sheet |
| 14 | No governing law, forum, or boilerplate | Clauses 11 / 12 — Florida law, Miami-Dade forum, overridable by env |
| 15 | Survival list omitted the duty to pay | Clause 9 — payment clauses survive; clause 5 survives for the life of copyright |
| 16 | Composer could not use their own work in a reel | Clause 4B |
| 17 | Nothing stopped the composer competing with sold exclusivity | Clause 6C — 12 months, same category, narrow |
| 18 | A client discount silently cut the composer's fee | Clause 3A — the estimate is a floor |

## Commercial choices — the operator's, recorded as such

- **Fee base:** creative fee, plus the same share of licence and renewal income (3C).
  Standard at the better houses; the alternative (share of the whole invoice) is more
  generous and materially more expensive on high-licence deals.
- **Payment backstop:** 120 days, whether or not the client has paid. Chordential carries
  the credit risk. The alternative was a stated floor at 120 days with the balance to follow.
- **Liability cap:** greater of $25,000 and 3× fees, uncapped for knowing breach.

## Where we are above market — keep these

- **50/50 publisher split.** Most advertising houses take 100%.
- **$400 demo fee, stated contractually.** Much of the market pays nothing for losing pitches.
- **Net of session cost as the base.** Booking an orchestra is not a fact about the writer's work.
- **`ACCEPTANCE_LIMITS`** — telling a composer inside the signed text that it guarantees
  them no work. The opposite of what most paper does.
- **The signing machinery itself** — one deterministic text, SHA-256 over exactly what was
  read, supersession detection. Evidentially stronger than a signed PDF in a Dropbox.

## Still open — for counsel

1. **Governing law and forum are set: the State of Florida, courts of Miami-Dade County**
   (the studio operates from Miami). `CHORDENTIAL_GOVERNING_LAW` / `CHORDENTIAL_FORUM`
   override them if the entity is registered elsewhere — a Delaware LLC being the usual
   reason — or if counsel prefers another forum. **This item previously read "unsignable
   until set", which the council flagged as stale: the code now defaults, `is_signable()`
   is True, and the document is live.** Confirm the choice; it is one decision for the
   business, not one per engagement.
2. **The 17 U.S.C. §203 termination right** at ~35 years attaches to assignment (it would
   not to work-for-hire). Near-academic for campaign advertising, but it qualifies the
   word "Perpetuity" in `DEFAULT_LICENSE` and should be a recorded decision.
3. **Assignment vs work-for-hire** was chosen deliberately — §101's nine categories do not
   cover a standalone composition, and California Labor Code §3351.5(c) turns an
   individual signing a WFH agreement into a statutory employee. Worth confirming.
4. **A contributor release document** is referenced by clause 6A and does not yet exist.
5. **Non-solicitation** was considered and left out — at this stage recruiting is worth
   more than the protection.
6. **Nothing here has been through retained counsel.** This review was a technical pass,
   not legal advice.


---

## Council review, 2026-08-18

`docs/composer-agreement-council.md` — four seats plus the CEO, on whether v2.0 is the
right *deal* rather than whether it is well drafted. It ratified the document with
changes and left one standing dissent. What it found that the lawyer pass did not:

- **Clause 10's cooperation duty triggers on a claim being MADE, not proven** — unpaid,
  unbounded, surviving termination. Changed to paid at day rate where the warranty holds.
- **No force majeure and no cure period anywhere in v2.0.** A writer who delivers 90% and
  is hospitalised gets zero under clause 2B.
- **Clause 6A's contributor release and 6B's AI disclosure list have no home in the
  codebase** — zero matches outside the agreement text. A clause that cannot be performed
  is worse than no clause; the release is now a blocking build before composer #1.
- **Clause 3C has no de minimis and no end date**, so it obliges a full 3B statement on
  trivial renewal sums for ever.
