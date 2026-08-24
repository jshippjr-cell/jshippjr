# The Call Copilot — a plan

> *"Asking all the questions after the call goes against Chordential's promise to capture
> everything from the beginning."* — the operator, 2026-08-14

## The problem, stated precisely

The Halden brief closed with fourteen open questions. Every one of them was a real gap, and
**every one of them was findable during the call.** Nine were licence and rights terms that
take about forty seconds each to ask. One was a name that did not match a record we already
held. The rest were conflicts between two things said minutes apart.

Filtering that list so it stops embarrassing us in front of a client (`client_voice.py`,
shipped) is a fix to the *symptom*. The disease is that the machine only starts thinking
after everyone has hung up. It is a very good listener with no ability to raise its hand.

This changes the machine's job. Today it **transcribes then reasons**. The copilot makes it
**reason while it transcribes**, and gives that reasoning one and only one output: a short,
live list of what has not been covered yet, in front of the person who can still ask.

It also fixes something the current design cannot: **a question asked on the call gets an
answer.** A question emailed afterwards gets a reply if you're lucky, a partial reply if
you're normal, and silence if the client is busy — and then it becomes an assumption, which
is how a wrong number reaches a proposal.

## What it is

A panel beside the call. Not a bot in the meeting, not a second participant, not anything
the client sees or hears. **The client never knows it exists**; it is a prompt sheet that
keeps score.

```
  DISCOVERY · Halden × Fieldhouse                          14:32 elapsed
  ─────────────────────────────────────────────────────────────────────
  ✓ Budget            $55–65k, hard ceiling, USD, licence incl.   14:02
  ✓ Timeline          Oct 3 air · delivery 3wks prior             09:41
  ✓ Deliverables      6-min master + 6 cuts + stems               06:20
  ✓ Approver          Tom Vasquez, Halden brand director          17:55
  ✓ References        Jóhannsson / Guðnadóttir · NOT EitS         12:10
  ─────────────────────────────────────────────────────────────────────
  ○ Licence term      "How long do you need the usage to run?"
  ○ Territory         "Where does this run — US, or worldwide?"
  ○ Publishing        "Any expectation on who holds publishing?"
  ○ Payment terms     "What does your payment schedule usually look like?"
  ─────────────────────────────────────────────────────────────────────
  ⚠ You have two names for the approver: Haiden Jones (on file) and
    Tom Vasquez (this call). Worth asking which is right.
```

Three states, and the middle one is the whole point:

- **✓ covered** — heard, with the value and the timestamp. Clickable to jump to that moment
  in the recording afterwards.
- **○ not yet** — with the actual sentence to say. Not a topic label; a question, in the
  operator's voice, ready to read aloud.
- **⚠ worth resolving now** — a contradiction, or a mismatch against a record we hold. These
  are the ones that cost the most later and take ten seconds to settle live.

At the end: *"Everything covered"*, or a short list of what to raise before hanging up.
Both parties leave knowing the brief is complete, which is the promise.

## Why this is buildable without new invention

Almost all of it already exists and is pointed the wrong way.

| Needed | Already have |
|---|---|
| Live transcript | Recall streams it — we currently only fetch the final artifact |
| The checklist | `CANONICAL_FIELDS` — ten slots, and the copilot's job is filling them |
| The rights topics | `client_voice._DEFERRABLE_TOPICS` — the nine that keep recurring |
| Slot routing | `canonical_slot()` — same function, same rules |
| "Covered" detection | the same extraction, run on a window instead of a whole call |
| Conflict detection | already produces those records; today they arrive too late to use |

The one genuinely new thing is **cadence**: reasoning over a rolling window while the call
runs, rather than once at the end.

## Build order

Each phase is useful on its own and shippable alone. That is deliberate — an unfinished
copilot must still leave the operator better off than no copilot.

> **Status, 2026-08-24.** Phase 0 **shipped** (`call_prep.py`, `/opportunity/{id}/prep`).
> Phase 1 **shipped** (`call_prep.score_call`, scored onto the same page). Phase 2 is next
> and is now judgeable, which was the point of doing them in this order.

### Phase 0 — The prep sheet *(no live anything; ~half a day)*
Before the call, render the checklist as a static page from the opportunity: which of the
ten slots we already know from intake, which we do not, and the exact question for each
gap. Print it, keep it on a second screen, tick by hand.

**Ships the value of the whole idea at 5% of the cost**, and it is the honest first move:
if the operator does not find the sheet useful on paper, no amount of real-time makes it
useful. It also generates the question bank the later phases need, and the bank is the part
that must be *written well* rather than engineered.

### Phase 1 — Post-call scoring *(~a day)*
Run the checklist against the finished transcript and report coverage: *"11 of 15 covered;
missed licence term, territory, publishing, payment terms."* No live component at all.

This is the **measurement** phase, and it exists so Phase 2 can be judged. It answers "does
detection actually work" using calls that already happened, at zero risk and no new spend.
It also gives a number worth watching on its own: coverage per call, over time.

**What Phase 1 turned out to be, once built.** Two things the plan did not anticipate, both
worth carrying into Phase 2:

*Coverage is not one number, it is three.* "Covered" hides the most useful cell. A slot can
be **answered** (a value reached Campaign Intelligence from this call), **raised** (the
topic demonstrably came up and nothing landed), or **missed**. *Raised but not answered* is
the interesting one: the question **was** asked and the answer did not stick, which needs a
different fix from "nobody asked". Counting CI fields alone cannot see that state at all,
and it is most of why this phase is worth building rather than skipping to the panel.

*The detector's danger is exactly where the plan said, and it is worse than it looks.* A
first draft of the cues produced false ticks on ordinary sentences — "the music needs to
feel **exclusive** and premium" ticked the *exclusivity* term (the single most expensive
one on the sheet); "reconvene at **2:30**" ticked *deliverables*; "**one year** ago" ticked
*licence term*; "the **brand team** sits in New York" ticked *the brand*; "the European
**Union** rules" ticked *musicians*; "**tone of voice** guidelines" ticked *emotional arc*.
Every one is a plausible line on a real call. The cues are tightened and a bait transcript
made of exactly those sentences is a permanent test that must score **zero**.

Two rules came out of that and both belong in Phase 2:

- **Every tick carries the sentence that produced it**, printed. A tick you cannot check is
  worse than no tick, because the whole risk here is manufactured confidence.
- **`raised` never claims an answer.** A keyword can prove a topic came up. It cannot prove
  anything was said back, and the moment it pretends otherwise the panel starts lying
  quietly.

### Phase 2 — Live, one-way *(the real build)*
Recall's real-time transcript over a websocket; a rolling window; slot detection on each
window; the panel updates. Read-only, no interaction beyond marking a line covered by hand.

Cost control, which matters here because this runs *per minute of call* rather than once:
- detection on a window is a **small** job, so it runs on the economy model
  (`providers.model_for` already makes this choice);
- only windows containing new speech are examined;
- once a slot is covered it is **no longer looked for** — the work shrinks as the call goes
  on, which is the opposite of how the current end-of-call run behaves;
- a hard per-call ceiling, and the panel says plainly when it stops rather than going quiet.

Budget the whole thing against `ai_budget`: a call the operator is sitting in is
asked-for work by definition (ADR-0023), so this is inside the approved path, not a
speculative sweep.

### Phase 3 — Resolve it live
The ⚠ items become one-click: *"Haiden Jones or Tom Vasquez?"* → pick → the record updates
before the call ends. This is where the copilot stops being a checklist and starts being
the thing that makes the after-call summary short by construction, because there is nothing
left to ask.

## Where the questions come from

Not from a model. From a **written bank**, in the repo, versioned, because these are sales
craft and they should read like a person wrote them:

- one canonical question per slot, in the operator's voice;
- a *follow-up* for each, for when the first answer is partial ("and is that inclusive of
  the licence?");
- a **trigger**, so a question appears only when it applies — no point asking about
  broadcast territory for a piece that only ever runs on a website.

The bank is the deliverable most worth getting right and the least technical. Phase 0
produces it, and every later phase just changes when and how it is shown.

## What would make this fail

Named up front, because each is a way to build the wrong thing:

- **It becomes a script.** A rep reading a form is worse than a rep having a conversation.
  The panel must be glanceable and ignorable — it never blocks, never nags, never beeps.
  If it makes calls feel worse, it is deleted.
- **It fires wrong.** Marking something covered when it was not is worse than not being
  there, because it manufactures false confidence. Detection must be conservative:
  ambiguity leaves a line **open**, not ticked. A missed tick costs one repeated question;
  a wrong tick costs a wrong proposal.
- **It costs per minute.** See the ceiling above. A call that quietly spends more than the
  engagement is worth is a failure regardless of how well it works.
- **It leaks.** The client must never see it, hear it, or receive anything derived from its
  *unresolved* state. It informs the operator; it does not become another client artifact.

## The first commit

Phase 0. A `/opportunity/{id}/prep` page: the ten slots plus the recurring rights topics,
each showing either what we already know or the question to ask, printable, no model call,
no live anything.

If it makes the next call better on paper, the rest is worth building. If it does not, the
plan was wrong and the cheapest possible version of it said so.
