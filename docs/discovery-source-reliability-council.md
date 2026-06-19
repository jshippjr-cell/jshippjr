# Discovery Source Reliability Council — Replacing F5Bot

**Convened to answer:** F5Bot caps each keyword at 50 hits/24h and *auto-disables*
it — a silent funnel outage. Is there a way around it, and what should the
demand-discovery stack be instead?

**Personae:** CEO · CTO · COO · CFO · CMO

---

## 0. The fact that frames it

F5Bot is a **free relay of Reddit + Hacker News**. Two things follow:

- **It caps and disables.** A broad keyword ("music producer", "sound designer")
  blows past 50 hits in hours on Reddit chatter and gets switched off — and you
  only find out from a "limit reached" email, if at all. That's an unmonitored
  top-of-funnel that can go dark without warning.
- **It fishes the lowest-value pond.** The 11 hits triage already read were
  Reddit *comments* and *career-path threads* — the LLM correctly landed **0**.
  We're spending reliability budget (and Haiku calls) to surface noise.

So the question isn't "how do we keep F5Bot alive" — it's "what is F5Bot a weak
proxy *for*, and can we get that directly?"

---

## 1. The debate

### CEO — "F5Bot was never the prize."
We don't win agency deals from Reddit comments. The real funnel is the
professional gig boards and agency/brand RFPs. F5Bot was a free stopgap; making
it *reliable* is polishing the wrong source. Stop investing in it. Where's the
real demand, and are we even capturing it?

> **CMO answers:** The real demand is on **Mandy, ProductionHub, Staff Me Up,
> Hitmarker** — where buyers actually post paid music briefs — and later
> agency/brand RFPs and SAM.gov. Reddit is indie/hobby/low-budget; it's the
> wrong pond for the marquee buyers that are our strategic prize.

### CTO — "We already own the replacements."
Two parts are already in the codebase:
1. **A Reddit OAuth adapter** (`crawl_adapters.py`) — we can hit Reddit *directly*
   on the few subreddits that matter (r/composer, r/gameDevClassifieds [hiring],
   r/forhire, r/MusicForVideo). No 50-hit cap, our own rate limits, reliable.
   F5Bot is strictly worse — it adds a relay's latency + cap + noise on top of
   the same Reddit data.
2. **The Gmail triage we just shipped (B1/B2)** turns *any* forwarded alert email
   into structured opportunities — no per-source parser. That's the unlock: point
   the real boards' own saved-search emails at the `Chordential` label and they
   flow in, cap-free.
   Plus **RSS polling** (`rss.py`) for Google-Alerts/board feeds. Net: we can drop
   F5Bot with **no new external dependency**.

> **CFO adds:** And it's cheaper. F5Bot's "cost" is reliability + wasted triage
> spend on junk. Direct Reddit is free within rate limits; board alert emails and
> RSS are free. Paying F5Bot to *raise* a noisy cap is spending money to get more
> noise.

### COO — "The real defect is the silent outage."
An auto-disabled alert is a funnel that stops without telling anyone — the worst
failure mode for an operator. Whatever replaces it must fail **loudly and
visibly**. Sources we poll ourselves (Reddit API, RSS) and emails we receive both
do — we control the cadence and can alarm on zero. A third party that can disable
*us* is structurally fragile. Bonus: narrower, higher-intent keywords mean less
triage volume and less of my operator's attention burned on noise.

### CMO — "Source quality = buyer quality."
The pond determines the fish. Professional boards surface real paid briefs from
production companies and agencies; Reddit surfaces hobbyists and rev-share.
Concentrate funnel energy where the *strategic* buyers post. Use Reddit as a thin,
opportunistic supplement — not a primary source, and definitely not one we let
silently die.

---

## 2. Where the council lands

**Don't save F5Bot — retire it.** It's a capped, silent-failure relay of the
lowest-value pond, and you already built the better stack:

| Source | Status | Why it beats F5Bot |
|---|---|---|
| **Gig-board alert emails** (Mandy/ProductionHub/Hitmarker/Staff Me Up) → Gmail triage | ✅ built (B1/B2) | Higher-intent, the right buyers, no cap; any email becomes a funnel input |
| **Direct Reddit API** (right subreddits, [hiring] filter) | ⚙️ adapter exists, not yet wired to signals | Cap-free, reliable, replaces F5Bot's only useful coverage |
| **RSS / Google Alerts** (board + query feeds) | ✅ poller exists | Cap-free supplement we control |
| **SAM.gov** (gov music procurement) | 🔜 roadmap | Structured API, scheduled |
| **F5Bot** | ⛔ deprecate | 50/day cap, auto-disable, Reddit-only noise |

**The reframe:** building Gmail triage *was* the way around F5Bot. F5Bot existed
because parsing each board was painful; the agent removes that, so the real boards
become first-class inputs. F5Bot is now redundant.

---

## 3. Recommended next steps (leverage ÷ effort)

1. **Lean the funnel on board alert emails — today, zero build.** Create
   saved-searches on Mandy/ProductionHub/Hitmarker/Staff Me Up, forward them into
   the `Chordential` Gmail label. B1/B2 triage already extracts them. *This is the
   single biggest reliability + quality win and it needs no code.*
2. **Wire direct Reddit polling into the scheduler** (small build). Reuse the
   existing Reddit OAuth adapter; poll a short allowlist of high-intent subreddits
   on a cadence into the signals pipeline, with the same money-as-demand filter.
   Cap-free replacement for F5Bot's Reddit coverage.
3. **Add a couple of RSS / Google-Alerts feeds** (`CHORDENTIAL_RSS_FEEDS`) for
   queries the boards don't cover — cap-free, already polled.
4. **Deprecate F5Bot** to at most one or two *narrow, high-intent* keywords
   (e.g. "[hiring] composer") that won't hit the cap — or drop it entirely.
5. **Monitor for silent outage:** alarm when a source returns zero over a window,
   so a dead feed is visible (the failure mode F5Bot taught us).

**One sentence:** F5Bot isn't worth fixing — point the real gig boards at the
Gmail triage you already built, poll the few good subreddits directly with the
adapter you already have, and let F5Bot lapse.

---

## 4. Stopgap, if you want F5Bot alive this week

Narrow the keywords so they stay under 50/day: replace broad terms ("music
producer") with intent-bearing phrases ("composer needed", "original music for")
and drop the noisiest. It reduces cap-hits and triage noise — but it's a patch on
a source the council is retiring, not a destination.
