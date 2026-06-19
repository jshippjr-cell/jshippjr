# Signal Engine — Email-in setup (Phase 2)

Goal: forwarded alerts (F5Bot, Mandy/ProductionHUB/Hitmarker saved searches,
Google Alerts) land on the **Signal Radar automatically** — no pasting.

The app side is done: a token-protected webhook at **`POST /signals/ingest`** that
parses an email (labeled digest *or* link-list like F5Bot) into scored signals.
You just need to point your alerts at it. Two ways — pick one.

## 0. One-time: set the shared secret
Render → your service → **Environment** → add
`CHORDENTIAL_SIGNAL_TOKEN` = *(a long random string)*. This protects the webhook.

---

## Option A — Gmail bridge (recommended: free, no DNS, ~5 min)
Your alerts already arrive in Gmail. A tiny Google Apps Script forwards them in.

1. In Gmail, make a **filter** that labels your alert emails **`Chordential`**
   (e.g. matches `from:f5bot.com OR from:mandy.com OR subject:(composer)` → Apply
   label "Chordential"). New alerts get the label automatically.
2. Go to **script.google.com → New project**, paste the script below, set
   `TOKEN` to your secret, **Run** once (authorize when prompted).
3. **Triggers** (clock icon) → Add Trigger → `pollAlerts`, time-driven, every
   **5 minutes**. Done — alerts now flow to the Radar within 5 min.

```javascript
// Chordential — Gmail → Signal Radar bridge.
const WEBHOOK = 'https://chordential.com/signals/ingest';
const TOKEN   = 'YOUR_SIGNAL_TOKEN';            // = CHORDENTIAL_SIGNAL_TOKEN in Render
const QUERY   = 'label:Chordential is:unread';  // which emails to ingest

function pollAlerts() {
  GmailApp.search(QUERY, 0, 25).forEach(function (thread) {
    thread.getMessages().forEach(function (msg) {
      if (!msg.isUnread()) return;
      UrlFetchApp.fetch(WEBHOOK + '?token=' + encodeURIComponent(TOKEN) + '&source=email', {
        method: 'post',
        payload: { subject: msg.getSubject(), 'body-plain': msg.getPlainBody() },
        muteHttpExceptions: true
      });
      msg.markRead();
    });
    thread.markRead();
  });
}
```

## Option B — Mailgun inbound route (a real inbound address)
1. Mailgun (free) → add a subdomain you control (e.g. `inbound.chordential.com`)
   with the MX records they give you (keeps your Google email on the root domain
   untouched).
2. **Receiving → Routes → Create**: match `signals@inbound.chordential.com`,
   action `forward("https://chordential.com/signals/ingest?token=YOUR_SECRET&source=email")`.
3. Set your alert services / a Gmail forward to send to that address. Mailgun
   POSTs the parsed email (subject + body-plain) to the webhook.

---

## Recommended alert sources to point in
- **F5Bot** (free): watch `composer`, `music producer`, `original score`,
  `sound designer`, `music needed` → emails in minutes.
- **Mandy / ProductionHUB / Hitmarker**: saved searches → **instant** email
  (never daily digest — that's 24h of latency).
- **Google Alerts**: `"composer wanted"`, `"music for"`, brand/campaign launches.

Each becomes a scored signal on the Radar, ranked by freshness × score.
