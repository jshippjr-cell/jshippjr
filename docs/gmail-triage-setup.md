# Gmail Triage Setup (Phase B1)

Agentic email triage: an LLM reads the unread emails in a Gmail label, decides
which are real paid music opportunities, extracts the fields, and lands them on
the **Signal Radar** in the review queue (never auto-pursued). This is the
recall play for a starving funnel — it catches the gigs the keyword filters
drop, and lets you point *many* saved-searches at one inbox without a parser per
source.

B1 is **manual**: a "📥 Run Gmail triage" button on the radar (and a Gmail MCP
server for driving it from Claude). Autonomy (a scheduled run) is B2.

## What you need

1. A Gmail account that receives the alert emails (forward your Mandy /
   ProductionHub / Hitmarker / LinkedIn / agency saved-searches to it).
2. A Gmail **label** (and a filter) that those alerts land in — default
   `Chordential/Alerts`. Triage only ever reads unread mail under this label, so
   personal mail is never sent to the model.
3. A Google OAuth client (Desktop type) → a one-time **refresh token** with the
   `gmail.modify` scope.
4. An Anthropic API key.

## One-time: mint the refresh token

1. Google Cloud Console → APIs & Services → **enable the Gmail API**.
2. Credentials → Create Credentials → **OAuth client ID** → type **Desktop app**.
   Note the **client ID** and **client secret**.
3. Run Google's OAuth consent flow once (e.g. with the
   `google-auth-oauthlib` quickstart) requesting scope
   `https://www.googleapis.com/auth/gmail.modify`, and copy the **refresh
   token** from the result.

## Render env vars / secrets

| Variable | Value |
|---|---|
| `CHORDENTIAL_GMAIL_CLIENT_ID` | OAuth client ID |
| `CHORDENTIAL_GMAIL_CLIENT_SECRET` | OAuth client secret (secret) |
| `CHORDENTIAL_GMAIL_REFRESH_TOKEN` | the minted refresh token (secret) |
| `CHORDENTIAL_GMAIL_LABEL` | optional; default `Chordential/Alerts` |
| `ANTHROPIC_API_KEY` | Anthropic key (secret) |
| `CHORDENTIAL_TRIAGE_MODEL` | optional; default `claude-haiku-4-5` |

Build command must install the extras: `pip install '.[web,gmail,ai]'`
(the libraries are optional and lazily imported, so they're only needed where
triage actually runs).

## Use it

- **In the app:** Signal Radar → **📥 Run Gmail triage**. It scans the unread
  alerts, lands real opportunities on the radar, and reports
  `Scanned N … M landed … K skipped`. Triaged gigs go through the normal
  review/promote flow — nothing is auto-pursued.
- **From Claude (MCP):** install `'.[gmail,mcp]'`, set the same env vars, and run
  `chordential-gmail-mcp` (or `python -m chordential_oia.mcp.gmail_server`).
  Tools: `list_unread`, `get_message`, `mark_processed`, `status`.

## Cost & safety

- **Dedup first:** already-triaged messages (matched on Gmail id) are skipped
  *before* any LLM call — re-running is cheap and idempotent.
- **Cheap model:** the default is Haiku for the is-this-a-gig? + extract step.
- **Label pre-filter:** only unread mail under the alerts label is ever read, so
  personal email never reaches the model.
- **Human gate preserved:** triaged gigs land as signals in the review queue;
  promotion to the pipeline stays a human action.

## Roadmap

- **B2** — autonomous interval triage (wire into the scheduler) with the same
  cost controls.
- **B3** — feed your accept/reject decisions into `qualification.record_label()`
  (the existing training moat) so extraction accuracy compounds.
