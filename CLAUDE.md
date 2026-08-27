# CLAUDE.md — Chordential / ChordOS

Guidance for Claude/agents working in this repo. Read this first; it front-loads what
otherwise gets re-discovered every session.

## ⚑ Read the Constitution before making architectural decisions
This repository has a permanent architectural source of truth in
**`docs/architecture/`**. Before any architectural, product, or design decision, read
**[`docs/architecture/CONSTITUTION.md`](docs/architecture/CONSTITUTION.md)** — it
teaches what ChordOS *is* and the principles you inherit. Then skim
**`docs/architecture/PROJECT_STATE.md`** (what's built / deferred right now) and
consult **`docs/architecture/ARCHITECTURE_DECISIONS.md`** before changing a core
pattern. CLAUDE.md (this file) is the *tactical* guide — commands, conventions,
branch discipline; the Constitution is the *why*. When they seem to conflict, the
Constitution wins and this file is corrected.

## What this is
Chordential — a **procurement-grade music studio + the operating system that runs it.**
This software is **ChordOS**, the operating system beneath a creative-service business;
Chordential is its first instance (see the Constitution). The product the market pays
for is the *music service* (clearance-certified original music); the software
(qualification, estimation, the buyer↔creator graph, the Delivery OS) is the internal
moat. Strategy lives in `docs/company-strategy.md`, `docs/product-roadmap.md`, and the
deep research in `docs/market-research.md`; the enduring **why** lives in
`docs/architecture/CONSTITUTION.md`.

## Architecture
- **Python package:** `src/chordential_oia/`. Deterministic "engines" (no LLM/AI
  generation) compose the **mission spine**: Identify → Rank → Qualify → Estimate →
  Prepare → Outreach → Win/Loss. Key modules: `models.py` (`MusicDiscipline`,
  `Opportunity`, …), `qualification.py`, `scoring.py`, `strategic.py`, `estimation.py`,
  `proposals.py`, `outreach.py`, `capabilities.py`, `delivery.py`, `mailer.py`,
  `payments/` (provider seam), `talent.py`, `matching.py`.
- **Web app:** `src/chordential_oia/web/` — FastAPI + Jinja templates (`templates/`).
  **Production runs on managed Postgres** (cut over 2026-08-06, disk removed → deploys are
  zero-downtime); dev and tests are SQLite via stdlib `sqlite3`. One `db.py` serves both —
  a `postgresql://` `CHORDENTIAL_DB` switches it, connections are **pooled** (ADR-0048),
  and `tests/test_postgres_dialect.py` / `test_db_pool.py` verify the Postgres path against
  a real server when `CHORDENTIAL_TEST_PG` is set (they SKIP without it, and skipping is
  not passing). `seed.py` seeds demo data; `public.py` is the public front-of-house site.
- **`app.py` has been taken apart** (ADR-0044) — it was 9,133 lines and 251 routes; it is
  now **655 lines and 15 routes**, and holds only the application object (lifespan,
  middleware, the admin gate, PWA + Web Push, `/uploads`). Below it sit
  `shell.py` (Jinja env, `render`, `safe_local`, admin auth), the route modules
  (`agencies_`, `discovery_`, `talent_`, `opportunity_`, `project_`, `creator_`,
  `campaign_`, `simulator_`, `workspace_`, `console_`, `billing_`, `meetings_routes.py`,
  `auth_routes.py`)
  and the helper layer
  (`uploads.py`, `billing.py`, `delivery_ops.py`, `opportunity_ops.py`). **Imports flow one
  way: `app.py` → routes → helpers → `shell.py`.** Never import `app.py` from any of them;
  `tests/test_app_structure.py` fails the build if you do — and it also fails if `app.py`
  imports a name it does not use, because that is how the package ended up reachable
  through `app.py` as a namespace. Reach a helper on the module that owns it. Put new work
  in the module it belongs to, not in `app.py`.
- **Delivery OS** (supply/delivery side): `delivery.py` + the `delivery_*`/`review_*`
  routes + `delivery_portal.html`/`delivery_console.html`/`delivery_package.html`. Five
  "agents": Rights, Revisions, Metadata, Approvals, Assets. See
  `docs/delivery-os-*.md` and `docs/delivery-os-user-manual.md`.
- **The front door** (`/` and `/score`, one renderer, `public/score.html`): a scroll
  world of 7,419 engraved marks in 728 pieces, drawn by a hand-written WebGL2 renderer
  (`static/public/score-gl.js`, no library). The pieces scatter, reassemble into a cube,
  then fold into a delivery carton whose outline is staff paper and whose lid shuts
  at the end. Each act is MEASURED from the beat it illustrates (`pinActs()`, at boot and on
  resize) rather than written down — a beat covers a different stretch of scroll on a
  phone, so a fixed set of fractions can only be a compromise; they were re-fitted three
  times before this.
  **The model is described once** (ADR-0062) in `scripts/score_scene/recipe.py` and reported to a
  recorder: `scripts/build_score_scene.py` ships `score-scene.{json,bin}` to the browser,
  `scripts/blender_score_cube.py` builds real geometry in Blender for the offline render.
  `score_scene/pack.py` is where the carton lives — including its four lid hinges,
  which are SHIPPED to the renderer rather than deduced there. **The scene files are build
  artifacts** — change the recipe, rebuild, commit the regenerated pair. Never add a
  second copy of the layout; three of them existed once and 20% of the cube hung out of
  its own walls for weeks because of it.

## Governing rules (the product's spine — honor in code + UX)
- **"The machine proposes, Jon disposes."** Engines analyze + recommend; a human presses
  the decision buttons (qualify, assign, approve, release). Never auto-decide.
- **No AI-generated audio.** The system organizes, documents, packages, delivers — the
  music is always human/composer-made. Say so honestly in copy.
- **Honesty rule:** never imply real client work or fake capabilities. Demos use
  invented brands (e.g. AURORA, Vance Athletic), never real trademarks. Defer what can't
  be done well (don't fake it).

## Commands
- Install: `pip install -e ".[web,dev]"` (extras: `web`, `dev`, `gmail`, `ai`, `stripe`,
  `postgres`).
- Test: `python -m pytest tests/ -q` (runs **parallel via pytest-xdist `-n auto`**,
  ~70s; add `-n0` for serial debugging). On a small container xdist can stall — use
  **`scripts/run_tests_batched.sh`** instead (~7 files per batch, `-n0`, ~25 min). It
  prints every `FAILED`/`ERROR` line and exits non-zero; do NOT hand-roll a batch loop
  that summarises with `tail -3`, which is how four red tests reached a commit under a
  "0 failed" report. **1,577 tests**, must stay green before commit.
- Run locally: `uvicorn chordential_oia.web.app:app --reload` (or `--port 8099`).
- Quick import check: `python -c "import chordential_oia.web.app"`.
- Rebuild the front door's world (after any edit to `scripts/score_scene/`):
  `python3 scripts/build_score_scene.py` — regenerates `score-scene.{json,bin}`, reports
  how far anything escapes the cube (must be 0), and commits as part of the change.
  Offline render: `blender --background --python scripts/blender_score_cube.py`
  (`FOLD=24` keyframes the fold into the package and renders that instead).

## Branch & commit discipline
- Develop on the designated feature branch (currently **`claude/admiring-mayer-u241h5`**)
  — do NOT create/switch/rename branches unless asked. Commit directly to it.
- Commit per logical pass; keep the suite green. End commit messages with the
  `Co-Authored-By:` / `Claude-Session:` trailers used throughout the history.
- Only push / open PRs when asked.

## Env flags & config (all `CHORDENTIAL_*`)
- `CHORDENTIAL_DB` — **prod: the managed Postgres URL** (cut over 2026-08-06; the
  `/var/data` disk is gone). A filesystem path still selects SQLite, which is what dev and
  tests use. Pool dials: `CHORDENTIAL_DB_POOL` (kill switch), `_POOL_MIN`/`_POOL_MAX` (1–10).
  Scheduler leader election: `CHORDENTIAL_SCHEDULER_LEASE` (ADR-0046). See
  `docs/zero-downtime-cutover.md`.
- `CHORDENTIAL_SEED_DEMO=1` — seed the demo dataset (off in prod by default → prod shows
  real data only). **Demo campaigns / pipeline only appear with this on.**
- `CHORDENTIAL_ADMIN_TOKEN` — the shared passphrase. **Still works, always** — it is the
  break-glass beside real accounts (ADR-0054), not a legacy path. Unset = gate disabled.
- **Accounts** (ADR-0054): sign in with email + password for a NAMED actor on every
  decision. Bootstrap the first one with `CHORDENTIAL_FIRST_USER` /
  `CHORDENTIAL_FIRST_PASSWORD` / `CHORDENTIAL_FIRST_NAME` — created once at boot as an
  **owner**, never overwritten, and the variables can be removed afterwards. Minimum
  password length is `accounts.MIN_PASSWORD` (9).
- **Roles** (ADR-0055): `owner` / `operator` / `viewer`, enforced in the gate middleware,
  declared in `web/roles.py`. GET needs `viewer`; any other method needs `operator`; the
  irreversible and financial paths need `owner`. **The shared passphrase keeps full
  access** and an instance with no accounts is unaffected.
- `CHORDENTIAL_PUBLIC_DOMAIN` (default `https://chordential.com`) — absolute links
  (first-touch page, reviewer links, Stripe redirects).
- **Provider seams (null by default, real when configured):** payments —
  `CHORDENTIAL_PAYMENT_PROVIDER=stripe` + `STRIPE_SECRET_KEY` + **`STRIPE_WEBHOOK_SECRET`**;
  email — `CHORDENTIAL_MAIL_PROVIDER=smtp`
  + `CHORDENTIAL_SMTP_*` (HOST/FROM required). Both no-op until set. **Payments run live
  on Stripe in prod** — declared in `render.yaml`, keys in the Render dashboard. Two
  client-facing charges ride the seam: the **deposit** from the client's workspace once
  the proposal is countersigned, and the **final** from the delivery portal before the
  download unlocks. Without `STRIPE_WEBHOOK_SECRET`, `/webhooks/stripe` accepts
  **unverified** events — an open "mark this invoice paid" endpoint. Every state is
  announced at boot by `payments_status()` (`[payments] …`), including test-vs-live key,
  the same rule storage and pooling follow. **Signing is the
  exception** (ADR-0059): `CHORDENTIAL_SIGNATURE_PROVIDER` defaults to `inhouse`, which
  is a REAL electronic signature, and an unknown value **raises at boot** rather than
  degrading.
- `CHORDENTIAL_REVIEWER_LINK_DAYS` (default 90; `0` = never) — how long a NEW client
  review link lasts (ADR-0060). Never applied to links that already exist.
- **Call Copilot (Phase 2):** the live panel at `/opportunity/{id}/copilot` needs Recall to
  stream — `CHORDENTIAL_RECALL_WEBHOOK_SECRET` + `CHORDENTIAL_PUBLIC_DOMAIN` on real https,
  and the bot must be armed AFTER both are set. `CHORDENTIAL_CALL_COPILOT=0` stands it down
  (the notetaker is unaffected); `CHORDENTIAL_COPILOT_CALL_CAP` is the per-call spend
  ceiling (default $0.10). The free cue tier works with no API key.
- Others: `CHORDENTIAL_UPLOAD_DIR`, `CHORDENTIAL_ENABLE_SCRAPE`, `CHORDENTIAL_VAPID_*`,
  `CHORDENTIAL_NTFY_TOPIC`, `CHORDENTIAL_DISCOVERY_CALL_URL`.
- **Extraction engine (ADR-0023):** with `ANTHROPIC_API_KEY` set, intake captures run the
  orchestrated 10-worker extraction (`src/chordential_oia/extraction/`) — kill switch
  `CHORDENTIAL_EXTRACTION_ENGINE=0`; dials `CHORDENTIAL_EXTRACTION_MODEL`,
  `CHORDENTIAL_EXTRACTION_RECALL_ROUNDS`, `CHORDENTIAL_EXTRACTION_WORKERS`. No key →
  deterministic heuristics, unchanged.

## Patterns to reuse (don't reinvent)
- **Per-record JSON state blobs:** `opportunities.doc_overrides` and `projects.delivery_json`
  — read/merge-one-key helpers (`get_/update_doc_override`, `get_/update_delivery`).
  Mirror this for new per-record editable state — and merge through
  **`db.merge_json_key`** (ADR-0049), never read-modify-write in Python: one statement,
  so a concurrent merge of a different key cannot erase yours.
- **Token-gated client pages:** `share_token` (opps + projects) + the admin-gate
  exemption (see `_is_first_touch_path` / `_is_delivery_portal_path`). Reviewer links
  use a per-reviewer `?r=` token whose **lifecycle and capabilities live in
  `reviewers.py`** (ADR-0060): expiry, last-used, revoke-don't-delete, and explicit
  sign/approve/delegate. A delegate is always strictly weaker than their inviter, and
  a gate exemption is only ever granted to a route that does its OWN stricter check.
  **Mint every link token with `db.public_token(n)`** (ADR-0066) — letters and digits,
  never `secrets.token_urlsafe`, whose `-`/`_` end ~1 link in 30 in punctuation that mail
  clients trim off. And **never hand `send_email` your own `html`**: it wraps any body
  containing a URL in `branded_html` so the link ships as a real `<a href>` rather than
  bare text a phone has to find the end of. Both rules are tripwired in
  `tests/test_a_link_that_survives_the_inbox.py`.
- **Column migrations:** add to the `_*_COLUMNS` dict + the `ALTER TABLE` loop in `db.py`
  (`CREATE TABLE` for fresh DBs; the loop migrates existing ones).
- **Canonical identity:** a buyer is one **person** (`buyer_person`, keyed by email —
  ADR-0050) and one **organisation** (`buyer_org`, keyed by a normalised name —
  ADR-0056). Surfaces carry `person_id` / `org_id`, stamped by `link_people` /
  `link_orgs` at boot **after** seeding. Reach a company through the org, never by
  string-matching `client` again. Evidence or nothing: no email → no person, no name →
  no org, and the gap is *reported*, not filled with a guess.
- **One derivation, many reporters:** the relationship stage lives only in
  `buyer_intel` (ADR-0057), as the queue count lives only in `queue.compute_queue`
  (ADR-0029) and the price only in `web.estimate.estimate_for` (ADR-0033). If two pages
  answer the same question, one of them is wrong on a day nobody is looking.
- **The pricing model has a page** — `/pricing` (nav → Intelligence). Every other pricing
  surface hangs off one opportunity, which prices a job but cannot teach the model. It READS
  the factor tables, margins, cap and rates out of `pricing.py`/`estimation.py` and prices a
  worked example through the real `build_quote`; it must never restate a number, or it
  becomes a second authority that goes stale in silence.
- **One quote authority, wired to the work** (ADR-0034 + ADR-0065): `capabilities.quote_for`
  returns the whole `Quote` (itemisation, floor, verdict); `quote_band` is its tuple view.
  Every buyer-facing surface renders it and **never adjusts it** — `public_price_band` used
  to re-convert it at margin and double-marked-up the moment it stopped being a cost band.
  Build the estimate behind it with **`opportunity_ops._estimate_for_row`**, which resolves
  the deal's project so assigned rates are in play; two conventions for that is how the
  Review and the proposal came to disagree on the deposit.
- **Two fees, and the budget is only a check** (ADR-0065): `pricing.py` prices a
  **creative fee** (cost at target margin — `estimation`, not second-guessed) plus a
  **licence fee** (media × territory × term × exclusivity, capped). What the client said
  their budget is NEVER sets the price; it returns a verdict (below floor / in band /
  above band). The factor tables are **priors ratified against
  `docs/market-pricing-research.md`** — read that before touching one. Note
  `estimation.suggested_price` folds usage into the creative number and therefore now
  disagrees; `build_quote` ignores it deliberately.
- **The summary IS the proposal, and it is signed** (ADR-0065): after a call, the client's
  Discovery Summary carries scope/fee/terms and an Agreement block.
  `agreement.signable_text()` is ONE deterministic text that is both what the client reads
  and what the SHA-256 covers — never hash rendered HTML, and never put acceptance copy in
  a template, because it is part of the signed document. A drawn signature (finger/mouse)
  is optional, validated by `signing.clean_drawn_mark` or dropped, and excluded from the
  digest. A signature hangs off an opportunity OR a project, never both.
- **Closing by signature takes the same road as closing by review** (ADR-0067):
  countersigning writes the project's `proposals` row via
  `opportunity_ops._ensure_proposal_for_project` — from the SIGNED band, never a fresh
  quote — and `_workspace_signals` reports `commercial_approved`, so the deal reaches
  KICKOFF, which is the only surface that asks the client for anything. Kickoff asks for
  the picture as well as the deposit (never gated on it), and a client action that can be
  taken carries the link that takes it. A second way to close a deal is not done when the
  signature is stored: walk the client's path after it.
- **One room, capability-gated** (ADR-0068): `/room/<project_id>` serves creator, client
  and studio from ONE template. `creator_routes._room_fields` builds the engagement once;
  `room.room_view` **subtracts** what the role may not see, so the client's copy is made
  by never putting the pending take in it — never by a template `{% if %}`. `room.CAPS`
  is the authority and an unknown role gets nothing. A gate-exempt route must make its
  own stricter check: `_session_role` reads "no token" as *operator*.
- **After the countersignature the client lives in the room** (ADR-0093): once a project
  exists, `/workspace/{token}` **303s to `/room/{pid}?k=…`** and the kickoff gate (deposit
  + "send us your cut") renders there via `kickoff.client_gate`. Mint every post-award
  client link with **`room.client_url(conn, db, opp_id, base=…, flag=…)`** — a hand-written
  `/workspace/…?paid=1` loses its query to the redirect, so the receipt banner vanishes.
  The workspace survives **only before the countersignature**, because a room is a project
  and the Commercial Review is what creates one.
- **A note is not work until it is priced** (ADR-0069): every client note is classified
  `conform` / `revision` / `out_of_scope` before a creator sees it — `room.priced_notes_only`
  is the ONE rule, read by the room and the composer's portal. A change request arrives
  pre-priced as a revision. A new cut is **parked** (`conform_pending`) until the studio
  states the offset and every note moves with the picture. A cut carries its own `fps` +
  `tc_start`; with none declared the room says *seconds from head* rather than inventing
  frames.
- **Scope carries its own evidence:** `estimation.Scope` / `estimation.Session`
  (ADR-0058) each pair a value with whether the brief STATED it. Anything assumed is
  named on the surface that shows the number. Mirror this for any inferred input a
  client-facing figure rests on — a guess presented as a fact is the honesty rule
  broken, not a rounding error.
- **Provider seams:** `payments/` and `mailer.py` — null default + env-selected real
  impl, best-effort, never raise/block. **`signing_providers/` is the exception that
  proves the rule:** its default is a REAL in-house signature, not a null object, and an
  unknown provider name **raises at boot** rather than degrading — silently signing
  documents ourselves under a config that asked for a third-party witness is the one
  direction a signature must never fail.
- **Bind a signature to its document:** `signing.py` (ADR-0059) stores a SHA-256 of the
  exact text signed and reports `SUPERSEDED` when it stops matching. Signature rows are
  append-only; withdrawal marks, never deletes.
- **Two standing agreements, one router** (ADR-0082): `composer_agreement.py` for people
  who AUTHOR music, `service_agreement.py` for people paid for craft on music somebody
  else wrote (mixer, editor, sound designer, supervisor) — no publishing, a fee per
  engagement, a grant of only what they themselves make. **Which one governs is
  `agreements.kind_for` and nowhere else**, read from the creator's disciplines; no craft
  recorded means NEITHER document, never the writer's by default. Every "has this person
  signed?" reader goes through `agreements`; a test fails the build if one pins itself to
  `DOC_COMPOSER_AGREEMENT` again. Terms shared by both agreements are **imported** from
  `composer_agreement`, never restated.
- **Deterministic doc builders:** `capabilities.py` / `delivery.py` assemble docs from
  engine data; the client doc + delivery package are editable via overrides.
- **One recipe, several recorders** (ADR-0062): where the front door's world goes is
  decided in `score_scene/recipe.py` and nowhere else; a surface that needs it
  implements `piece()/box()/glyph()` and receives it. This is the "one derivation, many
  reporters" rule applied to a picture — and the picture is where it had already been
  broken, three times over.
- **Living OS layer:** every page carries ≥1 living element that can't exist in print
  (`static/live.js` + `lv-*` CSS grammar; see the bible's "Living OS principle").
  Motion communicates state/automation/intelligence only — honest liveness, never
  decoration; thinking states run only while real server work runs.

## Deploy
Render, from `render.yaml` (service `chordential`, `autoDeploy: true` on the dev branch
→ every push deploys; ~2-min blip until the Postgres cutover removes the persistent
disk). PWA + Web Push configured.

## Where uploaded bytes live (ADR-0043 + ADR-0084)
`uploads._persist_upload` is the ONE write door and `uploads.forget_media` the one way
out. With no bucket configured, **the DATABASE is the durable store**: every upload is
mirrored into `media_blob` and `serve_upload` rehydrates from it when the container's
disk comes back empty (Render replaces it on every deploy). The ceiling is
**`uploads.mirror_cap(conn)`** — 512 MB on Postgres, matching the largest file the doors
accept, because *whatever we accept we must be willing to keep*; still 64 MB on SQLite,
where ADR-0026's reasoning holds. Dial with `CHORDENTIAL_MIRROR_MB` (`0` disables it).
Never hardcode the ceiling at a call site — five routes used to, which is how it went
un-reviewed through the Postgres cutover and quietly ate every file over 64 MB. Ask
`media_present` / `media_durable`; both MEASURE, and a stamped flag would go stale.

## Deferred / known gaps (don't assume these exist)
DocuSign e-signature (placeholder only); durable object storage for uploads (S3/R2 — the
seam is built and tested, `CHORDENTIAL_STORAGE=s3`, but not switched on; **deferred, not
urgent** since ADR-0084 — still the better answer for egress and for files >512 MB);
server-side PDF rendering of the branded delivery docs (best-effort only).
**`/pay/return` is an unauthenticated GET that marks an invoice Paid** with no
verification against Stripe — known, live, unfixed.

## Docs index
- **`docs/architecture/`** — the **canonical source of truth** (read first):
  `CONSTITUTION.md` (what ChordOS is + enduring principles), `ARCHITECTURE_DECISIONS.md`
  (binding technical decisions + rationale), `PROJECT_STATE.md` (what's built/deferred
  now). Start at `docs/architecture/README.md`.
- **`docs/` (the rest)** holds the decision/plan **archive**: `company-strategy.md`,
  `product-roadmap.md`, `market-research.md`, the `*-council.md` deliberations, the
  `delivery-os-*` plans + reviews + user manual, `efficiency-report.md`, and
  `product-efficiency-audit.md`. Reconcile re-sequencing into `product-roadmap.md`.

Layering: Constitution (why, changes rarely) → ADRs (decisions) → PROJECT_STATE (state,
changes often) → this file (tactics) → `docs/` archive (history). Higher, slower layers
win conflicts.
