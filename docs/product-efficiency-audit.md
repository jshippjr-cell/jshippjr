# Product Efficiency Audit — What's Built, Where It Leaks, What to Fix First

*July 2026. The product-side companion to `efficiency-report.md` (which audited the
working process). Method: a six-lens multi-agent audit — interaction/UX seams, hot-path
data efficiency, duplication drift, background-engine efficiency, journey gaps vs.
`platform-website-plan.md`, and a live browser walkthrough of the running app — followed
by an adversarial verification pass in which every finding was independently re-checked
against the actual code and refuted, corrected, or confirmed. **43 findings survived
verification** (several with impact corrected downward; overstatements are noted in the
findings themselves). Full details per finding live in the workflow journal; this doc is
the ranked digest.*

---

## 0. Fix immediately — one real production bug

**Admin-gate exemption regex drifted from the portal's routes** (`app.py:208`, HIGH).
With `CHORDENTIAL_ADMIN_TOKEN` set (i.e. production), an agency reviewer who clicks
**Resolve/Reopen on a note, or the per-deliverable Approve / Request-changes buttons,
is 303-redirected to Chordential's internal admin login** — and because the redirect
converts their POST to a GET, the action is silently lost. Project-level Approve/
Request-changes still work (those paths are exempted); the newer per-note and per-asset
routes were added without updating the exemption regex. This is the flagship
"one link, no email" client surface failing in front of the exact people it exists to
impress. *Fix: one-line regex update now; durably, derive the exemption from a single
portal-route list so the two can never drift again — the root cause is duplication,
which is the audit's recurring theme.*

---

## 1. The five themes (what 43 findings actually say)

### Theme A — The reload tax on client-facing surfaces
Every review action on the delivery portal is a full POST → redirect → reload: posting a
timecoded note **resets the audio playhead to 0:00 paused** (a reviewer leaving 8 notes
re-seeks 8 times); resolve/reply **drops the `?v=` version selection**, teleporting the
reviewer off the round they were auditing (and a note posted while viewing v2 is tagged
to the *current* version — a data-correctness wrinkle, not just UX); compose's "live
preview" needs a full round-trip per block toggle. **Options, in ascending effort:**
(1) sessionStorage playhead + version restore (the scroll-fix trick, hours); (2) fetch()-
based in-place updates on the portal's actions (the handlers must gain JSON/fragment
responses); (3) htmx across the admin dashboard as the general pattern. The portal
deserves (2) regardless of whether we adopt (3) broadly.

### Theme B — Blind background work
The product's marquee "Build full profile" button tells the user to *refresh to watch*;
`/agencies` instead auto-reloads the whole page every 15s — **wiping any in-progress
form input** (Chrome/Safari) and re-running ~8 table scans per tick; the crawl button
blocks the request for 5–15s per page fetched; enrichment buttons silently no-op when
scraping is off. **Option:** one small JSON status endpoint pattern (per-agency: read
the enrichment blob; batch: read the scheduler status dicts) + a polling strip that
updates in place. Kills four findings with one pattern.

### Theme C — Blocking I/O in async handlers (latent full-site stalls)
Notification fan-out (SMTP loops, web-push, ntfy) runs synchronously inside `async def`
routes: uvicorn has **one event loop**, so a slow provider stalls *every* user —
admin, portals, `/healthz` — for up to N×timeout. The walkthrough *observed* an 8.0s
hang on the public apply form from the push calls alone; the SMTP half is latent until
a real provider is configured (which is now the plan of record). **Option:** make the
handlers `sync def` (FastAPI threadpools them) or wrap sends in `run_in_threadpool` —
mechanical, low-risk, and it removes a whole outage class before SMTP goes live.

### Theme D — O(table) data paths that were fine at 200 agencies, not at 12k+
All six autonomous-engine queue selectors full-scan `agencies` and JSON-parse every blob
in Python to pick one row — and the batch loop calls the selector **once per agency**
(O(table × batch) per pass, exactly the scan the queue-wedge bug lived in). `/agencies`
runs three full-table LIKE scans over multi-KB blob columns per page view.
`/relationships` — the plan's morning-read surface — runs ~150 queries and up to 50
write-commits on a cold render. The signal "seen" set grows without bound inside
`signals_json`. **Options:** push the status filter into SQL using the LIKE markers the
count functions already use (quick), or add a small indexed `enrich_status` column
maintained on save (right). Batch the `/relationships` reads into two grouped queries
and one transaction. These also make the Postgres cutover cheaper, not harder.

### Theme E — Duplication that has already drifted
The theme behind the production bug. The branded delivery document exists as a Jinja
template *and* a Python string builder (the ZIP can diverge from what the client
reviewed in the browser — real credibility exposure for a procurement-grade product);
the cap-audio player is pasted 5× with drift; six batch-kick routes are near-identical;
the CSS cache-buster `?v=22` is hardcoded in 4 templates (stale-CSS has already happened
once); the scroll-restore fix now has two divergent copies. **Option:** a consolidation
pass — shared Jinja partials/macros (audio player, batch banner), one batch-route
helper, one cache-buster variable, one source for the delivery-doc markup (offline Jinja
env for the ZIP, honoring the stdlib-only constraint on the ZIP path).

### Journey gaps (design intent, not regressions)
Verified as *gaps against the storyboards*, all on the composer/client loop: client
review feedback (timecoded notes, change requests, revision count) **never reaches the
composer's portal** — Jon relays it by hand, the exact relay the timecode feature was
built to kill; creator uploads go **live to the client instantly with no vet step** (a
"machine proposes, Jon disposes" breach — the client can hear unapproved work) and with
no client notification either; the first-touch page can render with zero playable music
and a recipient-less mailto; outreach drafts on agency pages dead-end (no send/copy/
promote). These four are the highest-leverage *product* upgrades in the audit: they
close the loop the three storyboards promise.

---

## 2. Full findings table (severity → effort within severity)

| Sev | Effort | Lens | Finding | Where |
|---|---|---|---|---|
| high | low | duplication | Admin-gate exemption regex drifted from the portal's actual routes: client 'Resolve' and per-asset sign-off bounce to the admin login in prod | `…/web/app.py`:208 |
| medium | high | duplication | The branded delivery package document is implemented twice (Jinja template + Python string builder), plus a third hand-mirrored public snapshot | `…/delivery.py`:1450 |
| medium | medium | interaction | Every review action on the client portal is a full-page POST/redirect that resets the audio playhead | `…/web/templates/delivery_portal.html`:354 |
| medium | medium | interaction | "Build full profile" background job has no progress surface — the UI literally tells the user to refresh | `…/web/templates/agency_detail.html`:31 |
| medium | medium | interaction | Compose page's "Live preview" requires a full Apply-POST round-trip for every block toggle | `…/web/templates/compose.html`:37 |
| medium | medium | dbperf | All six queue selectors full-scan the agencies table and JSON-parse blobs in Python to filter | `…/web/db.py`:2270 |
| medium | medium | dbperf | Every /agencies page load runs three full-table LIKE scans over multi-KB JSON blob columns | `…/web/app.py`:550 |
| medium | medium | engines | Auto-fetch parses hostile external HTML in-process, retaining the exact wheel-of-death failure the enrichment engine was moved out-of-process to eliminate | `…/web/discovery.py`:296 |
| medium | medium | journeys | Outreach engine dead-ends: drafts cannot be sent, copied, or promoted into the pipeline | `…/web/templates/agency_detail.html`:270 |
| medium | medium | journeys | Client review feedback never reaches the composer: portal omits comments, change requests, and revision count | `…/web/app.py`:3011 |
| medium | medium | journeys | Creator uploads go live to the client instantly with no vet step — and no way to notify the client after vetting | `…/web/app.py`:3048 |
| medium | medium | journeys | Posting a timecoded note reloads the review portal and kills audio playback | `…/web/templates/delivery_portal.html`:354 |
| medium | medium | journeys | /relationships GET runs ~150 queries plus up to 50 write commits per page view | `…/web/app.py`:936 |
| medium | medium | walkthrough | Homepage eagerly downloads a 2.8MB hero video on every visit with preload=auto | `…/web/templates/public/home.html`:26 |
| medium | low | interaction | 15-second blind location.reload() on /agencies wipes in-progress form input while an enrich pass runs | `…/web/templates/agencies.html`:162 |
| medium | low | interaction | Review-action redirect drops the ?v= version selection, snapping reviewers off the version they were annotating | `…/web/app.py`:4267 |
| medium | low | engines | run_loop awaits each heavy cycle inline, so a long enrich pass delays time-sensitive gig-feed polling by up to the pass length | `…/web/scheduler.py`:1109 |
| medium | low | engines | Supervised passes re-select with limit=1 per agency, and the selector is a full-table Python-side JSON scan — O(table) work per agency, per pass | `…/web/scheduler.py`:418 |
| medium | low | engines | Per-agency manual actions bypass the shared heavy lock — n clicks spawn n concurrent scraping workers, recreating the overload the lock exists to prevent | `…/web/scheduler.py`:126 |
| medium | low | journeys | First-touch page can dead-end with zero music and a recipient-less mailto CTA | `…/web/templates/first_touch.html`:133 |
| medium | low | journeys | Background enrichment pipeline demands manual hand-refreshing to watch it finish | `…/web/templates/agency_detail.html`:31 |
| medium | low | walkthrough | Public intake form submits block on synchronous phone-push notifications (observed 8.0s hang) | `…/web/public.py`:268 |
| medium | low | walkthrough | Blocking SMTP/push loops inside async handlers stall the entire event loop (whole site freezes) | `…/web/app.py`:3986 |
| low | medium | interaction | POST /agencies/crawl fetches up to 5 live directory pages synchronously inside the request | `…/web/app.py`:648 |
| low | medium | duplication | The cap-audio player (CSS + JS widget) is copy-pasted 5 times and has already drifted — inconsistent behavior across client-facing pages | `…/web/templates/delivery_portal.html`:47 |
| low | medium | duplication | Six copy-pasted 'run a batch now' routes (× six scheduler starters × six template banner blocks) with inconsistencies already between them | `…/web/app.py`:659 |
| low | medium | engines | Re-enrich timer seeds to 'a full interval from boot' while every push redeploys — under active dev cadence re-enrichment may never run, and all engine stats zero on each deploy | `…/web/scheduler.py`:1070 |
| low | medium | engines | One fresh Python interpreter per agency instead of one supervised worker per pass — fixed spawn+import+connect tax on every item | `…/web/scheduler.py`:369 |
| low | medium | walkthrough | Every page view opens two DB connections; nav badges add a third query pair per minute per tab | `…/web/app.py`:291 |
| low | low | interaction | Lead triage actions dump the user back to the unfiltered /leads view, losing the queue they were working | `…/web/app.py`:1201 |
| low | low | interaction | Match Board drag-drop assign always does a blind full reload and treats failure as success | `…/web/static/matchboard.js`:24 |
| low | low | dbperf | Supervised batch pass re-runs the full-table selector (plus a full-table LIKE count) once per agency | `…/web/scheduler.py`:418 |
| low | low | dbperf | Signal-scan and score rotating queues sort never-eligible rows to the front, guaranteeing worst-case scans every cycle | `…/web/db.py`:1871 |
| low | low | dbperf | Batch engines re-SELECT and re-parse the exact rows and blobs their selector just loaded | `…/web/intelligence.py`:406 |
| low | low | dbperf | Signal snapshot 'seen' set grows without bound inside agencies.signals_json, inflating every scan and every table pass | `…/web/opportunity_signals.py`:326 |
| low | low | dbperf | insert_opportunity_signal does SELECT-then-INSERT per signal despite an existing UNIQUE index | `…/web/db.py`:1799 |
| low | low | duplication | site.css cache-buster '?v=22' hardcoded in 4 templates — a bump must be made in all four or pages serve week-stale CSS (has already happened once) | `…/web/templates/public_base.html`:8 |
| low | low | duplication | The scroll-restore fix now exists as two divergent copies, and other standalone POST-heavy pages use a third mechanism or none | `…/web/templates/capabilities_doc.html`:583 |
| low | low | engines | Lock-busy cycles still reset their interval timer, so losing one lock race defers an engine a full interval (6 hours for re-enrich) | `…/web/scheduler.py`:1107 |
| low | low | engines | Batch progress is surfaced by full-page reload every 15s against a route that runs ~8 table scans per render | `…/web/templates/agencies.html`:162 |
| low | low | walkthrough | Agency enrichment buttons give zero started/progress feedback; silently no-op when scraping is off | `…/web/app.py`:1015 |
| low | low | walkthrough | Dashboard materializes the entire incoming queue to render 6 rows and a count | `…/web/app.py`:1121 |
| low | low | walkthrough | Client-facing delivery portal (and creator portal) missing favicon — 404 console error on every load | `…/web/templates/delivery_portal.html`:3 |

---

## 3. Prioritized fix plan

**P0 — same day (all low effort, real exposure):**
1. Admin-gate regex fix + single portal-route source (§0).
2. Move notification/mail sends off the event loop (`sync def` / threadpool) — kills the
   observed 8s public-form hang and the latent full-site stall before SMTP goes live.
3. First-touch page: fall back to showcase tracks when empty; give the mailto a real
   recipient. Portal favicon.

**P1 — the seamlessness pass (one focused sprint):**
4. Portal polish trio: preserve `?v=` (and tag comments to the *viewed* version),
   restore audio playhead across actions, then fetch()-based in-place review actions.
5. The JSON-status + in-place-polling pattern for all background work (replaces the
   blind 15s reload and every "refresh to see progress" card).
6. Queue selection in SQL (or an indexed status column) — one change, six engines
   faster, and `/agencies` page-load scans fixed with the same markers.

**P2 — close the storyboard loops (highest product value):**
7. Composer feedback loop: render client comments/change-requests/revision count on the
   creator portal; notify creators on changes-requested/approved via the existing mailer
   seam.
8. Publish gate on creator uploads: pending flag → Jon presses "Publish to client" →
   reviewer notification fires ("machine proposes, Jon disposes," restored).
9. Outreach drafts: add send/copy/promote actions (wire to the existing compose/send
   flow).
10. `/relationships` read path: two grouped queries, one transaction.

**P3 — consolidation & engine tuning (background-pace):**
11. Shared partials: audio player, batch-banner, cache-buster variable, scroll-restore;
    single-source delivery doc (offline Jinja for the ZIP, stdlib constraint honored).
12. Engine tuning: don't reset interval timers on lock-busy; persist/restore engine
    stats across deploys; route per-agency manual actions through the heavy lock; move
    auto-fetch parsing out-of-process like enrichment; one worker per pass instead of
    one interpreter per agency.
13. Homepage hero: `preload="metadata"` + poster.

*Not re-litigated here (already the plan of record): the Postgres cutover for
zero-downtime deploys, and the broader htmx/design-system direction from
`platform-website-plan.md` — Theme A/B fixes are deliberately shaped so they become the
first pieces of that direction rather than throwaway patches.*
