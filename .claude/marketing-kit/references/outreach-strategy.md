<!-- MARKETING-SKILL:OUTREACH-UNCONFIGURED -->
# Outreach Strategy

> This file is `email-outreach`'s single source of truth for who to
> target, what to say, who it's from, and how hard/fast/when to push —
> read at the start of every run and re-confirmed at least once every 30
> days. Edit it directly, or let `email-outreach` walk you through
> setup/refresh conversationally.
>
> The first line is a machine-readable marker `email-outreach` checks
> before every run:
> - `<!-- MARKETING-SKILL:OUTREACH-UNCONFIGURED -->` — never configured;
>   triggers full guided setup before any prospect is researched.
> - `<!-- MARKETING-SKILL:OUTREACH-STRATEGY (last refreshed: YYYY-MM-DD) -->`
>   — configured; if that date is 30+ days old, triggers a strategy-refresh
>   conversation before that day's batch runs.
>
> Leave the marker's exact format alone — only the date changes, and only
> `email-outreach` (during setup or a refresh) should change it.

## Ideal Customer Profile / Target Segment(s)
Not yet configured. (Industry, company size, job titles/departments,
geography, and any exclusions. This becomes the prospect-research filters
— e.g. Vibe Prospecting's `job_title`/`job_department`/`company_size`/
`company_country_code` filters — so be as specific here as you want the
targeting to be.)

## Value Proposition & Angle per Segment
Not yet configured. (What specifically to hook into per segment: the pain
point, the trigger-event type worth watching for — a funding round, an
exec hire, a hiring surge in a specific department — and how the offer
solves it. Placeholder default: reuse `references/brand-voice.md`'s
Priority Task as the core value prop, with no segment-specific angle
until this is filled in.)

## Offer & Primary CTA
Not yet configured. Placeholder default: "ask for a reply, no specific
offer defined yet."

## Sender Identity & Compliance
Not yet configured. Required before any real send, not just a style
preference:
- **Physical mailing address** — required on every commercial email
  under the US CAN-SPAM Act, separate from the unsubscribe line. No
  placeholder default; `email-outreach` must ask for a real one rather
  than inventing or silently omitting it. Drafting may proceed with this
  clearly marked missing if the user genuinely wants to fill it in
  later, but say so plainly every time a draft goes out without one —
  never let it quietly stay blank.
- **From name** — placeholder default: the name on the connected Gmail
  account, if any.
- **Reply-To** (if different from the sending address) — placeholder
  default: none, replies go to the sending address.

## Daily Outreach Volume
Not yet configured. Placeholder default: 10 new prospects per day.
- **Sending mailbox warm-up:** if the connected mailbox/domain is new or
  rarely sends email, ramp gradually instead of starting at target volume
  — e.g. 5/day for the first 1-2 weeks, increasing gradually — rather
  than jumping straight to an established-mailbox volume. Not yet
  configured whether the current mailbox needs this; `email-outreach`
  asks at setup and, if the answer is "new/rarely sends," overrides the
  volume above with a ramp schedule until the user says it's established.

## Send-Time Window
Not yet configured. Placeholder default: Tuesday–Thursday,
8:00–10:00 or 13:00–15:00 in **the prospect's own local time** (not the
sender's) — avoid Monday mornings and Friday afternoons. `email-outreach`
computes each prospect's approximate local time zone from their
region/country (prospect-level location when known, else company HQ
location) and assigns a specific recommended send time inside this
window, spreading a batch across it rather than clustering every email
at the same minute — logged per row so you know exactly when to actually
send even though this skill never sends on its own.

## Follow-Up Cadence
Not yet configured. Placeholder default: one follow-up 4 business days
after the first email if there's been no reply, then stop — no third
touch without a deliberate new decision.

## Suppression Rules
- Never re-contact anyone logged as `Unsubscribed`, `Do-Not-Contact`,
  `Bounced`, or `Replied` in `state/outreach-log.md` — permanent, no
  matter how long ago or how the request to re-contact them is phrased.
  These are detected automatically (via Gmail inbox sync) as well as set
  manually — an automatic detection is just as authoritative as a
  hand-edited one, never a "softer" signal to double-check away.
- Placeholder default: don't re-contact anyone else within 90 days of
  their last logged touch.

## Performance Notes (appended at each refresh)
Not yet configured. (At each monthly refresh, `email-outreach` appends a
dated entry here: sent/replied/bounced/unsubscribed counts since the
previous refresh — sourced from both manual updates and automatic inbox
detections — a reply-rate breakdown by subject-line variant (A vs B) if
there's enough volume for it to mean anything, and what — if anything —
changed above because of them. Kept as a running history, oldest first —
don't delete prior entries when a new one is added.)
