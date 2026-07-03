# Discovery Call Setup Guide — Zoom, Google Calendar, Recall.ai

**Audience:** you, assuming you have never configured Zoom APIs, Google Calendar APIs, or
Recall.ai before. Follow top to bottom. When you finish, ChordOS can schedule a Zoom (or phone)
discovery call, record + transcribe it, and turn the transcript into Campaign Intelligence — no
manual uploads.

**How ChordOS reads configuration.** Everything is an **environment variable** set on your host
(Render → your service → **Environment** tab). There is no in-app settings screen — that's by
design (secrets never live in the app or the repo). Each integration is a *seam*: unset = that
piece is simply off and the rest still works. So you can turn these on **one at a time** and test
as you go.

**Recommended order:** ① Recall (recording) → ② Zoom (meeting creation) → ③ Google Calendar
(invites). You get value after each step. Phone calls need none of these.

---

## 0. What each service does (so the steps make sense)

| Service | Job in ChordOS | Env prefix | Needed for |
|---|---|---|---|
| **Recall.ai** | Sends a bot into the meeting, records + transcribes, hands ChordOS the transcript | `CHORDENTIAL_RECALL_*` + `CHORDENTIAL_NOTETAKER_PROVIDER` | auto transcription |
| **Zoom** | Creates the Zoom meeting + join link when you schedule | `CHORDENTIAL_ZOOM_*` + `CHORDENTIAL_MEETING_PROVIDER` | auto Zoom links |
| **Google Calendar** | Puts the call on your + the client's calendar, sends invites | `CHORDENTIAL_GOOGLE_*` + `CHORDENTIAL_CALENDAR_PROVIDER` | calendar invites |

If you set **none** of these, ChordOS still schedules a meeting record and (if email is
configured) sends a confirmation — you'd just paste the transcript in yourself afterward. Each
service you add removes one manual step.

---

## 1. Recall.ai — the recording bot (do this first)

Recall's bot joins any Zoom/Meet/Teams meeting regardless of the host's plan, so it works even on
a **free** Zoom or Google Meet account. Pay-as-you-go: ~$0.50/recording-hour + $0.15/hour
transcription (a 30-min call ≈ $0.33); free trial credits to start.

### 1a. Create the account + key
1. Go to **https://www.recall.ai/** → **Sign up** (self-serve). ⚠️ Not `getrecall.ai` — that's a
   different product.
2. In the dashboard, open **API Keys** → **Create key** → copy it (starts with `sk_…`). Keys
   don't expire; you disable them to rotate.
3. Note your **region** (top of the dashboard / your workspace URL): `us-east-1`, `us-west-2`,
   `eu-west-1`, etc.

### 1b. Set the env vars (Render → Environment)
```
CHORDENTIAL_NOTETAKER_PROVIDER = recall
CHORDENTIAL_RECALL_API_KEY     = sk_...your key...
CHORDENTIAL_RECALL_REGION      = us-east-1        # MUST match your workspace's region
```
> **`_PROVIDER=recall` is the switch** — without it the key does nothing.
>
> ⚠️ **Region matters — get it exactly right.** Recall's regions are *completely separate
> deployments*; a key is valid **only** on its own region's URL. Using the wrong region →
> **HTTP 401 Unauthorized** ("Recall invite failed" in your logs), *not* a "wrong region" error.
> Your workspace region is shown at the top-left of the Recall dashboard. The value maps to:
>
> | Dashboard region | `CHORDENTIAL_RECALL_REGION` |
> |---|---|
> | US East | `us-east-1` |
> | US West | `us-west-2` |
> | EU (Frankfurt) | `eu-central-1` |
> | Asia Pacific (Tokyo) | `ap-northeast-1` |

### 1c. How ChordOS uses it (no webhook needed)
ChordOS **polls** Recall: when you schedule a Zoom call, a bot is invited; a background loop
checks the bot every ~30 s and, once the call ends and the transcript is ready, ingests it. You
do **not** need to configure a Recall webhook. (A webhook is optional, for instant-instead-of-
~30 s ingest — skip it.)

**Verify:** after deploying, open any Opportunity → **Schedule discovery** → Zoom. The
"Upcoming Discovery" panel should show **Notetaker: Recall connected**. (Full end-to-end test in
§5.)

---

## 2. Zoom — automatic meeting creation

This lets ChordOS create the Zoom meeting + join link when you schedule. A **Server-to-Server
OAuth** app is the right type (no per-user login, runs unattended). Creating meetings works on a
**free** Zoom plan. *(Free Zoom can't produce its own cloud transcript — that's why Recall does
the recording.)*

### 2a. Create the Zoom app
1. Go to **https://developers.zoom.us/** (this is the developer portal — *not*
   `marketplace.zoom.us`, which Zoom now uses only for browsing/installing published apps) →
   **Sign In** with your Zoom account.
2. Click **Build App** (a button on the developer dashboard, or under a **Develop** menu) →
   choose **Server-to-Server OAuth** → name it `Chordential` → **Create**.
   - *Don't see "Build App"?* Server-to-Server OAuth apps require the account **owner/admin**.
     On a free single-user account you're the owner (fine); if it's blocked, enable app creation
     in Zoom **Admin → Advanced → App Marketplace**.
3. On **App Credentials**, copy **Account ID**, **Client ID**, **Client Secret**.
4. **Information** tab: fill the required company/name/email fields (Zoom won't activate the app
   until these are filled).
5. **Scopes** tab → **Add Scopes** → add:
   - `meeting:write:meeting:admin` (create meetings) — in older UIs this is `meeting:write:admin`.
   - `user:read:user:admin` (read your own user) — older: `user:read:admin`.
6. **Activate** the app (Activation tab → Activate).

### 2b. Set the env vars
```
CHORDENTIAL_MEETING_PROVIDER   = zoom
CHORDENTIAL_ZOOM_ACCOUNT_ID    = ...
CHORDENTIAL_ZOOM_CLIENT_ID     = ...
CHORDENTIAL_ZOOM_CLIENT_SECRET = ...
```

### 2c. Verify
Schedule a Zoom discovery call (§5). The "Upcoming Discovery" panel should show a **Join
meeting** link. If it stays blank, see Troubleshooting.

---

## 3. Google Calendar — invites on both calendars

Optional but nice: puts the call on your calendar and the client's, and sends the invite email.
Booking works without it (you'd just not get a calendar event).

> Consumer `@gmail` works. The trickiest part is the one-time OAuth to mint a **refresh token**;
> follow carefully.

### 3a. Create the Google Cloud project + OAuth client
> Google renamed "OAuth consent screen" to the **Google Auth Platform** (tabs: Overview /
> Branding / Audience / Clients). The steps below use the new UI.
1. **https://console.cloud.google.com/** → create a project `Chordential`.
2. **APIs & Services → Library** → search **Google Calendar API** → **Enable**.
3. **APIs & Services → Google Auth Platform** → **Get started** → fill **App name** + **User
   support email** → for **Audience** pick **External** (the only option on a personal @gmail
   account) → finish. Leave **Publishing status = Testing** (do *not* publish).
4. On **Google Auth Platform → Audience → Test users → Add users**, add your own Google address.
5. **Google Auth Platform → Clients → Create client** → type **Web application** → under
   **Authorized redirect URIs** add `https://developers.google.com/oauthplayground` → **Create**
   → copy the **Client ID** and **Client Secret**.

### 3b. Mint a refresh token (one time, via OAuth Playground)
1. Go to **https://developers.google.com/oauthplayground**.
2. Click the ⚙️ gear (top-right) → check **Use your own OAuth credentials** → paste your Client
   ID + Secret.
3. Left panel → in **Input your own scopes** paste: `https://www.googleapis.com/auth/calendar`
   → **Authorize APIs** → sign in as yourself → allow.
4. Click **Exchange authorization code for tokens** → copy the **Refresh token**.

### 3c. Set the env vars
```
CHORDENTIAL_CALENDAR_PROVIDER    = google
CHORDENTIAL_GOOGLE_CLIENT_ID     = ...
CHORDENTIAL_GOOGLE_CLIENT_SECRET = ...
CHORDENTIAL_GOOGLE_REFRESH_TOKEN = ...
CHORDENTIAL_GOOGLE_CALENDAR_ID   = primary        # or a specific calendar's id
```

### 3d. Verify
Schedule a call with a client email → both of you should receive a Google Calendar invite.

---

## 4. Confirmation emails + your identity (OPTIONAL — you can skip the SMTP part)

**You can skip this whole SMTP block.** Scheduling, Recall, and — importantly — **Google
Calendar invites all work without it**, and a calendar invite already serves as the client's
confirmation. Only set SMTP if you specifically want *ChordOS itself* to send emails.

**Do set these two (no email service needed):** `CHORDENTIAL_OPERATOR_EMAIL` (just your email)
and `CHORDENTIAL_PUBLIC_DOMAIN` (your Render app URL, e.g. `https://your-app.onrender.com`).
For free new-request phone pings, set `CHORDENTIAL_NTFY_TOPIC` and subscribe to it in the ntfy
app — no email server required.

If you *do* want ChordOS to send email, the SMTP settings (Gmail example below) turn it on.
Gmail needs 2-Step Verification → an **App Password** as `CHORDENTIAL_SMTP_PASS`
(`CHORDENTIAL_SMTP_HOST=smtp.gmail.com`, `CHORDENTIAL_SMTP_PORT=587`).
```
CHORDENTIAL_MAIL_PROVIDER = smtp
CHORDENTIAL_SMTP_HOST = ...        CHORDENTIAL_SMTP_FROM = you@yourdomain.com
CHORDENTIAL_SMTP_USER = ...        CHORDENTIAL_SMTP_PASS = ...
CHORDENTIAL_OPERATOR_EMAIL = you@yourdomain.com   # where request notifications go
CHORDENTIAL_PUBLIC_DOMAIN  = https://your-app.onrender.com   # for links in emails
```
Optional phone-alert on a new request: `CHORDENTIAL_NTFY_TOPIC = your-secret-topic` (install the
free **ntfy** app, subscribe to that topic).

Working-hours (used only if you later add an availability picker) — all optional, sensible
defaults:
`CHORDENTIAL_BOOKING_TZ_OFFSET_MIN` (minutes east of UTC; EDT = -240), `CHORDENTIAL_BOOKING_DAYS`
(`0,1,2,3,4`), `CHORDENTIAL_BOOKING_START_HOUR`, `CHORDENTIAL_BOOKING_END_HOUR`.

---

## 4bis. AI extraction — make Campaign Intelligence actually *understand* the call (recommended)

Without this, ChordOS extracts facts with a **deterministic keyword matcher** — it catches
`$20,000` and "November" but *not* natural speech like "about twenty grand" or "by the fall". To
have it read a discovery call like a smart analyst (budget from "twenty grand", inferred
emotional direction, risks, recommendations, follow-up questions), turn on the LLM extractor:
```
ANTHROPIC_API_KEY = sk-ant-...            # from console.anthropic.com → API Keys
```
That's it — the extractor switches on automatically when the key is present (the `anthropic`
package is already in the build). Optional tuning:
```
CHORDENTIAL_INTAKE_MODEL = claude-sonnet-5   # default; use claude-haiku-4-5-20251001 for lower cost
CHORDENTIAL_INTAKE_LLM   = 0                  # set to 0 to force the deterministic pass off
```
It stays **honest + human-gated**: the LLM only *proposes* fields (they land `needs_review`),
facts vs. insights vs. recommendations stay distinct, a debrief never becomes objective fact,
and if the model errors it silently falls back to the deterministic pass. Cost is a few cents per
call. Get a key at **console.anthropic.com → API Keys**.

## 5. Test your first real discovery call

1. **Deploy** with the env vars set (Render redeploys on save).
2. Open an Opportunity → **Schedule discovery** (or accept a client Discovery Request) → pick
   **Zoom**, a date/time a few minutes out → **Schedule**.
3. **Check:** the "Upcoming Discovery" panel shows the date, **Notetaker: Recall connected**, and
   a **Join meeting** link. You + the client get a calendar invite (if Google is set) and a
   confirmation email (if SMTP is set).
4. **Join** the meeting from the link. The Recall bot should join within ~30 s (it appears as a
   participant). Talk for a minute — mention a budget, a timeline, a deliverable.
5. **End** the call.

### Verifying transcription → Campaign Intelligence
- Within a couple of minutes, the panel's **Transcript** flips to **Complete**.
- Open the Opportunity's **Campaign Intelligence** panel: new **proposed** facts appear (budget,
  timeline, deliverables, decision-makers) sourced to `discovery_call`, each with the speaker/
  timestamp evidence — awaiting your review (nothing auto-confirms).
- Confirm what's right; those facts write back to the Opportunity and refresh qualification.

Phone calls: choose **Phone** — a meeting record + confirmation email, no bot, no transcript.

---

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Panel shows **Notetaker: Not connected** | `CHORDENTIAL_NOTETAKER_PROVIDER=recall` not set (the key alone isn't enough), or the deploy didn't pick up env changes — redeploy. |
| **No Join link** after scheduling Zoom | `CHORDENTIAL_MEETING_PROVIDER=zoom` missing, Zoom app not **Activated**, missing `meeting:write` scope, or wrong Account/Client/Secret. Re-check §2. |
| Logs show **"Recall invite failed (HTTP Error 401: Unauthorized)"** | `CHORDENTIAL_RECALL_REGION` doesn't match your Recall workspace's region — the key is region-locked. Set it to your region (Tokyo = `ap-northeast-1`; see §1b). |
| Bot never joins the call | Meeting started before the bot was invited (schedule a few min ahead), or the join URL wasn't created (see the row above). Recall dashboard → **Logs** shows the bot's status. |
| **Transcript never completes** | The bot joined but transcription is off — confirm `meeting_captions` are available, or set `CHORDENTIAL_RECALL_TRANSCRIPT_PROVIDER` to a Recall transcription provider. Recall **Logs** shows the transcript status. |
| Transcript ingests but facts look wrong/empty | The transcript shape differed from the parser's expectation — send the raw Recall transcript JSON; the fix is one edit in `meetings/recall.py` only. |
| No calendar invite | `CHORDENTIAL_CALENDAR_PROVIDER=google` missing, or the refresh token expired/was revoked (re-mint via §3b), or the consent screen is still restricting access (add yourself as a Test user). |
| No confirmation emails | `CHORDENTIAL_MAIL_PROVIDER=smtp` + `CHORDENTIAL_SMTP_*` not set (they only log otherwise). |
| Request notifications not arriving | Set `CHORDENTIAL_OPERATOR_EMAIL` (email) and/or `CHORDENTIAL_NTFY_TOPIC` (push). |
| Everything 401/403 to a provider | A credential is wrong or the provider proxy is blocking — check the exact key, and the provider's own dashboard logs. |

**Golden rule:** each seam is independent. If something's off, unset that one provider's
`*_PROVIDER` var to confirm the rest still works, then re-add it. ChordOS degrades honestly — it
never fakes a link, a transcript, or a "connected" badge.
