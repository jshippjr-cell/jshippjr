# ChordOS Translation — Applying the pacomepertant.com UX System to Chordential

> **Companion to** `ux-teardown-pacomepertant.md` (the forensic analysis; all measured
> values cited here come from it) and `ux-build-spec.md` (the engineer-ready spec).
>
> **Ground rules honored throughout:**
> - **No redesign.** Chordential keeps its identity: warm light theme (`--cream #FCF7F8`
>   background, white cards, warm hairlines), ink `#1F1E1E`, wine `#44161E`, orange
>   `#E4671F`, the existing sidebar IA, the existing screens. Everything below is a
>   *refinement layer* on what exists.
> - **Translate the grammar, not the costume.** The portfolio's dark stage, WebGL spiral,
>   and audio are *its* brand. What transfers is the underlying system: the tempo
>   hierarchy, the spring, attention-by-subtraction, thresholds, representation switches,
>   designed exits, sticker annotations, one-primary-per-screen.
> - **ChordOS constraints respected:** server-rendered Jinja + vanilla JS + one
>   `style.css` (no Vue/GSAP/WebGL rewrite); "the machine proposes, Jon disposes"; the
>   honesty rule; provenance everywhere.

---

## 0. What transfers and what doesn't (the honest filter)

| From the teardown | Verdict for ChordOS |
|---|---|
| Tempo hierarchy (micro 0.15s → reaction 0.25s → transition 0.4s → panel 0.6s) | **Adopt wholesale.** Chordential today has one speed (0.12s) — functional, but nothing "arrives." |
| One spring curve as the product's physical material | **Adopt** — as CSS `linear()` token, used for panels/drawers/reveals only. |
| Physical↔spring / optical↔ease split | **Adopt** as a hard rule in style.css. |
| Attention by subtraction (dim siblings, don't decorate the target) | **Adopt** — lanes, queues, lists, tables. |
| One primary pill per screen + orbiting-dot affordance | **Adapt** — Chordential keeps its button shapes; the *discipline* (one visually-loudest action per screen) and a subtle dot/pulse affordance on THE action transfer. |
| Threshold/entry moment that guarantees readiness | **Adapt** for client-facing surfaces (Brief, portals) — not for the operator console (Jon enters 40×/day; gates would infuriate). |
| Same data, two representations, one switch | **Adopt** — pipeline (board/list), roster (cards/table), workspace (timeline/checklist). |
| Designed exits + "next up" momentum | **Adopt** — every module gets an explicit "what happens next" tail. |
| Sticker tags (rotated pills, one accent) | **Adapt** — as flat (unrotated in operator UI, 1–2° only on client docs) status pills; orange stays THE accent and gets *scarcer*, hence louder. |
| Chrome whispers lowercase / content speaks | **Adapt** — keep Chordential's casing, but adopt the *size/value contract*: chrome small + muted, content large + ink; kill mid-size mumbling. |
| Sound design | **Do not adopt** (a procurement console that clicks and whooshes undermines trust). One exception noted in §9 (Review Queue confirm — optional, off by default). |
| Dark stage, WebGL, spiral, cursor trails, letter-jiggle | **Do not adopt.** Wrong genre. The *lerped-following* and *elastic pop* ideas survive in tiny doses (drag ghosts, tooltip pops). |
| Entry gate with sound choice | **Do not adopt** anywhere operator-facing. |

The unifying translation: the portfolio makes *browsing feel like being somewhere*.
ChordOS should make *operating feel like being in control* — same means (tempo, physics,
subtraction, designed exits), opposite temperament (calm, luminous, precise).

---

## 1. The shared refinement layer (applies to every module below)

These six upgrades to `style.css` + a ~60-line `ui.js` give every screen the teardown's
feel without touching any template's structure (full specs in `ux-build-spec.md`):

1. **Motion tokens.** `--ease-spring` (the sampled `linear()` curve, toned to ~1% overshoot),
   `--ease-out` `cubic-bezier(.19,1,.22,1)`, durations `--t-micro .15s / --t-react .25s /
   --t-move .4s / --t-panel .6s`. Replace the eight ad-hoc `0.12s` transitions.
2. **Enter animations for content, not chrome.** Cards/rows/KPIs rise 8–12px + fade on
   load, staggered 40ms, capped total 300ms (IntersectionObserver, `once`). Chrome
   (sidebar, topbar) never animates on load — it was "always there."
3. **Attention by subtraction.** `.list-hover-dim` utility: hovering a row/card dims
   siblings to 0.55 (0.25s ease) instead of decorating the hovered one. Focus mode for
   tables, lanes, queues.
4. **Leave < enter, everywhere.** Dismissals/collapses at 0.6× the entrance duration.
5. **The dot affordance.** THE primary action of each screen gets `.btn-live`: Chordential
   orange fill + a 6px dot that breathes (opacity 0.5→1, 2s loop) — quiet kin of the
   portfolio's orbiting dot; on hover the dot slides right 2px (spring).
6. **Panel physics.** Anything that slides in (drawers, mobile sidebar, modals, the brief
   preview) uses `--t-panel` + spring; backdrop = ink-at-40% scrim + `backdrop-filter:
   blur(6px)` (the teardown's blur-not-shadow elevation, tuned way down for a light theme).

Plus one **global type contract** (teardown §7): every screen has exactly three text
roles — display (page/entity title, 22–28px, weight 700+, tracking −0.4px), body
(13.5–15px), chrome (11–12px, muted, uppercase-or-small per current Chordential style).
Anything currently 16–18px "neither title nor body" gets promoted or demoted.

---

## 2. Pattern → module map (the complete grid)

| Teardown pattern | Where it lands in ChordOS |
|---|---|
| Entry threshold / readiness gate | Campaign Brief (client open moment), Delivery Portal, First-touch page |
| Spiral↔list representation switch | Pipeline lanes↔table; Workspace timeline↔checklist; Roster cards↔table |
| Sibling-dimming hover | Pipeline cards, Review Queue items, CI field list, roster, all tables |
| Cursor/preview-on-hover (adapted: hover peek) | Buyer Graph nodes, Pipeline cards → mini CI summary popover |
| Menu overlay (state kept behind, dim+blur) | Right-hand action drawers: "Schedule discovery," "Compose outreach," Review side-panel |
| Pill + orbiting dot (primary discipline) | One `.btn-live` per screen: Qualify / Send / Approve / Release / Schedule |
| Sticker tags | Status/provenance pills: `human-confirmed`, `machine-proposed`, `needs review`, `conflict`; "NEXT STEP" on the Brief (already exists — gets the sticker treatment) |
| Next-up momentum tail | Review Queue auto-advance; Opportunity "next best action" footer; Debrief → "apply to next campaign"; Delivery stage → next agent |
| Framed media mat (rounded, inset hero) | Brief cover block; Proposal header; Delivery package cover; Evidence transcript panel |
| Scroll-read (scrub) intro | Client-facing Brief/Proposal only: sections fade-up on scroll (triggered once — not scrubbed; scrub is too theatrical for documents) |
| Loader with eased progress | Anywhere ChordOS computes: "Analyzing transcript…" on intake — eased progress bar, never a spinner |
| Escape closes / exits always top-right | All drawers/modals sitewide (consistency contract) |
| Circular text / rotated object CTA | **Not adopted** (wrong temperament) — closest kin: the Brief's floating "Request a Discovery Call" pill stays fixed-visible at document end |
| 404-deep-link flaw (their mistake) | **Inverse lesson:** every ChordOS entity keeps a stable, shareable, token-gated URL. Already true — keep it sacred. |
| No-reduced-motion flaw (their mistake) | ChordOS ships `prefers-reduced-motion` support from day one (build spec §7). |
| Hidden-but-tabbable menu links (their mistake) | Drawers get `inert`/`visibility:hidden` when closed; visible focus rings sitewide. |

---

## 3. Module-by-module

Each section: what the module is *for*, which patterns apply, and concretely what changes
on the existing screen. No new pages are proposed anywhere.

### 3.1 Campaign Intelligence (the heart — `detail.html` CI panel, `evidence.html`)
*Job: one living, provenanced record; machine proposes, Jon disposes.*

- **Attention by subtraction for review states.** When any field is `needs_review` or
  `conflict`, confirmed fields dim to 0.55 and the pending ones stay full-ink. Jon's eye
  lands on what needs him without a single red banner. (Teardown 4.4 — the list-row dim.)
- **Provenance stickers.** Each CI field's source becomes a small pill on the field row:
  sand pill `machine · transcript 07-02`, white pill `you · edited`, wine-text pill
  `conflict`. One color rule: **orange appears only on the single next action**, never on
  status. (Teardown 4.9 — stickers carry metadata; accent stays scarce.)
- **Field-confirm micro-moment.** Confirming a proposed field: the row's pill flips
  (0.25s), the row settles with a 1%-overshoot spring nudge (2px), then *dims itself* as
  it joins the confirmed majority. Feedback in <100ms, embellishment after (teardown §5).
- **"Why did this change?" as hover peek.** The provenance popover (source, confidence,
  timestamp, history) opens on hover/focus of the pill with the elastic pop
  (`scale .92→1`, 0.3s spring), leaves in 0.15s. The portfolio's tooltip contract:
  identifies, never acts (teardown 4.11).
- **Analyzing = eased progress.** When intake runs, the CI panel header shows a hairline
  progress bar whose value eases toward target (2%/frame, the loader trick) — organic,
  honest, no spinner. On completion: the *new* proposed rows enter with the 40ms stagger.
- **Evidence Viewer as the mat.** The raw transcript panel gets the framed-artifact
  treatment: rounded-`--radius` panel inset on the sand `--panel` background, extraction
  list beside it. Raw evidence *looks* preserved — framed like the case-page hero
  (teardown §9, case page).

### 3.2 Opportunity (`detail.html` — the hub)
*Job: the "one room" where a pursuit lives; everything else is an arrangement of it.*

- **Adopt the hub-and-overlay model explicitly** (teardown §3): the Opportunity page is
  the room; Schedule Discovery, Compose, Update Intelligence become right-side **drawers**
  (width = existing content column; spring open 0.6s; scrim + 6px blur behind; Escape
  closes; ✕ top-right). Jon never loses the page state he was reading. Currently these
  are separate pages/inline forms — the *routes stay* (server-rendered fallback), the
  drawer is progressive enhancement fetching the same partial.
- **Five fixed anchors** (teardown §3, chrome corners): title + stage top-left; **one**
  `.btn-live` top-right (the stage's next action: Qualify → Schedule → Send Brief → Won);
  Campaign Brief button stays upper-right adjacent (already placed there — keep);
  activity/provenance feed bottom; sub-nav constant. Same anchors on every opportunity,
  spatial memory does the wayfinding.
- **Next-best-action tail.** Page footer: a quiet full-width block — "next up… Schedule
  the discovery call" with the one orange pill. Momentum designed in (teardown case-page
  footer): an Opportunity never dead-ends.
- **Hover peek on related entities.** Buyer name, meetings, proposals get the 0.3s-pop
  peek card (mini summary + status pills) — preview without navigation, the cursor-trail
  idea at 5% intensity.

### 3.3 Proposal (`proposal_detail.html`)
*Job: a document that closes; client-facing = the temperament changes to "presented."*

- **The mat.** Proposal preview renders as the framed artifact: white page on `--panel`
  sand field, `--radius` corners, generous grid margin — matted like the case hero. The
  operator editing chrome sits *outside* the mat; inside the frame is exactly what the
  client sees (honesty made visual).
- **Sections enter once** on scroll (fade-up 12px, 0.4s, `once`) in the client view —
  the scroll-read idea at document temperature. No scrubbing, no theatrics.
- **One primary per state:** Draft → `Send proposal` is the only orange object; once sent
  → `Mark accepted` takes the orange and Send *demotes to text* (the portfolio's rule:
  primary is a role, not a style that accumulates).
- **Sticker for terms status:** `draft` (sand), `sent` (slate), `accepted` (wine),
  positioned top-right of the mat like the case page's corner tags.

### 3.4 Campaign Workspace (`campaign_home.html`)
*Job: the one room per campaign after Won — same CI, new arrangement.*

- **Representation switch, center-top** (teardown 4.3): `timeline ● checklist` — two
  views over the same campaign state, one click apart, state persisted per campaign
  (localStorage). Switch transition: leave 0.25s down-fade, enter 0.4s rise with 40ms
  stagger — the measured list↔spiral contract, de-theatricalized.
- **Inherited-CI banner as provenance, not decoration:** a hairline block "Intelligence
  inherited from pursuit · nothing recreated" with the `you/machine` pill counts —
  reinforcing the Constitution in the UI.
- **Ambient status without a marquee:** the portfolio's 40s marquee becomes a **static**
  quiet status line that *changes with a 0.4s crossfade* when state changes (deliverable
  approved, revision requested). Movement only at moments of meaning.

### 3.5 Agency Intelligence (`agencies.html`, `agency_detail.html`, buyer graph)
*Job: the relationship memory — browsing should feel like recall, not querying.*

- **Cards↔table switch** for the agency list (same pattern as 3.4).
- **Sibling-dim on the graph:** hovering a buyer node dims unrelated nodes/edges to 0.3
  (0.25s) — the single highest-value place for attention-by-subtraction in all of
  ChordOS, because graphs are where attention drowns.
- **Hover peek chips** on nodes: white rounded chip (thumb/initial + name + last-touch
  pill), elastic pop in, 0.15s out — verbatim the spiral tooltip contract (identify,
  never act; click acts).

### 3.6 Delivery (`delivery_console.html`, `delivery_portal.html`, `delivery_package.html`)
*Job: five agents, staged flow, client-visible endgame.*

- **Console = lanes with designed momentum.** Each stage column footer shows "next:
  Metadata review" — the next-up tail per column. Completing a stage: the card leaves
  *down* (0.25s) and arrives in the next column rising (0.4s) — physical continuity for
  state changes (never teleport a card).
- **Portal (client-facing) gets the threshold** (teardown §1): token link opens on a calm
  cover — campaign name, "prepared by Chordential," one pill `View your delivery •` —
   while package assets preload behind it. Client never sees a half-loaded page; readiness
  is guaranteed before entry, exactly the loader's contract (and it costs one click, which
  a *client* pays happily — unlike Jon).
- **Package = the mat, chaptered.** Each deliverable framed on the sand field; approvals
  render as stickers (`approved · Sarah · Jul 2` in wine on white); the ✕/exit and the
  "next deliverable" tail follow the case-page grammar.

### 3.7 Producer Debrief (debrief intake lane)
*Job: the learning loop — insights, never facts (ADR: stance guard).*

- **The reading-pace idea, inverted for writing:** the debrief form is one large calm
  text surface (display-size prompt "What happened?", body-size textarea, zero chrome) —
  the about-page's one-object-of-attention applied to input. Submitting runs the eased
  "Analyzing…" bar, then proposed insights stagger in as pills-on-rows for confirmation.
- **Insight cards carry the stance visually:** `insight` / `recommendation` /
  `open question` as sand/slate/wine pill variants — never the same pill as facts
  (the never-launder-inference rule made visible; teardown lesson: distinct things get
  distinct components, not distinct colors of the same component).
- **Momentum tail:** after confirm — "applied to Campaign Intelligence → next up…
  2 open questions for the next call" linking to CI. The debrief never ends in a void.

### 3.8 Review Queue (`inbound_queue.html`, `incoming.html`, review batches)
*Job: Jon's decision treadmill — throughput with judgment.*

- **One item, one decision, auto-advance.** The queue adopts next-up as its *core
  mechanic*: confirming/dismissing an item slides it out (0.25s), the next rises in
  (0.4s), counter ticks. The portfolio's circular browsing, re-purposed as flow-state
  triage.
- **Sibling-dim IS the queue:** the active item full-ink at center; the upcoming 2–3
  visible below at 0.55/0.4/0.25 opacity — a literal focus stack (spiral depth-of-field,
  zero WebGL).
- **Batch review ("review this call's updates"):** grouped diff enters with the 40ms
  stagger; `Confirm all` is the one orange pill; per-row overrides are text-buttons.
  Optional, off-by-default: a single soft confirm tick sound for batch-confirm — the one
  place sound might earn a seat (Jon processing 30 items by keyboard). Honest default: off.
- **Keyboard-first** (their flaw, our fix): visible focus ring (2px orange offset 2px),
  j/k advance, enter confirm — with the same motion grammar bound to keys as to clicks.

### 3.9 Meeting Scheduler (`discovery_schedule.html`, `discovery_request.html`, `meeting_manage.html`)
*Job: two initiators, one engine; client side must feel effortless, operator side fast.*

- **Client request page = threshold temperament:** calm centered column on cream, display
  greeting ("Let's find a time"), the 3 fields, one pill `Request the call •`. The done
  state mirrors the portfolio's exit design: confirmation + "what happens next" (Jon
  reviews → you get an invite) — no dead end, expectations set (teardown §9 contact
  reasoning: forms only where they earn it — this one earns it).
- **Operator form keeps density** (no threshold, no theatrics) but gets: drawer
  presentation from the Opportunity (3.2), integration chips as provenance pills (already
  built — restyle to the pill grammar), and the confirm moment: on schedule, the drawer
  closes 0.35s and the new Upcoming Discovery panel *arrives* in the page with the spring
  rise — the state change is witnessed, not discovered on reload.
- **Manage page (client, token-gated):** same threshold temperament; reschedule/cancel as
  text-secondary under one pill; Escape/✕ consistency.

### 3.10 Campaign Brief (`capabilities_doc.html` — the client-facing artifact)
*Job: the one artifact a buyer reads; conversion surface for discovery.*

**This is where the teardown pays off most — the Brief is Chordential's "portfolio":**

- **Cover as threshold.** The token link opens on a cover viewport: buyer name small
  (chrome), campaign need as display type on cream, "prepared by Chordential" + date as
  stickers, one hint "scroll" — assets preloaded behind it. First impression = attended-to,
  not "a web page loaded." (Entry gate, minus the gate: scrolling is the consent.)
- **Sections enter once on scroll** (fade-up, stagger inside each section ≤300ms):
  the *reading* is paced like the about page, at document temperament.
- **The mat for evidence:** capability proof blocks / reel links framed as artifacts
  (rounded, inset on sand), never inline-loose.
- **Display/chrome contract hard-applied:** section titles display-size ink; running text
  body; meta (dates, scope pills) chrome — the 4:1 ratio that makes documents feel
  designed (teardown §7).
- **The tail is the conversion:** the existing end-of-brief "NEXT STEP — Request a
  Discovery Call" block adopts the full pattern: sand field, sticker header `NEXT STEP`,
  one orange pill with the breathing dot, sub-text "no scheduling back-and-forth — you
  ask, Jon confirms." The portfolio funnels to the next case; the Brief funnels to the
  call. Same grammar, ChordOS's one true CTA.
- **Never**: sound, dark theme, letter-jiggle, cursor trails. The Brief's premium is
  *calm print* — the teardown's discipline (one accent, tempo, framing), not its costume.

---

## 4. What this buys, in one sentence per stakeholder
- **For Jon:** every screen tells him the one thing to do next, state changes are
  witnessed instead of discovered, and triage becomes flow.
- **For clients:** every touchpoint (brief, request, portal) feels attended-to and
  finished — the interface is evidence of how the studio operates.
- **For the codebase:** one token block + one small JS file, no framework, no redesign —
  the exact seam philosophy (null-by-default, progressive enhancement) ChordOS already
  practices.

→ Implementation details, exact values, and acceptance criteria: `ux-build-spec.md`.
