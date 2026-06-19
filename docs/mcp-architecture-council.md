# Backend MCP Architecture — Executive Council

**Convened:** CTO, Chief Product Officer, Head of Data, Head of Revenue Ops
**Question on the table:** How should Chordential's backend expose its
capabilities to AI agents (via the Model Context Protocol) versus wire them as
plain server-to-server API connections — across Gmail ingestion, the database,
opportunity storage, buyer intelligence, win/loss tracking, dashboard updates,
and the future integrations (LinkedIn, SAM.gov, ProductionHub, Mandy, Hitmarker,
CRM)?

This document is grounded in the **actual codebase** as it stands today. Every
"✅ Done" line points at real, shipped modules; every "🔜 Roadmap" line is net-new.

---

## 1. The decision rubric — when MCP, when direct API

We use one test for every capability. It is not "is it external?" — it is
**"does an LLM agent need to reason over this?"**

> **Wrap it in an MCP server when** the capability is *agent-facing*: an LLM
> needs to discover it, call it with judgment, interpret messy/unstructured
> input, or compose it with other tools. MCP gives a uniform, self-describing
> tool/resource interface with its own auth boundary, reusable across any
> MCP-capable client (Claude Desktop, Claude Code, a future Chordential agent).
>
> **Wire it as a direct API/in-process call when** the capability is
> *machine-facing and deterministic*: scheduled feed polls, high-frequency
> mechanical sync, or latency-sensitive UI render paths where no model is in the
> loop. Wrapping these in MCP only adds a hop and a failure mode.

Three secondary factors break ties:

| Factor | Leans MCP | Leans Direct |
|---|---|---|
| **Input shape** | Unstructured / natural language | Structured / typed records |
| **Caller** | An LLM agent making judgment calls | A cron job / the web app |
| **Latency budget** | Seconds OK (human-in-loop) | Milliseconds (page render) |
| **Reuse** | Many agent workflows share it | One code path uses it |
| **Write risk** | Read, or gated writes | — |

A capability can be **both**: the web app talks to SQLite directly for a 5ms
dashboard render *and* a thin MCP server exposes the same data, read-only, so an
agent can answer "which agency buyers went cold this month?" Same data, two
doors, different callers.

---

## 2. The verdict — capability by capability

| Capability | Verdict | Why | Today |
|---|---|---|---|
| **Gmail ingestion** | 🟢 **MCP server** | Reading an inbox and deciding *which* messages are real opportunities, then extracting fields from prose, is LLM-shaped work. | ✅ Direct webhook + regex parser shipped; MCP is the upgrade |
| **Database access** | 🟡 **Both** | App renders direct (fast); agent queries via a read-only MCP wrapper. | ✅ Direct (`db.py`); 🔜 MCP read layer |
| **Opportunity storage** | 🟡 **Both** | Storage is direct; an MCP toolset lets an agent create/score/promote with gated writes. | ✅ Direct; 🔜 MCP write tools |
| **Buyer intelligence** | 🟢 **MCP server (read)** | Account research & outreach drafting are agent workflows that want `get_buyer`, `next_best_action` as tools. | ✅ Engine shipped (`buyer_intel.py`); 🔜 MCP surface |
| **Win/loss tracking** | 🟡 **Both** | Kanban UI is direct; win-rate analysis & loss-reason mining are agentic reads. | ✅ Pipeline states + outcome value; 🔜 MCP analytics |
| **Dashboard updates** | 🔴 **Direct only** | Latency-critical render path, no model in the loop. Real-time = SSE/WebSocket, not MCP. | ✅ Direct render shipped |
| **SAM.gov** | 🔴 **Direct API** (+ optional MCP search) | Real, documented REST API; structured, high-volume, scheduled → a feed poll like RSS. | 🔜 Not present |
| **ProductionHub / Mandy / Hitmarker** | 🔴 **Direct ingestion** | No public APIs. Access is email alerts (wired) + gated scrape (wired). It's content extraction, covered by the Gmail MCP. | ✅ Email + crawler shipped |
| **LinkedIn** | 🟢 **MCP server** (via compliant provider) | Buyer/contact enrichment & person↔company matching is LLM-shaped. *No* direct scrape — ToS. Wrap a compliant data provider. | 🔜 Not present |
| **CRM (Salesforce / HubSpot)** | 🟢 **MCP server** | Two-way sync where an agent maps Chordential buyers ↔ CRM accounts and logs activity. Robust REST APIs underneath. | 🔜 Not present |

**Reading the colors:** 🟢 = primarily an MCP server · 🟡 = direct for the app,
MCP for the agent · 🔴 = direct API only (MCP would be the wrong tool).

---

## 3. Target architecture

```
                         ┌─────────────────────────────────────┐
                         │           AGENT LAYER                │
                         │  (Claude / Chordential copilot)      │
                         │  "triage my inbox", "draft outreach  │
                         │   to cold agency buyers", "why did    │
                         │   we lose the Toyota bid?"            │
                         └───────────────┬─────────────────────┘
                                         │  MCP (stdio / HTTP)
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                 │
 ┌──────▼───────┐  ┌──────▼───────┐  ┌───▼────────────┐  ┌────────────────▼─┐
 │  Gmail MCP   │  │ Chordential   │  │ Buyer-Intel MCP │  │  External-Enrich  │
 │  (triage +   │  │ Core MCP      │  │ (read: stage,   │  │  MCP              │
 │   extract)   │  │ (opps/signals/│  │  next action)   │  │  LinkedIn · CRM   │
 │              │  │  pipeline;    │  │                 │  │  (compliant       │
 │              │  │  read + gated │  │                 │  │  providers)       │
 │              │  │  write)       │  │                 │  │                   │
 └──────┬───────┘  └──────┬───────┘  └───────┬─────────┘  └────────┬─────────┘
        │                 │                  │                     │
        │                 ▼                  ▼                     │
        │         ┌───────────────────────────────────┐           │
        └────────▶│      DATA LAYER  (db.py)           │◀──────────┘
                  │  SQLite now → Postgres later        │
                  │  opportunities · signals · buyers   │
                  │  pipeline · outreach_events · …     │
                  └───────────────▲───────────────────┘
                                  │  in-process (direct, fast)
                  ┌───────────────┴───────────────────┐
                  │     FastAPI web app (app.py)        │
                  │  dashboard · inbox · lanes · radar  │   ◀── Direct render,
                  │  buyers · projects · matchboard     │       no MCP hop
                  └───────────────▲───────────────────┘
                                  │ direct feed polls (cron/scheduler)
                  ┌───────────────┴───────────────────┐
                  │   DIRECT INGESTION (no MCP)         │
                  │  RSS · SAM.gov API · email webhook  │
                  │  gated crawler (Reddit, boards)     │
                  └────────────────────────────────────┘
```

**The load-bearing idea:** the **data layer is the integration point**, not MCP.
Both the web app (direct, millisecond) and the agents (via MCP, second-scale)
read and write the *same* SQLite/Postgres store. Direct ingestion pipelines feed
that store on a schedule. MCP servers are a *second door* onto the same house,
built for a different kind of caller (an LLM with judgment), never a replacement
for the fast in-process path the dashboard depends on.

---

## 4. What's already done (the foundation MCP will sit on)

Every capability below is **shipped and working today** — as direct/in-process
code. MCP is an additive layer; none of this has to be rebuilt.

| Area | Status | Where it lives |
|---|---|---|
| Email-alert ingestion (Mandy, ProductionHub, Hitmarker, Staff Me Up, F5Bot) | ✅ | `intake.py`, `POST /signals/ingest`, `POST /signals/paste` |
| RSS / Atom feed polling | ✅ | `rss.py`, `scheduler.py` |
| Real-time Signal Engine (detect, score, freshness-rank) | ✅ | `signals.py` (`score × e^(-age/τ)`, τ=12h) |
| Human-gated discovery crawler (Reddit OAuth + HTML, curated catalog) | ✅ | `discovery.py`, `crawl_adapters.py` |
| SQLite store, 15 tables, idempotent migrations | ✅ | `db.py` |
| Opportunity storage + evaluation cache | ✅ | `db.py` (`opportunities` table, ~30 cols) |
| Qualification engine (disqualify → classify → rubric) | ✅ | `qualification.py` |
| Scoring engine (7 weighted signals, A/B/C/Watch tiers) | ✅ | `scoring.py` |
| Strategic-value (CMO) lens — "small-but-strategic" | ✅ | `strategic.py` |
| Buyer intelligence (stage, score, next-best-action) | ✅ | `buyer_intel.py` |
| Win/loss tracking (pipeline states + outcome value) | ✅ | `db.py`, `POST /opportunity/{id}/status` |
| Outreach audit trail | ✅ | `outreach_events` table |
| Dashboard / inbox / lanes / buyers / projects / matchboard | ✅ | `app.py` (~81 routes) |
| PWA + Web Push notifications (now with app-icon badge) | ✅ | `webpush.py`, `sw.js`, `base.html` |
| Reddit OAuth, email-in webhook | ✅ | `crawl_adapters.py`, `app.py` |

**What is *not* present today:** any MCP server or client, any LLM call, any
LinkedIn / SAM.gov / CRM connection, and a real Stripe implementation (stubbed).
The system is, by design, deterministic and self-contained — which is exactly why
adding a thin MCP layer is low-risk: there's a clean data layer to expose.

---

## 5. The roadmap — incomplete areas, sequenced

Sequenced by **leverage ÷ effort**. Each phase is independently shippable and
leaves the app fully working if we stop.

### Phase A — Chordential Core MCP (read-only) · *foundation*
**Goal:** let Claude/an agent answer questions over live data without touching
the web app. **Effort: small.** A thin MCP server wrapping existing `db.py`
read functions — no schema changes, no new data.
- Tools: `list_opportunities(filter)`, `get_opportunity(id)`, `list_signals`,
  `get_buyer(client)`, `pipeline_summary`, `win_loss_stats`.
- Resources: opportunity & buyer records as addressable context.
- **Guardrail:** read-only; no raw SQL exposed to the model (parameterized tools
  only, or a single allow-listed read query tool).
- **Unlocks:** "which agency buyers went cold?", "summarize this week's radar",
  "what's our win rate on sonic-branding deals?" — answered by an agent, live.

### Phase B — Gmail MCP (agentic triage) · *highest single upgrade*
**Goal:** replace the brittle regex parser with agentic extraction. **Effort:
medium.**
- Wrap Gmail API (OAuth) in an MCP server: `search_messages`, `get_message`,
  `list_unread`, `label`. The *agent* reads each candidate email and decides
  "is this an opportunity?" and extracts client / budget / brief into a
  structured opportunity — handling formats the regex parser can't.
- Keep the existing `POST /signals/ingest` webhook as the fast deterministic
  lane; Gmail MCP is the smart lane for the long tail.
- **Guardrail:** writes (creating opportunities) flow through Phase-A gated
  write tools, landing in the existing human review queue — never auto-pursued.

### Phase C — Direct ingestion: SAM.gov + opportunity write tools
**Goal:** new structured demand sources. **Effort: medium.**
- **SAM.gov = direct API**, not MCP. It has a documented REST Contract
  Opportunities API with keys. Wire it like RSS: a scheduled poll in
  `scheduler.py` → `signals.ingest_*` → review queue. Optionally a small MCP
  `search_sam(keywords)` tool for ad-hoc agent lookups.
- Add **gated write tools** to Core MCP: `create_opportunity`,
  `advance_stage`, `log_outreach` — every write lands in a review state.

### Phase D — Buyer-Intel MCP + External Enrichment (LinkedIn)
**Goal:** richer account intelligence. **Effort: medium-large.**
- **Buyer-Intel MCP (read):** surface `buyer_intel.py` as tools so agents draft
  outreach grounded in stage + history.
- **LinkedIn = MCP via a *compliant* provider**, never direct scraping (ToS).
  Wrap a sales-intelligence data API; agent matches a Chordential buyer to a
  company/decision-maker and enriches the buyer record. Net-new `contacts`
  enrichment on the buyer graph.

### Phase E — CRM MCP (two-way sync)
**Goal:** Chordential ↔ Salesforce/HubSpot. **Effort: large.**
- **CRM = MCP server.** Agent-mediated bidirectional sync: map buyers ↔
  accounts, push won deals, pull existing relationships, log activities.
  HubSpot ships an official MCP server; Salesforce has robust REST.
- **Guardrail:** sync is agent-proposed, human-approved before first write-back
  (same "machine proposes, Jon disposes" gate the crawler already uses).

### Cross-cutting prerequisites
- **Postgres migration** before multi-writer agent load (SQLite single-writer is
  fine for the app today; concurrent agent writes want Postgres/Supabase — the
  schema ports cleanly).
- **Auth boundary** for MCP servers (per-server tokens; agents never hold raw DB
  credentials).
- **Audit log** of all agent writes (extend the existing `outreach_events`
  pattern to a general agent-action log).

---

## 6. One-paragraph executive summary

Keep the **dashboard and every UI render direct and in-process** — MCP there
would only add latency. Treat the **SQLite/Postgres data layer as the single
integration point** that both the web app (fast path) and AI agents (MCP path)
share. Build **MCP servers where an LLM must reason**: Gmail triage, buyer
intelligence, LinkedIn enrichment, and CRM sync. Wire **direct APIs where data is
structured and scheduled**: SAM.gov, RSS, the email webhook, and the existing
gig-board ingestion (ProductionHub/Mandy/Hitmarker have no public APIs, so
they stay on the email + gated-crawler paths already shipped). Start with a
small, read-only **Core MCP** over today's database — it's days of work, changes
nothing existing, and immediately lets Claude reason over live opportunity,
buyer, and win/loss data.
