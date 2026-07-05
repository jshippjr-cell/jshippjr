# Turning on outbound email (step by step)

Chordential's outbound email (the website-inquiry acknowledgment, outreach
"Send now", crew broadcasts, recruiting invites) is built and waiting. It stays a
safe no-op until a mail sender is configured. This guide turns it on using
**Resend** (simplest setup, free tier covers this volume).

You need: access to the **Render dashboard** for the `chordential` service, and
access to wherever **chordential.com's DNS** is managed (your domain registrar —
GoDaddy, Namecheap, Cloudflare, Squarespace, Google Domains, etc.).

---

## Part A — Create the Resend account (2 min)
1. Go to **https://resend.com** and click **Sign up**. Use your Google account
   (jshippjr@gmail.com) or an email + password.
2. When it asks, you don't need to invite a team — skip/continue to the dashboard.

## Part B — Add and verify chordential.com (5 min + DNS wait)
This is what makes email land in the inbox instead of spam. You're proving to the
world that Chordential is allowed to send from chordential.com.

1. In the Resend dashboard left menu, click **Domains** → **Add Domain**.
2. Type `chordential.com` and click **Add**.
3. Resend now shows you a list of **DNS records** to add (usually 3–4 rows: one
   MX, one or two TXT for SPF, and one or more TXT/CNAME for DKIM). Leave this
   page open — you'll copy from it.
4. In a new tab, log in to **wherever chordential.com's DNS lives** (your
   registrar) and find the **DNS records / DNS management** screen for the domain.
5. For **each row** Resend shows, add a matching record at your registrar:
   - **Type** — match it exactly (MX, TXT, or CNAME).
   - **Name / Host** — copy exactly. If your registrar already appends
     `.chordential.com`, paste only the part *before* it (e.g. `send` rather than
     `send.chordential.com`). If unsure, most registrars accept the full value.
   - **Value / Points to** — copy exactly (long strings — copy the whole thing).
   - **Priority** — only the MX row has one (usually `10`). Enter it there.
   - Leave TTL at its default.
   Save each record.
6. Back on the Resend Domains page, click **Verify** (or just wait — it
   auto-checks). Records usually verify in a few minutes but can take up to an
   hour. When every row shows a green **Verified**, you're done with DNS.
   > If it's stuck after an hour, double-check you didn't add an extra
   > `.chordential.com` to the Name field, and that you copied the full Value.

## Part C — Get the SMTP credentials (2 min)
1. In the Resend left menu, click **API Keys** → **Create API Key**.
2. Name it `chordential-prod`, permission **Full access** (or "Sending access"),
   and click **Create**.
3. **Copy the key now** — it starts with `re_...` and is shown only once. Paste it
   somewhere safe for the next step. (If you lose it, just create another.)
4. The SMTP settings you'll need are fixed for Resend:
   - **Host:** `smtp.resend.com`
   - **Port:** `587`
   - **Username:** `resend`  (literally the word "resend")
   - **Password:** the `re_...` API key you just copied
   - **From address:** must be on the verified domain, e.g. `hello@chordential.com`
     (the mailbox doesn't need to exist to *send* — replies just come back to you
     if it does).

## Part D — Put the credentials in Render (3 min)
1. Go to **https://dashboard.render.com** and open the **chordential** service.
2. Click the **Environment** tab (left side).
3. Add these environment variables (click **Add Environment Variable** for each).
   Set the four secrets FIRST, and the provider switch LAST:

   | Key | Value |
   |-----|-------|
   | `CHORDENTIAL_SMTP_HOST` | `smtp.resend.com` |
   | `CHORDENTIAL_SMTP_PORT` | `587` |
   | `CHORDENTIAL_SMTP_USER` | `resend` |
   | `CHORDENTIAL_SMTP_PASS` | your `re_...` API key |
   | `CHORDENTIAL_SMTP_FROM` | `hello@chordential.com` |
   | `CHORDENTIAL_MAIL_PROVIDER` | `smtp` |

4. Click **Save Changes**. Render redeploys automatically (~2 min). The moment
   it's live, email is on.

## Part E — Confirm it works (2 min)
1. Go to **https://chordential.com/start** and submit the form with **your own
   email** in the contact field (any test project details).
2. Within a minute you should receive the **"Thanks for reaching out to
   Chordential"** email. Check spam the first time — if it's there, it means a DNS
   record didn't verify; recheck Part B.
3. That's it — every real inquiry now gets the acknowledgment automatically.

---

## Notes
- **Nothing sends until Part D is complete.** With the provider unset (or half-set),
  the app logs "would send…" and delivers nothing — by design.
- **Free tier:** Resend is 100 emails/day / 3,000 per month free — well above
  inquiry volume. Paid plans start ~$20/mo if you outgrow it.
- **Alternative provider:** Postmark works identically — swap the host to
  `smtp.postmarkapp.com`, username/password to your Postmark server token. Same
  six Render variables.
- **What else turns on:** once mail is live, the outreach "Send now" button, the
  crew broadcast emails on assignment, and recruiting invites all start delivering
  too — they share this one sender.
