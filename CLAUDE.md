# CLAUDE.md — Chordential

Guidance for Claude/agents working in this repo. Read this first; it front-loads what
otherwise gets re-discovered every session.

> **Architectural constitution:** `CHORDENTIAL_SYSTEM_ARCHITECTURE.md` (root) is the
> authoritative architecture + governance doc, and `AGENTS.md` (root) is the live agent
> manifest. Read both before non-trivial work; honor them; amend via ADR, never silently.
> New agents go in `AGENTS.md` (Planned) **before** they're built (manifest-first).

## What this is
Chordential — a **procurement-grade music studio + the operating system that runs it.**
The product the market pays for is the *music service* (clearance-certified original
music); the software (qualification, estimation, the buyer↔creator graph, the Delivery
OS) is the internal moat. Strategy lives in `docs/company-strategy.md`,
`docs/product-roadmap.md`, and the deep research in `docs/market-research.md`.

## Architecture
- **Python package:** `src/chordential_oia/`. Deterministic "engines" (no LLM/AI
  generation) compose the **mission spine**: Identify → Rank → Qualify → Estimate →
  Prepare → Outreach → Win/Loss. Key modules: `models.py` (`MusicDiscipline`,
  `Opportunity`, …), `qualification.py`, `scoring.py`, `strategic.py`, `estimation.py`,
  `proposals.py`, `outreach.py`, `capabilities.py`, `delivery.py`, `mailer.py`,
  `payments/` (provider seam), `talent.py`, `matching.py`.
- **Web app:** `src/chordential_oia/web/` — FastAPI + Jinja templates (`templates/`),
  SQLite via stdlib `sqlite3` (`db.py`). `app.py` is the route layer; `seed.py` seeds
  demo data; `public.py` is the public front-of-house site.
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
  ~70s; add `-n0` for serial debugging). 515 tests, must stay green before commit.
- Run locally: `uvicorn chordential_oia.web.app:app --reload` (or `--port 8099`).
- Quick import check: `python -c "import chordential_oia.web.app"`.

## Branch & commit discipline
- Develop on the designated feature branch (currently **`claude/admiring-mayer-u241h5`**)
  — do NOT create/switch/rename branches unless asked. Commit directly to it.
- Commit per logical pass; keep the suite green. End commit messages with the
  `Co-Authored-By:` / `Claude-Session:` trailers used throughout the history.
- Only push / open PRs when asked.

## Env flags & config (all `CHORDENTIAL_*`)
- `CHORDENTIAL_DB` — SQLite path (prod: `/var/data/chordential.db`; the DB layer is also
  Postgres-capable — a `postgresql://` URL switches it; see `docs/zero-downtime-cutover.md`).
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

## Patterns to reuse (don't reinvent)
- **Per-record JSON state blobs:** `opportunities.doc_overrides` and `projects.delivery_json`
  — read/merge-one-key helpers (`get_/update_doc_override`, `get_/update_delivery`).
  Mirror this for new per-record editable state.
- **Token-gated client pages:** `share_token` (opps + projects) + the admin-gate
  exemption (see `_is_first_touch_path` / `_is_delivery_portal_path`). Reviewer links
  use a per-reviewer `?r=` token.
- **Column migrations:** add to the `_*_COLUMNS` dict + the `ALTER TABLE` loop in `db.py`
  (`CREATE TABLE` for fresh DBs; the loop migrates existing ones).
- **Provider seams:** `payments/` and `mailer.py` — null default + env-selected real
  impl, best-effort, never raise/block.
- **Deterministic doc builders:** `capabilities.py` / `delivery.py` assemble docs from
  engine data; the client doc + delivery package are editable via overrides.

## Deploy
Render, from `render.yaml` (service `chordential`, `autoDeploy: true` on the dev branch
→ every push deploys; ~2-min blip until the Postgres cutover removes the persistent
disk). PWA + Web Push configured.

## Deferred / known gaps (don't assume these exist)
DocuSign e-signature (placeholder only); durable object storage for uploads (S3/R2 —
currently local disk); the zero-downtime Postgres cutover (code ready, ops not run);
server-side PDF rendering of the branded delivery docs (best-effort only).

## Docs index
`docs/` holds the decision/plan record: `company-strategy.md`, `product-roadmap.md`,
`market-research.md`, the `*-council.md` deliberations, the `delivery-os-*` plans +
reviews + user manual, and `efficiency-report.md`. Reconcile re-sequencing into
`product-roadmap.md`.
