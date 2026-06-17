# Chordential — Hourly Build-Council Charter

*Established 2026-06-16 from Jon's onboarding interview. Each hourly cycle reads
this file for its operating parameters.*

## Mandate (from the CEO interview)

| Dimension | Decision |
|---|---|
| **North star** | **Expand the vision** — build toward the procurement OS (estimation, prepare/proposals, outreach, buyer graph). |
| **Autonomy** | **Approve-then-build** — the council presents the agreed plan/requirements for Jon's OK *before* the engineer builds. (Reconciled with the repo's stop-hook policy, which requires every commit to be pushed: pausing *after* a build would leave uncommitted work the hook rejects, so the pause moves to the plan stage. Once approved, the engineer builds → QA → commit → push.) |
| **Scope** | **Intelligence engine** — sources, qualification, estimation, the data moat. |
| **QA bar** | **Tests + screenshot + acceptance** — full suite green, a rendered screenshot of any affected screen, and a written check against the cycle's agreed requirements. |

## The council
CEO (Jon) · COO · CTO · CMO · Creative Director → agree the next build →
hand requirements to the Engineer → Engineer builds → QA agent verifies →
**pause for Jon's approval** → publish on OK.

## Per-cycle process
0. **Name the roadmap stage** — every cycle states which stage of
   `docs/product-roadmap.md` it advances. A build that maps to no stage is out of
   scope (or the roadmap is updated first). The roadmap is the decision anchor;
   the CMO gate (`cmo-charter.md`) and a named roadmap stage are checked together.
1. **Council dialogue** (short) — agree the single highest-value next build within scope.
2. **Requirements + plan** — written acceptance criteria.
3. **Pause for approval** — present the plan to Jon. **Wait for his OK before building.**
4. **Build** — implement on branch `claude/admiring-mayer-u241h5`.
5. **QA** — run `pytest`; render a screenshot of any affected screen; check each acceptance criterion.
6. **Publish** — commit + push (satisfies the stop-hook policy).
7. **Log** — append the cycle outcome below.

## Cycle log

### Cycle 1 — 2026-06-16 ~14:25 UTC — Promote Estimation to a first-class engine
- **Build:** new `src/chordential_oia/estimation.py` (Phase-1 expert engine + `EstimationEngine`), added an uncalibrated **confidence band** (±35%) to every estimate, collapsed `web/estimate.py` into a thin shim, exported from the package, surfaced the band on the dashboard estimate page.
- **Acceptance:** engine returns point + band; team derived from discipline; web delegates to engine (no duplicate logic); existing numbers unchanged; all tests green.
- **Status:** ✅ published (commit `781076e`).

### Cycle 2 — 2026-06-16 ~15:05 UTC — The Prepare layer (Pursuit Brief)
- **Build:** new `src/chordential_oia/prepare.py` — deterministic `PursuitBrief` generator (the fifth mission verb) assembling qualification + estimate + strategic value into a ready brief with a suggested response outline; new dashboard "Pursuit brief" tab + plain-text/copy export; exported from the package.
- **Acceptance:** brief assembles from existing engines (no LLM); `render_text()` copy-paste output; new tab + `.txt` route render; full suite green.
- **QA:** 79 tests pass; brief + brief.txt routes 200; screenshot verified; 3/3 acceptance.
- **Status:** ✅ published.

### Cycle 3 — 2026-06-16 — Product Roadmap + the Outreach-to-Win layer
- **Roadmap stage:** Demand side → **Outreach-to-win** (the sixth mission verb). Also establishes `docs/product-roadmap.md` as the exec decision anchor.
- **Build:** (A) new `docs/product-roadmap.md` — the two-track (demand/supply) roadmap with status per stage and the talent-matching decision (profile + credits + Jon-reviewed demo reel, no audio AI); governance rule added (every cycle names a roadmap stage). (B) new `src/chordential_oia/outreach.py` — deterministic `OutreachPlan` (recommended contact, urgency, buyer-tuned cadence, first-touch message); persistence for contact + next-action/due + an outreach event log with a non-destructive DB migration; new "Outreach" tab + `.txt` export; dashboard "Follow-ups due" queue.
- **Acceptance:** plan assembles from existing engines (no LLM); contact + next action persist; events log and stamp last-contacted; follow-ups surface on the dashboard; old databases migrate without data loss; full suite green.
- **QA:** 91 tests pass; outreach + outreach.txt routes 200; screenshots of the Outreach tab and the dashboard follow-up queue verified; migration test green.
- **Status:** ✅ published.

### Cycle 4 — 2026-06-16 — Buyer Graph (buyer relationship intelligence)
- **Roadmap stage:** Demand side → **Buyer Graph** (the moat asset; built on the Outreach layer's contacts + touch log).
- **Council:** CMO + Creative Director + COO argued the relationship — not the single pursuit — is the moat and must be browsable with a next-best-action; CTO scoped it to deterministic aggregation over existing data (no new infra/LLM); CEO approved.
- **Build:** new `web/buyer_intel.py` — deterministic `BuyerRelationship` (stage Cold/Warming/Engaged/Client, 0-100 score, signals, next-best-action); `db.py` aggregations (`all_buyers`, `buyer_touch_summary`, `buyer_contacts`); new `/buyers` directory ranked by relationship then strategic value + "Buyer Graph" nav; buyer profile relationship panel + known-contacts list.
- **Acceptance:** deterministic engine with correct stage rules; directory + profile render and rank; relationship reflects outreach + wins; built only from existing data; full suite green.
- **QA (independent QA agent):** 101 tests pass; engine stage/boundary/determinism checks pass; `/buyers` + buyer profile 200 with expected content; end-to-end (contact → touch → Won ⇒ "Client") verified; clean working tree. 5/5 acceptance, no defects. Screenshots of the directory + profile verified.
- **Status:** ✅ published.

### Cycle 5 — 2026-06-16 — Talent Roster (supply-side foundation)
- **Roadmap stage:** Supply side → **Recruit talent** (the first supply-side stage; everything downstream needs a person model).
- **Council:** CEO reaffirmed match-on-profile-and-credits + a Jon-reviewed demo reel (no audio AI); Creative Director owns the reel gate; CMO defined the Prospect→Invited→Joined funnel; CTO reused `MusicDiscipline` for talent skills and kept it to a new table + migration, reel as a link (no file-hosting infra).
- **Build:** new `talent.py` (Talent model, ReviewStatus/InviteStatus, profile_completeness, matchable rule); `db.py` talent table + CRUD (migration-safe); `seed.py` starter roster; `/talent` roster + filters, add/edit, demo-reel review action, invite funnel; new Supply nav section.
- **Acceptance:** matchable = approved reel + ≥1 discipline; roster/detail render; review + invite persist; seeded roster present; migration-safe; full suite green.
- **QA (independent QA agent):** 112 tests pass; domain rules (matchable cases, completeness) verified; `/talent` + `/talent/new` 200 with seeded creator; review gate end-to-end (Pending⇒not matchable, Approve⇒Matchable) verified; migration idempotent; clean tree. 5/5 acceptance, no defects. Screenshots verified.
- **Status:** ✅ published.

### Cycle 6 — 2026-06-16 — Talent Matcher (demand ↔ supply)
- **Roadmap stage:** Supply side → **Talent match**. Applies the CEO directive (recorded same day): the app does the matching/ranking and explains it, but **does not assign** — assignment is Jon's confirm-button in Cycles 7/8.
- **Council:** Creative Director wanted craft-first ranking with visible reasoning; CTO kept it deterministic (discipline fit + credits keyword-overlap + completeness), matchable-only, no LLM; CMO put it on the opportunity as a "Talent match" tab.
- **Build:** new `matching.py` (`match_talent` → ranked `TalentMatch` with reasons; excludes no-craft-fit and unapproved creators); `db.load_talent`; `/opportunity/{id}/match` tab across the opportunity subnav with the "you make the final call" frame.
- **Acceptance:** matchable-only; primary discipline outranks secondary; credits overlap raises + explains score; deterministic; route renders ranked candidates; no assignment path.
- **QA (independent QA agent):** 119 tests pass; gate (Pending excluded, Approve includes) verified over HTTP; primary>secondary and credits-overlap verified numerically; deterministic ordering; clean tree. All acceptance, no defects. Screenshot verified.
- **Status:** ✅ published.

### Cycle 7 — 2026-06-16 — Projects + Assignment (Jon's decision surface)
- **Roadmap stage:** Supply side → **Identify required labor + Assign**. Implements the CEO directive (recorded this session): the app scopes roles + ranks creators and lays out both sides; **Jon assigns via an explicit action — nothing auto-assigns.**
- **Council:** COO wanted a won opp to carry the estimator's roles into a project; Creative Director wanted both-sides context on the page; CTO used projects + assignments tables and reused the Cycle 6 matcher; assign/unassign are explicit POSTs.
- **Build:** `db.py` projects + assignments tables (migration-safe) + CRUD; `/projects` directory; POST `/opportunity/{id}/project` (spin up from Won, deduped); `/project/{id}` decision page (roles, per-role Assign from ranked matches, recommended-creators panel); explicit assign/unassign/status; "Spin up project" button on Won opps; Projects nav.
- **Acceptance:** project from Won opp (no dup); per-role assign/unassign explicit; ranked candidates shown; project status toggle; migration-safe.
- **QA (independent QA agent):** 123 tests pass; **no-auto-assign directive verified behaviorally AND by code path** (`add_assignment` called only from the assign handler); assign/unassign end-to-end; dedup; migration; clean tree. 16/16 checks, no defects. Screenshot verified.
- **Status:** ✅ published.

### Cycle 8 — 2026-06-16 — Delivery progress (milestone tracking)
- **Roadmap stage:** Supply side → **Track progress**. Estimation Director noted this is the source of Phase-3 estimation actuals.
- **Build:** `milestones` table (migration-safe) + CRUD + `milestone_progress`; default deliverable milestone per role auto-seeded on project creation; advanceable Pending→In progress→Done with a progress bar; done/total surfaced on the project and the projects directory.
- **Acceptance:** default milestones from roles; status advances progress; invalid status rejected; add/delete; directory progress; migration-safe.
- **QA (independent QA agent):** 126 tests pass; default seeding {total:3,done:0}; Done raises done/pct; invalid status raises ValueError; add/delete; directory readout; migration; clean tree. 6/6 acceptance, no defects. Screenshot verified.
- **Status:** ✅ published.

### Cycle 9 — 2026-06-16 — Project broadcast feed (completes the supply side)
- **Roadmap stage:** Supply side → **Broadcast progress to everyone assigned** (final supply-side stage).
- **Build:** `project_updates` table (migration-safe) + feed helpers + `project_crew` (recipients); assign/unassign and milestone-status routes auto-append feed entries; manual broadcast post; "Activity & broadcast" card with recipient list, post box, and a color-coded newest-first feed.
- **Acceptance:** auto-broadcast on assign + milestone move; crew recipient list; manual post; empty post no-op; newest-first; migration-safe.
- **QA (independent QA agent):** 129 tests pass; auto-broadcast on assign + milestone verified; crew line; manual post + empty/whitespace no-op; newest-first (id DESC tiebreak); migration; clean tree. All acceptance, no defects. Applied QA's polish note (empty body now redirects gracefully instead of 422). Screenshot verified.
- **Status:** ✅ published.

### Cycle 10 — 2026-06-16 — Executive Summary → pipeline view (demand-side reorg)
- **Roadmap stage:** Demand side → decision-surface reorganization. Driven by a CEO interview on the demand-side information hierarchy: at a glance Jon wants winnability + angle, the money, and deep-dive links; the dashboard is the workhorse. He then directed the Exec Summary specifically to read as his pipeline.
- **Build:** replaced the six stat cells **and** the pipeline-mix chart with a three-column pipeline — **🎯 Top targets to pursue** (qualified, not-yet-bid, ranked by tier→fit, each with a suggested price + budget + Original-posting/Contact links), **📨 Tentative** (`Submitted` bids out for decision, value + due), **🏆 Won** (closed deals with the **assigned talent/crew** pulled from the linked project). New `db` helpers `pursue_targets`/`tentative_bids`/`won_deals`; dashboard route computes per-row suggested price via the standard engines; `seed_demo_pipeline` stages one bid + one win (with assigned crew) so the columns show live data, idempotently. Kept Strategic spotlight, Follow-ups due, Needs review.
- **Acceptance:** three sections render from the correct statuses; Won lists crew (or an assign/spin-up prompt); stat grid + mix chart gone with no dead vars; empty states read cleanly; suite green.
- **QA:** 130 tests pass (2 new dashboard tests); rendered HTML verified for all three columns, crew chips (Devin Park · Maya Okafor on the demo win), price figures, deep-dive links, and removal of the old cells/chart. **Pixel screenshot not captured — the sandbox network policy blocks the Playwright browser download;** structural HTML + test verification stood in.
- **Deferred to next cycle:** the editable **Company website** field (new column + edit UI) and the Opportunity-Overview action bar.
- **Status:** ✅ built; QA green (screenshot caveat above).

### Cycle 11 — 2026-06-16 — Deferred demand-side polish: Company website + Overview action bar
- **Roadmap stage:** Demand side → decision-surface polish (clears the two items the Cycle 10 log explicitly deferred).
- **Build:** (A) **Company website** — a new `companies` table (migration-safe; buyers are still aggregated by client name, this holds the few attributes that belong to the company itself) with `get_company`/`company_website`/`set_company_website` (upsert, URL-normalized: a bare host gains an `https://` scheme). Editable inline on the Buyer profile header; rendered as a compact scheme-stripped link via a new `displayurl` filter. (B) **Opportunity-Overview action bar** — a quick-action row under the subnav: one-click pipeline advance (New→Pursuing→Submitted; **Won is intentionally omitted so closing still routes through the win/loss form that captures the value**) plus jump buttons to Pursuit brief / Plan outreach / Talent match, Open project (when one exists), and the original posting.
- **Acceptance:** website persists + normalizes + displays compactly; edit repopulates; action bar shows the correct next-status (or none past Submitted) and the jump links; migration-safe; suite green.
- **QA:** 133 tests pass (3 new — action bar present, advance moves New→Pursuing→Submitted, website persists/normalizes/displays). Rendered HTML verified for both surfaces (advance button + links; normalized `https://acme-music.com` link with compact display). **Pixel screenshot not captured — the sandbox network policy still blocks the Playwright browser download;** structural HTML + tests stood in (same caveat as Cycle 10).
- **Roadmap note:** marked **Invite to the app** as the single partial supply stage — funnel states exist, but real multi-user accounts/login/email for creators is the bigger build that bridges to Model C, deferred until the demand-side moat justifies a second user surface.
- **Status:** ✅ built; QA green (screenshot caveat above).

### Cycle 12 — 2026-06-16 — Outreach page: one-click email + LinkedIn links
- **Roadmap stage:** Demand side → **Outreach-to-win** (enhancement — turn the drafted plan into action without copy-paste).
- **Build:** the Outreach page now surfaces two clickable reach-out actions on the contact card. **✉ Compose email** is a `mailto:` to the saved contact that opens the user's mail client with a prefilled draft — a concrete subject (`{need} — Chordential`, new `OutreachPlan.email_subject`) and the existing deterministic first-touch pitch as the body (both URL-encoded). It works even before an email is captured (empty recipient, template still prefilled). **in LinkedIn profile ↗** opens the contact's profile in a new tab, shown only when a LinkedIn URL is saved. New persisted field `contact_linkedin` (migration-safe column added to `_OUTREACH_COLUMNS`), normalized to a working `https://` URL via the existing `_normalize_url`; added to the contact form and threaded through `update_outreach` + the `/outreach` POST.
- **Acceptance:** email link is a mailto to the contact carrying subject + body; works with no saved email; LinkedIn link present only when set and normalized; field persists; migration-safe; suite green.
- **QA:** 136 tests pass (3 new — mailto with subject+body, mailto with empty recipient, normalized LinkedIn link; plus a unit test for `email_subject`). Rendered href verified well-formed (`mailto:dana@acme.com?subject=…&body=Hi…`, `https://linkedin.com/in/danareyes`). Screenshot caveat unchanged (sandbox blocks the Playwright download); structural HTML + tests stood in.
- **Status:** ✅ built; QA green (screenshot caveat above).

### Cycle 13 — 2026-06-16 — Auto-researched LinkedIn lead + brand logo
- **Roadmap stage:** Demand side → **Outreach-to-win** (lead enrichment) + brand polish.
- **Build:** (A) **Auto-researched decision-maker LinkedIn** — the outreach page no longer needs the LinkedIn field filled by hand. `OutreachPlan.linkedin_search_url` deterministically builds a LinkedIn **people-search deep-link** from the RFP's own facts (the scoring engine's inferred decision-maker role + the buyer name, with the `Likely` qualifier and any parenthetical buyer-type suffix stripped). The page pre-populates the LinkedIn field and the **Find on LinkedIn ↗** button with it; pasting a verified profile overrides the suggestion (then the button reads **LinkedIn profile**). **Honest scope:** without an external data provider (Apollo/Clearbit/LinkedIn API + network egress) the app can't fetch a *specific* private profile, so it points one click at the exact person to find rather than fabricating profile/email data — the field is the seam where a real enrichment provider drops in later. (B) **Brand logo** — new `static/logo.svg` (the wordmark's signature mark: the chord "o" as a vertical infinity — an orange ring over its faded reflection) replaces the `◆` glyph next to "Chordential" in the sidebar; `.brand-mark` reworked to a cream tile housing the mark.
- **Acceptance:** LinkedIn link auto-built from inferred role + buyer, terms cleaned; field/button pre-filled when none saved; saved profile overrides; logo renders in the sidebar and is served; suite green.
- **QA:** 139 tests pass (3 new web + 1 unit). Rendered URL verified (`…/search/results/people/?keywords=Executive+Producer+%2F+Music+Supervisor+Brightline+Films`); `logo.svg` serves 200 and is referenced on every page. Screenshot caveat unchanged (sandbox blocks the Playwright download); structural HTML + tests stood in.
- **Status:** ✅ built; QA green (screenshot caveat above).

### Cycle 14 — 2026-06-16 — Decision-surface UX reorg (council review P1–P3)
- **Roadmap stage:** Cross-cutting decision-surface ergonomics — acts on the council's page-by-page UX review of the six primary screens. No new schema (every signal already existed); all changes are templates/CSS/routes, fully reversible.
- **Build (by page):**
  - **Dashboard:** one-line **KPI strip** (in-flight count+value · win-rate · won lifetime · follow-ups-due, each click-to-filter); **Follow-ups due promoted** above the pipeline with an urgent accent; inline **→ Mark <next>** advance on top-target cards.
  - **Opportunity Inbox:** **auto-submit filters**; **click-to-sort headers** (Buyer/Budget/Fit/Strategic) preserving active filters; **inline advance** per row returning to the *filtered* view (`return_to`); Action-vs-Status legend + header tooltips.
  - **Pipeline Lanes:** reframed from action-triage to a **status kanban** (New→Pursuing→Submitted→Won/Lost) matching the Dashboard model, with **one-click advance** per card and Won/Lost at Submitted; **Pass collapsed** into an expandable strip.
  - **Buyer Graph:** **Next-best-action emphasized** (no longer muted); new **Last-touch (days-since)** column with a stale flag; **stage filter** (Cold/Warming/Engaged/Client) + sortable headers.
  - **Talent Roster:** **KPI cards are click-to-filter**; new inline **reel-review queue** (approve/decline without leaving the page, `return_to`); **sort** (matchable-first / completeness / discipline).
  - **Projects:** **Deadline** column with **overdue** flag; **understaffed** row flag (assigned < roles); text progress swapped for a **mini progress bar**; **Active/Delivered** segmented filter.
  - Shared: safe same-site `return_to` redirect helper on `set_status`/`talent_review` (guards against open-redirects).
- **Acceptance:** every page renders; inline actions persist and return to origin; sorts/filters don't error; flags compute correctly; no schema change; suite green.
- **QA:** 147 tests pass (8 new; `test_lanes_render` rewritten for the kanban). All six pages smoke-tested 200 with the new components; inline advance + review-approve redirect verified. Screenshot caveat unchanged (sandbox blocks Playwright); structural HTML + tests stood in.
- **Status:** ✅ built; QA green (screenshot caveat above).

### Cycle 15 — 2026-06-16 — Overview reorg + Brief checklist + Outreach proposal & examples
- **Roadmap stage:** Demand side → Prepare + Outreach-to-win (decision-surface depth). Migration-safe (`brief_progress` table added; all else templates/routes).
- **Build:**
  - **Overview (detail):** subnav unified into a `opp_subnav` macro and **reordered** — Overview · Budget estimate · Outreach · Talent match · Pursuit brief · Buyer profile · Qualification rationale (applied across all 6 opp subpages). Action bar de-duplicated (removed Pursuit brief / Plan outreach / Talent match — they're tabs); **Mark <next> pushed to the far right** after Original posting. **Strategic-value card moved below** the Opportunity + Win/loss row.
  - **Pursuit brief:** the response outline and next steps are **merged into one ordered, de-duplicated pursuit checklist** (budget/team/close overlaps collapsed) that is **tracked** — each step toggles done and a progress bar persists (`brief_progress` table + `brief_done_keys`/`set_brief_step`; index+slug keys). **Council verdict: removed the Plain-text / Copy-brief export buttons** — the brief is an internal working/decision doc; the outbound artifact is the Outreach email (which keeps its own copy). (`.txt` route retained, just unlinked — reversible.)
  - **Outreach:** **recommended examples to attach** per discipline (e.g. Sonic branding → Sonic logo / Brand anthem / Campaign adaptation) — honest framing: recommended *portfolio* pieces, not synthesized audio (no audio AI). **First-touch message rewritten** into the relationship-first proposal template (thanks → "built for" → relevant-work bullets → unified-system framing → "anticipate supporting" deliverables → walk-through close), adapting examples/deliverables to the discipline and the greeting to the saved contact name.
- **Acceptance:** subnav order correct on all subpages; action bar de-duped with Mark right-aligned; strategic card relocated; brief checklist persists + progresses; export buttons gone; outreach shows examples + template message; message greeting adapts to contact; migration-safe; suite green.
- **QA:** 154 tests pass (8 new/updated). Rendered all three surfaces; checklist toggle round-trip, example list, and multi-paragraph message verified. Screenshot caveat unchanged (sandbox blocks Playwright); structural HTML + tests stood in.
- **Status:** ✅ built; QA green (screenshot caveat above).

---

**Supply side complete (Cycles 5–9):** recruit → match → assign (Jon's button) → track → broadcast. The OS now spans the full pipeline end to end: scan → qualify → estimate → prepare → outreach → win → recruit → match → assign → track → broadcast.
