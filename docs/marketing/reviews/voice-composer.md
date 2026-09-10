# Voice review — read as a working composer

*A composer who scores commercials and brand films decides whether to write for this
house. Judged only against what is in the files; comparisons to normal practice are my
own read and marked as such.*

---

## 1. The terms, judged

I read `composer_agreement.py` before a word of the marketing, because that is the only
document that can lie to me slowly.

**What I am paid.** Clause 3: *"A share of NET CREATIVE REVENUE for the engagement: 30%,
rising to 40% where the writer also orchestrates or produces the recording session."* Net
is defined, and the deductions are a **closed list** (3B): *"Nothing else is deducted —
not the studio's own time, overhead, software, insurance, commission, travel, or any
payment to a person or company connected with the studio."* Most net deals I have been
offered have neither a closed list nor a related-party exclusion. My read: above the norm.

**3A.** *"If the price the client finally pays is higher, the writer's fee rises with it…
A discount the studio chose to give is not a fact about the writer's work either."* A
one-way ratchet. I have never been offered one.

**3B, when.** Within 30 days of the client settling, *"and in any event within 120
days of the client accepting delivery, whether or not the client has paid"*, plus: if the
studio has not invoiced within 30 days, I am paid as though it had. An itemised statement,
and a yearly audit the studio pays for if I was short by more than 5%. Good clauses. But
**120 days is not "fast"**, and there is **nothing up front**.

**3C.** *"If the client later pays to extend the term, widen the territory, add media,
take exclusivity, upgrade to a buyout… the writer is paid the same 30% share of the net
of that payment… for as long as the work earns. This does not stop when this agreement
ends."* This is the clause that decides the whole document.

**Free work.** None. Clause 2 requires scope, dates and fee in writing *before* I accept;
a requested demo that loses is *"paid a flat $400"* (`compensation.DEMO_FEE`). Revisions
inside the stated rounds are in the fee, beyond them *"scoped and paid separately, never
assumed."* Silence for 5 working days after delivery is acceptance. Kill fee (2B): 50%
before delivery, 100% after, same if I am replaced for anything but failing to deliver.

**What I grant.** Clause 4: masters, stems, alternates, **session files, MIDI and project
files**, worldwide, life of copyright, on creation. Clause 5: *"The writer assigns to
Chordential Music the whole of the copyright in the composition — the publishing — for the
life of copyright."*

**What I keep.** The writer's share of performance income: *"It is not the studio's to
take, and this agreement does not take it."* Half the publisher's share — and with no
publishing entity of my own the house *"holds that half FOR the writer"*, tells me in
writing, and files or pays it over within 30 days of my naming one: *"does not keep it by
default and does not keep it by silence."* Cue sheet filed within 30 days of first
broadcast, copy to me. Reel rights after release (4B). Cue-sheet credit is a promise;
client credit is only *"a promise to ask"* — at least said honestly.

**Verdict: a fair deal, edging good, and clause 3C decides it.** A full life-of-copyright
publishing assignment is ordinarily where I stop reading. 3C turns it from a buyout into a
continuing interest: every later payment to widen the grant pays me again, and it survives
the agreement ending. Take 3C out and this is a below-market buyout in warm language. It
is in, so I would sign — after these are fixed.

**Missing, and I would not sign without them:**

1. **Rights do not revert if I am not paid.** Clause 4 assigns on creation; 2B revokes the
   grant if *I* fail, and nothing revokes it if the *studio* fails to pay at 120 days — no
   interest, no remedy, no reversion. A studio with no clients is exactly where this
   matters. One sentence fixes it.
2. **No reversion, ever, on the publishing** — not if the cue is never broadcast, never
   used, or the studio dissolves. An unused cue should come home.
3. **No money up front**, at acceptance or delivery. On a job that dies at 120+ days I
   have financed the studio.
4. **The "cap" is bigger than the fee.** Clause 10: *"capped at the greater of $25,000 and
   3 times the fees the studio has paid the writer."* On a single-cue fee, $25,000 is a
   multiple of what I earned. Presented as protection; read again it is an exposure floor.
   Put it at 1× fees actually received.
5. **6C's restraint is undefined and unpaid** — *"a materially similar cue for a competing
   brand in the same product category"* for 12 months. Nobody can adjudicate "materially
   similar", and it costs me work in the only category I sell into.
6. **6A makes me your contracts administrator** — collecting releases from every player,
   singer and programmer, unpaid, on my time.

**Two places the code does not match the clause — fix them before a writer finds them.**

- Clause 3 bases my fee on *"the CREATIVE FEE the client pays… as itemised on the client's
  proposal"* and excludes the licence fee. `db._writer_fee_per_head` computes it from
  `est.suggested_price` — the figure `pricing.build_quote` says it deliberately does not
  use, because it folds usage in. The ledger owes me a share of a price the proposal does
  not show.
- `db.ensure_project_payouts` pays a writer their flat `talent.rate` whenever one is on
  file, falling back to the 30% policy only when it is not; `recruiting.compose_review_decision`
  tells a new writer *"our standing rate for this work is $X/hr"*. Nothing in the agreement
  lets an hourly rate replace the share. Two pay models, and the one I signed loses.

---

## 2. Creator-facing copy that would put me off

| Line | File | Why it lands badly on a composer | Replace with |
|---|---|---|---|
| "The music is always yours to be proud of; the paperwork is ours to carry, so the rights are clean." | `public/for_artists.html` | The paperwork assigns my composition for the life of copyright. Warmth describing the clause that takes the asset is the tell of a house that supports artists and hands you a buyout. "Yours to be proud of" is what you say when you cannot say "yours". | "You assign the master and the publishing. You keep your writer's share, half the publisher's share, and 30% of every later payment to widen the licence, for as long as it earns. Read the agreement first." |
| "we treat creators with respect and pay fast" | `recruiting.py` offer block | "Respect" is not a term. "Fast" is — and the backstop is 120 days with nothing up front. I will find that, and then the rest is suspect. | "We pay within 30 days of the client settling, and within 120 days of their accepting delivery whether or not they have paid." |
| "Clear scope, defined deliverables, and prompt payment." | `for_artists.html` | Three abstractions where three real numbers exist (5-day acceptance, 50% kill fee, 120-day backstop). Vagueness about money is the thing I screen for. | The three numbers. |
| "a curated roster of creators" / "When you're on the roster, you're on the roster." | `for_artists.html` | No roster is signed — `00-brief.md` §13.8 rules exactly this. The second sentence means nothing. | "No creator has signed yet. You would be among the first, and the terms are published above." |
| "First-look on fit work" / "you hear first" | `for_artists.html`, `recruiting.py` | First-look is a term of art that normally carries consideration; nothing in the agreement grants it. A promise the contract does not contain is one I discount. | "When a brief matches your craft you are offered it before anyone outside the roster. Not exclusive, and it binds neither of us." |
| "A curated invite from Chordential, {name}" / "your profile is the kind of work we want to bring real briefs to" | `recruiting.py` subject, `_why_them` | Calling your own invitation curated asks me to be flattered by it; the second fires when you have no credit to name, and says you listened to nothing. | "Chordential — a brief, and our terms". Send nothing until you can name a piece. |
| "Original, cleared work, fixed scope, clean rights, same terms as always." | `recruiting.compose_project_assignment` | "Clean rights" from my side means I gave them up. The mail carries a rate but not the creative fee it is a share of — the docstring says *"the client's budget isn't theirs to see"*. If I am paid 30% of net creative revenue, that number is not the client's budget, it is the basis of my fee. | The creative fee, the session cost deducted, the share, the result — what 3B requires on payment, said at the offer instead. |
| "your room will be dressed and waiting here" / "Signing it is what lets us put you on paid work." | `creator_portal.html` | Set decoration, and dispatch language. Both put me on the supply side. | "When you take an engagement, the brief, the picture and the client's notes are here." / "…lets us book you." |
| "…they reach you here the moment they are cleared. Nothing to do yet." | `creator_portal.html` | "Cleared" reads as the client being filtered before reaching me, and "nothing to do yet" tells me how to feel about my own job. The rule underneath — price a note before it becomes work — is in my favour. Say that. | "We price each note before it reaches you so nothing becomes unpaid work by accident. You will see them, and what they cost, as soon as that is done." |
| "the client never hears unvetted work." | `creator_portal.html` | My work is the thing being described as unvetted. | "Your take comes to us first, so the client hears it with the context we agreed." |
| "structure first, not noodling" | `showcase.py` `STEPS` | Client-facing, but I read it before applying. "Noodling" is a non-writer's word for what writing looks like from outside the room. | "structure first." |
| "Music rarely fails creatively. It fails operationally." | `showcase.py` `PROBLEM` | *"The music is the easy part"* in a suit — the sentence your own brief bans outright (§0.4). The line most likely to cost you a composer who otherwise liked the terms. | "Music rarely fails in the writing. It fails in the last mile — approvals, versions, paper." |
| "If you write, and you've never heard your own work played by real players in a real room, that's who this is for." | `04a-the-first-posts.md`, Fri 25 Sep | Aimed at me, and it assumes I have not. Plenty of working advertising composers have — it is the budget that vanished, not the experience. | "If you write, and the last time you had real players was a budget nobody approves any more — that is what the room is for." |

Two things I would not touch: the demo blurb in `showcase.py` (*"a music house should not
put machine-made music on its own site"*) and clause 6B's AI warranty with its named list
of permitted processing. Both know what the line costs.

---

## 3. The founder's position

Genuine, because the specifics are the wrong shape for a pitch. *"I have a folder full of
unfinished things… I used to compose. I stopped."* Nobody invents that. The studio he
walked away from, and *"I started with advertising because that's where the budget to pay
a composer properly still exists"* — someone who looked at where the money is rather than
where the romance is. That buys more with me than any supporting-artists language would.

Where it reads from outside: *"Some people don't stop. They gave up other lives to keep
going, and they can sit with an idea for six weeks."* That is a composer's life painted by
someone who left it. Most of us renounced nothing; we kept taking the work and got worse
at everything else. Narrating my sacrifice back to me is writing about a character.

And put the ownership on the page I actually read. *"Own the place where people who did
commit their lives to composing get paid"* is honest — and it is on LinkedIn, while
`for_artists.html` gets "curated roster". Tell me directly: he owns it, I do not, here is
the split, here is what I keep. That beats warmth.

---

## 4. What would make me say yes, in order

1. **The whole Composer Agreement, published, before I apply** — the text, not a summary.
   You already generate it deterministically; link it from `/for-artists`.
2. **The three numbers in the recruiting copy**: 30% of net (40% with orchestration),
   50/50 publisher's share, $400 for a requested demo that loses.
3. **Rights revert if I am not paid**, and something paid up front.
4. **One engagement priced in writing with the creative fee shown**, so I can check the
   share against its base myself.
5. **A named first client, even a small one.** I will take the risk of being first, not of
   being first indefinitely.
6. **The cap at 1× fees received**, or the $25,000 floor struck.

**In a first message from him**, four sentences: what the brief is, what the fee is and
what it is a percentage of, that no client has paid yet, and where the terms are. No
"curated", no "respect". One line about something specific of mine that he has actually
heard, and I reply.

---

## 5. The one thing that would make me say no immediately

Being asked to write anything — a test cue, a "quick idea to show the client the
direction", a pass on a brief that has not been sold — without a written fee. Clause 2 and
the $400 demo fee already forbid it. If practice contradicts the document, the document is
decoration and nothing else in it is worth reading.

The near-miss: an offer quoting me an hourly rate instead of the share. Fix
`ensure_project_payouts` and that acceptance email before a writer signs, or your first
conversation with a composer is about which of your two numbers is real.

---

## 6. The chamber orchestra room

It moves me, and I distrust that it moves me. A room where a composer dials in and conducts
real players is what most of us stopped expecting — which is why it is the easiest thing
here to say and the hardest to build.

Hold it back. Not because it is dishonest: the Friday post is careful (*"It does not exist
and I'm not pretending it's close"*), and on his own feed, as his own ambition, it earns
him something. But in a first message to me it inverts the order — I read the room, then
read the terms through it, and discount both. Fee, split and the 120 days first; the room
on the second call, or when there is a lease.

And mention it as his, not as mine. *"That's who this is for"* asks me to want it with him
before he has paid me anything.
