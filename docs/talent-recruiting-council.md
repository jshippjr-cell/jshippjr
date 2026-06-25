# Talent Recruiting & Retention — Cabinet Deliberation

**Convened:** 2026-06-25 · **Chair:** Jon Shipp (CEO) · **Mandate:** a plan for the
supply side — (1) **find** top talent, (2) a **recruiting outreach campaign** to make
them want to work with Chordential, (3) **vet** skill and decide **retainer vs.
work-for-hire**, (4) **retain/engage** approved talent on a **bench** until leads flow,
and (5) **pay them out** once a project is delivered. **The cabinet deliberates and
returns options + a phased plan; Jon decides.**

Governing rule unchanged: **the machine proposes, Jon disposes** — sources surface
candidates; Jon's reel review is the gate.

Roster: **Head of Production** (lead — runs the craft team), **CMO** (employer brand),
**COO** (bench ops), **CTO** (systems), **CFO** (payout + retainer economics),
**Founder's Advocate**.

---

## 0. Ground truth (what exists today)

So the plan builds on reality, not a blank page (verified in code):

- **Sourcing exists, lightly.** A human-gated discovery crawler with a `talent` kind
  (`discovery.py`), a `TalentSource` plugin interface (`talent_sources/`), the public
  `/apply` creator form, and a manual "Add a creator" form. All candidates land at
  **`review_status=Pending` / `invite_status=Prospect`** — Jon's reel review is the gate.
- **Vetting is binary.** `ReviewStatus` = Pending → **Approved**/Declined; a separate
  `InviteStatus` = Prospect → Invited → Joined. `matchable = approved AND has
  disciplines`. There is **no tier, no retainer, no availability, no rate** on talent.
- **Matching works.** `match_talent` ranks approved creators by 60% craft fit + 30%
  credits overlap + 10% profile completeness (`matching.py`); a match board assigns them
  to projects. **Assignments store only `(project_id, role, talent_id)` — no rate, no
  payment.**
- **Money flows IN only.** Client pays via proposal → invoice → Stripe Checkout. **There
  is ZERO talent payout** — no payout code, no talent bank/Stripe fields, no Connect, no
  retainer. Confirmed absent across the whole codebase.
- **New discipline just added:** *Audio mixing engineer* — so the roster now spans
  composition, sonic branding, sound design, arrangement, supervision, licensing, **and
  mixing/mastering**.

**The honest headline:** the front of the funnel (source → review → match) is built; the
**back** (tiering, bench engagement, and especially **paying talent**) is not. And the
company is **early — lumpy lead flow, no steady deal volume yet.** Every recommendation
below is shaped by that: *don't build a payroll for a bench you can't yet feed.*

---

## 1. Find top talent — Head of Production (lead)

**Head of Production:** Top craft talent is **not** found by crawling job boards — that
surfaces people *looking for work*, which is adverse selection for the top tier. The best
composers/mixers are **busy and referred.** So a two-track sourcing model:

- **Track A — Scouted (the top tier).** Work backward from **credits**: identify the
  actual people behind sounds we admire (film/ad/game credits, liner notes, AdView/
  ProductionHUB/IMDb), and the discovery crawler's `talent` kind proposes them as
  Prospects. Quality over volume — a curated shortlist, not a cattle call.
- **Track B — Inbound (the wide net).** The `/apply` form + community presence (Reddit
  r/composer, VI-Control, Discord guilds, Soundlister). Higher volume, lower hit rate —
  the reel-review gate does the filtering.

**Founder's Advocate (dissent — focus):** Don't source across all seven disciplines at
once. Source **to demand.** Right now the pipeline is composition + sonic-branding shaped
work; over-recruiting supervisors or even mixers we can't yet staff just fills the roster
with disappointed people. Match the recruit list to the **next ~10 likely briefs**, not a
theoretical full-service agency.

**Head of Production:** Fair — sourcing is **demand-pulled**, a rolling shortlist per
discipline we're actually selling, with mixing added now that it's a craft we offer.

**CMO:** One add — the **single best source is a delighted collaborator.** Build the
referral loop early: every approved creator can refer one peer. Referred talent converts
and stays better than anyone we cold-scout.

---

## 2. The recruiting outreach campaign — CMO (lead)

**CMO:** Recruiting a craftsperson is a *sale*, and we just built the machine for it on
the client side — **reuse the pattern.** The creator's question isn't "do they have
work," it's *"will this respect my craft and pay me fairly?"* So the pitch leads with
what a new studio can credibly promise an artist:

- **Real briefs, not spec.** We bring you scoped, paid work — never unpaid pitches.
- **Clean rights & fair terms.** Clear scope, defined deliverables, **prompt payment**.
- **Curated, not a marketplace.** You were chosen; you're not bidding against 200 people.
- **First-look on fit work.** When a brief matches your craft, you hear first.

**The campaign mechanics (mirror the client first-touch):** a **recruiting composer** —
a personalized invite assembled from blocks (who we are, why them specifically /
their credit, what we offer creators, a soft link) — plus a **"Why Chordential for
artists" page** (the supply-side analog of the first-touch page). Sequence: **Prospect →
personalized invite → reel/portfolio review → onboard (Joined).** This maps onto the
existing `InviteStatus` funnel (Prospect → Invited → Joined), which today has buttons but
no outreach content behind them.

**Founder's Advocate (dissent — honesty):** A new studio must not over-promise *volume.*
"First-look on fit work" is honest; "steady income" is not — we don't have the deal flow
yet, and a creator who joins expecting a paycheck and waits in silence churns angry and
bad-mouths us. **Recruit on craft respect + fairness, set volume expectations low,** and
let reliability earn the relationship.

**CMO:** Accepted — the pitch promises *respect, fairness, and first-look*, never a
salary. Under-promise volume, over-deliver on how we treat them.

**COO:** And cap invite velocity to what Jon can actually review. An invite funnel that
outruns reel review creates a backlog of ignored applicants — worse than not inviting.

---

## 3. Vet skill → retainer vs. work-for-hire — Head of Production + CFO

**Head of Production:** The binary Approved/Declined is too blunt for "retainer vs WFH."
Add a **tier** on approved talent:

- **Core (retainer-candidate):** proven, fast, reliable, in a discipline we sell often —
  the people we *want guaranteed*.
- **Roster (work-for-hire):** approved and matchable, used per-project as fit demands.
- (Declined stays declined.)

The vet itself stays reel-first (Jon reviews the demo), plus a **paid micro-brief** for
Core candidates — a small, *paid* test that proves speed + direction-taking on a real-ish
prompt before we ever talk retainer. Never unpaid spec.

**CFO (hard dissent — retainer economics):** I will fight an actual cash retainer at this
stage. A retainer = **fixed cost against lumpy, unproven revenue** — the fastest way to
bleed a young studio. Until lead flow is *steady and forecastable*, "Core" should mean
**priority + first-look + a faster/served-first commitment**, NOT a monthly check. Earn
the right to pay retainers with a backlog that justifies guaranteeing capacity. **Tier
now (free); cash retainers later, gated on revenue.**

**Head of Production:** Accepted — **"Core" is a priority tier, not a paid retainer,
yet.** The retainer is the *destination* once deal flow is steady; the tier field is the
on-ramp we build now.

**CTO:** Concretely that's a `tier` field on talent (Core/Roster) + the paid-micro-brief
as a logged step. Small schema add; no money movement.

---

## 4. Keep them engaged on a bench — COO (lead)

**COO:** The danger with a bench is **silent decay** — approved people who never hear
from us go cold and unreachable exactly when a lead finally lands. Keep them warm
*cheaply* (we can't pay them to sit):

- **First-look, fast.** When a brief matches, the matched Core/Roster talent hears within
  hours — being *thought of first* is the #1 retention lever for freelancers.
- **Availability pulse.** A light, periodic "are you open the next few weeks?" so the
  bench data is live, not stale (needs an `availability` + `last_contacted` field).
- **Reputation as the product.** The thing that keeps top freelancers loyal to a small
  shop is **paying fast and fairly** (see §5) — that's worth more than any newsletter.
- **Occasional paid test briefs** to Core candidates — keeps them sharp *and* fed a
  little while the pipeline builds.

**Founder's Advocate (dissent — don't build a bench ahead of demand):** A "bench" implies
people waiting. Before there's deal flow, a formal bench is **a list of people we're
disappointing.** Keep it tiny and honest: a **warm shortlist** per active discipline,
contacted only when there's something real or a genuine availability check — not a
program that simulates activity. Build the bench *as the deal flow arrives*, not before.

**COO:** Agreed in spirit — **warm shortlist now, formal bench later.** The build is the
same minimal fields (`tier`, `availability`, `last_contacted`); the *program* (digests,
test briefs) waits until there's flow to make it honest.

**CMO:** The cheapest, highest-impact engagement is **closing the loop**: tell a creator
what happened to a brief they were considered for. Silence churns; "we went another way
this time, you were close" retains.

---

## 5. Pay talent when a project delivers — CFO + CTO

**CFO (lead):** This is the real gap and the founder's direct question. Today: **nothing
pays talent** — no payout code, no rates on assignments, no Connect. Three options,
cheapest first:

- **(A) Manual payout, logged.** Jon pays off-platform (ACH/Zelle/PayPal/Wise) and the
  system just **records** it. Zero payment infra. Ships today.
- **(B) Payout ledger (recommended first build).** A `talent_payouts` table —
  `(project, talent, role, hours, rate, amount, status: Owed→Paid, paid_at, ref)` — plus
  a **rate on the assignment** (missing today). The app then *tells Jon what's owed to
  whom* when a project's client invoice is Paid, and he marks each payout Paid after
  sending money off-platform. Tracks the liability and the moat (paid-fast reputation)
  **without** moving money in-platform.
- **(C) Stripe Connect (in-platform payouts).** Real automated transfers — needs Connect
  enabled, `stripe_account_id` + W-9/tax fields on talent, onboarding UI, transfer logic,
  1099 compliance. **Net-new and heavy; deferred** (the billing council already parked
  Connect as a future "Phase C").

**CFO's recommendation:** **(A)+(B) now, (C) later.** The ledger gives you the discipline
(every collaborator paid promptly, tracked) that *is* the retention strategy in §4 —
without the cost and compliance weight of Connect before volume justifies it.

**CTO:** Endorse. (B) is a table + a rate field + a "what's owed" view — days, not weeks,
and reuses the invoice-status signal (pay talent *after* the client deposit/final clears).
(C) is a project: Connect onboarding, tax docs, transfer + payout webhooks, error states.
Don't start (C) until payouts are frequent enough to hurt by hand.

**Founder's Advocate:** And tie payout to **cash received**, not project completion —
pay talent out of money that has actually landed (client invoice Paid), so a slow-paying
client never puts the studio underwater fronting talent. Trigger the ledger entry on
**invoice Paid**, surface it as "owed," pay promptly.

**CFO:** Critical compliance flag: paying contractors means **W-9 collection + 1099s** at
year-end. Even in the manual/ledger phase, **collect a W-9 before the first payout** and
store tax status on talent — cheap now, painful to backfill.

---

## Decisions for the founder (Jon decides — cabinet recommendation in *italics*)

1. **Sourcing model (§1).** *Recommend two-track, **demand-pulled**: scouted-by-credits
   (top tier, via the talent crawler) + inbound `/apply`/community, a rolling shortlist
   matched to the next ~10 likely briefs (incl. mixing now). Build a referral loop.* —
   Confirm.
2. **Recruiting campaign (§2).** *Recommend a **recruiting composer + "Why Chordential
   for artists" page** (mirror the client first-touch), pitching craft-respect + fairness
   + first-look — never promising volume. Funnel: Prospect → Invited → Joined.* —
   Confirm scope.
3. **★ Vetting + tiers (§3).** *Recommend adding a **tier** (Core / Roster) on approved
   talent + a **paid micro-brief** for Core candidates. "Core" = **priority/first-look,
   NOT a cash retainer yet** (CFO). Cash retainers deferred until lead flow is steady.* —
   **Your call: tier-only now (rec.) / commit to paid retainers now.**
4. **Bench engagement (§4).** *Recommend a **warm shortlist** (not a formal bench yet):
   minimal `availability` + `last_contacted` fields, first-look-fast, close-the-loop, and
   the paid-fast reputation as the real retention lever. Formal bench program waits on
   deal flow.* — Confirm.
5. **★ Talent payout (§5).** *Recommend **(A) manual + (B) payout ledger now**, triggered
   on client-**invoice-Paid**, with per-assignment rates and a "what's owed" view; **(C)
   Stripe Connect deferred.** Collect a **W-9 before the first payout.*** — **Your call:
   ledger-now + Connect-later (rec.) / push straight to Connect / manual-only.**

**Phased build if greenlit** (lean, demand-paced): **tier + availability fields → the
payout ledger (rates + owed view, W-9) → the recruiting composer + artists page → (later,
on volume) paid retainers and Stripe Connect.**

*Systems note (CTO): the recruiting composer/page reuse the client first-touch
infrastructure; tiers/availability are small talent-table adds; the payout ledger is a new
`talent_payouts` table + an assignment rate + an "owed" view keyed off invoice status.
Stripe Connect is the only piece that is genuinely net-new and heavy — keep it last.*
