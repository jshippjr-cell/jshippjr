# Back-of-House Consolidation — Build Plan

Derived from `docs/dashboard-consolidation-council.md` and the founder's rulings
(2026-06-24). Ordered cheapest-and-highest-value first, so each phase ships something
visible. File references are the current code as mapped during the deliberation.

Stack: FastAPI/Starlette + Jinja templates under `src/chordential_oia/web/`, SQLite
today (Postgres-capable). Tests in `tests/test_web.py`.

---

## Phase 1 — Incoming queue + universal notifications  *(ruling #3, #5 partial)*
**Why first:** highest value, lowest cost; fixes the "warm leads arrive silent" gap.

- **Unified "Incoming" view** over a UNION of `inbound_leads` + `signals` (do **not**
  merge tables). New read-model in `db.py`; new `/incoming` route + template; source
  chips (🌐 Website · 🤖 Crawler · 📡 Signal · ✉ Email). Retire `/leads` and `/signals`
  as separate nav tabs (keep routes as redirects).
- **One badge for all sources.** Generalize `new_signal_count()` (`db.py:1183`) →
  `incoming_unactioned_count()` = inbound `New` + signal `New`. New `/incoming/count`
  endpoint (model on `app.py:713`). Render badge in `base.html` nav; reuse the 60s
  poll JS (`base.html:115-136`).
- **Phone push on every source.** Add a `notify_new_lead()` call after
  `insert_inbound_lead()` in `public.py` (questionnaire + book-a-call) and in
  `discovery.py` `_do_fetch()` — analogous to `notify_new_gig()` (`signals.py:259`).
  Message: "New {source} lead — {company/name}."
- **Promote feedback** (#5): success flash on `/leads/{id}/promote` (`app.py:533-571`);
  guard the null-id path before `link_inbound_to_opp` (`app.py:567`) — show an error
  instead of redirecting to a ghost.

## Phase 2 — Quick-win bug fixes  *(ruling #5 remainder)*
- **Follow-ups empty state** — `dashboard.html:20,32-50`: real "✅ Nothing due today"
  state; when items exist, deep-link the KPI to a filtered list, not the `#followups`
  anchor.
- **"View all" misroute** — `dashboard.html:58`: re-point from `/inbox?action=Pursue`
  to the new Needs-triage module (Phase 4).

## Phase 3 — Website questionnaire gate  *(ruling #6)*
- Add **phone** column to `inbound_leads` (`db.py:161`); show in Incoming + lead views.
- Add phone + LinkedIn fields to `public/start.html`, `book.html` (and `apply.html` as
  fits). Mark email + a "reachable" pair required.
- **Server-side validation** in `public.py` handlers (`:128`, `:162`): require
  `email` AND (`phone` OR `linkedin`); company website optional. Reject with a clear
  error, don't just rely on HTML `required`.
- Add a **honeypot** field + basic anti-spam.

## Phase 4 — Tab consolidation + stage relabel + the two-list home  *(rulings #1, #2, #4)*
- **Stage relabel** (#2): map display labels in the kanban + filters — Pursuing→
  "Reaching out", Submitted→"Proposal out", Lost+Passed→"Closed" (collapse in
  `_KANBAN_STAGES` `app.py:945`; keep Reaching out / Proposal out as separate columns).
  Keep underlying `PIPELINE_STATES` values (`db.py:32`) to avoid a data migration —
  relabel at the view layer; reconcile every deep-link to one vocabulary.
- **Two daily tabs** (#1): "Today" (home) = KPI strip + the two-list stack below;
  "Pipeline" = the kanban (today's `lanes.html`), now the single deal board. Fold the
  old dashboard 3-column grid into the kanban. Demote `/inbox` from nav to a
  "Find a deal" search affordance.
- **Two-list home** (#4): "Needs triage" module (fed by Phase-1 Incoming, inline
  Promote/Dismiss) stacked **above** "Top targets to pursue" (unchanged
  `pursue_targets()` `db.py:2061`, qualified-only). Promotion stays an explicit click.

## Phase 5 — Lead detail: contact-first + guided stepper  *(ruling #7)*
- **Contact to the top** of `detail.html` — pull name/phone/email/LinkedIn (currently
  on the outreach subpage `outreach.html:41`) into the Overview header as `tel:` /
  `mailto:` tap-to-act links.
- **Guided-not-gated stepper** across the top: New → Reaching out → Proposal out → Won,
  with the expected next step as the primary button; keep the freeform status grid
  (`detail.html:85-96`) as the "…or set another stage" escape hatch.
- New **"Delivery doc sent"** milestone (timestamped checkmark, not a buried log line)
  — the hand-off point that fires the Phase-6 doc.

## Phase 6 — Combined personalized client document + Stripe  *(ruling #8)*
- **One staged doc**: capabilities framing (`capabilities_doc.html` — already
  personalized) + the delivery-package outline (port structure from the static
  `public/delivery_sample.html`), auto-filled with the deal's client/need/price.
- **Progressive disclosure** (CMO guardrail): manifest/rights/rollout render only when
  real project data exists; fall back to capabilities framing otherwise.
- **Surface Stripe** "Pay deposit" — Checkout already wired (`app.py:1991-2073`); add
  the button into the doc + the deal flow. No new payment work.
- Wire the doc to the Phase-5 "Delivery doc sent" milestone.

## Phase 7 — Crawler legibility + attribution  *(ruling #10)*
- On `/discovery` (`discovery.html`): show **auto-fetch on/off state** with one-click
  enable; **Fetch feedback** ("last fetched 2h ago · N found", spinner); route fetched
  output into the Phase-1 Incoming queue with the 🤖 chip.
- **Instrument source→won attribution** (leads-fetched → promoted → won, by source) to
  inform whether discovery earns deeper investment. Measure before gold-plating.

## Later phase (not this cycle) — DocuSign  *(ruling #9)*
Net-new: e-sign SDK + server-side PDF engine (WeasyPrint or headless Chromium, since
docs are browser-print today) + envelope creation + a Terms PDF per proposal + a
status webhook + a "Send for signature" action. Sits on top of the Phase-6 doc.

---

### Notes
- Re-label at the **view layer**; keep `PIPELINE_STATES` values stable so no data
  migration is needed and history stays intact.
- Keep `inbound_leads` and `signals` as **separate tables**; unify only the read-model.
- Extend `tests/test_web.py` per phase (new routes, the validation gate, the badge
  count, Promote feedback).
- Independent of the Postgres cutover (`docs/zero-downtime-cutover.md`) — this work
  runs on either backend.
