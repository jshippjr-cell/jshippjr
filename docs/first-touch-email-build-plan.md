# First-Touch "Capabilities Email" — Build Plan

Derived from `docs/first-touch-email-council.md` + the founder's rulings (2026-06-25).
Chosen path: **Option B** — a composable, minimal, *personal* email (sent from Jon's
own mail client) carrying one soft link to a per-lead **tailored first-touch page**
where the rich content lives. Option C (Gmail HTML send) is deferred; Option D rejected.

Reuses the existing capabilities-doc machinery: `doc_overrides` (per-deal persistence),
the chip/override pattern, `outreach.py` (`build_outreach_plan`, `_mailto`,
`recommended_examples`), and the doc renderer/brand styles.

---

## Phase 1 — The block composer + Option A email mechanism
**Goal:** "Compose email" opens a composer of on/off blocks with a live preview; the
send action builds the personal email body into Jon's mail client (mailto). Minimal
defaults; choices persist per deal.

- **Composer route + screen.** `GET /opportunity/{id}/compose` (or a panel on the
  outreach page). Left rail = the block toggles; right = live preview of the assembled
  email; bottom = "Open in mail client" (and "Copy" fallback).
- **Block definitions** (assemble plain-text body from the lead + plan):
  - Default ON: **warm opener** (greeting + one specific line about their brief),
    **understanding** (the one-line synopsis — same source as the doc), **one relevant
    track** (the single best-fit from `recommended_examples`, named), **call offer**
    (the reworded excerpt already in `_build_first_touch`), **soft page link** (one line
    pointing at the Phase-2 page), **personal sign-off** (Jon's name/role).
  - Default OFF: **second/third example**, **credibility line** (original & cleared /
    fixed scope / vetted team), **P.S.**
- **Persistence.** Store the per-deal block on/off state (+ any edited block text) under
  a `compose` key in `doc_overrides` (reuse `get/save/update_doc_override`). Save routes
  mirror the doc's (`POST /opportunity/{id}/compose/block` toggle, `/compose/field` for
  edited text).
- **Send mechanism (Option A).** Build the `mailto:` from the selected blocks via the
  existing `_mailto` (subject = `email_subject`; body = assembled blocks). Replaces the
  current single fixed-body Compose button.
- **Defaults minimal** (founder ruling #4) — only the six default-ON blocks pre-checked.

## Phase 2 — The tailored first-touch page (the "awesome" layer)
**Goal:** a per-lead branded page the soft email link points at — capabilities-doc-lite,
framed as an intro, where the relevant track plays and the brief synopsis + soft CTA
shine.

- **Shareable route.** `GET /opportunity/{id}/first-touch` rendered for an external
  viewer (NOT admin-gated — the recipient must open it). Gate with an unguessable
  per-opp **token** in the URL (e.g. `?k=<token>`), so it's shareable but not
  enumerable. (Add a `share_token` to the opp/overrides; validate on the route.)
- **Content** (reuse the capabilities-doc renderer/components, trimmed for a cold open):
  brand letterhead, "for {client}" + their brief synopsis, **the one relevant track as a
  player** (reuse the compact brand audio player / relevant-work embeds), the call offer
  + a single low-pressure CTA (reply / book a short call), a tasteful footer. Keep it
  short — this is an intro, not the full capabilities doc.
- **Wire the composer's page-link block** to this URL (with the token).
- **Screen-only richness** (audio players, embeds); the page is the place audio actually
  plays (email can't).

## Phase 3 — Measure, then decide on Option C (deferred)
**Goal:** validate before building inbox-HTML plumbing.
- Lightweight engagement signal on the first-touch page (a view ping / opened-at stamp).
- Surface page-views per deal in the outreach view so Jon can see whether buyers click.
- **Only if** engagement justifies it: build **Option C** (branded HTML email via Jon's
  Gmail) — re-mint the Gmail token with a `send` scope, add a MIME-HTML composer with
  inlined CSS + hosted images, a per-client render pass; it still links out to the page
  for audio. Not authorized until the page proves out.

---

### Notes
- Keep the **default email personal and minimal** (Founder's Advocate guardrail) — it
  must read hand-typed, never assembled-by-software.
- The **page link is a bonus, softly on** (ruling #5): the email stands on its own; the
  link is one low-pressure line.
- No new send infrastructure in Phases 1–2 — the email still goes through Jon's own mail
  client (personal, deliverable). Option C is the only piece that ever sends from the app.
- Extend `tests/` per phase (composer block assembly + mailto body, token-gated page
  renders for an external viewer, page-link wiring, persistence).
