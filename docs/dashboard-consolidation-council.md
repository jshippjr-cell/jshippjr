# Back-of-House Consolidation — Cabinet Deliberation

**Convened:** 2026-06-24 · **Chair:** Jon Shipp (CEO) · **Mandate:** consolidate
the admin dashboard into one legible, end-to-end engagement surface — lead →
qualify → reach out → pursue → deliver — and resolve a dozen specific frustrations
the founder raised. **The cabinet deliberates and returns options; Jon makes the
final call** (no CEO ratification this round — every fork is teed up at the bottom
for the founder to decide).

Governing rule unchanged: **the machine proposes, Jon disposes.** Agents are
required to disagree where they actually disagree.

Roster: **Head of Product** (lead), **COO**, **CTO**, **CMO**, **CRO**, **CFO**,
**Head of Production**, **Founder's Advocate**.

---

## 0. Ground truth (read this first — three of the complaints rest on misreads)

Before positions, the cabinet stipulates what the code actually does today, because
several decisions change once the facts are straight (file refs for the build team):

| Founder's report | What the code actually does | Verdict |
|---|---|---|
| "Follow-ups due goes nowhere" | It's an in-page anchor `#followups` (`dashboard.html:20`) that scrolls to a section (`:33`) which is **empty when nothing is due** | Not a dead link — a **dead-feeling empty state** |
| "View all in Top targets → empty opportunity inbox" | Routes to `/inbox?action=Pursue` (`dashboard.html:58`) — the **pipeline** table (`opportunities`), which is empty until a lead is **promoted** | Routing is "correct" but **points at the wrong mental model** |
| "Promote did nothing" | `/leads/{id}/promote` (`app.py:533-571`) **does** create an opportunity + redirect — but has **no success message and no error check**; if the insert fails it redirects anyway | Either a **silent success** (looked like nothing) or a **silent failure** — both are bugs of *feedback*, not logic |
| "Combine the two PDFs" | Capabilities doc (`capabilities_doc.html`) **is** personalized per deal; the delivery package (`public/delivery_sample.html`) is a **100% static fictional sample** (AURORA Outdoor Co.), no data flow | Combining = **build a real personalized delivery doc**, not merge two existing ones |
| "Build in DocuSign and Stripe" | **Stripe is already fully wired** — Checkout + signed webhook → auto-marks invoices Paid (`app.py:1991-2073`). **DocuSign is placeholder text only** (`capabilities_doc.html:141-149`) — no SDK, no envelopes | Stripe = **surface what exists**; DocuSign = **net-new integration** |
| "Red bubble not firing for website leads" | Badge + phone push fire **only for market signals** (`signals.py:259`, `base.html:79`). Website + crawler leads land in a different table with **zero notification wiring** | **Confirmed real gap** |

**The shape of the surface today** — eight admin tabs, four of which are lead/deal
funnels at different stages:

- **Dashboard** (`/dashboard`) — exec summary: 5 KPIs + three columns (Top targets /
  Tentative / Won) + follow-ups + spotlight + needs-review.
- **Pipeline Lanes** (`/lanes`) — a 5-column kanban (New / Pursuing / Submitted /
  Won / Lost) of the **same** `opportunities` table.
- **Opportunity Inbox** (`/inbox`) — filterable table of the **same** `opportunities`.
- **Inbound Leads** (`/leads`) — raw web-form + crawler submissions (`inbound_leads`
  table), **no scoring, no badge, no push**.
- **Signal Radar** (`/signals`) — market-detected gigs (`signals` table), **scored,
  tiered, badged, pushed**.
- **Discovery / Crawler** (`/discovery`), **Outreach** (per-deal subpage), plus
  Sources/Talent/etc.

So **three tabs (Dashboard, Lanes, Inbox) are three renderings of one table**, and
**two tabs (Leads, Signals) are two intake queues that differ only in evaluation.**
That redundancy is the whole problem. Now the positions.

---

## A. Dashboard vs Pipeline Lanes — collapse three views of one table into one

**Head of Product (lead):** The founder is right that Dashboard and Lanes feel like
the same thing, because they *are* — both render `opportunities`, just in different
clothes. But the answer isn't "delete one," it's to assign each surface **one job**
and stop overlapping:

- **Home = "Today"** — a true command center: what's new and needs me, what's due
  today, what's stuck. Not a second pipeline board.
- **Pipeline = the kanban** (today's Lanes) — the *single* working board where you
  drag a deal New → Pursuing → Submitted → Won. This absorbs the dashboard's three
  columns; they were a worse version of the kanban anyway.
- **Inbox = search/filter** — keep as the power-user query tool, demoted from the nav
  to a "Find a deal" affordance. It is not a daily destination.

So: **keep two daily tabs (Today + Pipeline), retire the third as a daily
destination.** The "In flight" KPI stops linking to a redundant board and instead
deep-links into the Pipeline kanban filtered to active deals.

**COO (dissent):** Half-agree. I do **not** want to lose the at-a-glance exec
summary. When I open this at 7am I want numbers — win rate, pipeline value,
follow-ups due — *before* I'm dropped into a board of cards. Make "Today" lead with
the KPI strip and the action lists; the kanban is one click away, not the landing.

**Head of Product:** Accepted — "Today" keeps the KPI strip. The disagreement was
never about killing KPIs; it's about killing the **second deal board**.

**CTO:** Cheap and safe. Lanes, Dashboard columns, and Inbox already share the same
queries (`list_opportunities`, `pursue_targets`, `tentative_bids`). Folding the
dashboard's three columns into the kanban deletes code, it doesn't add it. One real
cost: every deep-link and the `_KANBAN_STAGES`/`pursue_targets` filters must agree on
one stage vocabulary (see §B) or we'll have three tabs disagreeing about what
"in flight" means.

**Founder's Advocate:** The lived complaint is "I click In flight and land somewhere
that looks identical." Whatever we build, the test is: **no two tabs may show the
same cards in the same layout.** If "Today" and "Pipeline" ever look the same again,
we failed.

---

## B. The Pursuing / Submitted / "lanes" stage model — too many words for the same feeling

**Head of Product:** The founder says Pursuing and Submitted "feel the same." In the
data they're distinct — Pursuing = New+unbid, Submitted = bid is out
(`db.py:2061` vs `:2076`) — but the *labels* are jargon from a bidding world, and the
kanban has **five** active columns (New, Pursuing, Submitted, Won, Lost) which is too
many to scan. Re-language to the engagement the founder actually runs:

| Today | Proposed | Means |
|---|---|---|
| New | **New** | just arrived, not worked |
| Pursuing | **Reaching out** | I've made contact / am chasing |
| Submitted | **Proposal out** | capabilities/delivery doc + price sent, awaiting yes |
| Won | **Won** | signed |
| Lost / Passed | **Closed** (lost/passed, collapsed) | done, archived |

**CRO (dissent):** Don't over-merge. "Reaching out" and "Proposal out" are the two
stages where money is actually won or lost — I need them *separate and visible*, with
counts, because a deal rotting in "Proposal out" for 10 days is my single most
important alert. Re-label, yes. Collapse, no.

**Head of Product:** Agreed — re-label, keep them as distinct columns. The collapse I
want is only **Lost + Passed → one "Closed" archive**, which nobody works daily.

**COO:** One add: the founder's end-to-end mental model includes **"reached out,"
"sent the PDF," and "pursued"** as *milestones*. Those aren't all pipeline columns —
some are events on a deal (a touch logged, a doc sent). Decide deliberately: a stage
is a *column* (you can have only one), a milestone is a *checkmark* (you can have
many). "Proposal sent" is the ambiguous one — I'd make it a **column** (Proposal out)
because it's the single highest-signal state.

---

## C. Merge Inbound Leads + Signal Radar into one "Incoming" — and notify on *every* source

**COO (lead on this one):** This is the founder's strongest instinct and I back it
fully. Two intake tabs that both mean "new stuff to triage" is one tab too many. Merge
`/leads` and `/signals` into a single **"Incoming"** queue: every new lead — website
questionnaire, book-a-call, crawler, RSS, email alert, manual paste — rolls up here,
newest first, with a **source chip** (🌐 Website · 🤖 Crawler · 📡 Signal · ✉ Email).

**One badge, one push, all sources.** The red bubble and the phone notification
currently fire only for `signals` (`signals.py:259`, `new_signal_count` in
`db.py:1183`). Extend both to fire for **inbound_leads** too. A prospect who fills out
the website form is a *hotter* lead than an RSS hit — it is indefensible that the
warm one is silent and the cold one buzzes your phone.

**CTO (real-cost dissent):** Endorse the unified *view*; push back on a unified
*table*. `inbound_leads` and `signals` have genuinely different shapes — signals carry
score/tier/freshness-rank; leads carry contact fields and a quoted price band. Don't
migrate them into one table (that's a data migration + a rewrite of scoring). Instead
build **one read-model that UNIONs both** behind a single "Incoming" view and a single
`/incoming/count` badge endpoint. Same inbox to Jon; two tables underneath. Cheaper,
reversible, and we don't lose signal scoring.

**COO:** Accepted — unified view over a UNION, not a table merge. Jon experiences one
queue; the engine keeps its two specialized stores.

**CMO:** While we're here — the badge should count **what's unactioned**, not what's
"New," or it'll undercount leads sitting in a half-triaged state. Define "needs me" =
inbound `New` + signal `New`. One number, honest.

**Founder's Advocate:** The push wiring is a 1-hour job (`notify_new_gig` already
exists; call an analogous `notify_new_lead` after `insert_inbound_lead` in
`public.py` and `discovery.py`). This is the highest-value, lowest-cost item on the
whole list. Whatever else slips, **this ships first.**

---

## D. THE FORK: should un-qualified leads appear in "Top targets to pursue" on the home page?

*This is the one genuine architectural disagreement. The cabinet is split. Jon
decides.*

**Founder's position (as briefed):** "If a new lead comes in from anywhere — website,
crawler, scanner — it should show up in my Targets to Pursue on the dashboard. It
shouldn't just sit in Signal Radar or Inbound Leads."

**CTO (against — defend the gate):** Today "Top targets to pursue" =
`pursue_targets()` = opportunities that are **`status IN (New,Pursuing)` AND
`qualified=1`** (`db.py:2061`). Raw leads and signals are deliberately *not*
opportunities yet — they become opportunities only when you **Promote** them. That
gate is the spine of the whole product: "the machine proposes, Jon disposes,"
precision-biased so the pipeline never fills with junk. If unqualified website spam
auto-appears in "targets to pursue," the dashboard's most valuable list — *qualified
deals worth your time* — becomes a firehose. We'd be deleting the product's main
guarantee to save two clicks.

**CRO (for — the founder's right):** The founder isn't asking to delete the gate; he's
asking to **see the incoming flow from the home page** instead of hunting two tabs for
it. The honest read of the complaint is a **missing surface**, not a broken gate.

**Head of Product (synthesis — and my recommendation):** Resolve it by **separating
the two lists the founder is conflating**:

1. **"Needs triage" (new)** — a home-page module fed by the §C unified Incoming queue:
   raw leads/signals from every source, with a one-click **Promote** / **Dismiss**
   right there. *This* is what the founder means by "show me everything that came in."
2. **"Top targets to pursue" (existing)** — stays exactly as is: **qualified
   opportunities only.** The gate is intact; it just sits *below* triage on the page.

So the dashboard reads top-to-bottom as the actual workflow: **what just arrived
(triage) → what I've qualified and should pursue → what's awaiting a yes → what's
due.** The founder gets "everything visible on the home page" **without** poisoning
the qualified list. Nobody has to choose between visibility and the gate.

**COO:** This is the right call and it also kills the §0 bug where "View all" dumped
Jon into an empty pipeline inbox — that link now points at the **triage** module,
which is where his mental model said "new leads to review" all along.

**CTO:** I can support this. One firm condition: **Promote stays an explicit human
action.** Triage can live on the home page; auto-promotion cannot.

*→ Decision 4 at the bottom. The cabinet recommends the Head of Product synthesis
(two distinct lists), but the founder may instead choose full auto-surfacing — stated
plainly so he owns the trade-off.*

---

## E. Quick wins: the follow-ups empty state, the "View all" misroute, and the silent Promote

**Head of Product:** Three small, unambiguous fixes — no real disagreement, listed so
they don't get lost behind the big stuff:

1. **Follow-ups "dead" tile** — it scrolls to an empty section when nothing's due.
   Give it a real **empty state** ("✅ Nothing due today") and, when items exist,
   make the KPI deep-link to a filtered list, not an anchor. *It was never dead; it
   was mute.*
2. **"View all" → empty inbox** — re-point from `/inbox?action=Pursue` to the new
   **triage** module (§D). Fixes the founder's "why am I in an empty inbox" instantly.
3. **Promote feedback** — add a success flash ("Promoted → opened as a deal") and an
   **error guard**: if `insert_opportunity` returns no id, *don't* redirect to a
   ghost; show "couldn't promote." (`app.py:567` currently links the lead to a
   possibly-null id and redirects regardless.)

**CFO:** All three are hours, not days. Approve on sight.

**Founder's Advocate (lone dissent on scope):** Don't let "quick wins" become the
whole project. These are table-stakes bug fixes; they don't deliver the *streamlined
end-to-end experience* the founder actually asked for. Ship them, but they're the
floor, not the deliverable.

---

## F. The website questionnaire — gate it, but mind the conversion cost

**CRO (lead):** The founder wants required phone + email, block submit on missing
info, company/LinkedIn optional. Today the public forms (`public/start.html`,
`book.html`, `apply.html`) require **only a name** — email is optional and **there is
no phone field at all** (`public.py:130-131`). So this is partly "add validation" and
partly "add a field that doesn't exist."

I support a hard gate on **email** (server + client, `required` + format check). I am
**against making phone mandatory.** Every required field cuts completion — phone is
the single most abandonment-prone field on a B2B form. Requiring it will *reduce the
number of leads*, which is the opposite of the funnel goal. Make phone **strongly
encouraged, not required.**

**COO (dissent — the founder's lived pain):** Disagree. The founder's complaint is
that prospects submit **garbage with no way to reach them.** A lead with neither a
phone nor a reachable context is worthless operationally — it *feels* like volume but
converts to nothing. I'd require **email AND phone**, exactly as asked. Better five
reachable leads than twenty ghosts.

**CRO:** Compromise on the table: require **email always**, and require **"email + at
least one of {phone, LinkedIn}"** — so every lead is reachable on *some* channel
without forcing the highest-friction field specifically. Company website + the second
contact field stay optional.

**Head of Product:** I like the "reachable on at least one channel" rule — it satisfies
the founder's actual need (never an unreachable lead) and CRO's conversion concern. But
**Jon should pick the strictness**, because it's a direct revenue-vs-quality dial:
- **(a)** Email required only — max volume.
- **(b)** Email + (phone OR LinkedIn) — reachable, balanced *(cabinet's recommendation)*.
- **(c)** Email + phone both required — max quality, as originally asked.

**CTO:** Whichever tier — validate **server-side**, not just the HTML `required`
attribute. Browser validation is bypassable; the founder's "garbage submissions" can
come from bots that skip the form entirely. Add a phone column to `inbound_leads`
(`db.py:161`) and enforce in `public.py` handlers.

**CMO:** And add a real **honeypot / basic anti-spam**, or the gate just changes the
shape of the junk. Cheap, do it with the field add.

---

## G. The lead detail page — contact info front-and-center, and a guided progression

**Head of Product (lead):** Two asks here: (1) when I open a lead, the contact info
should be *front and center to react to*; (2) make it a step-by-step progression
(receive → qualify → reach out → mark pursued → mark PDF sent → mark won).

On (1): today contact fields (phone/email/LinkedIn/role) live on the **Outreach
subpage**, *not* on the deal Overview (`detail.html` shows need/client/fit; contact is
one click away in `outreach.html:41`). That's backwards for a founder-run shop where
the first move is always "call/email this person." **Pull contact to the top of the
Overview** — name, phone, email, LinkedIn as tap-to-act links (`tel:`, `mailto:`),
above the qualification detail.

On (2): build a **horizontal progress stepper** across the top of every deal — the
re-labeled stages from §B (New → Reaching out → Proposal out → Won) — with the **next
action as one primary button** ("Mark: Reaching out"). Keep the milestone events
(touch logged, **PDF sent**, deposit paid) as checkmarks *under* the current stage.

**CTO (dissent — don't force linearity):** A stepper is good *visual orientation*, but
do **not** make it a wizard that forbids skipping. Real deals jump — a warm referral
goes straight to "Proposal out"; a deal dies at "New." The current freeform status
grid (`detail.html:85-96`) exists precisely so Jon can jump. Keep jump-ability:
stepper shows *where you are* and suggests *the likely next step*, but any stage stays
one click away. A linear-only flow will fight reality and Jon will hate it by week two.

**Head of Product:** Accepted — **guided, not gated.** Big primary button = the
expected next step; a quiet "…or set another stage" keeps the escape hatch.

**Head of Production:** Add one milestone that doesn't exist yet but the founder
explicitly wants: **"Delivery doc sent."** That's the hand-off from outreach to
closing, and it's the natural place to fire the §H combined PDF + the Stripe pay link.
Make it a first-class checkmark with a timestamp, not a buried log line.

---

## H. Outreach — one personalized client document, with DocuSign added and Stripe surfaced

**Head of Production (lead):** The founder wants the **agency delivery package**
(which "perfectly outlines what they'll receive") combined with the **capabilities
PDF**, auto-populated with the client's info, with **DocuSign** to sign and **Stripe**
to pay, all in the document he sends. Here's the reality and the build:

- The **delivery package is a static fiction** today (AURORA Outdoor Co.,
  `public/delivery_sample.html`) — gorgeous, but zero data flow. The **capabilities
  doc is the personalized one** (`capabilities_doc.html`, real client/need/team/price).
  So "combine them" = **port the delivery package's structure into the personalized
  pipeline** and feed it the deal's data.
- The right artifact is **one document, staged**: it *opens* with the capabilities
  framing (who we are, what we understand you need, the team, the price band) and
  *continues* into the delivery-package outline (deliverables manifest, asset map,
  rights/ownership, rollout) — so the client sees **both the pitch and exactly what
  they'll receive** in one branded piece, auto-filled with their name, project, and
  price. This becomes the thing the §G "Delivery doc sent" milestone fires.

**CFO:** Sequence the money. **Stripe already works** end-to-end for invoices
(`app.py:1991-2073`) — so surfacing a **"Pay deposit" button** in the document is
*surfacing existing capability*, near-free. Do that now. **DocuSign is net-new** — SDK,
keys, envelope creation, a status webhook, and a Terms PDF tied to the proposal. That's
the single biggest build on this entire list. I want it **phased**, not bundled into
the consolidation sprint, or it swallows everything.

**CTO:** Concur, and a feasibility note: both docs render today via **browser
Print-to-PDF**, no PDF engine. A *signable, emailable* document implies a real
generated PDF (WeasyPrint or headless Chromium) — that's infrastructure the combine
needs anyway. So the order is: **(1)** build the combined personalized doc (HTML),
**(2)** surface the Stripe pay link in it (cheap, exists), **(3)** add server-side PDF
generation, **(4)** *then* DocuSign on top. Doing DocuSign before (3) is impossible.

**CMO (dissent — protect the artifact):** The delivery package is our **best
marketing object** — it's what makes us look procurement-grade. When we auto-populate
it, do **not** let real-but-thin deal data make it look emptier than the AURORA sample.
A half-filled manifest is worse than the polished fiction. Gate the rich sections so
they only render when there's real content; fall back to the capabilities framing when
there isn't.

**Head of Production:** Accepted — progressive disclosure: personalized header always;
manifest/rights/rollout only when the project data exists.

**Founder's Advocate:** Flag the sequencing honestly to Jon: he asked for "DocuSign and
Stripe built in." **Stripe: yes, basically already there.** **DocuSign: a real
mini-project of its own.** If he wants signing *this* cycle, it likely *is* the cycle —
it can't be a footnote on the consolidation work.

---

## I. The Crawler / Discovery tab — it works; it just never says so

**COO (lead):** The founder says the crawler/gated tab "isn't doing anything." It is —
but it's **off by default and silent.** Auto-fetch only runs when
`CHORDENTIAL_ENABLE_SCRAPE` is set; gated sources (Reddit, LinkedIn) require manual
log-in-and-scan by design; and clicking **Fetch** reloads with **no progress feedback**
(`discovery.py`). So it *looks* dead even when it's working — same disease as the
follow-ups tile in §E.

**Head of Product:** Don't fold it into Incoming — it's an *operations console*
(approve sources, turn fetching on/off), not a lead queue. But its **output** (fetched
leads) should flow into the unified §C Incoming with a 🤖 Crawler chip, and it needs
**activity feedback**: "last fetched 2h ago · 14 found," a spinner on Fetch, and a
plain on/off state. Make it *legible*, keep it separate.

**CTO:** And surface the actual switch: if auto-fetch is off, the page should **say
so** with a one-click enable, instead of silently doing nothing. That single missing
sentence is most of why it "feels broken."

**CFO (dissent — value question):** Before we invest in polishing it, answer whether
the crawler actually *produces* qualified deals. If most pursued work comes from
website + signals, the crawler tab is a cost center wearing a feature's clothes. I'd
**measure first** (leads-fetched → promoted → won, by source) and let that decide
whether discovery gets investment or gets demoted. Don't gold-plate an unproven channel.

**COO:** Fair — instrument source-to-won attribution before we spend real time here.
For *this* sprint, the crawler gets only the cheap legibility fixes (state + feedback);
deeper investment waits on the numbers.

---

## Decisions for the founder (Jon decides — the cabinet's recommendation in *italics*)

The cabinet deliberately did **not** self-ratify. Each fork below carries a
recommendation and the dissent, so you own the trade-off:

1. **Dashboard vs Lanes (§A).** Recommend **two daily tabs**: "Today" (KPIs + action
   lists) and "Pipeline" (the kanban). Demote Inbox to a find-a-deal tool. *Retires the
   duplicate board you're complaining about.* — **Your call: 2 tabs (rec.) / keep all
   three / one mega-tab.**

2. **Stage labels (§B).** Recommend **re-label** Pursuing→"Reaching out",
   Submitted→"Proposal out", collapse Lost+Passed→"Closed"; keep "Reaching out" and
   "Proposal out" as **separate** columns (CRO insisted). — **Your call: adopt
   re-labels? collapse more or less?**

3. **Merge Leads + Signals → "Incoming" + notify on all sources (§C).** Recommend
   **yes** — unified view over a UNION (not a table merge), one badge, **phone push for
   website/crawler leads too.** Cabinet's highest-value, lowest-cost item; ships first.
   — **Your call: approve the merge + universal push?**

4. **★ The fork — do raw leads appear in "Top targets to pursue"? (§D)** Recommend the
   **two-list split**: a new **"Needs triage"** module on the home page shows *all*
   incoming from every source (Promote/Dismiss inline), while "Top targets to pursue"
   stays **qualified-only** so the gate survives. *Gives you total visibility without a
   junk firehose.* Alternative you may pick instead: **auto-surface everything**
   un-gated (CTO warns this dilutes the pipeline's core guarantee). — **Your call:
   two-list split (rec.) / full auto-surface.**

5. **Quick-win bugs (§E).** Recommend **ship all three**: follow-ups empty state,
   re-point "View all" → triage, Promote success/error feedback. No dissent. — **Your
   call: confirm.**

6. **Questionnaire gating (§F).** Pick the strictness dial: **(a)** email only · **(b)
   email + (phone OR LinkedIn)** *(recommended — reachable without max friction)* ·
   **(c) email + phone both** (as you originally asked; CRO warns it lowers lead
   volume). Server-side validation + a phone field + honeypot regardless of tier. —
   **Your call: a / b / c.**

7. **Lead detail (§G).** Recommend **contact info pulled to the top** (tap-to-call/
   email) + a **guided-but-not-gated stepper** (suggests next step, still lets you
   jump) + a new **"Delivery doc sent"** milestone. — **Your call: confirm guided
   (rec.) vs strict linear wizard.**

8. **The combined client document (§H).** Recommend **one personalized doc** =
   capabilities framing + delivery-package outline, auto-filled, with the **Stripe pay
   button surfaced now** (already wired). — **Your call: confirm scope.**

9. **★ DocuSign (§H).** This is **net-new infrastructure** (SDK + PDF engine + webhook),
   the biggest single build on the list — *not* the footnote it sounds like. Recommend
   **phase it after** the combined doc + Stripe + PDF generation land. — **Your call:
   include DocuSign this cycle (makes it the cycle) / defer to next.**

10. **Crawler tab (§I).** Recommend **cheap legibility fixes only** now (show on/off
    state, fetch feedback, route output into Incoming) and **instrument source→won
    attribution** before deciding on deeper investment (CFO: don't gold-plate an
    unproven channel). — **Your call: confirm light-touch + measure.**

**Suggested build order if you greenlight broadly** (cabinet consensus on sequencing,
cheap-and-high-value first): **#3 push/merge → #5 bug fixes → #6 form gate → #1 tab
consolidation → #4 triage module → #7 detail/stepper → #8 combined doc + Stripe → #9
DocuSign (own phase).**

Mark up the ten decisions and the cabinet will turn your rulings into a build plan.
