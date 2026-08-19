# ChordOS — Project State

*The "you are here." A living snapshot of what exists, what's in flight, and what's
deferred — so a new session orients in one read without spelunking. Update this when
the state materially changes; keep it short and current. For the enduring **why**,
read `CONSTITUTION.md`; for **binding decisions**, `ARCHITECTURE_DECISIONS.md`; for
**commands/conventions**, `/CLAUDE.md`.*

**Last updated:** 2026-07-18 · **Phase:** A (studio force-multiplier, dogfood-first)

---

## What ChordOS is today

A single-operator, internally-used operating system running the Chordential music
studio end to end — demand side (find/qualify/estimate/prepare/outreach/win) and
supply side (recruit/match/assign/produce/review/deliver). Deployed on Render;
FastAPI + Jinja + SQLite; ~915 tests, must stay green before commit.

## The three-OS model (the architectural pivot)

ChordOS is resolving into three stacked systems:
- **Intelligence OS** — ✅ built. Discover, understand, qualify, reason, CRM,
  opportunity, proposal.
- **Workflow OS** — 🔨 partial. Projects, tasks, production, delivery, status,
  approvals, QA, rights.
- **Creative OS** — 🔨 building; **increment 1 shipped and flag ON in prod**. The
  **Campaign Workspace** — one screen, one campaign, everything (brief, direction,
  team, timeline, references, cues, versions, stems, reviews, approvals, rights,
  delivery). This is the layer that makes ChordOS impossible to copy. **Fully
  specified in `docs/campaign-workspace-prd.md`.** Increment 1 (the campaign
  container + structured creative direction + creative-timeline phases) is live
  behind `CHORDENTIAL_CAMPAIGN_WORKSPACE=1` (dogfooding). Governing law: every
  feature must make ChordOS feel more like the OS for campaign music, never like
  generic project management.

## The three mechanisms — current maturity

| Mechanism | State | Notes |
|---|---|---|
| **Intelligence** | ✅ engines built; presentation partial | Agency discovery, enrichment (micro-agents), decision-makers, company intelligence, signal detection, opportunity scoring all exist. The control-room UI in `platform-website-plan.md` is planned, not built. |
| **Relationship** | ✅ built | Buyer graph, relationship stages, outreach drafting **+ real branded sending / copy / open-in-mail**, follow-up continuity, institutional memory. `/relationships` batched to O(1) queries. |
| **Delivery** | ✅ built (flagship) | Delivery OS (Rights/Revisions/Metadata/Approvals/Assets), token-gated review portal with **timecoded feedback + audio-playhead persistence**, creator portal with **client feedback shown + publish gate**, clearance-certified delivery package (browser + ZIP, single-source legal copy), payment gate. |

## Mission spine — implementation map

Demand: `intake.py` · `scoring.py` · `qualification.py` · `strategic.py` ·
`estimation.py` · `prepare.py` · `outreach.py` · win/loss in `web/db.py` ·
`web/buyer_intel.py`.
Supply: `talent.py` · `matching.py` · projects/assignments + `delivery.py` +
`web/decision_makers.py` · `web/enrichment.py` · `web/intelligence.py` ·
`web/opportunity_signals.py` · `web/music_opportunity.py`.
Web/OS surface: `web/app.py` (routes) · `web/public.py` (front-of-house) ·
`web/scheduler.py` (background engines) · `web/db.py` (storage, backend-portable).

## In flight — the Client Workspace + Commercial Commitment layer (ADR-0018)

The product is being reframed (operator directive, the "ten principles" in
`docs/client-workspace-principles.md`) as the OS for the **entire lifecycle of a
commercial music engagement**: one durable **Client Workspace** (one token-gated URL
that never changes), contents evolving by a computed **phase**
(`intro → discovery → brief → commercial → kickoff → production → delivery → archive`).
Client **commitment drives state** (approval of the Commercial Review is the primary
award trigger; operator buttons are fallbacks). Building foundation-first:
- **P0 (done):** durable workspace token (project inherits the opp token), the phase
  engine (`web/workspace.py`), `/workspace/{token}` shell, and the **Campaign Brief folded
  inline** via the stage-partial pattern (`_brief_document.html` + static `brief.css`). The
  workspace is the canonical client link (emailed link → `/workspace/{token}`).
- **P1 (done):** the **Commercial Review** (`web/commercial.py`) — the formal agreement,
  projected entirely from CI + estimation/proposals, **frozen at operator release**
  (`commercial_reviews`), rendered inline in the workspace as the brief's continuation, with
  a client electronic approval (`commercial_approvals`) that advances the phase to Kickoff.
  Operator decision: freeze-at-release + operator-released (see ADR-0018).
- **P4 (done):** **Kickoff — the Production Readiness Workspace** (`web/kickoff.py`). The
  client's Commercial approval is the **award trigger**: it creates the project and the
  workspace enters KICKOFF (gated from PRODUCTION by `projects.kickoff_completed_at`, which the
  operator stamps via "Start production"). A concierge handoff, not a form — campaign summary,
  production checklist, team, communication, milestones, and a "everything is ready" state,
  all projected from CI + the approved Review + the project. Legacy won projects (no approved
  review) skip Kickoff → Production, unchanged.
- **Production OS increment 1 (done, ADR-0019):** the Direction→Version spine on the
  EXISTING delivery machinery (`web/production.py`, no new tables): `directions` (territories
  with thesis + fate + rejection reasons), `round_log` (the ledger behind `revisions_used`,
  fed by review/changes, post-lock rounds stamped), `creative_lock` (a record, not a label),
  and the computed **court-state** (client|studio|scheduled + age). The Workspace PRODUCTION
  phase now answers the court question in concierge voice + shows the creative journey; the
  delivery portal remains the listening room. Operator: Directions card + lock on the
  delivery console. Business model: `docs/production-lifecycle-model.md` (agreed, both
  passes).
- **P2, P3, P5 (planned):** producer-voiced Terms engine (basic shipped in P1) →
  commitment/audit enrichment + DocuSign seam → adaptive procurement + delivery unification.
  See `docs/client-workspace-principles.md`; ADR-0018 for decisions.
- **Later:** CI → Relationship Intelligence (CI accumulates per client across campaigns).

## Recently completed (this working stretch)

- **The taste gate had no door in the room** (ADR-0072, 2026-08-19). *"I don't see a way
  for me to push a version out to the client after review, nor how to deny it and send it
  back to the composer."* Publish lived only on the delivery console, so the operator
  auditioned a take in the room and had to leave it to act. And the console's other
  button, **Discard**, cleared the submission and told the composer nothing — no reason,
  no email. Both are in the room now, and denying a take is a **send-back** carrying a
  reason to the crew by email and into the room's event stream (never to the client; they
  never heard it). It spends no revision round. Also: the console's live feed replayed
  the notes above the title, before anything you came to the page to do — presence stays,
  the feed is opt-out per mount and the room keeps its own.

- **A take and its notes are one thing** (ADR-0071, 2026-08-19). A composer submitted v2
  and the room still opened on v1, with v1's notes on the lane — because notes were
  filtered to the version under review and rendered once, so there was nothing for
  selecting a take to select. Every note now names the take it was written against; the
  newest take leads (labelled `v2 …`, not "with the studio"); clicking a take row loads
  it *and its notes* without starting it, with ▶ kept for auditioning. A take nobody has
  heard opens on an empty pane, and a new note lands on the take that is playing —
  validated server-side, since a version string from a form is not a fact. The room also
  speaks a note as the playhead reaches it. Alongside: a verdict given in the room stays in the room
  (`origin=room` — Request changes used to eject the client to the delivery portal), and
  a submission waiting at the taste gate raises a **Queue nav badge**, because the alert
  went out by email and no page said anything.

- **The client's room named the freelancers** (ADR-0070, 2026-08-19). The presence
  roster ("Ada · talent"), every note author and every line of the live feed reached the
  buyer by name — the executive review's one condition on putting the room in front of a
  real client, because the roster IS the business. `see_who` is now an operator/talent
  capability and `room.attribute` signs our whole side of the room as **Chordential**;
  the client's own names stay theirs. Which side a note came from is recorded at the
  write (`review_comments.author_role`) — every arm of the note route already knew and
  threw it away, which is how `actor_role="client"` came to be stamped on notes the
  studio wrote. Shipped with it: takes bound to the cut they were written against
  (chips read `v2 · cut 1`, an out-of-conform band when they disagree); sync measured
  every frame and corrected by `playbackRate` trim rather than a hard seek that clicks,
  with the offset on screen; and a standing note that browser playback is true for
  timing and intent but is not a mix room.

- **The keyboard belonged to whatever you last clicked** (2026-08-19). Space deferred to
  the focused control, so a tapped note or the Range button swallowed the transport key;
  Escape closed the B/N/V sheets, so three unrelated gestures dismissed a layer and none
  of them was the one that opened it. Space is the transport and nothing else; a sheet
  closes by its own key or by clicking away. **Range** gained the state it never had —
  open it, close it, the highlight STAYS while you write, and it can be drawn by
  dragging across the Notes lane.

- **A client was shown the internal login at the moment of signing** (2026-08-17).
  Reported live: a client opened her Discovery Summary from the emailed link, read it,
  typed her name, drew her signature, pressed **Sign and accept** — and got
  *"Procurement OS — internal / Password or passphrase"*. `/workspace/{token}/sign` had
  been added to the router and not to `app._WORKSPACE_RE`, the alternation exempting
  token-gated client paths from the admin gate. The GET was exempt, so the document
  rendered perfectly and the gap appeared only at the one moment it exists for. The
  operator's first guess — a stale link — was wrong: the share token is durable (ADR-0018)
  and still resolved. The exemption list is now **derived from the router** by
  `tests/test_the_client_never_meets_the_login.py`, verified by reintroducing the bug, so
  it cannot fall behind again. Also fixed on that screen: `That didn’t match` — a
  Python escape written into HTML, rendering raw.

- **The price is now the work, everywhere a buyer can see it** (ADR-0065, 2026-08-17).
  `quote_band`'s disclosed-budget tier is gone — the client's stated figure produces a
  **verdict**, not a price, and the verdict lands on the deal page naming both numbers so
  the decision (reduce the scope, or decline) is a human's. Wiring it exposed two latent
  divergences the budget-as-quote had been masking: the Commercial Review priced off
  global role rates while the project's own proposal used the assigned creators' real
  ones (now one helper, `_estimate_for_row`), and the public intake was converting the
  authority's band at margin a second time. Most striking find — the seeded orchestral
  fixture: $25,700 of players and room, $34,468 to deliver, and we were quoting the
  client's stated **$8,000–$15,000**. Less than half of cost, silently, on every deal
  shaped like that one.

- **The module that crippled anything importing it** (2026-08-16). `_enrich_worker` set
  `RLIMIT_AS` **at import time**, soft and hard together — and a lowered hard limit can
  never be raised again, not even by root. Any process that merely imported it was capped
  at 320MB for life, and the only symptom was `Thread.start()` blocking for ever: no
  exception, no message, just a hang. It bit **twice**. First through `test_oom_guards`
  itself, which was fixed by moving that check to a subprocess — the symptom, not the
  cause. So it bit again through `test_scheduler_loop`, which imports the module to drive
  the worker in-process: run alone the suite fitted inside the cap and passed; batched
  with other files it deadlocked in `asyncio.to_thread` and a whole batch timed out at
  600s. Diagnosed with **py-spy** on the hung process, confirmed pre-existing by replaying
  the identical batch on a worktree two commits back. The ceiling now belongs to `main()`,
  where the process is known to exist to run one job and die. That batch: 600s hang →
  **10.5s, 88 passed**.
- **We know how we are pricing the product** (ADR-0065, 2026-08-16). Reported live: *"I
  have no idea how I am pricing the product. The proposal generated a price based on what
  the client told me their budget was, which is a name-your-price on my service."* True:
  `quote_band`'s second tier was the disclosed budget, which fires on every deal that has
  had a discovery call. Measured on one film — cost $4,062–$8,435, quoted **$6,000** to a
  client who said $6,000 and **$90,000** to one who said $90,000. `pricing.py` now splits
  a **creative fee** (cost at target margin) from a **licence fee** (media × territory ×
  term × exclusivity), because production cost is flat with respect to usage and value is
  not — the same cue is $14,000 or $28,500 on the licence alone. Budget is demoted to a
  three-way verdict. Calibrated against real competitor data in
  `docs/market-pricing-research.md`; the clearest miss was exclusivity, priced at +85%
  against a market of +150%. **Not yet wired to what a client is quoted** — that is a
  business decision and the factors are the operator's to ratify.
- **The discovery summary is the proposal, and it can be signed** (ADR-0065, 2026-08-16).
  A met deal's summary carries the commercial close and an Agreement block; accepting it
  is a real signature bound to a SHA-256 of `agreement.signable_text()`, so a term moved
  afterwards reads SUPERSEDED. Sign with a **finger on a phone or a mouse on a desktop** —
  the drawn mark is validated as a base64 PNG or dropped, is excluded from the digest, and
  is never required, so a browser where the canvas fails still signs. Supersedes ADR-0020
  on one point only (no pricing in the summary); its rule of exactly ONE commercial
  commitment is better served, because the client used to be asked twice.
- **The prep sheet prices its own questions** (ADR-0065, 2026-08-16). The four licence
  questions were already on the sheet and already flagged as the ones dropped when a call
  overruns; now each answer is costed against the live deal, loudest first. On the
  Larkspur test deal, exclusivity is worth **$8,000**.
- **The budget reached the Budget field** (ADR-0064, 2026-08-14). A live discovery call
  stated it plainly — *"roughly 25. No, no, 30,000. And that's all in including any
  licensing"* — and the ten-agent engine read it correctly, spoken correction and all,
  then filed it as **`commercial/budget_band`** while the slot is
  `(engagement, budget_band, fact)`. The field showed its placeholder with the right
  answer in the evidence column beside it; Deliverables the same. This was the first
  comprehension call's defect fixed for the KEY only — half an address. The facet is now
  derived from the key, facts already stored are repaired once at boot (free, idempotent,
  never overwriting a value a human put there), and only facts move: an open question about
  the budget stays a question.
- **The calendar block, all the way down** (ADR-0063 + follow-ups, 2026-08-14). Four
  more layers under the invite format, each silent. **The operator address**: unset
  `CHORDENTIAL_OPERATOR_EMAIL` fell back to `CHORDENTIAL_SMTP_FROM`, so an unconfigured
  inbox looked configured and confirmations went to the app's own sending address; it is
  now declared in `render.yaml` and flagged on the page. **The send status**: returned by
  the mailer and dropped, so "no provider", "SMTP errored" and "sent" were one observable
  event — now recorded per meeting and shown on the card. **Google's refusal**: caught into
  a log line, and `str(HTTPError)` is only "HTTP Error 400: Bad Request" — the reason is in
  the response body, unread. Now surfaced with Google's own words. **The credential**: a
  service-account key that was SET BUT UNREADABLE returned `None`, indistinguishable from
  absent, so `configured()` fell through to the leftover OAuth variables and silently
  resumed the expired token the operator had already retired to escape the 7-day expiry —
  broken no longer falls back, and a key file can be pasted in raw (its mangled newlines
  are repaired) instead of requiring `base64` first. The last mile was not code at all:
  Gmail's *"Add invitations to my calendar: only if the sender is known"* was declining to
  place an invitation it had received. **Confirmed working on the operator's calendar.**
- **A test that capped its own process** (2026-08-14). Pre-existing, invisible under
  `-n auto`, and it stopped a serial batch dead for 900s twice. `test_oom_guards` imported
  the enrichment worker into the pytest process; that module lowers `RLIMIT_AS` soft AND
  hard, a lowered hard limit can never be raised again, and the restore threw straight into
  an `except: pass`. Everything after it ran under a 256MB address-space cap and the first
  test needing a thread stack hung in `Thread.start()` for ever — no failure, no message.
  Now checked in a subprocess, with a second test asserting the parent is never capped.
  That batch: 900s timeout → 70 passed in 11s.

- **A booked call lands on a calendar without anyone pressing anything** (ADR-0063,
  2026-08-14). Reported live: *"I dont want to click anything."* Four defects between a
  booking and a block, each of them silent. The invitation was being **presented as a
  download** (`Content-Disposition: attachment`), so no client offered an RSVP card at
  all — fixed first, by adding the calendar as a `multipart/alternative` part carrying
  `method=REQUEST`. Then: the operator was listed as a **guest of their own meeting**
  (`RSVP=TRUE; NEEDS-ACTION`), so their own calendar greyed the entry out awaiting a Yes
  — they are the `ORGANIZER`, and their invitation now arrives `PARTSTAT=ACCEPTED`. The
  `.ics` was suppressed whenever a **native event existed**, on the belief Google had
  invited everybody — true only on the OAuth path, and false in exactly the
  service-account configuration the setup guide recommends, so the **client's** invitation
  was withheld on the strength of an invitation nobody had sent. That question is now
  asked per recipient (`invites_for`) and answered by the seam (`invites_attendees()`) —
  three configurations, three answers, where the code had two. And `SEQUENCE` was
  hardcoded, so the **second** reschedule of any call was discarded by every calendar
  client without an error anywhere; it is stored per meeting and advanced in one
  statement. Lines are folded to 75 octets on the way out. Verified on real Postgres,
  including the column migration against an existing database. What still cannot be
  promised: an invitation **asks** — writing to a client's diary without their consent is
  not something to build, and only the OAuth path has Google invite them for us.

- **The cube is a cube, and then it is a package** (ADR-0062, 2026-08-12). The front
  door's world had **150 of its 728 pieces finishing assembly outside the box, the worst
  by 125 units — 42% of the cube's own width**: staves projecting through the faces,
  fragments floating clear of the corners. The layout existed as **three copies in an
  ephemeral scratch directory**, so the one that shipped could be wrong for weeks while
  the Blender file the look was judged in was fine. It is now described **once**, in
  `scripts/score_scene/recipe.py`, and reported to a recorder — the web exporter and the
  Blender builder. The extraction was proved behaviour-preserving (regenerated scene
  byte-identical), and comparing the two recorders immediately surfaced a second defect:
  every glyph in the offline model sat at **double** its offset, because `matrix_world`
  was assigned against a stale parent matrix in background mode. Both now report zero
  pieces outside. `fit`/`seat` slide a run inward and shorten only when the box is
  genuinely narrower, so **nothing is dropped** — same 7,419 marks, same 728 pieces.
  On top of that the cube now **folds into an open delivery carton whose outline is staff
  paper**: 80 pieces lay themselves along its 24 edges, 648 stack flat inside it, and the
  four ember notes take its corners so the page is still playing music where it asks for
  the brief. `tests/test_score_scene.py` holds containment at zero, holds the cube full,
  holds it touching its own walls, and fails if the shipped `.bin` is stale.
- **Roles** (ADR-0055, 2026-08-06). `owner` / `operator` / `viewer`, enforced in the gate
  so no route can be missed. A hire can run campaigns; only an owner can release a
  delivery, confirm a licence, move money, delete an opportunity or rotate a share link.
  **The shared passphrase keeps full access** (break-glass) and an instance with no
  accounts is completely unaffected. The first bootstrapped account is an **owner** —
  otherwise the founder's only account could not release their own delivery. Default is
  restrictive, so a route added tomorrow is covered by its method rather than by someone
  remembering a file. **Phase 4's auth item is now complete.**

- **Accounts and sessions** (ADR-0054, 2026-08-06). Sign in with email + password and the
  decision log stops saying "the operator" and says **who** — the seam ADR-0053 was built
  for, filled without changing a call site. **The shared passphrase still works and always
  will**: it is break-glass, not legacy, and a change that could lock the operator out
  mid-deploy is not worth any tidiness. scrypt from the stdlib (no new dependency), session
  tokens stored as digests, revocation and expiry checked on every request, sign-out
  revokes server-side. First account bootstraps from the environment, once, and never
  overwrites. **Next: roles** — the column exists and nothing enforces it yet.

- **Phase 4 started: every state change is attributable** (ADR-0053, 2026-08-06). The
  first slice of "multi-user auth with actor identity", done deliberately BEFORE any login
  change because it is additive and cannot lock anyone out. Dozens of decision routes
  recorded the actor as a hardcoded `"Studio"`/`"ChordOS"` or nothing; every mutating
  request now writes who/what/which-record to `decision_log`, derived in the gate
  middleware so no route can be missed. **It records a ROLE, not a name** — one shared
  passphrase means the system cannot know which human, and naming one anyway would be a
  lie that looks like evidence. Tokens are fingerprinted, never stored. **Next in this
  item: real accounts and sessions, then roles.**

- **The delivery state machine moved into the engine** (ADR-0052, 2026-08-06) — the last
  Phase 3 item. It lived in the route modules as **18 bare string literals across three
  files**, and the drift that causes was already real: **`"Approved"` was written and
  compared by the routes while missing from `DELIVERY_STATES`**. The non-obvious
  transitions are now named functions in `delivery.py`, and `update_delivery` **raises** on
  a state outside the declared list. `"Delivered"`/`"Released"` stay inline on purpose —
  naming a tautological transition is ceremony — and are still covered by the guard.
  **Phase 3 of the launch review is complete.**

- **The dashboard stopped asking the same questions** (ADR-0051, 2026-08-06). It composes
  several cards from the same rows and each aggregator fetched them itself: **71 queries
  for four projects**, `delivery_json` read nine times. A request-scoped read memo plus two
  batched priming queries cut it to 51 — and the saving grows with the data (12 projects:
  99 vs 215; 38 projects: **255 vs 683, 62% fewer**), which is what matters now every query
  is a network round trip. The page is asserted byte-for-byte identical with both
  mechanisms off.

- **A buyer is one person now** (ADR-0050, 2026-08-06). A human on the buying side was
  recorded in **five unlinked tables** — `decision_makers`, `discovery_requests`,
  `meetings`, `meeting_proposals`, `review_comments` — each with its own name/email pair,
  so the same person asked for a call, took it, and signed off a master as three
  strangers. `buyer_person` is now the canonical human, keyed by normalised email with a
  UNIQUE index; `link_people` runs at boot and `person_touchpoints` returns one history.
  **Identity is the email and only the email** — no email means no person, because merging
  humans on a name eventually attributes one buyer's approval to another in the record a
  client signs against. **The organisation half is done too** — see below.

- **Client links have a life, and can be shared safely** (ADR-0060, 2026-08-06). A
  reviewer's personal link was `{token, name, email, role}` — no expiry, no record of
  use, no revocation (only deletion, which erased that access was ever granted), no
  record of who issued it, and **no statement of what it may do**, which became
  load-bearing the moment signing arrived: every link could sign the certificate.

  Entries now carry created/expires/last-used/revoked/invited-by and explicit
  sign/approve/delegate capabilities. New links expire (`CHORDENTIAL_REVIEWER_LINK_DAYS`,
  default 90; `0` = never); withdrawal keeps the row; expired and revoked links answer
  **410 with an explanation** rather than 404 at a real client who really was invited.

  **Delegated access reduces risk rather than adding it.** With no supported way to loop
  in a colleague, clients forward the link — so the real access model was *whoever has
  the URL* while the records named one person, and every copy could sign. A verified
  reviewer can now invite a colleague, who gets their own named entry, an expiry capped
  at their inviter's, and **cannot sign, approve or delegate on**. Signing and approving
  stay with someone the operator named; the operator can promote a delegate.

  **Never retroactive:** entries written before these fields exist keep full
  capabilities and no expiry, so live client links are untouched. Use is recorded at day
  granularity — this is the read path of a page clients leave open while a mix plays.

- **The certificate is really signed now** (ADR-0059, 2026-08-06). The Clearance
  Certificate is the one thing the market pays a premium for, and nothing signed it.
  What the product called a sign-off was `{"asset": …, "approver": "Dana Whitfield,
  Aurora", "date": "2026-08-06"}` — a free-text name in a JSON list. **Reproduced on
  seeded data: a client signs off, the operator then changes the licence from
  perpetual/worldwide/exclusive to one year, US only, non-exclusive, and the approval
  record is byte-for-byte identical.** It survived a change to the terms it was a
  sign-off on, because it never referred to them.

  A signature now stores the SHA-256 of the exact document text plus the signer, their
  typed mark, the consent verbatim, the time and a fingerprinted address; verification
  rebuilds the document and reports **SUPERSEDED** when a term moved. Both the console
  and the client's portal say so. Signatures are append-only — voiding marks the row and
  keeps it, because *that* something was signed and later withdrawn is the record. Only
  a verified reviewer (personal `?r=` link) may sign; voiding is owner-only.

  **No DocuSign module, on purpose.** Under ESIGN/UETA this is already a valid
  electronic signature — intent, consent, attribution, association, retention. A vendor
  adds a neutral witness and a procurement checkbox, not validity, and an OAuth/envelope
  client nobody has run against a real account would read as done while being nothing.
  `signing_providers/` is the seam; an unknown provider name raises at boot rather than
  silently signing in-house.

- **Film/TV can be priced now** (ADR-0058, 2026-08-06). The engine was blind to the
  amount of music: one cue and sixty cues both priced at **$57,446**, two minutes of
  score and ninety minutes both priced at **$57,446**. Only format words moved the
  number, so a **:60 commercial with two cutdowns quoted at 1.33× a 28-cue, 45-minute
  orchestral feature score** — the product sold an engagement it could not price.
  Scored media (a format word **and** a scoring signal, so "a series of six spots"
  stays a campaign) is now priced per finished minute plus a per-cue allowance for
  spotting, revisions and delivery.

  Pulling that thread found a second conflation: **orchestral writing and hiring an
  orchestra were one purchase.** The word "orchestra" bought the orchestration hours
  *and* thirty players on every date, which is why an indie feature carried a studio's
  budget. Players and dates are separate scope now, read from the brief, and a sampled
  orchestral score costs the full orchestration hours and **no session** — a real
  delivery the engine could not express. The same 45-minute feature spans **$192,582
  sampled to $493,915 with sixty players over four dates**.

  Minutes, cues, players, dates and live-vs-sampled each carry a stated/assumed flag,
  surfaced on the estimate page and in the assumptions — the amount of music and the
  size of the session are the two biggest drivers, and a guess must not read as a fact.
  **Not done:** the priors (`MINUTE_HOURS`, `CUE_HOURS`, `MINUTES_PER_SESSION`) are
  Phase-1 expert values, **not operator-ratified** the way `PUBLIC_BANDS` are, and
  `PUBLIC_BANDS` has no film/TV entry to anchor them. Per-minute hours are linear —
  thematic reuse should make a long score cheaper per minute and that is not modelled.
  The campaign path is unchanged and pinned by golden values.

- **A buyer is one organisation now, and has one relationship** (ADR-0056 + ADR-0057,
  2026-08-06). The half ADR-0050 deferred. A company was `agencies.id` in Agency
  Intelligence and a bare name string in `opportunities`, `projects`, `companies` and
  `client_procurement_history`, with nothing joining them. `buyer_org` is now canonical,
  keyed by a **normalised name** with a UNIQUE index; `link_orgs` runs at boot and
  `org_touchpoints` returns one history. The name is a weaker identity than the person
  half's email and it is stated rather than hidden: an org with no website still has to
  be canonical, and a shared domain never merges two names — a second domain under one
  name is *counted* as a conflict.

  What the join then exposed: **two relationship engines over the same companies, each
  blind to half the evidence.** The Buyer Graph (`/buyers`) staged from opportunities, so
  it knew we had been paid and had no concept of a relationship going quiet; Relationship
  Management (`/relationships`) staged from the agency outreach log, so it knew about
  dormancy and **could not return "Client" at any input** — the value was in its `STAGES`
  tuple with no code path to it. A company that had commissioned, paid for and received
  delivered work read "Client" on one page and "Active", or after a quiet quarter
  "Dormant", on the other. There is now ONE derivation in `buyer_intel`, one vocabulary
  (`Cold → Warm → Engaged → Client`), and **dormancy is a flag beside the stage rather
  than a fifth stage** — because making it a stage is exactly what erased "Client". The
  two pages cross-link, and `pipeline_stages` still costs a constant number of reads.

  **Still open:** nothing writes `org_id` at insert time (same as `person_id`) — the boot
  pass keeps it current, which is enough while the identity is read-only.

- **The transcript poller backs off, and stops** (2026-08-06). `poll_and_ingest` asked the
  capture provider about every un-ingested bot on every ~30s tick, for as long as the row
  existed — a bot that finishes without a transcript was re-asked **~2,880 times a day, for
  ever**, logging a WARNING each pass. The API calls were not the real cost: **a failed
  capture was invisible.** The call's notes never arrived, the meeting sat in
  `transcript_ready` looking like it was still working, and the tile on the opportunity read
  "◐ Transcript pending" indefinitely — so the failure looked like patience. Now a schedule
  that is dense early and decays to 30-minute checks, a give-up after ~8 hours that writes
  `failed` **with the reason in it**, and a tile that says "✕ No transcript — add the notes
  by hand". Giving up decides nothing about the campaign; it hands the job back to a human.
  Found on the way: `update_meeting` silently DROPPED unknown fields, so the new bookkeeping
  wrote nothing and the fix nearly shipped doing nothing at all. It raises now.

- **An upload now says what happened** (2026-08-06). The byte-progress bar was honest
  about the upload and then said nothing about the RESULT: on success the handler called
  `window.location.reload()`, throwing away the redirect the server had just issued —
  anchor and all — and dropping the operator wherever they happened to be. On the delivery
  console that is **three full screens** from the card the upload produces (measured in a
  browser: form at y=3080, card at y=288, 800px viewport). Reported verbatim in a live
  session: *"I uploaded a new version twice, it went nowhere, I don't know where to go to
  play it back."* The upload had worked both times. Now every `data-upload` form declares
  where its result lands and what it means, the page returns to that card and haloes it,
  and a dismissing banner names the file — for a version, saying plainly that **nothing has
  gone to the client yet**, because every upload waits for an explicit publish and an
  acknowledgement that implied otherwise would be worse than the silence it replaced.

- **`delivery_json` stopped losing writes** (ADR-0049, 2026-08-06). Merging one key was a
  read-modify-write in Python, so two overlapping writers meant the later one carried a
  document read before the earlier — the earlier change gone, nothing raised, both callers
  told they succeeded. Reproduced: **a client's asset approval erased by a simultaneous
  version publish.** Now one statement per merge (`json_set` / `jsonb ||`), which protects
  every key rather than the two the review named — `state`, `license` and `pending_version`
  raced identically and decide what the client sees. `doc_overrides` had the same bug on
  the document the client reads, and is fixed with it.

- **THE POSTGRES CUTOVER IS DONE** (2026-08-06). Production runs on managed Postgres and
  the Render persistent disk has been deleted — so deploys no longer stop the old instance
  before starting the new one, and the ~2-minute 502 on every push (including docs-only
  ones, which is how it kept interrupting live testing) is gone. Migration: 53 tables, all
  `ok`, counts matching, on real volume — `agencies` 11,905, `opportunity_signals` 85,699,
  `decision_makers` 38,924, `media_blob` 12. Rehearsed end to end against a local
  PostgreSQL 16 first: pages served, an uploaded master round-tripped byte-for-byte, and
  id sequences continued rather than colliding. Run as **two deploys, not one** — the
  `CHORDENTIAL_DB` change is reversible while the disk is still mounted, and that rollback
  vanishes when the disk goes; the runbook now says so. **The three preconditions
  (ADR-0046 lease, ADR-0047 indexes, ADR-0048 pooling) were all in place first.**

- **The two cutover preconditions are done** (ADR-0046, ADR-0047, 2026-08-05).
  **One scheduler across instances:** `run_loop` holds a `scheduler_lease` row and does
  nothing without it — blue-green runs two instances *on purpose*, and both were running
  the engines, which means outreach sent twice and meeting bots were polled twice with
  nothing anywhere reporting it. A lease, not `pg_try_advisory_lock`: advisory locks are
  session-scoped and this codebase opens a connection per call across 254 sites, so such a
  lock would release microseconds after it was taken — and would leave SQLite, which is
  what production runs today, with nothing. **Indexes:** there were none at all, and 13 of
  16 hot queries full-scanned, including both client-facing token lookups; now 0 of 16,
  from a declared list of 51. Both verified against a real Postgres 16, not only SQLite —
  they exist for the cutover, so a SQLite-only pass proves the wrong thing.
- **Postgres connections are pooled** (ADR-0048, 2026-08-06). `connect()` is called 254
  times across the web layer, several per page, each closed at once — a file open on
  SQLite, a TCP + TLS + auth round trip to another host on Postgres. The pool sits behind
  `connect()` so no call site changed and SQLite is untouched. Measured on a real server
  over loopback: **25 server backends / 3.95 ms per connect without it, 2 / 0.38 ms with**.
  `psycopg_pool` is optional and a missing one degrades to the old behaviour **and says so
  at boot** — the runbook now checks for it in the shell before the flip, because the
  build-command trap that cost the uploads applies here identically.

- **Launch review — Phase 2, first pass: one pricing voice** (ADR-0028, 2026-08-04). The
  same brief was quoted four ways — $9–18k on the site, $4,847 by the engine, ≈$3.1–6.6k on
  the client proposal, ~$8,694 in the outreach cadence. Three structural faults, all fixed:
  the estimator classified a brief by its **smallest** duration (":60 anthem with :30 and
  :15 cutdowns" priced at half a bare :30 — naming the work made it cheaper); "full
  orchestra" was a **×4 on desk hours** including the PM's and **paid no players**; and
  usage/licence was a **cost** multiplier rather than a fee on price. Role hours now
  describe a campaign cue rather than one demo, `SESSION_PACKAGES` pays players and the
  room, and `PUBLIC_BANDS`/`PUBLIC_LENGTHS`/`PUBLIC_USAGE` are the single definition the
  `/commission` estimator renders from. A national :30 now suggests **$10,414** inside the
  public $9–18k, and the seeded Meridian deal quotes $15,414 against its $15–30k disclosed
  budget (was $8,694). `tests/test_pricing_voice.py` holds the two voices together.
  **Still open in Phase 2:** the nine divergent `build_estimate` call sites, the cue
  sheet's rights contradiction, console nav diet, portal court-state ordering.
- **One "waiting on you" authority** (ADR-0029, 2026-08-04). The dashboard said **2**
  while `/queue` said **11** on the same DB — two independently-coded aggregators
  disagreeing on the operator's most-looked-at number. `queue.compute_queue()` is now the
  only one; the dashboard's inline sum and its duplicate "▶ Your move" table (the same
  decision the Mission Control hero already features) are deleted. `next_action.compute()`
  also floors on the recorded stage, so a **Won** deal staffed and in delivery can no
  longer be featured as "Schedule the discovery call" just because no meeting row exists.
  Note: `compute_queue` now runs on the dashboard too — its cost is on the Phase 3 batching
  list.
- **One open-pipeline number** (ADR-0030, 2026-08-04). Three surfaces asserted three
  pipelines on one DB: the KPI summed `budget_max` (the client's *ceiling*), the Tentative
  column summed `outcome_value`, and `/revenue` read the `proposals` table — where a row
  needs a `project_id`, so it cannot exist until the deal is **won**, making open pipeline
  structurally $0 there. `db.open_pipeline()` now owns it: our bid → the disclosed
  budget's midpoint → counted as unknown, with the composition returned so the number
  shows its provenance. All three read the same figure on the seeded DB.
- **A fileable cue sheet** (ADR-0031, 2026-08-04). The composer column is what a PRO pays
  royalties on, and it credited **every** assignment — reproduced as `composers='Maya
  Chen, Leo Park, Ana Ruiz, Sam Diaz'`, filing the mixer, the editor and the PM as authors
  of the composition. It also carried one conflated `100%` share, hardcoded `BMI` for
  every writer, and hardcoded the main cue to `VV` (Visual Vocal — a sung performance on
  camera) for every bed. Now: `WRITER_ROLES` only, writer/publisher share as separate
  columns, PRO per writer from the new additive `talent.pro` column (editable on the
  talent page, blank when unknown), and usage derived `BI`/`BV` from the brief with a
  per-cue operator override.
- **One rights basis** (ADR-0032, **operator ruling**, 2026-08-04). The package asserted
  three mutually exclusive positions at once — a licence typed "Full buyout /
  work-made-for-hire", a cue sheet filing Chordential as **100% publisher**, and a
  **category-exclusivity** clause. Under WFH the client is the author and owns the
  publishing, so we cannot also collect a publisher share, and exclusivity is meaningless
  on rights we no longer hold. Ratified: **master bought out + perpetual sync licence
  across all campaign media; composition publishing retained.** `DEFAULT_LICENSE` gained
  `publishing` and the missing `media` term, both printed on the certificate; sales copy
  and the demo seed moved to match. Per-deal overrides still win. **Still open in Phase
  2:** console nav diet; portal court-state ordering; brand-unified intake with the
  budget field.
- **One estimate call path** (ADR-0033, 2026-08-04). The four lines that turn an
  opportunity into an estimate were copy-pasted at **nine** web-layer call sites in
  **three** versions. Seven applied the qualified-fallback; the dashboard KPI
  (`_suggested_price`) and the project estimate used `qual.discipline` raw — and because
  `NON_CRAFT` carries an *empty* team shape, the same disqualified deal priced at
  **$7,810 on the dashboard and $8,350 on its own estimate page**. Separately, only the
  project estimate resolved `assigned_rate_overrides`, so an approved number could differ
  from the proposal generated after assignment. `web.estimate.estimate_for(opp, conn=,
  project_id=, qual=)` is now the only path — eleven call sites across `app.py`,
  `public.py` and `seed.py` route through it, and a test fails if a web module calls
  `build_estimate` directly or if the fallback idiom spreads back out.
- **One quote authority** (ADR-0034, 2026-08-04). Chasing the last open thread of the
  pricing finding — "the outreach cadence quotes a different figure from the commercial
  engine" — found **four** surfaces deriving a client quote four ways. The two the *same
  buyer reads* disagreed on every seeded deal: the Campaign Brief reached for
  `_price_band` while the Commercial Review quoted to the disclosed budget, showing
  Brightline **$7,200–$15,100** and **$20,000–$40,000** respectively (Halcyon the other
  way: $8,600–$18,000 vs $6,000–$10,000). Internally the pursuit checklist printed
  `estimate.cost_range` — *our production cost* — under "Provide an indicative quote",
  telling Jon to quote **$4,342** into a disclosed $20,000–$40,000 budget; the cadence
  quoted the estimator's point price, 58% under one client's floor and 33% over
  another's ceiling. It reached the money too: the project's Generate-proposal button
  totalled **$9,712** on a deal whose Commercial Review had told the client a deposit
  implying **$8,000**, and the brief's Pay-deposit figure disagreed with the band printed
  above it. `capabilities.quote_band` (override → discovered budget → estimator's band,
  ADR-0020's precedence) is now the one authority; the client brief, the review, the
  checklist, the cadence, the proposal total and the deposit all render it. Also
  collapsed: `PursuitBrief` carried **three** action lists — the HTML page
  showed `checklist`, `brief.txt` showed `response_outline` + `next_steps` — so one
  brief gave two different instruction sets, with the bad quote line in all three.
  `checklist` is the only list now.
- **Console nav diet** (ADR-0035, 2026-08-04). The sidebar carried **21** links, five of
  which were not destinations. `/lanes` rendered the **identical 18 opportunities** as
  `/inbox` — same table, same one-click advance — and its one unique control, a "Won"
  button, POSTed `status=Won` with no `outcome_value`, booking a won deal at **$0** and
  contradicting the rule documented six lines above `_NEXT_STATUS` in the same file
  ($13,325 vs $25,325 on the same two deals). The four "queue" quick-links were saved
  searches over pages already in the nav — `action` offers Pursue/Review and `status`
  offers Won in `/inbox`'s own dropdowns, and `#followups` is an anchor on the dashboard.
  Route + template deleted; 21 → **16** links. The "in flight" KPI now links to
  `/inbox?status=open`, which reuses `OPEN_PIPELINE_STATES` (ADR-0030) so the number and
  the list agree — it used to open a board showing Won and Closed deals too. The detail
  stepper's identical blind-Won path is closed: it hands off to the win/loss card, which
  carries the value field. This supersedes the `/lanes` half of
  `docs/dashboard-consolidation-council.md`, whose own acceptance test ("no two tabs may
  show the same cards") is what finally decided it.
- **The portal answers the court question** (ADR-0036, 2026-08-04). ADR-0019 ratified
  that the client-facing production experience must always answer whose court the ball
  is in, and built `production.court_state()` to compute it — the portal rendered **none
  of it**. Measured: **Lumen Health** (court=`studio`, nothing owed) and **Vance
  Athletic** (court=`client`, v2 waiting) produced the *identical* page — card order
  `[picture, review, brief]`, the same "Review & approve" CTA — differing only in a hero
  chip reading our internal state machine ("In production · v1 Concept" vs "In review ·
  v2 Direction-lock"). Worse, Lumen has **zero versions**: `v1 Concept` is
  `revision_status`'s *default label*, so the portal named a version never delivered and
  offered a Request-changes form, which opens a contractual revision round (ADR-0019's
  `round_log`) against work that doesn't exist. Now: the hero leads with the engine's
  badge + sentence, cards are placed by court (client → review leads; studio → send us
  the cut; delivered → package), and with no track the section is "The listening room"
  with no version label, no round counter, and no decision row.
- **Delivery filenames stopped fabricating** (ADR-0037, 2026-08-04). Both upload paths
  called `version_name(campaign, "Master", 60, "Master", n, f"v{n}")` →
  **`SUMMER_Master_60_MASTER_v1_V1`**: a hardcoded `:60` (three of four seeded briefs
  never say :60; one says ":06/:15/:30 cutdowns", i.e. a **:30** master), `Master` twice
  (the CUE slot filled with the role; a blank cue became the placeholder `Cue`), and the
  version number twice (`f"v{n}"` in the STATE slot, which is for `FINAL`). The manifest
  separately *recomputed* a stem instead of reading the stored one, so it could list a
  file the package doesn't contain. Now: `estimation.stated_length()` reads the duration
  the brief actually states and the token is omitted when none is — pricing keeps
  assuming :30, naming abstains. One shared `app._master_stem()` for both upload paths;
  the manifest renders the stored stem. Seeded output is now `ORIGINAL_30_MASTER_v1`,
  `BRAND_MASTER_v1`, `SUMMER_MASTER_v1`, `HOLIDAY_MASTER_v1`.
- **Console uploads show real bytes** (ADR-0038, 2026-08-04). The delivery console carries
  the largest files in the system (a cut or a stem package is hundreds of MB) and all four
  of its upload forms were **naked synchronous POSTs** — blank tab, no feedback, no way to
  tell a stalled upload from a slow one. Both client-facing surfaces already had XHR byte
  progress, so the operator had the worst experience in the product. One declarative
  `data-upload` behaviour now lives in `live.js` (rather than a third copy of the same
  twenty lines) and covers the console's four plus the two `audio/*` attachments on the
  brief doc and compose. The bar is driven by `ev.loaded/ev.total` only — no timer, no
  indeterminate crawl. `data-think` still wins where the wait is the server thinking (the
  AI intake). Verified in Chromium on a throttled 24 MB upload, plus the abort path and
  the JS-disabled fallback.
- **A client link can be cut** (ADR-0039, 2026-08-04). The share token is the **only**
  credential on the delivery portal — a bare `?k=` opens the unreleased master, the
  client's brief and scope, and the Request-changes form, which writes the round ledger
  and so **spends a contractual revision round**; without it the portal 404s. There was
  no rotate, revoke or expiry anywhere in the codebase, so a forwarded email or an
  exported Slack channel was permanent access, while the console's own copy told the
  operator to "treat it as forwardable". `db.rotate_share_token()` now mints a fresh
  token and rotates **both** records for a deal (the opportunity's and the project's —
  they can diverge, so rotating one leaves the same work open under the other), stamps
  `share_token_rotated_at`, and is driven by one confirmed operator press logged to the
  project history. Reviewer `?r=` links keep working — revoking one person and cutting a
  leaked link are different acts. Never automatic.
- **The front door plays music** (ADR-0040, 2026-08-04). The hero promised *"written and
  recorded in house by people — never AI-generated audio"* and two lines below it offered
  **"Hear the score"**, which scrolled to a player driven by a **WebAudio oscillator**.
  There was no `<audio>` element and no recording anywhere on the page. The homepage now
  carries a **Listen** section rendering the four real capability demonstrations — from
  the same `showcase.DEMOS` list `/samples` uses, so the two can't drift — with the hero
  CTA pointing at it, and the synth now discloses that its tone is browser-generated and
  links to the recordings. Audio moved off the third-party CDN onto our own
  `/static/public/` (the operator's demo uploads, to be replaced with final masters);
  swapping a track is a file swap at one path.
- **`--olive` clears AA** (ADR-0041, **operator ruling**, 2026-08-04). The last deferred
  contrast item, and worse than filed: `#737469` measured **4.47:1** on `--bg`, **4.15:1**
  on `--panel` and **3.89:1** on `--panel2` — under AA on three of the four console
  surfaces it types on. The Phase-1 pass had fixed `site.css`'s `--muted` but missed the
  same value in **`brief.css`** and **`first_touch.html`** (documents a *client* reads,
  at 3.86:1 on the body) and a raw literal on the homepage's paper card (3.84:1).
  Self-contained palettes are how a sitewide colour fix misses surfaces. Now `#65665B` —
  OKLCH lightness 0.555 → 0.505, hue and chroma untouched — with a 4.78:1 worst case.
  Both palettes, both client documents, the literal and all fourteen `var()` fallbacks
  moved together.
- **The intake asks for a budget** (ADR-0042, 2026-08-04). `/start` promised "an approach
  and a price range" and never asked what the project was worth to the client — though
  the POST handler already accepted `budget_text` and `promote_lead` already extracted it
  into `opportunities.budget_min/max`, **leg 2 of `quote_band`**. The form never asked, so
  the chain ran dry: measured end to end, a lead that would have said **$25,000–$40,000**
  was quoted **$7,200–$15,100** — our cost model, 3.4× under, on exactly the deals that
  arrive through the front door. The field is optional; `public_price_band` now prefers a
  stated budget so the intake band and the later quote agree (amending ADR-0034, which
  had excluded that function precisely because intake captured no budget). The brand half
  of the item needed no work — the intake pages already share the wordmark, serif, ember
  and palette, and all six front-of-house routes resolve.

**Phase 2 of the launch review is complete.**
- **Client media is behind a storage seam** (ADR-0043, 2026-08-04). Phase 3, first item.
  The cutover runbook says removing the disk "destroys every client cut, master and
  stem" — and measured on a seeded instance, **four of five uploaded files had exactly
  one copy**, because three routes wrote straight into `UPLOAD_DIR`, bypassing the helper
  whose docstring claimed to be "the single place that persists media": the intake
  artifact, the procurement document, and the opportunity doc upload. Now every write and
  read goes through `storage.get_object_store()` (local by default, S3/R2 when
  `CHORDENTIAL_STORAGE=s3`); the SQLite mirror is written only when the store isn't
  durable; a remote store serves by presigned redirect; a half-configured switch falls
  back to disk and says so at boot. **The migration itself is not done** — no bucket has
  **The media migration RAN on 2026-08-05 and it is the strongest evidence ADR-0043 has
  produced: 12 files moved, 0 failed — and ALL TWELVE were tagged `mirror only`.** The
  upload directory was empty; the disk had already lost every master and both delivery
  ZIPs (11 MB and 12 MB), and the SQLite `media_blob` mirror was the sole surviving copy
  of the entire media library. A `cp -r /var/data/uploads` would have copied nothing,
  reported success, and been followed by removing the disk. The two-source read was not
  belt-and-braces; it was the whole migration.
  *(Note for the cutover: with a durable store active, `persist_upload` now skips the
  mirror by design, so the bucket is the single copy for NEW uploads — which is the point,
  and is why the Postgres copy must still carry the existing `media_blob` rows across.)*
  been written to from this code (no credentials in the build environment). The runbook
  is now complete and ordered: `docs/zero-downtime-cutover.md` Step 1 moves the media
  (`scripts/migrate_uploads_to_object_store.py`, SHA-256 verified, idempotent) and the
  database copy comes last. **Found while writing it:** the production build omitted the
  `s3` extra, so flipping the switch would have reported durability, dropped every
  upload, and turned off the mirror — zero copies. Fixed and pinned.
  **The audit that followed (2026-08-05) found the claim still wasn't true.** After the
  migration a client version played back as silence, and no amount of reading counters
  off a page could name the file. `/settings/storage` now audits every media key the
  DATABASE references — versions, pending submissions, assets, pictures, delivery
  packages — against the bucket and the mirror, **with sizes**, and names what it cannot
  find. In production it named two files, and neither was uploaded by a person: the
  seeded demo master and the demo's delivery ZIP, both written by `seed.py` outside the
  write door (one `shutil.copyfile`, one direct `store.put`), so neither reached the
  mirror. Seeding is idempotent; the first redeploy wiped the disk and the demo
  campaign's ":60 master" and "Download everything" have been dead since. The guard test
  only matched `open(…, "wb")` — two doors out of four — and is replaced by a
  behavioural one (seed, delete the directory, assert the audit is clean) that fails on
  the pre-fix tree naming exactly those two files. Same class of bug in
  `_build_delivery_package`: it wrote the ZIP to disk and mirrored it directly, so with a
  bucket configured **the one artefact the client pays for never reached the bucket**.
  The seam gained `size()`, because existence is not playability — a zero-byte object is
  present, passes `exists()`, survives a SHA-verified migration, and plays as silence.
  **And the read path was the last write-door bug in disguise:** `/uploads/{name}` handed
  a durable store the redirect without asking the bucket whether the object was there
  (`url()` signs a key blind), so a missing object became a 307 at a presigned URL that
  answers 404 — silence in an `<audio>` element, no error anywhere — *and* skipped the
  mirror fallback, which is exactly where `persist_upload` puts the bytes when a bucket
  write fails. Now the redirect requires a confirmed object, and a mirror-only key serves
  and repairs itself into the bucket.
  **And none of that was the silence.** The cause was the waveform:
  `wave-live.js` called `createMediaElementSource(audio)`, which does not observe an
  element but CAPTURES it — once called, the element's only route to the speakers is
  through the Web Audio graph. The context was built inside the `play` event handler,
  which is not reliably inside the user-gesture window, so Chrome started it suspended;
  `resume()` was a promise nobody awaited, and the audio was already captured. Measured
  in a browser: element playing, `audio.paused` false, no MediaError, `ctx.state`
  suspended, the graph's clock frozen at 0, `currentTime` stuck at 0 — and not one
  visible signal, on any surface, that anything was wrong. Every other layer was healthy
  and said so, which is why it took several rounds to find. Now the context is built and
  resumed from the CLICK, and nothing is tapped unless `ctx.state` is genuinely
  "running": a still waveform is a decoration we can lose, silence is not. Verified both
  ways in a real browser (suspended → element plays untouched; running → the wave still
  animates). The portal player also reports load failures now instead of doing nothing.
  **The cause underneath that was CORS.** A `MediaElementAudioSourceNode` fed
  cross-origin media without CORS approval must emit silence by spec; `/uploads` 307s to
  a presigned bucket URL on a durable-store instance, so **turning the bucket on silenced
  every review player at once** — including files uploaded months earlier. Measured:
  same-origin energy 8564, cross-origin 0, both "playing". The server now stamps
  `wave-live.js?…&offsite=`, and the tap fails closed. Waveform on a bucket instance would
  need CORS on the bucket + `crossorigin="anonymous"`; deliberately not done, since a
  missing CORS rule would fail the media outright.
  **The wave is back on (2026-08-05), on condition.** Each player proves the bytes are
  CORS-readable with a one-byte `Range` GET before it sets `crossorigin` or taps anything,
  and recovers — attribute off, reload, resume, no wave — if the media fails regardless.
  Verified across four bucket configurations; a misconfigured bucket costs the animation
  and never the audio. To light it up on an instance: add a CORS rule to the bucket
  allowing GET/HEAD with the `range` header from the site origin. Nothing to deploy.
- **`app.py` starts coming apart** (ADR-0044, 2026-08-04). It hit **9,133 lines / 251
  routes**. `shell.py` now holds the shared web primitives (the Jinja environment,
  `render`, `public_base`) — created there, still decorated in `app.py` — which is what
  breaks the import cycle that made any extraction impossible. `/agencies` moved first on
  measurement: 26 routes (10%) touching only four `app.py` helpers, versus 23 and 29 for
  `/opportunity` and `/project`, with no route-pattern collision. **app.py: 9,133 → 8,545
  lines; 225 routes remain.** The pattern and its guard-rail tests are in place for the
  next slices; `/opportunity` and `/project` need their shared helpers relocated first. **Slice 2:** the discovery surface (`/signals`, `/discovery`,
  `/sources`, `/leads` — 25 routes, zero helper coupling) → `discovery_routes.py`, and
  `_safe_local` → `shell.safe_local`. **app.py: 8,545 → 8,051 lines, 201 routes left.** **Slice 3:** the supply side
  (`/talent` + `/payouts`, 15 routes) → `talent_routes.py` with the rate helpers.
  **Slice 4:** the **helper layer**, not a route group — the 16 helpers called by more
  than one group, closure of 31 functions, into `uploads.py` / `billing.py` /
  `delivery_ops.py` / `opportunity_ops.py`, with admin-auth to `shell.py`. Every name is
  imported back under its old spelling, so no handler changed. This corrected the claim
  carried in the two previous entries: the blocking helpers were **not** `_load`,
  `_brief_for`, `_outreach_for`, `_quote_band_for` — three of those four are used by only
  one route group and block nothing.
  **Slice 5:** the opportunity surface (`/opportunity`, 58 routes) →
  `opportunity_routes.py`, with the twelve helpers and four constants that only this group
  uses. Proved equivalent by running the previous commit in a git worktree side by side:
  same status on all 58 routes, byte-identical GET responses, same stored rows after the
  same writes. `_quote_band_for` moved into the shared layer — slice 4 had called it
  "/project-only", which was true of its direct route callers and false of the transitive
  closure through `_brief_for`.
  **Slice 6:** the project surface (`/project`, 57 routes) → `project_routes.py` — the
  last of the large groups. Three helpers shared only with `/creator` went into the helper
  layer. Two measurement bugs found and fixed in the closure tooling (local bindings must
  be excluded, or the `/manifest.webmanifest` route moves by accident; `AnnAssign`
  constants must be collected, or `_PRESENCE` raises `NameError` on the first poll), and
  three admin-gate/webhook drift guards that had gone blind to included routers were
  repaired — they were seeing 81 of 274 routes.
  **app.py is now 2,725 lines / 71 routes** — from 9,133 / 251, so 70% of the file and 72%
  of the routes have moved. What remains is the application object itself (middleware,
  lifespan, the admin gate, the PWA endpoints) plus `/creator`, `/campaign`, `/simulator`,
  `/workspace`, `/matchboard`, `/invoice` and the singletons.
  **Slice 7:** the creator portal (`/creator`, 6 routes) → `creator_routes.py` — one
  contiguous block, zero interleaved routes, zero shared helpers, because slices 4 and 6
  had already lifted everything it shared. **app.py is now 2,326 lines / 65 routes** —
  from 9,133 / 251, so 75% of the file and 74% of the routes have moved.
  **Slice 8:** the campaign workspace (`/campaign`, 7 routes) → `campaign_routes.py`, plus
  17 genuinely dead imports removed from `app.py`. **Slice 9:** the objection simulator
  (`/simulator`, 7 routes) → `simulator_routes.py` — no helpers at all, and a new test pins
  the one place declaration order is load-bearing (`/simulator/library` must stay ahead of
  `/simulator/{session_id}`). **Slice 10:** the client workspace (`/workspace`, 5 routes) →
  `workspace_routes.py`, including the award trigger — verified by releasing an identical
  commercial review on both trees and confirming the approval created the same project.
  **Slice 11 (the last):** the remaining 31 routes → `console_routes.py` (19),
  `billing_routes.py` (7), `meetings_routes.py` (5), and the re-export debt paid — `app.py`
  was importing **55 names it does not use**, all so tests could reach them through
  `app_mod`; 104 references across 28 files now point at the owning module.
  **app.py is now 655 lines / 15 routes** — from 9,133 / 251, so 93% of the file and 94% of
  the routes have moved. What is left is only the application object: the admin gate and
  its allowlist, `/healthz`, `HEAD /`, the PWA and Web Push endpoints, the three admin
  doors, and `/uploads/{name}`. Route declarations across the package: 252, unchanged.
  **Closed 2026-08-05:** `_append_version_from_bytes` is deleted. It had no callers since
  the first commit, and `test_naming.py` read its source to assert half the ADR-0037
  naming contract — so that half was pinned on unreachable code. The guard is now
  behavioural (upload through both doors, publish, compare the stems the client receives)
  plus a package-wide check that exactly one function names a version.
  **Also closed 2026-08-05 (slice 11):** the unused-import finding. `app.py` had grown to
  **55 imports it does not use**, every one a re-export kept so a test could reach it
  through `app_mod`; all are gone, 104 test references now point at the owning module, and
  `test_app_py_imports_only_what_it_uses` fails the build if one comes back.
- **The Postgres path is actually tested** (ADR-0045, 2026-08-04). The cutover shim was a
  regex SQL translator that had **never met a Postgres** — `psycopg` wasn't installed.
  Running PostgreSQL 16 against it found three defects that each fail *during* the
  cutover: **`BLOB` isn't a Postgres type** (`media_blob` can't be created — the app
  won't boot), **`COLLATE NOCASE` doesn't exist** (`/agencies` and the roster 500), and
  the **migration script crashed mid-copy** on `media_blob`, which has no `id` column,
  after other tables were already written. All fixed and verified end to end on a real
  server: schema builds, every console route serves, writes work, the migration
  completes with matching counts, and an uploaded master survives byte-for-byte
  (SHA-256). `tests/test_postgres_dialect.py` runs the live path when
  `CHORDENTIAL_TEST_PG` is set — **skipping is not passing**.
- **The front door is the Commission** (2026-08-03): `/` serves `public/commission.html`
  — the live score, the note on a cue, the planning band, the certificate, the packing.
  The World film that landed here (it opened on a brush drawing on paper) and the older
  Experience film were **deleted**, not parked at second addresses — nothing linked to
  either, and each retired homepage left behind was the cause of the dead-link findings.
  The 4K masters are archived in `media/masters/` and the web legs are re-cuttable from
  them. Old `/world` and `/experience` links now 404 by design. Two related fixes shipped with it: `/commission` and
  `/experience` were never in the admin gate's `_PUBLIC_PATHS`, so in production they
  answered `303 → /admin/login` — the Commission had never been publicly viewable — and
  `static/public/vendor/` was missing from the package-data globs, so the vendored
  three.js 404'd in prod and the score layer never rendered there at all. Tests now assert
  public.py's routes against `_PUBLIC_PATHS`, and every shipped file against the
  package-data globs (dev serves the source tree, so no request-based test can catch that).
- **Launch review — Phase 1** (`docs/launch-review.md`, 2026-08-03): ten independent
  reviewers over the whole product; 98 findings, cross-examined against the code. The
  launch-blocking set is fixed: every `/commission` CTA dead-ended at its own closing
  section; sitewide `Work`/`About` pointed at anchors of two retired homepages; marking a
  deal **Won erased its recorded value** (`update_status` now COALESCEs); prod uploads
  landed in the ephemeral package dir (`CHORDENTIAL_UPLOAD_DIR` → `/var/data/uploads` —
  **removing the disk at cutover now deletes client media unless object storage lands
  first**); a duplicate `/webhooks/stripe` handler shadowed the live one; the AI spend
  confirm fired *after* the paid request was dispatched; the portal stamped CLEARED over
  draft terms and read "Delivered" on upload. Also: GZip (nothing was compressed —
  `/commission` 718 KB → 187 KB), AA-passing ember text tokens, `public/home.html`
  deleted. **Phases 2–4 in that document are the standing backlog** — the pricing model's
  four disagreeing voices, the two "waiting on you" aggregators, and the cue sheet's
  rights contradiction are the largest.
- **The company architecture** (`docs/company-architecture.md`, 2026-07-18): the
  20-section first-principles redesign of Chordential as a company (AI-executive org,
  Disposition Queue doctrine, $1M roadmap). Amendments A-1/A-2 remain proposals;
  **A-3 was founder-ratified as a hard block → ADR-0024.**
- **ADR-0024 — the supply-side floor**: `talent.agreement_executed_at`/`agreement_ref`
  (additive), the Agreement block on the talent page, and a server-side refusal on both
  assign paths until agreement + rate are on file. Demo seed models the compliant state.
- **Disposition Queue v1** (`/queue`, `web/queue.py`): every pending founder decision on
  one deterministic, ranked surface (discovery requests → invoices → payouts →
  follow-ups → deal moves → taste-gate submissions → REVIEW-tier opps → reels → floor
  gaps → CI housekeeping). Pure aggregation; zero new decision logic; surfaces the
  funnel audit's hidden REVIEW volume without touching the precision-biased alert tier.
- **ADR-0014 reconstructed** in the ADR log (the captures-envelope ruling was cited by
  0021/0023 but its entry was missing).
- **The Scoring Stage — the composer's Session Room** (spec:
  `docs/design/chordos-studio-experience.md`; ADR-0025/0026). Phases 1–2 built and
  phase-gate reviewed by the standing 4-agent panel (Engineering / Design / Composer /
  Executive Producer). Phase 1: `creator_portal.html` rebuilt as the Session Room —
  one dark room per engagement, one shared playhead, summoned sheets (Brief/Notes/
  Takes on B/N/V, Esc), client feedback threaded with composer-addressed vs
  client-resolved separation, internal Ask-the-studio replies, publish-gated
  deliverables, needs-first room sort + `?p` doors (ADR-0025). Phase 2 (The Picture):
  the client's cut is the stage — client Drop upload with byte progress
  (`delivery_portal.html`), video master clock with audio follower + drift snap,
  timeline pins from timecoded notes (beyond-cut pins badge at the edge), new cut =
  **conform** event (free, per-note `conform · free` species chip, operator species
  toggle, cut ledger in the console), hearable references with rights-honest copy,
  storage per **ADR-0026** (disk + ≤64MB DB mirror, 512MB cut cap, chunked reads),
  stored-XSS serving policy on `/uploads` (inline media allowlist, attachment +
  nosniff otherwise, blocked markup extensions on references). **Phase-2 gate:
  PASSED 4/4** — the standing panel (Engineering / Design / Composer / Executive
  Producer) each independently returned production-ready after two consolidated
  fix rounds. Key round-2 fixes: classifying a change request as a conform now
  *returns* the revision round (was cosmetic); the composer room's round sentence
  reads from the one shared scoped-rounds source; the "to address" counter is
  consistent from first paint; the client portal shows the conform tag; the
  Session Room presence strip and approve/ready states are on-palette. **Carried
  to Phase 3** (round arithmetic): a hard stop / change-order trigger when
  contracted rounds are exhausted, a conform-spam throttle, and a
  conform-vs-revision rollup on the console. **Carried to Phase 4** (flow/mobile):
  AJAX note reply, mobile Companion (§13), tablet touch grammar (§12), and a demo
  project seeded with a real cut + references so picture+pins are demonstrable.
- **The Scoring Stage — Phase 3, The Cue Layer** (ADR-0027). **Gate: PASSED 4/4**
  after one consolidated fix round. Scoring cues + hits live on `delivery_json['cues']`
  (blob pattern). Operator builds the list on the console (`/delivery/cues/*`);
  cue state runs `open → take → published → approved` with **every advance a human
  button press** (single `set_cue_state` call site proves no self-approval). The
  composer gets it read-only: cue regions (state as border weight) + hit diamonds
  on the spine, a readable cue list with direction in the Brief, click-to-seek +
  whisper. **Conform is anchored to the cue that changed** — each timecoded note
  shows the cue it falls under (`cue_for_time`), the banner names the cues the cut
  touches (`cues_touched_by_cut`). Round-2 fixes hardened it: cue mutations serialize
  through `_mutate_cues` (`BEGIN IMMEDIATE`) so concurrent writers can't lose an
  update or misplace an approval; the delete-confirm no longer interpolates a cue
  field into inline JS (stored-XSS lane closed); timecodes cap at 24h; `.mono` is
  defined (cue codes/timecodes were rendering sans-serif); cues beyond the cut get a
  "N beyond this cut" badge. **Carried to Phase 4**: per-cue deadline/assignee, AJAX
  cue editing, CSV/EDL cue import, SMPTE timecode display.
- **The Scoring Stage — Phase 4, Flow polish** (Session Room). **Gate: PASSED 4/4**
  after one consolidated fix round. Shipped: the **Arrival sequence** (once-per-
  engagement house-lights — the dressed room shows through a scrim, spine draws
  left-to-right, Begin; localStorage-gated, reduced-motion-safe); the **⌘K command
  bar** (Raycast-style fuzzy jump to cues/notes/layers/actions/mini); **AJAX
  ask-the-studio reply** (no reload, playhead survives); **mini mode ⌘M** (room →
  380px reference strip; reachable from ⌘K since macOS eats ⌘M); **range/span
  notes** (`review_comments.t_end`; the ⇤ Range control on the portal; a wine span
  bar on the spine; rendered on all three doors; span-aware cue attribution
  `m01–m02`); the **private Capture shelf** (§13 — composer-only, never the client,
  leak-tested, capped at 200); **mobile Companion** (§13 Listen/Know, uploads +
  checklist stripped); **tablet grammar** (§12). A/B take scrubbing already shipped
  (take-chips). The review round caught and fixed a **critical** regression (the
  arrival's spine-draw clobbered the spine's opacity reveal → the whole work
  surface was invisible on every first visit) plus a phantom-reply bug and the
  range-render gap. **Deferred**: precomputed waveform peaks (needs server-side
  audio decode not in this env), a purpose-built 3-screen mobile Companion, and a
  studio-side view of composer captures.

The four-phase Scoring Stage (Session Room) build is complete: audio-and-notes
room → The Picture → The Cue Layer → Flow polish, each phase-gated by the standing
4-agent panel (Engineering / Design / Composer / Executive Producer).

- **The Campaign Intelligence Extraction Engine (ADR-0023)** — extraction into CI is now
  an orchestrated system (`src/chordential_oia/extraction/`): ten parallel domain
  specialists over every artifact → deterministic validation (dedupe / flagged conflicts
  / impossible values) → a bounded recall loop ("what was missed?") → a merge that
  preserves evidence + alternates in `value_json`. Plugs into `campaign_intake`'s
  existing LLM seam; everything still writes through `contribute()` with capture stamps;
  null provider → deterministic heuristics unchanged. Design:
  `docs/architecture/EXTRACTION_ENGINE.md`.
- **Product efficiency audit** (`docs/product-efficiency-audit.md`): 43 verified
  findings, ranked P0–P3.
- **P0:** admin-gate/portal-route drift fixed; event-loop-blocking sends offloaded;
  first-touch dead-end + favicon fixed.
- **P1:** SQL queue selection (was O(table×batch)); live status polling (replaced
  blind reload); review-portal audio playhead persistence.
- **P2:** composer feedback loop (client notes on the creator portal + decision
  emails); **publish gate** on creator uploads (pending until a human publishes);
  outreach draft send/copy/open-in-mail; `/relationships` N+1 elimination.
- **P3 (partial):** hero video `preload=metadata`; single-source CSS cache-buster;
  single-source delivery-doc legal copy.

## In flight / next candidates

- **Campaign Workspace (Creative OS)** — the strategic pivot, now building. Increment
  1 shipped (campaign container + structured creative direction + creative timeline),
  flag **ON in prod** (`CHORDENTIAL_CAMPAIGN_WORKSPACE=1`) for dogfooding.
  ⚠️ **Architectural spine (in progress):** the workspace must *inherit* creative
  direction, not *recreate* it (lineage: `DISCOVERY_INTELLIGENCE_LINEAGE.md`). Progress:
  **✅ Step 1 done** — `agency_id` threads Opportunity→Project→Campaign so Agency/Company
  Intelligence is reachable. **✅ Parent object designed** — **Campaign Intelligence**
  (`CAMPAIGN_INTELLIGENCE.md`): the canonical per-engagement record with a per-field
  provenance model (`{value, sources[], status}`), inherited and contributed-back by every
  module. **✅ Campaign Intake designed** (`campaign-intake-prd.md`) — the *capture
  experience* that creates/enriches CI (user says "what happened"; AI extracts, asks only
  material gaps, produces CI invisibly). Two records: immutable **Captures** (evidence) →
  living **Campaign Intelligence** (synthesis). Vocabulary: *Capture* (user verb) /
  *Campaign Intake* (module) / *Campaign Intelligence* (system object, never shown).
  Two capture stances — **objective** ("what happened") + a first-class **Producer Debrief**
  ("what's your read?"). CI preserves the **epistemic kind** of every field —
  `fact` / `insight` / `recommendation` / `open_question` (+ risk flag) — so inferred
  judgment is never laundered into fact and the producer's read is a preserved asset.
  **✅ CI-1 built** — the living Campaign Intelligence object exists: tables
  (`campaign_intelligence` + `_field` with the epistemic `kind` + `_event` log),
  lazy-created + seeded per campaign from the opportunity (engagement facts), the linked
  agency (buyer facts — the moat, via the Step-1 thread), and the direction cards; the
  provenance panel on the campaign home renders every fact/insight/recommendation/
  open-question with its kind + sources + disposition, and the workspace now writes
  *through* CI (editing a direction contributes a fact — no private copy). Migration-safe
  (verified on an increment-1 DB).
  **✅ Intake-1 built** — the capture pipeline (paste-notes + Producer Debrief →
  extract/classify by kind → write through CI, with gap follow-ups).
  **✅ Opportunity-anchored (ADR-0013)** — Campaign Intake is now a first-class panel on
  the **Opportunity** page (above the Opportunity section + tabs), not gated behind Won.
  CI is born on and keyed by the opportunity; **"Update Intelligence"** ingests multiple
  modalities (notes / transcript / voice memo / RFP / email; audio behind a transcription
  seam); every CI field + the title + buyer name are **inline-editable and human edits are
  authoritative** (machine never clobbers a human-owned field — disagreements surface as
  **conflicts** to resolve); confirmed engagement facts **write back to the opportunity's
  own columns** so qualification/estimate/brief/outreach recompute from one source; and at
  Won the Project/Campaign Workspace **adopt the same CI in place** (nothing recreated).
  **✅ Intake framework (Increment 1, ADR-0014)** — Campaign Intake is now an extensible
  framework of **intake lanes** (`intake_lanes.py`, the single registry: discovery call,
  producer debrief, meeting notes/transcript, RFP, email thread, client brief), none
  privileged. Every lane normalizes to the ONE Capture **envelope** (`captures` gains
  lane/provenance_source/opp_id/metadata/artifact/external/status) and funnels through the
  ONE shared pipeline; every CI field + event now **cites its raw-evidence `capture_id`**
  (answers "why did this change?"). The discovery-call lane is present but honestly disabled
  until its notetaker seam is configured. `review_batch(capture_id)` derives a capture's
  proposed changes (feeds the Increment-2 review surface). Full design:
  `docs/discovery-call-intake-design.md`.
  **✅ Meeting domain (ADR-0015, increments 4-5)** — a **Meeting** is the business object;
  hosting (Zoom/Meet/Teams) and capture (Recall/Zoom AI/Fireflies) are two null-by-default
  seams (`meetings/` package). Everything downstream consumes a Meeting + a normalized
  **Transcript**, never a provider event: provider webhooks normalize into domain MeetingEvents
  in one place, and `campaign_intake.ingest_transcript(meeting, transcript)` is the boundary.
  The `/webhooks/capture/{provider}` receiver (signature-verified, idempotent, offloaded) +
  a gated scheduler fallback drive `Meeting → Transcript → Campaign Intake → CI`. Proven
  end-to-end with a fake Recall webhook (no creds); live Zoom/Recall HTTP is the credential
  flip. The Campaign Brief is the primary client artifact and carries the discovery CTA; the
  opp page shows an "Upcoming Discovery" panel only when a meeting exists.
  **Next (Increment 2):** the batched review surface ("review this call's updates" — the
  diff + confirm-all + projected downstream impact) over every lane; then the document/RFP/
  email parsers (3), and the live Zoom + Google Calendar + Recall credentials flip. Each stays
  flagged, dogfood-first, anti-generic-PM.
- **Platform UI** — realize `platform-website-plan.md` (control-room theme, Why-Today
  queue, Strategy Card gating outreach, `/today` continuity queue, timecoded review as
  the hero).
- **Zero-downtime cutover** — run the SQLite→Postgres ops (code ready, see ADR-0006 /
  `docs/zero-downtime-cutover.md`).

## Known deferred / not-yet-built (do not assume these exist)

- **Scoring Stage — master-review carryover** (`docs/design/scoring-stage-master-review.md`):
  a **round-exhaustion hard stop + conform-spam throttle** (the round ledger displays
  but never *gates* — an unenforced revision budget is a commercial-guardrail gap
  named at the Phase-2 gate and never resolved; do not let it drop again); generalize
  **`_mutate_cues`** into a blob-mutation primitive for all `delivery_json` sub-keys
  (the lost-update race ADR-0027 fixed is still open for `add_capture`, reviewer
  add/remove, asset approval) **and make the lock Postgres-safe** (it no-ops on the
  Postgres cutover); the purpose-built **§13 mobile Companion** (Listen/Capture/Know,
  not a squeezed desktop); real demo **footage** (not SMPTE bars); WRITING-state
  **transport density** (>7 elements) + ⌘K/⌘M **debounce**. Precomputed waveform peaks
  need server-side audio decode (not in the current env).
- **Postgres cutover ops** — code ready **and now verified against a real PostgreSQL 16**
  (ADR-0045: three cutover-day defects found and fixed by running it); ops not run.
  The uploads migration (ADR-0043) gates it — the disk cannot go until the bucket
  has the files. Prod is still SQLite on a
  single-attach disk (every deploy ~2-min blip).
- **DocuSign e-signature** — placeholder only.
- **Durable object storage** — the **seam is wired** (ADR-0043, `CHORDENTIAL_STORAGE=s3`);
  what remains is the ops step: copy the existing files into a bucket and flip the env.
  Media above the 64 MB mirror cap has exactly one copy, on that disk. The Postgres
  cutover runbook removes the disk: **migrate uploads to object storage first or the
  cutover destroys every client cut, master and stem.** Postgres does not cover them.
- **Server-side PDF rendering** of branded docs — best-effort/print-to-PDF only.
- **Scheduler-internals hardening** (from the audit's P3 tail, deliberately left for a
  dedicated pass): auto-fetch/discovery still parses hostile HTML **in-process**
  (unlike enrichment — see ADR-0008); per-agency manual actions bypass the heavy lock;
  lock-busy cycles reset their interval timer; engine stats zero on deploy. All LOW
  severity, most only active under `CHORDENTIAL_AUTONOMOUS=1` (off by default).
- **DBperf micro-opts** (LOW): signal insert is SELECT-then-INSERT; signal "seen" set
  grows unbounded. Flagged as needing a Postgres test target before relying on
  `ON CONFLICT`/`rowcount` semantics (ADR-0006).
- **Phase B/C** — multi-tenant accounts and the buyer-side marketplace are horizon,
  not started.

## Where the real record lives

- **Strategy & philosophy:** `docs/company-strategy.md`, `docs/company-definition.md`,
  `docs/product-roadmap.md`, `docs/cmo-charter.md`.
- **Deliberation archive:** the `*-council.md` files and build plans in `docs/`
  (chronological decision record — not canonical reference).
- **Design direction:** `docs/platform-website-plan.md`,
  `docs/storyboards/chordential-experience-storyboards.html`.
- **Operations:** `docs/delivery-os-user-manual.md`, `docs/zero-downtime-cutover.md`,
  `docs/efficiency-report.md`, `docs/product-efficiency-audit.md`.
