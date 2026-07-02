# Chordential Platform Website Plan — Three Mechanisms in One

*Research + build plan, July 2026. Companion to `company-strategy.md` and `product-roadmap.md`.
This is the presentation-layer plan for the platform: **Frame.io meets Salesforce** — the
operating system through which agencies manage the music function of campaigns.*

---

## Part 1 — Design research: what makes the top sites stand out

Research base: commercial music houses (Barking Owl, Butter Music & Sound, Squeak E. Clean
Studios, Human Worldwide, Mophonics, MassiveMusic), creative-tool brands (Frame.io,
Teenage Engineering, Ableton, Splice), and the current best-in-class B2B SaaS design
languages (Linear, Attio). Sources listed at the end.

### 1.1 Typography — one confident voice, not a font menu

- **Frame.io** commissioned *Frame Gothic* with Monotype — a modernist, variable-weight
  sans in eight weights ("quirky without trying too hard, but also sophisticated"). The
  lesson isn't "buy a custom font"; it's that the whole brand hangs on **one expressive
  sans used at every weight**, from thin display headlines to UI labels.
- **Ableton** uses **Futura (ParaType)** everywhere — a 1927 geometric sans that reads
  as fresh because it's paired with adventurous flat color. One typeface, decades of
  mileage.
- **Teenage Engineering** uses **monospace only**. It communicates precision and
  "technical honesty without any supporting narrative." Spec tables set in monospace with
  1px-gap grids read as *engineering documentation, not marketing* — which **increases
  trust**.
- **Linear** pairs **Inter Display for headings** (expression) with regular Inter for
  body (readability) — two optical sizes of one family, not two fonts.

**Takeaway for Chordential:** keep the existing serif/display voice for the
front-of-house (the "studio" feel), and adopt a **single precise sans + monospace for
data** inside the platform. Monospace for evidence, IDs, timestamps, cue-sheet data —
the Teenage Engineering trick — makes intelligence output feel like instrumentation,
not copywriting. That *is* the honesty rule, typographically.

### 1.2 Color — dark room + one hot accent

- **Frame.io's** palette (Cobalt, White, Electric teal, Iris purple, Coral) is derived
  *from the product UI*, combined into gradients that "feel cinematic… vibrant, bright,
  and in contrast to the dark aesthetic of a filmic workspace." Their stated ambience:
  **"a windowless edit bay or darkened soundstage, where the walls are awash with the
  hues of the film."** That's the exact emotional register for a music platform: the
  studio control room.
- **Linear**: sophisticated dark surface system — calibrated neutral grays for hierarchy,
  high-contrast text, gradients used as "faux detail" (dimension without clutter),
  restrained elegant motion. Never pure black (industry practice: `#121212`-ish bases).
- **Attio**: disciplined monochrome with **subtle per-section pastel accents** — the
  accent color quietly tells you which part of the product you're in.
- Music-site trend consensus: **dark themes with vibrant pops of accent** create striking
  contrast and make interactive elements unmistakable; minimal palettes keep the work
  center-stage.

**Takeaway:** Chordential already has a strong palette (cream `#FCF7F8`, sand `#D8CDB6`,
olive `#737469`, slate `#546671`, ink `#1F1E1E`, wine `#44161E`, orange `#E4671F`).
The plan is **two moods from one palette**: front-of-house stays cream/daylight (the
procurement-grade studio); the *platform* inverts to an ink-based "control room" dark
theme where wine and orange become the glowing accents — Frame.io's edit-bay ambience
achieved with our own colors, and Attio's trick of per-mechanism accent (Intelligence =
slate, Relationships = wine, Delivery = orange).

### 1.3 Motion — small, purposeful, never decorative

- **Linear**'s praised motion is *small elegant motion* — micro-transitions that make
  software feel "professional and severe," never parallax carnival.
- **Attio**'s hover micro-interactions on bento cards are called some of the most refined
  in B2B; their hero is a **live product demo** (a real query executing), not an
  animation *about* the product.
- Music-site consensus: smooth transitions, hover, scroll-reveal — enhancing without
  overwhelming.

**Takeaway:** three motion signatures, used everywhere and nowhere else:
1. **The pulse** — audio-reactive/waveform-derived motion on anything playable.
2. **The reveal** — 150–250ms fade/rise on cards and evidence as they enter.
3. **The live demo** — the marketing site's hero shows the *actual product* answering an
   actual question ("Why is today the best day to contact this agency?"), Attio-style.

### 1.4 Audio & reel presentation — sound within one click, always

- Music houses (Barking Owl, Butter, Squeak E. Clean, Human) converge on: **full-bleed
  showreel or work grid straight from the homepage**, minimal chrome, sound one click
  away at all times. Human's positioning line — bridging "the divide between seeing and
  feeling" — is delivered by the site *demonstrating* it, not claiming it.
- The standard interaction grammar for pro audio on the web is the **clickable waveform**
  (wavesurfer.js v7: canvas rendering, pre-decoded peaks for large files, regions/
  timeline/hover plugins). SoundCloud made the waveform-as-scrubber a universal literacy.
- Frame.io's core review pattern: media plus **frame-accurate (for us: timecode-accurate)
  comments** anchored to the timeline.

**Takeaway:** one shared `<cue-player>` component across the whole platform — waveform,
click-to-seek, version label, rights badge — used identically on the public reel, the
review portal, and the delivery console. Timecoded comments on the waveform is the
"Frame.io for music" mechanic and the single highest-leverage feature in the whole plan.

### 1.5 Credibility for agency buyers — proof, not adjectives

- Music houses lead with **client/brand logos, awards, offices** ("New York, Chicago,
  Los Angeles" does real work — it says *scale and coverage*).
- Teenage Engineering earns trust with **spec-sheet honesty** — dense factual grids.
- Attio reads "serious software" by *restraint*: no aggressive CTAs, no feature dumping,
  typography-led.
- For Chordential the honesty rule constrains us: **no fake client logos, ever.** Our
  credibility equivalents are (a) the *live instrument panel* — real counts from the
  real database (agencies profiled, signals detected this week, cues delivered), (b) the
  procurement-grade artifacts themselves (a real cue sheet, a real rights summary,
  redacted), and (c) demo-brand case studies clearly labeled as demos (AURORA, Vance
  Athletic).

---

## Part 2 — The design language (decisions)

| Token | Front-of-house (daylight) | Platform (control room) |
|---|---|---|
| Surface | cream `#FCF7F8` | ink `#1F1E1E` base, elevated surfaces +4/+8% lightness |
| Text | ink | cream at 92% opacity; olive for secondary |
| Borders | sand | sand at 18% opacity (hairlines, 1px) |
| Accent — Intelligence | slate | slate, brightened for dark |
| Accent — Relationships | wine | wine, brightened for dark |
| Accent — Delivery/action | orange | orange (primary CTA everywhere) |
| Display type | existing serif voice | same serif, headings only |
| UI type | precise sans (system stack or Inter) | same |
| Data/evidence type | — | **monospace** (timestamps, IDs, cue data, signal evidence) |

Rules:
- Gradients only as **wine→orange "studio glow"** on hero surfaces and section headers —
  Frame.io's cinematic warmth, our colors. Never on data surfaces.
- Motion budget: 150–250ms ease-out for reveals; waveform pulse on playables; zero
  scroll-jacking. Respect `prefers-reduced-motion`.
- Every number shown on marketing surfaces is **live from the DB** or clearly labeled
  demo. (The seed/demo gating already exists: `CHORDENTIAL_SEED_DEMO`.)

---

## Part 3 — Three mechanisms, one platform

The site is one product with three faces, sharing one design system and one database:

```
┌────────────────────────────────────────────────────────────┐
│  FRONT OF HOUSE  (public.py — daylight theme)              │
│  The promise: "We remove the work of managing music        │
│  so agencies can stay focused on managing the campaign."   │
└──────────────┬─────────────────────────────────────────────┘
               │
┌──────────────▼───────────────┐  ┌──────────────────────────┐
│ MECHANISM 1 · INTELLIGENCE   │  │ MECHANISM 2 · RELATIONSHIP│
│ (Salesforce half — internal) │  │ (internal + email surface)│
│ Discover → Understand →      │  │ Memory → Strategy →       │
│ Detect → Reason              │  │ Content → Continuity      │
└──────────────┬───────────────┘  └────────────┬─────────────┘
               └──────────────┬────────────────┘
                              ▼
               ┌──────────────────────────────┐
               │ MECHANISM 3 · DELIVERY       │
               │ (Frame.io half — client-facing│
               │  token-gated portals)        │
               │ Produce → Review → Ship      │
               └──────────────────────────────┘
```

Much of the machinery already exists in this repo. This plan is the **experience layer**
that unifies it. Per element below: *what it is → key screens → design patterns from
research → what exists → what to build.*

---

### Element 1 — Agency Intelligence Platform
*"Who are they?" — living profiles of agencies, branding firms, experiential shops,
production companies, creative consultancies.*

**Exists:** `agencies` table + directory crawlers (`directory_crawl.py`,
`directory_parsers.py`), enrichment engine (`enrichment.py` — micro-agents for services,
industries, offices, leadership, awards, portfolio, contact), decision-maker discovery
(`decision_makers.py`), autonomous scheduler (`scheduler.py`).

**Build — the experience:**
- **The Living Map** (`/agencies` reimagined): dark control-room theme. Header is an
  instrument row of live counters in monospace (profiled / enriching now / signals this
  week) — Teenage Engineering spec-grid style, real numbers.
- **Agency profile page** as the platform's core object: identity header (name, type
  chips, offices, site), then Attio-style **bento grid** of profile cards — Services,
  Industries, Leadership, Awards, Portfolio, Decision Makers, Music Characteristics.
  Every fact carries a monospace **source line** (URL + date observed) — evidence-first.
- **Enrichment as visible instrumentation:** the profile shows its own completeness
  (which micro-agents have run, what's pending) as a quiet progress meter — the "agent
  working in the background" made legible.
- Empty fields say "not yet observed" — never guessed (honesty rule, in the UI).

### Element 2 — Company Intelligence Engine
*"How do they work?" — executive summary, campaign types, creative strengths, production
complexity, typical clients, observed music usage, org structure, buying tendencies.*

**Exists:** `intelligence.py` (evidence-backed profile generation), `intel_json` blob.

**Build:**
- **Intelligence dossier tab** on the agency page: an executive summary set in the serif
  display voice (this is the one narrative surface), followed by structured sections in
  the sans/mono system. Each claim links to its evidence signal.
- **Production-complexity and buying-tendency meters** rendered as small dataviz (bars,
  not gauges) with the observed basis stated beneath.
- "Observed music usage" section embeds actual referenced campaign links where captured.
- Regenerate button = machine proposes; the dossier is never auto-published to any
  outbound doc without Jon pressing the button.

### Element 3 — Signal Detection Framework
*Meaningful changes, not indiscriminate monitoring: case studies, campaigns, hiring,
awards, press, portfolio updates, leadership changes, new offices, client wins.*

**Exists:** `opportunity_signals.py` (diff-based detection over re-enrichment snapshots),
re-enrichment cadence in `scheduler.py`.

**Build:**
- **The Signal Feed** (`/signals`): a reverse-chron evidence stream. Each signal is a
  card: signal type chip (accent-coded), agency, the *diff itself* in monospace
  (before → after), source URL, detected date. Structured evidence, visibly structured.
- Filters by type/agency/recency; a signal links to its agency and to any opportunity it
  contributed to.
- **Signals week-strip** on the dashboard: a 7-day sparkline of detection volume — the
  heartbeat of the autonomous system, proving it runs without being watched.

### Element 4 — Music Opportunity Engine
*The reasoning engine: Agency Intelligence + Signals + Decision Makers + Relationship
History → "Why is today the best day to contact this agency?"*

**Exists:** `music_opportunity.py` (scoring), `scoring.py`/`strategic.py` (mission-spine
ranking).

**Build — the platform's signature screen:**
- **The Why-Today Queue** (`/opportunities` reimagined): ranked cards, each led by a
  one-sentence **reasoning line** ("New CD hired 12 days ago + two case studies shipped
  without credited music partner"), then the evidence chain beneath it — the four
  inputs as linked chips (intelligence facts, signals, the person, history).
- This screen is also the **marketing hero**: the live-demo pattern (Attio) — the public
  site shows a real (demo-data) Why-Today card assembling itself.
- Score is shown but subordinate to the reasoning sentence: humans act on reasons,
  not numbers. Jon disposes: Pursue / Snooze / Dismiss buttons on every card.

### Element 5 — Relationship Platform
*Not a contact list — institutional memory: notes, conversations, preferences, creative
tendencies, communication style, meeting history, documents, opportunity history.*

**Exists:** opportunities pipeline + notes, `doc_overrides` pattern, win/loss engine;
decision-maker records.

**Build:**
- **Relationship timeline** on each agency: one merged stream of everything — notes,
  emails sent (from Element 7), meetings, signals, opportunities opened/won/lost — with
  type-chips and the wine accent. The Salesforce half, done as a *memory*, not a form.
- **Preference & tendency cards** (communication style, creative leanings, "always CCs
  the producer") — structured but hand-entered; the machine surfaces suggestions from
  observed interactions, Jon confirms them into the record.
- A `relationship_events` table generalizing the existing per-project `updates` pattern
  to agencies (mirror the `delivery_json`/merge-one-key pattern for preference blobs).

### Element 6 — Outreach Strategy Engine
*Should we reach out? Why now? To whom? What objective? Strongest talking point?
Contextual, never generic.*

**Exists:** `outreach.py`, compose flow (`/opportunity/{id}/compose`), real branded
sending (`mailer.branded_html`, July 2026).

**Build:**
- **The Strategy Card** — precedes any compose: five labeled answers (reach out? / why
  now? / to whom? / objective? / talking point?) each with its evidence chip. Approving
  the strategy unlocks the composer (machine proposes → Jon disposes, enforced by flow).
- Talking point is drawn from the Why-Today reasoning line, so outreach and opportunity
  reasoning are literally the same object — never two divergent stories.

### Element 7 — Content Generation Engine
*From the approved strategy: emails, LinkedIn messages, meeting agendas, call briefs,
proposal drafts, creative briefs, follow-ups — generated from evidence, not templates.*

**Exists:** deterministic block-based composers (`proposals.py`, `capabilities.py`,
`recruiting.py` compose functions, compose-blocks with `doc_overrides` persistence).

**Build:**
- **One composer surface, seven output types.** The existing block architecture
  (show/skip/edit blocks, persisted overrides) generalizes: each content type is a block
  recipe over the same evidence. Tabs across the top; the strategy card pinned beside it.
- Every generated block shows a faint monospace *provenance footnote* (which fact/signal
  it was built from) — "generated from evidence" made visible and checkable.
- LinkedIn messages get a copy-to-clipboard flow (no API integration this phase);
  agendas/briefs get the print-to-PDF treatment already used by the capabilities doc.

### Element 8 — Relationship Continuity Engine
*After outreach: monitor responses, silence, new signals, status, recent activity —
recommend the next best action.*

**Exists:** follow-up cadence fields on opportunities; win/loss capture; the scheduler.

**Build:**
- **The Continuity Queue** (`/today` — the platform's landing screen): every relationship
  with a recommended next action and its reason ("14 days of silence after a warm reply —
  send the case-study follow-up" / "New signal since last touch — re-open with it").
  One list Jon works top to bottom each morning. Salesforce's pipeline, inverted into
  an advisor.
- Recommendations are deterministic rules over the relationship timeline (silence
  windows, signal-since-last-touch, promised-follow-up dates) — engine recommends,
  buttons dispose (Do it now → composer; Snooze; Not relevant).

### Element 9 — Music Production System
*Only after everything above does music begin: creative strategy, composition,
arrangement, production, mix, master, stems, campaign versions, alternate edits,
deliverables, rights, documentation. Human-made, always.*

**Exists:** projects + assignments, Delivery OS five agents (Rights, Revisions, Metadata,
Approvals, Assets — `delivery.py`), talent roster + matching, signing scope emails.

**Build:**
- **Production board** per project: the stage spine (Strategy → Composition →
  Arrangement → Production → Mix → Master → Stems → Versions) as a horizontal progress
  rail — the delivery console's milestone pattern, elevated to the main visual.
- **The cue-player component** (Part 1.4) debuts here: every uploaded cue/version gets a
  waveform (wavesurfer.js v7, pre-decoded peaks stored at upload), version chip,
  rights-status badge.
- **Timecoded review**: reviewer comments anchored to waveform positions in the existing
  token-gated review portal — the Frame.io mechanic, for sound. This is the flagship
  feature of the entire plan.
- Roadmap-ready seams (don't build yet, don't block): multiple composers/sound designers/
  supervisors/orchestrators/mix engineers/session musicians (roster already supports
  disciplines), licensing partners, live-recording coordination, budget estimation
  (estimation.py exists), vendor management, AI-assisted *ideation only* — never
  AI-generated audio (product spine).

### Element 10 — Delivery Platform
*Every project ships with: cue sheets, rights summaries, version naming, folder
organization, delivery inventory, approval packages, campaign rollout versions.
The goal is operational clarity.*

**Exists:** delivery package page, cue sheets, rights docs, reviewer tokens, payment
gate, the five delivery agents.

**Build:**
- **The Delivery Room** (client-facing, token-gated, dark control-room theme): the
  Frame.io-quality surface the client remembers. Left: folder-organized inventory with
  monospace version names (naming convention enforced by the Metadata agent). Center:
  cue-player. Right: approval package status + rights summary.
- **Campaign rollout matrix**: versions × placements (broadcast :30/:15, social 9:16,
  cutdowns) as a Teenage Engineering-style 1px spec grid — operational clarity as an
  aesthetic.
- Downloadable everything; the payment gate already in place governs release.
- The customer promise, printed at the bottom of every delivery room, and meant:
  **"Chordential removes the work of managing music so agencies can stay focused on
  managing the campaign."**

---

## Part 4 — Build order (each phase ships green and deployable)

1. **Design system pass** — dark control-room theme tokens (CSS variables alongside the
   existing daylight set), mono-for-data convention, the three motion signatures, the
   `<cue-player>` component. *Foundation for everything else.*
2. **Intelligence face** — Living Map header instrumentation, agency profile bento +
   dossier tab, Signal Feed + week-strip. (Engines exist; this is presentation.)
3. **Reasoning face** — Why-Today Queue with evidence chains; Strategy Card gating the
   composer; provenance footnotes in compose.
4. **Relationship face** — relationship timeline + preference cards
   (`relationship_events` migration via the `_*_COLUMNS` pattern); Continuity Queue as
   `/today` landing.
5. **Production & Delivery face** — production board rail, waveform players with stored
   peaks, timecoded review comments, Delivery Room, rollout matrix.
6. **Front-of-house refresh** — live-demo hero (Why-Today card on demo data), live
   instrument counters, reel with the same cue-player, customer-promise narrative.

Constraints honored throughout: machine proposes / Jon disposes on every decision
surface; no AI-generated audio anywhere (ideation assistance only, later, clearly
scoped); no fake clients or capabilities — live numbers or labeled demos only.

---

## Sources

- [Rebranding Frame.io — Adobe Design](https://adobe.design/stories/process/rebranding-frameio)
- [Frame.io: A Bright New Look for an Exciting Future](https://blog.frame.io/2022/10/14/frame-io-rebrand-2022/)
- [Frame.io Brand Style Guide 2023 — Deck.gallery](https://www.deck.gallery/frame-ios-brand-guideline-2023/)
- [Teenage Engineering: Constraints as Aesthetic — Blake Crosley](https://blakecrosley.com/guides/design/teenage-engineering)
- [Ableton website — Fonts In Use](https://fontsinuse.com/uses/2291/ableton-website)
- [Linear design: the SaaS design trend — LogRocket](https://blog.logrocket.com/ux-design/linear-design/)
- [How we redesigned the Linear UI — Linear](https://linear.app/now/how-we-redesigned-the-linear-ui)
- [Attio design system notes — SaaSUI](https://www.saasui.design/application/attio) / [Design at Attio](https://verifiedinsider.substack.com/p/design-at-attio)
- [Barking Owl](https://www.barkingowl.com/) · [Butter](https://www.gimmebutter.com/) · [Squeak E. Clean Studios](https://www.squeakeclean.com/) · [Human Worldwide](https://www.humanworldwide.com/) · [Mophonics](https://www.mophonics.com/) · [MassiveMusic](https://massivemusic.com/)
- [40 Music Website Design Examples — Really Good Designs](https://reallygooddesigns.com/music-website-design-examples/)
- [Awwwards — Best Music & Sound websites](https://www.awwwards.com/websites/music-sound/)
- [wavesurfer.js — audio waveform player](https://wavesurfer.xyz/docs/) / [GitHub](https://github.com/katspaugh/wavesurfer.js/)
