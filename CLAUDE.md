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
  `campaign_`, `simulator_`, `workspace_`, `console_`, `billing_`, `meetings_routes.py`)
  and the helper layer
  (`uploads.py`, `billing.py`, `delivery_ops.py`, `opportunity_ops.py`). **Imports flow one
  way: `app.py` → routes → helpers → `shell.py`.** Never import `app.py` from any of them;
  `tests/test_app_structure.py` fails the build if you do — and it also fails if `app.py`
  imports a name it does not use, because that is how the package ended up reachable
  through `app.py` as a namespace. Reach a helper on the module that owns it. Put new work
  in the module it belongs to, not in `app.py`.
- **Delivery OS** (supply/delivery side): `delivery.py` + the `delivery_*`/`review_*`
  routes + `delivery_console.html`/`delivery_portal.html`/`delivery_package.html`. Five
  "agents": Rights, Revisions, Metadata, Approvals, Assets. See
  `docs/delivery-os-*.md` and `docs/delivery-os-user-manual.md`.

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
  ~70s; add `-n0` for serial debugging). On a small container xdist can stall — run
  in batches of ~7 files with `-n0` instead. **1,539 tests**, must stay green before
  commit.
- Run locally: `uvicorn chordential_oia.web.app:app --reload` (or `--port 8099`).
- Quick import check: `python -c "import chordential_oia.web.app"`.

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
- `CHORDENTIAL_ADMIN_TOKEN` — admin passphrase; unset = gate disabled. Public surfaces
  (front-of-house, `/healthz`, token-gated portals) bypass the gate.
- `CHORDENTIAL_PUBLIC_DOMAIN` (default `https://chordential.com`) — absolute links
  (first-touch page, reviewer links, Stripe redirects).
- **Provider seams (null by default, real when configured):** payments —
  `CHORDENTIAL_PAYMENT_PROVIDER=stripe` + `STRIPE_*`; email — `CHORDENTIAL_MAIL_PROVIDER=smtp`
  + `CHORDENTIAL_SMTP_*` (HOST/FROM required). Both no-op until set.
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
  use a per-reviewer `?r=` token.
- **Column migrations:** add to the `_*_COLUMNS` dict + the `ALTER TABLE` loop in `db.py`
  (`CREATE TABLE` for fresh DBs; the loop migrates existing ones).
- **Provider seams:** `payments/` and `mailer.py` — null default + env-selected real
  impl, best-effort, never raise/block.
- **Deterministic doc builders:** `capabilities.py` / `delivery.py` assemble docs from
  engine data; the client doc + delivery package are editable via overrides.
- **Living OS layer:** every page carries ≥1 living element that can't exist in print
  (`static/live.js` + `lv-*` CSS grammar; see the bible's "Living OS principle").
  Motion communicates state/automation/intelligence only — honest liveness, never
  decoration; thinking states run only while real server work runs.

## Deploy
Render, from `render.yaml` (service `chordential`, `autoDeploy: true` on the dev branch
→ every push deploys; ~2-min blip until the Postgres cutover removes the persistent
disk). PWA + Web Push configured.

## Deferred / known gaps (don't assume these exist)
DocuSign e-signature (placeholder only); durable object storage for uploads (S3/R2 —
currently local disk); the zero-downtime Postgres cutover (code ready, ops not run);
server-side PDF rendering of the branded delivery docs (best-effort only).

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
