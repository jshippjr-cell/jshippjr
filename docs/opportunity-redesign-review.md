# Opportunity Workspace Redesign — the overnight design-org review

*2026-07-08 overnight sprint. Eight personas (EP, agency EP, product designer, IA, Apple critic, Linear critic, first-time user, staff engineer) critiqued independently; a design director adjudicated — rulings below, disagreements preserved verbatim.*

## The final page (zones top to bottom, max 6, with what each contains and why it exists)

1. **Command header (unboxed, no card chrome)** — title 28px + buyer link; one-line contact row beneath (`Name · Role · tel · mail · LinkedIn`, muted); **two pills only: stage + tier**; small fit% chip linking to Qualification rationale tab; right side: permanent **Client workspace** + **Campaign Brief** buttons and a `⋯ Actions` `<details>` overflow holding Create discovery call / Commercial Review / Original post / Start production; identity-edit stays as its existing disclosure. *Exists because:* identity + the two permanent artifacts (one-URL-forever law) belong at the top; everything else is the NEXT card's job.
2. **NEXT — the ember hero** — court badge (YOUR/THEIR MOVE etc.), one 16px action label, since-age, ONE primary button (the resolved `next_act` route, Enter-bound). The page's only accented card and only `live-dot`. When won, its slot renders "Open project →". *Exists because:* it is the ratified question rendered; 28 of 30 daily opens are 4-second court checks.
3. **State rail + Discovery cluster** — the existing `stage-stepper` restyled as a slim unboxed rail (dots, caps labels, hairline connector), single advance button demoted to ghost weight, "Mark delivery doc sent" rendered as a milestone control on the rail; directly beneath, one **Discovery** cluster containing the three existing conditional sub-blocks (requests / times offered / Upcoming Discovery) with their `{% if %}` guards verbatim. *Exists because:* one stage machine, one rendering; a meeting is one thread, not three cards.
4. **Campaign Intelligence** — conflicts (tinted) and open gaps and the producer's read visible on load; confirmed facet sections collapsed per-section `<details>`; the intake form collapsed to a single prompt row ("Paste a transcript…") that expands on focus — **auto-open when the record is empty**. CI blocking gaps feed the NEXT engine as proposed actions. *Exists because:* it's the moat, but intelligence is a verdict, not a dump; the mouth shows only at feeding time.
5. **Tab subnav** — Overview / Budget estimate / Outreach / Talent match / Pursuit brief / Buyer profile / Qualification rationale (full fit breakdown retires here), rendered as underline tabs. *Exists because:* it's the working progressive disclosure the page already has, and its strings are test-asserted.
6. **Record footer (one quiet zone)** — strategic-override callout on top (it's a decision input), then: original post + KV table + fit summary; win/loss outcome value + Save; `<details>` "Correct the record" holding the status-jump grid; Notes; **Strategic value** bars with the recompute form inside a `<details>`. *Exists because:* provenance and bookkeeping are consulted, never monitored — the page ends with a ledger, not another cockpit.

## Deleted (item — why — where its data went)

- **3 of 5 status pills (action / confidence / strategic)** — five vocabularies = anxiety, each duplicates another surface — action→NEXT card, confidence→fit chip tooltip, strategic→Strategic value card (test strings at test_web.py:193/667 satisfied there).
- **Big "93% qualification fit" hero number** — a triage-time trophy outweighing the NEXT card — becomes a small header chip; full breakdown lives in Qualification rationale tab.
- **The 6-button CTA row as a row** — six equals is the page refusing an opinion — 2 permanent buttons stay in header; the other 4 move into the `⋯ Actions` `<details>` (strings stay in DOM).
- **"📋 Original post ↗" head button** — exact duplicate — the record footer's original-post link is the sole source (test_signals.py:214 satisfied).
- **Standalone "Open project" action bar (detail.html:403-407)** — duplicates the win/loss card button and the won-state NEXT slot — NEXT owns it; no test asserts the bar.
- **Contact card as a card** — furniture around three links — data becomes the header contact line; empty state is one muted sentence.
- **Status-jump pill grid as a visible control** — third writer of one state — buried in "Correct the record" `<details>` in the footer; POST /status route untouched.
- **Emoji button iconography + extra `live-dot`s / `btn-live` styling everywhere except NEXT** — three embers is zero embers — text-only 13px/600 buttons.
- **Both inline `<style>` blocks in detail.html (~90 lines)** — moved to the shared stylesheet; zero test risk (assertions hit class names in HTML).

## Merged (items → into)

- Discovery requests + Times offered + Upcoming Discovery → **one Discovery cluster** (zone 3), each sub-block's conditional guard and heading kept verbatim.
- Stepper + "Mark delivery doc sent" + win/loss current-status line → **the state rail** (zone 3), doc-sent as a milestone tick.
- Contact card + identity-edit → **header** (contact line + existing disclosure).
- 6-button CTA row → **NEXT primary button + header pair + `⋯ Actions` overflow**.
- Campaign Intake box → **CI panel's collapsed prompt row** (auto-open when record empty).
- Opportunity card (post + KV + fit summary) + Win/loss outcome + Notes + Strategic value card + status-jump escape hatch → **Record footer** (zone 6).
- "Open project" + "Start production" → **NEXT card's action slot** at the appropriate lifecycle states.

## Became automation (item — trigger)

- **Stage advance (event stages)** — proposal-release, client-approval (the ONE approval → Won), discovery-booked, start-production routes each write the stage forward if current stage is earlier (one-line per handler). Manual advance survives only for fuzzy stages ("Reaching out") + the buried Correct-the-record drawer. Full derived-stage engine is a weekend project, **not tonight** — stored column stays.
- **delivery_doc_sent_at** — stamped in the same transaction as the actual mailer/share send; the manual button remains for out-of-band sends (test_web.py:935 requires it when unsent).
- **Strategic value recompute** — fires inside the CI-update route (deterministic, milliseconds); form demoted into a `<details>`, quiet "recomputed just now" timestamp on the bars.
- **Outcome value prefill** — on Won, pre-fill from the approved commercial total (fallback: estimation midpoint); editable, never blank.
- **Head/NEXT primary button** — rendered from the existing `next_act` compute via one shared Jinja macro; every POST route on the page recomputes `next_act` before redirect so the card never lags its own action.
- **CI blocking gap → NEXT** — when court=you and CI has a lifecycle-blocking gap, the gap becomes the proposed action ("Ask about budget"); passive gaps stay in the panel.
- **Enter key** — when court=you, one live.js keydown submits the NEXT action.

## Motion spec (max 8 rules)

1. **NEXT `live-dot`** / court=you / slow pulse / "the ball is in your court" — the page's ONLY pulsing element.
2. **NEXT left rule** / age crosses 3d then 7d with court=you / border saturates (color step, no animation) / "this is going stale."
3. **NEXT since-age** / page open / live.js ticks the relative age / "time is passing on your move."
4. **Court=client/scheduled states** / render / static calm green/grey, zero motion / "nothing for you here — relax."
5. **CI "Analyze & update"** / real POST in flight only / existing lv-thinking state / "the machine is actually working."
6. **Stage rail dot** / event-driven advance since last visit / one-time 150ms fill on render, then static / "the system moved this itself."
7. **All `<details>` disclosures** / toggle / 120ms ease on content, nothing else / "more exists; it was hidden on purpose."
8. **Strategic bars timestamp** / auto-recompute / text swap only ("recomputed just now"), no bar animation / "this is current without you asking."

## Major disagreements (each: who vs who, the argument, the ruling, why)

1. **Kill all manual stage controls tonight (Critics 2/3/4/7) vs demote-first (Critic 8).** Argument: derived stage is the honest law vs POST /status is directly test-exercised and downstream queries filter the stored column. **Ruling: Critic 8 wins on scope, Critics 2–4 win on direction** — event hooks auto-write the stored stage tonight; controls demote (ghost advance + buried jump drawer); full derivation is next weekend. A one-night rewrite that breaks the status route would fail the "1000 tests green" constraint.
2. **Campaign Intelligence: keep large and open (Critic 4) vs collapse to producer's read (Critics 1/5/6).** **Ruling: split it by decision-weight (Critics 3/8's framing wins)** — conflicts, gaps, producer's read stay visible (they demand disposal); confirmed facts fold per-section. Critic 4 is right that the moat must not hide; Critics 1/5/6 are right that a facet dump isn't intelligence. Both are satisfied by folding only what needs no decision.
3. **Fit % number: keep as head anchor (Critic 8, alone) vs demote (everyone else).** **Ruling: demote to a chip.** Seven experts independently called it a past-tense trophy; Critic 8's defense ("glanceable is-this-real signal") is served by the chip. The emotional headline belongs to court+age (Critic 5's point is decisive: a big green 93 lies about a deal dying of silence).
4. **Discovery detail folded into the NEXT zone (Critic 1) vs its own conditional cluster (Critics 2/3/5/6/7).** **Ruling: own cluster.** The negative test assertion (Upcoming Discovery absent without a meeting) makes per-block conditionality load-bearing; and NEXT must stay one sentence + one button — a scheduled call sets NEXT's court to "ON THE CALENDAR," the detail lives one zone down.
5. **Cockpit mode / dim-the-page-and-jump-queue (Critics 1 & 6 risky ideas) vs full visible panel.** **Ruling: rejected for tonight.** The reordered hierarchy already delivers the 4-second court check without hiding data or new routes; deliberate page-dimming is a philosophy change to demo after the restructure proves itself. (The Enter-binding from Critic 6 is adopted — it's five lines.)
6. **Reference material into tabs (Critics 4/6) vs an on-page record footer (Critic 8, Critic 1 partially).** **Ruling: footer.** Same visual outcome (below everything actionable), zero risk to tab templates and the many strings asserted on the main page response; moving content between templates at 2am is how strings get lost.
7. **Which two pills survive: stage+court (1) vs status+tier (3) vs tier+strategic (4).** **Ruling: stage + tier.** Court is already the NEXT card's badge (duplicating it recreates the disease); strategic renders in the footer card; stage as a pill is redundant with the rail but cheap insurance and reads instantly.

## Implementation notes for tonight (Jinja/CSS-level, test-safe)

**Strings that MUST survive in the page response, verbatim** (all httpx text-substring assertions — `<details>` content counts, visibility doesn't): `Create discovery call` (test_meeting_proposals.py:229), `Commercial Review` (test_commercial.py:141), `Campaign Brief` (test_discovery_meetings.py:73, test_workspace.py:104), `Campaign Intelligence` + `Analyze &amp; update` (test_intake_opportunity.py:148), `stage-stepper` as a class attr (test_web.py:927), `Mark delivery doc sent` when unsent (test_web.py:935 — keep the sent-state variant too), `Upcoming Discovery` only-with-meeting (test_discovery_meetings.py:77/90/95 — keep each discovery sub-block's `{% if %}` guard exactly), `Strategic value` (test_web.py:193/667), `Original post` (test_signals.py:214 — satisfied by the record-footer link after deleting the head button), `/capabilities` href present.

**Template moves (detail.html, block reorder only — no route changes):**
- Extract a `{% macro next_action_button(next_act) %}` from lines 133–140; use it in NEXT and nowhere else (header primary = the two permanent buttons, not a third copy of the action).
- Move the NEXT section block (122–144) above the stepper block (77); move Contact card contents (55–74) into the head as a `<div class="contact-line">`; wrap the old CTA buttons (except Client workspace, Campaign Brief) in `<details class="overflow"><summary>⋯ Actions</summary>…</details>`.
- Wrap the three discovery blocks (146–228) in one `<section class="card" id="discovery">`, guards untouched.
- Wrap the status-jump grid (456–459) in `<details><summary>Correct the record</summary>…</details>`; wrap the strategic recompute form and CI confirmed-facet sections in `<details>` likewise; intake form gets `<details {% if not ci_fields %}open{% endif %}>`.
- Delete: head Original-post button (line 37), Open-project bar (403–407), strat pill (line 11), action+confidence pills, both inline `<style>` blocks (→ shared stylesheet).

**Route-side (small, additive):** stage-forward one-liners in the proposal-release / approval / booking handlers (guard: only advance, never regress); `delivery_doc_sent_at` stamp in the doc-send path **only if** sends funnel through one choke point in mailer.py — grep first, defer if not; strategic recompute call in the CI-update handler; outcome prefill in the /status Won branch; recompute `next_act` before redirect on this page's POSTs.

**CSS (dissolve boxes, don't delete elements):** header and stage rail lose `.card` chrome (background/border/shadow → transparent, hairline `#efe9e0` dividers); `.cols-2` in the footer may stay inside the record zone (Critic 8) but the zone gets one shared muted register (13px, reduced contrast); NEXT keeps its 4px court-colored left rule and is the only element allowed `btn-live`/`live-dot`; tabs restyled to underline (2px ember active); emoji stripped from button labels — check no test asserts an emoji-containing string before removing.

**Do NOT touch tonight:** POST /status semantics, tab templates, next_action compute (test_next_action.py pins it), any workspace/portal template. Run `python -m pytest tests/ -q` after the reorder and again after route hooks; if the mailer choke-point check fails, ship the doc-sent stamp as a follow-up.

---

## Critique loop 2 (fresh eyes, post-implementation)

A combined first-time-user + Apple-critic pass over the implemented page returned five
findings; disposition:
1. Literal `\n` rendering on the page — **fixed** (template artifact from the restructure).
2. The ONE-primary law broken by four ember-filled controls — **fixed**: the accent fill is
   reserved for the NEXT action; the CI panel's Analyze/Confirm buttons are outline-weight now.
3. "Mark delivery doc sent" offered at stage New — **fixed**: gated to Proposal-out/Won.
4. Status told twice (hero pill + rail) — **fixed**: the rail owns stage; hero keeps tier + fit.
5. Open intake double-prompting — **fixed**: the summary dims to 45% when open.
Loop 3 was a visual re-verification of the fixes; no meaningful simplification remained at
the CSS/Jinja altitude — deeper ones (derived stage engine, CI-gap→NEXT feeding) are recorded
above as the deferred backlog.
