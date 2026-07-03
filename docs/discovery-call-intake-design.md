# Discovery Call Intake & the Multi-Lane Intake Framework — Design

**Status:** Design (2026-07-03) · No code yet · Author: Jon + ChordOS
**Depends on:** ADR-0013 (CI anchored to the Opportunity), `docs/campaign-intake-prd.md`,
`docs/architecture/CAMPAIGN_INTELLIGENCE.md`
**Proposes:** ADR-0014 (below) — the intake framework + meeting-driven capture via seams.

---

## 0. The reframing

Campaign Intake stops being a *transcript uploader* and becomes an **intelligent meeting
assistant plus an extensible intake framework.** The hero flow is:

```
Click "Schedule Discovery"  →  Hold the meeting  →  Meeting ends
   →  Campaign Intelligence updates automatically  →  Review changes  →  Keep selling
```

Two ideas carry the whole design:

1. **No intake lane is "the" workflow.** Discovery-call scheduling, pasted notes, a pasted
   transcript, a producer debrief, an RFP, an email thread, an uploaded client brief, and
   every future integration (Meet, Teams, Slack, CRM) are all **lanes**. Each lane does one
   job: turn *something that happened* into a **normalized Capture**. Everything after the
   Capture is shared.

2. **One object, one write path, one review.** Every lane funnels into the *same* Campaign
   Intelligence object through the *same* provenance API, and every lane's output lands as
   **proposed** — surfaced for one human review before downstream modules consume it. CI is
   the single source of truth no matter how information entered.

The extensibility contract (the point of the framework): **a new lane can be added without
touching the Campaign Intelligence model, the extractor contract, or the review UI.** A lane
only has to emit a normalized Capture.

---

## 1. Principles (what must stay true)

- **No lane is primary; the pipeline is shared.** Lanes differ only at the *edge* (how the
  raw material arrives). The normalize → extract → contribute → review → propagate spine is
  identical for all of them. (This is already true for the text lanes — `_apply_capture` in
  `campaign_intake.py`.)
- **Machine proposes, human disposes — even when capture is automatic (Constitution §4.1).**
  Automatic ingestion makes the human gate *more* important, not less: a discovery transcript
  can propose a dozen fields, but nothing is confirmed and nothing propagates downstream until
  the operator reviews. Auto-ingest fills CI at `needs_review`; **confirmation is what moves
  qualification, the buyer profile, the proposal, and the brief.**
- **Provider seams, null by default (ADR-0004).** Meeting creation, calendar, and
  transcription are three seams. With nothing configured the lane is *disabled and says so* —
  the manual lanes still work. A real provider upgrades the experience when its env is set.
  Nothing raises or blocks.
- **LLM behind a seam, deterministic-first (ADR-0005).** The transcript analyzer is the same
  injectable extractor the text lanes use (null → deterministic heuristic). No AI-generated
  craft; the AI reads and structures, it never composes.
- **Honesty (Constitution §7).** No fabricated transcript, no invented fields, no silent
  auto-confirm. A bot that didn't join says so; a deferred provider says "not configured"; a
  low-confidence field is labeled, not hidden.
- **Additive, migration-safe schema (ADR-0007); never block the event loop (ADR-0010);
  hostile/outbound work is offloaded (ADR-0008).**
- **CI remains the single source of truth (ADR-0013).** Anchored to the Opportunity; inherited
  in place at Won.

---

## 2. The intake framework (the extensibility contract)

### 2.1 The normalized Capture envelope

Every lane produces the same thing — a **Capture** (already an immutable evidence record in
`captures`). The framework standardizes its shape so the shared pipeline is lane-agnostic:

```
Capture {
  id
  ci_id                # the Campaign Intelligence it enriches (opportunity-anchored)
  opp_id               # denormalized for the review surface
  lane                 # discovery_call | paste_notes | paste_transcript | debrief |
                       #   rfp | email_thread | client_brief | <future>
  stance               # objective ("what happened") | debrief ("what's your read")
  modality             # notes | transcript | voice | rfp | email | document
  raw_text             # the normalized text the extractor reads (or "" if binary-only)
  artifact_ref         # optional pointer to the stored source file / recording
  external_ref         # provider id (Zoom meeting id, Recall bot id, Fireflies transcript id)
  provenance_source    # the source token stamped on every field: "discovery_call",
                       #   "notes", "producer_debrief", "rfp", "email", "client_brief", …
  metadata_json        # speakers[], timestamps, duration, meeting title, participants, …
  extraction_json      # what the extractor proposed (the evidence trail)
  status               # received | transcribing | ready | ingested | failed
  created_by, created_at
}
```

### 2.2 The IntakeLane contract

A lane is a small object that knows how to *arrive at a Capture*. It does **not** know about
facets, kinds, provenance, confidence, or the review UI:

```
IntakeLane:
  key            -> str                      # stable id ("discovery_call")
  label          -> str                      # "Discovery call"
  modality       -> str                      # default modality it produces
  is_available() -> bool                     # env/seam configured? (drives UI enable/disable)
  # exactly one of:
  #   • synchronous lanes (paste/upload): produce_capture(opp, payload) -> Capture
  #   • asynchronous lanes (meeting): schedule(opp, options) -> Meeting, and later a
  #     webhook/poller calls the shared ingest when the transcript is ready.
```

New lane = implement this contract + register it. The registry (`intake_lanes.py`) is the only
place that enumerates lanes; the CI model, extractor, and review surface never change.

### 2.3 The shared pipeline (already built; unchanged by new lanes)

```
Capture(raw_text, stance, provenance_source, metadata)
  → extract(text, stance, llm=…)             # LLM seam → deterministic heuristic fallback
  → for each candidate: contribute(...)       # provenance API: facet×key×kind,
                                              #   sources[]+confidence, conflict-aware,
                                              #   NEVER clobbers a human-owned value
  → raise material gaps as open_questions
  → assemble a REVIEW BATCH (this capture's proposed changes)
  → (on human confirm) propagate to the Opportunity + downstream engines
```

The only *new* pieces the framework needs beyond what exists today: (a) the **lane registry +
envelope**, (b) the **review batch** grouping a capture's proposed changes, and (c) the
**async meeting lifecycle** (seams + webhook + job). Everything else is in place.

---

## 3. The intake lanes (existing + new + future)

| Lane | Modality | Stance | Provenance source | Arrival | Status |
|---|---|---|---|---|---|
| **Discovery call** | transcript | objective | `discovery_call` | async (webhook) | **NEW** |
| Paste meeting notes | notes | objective | `notes` | sync | built |
| Paste transcript | transcript | objective | `transcript` | sync | built (modality) |
| Producer debrief | voice/notes | debrief | `producer_debrief` | sync (+ voice seam) | built (text) |
| Upload RFP | document | objective | `rfp` | sync (parse) | modality wired, parser TBD |
| Upload email thread | email | objective | `email` | sync (parse) | modality wired, parser TBD |
| Upload client brief | document | objective | `client_brief` | sync (parse PDF/DOCX) | **NEW** |
| Google Meet / Teams | transcript | objective | `discovery_call` | async | future (same seam) |
| Slack / CRM import | notes/email | objective | `slack`/`crm` | async | future |

All rows converge on the identical pipeline in §2.3. Adding a row never edits the CI model.

---

## 4. The Discovery Call lane (the new hero)

The discovery-call lane is **asynchronous and event-driven**. It spans three provider seams and
a meeting lifecycle. This is the only lane that needs new infrastructure; it reuses the shared
pipeline for everything after the transcript arrives.

### 4.1 Three seams (each null-by-default, mirroring `payments/` and `mailer.py`)

| Seam | Job | First concrete provider | Later | Env |
|---|---|---|---|---|
| **Meeting** | create the meeting + join URL | **Zoom** (Server-to-Server OAuth) | Google Meet, Teams | `CHORDENTIAL_MEETING_PROVIDER`, `CHORDENTIAL_ZOOM_*` |
| **Calendar** | create the invite, add attendees, attach conferencing, carry consent notice | **Google Calendar** | Outlook | `CHORDENTIAL_CALENDAR_PROVIDER`, `CHORDENTIAL_GOOGLE_*` |
| **Notetaker / transcription** | put a recording bot in the meeting; return transcript + speakers + timestamps | **Recall.ai** (recommended) | Zoom AI Companion, Fireflies, Fathom, Otter | `CHORDENTIAL_NOTETAKER_PROVIDER`, `CHORDENTIAL_RECALL_API_KEY`, … |

**Why Recall.ai as the first notetaker provider.** The user's requirement is "invite a
recording/transcription service to *the meeting*, across Zoom now and Meet/Teams later." Recall
is a *unified meeting-bot API*: you POST a bot to any meeting URL (Zoom/Meet/Teams), it joins,
records, and returns a transcript + speaker labels + timestamps via one webhook contract. That
matches the framework goal exactly — **one adapter covers three platforms**, so the "future
integrations" for Meet/Teams cost almost nothing on the notetaker side. Direct adapters
(Zoom AI Companion via Zoom's `recording.transcript_completed` webhook; Fireflies GraphQL +
webhook; Fathom API) remain first-class alternates behind the same seam for anyone who already
pays for one. *(Recall/Fireflies/etc. are real paid dependencies + cost — hence the seam: off
by default, on when a key is set. Consistent with every other outward integration.)*

**Seam boundary.** The `NotetakerProvider` ABC is deliberately small so any provider fits:
`invite(meeting_url, opp_ref) -> bot_id`, `fetch_transcript(bot_id) -> Transcript{text,
speakers, segments[{speaker,t0,t1,text}], duration}`, and a `verify_webhook(headers, body) ->
event`. Providers that join by *calendar* instead of by *URL* (Fireflies/Otter) implement
`invite` as "ensure the calendar event carries our bot's invite address."

### 4.2 The meeting ↔ opportunity association (before the meeting begins)

A `meetings` row is created **at schedule time**, binding the meeting to the Opportunity *before*
anyone joins. This is the durable tie the whole async flow depends on — the transcript finds its
way home by looking up this row, never by guessing.

```
meetings {
  id
  opp_id                     # the association — set at creation, immutable
  ci_id                      # resolved eagerly (ensure_for_opportunity)
  meeting_provider           # zoom | meet | teams | manual
  external_meeting_id        # provider's meeting id
  join_url, host_url
  start_at, duration_min, timezone
  attendees_json             # [{name,email,role}] — client + Jon
  notetaker_provider         # recall | zoom_ai | fireflies | …
  bot_id                     # the notetaker's bot/session id (correlates the webhook)
  consent_recorded           # was a recording-consent notice included in the invite?
  status                     # scheduled | bot_invited | in_progress | transcript_ready
                             #   | ingested | failed | canceled
  transcript_capture_id      # the Capture created on ingest (links meeting → evidence → CI)
  error, created_at, updated_at
}
```

### 4.3 Event flow (schedule → ingest → review)

```
 Opportunity page / Outreach email / Calendar
        │  click "Schedule Discovery Call"
        ▼
 [1] Meeting seam.create()  ── Zoom API ──▶ meeting id + join_url
 [2] Calendar seam.create() ── GCal API ──▶ invite to client + Jon (+ consent notice)
 [3] Notetaker seam.invite(join_url) ─────▶ bot_id
 [4] INSERT meetings{opp_id, ci_id, external_meeting_id, bot_id, status=scheduled}
        │   Opportunity page now shows: "Discovery call scheduled · <time> · join link · bot armed"
        ▼
   … the meeting happens; the bot records transcript + speakers + timestamps …
        │
        ▼
 [5] Provider POSTs webhook  ──▶  /webhooks/notetaker/{provider}
        │   verify signature (ADR-0011-style secret) · dedupe by event id · 200 fast
        │   match by bot_id/external_meeting_id → meetings row → opp_id/ci_id
        │   set meetings.status = transcript_ready ; store transcript payload
        ▼
 [6] Scheduler loop (in-process, ADR-0010) picks up status=transcript_ready:
        fetch/normalize transcript → Capture{lane=discovery_call, modality=transcript,
          stance=objective, provenance_source=discovery_call, metadata=speakers/ts}
        → run the SHARED pipeline (extract → contribute[needs_review] → gaps)
        → build a REVIEW BATCH (capture_id) ; meetings.status = ingested
        ▼
 [7] Notify (Web Push / ntfy — already wired): "Discovery call processed — N updates to review"
        ▼
 [8] Opportunity page: "Review this call's updates" — the diff (new/changed/read/risks/
        follow-ups/conflicts). Operator confirms (bulk or per-field), edits, or rejects.
        │   CONFIRM → propagate to the Opportunity columns + re-evaluate qualification,
        │            buyer profile, proposal draft, pursuit brief.
        ▼
 [9] Won → Project + Campaign Workspace INHERIT the same CI in place (ADR-0013). Nothing recreated.
```

### 4.4 Webhook receiver (the async front door)

- **Public, verified endpoint** (`/webhooks/notetaker/{provider}`), exempt from the admin gate
  like other public surfaces (ADR-0011), but **signature-verified** per provider
  (Zoom `x-zm-signature` HMAC; Recall webhook secret; Fireflies signature). Reject unverified.
- **Idempotent**: dedupe on provider event id (a transcript-ready event can be re-delivered);
  a second delivery is a no-op.
- **Fast + non-blocking (ADR-0010)**: verify, persist the payload, flip `meetings.status`,
  return `200` immediately. All heavy work (fetch full transcript, LLM extraction) happens in
  the scheduler loop / a threadpool-offloaded job — never in the webhook request.
- **Correlation**: match `bot_id` first, then `external_meeting_id`. If no `meetings` row
  matches (e.g. a bot fired for a meeting we didn't originate), park the transcript as an
  **unassociated capture** the user can attach to an opportunity manually (honest fallback, not
  a silent drop).

### 4.5 Async processing (no new infrastructure)

Reuse the existing **in-process `scheduler.run_loop`** (already runs signals/autofetch on an
interval). Add one tick handler: *"find `meetings` where `status=transcript_ready`, ingest,
advance to `ingested`."* This keeps the design on the current single-service deployment (Render,
one web service) with **zero new infra** — consistent with ADR-0008/0010. If throughput ever
demands it, the same handler moves to a dedicated worker without changing the contract.

### 4.6 Failure modes (all honest, none silent)

| Failure | Behavior |
|---|---|
| No provider configured | "Schedule Discovery Call" shows a one-time "Connect Zoom / a notetaker to enable" prompt; the manual lanes remain fully usable. |
| Bot failed to join | `meetings.status=failed`, `error` recorded; the opp shows "the notetaker didn't capture this call — paste notes or a transcript instead" (falls back to a manual lane). |
| Transcript delayed | Stays `transcript_ready`→ingest retries with backoff; the opp shows "processing…", never a fake result. |
| Low-confidence extraction | Fields land `needs_review` with a visible confidence + the source quote; never auto-confirmed. |
| Unassociated transcript | Parked as an unassociated capture with an "attach to opportunity" action. |
| Webhook signature invalid | Rejected; logged; no state change. |

---

## 5. Data model (all additive; ADR-0007)

**New table — `meetings`** (§4.2): the schedule-time association + lifecycle.

**Extend `captures`** (additive columns): `lane`, `provenance_source`, `artifact_ref`,
`external_ref`, `metadata_json` (speakers/timestamps/duration/participants), `status`. (Today's
`captures` already has `ci_id`, `campaign_id` (nullable), `stance`, `modality`, `raw_text`,
`extraction_json`.)

**Extend `campaign_intelligence_field`** — *no new columns needed for confidence* (`confidence`
exists) *or provenance* (`sources[]` exists). Add **evidence citation** inside `value_json`:
`{"evidence": {"quote": "...our budget's around twenty grand...", "speaker": "Sarah Chen",
"t": 767, "capture_id": 42}}`. This gives the "meeting assistant" provenance card
("Sarah Chen, 12:47 — '…'") with **no schema churn** — value_json is already free-form.

**Review batch — derive, don't add a table (preferred).** Stamp each field *event* and each
proposed field with the originating `capture_id` (event log already exists —
`campaign_intelligence_event`). "This call's proposed changes" = the fields whose latest event
has this capture_id and are still `needs_review`. (Optional `review_batches` table only if we
later want cross-capture batching; not needed for v1.)

**Provider config (env seams; null by default):**
`CHORDENTIAL_MEETING_PROVIDER` (`null|zoom`), `CHORDENTIAL_ZOOM_ACCOUNT_ID/CLIENT_ID/CLIENT_SECRET`,
`CHORDENTIAL_ZOOM_WEBHOOK_SECRET`; `CHORDENTIAL_CALENDAR_PROVIDER` (`null|google`),
`CHORDENTIAL_GOOGLE_*`; `CHORDENTIAL_NOTETAKER_PROVIDER` (`null|recall|zoom_ai|fireflies|fathom`),
`CHORDENTIAL_RECALL_API_KEY` + `CHORDENTIAL_RECALL_WEBHOOK_SECRET` (and per-provider equivalents).

**Module layout (mirrors `payments/`):**
```
src/chordential_oia/
  meetings/     base.py (MeetingProvider ABC + Null) · zoom.py · __init__.py (env selector)
  notetaker/    base.py (NotetakerProvider ABC + Null) · recall.py · zoom_ai.py · fireflies.py
  calendaring/  base.py (CalendarProvider ABC + Null) · google.py
  web/
    intake_lanes.py         # the lane registry + the Capture envelope helpers
    campaign_intake.py      # (exists) shared pipeline; gains ingest_transcript(meeting, transcript)
    app.py                  # schedule route + /webhooks/notetaker/{provider} + review routes
    scheduler.py            # (exists) + a transcript_ready tick handler
```

---

## 6. UX

### 6.1 Entry points (all three the user named)
- **Opportunity page** — a "Schedule Discovery Call" action in the intake panel (next to
  "Update Intelligence").
- **Outreach email generator** — a "Propose a discovery call" insert that drops a scheduling
  link/time into the drafted email and, on send, arms the meeting.
- **Calendar / Meeting section** — a lightweight meetings list ("upcoming / awaiting transcript
  / processed") scoped to opportunities.

### 6.2 Schedule modal
Provider (Zoom), date/time + duration, attendees (client email prefilled from the opp contact +
Jon), notetaker choice (default from env), and a **recording-consent notice** toggle (on by
default; its text goes into the invite — honesty + two-party-consent hygiene). Submitting runs
§4.3 steps 1–4 and returns to the opp with the scheduled state.

### 6.3 Pre-meeting state (on the opp)
A calm strip: "🎥 Discovery call scheduled · Thu 2:00pm · Join link · 🤖 notetaker armed ·
Reschedule / Cancel." No CI changes yet.

### 6.4 The post-meeting review surface (the important new UX)
Because capture is automatic, the review *is* the product. A "**Review this call's updates**"
card on the opp, shown after `ingested`:

- **Header**: "Discovery call · 32 min · 2 speakers · understanding 62% → 88%."
- **New facts** (n) — each with value, confidence, and the **source quote + speaker + timestamp**.
- **Changed facts** — old → new, with the quote that drove the change; a **conflict** with a
  human-confirmed value is shown as *keep yours / use proposed*, never auto-applied.
- **The producer's read** — insights / recommendations / risks the analyzer inferred (clearly
  labeled inferred, not fact).
- **Follow-up questions** — material gaps still open.
- **Projected downstream impact** — "confirming will move qualification 62%→88%, refresh the
  buyer profile, and update the proposal draft & pursuit brief." Nothing propagates until confirm.
- **Actions**: **Confirm all** (one tap), per-field confirm/edit, reject. Every field stays
  editable; edits are authoritative (ADR-0013).

### 6.5 The unified "Add intelligence" affordance
The existing Update Intelligence panel gains a lane switcher so every lane lives in one place:
`🎥 Schedule discovery · 📝 Paste notes · 📄 Paste transcript · 🎙 Producer debrief ·
📎 Upload RFP / brief / email`. Same panel, same review, one mental model.

---

## 7. Integrations (concrete)

- **Zoom (meeting seam).** Server-to-Server OAuth app (account-level, no per-user login):
  `POST /users/me/meetings` → `id`, `join_url`, `start_url`. Webhooks (`meeting.started`,
  `recording.transcript_completed`) verified via the webhook secret (HMAC of the payload). If
  using Zoom's own transcript, this seam doubles as the notetaker for Zoom-hosted calls.
- **Google Calendar (calendar seam).** OAuth (offline refresh token) → `events.insert` with
  `conferenceData` (or the Zoom link), attendees, and the consent notice in the description.
- **Notetaker seam.** *Recall.ai* (recommended default): `POST /bot` with the meeting URL →
  `bot_id`; webhook `transcript.done` → `GET /bot/{id}/transcript` (segments with speaker +
  ms timestamps). *Zoom AI Companion*: no bot; consume Zoom's `recording.transcript_completed`.
  *Fireflies*: calendar-based join; GraphQL `transcript` query + webhook. *Fathom/Otter*:
  API/webhook where available. All behind the one ABC in §4.1.
- **Notifications (already wired).** Web Push (VAPID) + ntfy topic for "call processed — review."

---

## 8. Downstream refresh (extends what's built)

On **confirm**, the confirmed engagement facts write back to the Opportunity's own columns and
re-evaluate (today: `budget_band → budget_min/max`; extend to timeline, deliverables→scope
hints, discipline). Because qualification, estimate, buyer profile, proposal, and pursuit brief
all read the Opportunity, they recompute from one source — **no separate refresh, no divergent
copy** (ADR-0013 §18.5). The review surface shows the *projected* deltas before the user commits,
so "update qualification / buyer profile / proposal / brief" is a previewed, confirmed action —
not a silent side effect.

---

## 9. Security, privacy, consent

- **Recording consent** is included in the calendar invite (default on) and recorded on the
  `meetings` row; copy is honest about who's recording and why. Respects two-party-consent norms.
- **Transcripts are client PII.** Stored as immutable Captures. Retention + redaction policy is
  an explicit setting; note the **durable-storage caveat** — recordings/transcripts on local
  disk are not durable across Render deploys (S3/R2 is the deferred fix, same as uploads).
- **Webhook auth** per provider signature; **least-privilege** OAuth scopes (create meetings,
  read transcripts — not mailbox/drive).
- **Provider isolation.** Outbound calls are best-effort and offloaded (ADR-0008/0010); a
  provider outage degrades to the manual lanes, never an error page.

---

## 10. Build sequence (once approved — each increment shippable behind the flag)

1. **Intake framework refactor** — the lane registry + Capture envelope + review-batch (derive
   from events). No behavior change to existing lanes; they become registered lanes. *(Pure
   internal; de-risks everything after it.)*
2. **The review surface** — "Review this capture's updates" diff + confirm-all/per-field, with
   projected downstream deltas + evidence citations. Works for the *existing* text lanes first
   (immediately useful, no external deps).
3. **Client-brief / RFP / email parsers** — the remaining synchronous lanes (document text
   extraction), reusing the shared pipeline.
4. **Meeting + calendar seams** — Zoom meeting creation + Google Calendar invite + the
   `meetings` table + "Schedule Discovery Call" from the three entry points. *(Meeting exists;
   no transcript yet.)*
5. **Notetaker seam + webhook + async ingest** — Recall.ai first: invite bot → webhook →
   scheduler ingest → review batch → notify. The hero flow closes here.
6. **Provider breadth** — Zoom AI Companion / Fireflies adapters; then Google Meet / Teams
   (mostly free once the notetaker seam is Recall).
7. **Evidence-rich provenance** — speaker/timestamp citations on every field; jump-to-quote.

Each step ships behind `CHORDENTIAL_CAMPAIGN_WORKSPACE` + the provider seams, dogfood-first,
and writes through the CI provenance model — so the UI and providers evolve without ever
changing the object.

---

## 11. Decisions (locked 2026-07-03, Jon)

1. **First notetaker provider → Recall.ai.** ✅ One adapter covers Zoom/Meet/Teams, so the
   future Meet/Teams lanes are nearly free. Behind the null-by-default `NotetakerProvider` seam;
   Zoom AI Companion / Fireflies remain first-class alternates.
2. **Downstream timing → apply-on-confirm, with a projected-impact preview.** ✅ Auto-ingest
   lands every field `needs_review`; qualification / buyer profile / proposal / brief move only
   when the operator confirms. The review surface shows the projected deltas first. The machine
   never moves the numbers on its own; a confirmed human edit is never clobbered.
3. **Scheduling → ChordOS owns Zoom + the Google Calendar invite.** ✅ At schedule time ChordOS
   creates the Zoom meeting *and* sends the calendar invite to the client + Jon (with the
   consent notice). Fullest assistant feel; both the meeting and calendar seams are in scope.

### Still to confirm (not blocking increments 1–3)
4. **Consent copy.** The exact recording-consent language for the invite (legal/brand) — needed
   before the calendar seam ships (increment 4).
5. **Retention.** How long raw transcripts/recordings are kept, and whether PII is redacted at
   rest — ties to the deferred durable-storage/S3 work; needed before the notetaker lane is
   used on real calls (increment 5).

---

## ADR-0014 — Campaign Intake is a multi-lane framework; capture can be meeting-driven via seams

*(To be copied into `docs/architecture/ARCHITECTURE_DECISIONS.md` on approval.)*

**Decision.** Campaign Intake is an **extensible framework of intake lanes**, none primary. Every
lane normalizes to one **Capture** envelope and funnels through one shared pipeline
(extract → contribute → review → propagate) into the single Campaign Intelligence object. A new
lane (including meeting platforms) is added **without changing the CI model, the extractor
contract, or the review UI**. Meeting-driven capture (schedule → bot → transcript → auto-ingest)
is a first-class **asynchronous** lane built on three null-by-default provider seams — **meeting**
(Zoom first), **calendar** (Google first), and **notetaker/transcription** (Recall.ai first,
covering Zoom/Meet/Teams). Automatic ingestion lands all fields **proposed** (`needs_review`);
**human confirmation is the gate that propagates to the Opportunity and downstream engines.**

**Why.** The real primary source of Campaign Intelligence is the client meeting, not typed notes.
Making capture automatic while keeping the human disposition gate turns every discovery call into
enrichment with near-zero manual work — without ever letting the machine self-confirm or letting
one lane's plumbing leak into the shared model.

**Consequences.** Providers live behind ABCs selected by env, null by default; the manual lanes
always work. The webhook is signature-verified, idempotent, and non-blocking; heavy work runs in
the existing scheduler loop (no new infra). Captures are immutable evidence; CI fields carry
confidence + an evidence citation (speaker/timestamp) in `value_json`. Nothing propagates
downstream until reviewed. Recording consent is included in invites and recorded; transcript
retention/durability follows the deferred object-storage plan.
