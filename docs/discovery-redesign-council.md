# Discovery Console — Redesign Council Deliberation

**Convened:** 2026-06-18 · **Chair:** Jon Shipp (CEO) · **Mandate:** make the
human-gated crawler page legible — what needs me, what's fetching, how to turn it
on/off — and decide how to handle login-gated sources.

Governing rule unchanged: **the machine proposes, Jon disposes.**

---

## The complaint

The old page led with two insider columns — **Status** and **Decision** — that
told Jon nothing actionable. There was no clear "this is fetching," no on/off
control, and approvals were buried below the catalog instead of demanding
attention. Login-gated sources (LinkedIn, X, TAXI) sat in the same list as
freely-combable ones with no way to use them.

## Positions

**Head of Product:** Reorder top-to-bottom by what the user needs: _what needs
me → what's running → what I can't automate → tools_. Kill "Status/Decision";
replace with plain controls.

**Demand-Gen Manager:** Approvals go in a numbered **① Needs your approval**
block at the very top, with an explicit "you're all caught up" empty state so the
queue is never ambiguous.

**Competitive Intelligence Analyst:** Per source, a literal **Fetch on/off**
toggle (that _is_ the decision) and an **Activity** cell that reports — last
fetched, leads found, or "Idle." A green marker when there's recent activity.

**CTO (architecture):** A true _"fetching now"_ pulse implies a background
scheduler. Recommend that as **Phase 2** (a Render Cron job that fetches On
sources' approved targets on an interval and writes live status). Phase 1 ships
the legible layout + real activity history without new infrastructure.

**CTO (security / ToS) — the load-bearing call:** Jon floated storing his
credentials so the crawler could log in as him. **We do not do that.** Storing
third-party passwords is a liability, and automated login to ToS-restricted
platforms (LinkedIn especially) risks account bans and legal exposure. Adopt the
**manual-assist** pattern instead: login-gated sources get their own list; each
row opens the site **in Jon's own logged-in browser** — the crawler never holds a
credential. Where a site offers an official **API/RSS**, integrate a scoped token
(encrypted secret) later — never a username/password.

**COO:** Every On source needs a visible last-success time or it rots silently.
The Activity column doubles as the SLA monitor.

**CEO (Jon):** Agreed — manual-assist over a password vault.

## Ratified design

Page order: **① Needs your approval** · **② Fetching · your sources** (on/off
toggle + Activity) · **③ Login-gated · manual-assist** (open-in-your-session) ·
**④ Approved & fetched targets** · **⑤ Tools** (add source / propose targets).

Columns replacing Status/Decision: **Source · Fetch (toggle) · Activity (last
run + leads found) · open/leads link.**

Login-gated: manual-assist handoff. **No stored passwords.**

## Build phases

- **Phase 1 — Clarity (shipped):** page restructured; `login_gated` flag on the
  catalog + DB; per-source activity aggregated from crawl targets; manual-assist
  list; `CHORDENTIAL_ENABLE_SCRAPE` turned on so approved targets actually fetch.
- **Phase 2 — Live fetching (shipped):** an in-process background auto-fetcher
  (`scheduler.py`) — chosen over a separate Render cron service because the SQLite
  DB lives on a disk only the web service can mount. Each cycle it fetches a
  bounded batch of due targets on On, non-gated sources (Approved backlog + stale
  re-scans), with a live "fetching now" indicator on the console. Discovered leads
  are deduped so re-scans don't pile up. Tunable via `CHORDENTIAL_AUTOFETCH*`.
- **Phase 3 — Authenticated sources:** official API / RSS via encrypted tokens
  (e.g. Reddit). Still no password vault.

Human gate is unchanged throughout: only **Approved** targets are ever fetched,
and every result lands in a review queue (Inbound Leads / Pending talent) for
Jon to promote.
