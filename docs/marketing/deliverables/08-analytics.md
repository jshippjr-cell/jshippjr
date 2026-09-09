# Analytics — deliverable

*Wave 2, 2026-09-09. Reads under `docs/marketing/00-brief.md` (§11, §12) and the Brand
Strategist's vocabulary. Where this file and the brief differ, the brief wins. Every
count below is zero on 2026-09-08, because that is the fact.*

Two rules govern everything here. **Trust, not reach; volume is never a metric.** And
**a number is recorded once, in one place, by one person, or it is not on the sheet.**
Where ChordOS holds the fact, the sheet copies it out; nothing is typed twice.

What ChordOS measures today, verified in code: `opportunities.source` (default
`unknown`); site inbounds as `inbound_leads` (`questionnaire` / `book_call`); discovery
calls as `meetings` (`ingested` / `transcript_ready` once held); signed Discovery
Summaries and contributor releases as `signature` rows by `doc_kind`; every send in
`outbox`; win/loss in `opportunities.status`; replies as `agency_outreach.responded` or an
`outreach_events` row with direction `Received`; the relationship stage derived once in
`buyer_intel.relationship_for` (ADR-0057); rounds, approval, package and release in
`delivery_json` (`round_log`, `creative_lock.at`, `delivery_zip.built_at`, `released_at`),
all stamped by the system. There is no analytics script on the public site, no
newsletter table, and no field anywhere for "how did you hear about us".
`db.source_attribution` rolls leads up to Website / Crawler / Email / Signal, a lead-board
vocabulary, not a marketing one.

---

## 1. The dashboard

Two rows. Followers, impressions, page views and likes are not on it (§4).

### Lagging outcomes

| Metric | Definition | Source | Who records |
|---|---|---|---|
| Discovery calls, with source | A `meetings` row that reached `ingested` or `transcript_ready`, joined to its opportunity's `source`. A booked call that did not happen is not counted. | ChordOS: `meetings` × `opportunities.source` | The system; the founder sets `source` (§3) |
| Signed Discovery Summaries | `signature` rows, `doc_kind = discovery_proposal`, `voided_at` null. | ChordOS: `signature` | The system |
| Unsolicited inbound from a producer we did not contact first | An `inbound_leads` row whose person has no prior outreach row and whose `source` is not `outbound`; counted once the founder confirms the seat is tier 1–3. | ChordOS: `inbound_leads`, `buyer_person`; the seat from the founder | The founder, Friday |
| Referrals from partners and editors | An opportunity with `source = referral` and the referrer's name in `notes`. | ChordOS: `opportunities` | The founder, at intake |
| Win/loss captured without exception | Every opportunity that reached `Submitted` ends `Won`, `Lost` or `Passed`, with one line on why in `notes`. The metric is closed deals *without* a reason, which must be zero. | ChordOS: `opportunities.status`, `notes` | The founder, the day the decision arrives |
| Founding engagement | A project with a countersigned proposal (`discovery_proposal_countersign`) and a paid deposit invoice. Zero until it is not. | ChordOS: `signature`, `invoices` | The system |

### Leading signals

| Metric | Definition | Source | Who records |
|---|---|---|---|
| **Clearance Reads requested** | A named person asked for a Read, in any channel, in their own words. Counted at the request; delivered Reads are a second column. | The Friday sheet, until §5 item 1 lands | The founder, the day it is asked |
| **Replies from target roles** | An inbound message from a producer, head of production, executive producer, business affairs / legal / procurement, or music supervisor, to a touch or a post. "Thanks" counts; an auto-reply does not. One per person per week. | `outreach_events` (direction `Received`) and `agency_outreach.responded` for the named list; the LinkedIn inbox for replies to posts | The founder, when logging the touch |
| Saves and shares on the artefacts | Saves + reposts on the three m02 artefacts and the Wednesday recording. Reposts show on the post; saves appear only in the poster's analytics view (verify). | LinkedIn post analytics | The founder, Friday |
| Organic search to the pillar pages | Clicks from Google Search to each of the six pillars. No page-view tool exists and none is recommended. | Google Search Console (verify: domain not yet verified) | The founder, Friday |
| Connection acceptance from the named list | Accepted ÷ sent, for requests to the thirty and the sixty-name list only. | LinkedIn "My network → Sent"; the named list in the sheet | The founder, Friday |
| Founder hours on marketing | Hours this week on posts, comments, communities, the site. Threshold: ≤ 8. Selling hours are a separate column and must exceed build hours. | The Friday sheet | The founder, Friday |
| Sequences started | Named people at touch one this week, and which touch each open sequence is on. | `agency_outreach` / `outreach_events`, tagged `outbound` | The founder, when sending |

The two the CEO reads first are in bold. If only two cells are filled on a Friday, it is
those two.

## 2. The weekly sheet

One tab, one row per week, filled on Friday in fifteen minutes. Columns, in order:

`week` · `selling_hours` · `marketing_hours` · `build_hours` · `sequences_started` ·
`people_in_sequence` · `connections_sent` · `connections_accepted` ·
`replies_target_roles` · `reads_requested` · `reads_delivered` · `posts_published` ·
`comments_left` · `community_contributions` · `saves_shares` · `search_clicks_pillars` ·
`inbound_unsolicited` · `discovery_calls` · `summaries_signed` · `referrals` ·
`closed_without_reason` · `note`

The routine:

1. Open ChordOS. Copy out calls, signatures, referrals, closed-without-reason, replies and
   sequences. Five minutes. Nothing the system holds is retyped from memory.
2. Open LinkedIn once. Fill connections, saves and shares, posts, comments. Five minutes.
   Close it.
3. Fill the hours, the Reads, the community count and the note. The note is one line:
   what changed, and one thing to stop or start. Five minutes.

**Thresholds.** The brief's stop rule (§11; roadmap m06) is *no leading signal from a
series or channel in eight weeks → stop it.* Per channel, with the signal that counts as
its own:

| Channel | The leading signal that keeps it alive | Stop if, over any 8 consecutive weeks |
|---|---|---|
| Monday series (How Agencies Actually Buy Music) | A reply, save or share from a target role, or a Read request that names it | zero of any |
| Wednesday series (What Actually Happens After Approval) | Same; YouTube is the archive copy and counts nothing on its own | zero of any |
| Friday series (Producer's Notebook) | Same | zero of any |
| Daily comments | A reply from a target role, or a connection accepted after a comment | zero of either |
| Each community (two) | A reply from a target role or a Read request traceable to the room | zero of either after the tenth contribution; leave for a quarter the first time the room reads us as promotion |
| Named-list connecting | Acceptance on the named list | under 20% for 8 weeks → rewrite the note, not the list; the list is the ruling |
| The five-touch sequence | A reply from a target role, or a Read request | zero across 30 started sequences → rewrite touches two and three before touch five is sent again |
| Search pillars | Any Search Console click to a pillar | zero 8 weeks after indexing → rewrite the page to the actual query; never delete it |

Two cut rules sit beside the stop rules: `marketing_hours` over 8 for two weeks running →
cut LinkedIn posting first (brief §11); `build_hours` over `selling_hours` in any week →
the week is recorded as failed in the note (Ruling 5).

**The 60-day review of the stand-down.** The demand engine was stood down on 2026-09-08;
the review falls in the week of **2026-11-06**. It asks four questions from the sheet and
nothing else: how many of the thirty reached a conversation; how many Reads were requested
and delivered; whether a founding engagement exists; whether any week failed the
build-versus-selling rule. The engine is re-cued only if the first three are non-zero and
the fourth is zero. If the thirty produced nothing, the answer is a different thirty, not
a demand engine.

## 3. Source attribution

**The vocabulary**, closed. One value per opportunity, set once, changed only by the
founder with a note saying why:

`referral` · `community` · `linkedin` · `search` · `outbound` · `event` · `inbound_site` ·
`unknown`

Rules: `outbound` means we contacted them first, wherever they answered. `linkedin` means
a post, comment or profile we did not aim at them. `referral` needs a referrer's name or
it is `unknown`. `inbound_site` is the two forms, until the call says what brought them.
`unknown` is legitimate and is reported, never filled with a guess.

**Where each value is set:**

| Moment | Who | Today | Should be |
|---|---|---|---|
| Intake, site form (`/start`, `/book`) | The system | `inbound_leads.source` = `questionnaire` / `book_call`; promotion stamps the opportunity `front_of_house` | Same; reads as `inbound_site` on the sheet. No "how did you hear" field: the call answers it better and the form is already long. |
| Intake, by hand | The founder | `opportunities.source` defaults to `manual`; the form does not ask | The founder picks from the closed list at creation; `manual` is retired |
| Intake, from lead boards and the crawler | The system | `signal`, `crawl`, `gmail`, `mandy`, … | Unchanged; all report as `outbound`, because none is a buyer coming to us |
| The discovery call | The founder | Nothing captures it; the script does not ask | One early question, *how did you come to us?*, overwrites `inbound_site` or `unknown` that day |
| After the fact | The founder | `notes` only | One correction allowed, with the reason in `notes`; the old value stays in the note |

**Supported already:** a `source` column on every opportunity and lead; the form's two
values; promotion carrying a source into the pipeline; `db.source_attribution` rolling
leads up to won. **Not yet:** a closed vocabulary (the column is free text with
eight-plus system values), a place on the form or the call to set it, and a roll-up in
this vocabulary. The mapping is mechanical; §5 item 2.

## 4. What not to measure

| Excluded | Why |
|---|---|
| Followers, total connections | Reach. A follower is not a producer, and the thirty are named. |
| Impressions, views | The platform's number about itself; it moves with the algorithm and rewards the engagement bait the brief forbids. |
| Likes, reactions, comment counts | Volume. A save from a target role is on the dashboard; a hundred likes from composers is not. |
| Page views, sessions, bounce rate | No analytics script exists and none should be added. Search clicks to the pillars is the one web number that says a producer asked a question we answered. |
| Newsletter subscribers | No list until Q2 (brief §10). When it exists, replies are the metric. |
| Email open rate | Mail clients prefetch; it measures a subject line, not a decision. |
| Posts published, comments left | On the sheet as *activity*, never as *results*; they give the stop rule its denominator. |
| Pipeline value, win rate | Real, and computed by ChordOS, but a rate over one or two deals is noise read as signal. Quarterly, never weekly. |
| Brand awareness, share of voice | Unmeasurable without a fabricated benchmark. "I've seen your posts" on a call goes in the note. |

## 5. What ChordOS should record that it does not yet

For the CEO seat, in priority order. Each is a need, not a schema.

1. **A Clearance Read as a record**: who asked, when, from which channel, delivered when.
   Belongs on the opportunity (or the person, when no deal exists) as an event kind in
   `outreach_events`, so the leading metric is counted by the system, not the sheet.
2. **A closed `source` vocabulary on the opportunity**, with the mapping from today's
   system values, set at creation and correctable once. On `opportunities.source` and the
   opportunity form; `db.source_attribution` reports in that vocabulary.
3. **The seat of the person who replied.** `outreach_events` records channel and direction
   but not who; `agency_outreach.contact` is free text. A reply should carry the
   `buyer_person` and their role, so "replies from target roles" is a query.
   `decision_makers.role_category` already classifies titles; reuse it.
4. **A reason on every loss.** `Lost` and `Passed` take none; the brief requires win/loss
   captured without exception. One required line on the status change, on `opportunities`.
5. **Which touch of the five a person is on**, its date, and the six-month stop after a
   no. Today each touch is a free log row and the position lives in the founder's head.
   On `agency_outreach` or the person.
6. **A demo mark on seeded records** (brief §8.2), so every computation in §6 excludes
   them mechanically rather than by the founder remembering which projects were real.
7. **The referrer on a referral**, as a person, not a note.

None is a product surface; each is a column or an event on a table that exists. Whether
they count as freeze exceptions is the founder's call (brief §13.3).

## 6. The quarterly review, and the numbers we publish

**The review** is one page, in the founder's first person, on the last Friday of the
quarter. Sections, in order:

1. The thirty: how many reached a conversation, a call, a signed summary, an engagement.
2. The dashboard, both rows, quarter total and the eight-week trend of the two bold cells.
3. Source attribution: every discovery call and signed summary, by source.
4. What was stopped under §2, with the eight-week evidence.
5. Founder hours, the weeks that failed the build-versus-selling rule, and what changed.
6. The numbers below, as published.
7. The next cue sheet, shorter than the last (m06's exit condition).

**The numbers the studio publishes about itself** (brief §12). Only numbers the system
computes from records it holds, each printed with its denominator and date range; under
three, the raw count with the words *too few to average*. Until the first paying
engagement, every one reads *not yet observed*, which is a complete sentence (brief §5).

| Published number | Computed from | Never from |
|---|---|---|
| Rounds per engagement | `round_log` length per delivered project | `revisions_used` typed by hand, or a target |
| Days from approval to package | `creative_lock.at` → `delivery_zip.built_at`, per project | A promised turnaround |
| Releases on file | Contributors on delivered projects with a `contributor_release` signature, over contributors named | "Everything is cleared" |
| Signed summaries that became engagements | `discovery_proposal` signatures with a countersignature, over signatures | Pipeline value |
| Notes priced before work began | Notes classified before a creator saw them, over client notes (ADR-0069) | An SLA |
| Signatures still matching their document | `signature` rows whose digest verifies, over signatures | A guarantee |

Never published: a client by name without written permission, a percentage over a
denominator of zero, or any rate computed on demo data. Demo projects are excluded from
every computation above; §5 item 6 is what makes the exclusion mechanical.

---

## Objection to the brief

One, narrow, on §11.

The brief lists **connection acceptance rate from the named list** as a leading signal.
On a list of thirty, one acceptance moves the rate by three points, and the founder can
raise it at will by sending fewer requests. I would record the count of acceptances and
leave the rate off the dashboard until the list is the sixty-name one from m03.

I continue under the brief as written: the rate is on the sheet with its denominator
beside it, and the §2 threshold runs eight weeks so a single week cannot trigger it.
