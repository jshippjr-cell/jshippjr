# Sequencing Council — Latency vs. Read-Only MCP

**Convened to answer:** Does reducing opportunity latency create more business
value than building read-only MCP access — and what is the single highest-leverage
next step?

**Hypothesis on the table (Jon's ordering):**
1. Gmail MCP ingestion → 2. Freshness scoring → 3. Agency intelligence signals →
4. Opportunity lifecycle tracking → 5. Core read-only MCP

**Personae:** CEO · CTO · COO · CFO · CMO

---

## 0. The fact that reframes the debate

Before anyone argues, the CTO puts one slide up:

> **"Freshness scoring is already built and shipping."** `signals.py` ranks the
> radar by `score × e^(-age/τ)`, τ=12h. Web Push + the new app-icon badge mean a
> fresh gig reaches Jon's phone in near-real-time. So item #2 is *done*, and the
> phrase "opportunity latency" is doing two jobs at once:
>
> - **Time-to-see** (source → Jon's awareness) — *already near-zero.* Webhook
>   intake is real-time; push is real-time.
> - **Recall** (does the gig enter the system *at all*) — *the real gap.* The
>   regex parser in `intake.py` silently drops anything it can't pattern-match.
>   A missed opp isn't "late" — it's **infinite latency**.

This single distinction collapses half the disagreement. "Reduce latency" really
means "**stop missing opportunities**," which is a *recall* problem, not a *speed*
problem. Hold that thought.

---

## 1. The debate

### CEO — "What kills us is the deal we never saw."
The existential risk isn't seeing a gig three minutes late; it's a marquee agency
brief that never entered the funnel because the parser choked on its formatting.
That's a 100%-loss event, invisible in our metrics because we don't know what we
missed. So **recall beats everything** — and Gmail MCP, by letting an agent *read
and judge* each email instead of regex-matching it, is a recall play. I back
ingestion first.

> **CFO rebuts:** "Back it with what number? We're asserting we miss opps. We have
> no measurement of the miss rate. We could spend two weeks on Gmail MCP and
> recover three junk leads. Show me the leak before you fund the patch."

> **CTO rebuts:** "And you can't fund freshness or agency intel *blind* either.
> Every downstream phase needs to query what the system currently captures. We
> have no instrument."

### CTO — "Build the instrument before the optimization."
Read-only Core MCP is **days of work, zero new data, zero risk** — a thin wrapper
over existing `db.py` reads. Its first job isn't analytics for Jon; it's
**observability for us**: "how many inbound emails became opportunities vs. were
dropped? what's the source mix? where's the funnel leaking?" That answers the
CFO's question *and* tells us whether we're supply-constrained or
attention-constrained — which determines the entire rest of the order. Measuring
is cheaper than guessing. **Core MCP (read) first — as the measurement step.**

> **CEO rebuts:** "I don't want a beautiful dashboard about a starving funnel.
> Measurement that doesn't change a deal outcome is overhead."

> **COO concedes partially:** "But I'll take three days to know if my operator is
> drowning or idle before I spend three weeks. That's not overhead, that's
> diligence."

### COO — "The binding constraint is Jon's attention, not data volume."
This is a single-operator shop. The "machine proposes, Jon disposes" gate means
**every phase that adds inflow without adding triage makes Jon's day worse.** If
Jon is already manually pasting and sorting alerts, Gmail MCP *auto-triage* saves
real hours — high value. But faster, fuller intake **without lifecycle tracking**
just manufactures dropped balls: more opps in, same number falling through the
cracks. So if we do ingestion, lifecycle tracking is its *required complement*,
not a later phase.

> **CMO rebuts:** "Hours saved is the wrong objective. I don't want Jon doing
> *more* outreach — I want him doing the *right* outreach. Volume triage is a
> COO metric; landing the agency relationship is the company's metric."

### CFO — "Latency is a vanity metric until it's tied to win-rate dollars."
What is a missed opportunity *worth*? One won agency deal dwarfs the cost of all
five phases combined. So the ROI question is narrow: **which step most increases
recall-of-high-value opps per dollar?** Gmail MCP carries an ongoing per-email
LLM cost; Core MCP read is near-free. My ranking by payback: (1) cheap
instrumentation to size the leak, (2) recall fix *only if* the leak is real and
high-value, (3) defer anything that just moves volume around.

> **CEO concedes:** "Fine — but the instrument has a one-week shelf life. The
> moment it confirms a leak, we build the recall fix. I won't let 'measure' become
> a quarter of measuring."

### CMO — "Our edge isn't speed or volume — it's *which agency, and why*."
Chordential already encodes this: `strategic.py` surfaces "small-but-strategic"
agency/marquee deals above big one-off government bids. **Agency intelligence
signals** are where our differentiation compounds — being *first AND smart* about
the right buyer wins relationships that pay off for years. I'd pull agency intel
*up*, not leave it third. A faster funnel of undifferentiated gigs is a commodity;
a sharp read on the ten agencies that matter is a moat.

> **CTO rebuts:** "Agency intel is the *highest*-effort item on the list — it
> needs enrichment data we don't have (that's the LinkedIn/CRM phase). It can't go
> early; it has the deepest dependencies."

> **CFO rebuts:** "And it's the hardest to attribute to revenue in the short term.
> Strategically right, fiscally premature."

---

## 2. Where the council lands

The disagreement resolves once the room accepts the CTO's reframing and the CFO's
discipline. The synthesis:

1. **"Latency vs. read-only MCP" is a false binary.** The highest-value form of
   latency reduction is *recall*, and the cheapest way to size and de-risk a
   recall investment is a *thin slice of read-only MCP*. They're not competitors —
   one is the instrument for the other.

2. **Freshness scoring leaves the roadmap** — it's shipped. (If anything, the
   refinement is tracking *source-to-intake* lag per source, which the instrument
   in step 1 reveals.)

3. **The pivotal unknown is: supply-constrained or attention-constrained?**
   - *Supply-constrained* (funnel too thin) → recall/ingestion wins → **Gmail MCP**.
   - *Attention-constrained* (Jon can't act on what's already there) → triage &
     decision leverage win → **read-only MCP for Jon + lifecycle tracking**.
   - We don't currently know which. That ignorance is itself the bottleneck.

4. **Agency intelligence is strategically right but dependency-deep** (needs
   enrichment). It stays after ingestion + lifecycle, not before.

---

## 3. Recommended highest-leverage next step

**Build a thin read-only Core MCP slice — scoped as instrumentation — and use its
first week to settle supply-vs-attention. Then commit to Gmail MCP as a *recall*
play (not a latency play), paired with lightweight lifecycle tracking.**

Concretely, the revised order:

| # | Step | Why here | Effort |
|---|---|---|---|
| **1** | **Core read-only MCP (as instrument)** — funnel coverage, drop rate, source mix, miss visibility | Cheapest possible; answers the one question that orders everything else; de-risks every later dollar | **Days** |
| **2** | **Gmail MCP ingestion (recall)** — agent reads & extracts what regex drops | The real "latency" win is not missing opps; size confirmed by step 1 | Medium |
| **3** | **Opportunity lifecycle tracking** — required complement to faster intake | More inflow without this = more dropped balls (COO's point) | Medium |
| **4** | **Agency intelligence signals** | Strategic moat (CMO), but enrichment-dependent — can't lead | Medium-large |
| — | ~~Freshness scoring~~ | **Already shipped** (`signals.py`) | Done |

**Why this beats Jon's ordering:** it keeps his instinct that ingestion is the
prize (step 2), but (a) corrects that freshness is already done, (b) reframes
"latency" as the more valuable "recall," (c) promotes a *thin* read-only MCP from
last-and-optional to first-and-cheap — not as Jon's analytics dashboard, but as
the measurement that proves the recall leak is real before we fund the fix, and
(d) couples lifecycle tracking to ingestion so faster intake doesn't leak out the
bottom.

**The one sentence:** *Don't choose between latency and MCP — spend three days on
read-only MCP to measure the leak, then spend the next sprint on Gmail MCP to plug
it, because the most expensive latency we have is the opportunity we never saw.*

---

## 4. The decision Jon owns

The recommendation defaults to **measure-then-recall**. But if Jon already *knows*
from lived experience that the funnel is starving (few qualified opps per week),
the council would skip straight to **Gmail MCP ingestion** — the instrument would
only confirm what he already feels. Conversely, if Jon feels buried in opps he
can't act on, jump to **read-only MCP + lifecycle** and treat ingestion as later.

That lived-experience read is the one input the codebase can't supply.
