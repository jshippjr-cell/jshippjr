# UX Teardown — pacomepertant.com (Forensic Analysis)

> **What this is.** A forensic reverse-engineering of https://pacomepertant.com/ (portfolio
> of Pacôme Pertant, motion & sound designer, Paris) conducted 2026-07 for one purpose:
> extract the design language, interaction patterns, architecture, and UX philosophy that
> make the experience feel the way it does, so ChordOS can be built with the same level of
> quality. **This is a teardown, not a visual critique, and not a proposal to copy.**
> Branding, colors, and purely stylistic typography are noted only where they carry a
> *system* lesson.
>
> **Method & evidence.** The site (a server-rendered Nuxt 3 app) was mirrored asset-by-asset
> — HTML, all JS chunks, compiled CSS, content payloads, CMS images, fonts, all 15 sound
> files — and rendered in an instrumented headless Chromium against the local mirror. Every
> claim below traces to one of: (a) extracted compiled CSS (design tokens, transitions,
> media queries), (b) de-minified JS (GSAP/three.js/Lenis/Howler configuration — exact
> durations, easings, staggers, volumes), (c) rendered screenshots across five viewports,
> (d) runtime measurements (computed-style sampling at ~16ms intervals during transitions,
> Pinia store inspection, tab-order walks). Values are **measured, not estimated**; the few
> inferences are labeled as such.
>
> **Honest limitations.** (1) Video streams (Mux HLS) do not play in the mirror; video
> *layouts* were analyzed via posters and the player DOM, playback feel was not observed.
> (2) The sound files' *musical* character was not evaluated — but the complete sound
> registry (which sound fires on which event, at which volume) was extracted from code, so
> the sound *system* is fully documented. (3) WebGL shader aesthetics (motion blur amount,
> lens distortion) are described from screenshots + shader-code reading, not frame-perfect
> measurement.

Companion documents:
- `ux-translation-chordos.md` — every pattern mapped onto Chordential/ChordOS modules.
- `ux-build-spec.md` — the engineer-ready build specification.

---

## 1. Overall Design Philosophy

### First impression
The site does not start with content. It starts with a **threshold**: a black screen, a
small 3D smiley sphere, one line of identity copy ("motion & sound designer based in
paris"), and a single white pill button — "enter with sound •" — with a dim escape hatch
("enter without sound") at the very bottom. You are asked to make one decision before you
see anything. That decision (sound on/off) is the *product's own dimension* — the person
sells motion **and sound**, so the first interaction makes you experience that sound is a
first-class material here.

### Emotional response and why it happens
The feeling is *"I am in a crafted place, and someone is in control of it."* Mechanically,
that feeling is produced by five reinforcing choices:

1. **A loading sequence that is choreography, not a spinner.** A Lottie plays; the tagline
   splits into lines and staggers up (`yPercent -100→0, opacity 0→1, stagger 0.1s,
   power1.out, 0.6s`); the enter button appears only when *both* the animation completed
   *and* the WebGL resources are fully loaded — and even the progress number itself is
   eased (`progress += (target - progress) * 0.02` per frame), so the loader *feels*
   smooth regardless of network reality.
2. **One thing on screen at a time.** At any moment there is exactly one primary object of
   attention (the loader; the spiral; the list; the menu panel; the case hero). Nothing
   competes.
3. **Continuous, physical motion.** Everything arrives and leaves with mass — springs with
   measurable overshoot (the menu panel opens 87px → 471px → settles at 465px), squash-and-
   stretch on list rows (`scaleY 0.5 → 1`), elastic pop on tooltips (`elastic.out(1, 0.4)`).
4. **Sound bound to interaction** (15 distinct sounds, volume-mixed — see §5/§6): hover
   ticks, view-switch whooshes, navigation "long click." The interface is *scored*.
5. **Total palette restraint** (see §8): near-black, off-white, one grey, and exactly one
   accent color that appears only on playful stickers ("keep scrolling !"). Premium feel is
   mostly the *absence* of color competing with the work.

### Visual hierarchy
Hierarchy is produced almost entirely by **scale and value (brightness), not by weight,
color, or decoration**:
- Display text is enormous (project titles render at ~76px in list view, menu links at
  ~64-80px, about intro at ~32px) while chrome text is small (18px) — a ratio of roughly
  4:1 between "content" and "controls." You always know what is content and what is chrome
  by size alone.
- Secondary-ness is expressed by dimming (opacity 0.2/0.4/0.6 steps), not by smaller type:
  in list view, hovering one title dims all siblings; on the about page, un-read words sit
  at 50% until scroll "reads" them to 100%.
- There is **one** primary action per screen, and it is *always* the same shape: a pill.

### Information density
Deliberately near-zero. Nine projects, two pages, one contact email. Each screen carries
3–7 interactive elements total (measured: home has logo, spiral/list switch, menu pill,
showreel card, mute button). This is the extreme end of "confidence through omission" —
appropriate for a portfolio where the work *is* the content. The transferable lesson is
not "show nothing" but **"per screen, decide what the single object of attention is, and
demote everything else to chrome."**

### White space strategy
Space is not distributed; it is **concentrated**. Margins are governed by a fluid grid
(`--grid-margin`, 15→30rem responsive) and content is centered in a huge void. The void is
active: it's where the WebGL grain/grid texture lives, so "empty" still has material. The
practical rule extracted: *edges get a fixed frame (grid margin), the center gets exactly
one composed object, and vertical rhythm inside flowing pages uses a gap scale
(10/15/20/30/45/60/90/120/180) rather than ad-hoc values.*

### Design principles (as evidenced, not claimed)
1. **Threshold before content** — an entry moment sets expectations and unlocks capability
   (audio) that the rest of the experience depends on.
2. **Same data, multiple representations** — spiral (spatial, emotional) vs list (fast,
   scannable) over the *same* nine projects, switchable in one click, state-preserved.
3. **Physics as brand** — one spring curve (`--ease-spring`, ~1.4% overshoot) reused for
   every panel, pill, and reveal, so the whole product shares one "material."
4. **Feedback is multi-channel** — visual (style delta) + spatial (motion) + audio (tick)
   for the same event, each subtle because the others carry part of the load.
5. **Chrome is honest** — controls literally say what they do in lowercase words: "menu,"
   "close," "spiral," "list," "enter with sound." No icons-only mystery meat (except the
   mute toggle — and that one earns it by being a universal glyph).
6. **The exit is always visible** — close buttons render top-right on every overlay; every
   case page ends by feeding you the *next* project (no dead ends).

### Why it feels premium
Because *nothing arrives instantly and nothing arrives late*. Every state change costs
0.25–0.9s of physically-plausible motion, tuned so the slow pieces (panels, 0.8–1.0s
springs) frame the fast pieces (hovers, 0.15–0.3s). Cheap products have two speeds:
instant and janky. This has a **tempo hierarchy** (§6) — and the discipline to use maybe
six easing curves and one accent color across the entire product.

---

## 2. Layout System

### The root scaling trick (the single most transferable engineering decision)
The CSS defines `--rem: 1px` and sets `html { font-size: var(--rem) }`, then sizes
**everything** in `rem`. On small screens a reference width (`--width-reference: 394`)
drives recalculation, so `1rem` scales with the viewport — i.e., the entire UI is designed
on a fixed art-board (394pt mobile / desktop board) and *proportionally* scales between
breakpoints instead of reflowing continuously. Mobile bumps the base to `19rem` body size.
This is why the site never has an "awkward in-between" viewport: geometry is preserved,
not reflowed, between the few true breakpoints.

### Grid
A real, calculated column grid, in custom properties:
```
--grid-column: calc(var(--vw)/12 - var(--grid-gutter)*11/12 - var(--grid-margin)*2/12)  /* desktop: 12 col */
--grid-column: calc(var(--vw)/6  - var(--grid-gutter)*5/6  - var(--grid-margin)*2/6)   /* mobile: 6 col */
--grid-gutter: 10rem → 15rem → 16rem (responsive)
--grid-margin: 15rem → 20rem → 30rem (responsive)
```
Widths are then *composed* from the grid: the menu panel is `4 cols + 4 gutters` (desktop),
`5 cols + 4 gutters` (≤1400px), `6 cols + 5 gutters` (≤1024px); text measures are capped at
`3 cols + 2 gutters` / `4 cols + 3 gutters`. **Nothing is an arbitrary pixel width; every
width is a sentence in grid vocabulary.**

### Spacing scale
Two families, both tokenized:
- **Gaps** (component-internal rhythm): `--gap-xs 10, -s 15, -20 20, -m 30, -45 45, -l 60,
  -xl 90, -xxl 120, -xxxl 180` (rem = design-px).
- **Grid units** (page-level rhythm): margins/gutters/columns as above; section padding
  uses grid expressions like `padding: 60rem calc(var(--grid-column) + var(--grid-gutter))`.

### Container widths & alignment
- Full-bleed dark stage for spatial views (home).
- Case pages: a **rounded full-width card inset by the grid margin** (the hero video sits
  in a `radius-xl` container framed by background on all sides — content is "matted" like
  a print, never touching the viewport edge).
- Text content centered, measure-capped at 3–4 columns.
- Styleframes alternate left/right on a checkerboard (image col 1–6, then col 7–12),
  collapsing to full-width stacked at ≤900px.

### Card system
Cards are **media-first with zero chrome**: rounded rectangle (`--radius-l/xl`), the image
*is* the card, no border, no shadow (the only box-shadow in the whole CSS is
`0 4px 8px #0003` on one small element). Depth is conveyed by backdrop blur, dimming, and
motion parallax instead of drop shadows. Labels attach as **stickers**: small rotated
pills pinned to corners (`.tag.top-right`, `.tag.bottom-left`, rotated a few degrees),
e.g. "next up...", "keep scrolling !".

### Responsive behavior & breakpoints (measured)
```
420px   — phone padding/frame adjustments (--padding 8rem)
900px   — the primary structural break: base font 19rem; columns stack;
          credits hidden; progress bar hidden; tags reposition or hide;
          menu footer padding changes
1024px  — menu panel widens to 6 cols
1400px  — menu panel 5 cols
hover:hover + pointer:fine — hover-dependent UI (cursor trail) is *gated at the CSS
          level* so touch devices never get half-working hover effects
```
Crucially, mobile is **not a different product**: the spiral remains, the same controls
remain in the same corners; only density and column count change. The mental model never
resets across devices.

---

## 3. Information Architecture

### Structure (complete)
```
Entry gate (sound choice)                    ← threshold state, not a page
└── Home "/" — the works browser
    ├── spiral view (default): 3D stream of 9 project cards, scroll = travel
    ├── list view: 9 giant title rows, hover = preview
    ├── showreel card (bottom-left, persistent) → fullscreen player overlay
    └── menu (top-right pill) → overlay panel: works / about / contact
        ├── works    → closes menu (you're already there)
        ├── about    → "/about" — bio, scroll-read intro, credits
        └── contact  → mailto (email is also printed in the panel footer)
└── Project "/projects/{slug}" — case page (client-side navigation only)
    ├── hero video (rounded, inset, autoplaying poster)
    ├── title + year + short description + "see the case •" → Behance
    ├── 3 styleframes, alternating layout
    └── next-project footer ("next up..." + poster + "keep scrolling !")
        → scroll continues into the next case (circular browsing)
```

### Navigation model
- **Hub-and-overlay, not tree-and-pages.** There is one hub (works). About and the player
  are overlays/leaves. The menu is an overlay *on top of* state, not a place you go — the
  spiral keeps living, dimmed and blurred, behind it.
- **Persistent chrome corners:** logo top-left (home), view-switch top-center, menu
  top-right, showreel bottom-left, sound bottom-right. Five anchors, never move, never
  disappear across pages — spatial memory does the wayfinding.
- **Forward momentum instead of back navigation:** case pages end with the next case.
  "back to home" exists (top-center on cases) but the *designed* path is onward. The
  browsing loop is circular: works → case → next case → … → home.

### Mental model
"**One room, many arrangements.**" You never leave the room; content rearranges around
you. This is why it feels coherent: page transitions are `mode: "out-in"` fades and the
WebGL stage persists behind everything, so context is never destroyed. (Lenis smooth
scroll stops during transitions, restarts on arrival — even the *scroll physics* is a
managed part of the transition.)

### Primary vs secondary actions
- Primary = **filled pill with the orbiting dot** ("enter with sound •", "menu •",
  "see the case •"). One per screen. The dot is a trademark micro-affordance: a small `•`
  travels around the pill's border on hover (`offset-distance` animation, 12s linear
  loop), literally *pointing at* the interactive boundary.
- Secondary = plain lowercase text at small size, often dimmed ("enter without sound,"
  "back to home," the inactive view-switch label).
- Destructive/exit = the round ✕ ("close ✕" pill, top-right, black-on-white or inverse).
  Same position on menu panel, player, case pages. **Exits are a component, not a
  decision.**

### Why the architecture works
It optimizes for a portfolio's single job — *make the visitor watch work* — by removing
every decision that isn't "which work next": no filters, no categories, no pagination, no
footer sitemap. The two views (spiral/list) acknowledge two visitor moods (browse
emotionally / scan professionally) without duplicating content. And because state persists
(view mode survives navigation; the store is the single source of truth), the visitor
never pays a reorientation cost. The deep-link 404 (project URLs are client-side only —
verified live) is the architecture's one real flaw: momentum was prioritized over
addressability.

---

## 4. Component Library (complete inventory)

The site is intentionally small: **12 reusable components** (verified against Vue scoped-
style hashes). For each: purpose, sizing, spacing, states, interaction, variants, usage
rules. Sizes are computed desktop values ("dpx" = design px = rem units in their system).

### 4.1 Pill Button (the primary-action component)
- **Purpose:** every primary action, sitewide (enter, menu, see-the-case).
- **Sizing:** height 48px; padding `15 28 15 15` (asymmetric — the right 28px reserves the
  dot's orbit lane); radius `100rem` (full pill); label 18px / weight 500 / lowercase.
- **Structure:** white (or black-on-light-context) filled capsule; label rendered
  *twice* — visible `.letter` spans + hidden duplicate for the flip effect; `•` dot after
  the label.
- **States (all measured):**
  - Rest: filled, dot static.
  - Hover: per-letter jiggle — each letter animates `rotation: random(-15°,15°),
    scale: random(1.15,1.4), fontWeight 500→600` in 0.25s power2.out, stagger 0.05s, then
    returns (0.25s) — a variable-font weight *animation*; the dot begins orbiting the pill
    border via `offset-distance` (12s linear infinite); background/color can invert
    (`transition: transform .3s ease, background-color .3s ease, color .3s ease`).
  - Pressed: scale-down via `transform .15s ease-out` (subtle).
  - Disabled/hidden: opacity 0 + `pointer-events: none` until revealed by `.show` (opacity
    + transform transition 0.3–0.5s spring).
- **Usage rules:** one per screen; always carries the dot; label always lowercase; never
  used for navigation-back or destructive actions.

### 4.2 Close Button (exit component)
- **Purpose:** dismiss any overlay (menu, player) and leave case pages.
- **Sizing:** 48px round; ✕ glyph; optional "close" word-label to its left (18px).
- **States:** rest black-on-white (menu) or white-on-dark (case hero); hover rotates/scales
  the ✕ (`transform .5s ease, opacity .3s ease` on the label, spring on the glyph);
  keyboard: Escape closes the player (verified).
- **Usage rules:** always top-right, always circular, always present when content is modal.

### 4.3 View Switch (segmented text control)
- **Purpose:** switch home between spiral and list representations of the same data.
- **Structure:** two text buttons ("spiral", "list") flanking a small dot separator,
  top-center; 18px lowercase.
- **States:** active label = white (full opacity), inactive = dimmed (~0.4); the labels are
  *doubled* spans (`spiralspiral`) for a roll-over flip effect; click plays the matching
  sound ("spiral" ogg / "list" ogg, vol 0.4) and triggers `revealProjects()` /
  `hideProjects()` in the WebGL world.
- **Interaction contract:** switching is a *transition*, not a swap — list rows leave with
  `y:50, opacity:0, scaleY:0.5, 0.3s, stagger 0.05` and arrive with `y:-30→0, opacity 1,
  scaleY 0.5→1, 0.5s power3.out, stagger 0.05, delay 0.2` (leave is faster than enter —
  a universal rule here).
- **Usage rule:** exactly two options; state persists across navigation (Pinia store).

### 4.4 Project List Row
- **Purpose:** fast scanning of works.
- **Sizing:** display type ~76px (56–80rem scale, 40rem ≤900px), centered, tight
  line-height (~1.0–1.1), letter-spacing −0.04/−0.05em.
- **States:** rest all-white; on any row hover, hovered row stays white while **siblings
  dim** (opacity ~0.2–0.4) — attention by subtraction; hover also plays "hover" sound
  (vol 1.0) and spawns the cursor-image trail (4.5).
- **Interaction:** click → "longclick" sound + route to case page.
- **Usage rules:** rows are pure text; imagery never sits *in* the row — it floats on the
  cursor instead.

### 4.5 Cursor Image Trail
- **Purpose:** preview-on-hover without committing layout space; rewards exploration.
- **Mechanics (from code):** up to **5** stacked thumbnails (512px-wide CMS crops); cursor
  position lerped at factor **0.1** per frame, scale lerped at **0.07** toward 1 when a
  project is hovered and toward 0.5 when not; positioned `translate(-25%, -75%)` from the
  pointer; each new image enters `fadeInScale 0.5s expo-out`; cycling images play "tick"
  (vol 0.2); trail clears when scale collapses below 0.01.
- **Usage rules:** desktop-only (`hover:hover and pointer:fine` gate); images are *behind*
  the text layer (list rows stay legible — verified in screenshots).

### 4.6 Menu Overlay Panel
- **Purpose:** global navigation + contact, as a temporary layer (never a page).
- **Sizing:** right-docked rounded panel, width `4 cols + 4 gutters` (desktop) →
  `6 cols + 5 gutters` (≤1024px) → near-fullscreen sheet ≤900px; inverse surface (white on
  the dark site).
- **Contents:** giant lowercase links (works/about/contact, ~64–80px, stacked, left-
  aligned), footer = email + 4 round 44px social icon buttons.
- **Motion (measured):** width springs open 87→471→settles 465px over ~0.65s
  (`width .9s var(--ease-spring), height 1s var(--ease-spring)`); the background scene
  dims *and* blurs (`backdrop-filter: blur(20px)` + dark scrim `--color-bg-dark60`).
- **States:** links hover → per-letter jiggle (same as pill) + per-link *distinct sound*
  ("menuhome" / "menuabout" oggs, vol 0.25); close = round ✕ top-right; the "works" link
  when already on works simply closes the menu (no dead navigation).
- **Usage rules:** menu never navigates *and* stays open; it is exclusively transient.

### 4.7 Showreel Card (persistent media entry)
- **Purpose:** one-click access to the reel from anywhere — the portfolio's "hero CTA"
  disguised as an object.
- **Structure:** small rotated video-thumbnail card pinned bottom-left, *half off-screen*
  (only a corner intrudes); circular text "showreel • 2025 •" wraps around it; hover
  straightens/scales it up (spring transitions `transform .8s var(--ease-spring), right
  .8s, top .8s`); click opens the fullscreen player.
- **Why it matters:** it demonstrates *peripheral persistent CTAs* — always available,
  never occupying layout, impossible to forget because it's slightly "alive."

### 4.8 Fullscreen Player (modal)
- **Purpose:** watch video with zero competing chrome.
- **Structure:** full-viewport dark surface; custom controls (play/pause, progress bar —
  hidden ≤900px, mobile gets a dedicated close affordance `.mobileclose`); HLS via Mux.
- **States:** open/close animated (width/height/border-radius transitions 0.9–1.0s spring
  — it *grows out of* the thumbnail card rather than popping); Escape closes (verified);
  close ✕ top-right.
- **Usage rule:** video always plays in this one surface — never inline in layout.

### 4.9 Sticker Tag
- **Purpose:** playful metadata labels ("next up...", "keep scrolling !").
- **Structure:** small pill (radius full), few degrees rotation, pinned to card corners
  (`top-right` / `bottom-left` variants); white or pop-green (`#21ffc0`) fill, black text.
- **Rules:** the *only* place the accent color appears; ≤900px some tags hide or recolor;
  never interactive (pure annotation).

### 4.10 Progress / Scroll Indicator
- Thin right-edge scroll progress bar on case pages (hidden ≤900px). Purpose: length
  awareness on long scroll pages, without a visible scrollbar.

### 4.11 Tooltip / Hover Info Chip (spiral view)
- **Purpose:** identify the hovered 3D card.
- **Structure:** white rounded chip, 64px thumbnail + title, docked bottom-center.
- **Motion:** appears with `elastic.out(1, 0.4)` pop (0.7s scale 0.8→1), leaves faster
  (`0.25s power2.inOut scale→0.8, opacity→0`); "project-fade" Vue transition wraps it.
- **Usage rule:** tooltip *identifies*, never acts — clicking happens on the card itself
  (raycast → cursor becomes pointer + "hover" sound on enter, "longclick" on tap).

### 4.12 Loader
- **Purpose:** the threshold (see §1).
- **Structure:** centered Lottie (bundled JSON, autoplay once) + SplitText tagline + enter
  buttons; full-viewport overlay (`z-index` top tier) that blocks pointer events until
  entered.
- **Reveal contract (from code):** tagline shows when Lottie *loads*; lines stagger in on
  Lottie *complete*; buttons show only when `isReady` (all WebGL resources loaded + eased
  progress ≥99.5%) **and** the Lottie finished — i.e., the gate opens only when the world
  behind it is guaranteed smooth.

### Components that do **not** exist (and the lesson)
No tables, no dropdowns/selects, no accordions, no tabs (the view-switch is a mode toggle,
not tabs), no breadcrumbs, no toasts/notifications, no pagination, no search, no forms/
inputs of any kind (contact = mailto), no empty states (content is fixed), no loading
skeletons (the one loader *is* the loading strategy). The absence is the point: **every
component that exists earns its place by being used repeatedly; nothing exists "just in
case."** ChordOS *does* need tables/forms/queues — the translation doc maps how this
component *grammar* (pills, stickers, dim-the-siblings, spring panels) applies to them.

---

## 5. Interaction Design

### Complete interaction→feedback map (extracted from code + verified live)
| Event | Visual | Motion | Audio (vol) |
|---|---|---|---|
| Loader completes | tagline lines rise | 0.6s power1.out stagger 0.1 | — |
| Enter (either button) | gate fades, spiral reveals | projects reveal ~200ms later | ambient loop starts (0.3; muted path sets mute) |
| Hover pill/menu link | letters jiggle, weight 500→600 | 0.25s power2.out stagger .05 | menu links: per-link sound (0.25) |
| Hover pill (sustained) | dot orbits border | offset-distance 12s linear | — |
| Hover list row | siblings dim; cursor trail grows | lerp 0.1 pos / 0.07 scale | "hover" (1.0) |
| Cursor trail image cycles | new thumb fadeInScale | 0.5s expo-out | "tick" (0.2) |
| Hover spiral card | cursor→pointer; info chip pops | elastic.out(1,.4) 0.7s | "hover" (1.0) |
| Click any project | navigate to case | out-in page transition | "longclick" (0.5) |
| Switch spiral→list | rows leave/enter staggered | 0.3s out / 0.5s in power3.out | "list" (0.4) |
| Switch list→spiral | inverse | same | "spiral" (0.4) |
| Open menu | panel springs from right; stage dims+blurs 20px | width .9s spring | "click" (0.5) *(inferred trigger)* |
| Close menu/player | panel retracts; ✕ | faster than open | "close" (0.7) |
| Open showreel | card grows to fullscreen | .9–1s spring incl. border-radius | "switch" (0.5) *(inferred)* |
| Mute toggle | icon swap | 0.2s | silence/restore ambient |
| Scroll (case page) | Lenis smoothing | wheelMultiplier 0.8, duration 1.2, expo ease | — |
| Scroll (about intro) | words brighten 50→100% | scrub-bound (no duration) | — |
| Escape (player) | closes | — | — |

### State discipline
- **Hidden ≠ removed:** overlays animate `opacity` + `pointer-events`, so re-entry is
  instant and state (scroll position, view mode) survives.
- **Loading is centralized:** exactly one loading experience (the entry loader). After the
  gate, *nothing* ever shows a spinner — assets were front-loaded behind the threshold.
  This inverts the usual pattern (make the user wait everywhere a little) into "wait once,
  meaningfully, then never again."
- **Success/error states do not exist** because no user input exists. (The translation doc
  handles how this philosophy meets ChordOS's forms: §11.)
- **Disabled state appears once:** the enter buttons pre-reveal (opacity 0, pe:none) —
  disabled-ness expressed as *not yet arrived* rather than greyed-out.

### What makes it feel responsive (the mechanics, precisely)
1. **Sub-100ms acknowledgment, always:** hover feedback (dim, cursor change, sound tick)
   begins immediately; the *decorative* completion takes 0.25–0.7s. Acknowledge fast,
   embellish slow.
2. **Leave < enter:** every exit is faster than its entrance (rows: 0.3s out vs 0.5s+0.2
   delay in; chip: 0.25s out vs 0.7s in). The UI gets out of your way faster than it
   arrives — a rule cheap UIs violate constantly.
3. **Lerped following instead of snapping:** the cursor trail follows at factor 0.1/frame
   — it *pursues* you. Nothing teleports.
4. **The interface pre-answers "did that work?"** with doubled channels (visual + audio),
   so no interaction ever needs a confirmation dialog.

---

## 6. Motion Design

### The tempo hierarchy (all values measured/extracted)
| Tier | Duration | What lives here | Easing |
|---|---|---|---|
| Micro | 0.1–0.2s | pressed states, icon swaps, small opacity | ease / ease-out |
| Reaction | 0.25–0.35s | hovers, letter jiggle, dims, chip exit | power2.out, ease, expo-out |
| Transition | 0.4–0.5s | row enter/leave, reveals, fades between views | power3.out, spring |
| Panel | 0.65–1.0s | menu open, player grow, showreel spring, hero reveals | **--ease-spring**, expo-out |
| Ambient | 12s / 40s | dot orbit; marquee scroll | linear, infinite |

### The signature curves (exact values)
```css
--ease-spring:      linear(0, .0014, …, 1.0142 47.07%, 1.0144 53.43%, 1.0054 68.37%, …, .9998)
                    /* a sampled spring: ~1.4% overshoot peaking around 50% of duration,
                       settling without secondary bounce — firm, not bouncy */
--ease-expo-out:    cubic-bezier(.19, 1, .22, 1)
--ease-quad-in-out: cubic-bezier(.455, .03, .515, .955)
/* plus in JS: power1/2/3.out, back.out(1.7), elastic.out(1, 0.4), expo Lenis easing */
/* plus one playful outlier used in CSS: cubic-bezier(.34, 1.56, .64, 1) (back-out-like) */
```
The spring is implemented as a **CSS `linear()` sampled curve** — meaning even plain CSS
transitions get true spring physics without JS. It is used for *width, height,
border-radius, transform, padding* — anything "physical." Bezier eases are reserved for
*opacity/color* — anything "optical." That split (physical↔spring, optical↔ease) is
consistent across the codebase and is the single most copyable motion rule found.

### Choreography patterns
- **Stagger everything plural.** Lines 0.1s apart; rows/letters 0.05s; about-credits 0.08s.
  Total stagger budget stays ≤0.4s regardless of item count (`stagger: {amount: .25}` used
  when count varies).
- **Transform + opacity together, never opacity alone** for content ("things move into
  place, they don't fade into existence"). Fade-only is reserved for full-page
  transitions (out-in mode).
- **Scale from meaning:** chips/tags scale from 0 (they "pop on"), rows squash
  (scaleY 0.5 — they "unfold"), panels grow from their trigger (player grows out of the
  showreel card, incl. animated border-radius 0.9s).
- **Scroll-scrub for reading, triggers for arriving.** About intro brightness and media
  scale are *scrubbed* (progress-bound, no duration); section entrances are *triggered
  once* (`start: "top 95%", once: true`, 0.8s power3.out y:100%→0). Two different
  scroll-motion grammars for two different jobs.
- **Page transitions manage physics:** Lenis stops before leave, scroll resets, restarts
  after enter — the *scroll system itself* participates in the transition lifecycle.
- **Delay as spotlight:** reveals that follow a user action wait ~200ms
  (`setTimeout(revealProjects, 200)`) so the *cause* (button press) finishes reading
  before the *effect* begins.

### Loading motion
The progress value is eased toward its target at 2%/frame — network progress is smoothed
into an organic ramp; `isReady` fires only when the eased value crosses 99.5. Lesson: the
*number* is choreography too.

---

## 7. Typography System

(One family — a variable grotesque ["Indivisible Variable", Typekit] with weight axis
110–900 — but per the brief, the system matters, not the face.)

### Measured scale (design-px)
```
200  showreel circular text context (display numerals)
80   menu links (mobile sheet ~64)
56–76 list rows, case titles (H2), 40 ≤900px
32   about intro paragraph, case descriptions, 28 ≤900px
24   case metadata headers
18/19 chrome: buttons, switch, links (19 is the ≤900px body base)
16   small info text (≤900px: 16)
14   footnotes, credits, email
```
Ratio between adjacent tiers ≈ 1.3–1.5; ratio between *content* type and *chrome* type
≈ 3–4×. The scale has a hole in the middle (no 20–22 "medium" size) — text is either
display or chrome, nothing mumbles.

### Rules extracted
- **Line-height inversely tracks size:** display sits at 0.7–1.0 (!), body at 1.3, chrome
  at 1. Tight display leading is what makes the giant lowercase stacks read as objects.
- **Negative tracking on display only:** −0.04em/−0.05em at ≥56px; chrome/body at normal.
- **Weight is meaning, not decoration:** rest 400–500; interaction *animates* weight
  (500→600 on hover — variable font as motion channel); 600–700 appears only in emphasis.
- **lowercase as voice:** every control and nav label is lowercase — chrome whispers.
  Content (titles) uses sentence case. The *case* distinction separates system from
  content, exactly like the size distinction.
- **Reading rhythm on long text:** the about intro "reads itself" — words at 50% opacity
  brighten to 100% under scroll scrub, with inline pictographs (animated icons between
  words, scale-in back.out(1.7)) pacing the sentence. Paragraph spacing = gap scale
  (24/32/40), section spacing = 60–180 tier.

---

## 8. Design Tokens (the complete extracted set)

```css
/* --- color (7 values total; that's the entire palette) --- */
--color-bg-dark:   #0a0a0a;          /* stage */
--color-bg-grey:   #171717;          /* raised dark surface */
--color-black:     #0a0a0a;          /* ink on light */
--color-white:     #fafafa;          /* light surface / text on dark */
--color-grey:      #e6e6e6;          /* secondary text on dark */
--color-pop-green: #21ffc0;          /* THE accent. stickers only. */
--color-white20:   #fafafa20;        /* hairlines on dark */
--color-bg-dark20/40/60: #0a0a0a{20,40,60}; /* scrims — alpha steps, not new colors */

/* --- radius --- */
--radius-xs 4  --radius-s 8  --radius-m 12  --radius-l 16  --radius-xl 20  --radius-full 9999
/* observed additional: 24 (media cards), 50% (round buttons) */

/* --- spacing (see §2) --- */
gaps: 10 15 20 30 45 60 90 120 180        /* component rhythm */
grid: columns calc'd; gutter 10/15/16; margin 15/20/30

/* --- easing --- */
--ease-spring (linear() sampled, ~1.4% overshoot)
--ease-expo-out cubic-bezier(.19,1,.22,1)
--ease-quad-in-out cubic-bezier(.455,.03,.515,.955)

/* --- durations (the used set) --- */
.1 .15 .2 .25 .3 .35 .4 .45 .5 .65 .7 .8 .9 1.0   /* s; ambient: 12s, 40s */

/* --- opacity steps --- */
0 .2 .4 .6 .7 1

/* --- elevation --- */
/* NO shadow system. one shadow exists (0 4px 8px #0003). elevation is expressed by:
   scrim (bg-dark60) + backdrop-filter blur(20px|1rem) + motion parallax + inverse surface */

/* --- borders --- */
--border-size: 1rem; hairlines use white20; borders are rare (cards are borderless)

/* --- viewport --- */
--vw/--vh custom props (JS-set); --ivh: 100dvh for mobile chrome correctness
--rem: 1px root scaling unit; --width-reference: 394
```

**Token philosophy observed:** tokens exist for *ratios and physics* (spacing, radius,
easing, alpha steps), not for every one-off value; the palette is small enough that alpha
variants of two colors cover all surface needs; durations are conventions rather than
variables (they live in the tempo tiers).

---

## 9. UX Decisions (screen by screen: why is this here?)

### Entry gate
- *Why a gate at all?* (1) Browsers block autoplaying audio without a user gesture — the
  gate converts a legal constraint into a brand moment; the "enter" click is the gesture
  that unlocks the ambient track. (2) It buys guaranteed-smooth WebGL (assets preload
  behind it). (3) It frames the visit as *attending* something.
- *Why is "with sound" primary and "without" a dim footnote?* Persuasion by hierarchy —
  the designer needs you to experience sound design; opting out is allowed but visibly
  the lesser path. The primary is a pill at center-eye-height; the secondary is 14px at
  the bottom edge.

### Home (spiral)
- *Why a spiral instead of a grid?* The work is motion design; a static grid would
  contradict the product. The spiral makes *browsing itself* a motion piece, and scroll
  becomes travel (depth) rather than pagination. Motion-blurred distant cards create
  focus depth-of-field — the center card is "in focus" like a camera.
- *Why is the view-switch top-center?* It's a *mode* of the whole room, not a local
  control; center placement says "this changes everything you see."
- *Why does the showreel intrude from a corner, rotated?* So it reads as a physical
  object left on the stage — noticeable forever, ignorable always. It's the highest-value
  content (the reel) given the lowest-pressure placement.
- *Cognitive load reduced:* one decision (which work), two ways to make it (feel/scan).

### Home (list)
- *Why giant text rows, no thumbnails in-layout?* Titles-as-objects keep the choice
  uncluttered; imagery arrives *at the cursor*, only for the row you're considering —
  preview exactly when relevant, never before. Sibling-dimming answers "what am I
  pointing at" without outlines or backgrounds.

### Menu
- *Why an overlay panel instead of a nav bar?* Three destinations don't justify permanent
  chrome. The overlay keeps the stage alive behind (dim+blur), reinforcing "one room."
- *Why is contact an email in the panel footer* rather than a page? A form would add a
  screen, validation, an error state, and zero extra value for a two-person conversation.
  This is ruthless scope honesty.

### Case page
- *Why does the hero video sit inset in a rounded frame instead of full-bleed?* The mat
  (background visible on all sides) presents the work as *artifact* — framed, precious;
  full-bleed would make it wallpaper.
- *Why "see the case •" → Behance instead of a longer page?* The site shows the reel of
  each work; deep documentation lives where it already exists. Again: defer what someone
  else does better (the honesty rule, verbatim).
- *Why does the page end with the next project instead of a footer?* Momentum. The visitor
  never faces a dead end; scroll inertia carries into the next case ("keep scrolling !"
  sticker literally instructs). Bounce is designed out.

### About
- *Why does the intro read itself via scroll?* It meters the pacing of a self-introduction
  (the one place the designer speaks) and demonstrates craft *in the reading experience
  itself*. Inline animated pictographs = personality without a photo shoot.

### Global
- *Why is the mute toggle bottom-right, alone?* It's a *state* control, not an action —
  parked in the least-valuable corner, always reachable, never in the way.
- *Why words instead of icons for menu/close/spiral/list?* Zero-ambiguity chrome. The
  cost (localization, width) is trivial for a personal site; the gain is instant legibility.

---

## 10. Product Thinking

### The philosophy, reconstructed
The site treats **attention as the currency and craft as the proof**. Every decision
optimizes for an uninterrupted, sensory demonstration of exactly one claim: "I make motion
and sound feel like this." The interface never *tells* you the designer is good; the
interface *is* the portfolio piece.

### User priorities (in order, as revealed by the design)
1. A creative director with 90 seconds: showreel is one click from anywhere, entry is 5s.
2. A curious browser: the spiral rewards wandering; sound rewards staying.
3. A vetting client: the list view + cases + Behance depth for due diligence.
4. (Distant) recruiters/press: about page, socials in the menu footer.

### Business priorities encoded
- **Differentiation over coverage:** two pages that no one forgets beat ten pages nobody
  remembers. The 404 deep-link flaw shows the tradeoff consciously accepted: shareability
  of individual works was sacrificed for experience continuity.
- **The product demonstrates the service** (sound design is *in* the UI; motion is *in*
  the navigation). For ChordOS the equivalent claim is: *the interface itself should feel
  procurement-grade — calm, precise, provenance-everywhere — because the interface is the
  proof of how the studio operates.*

### Conversion strategy
The funnel is: enter → feel (ambient + spiral) → watch (reel or case) → next case (loop)
→ contact (menu, one click, mailto). Conversion pressure is *near zero* on the surface —
no popups, no CTAs shouting — but the *architecture* is a conversion machine: the exit of
every content unit feeds the next one, and contact is permanently one click away in the
calm corner of the menu. Trust is built by consistency (every spring identical, every
sound mixed, every exit where you expect it) rather than by badges or testimonials.

### Retention/engagement strategy
For a portfolio, "retention" = memorability. The mechanisms: multi-sensory encoding
(sound+motion+space engage more memory channels than a grid of thumbnails); a signature
object (the smiley) repeated from loader to logo to about pictographs; and one accent
color reserved for moments of delight. You leave remembering *the feeling and the face*.

### What ChordOS should take from the product thinking (preview of doc 2)
Not the darkness, not the spiral, not the sound — but: **thresholds that guarantee
readiness; one object of attention per screen; representation switches over the same
data; exits and next-steps designed into every surface; feedback in under 100ms with
embellishment after; one spring, one accent, one voice.**

---

## Appendix A — Evidence index
- CSS token extraction: `evidence-css.txt` (341 lines, from 4 compiled stylesheets).
- JS animation/sound extraction: `evidence-js.txt` (libraries, GSAP calls, sound registry,
  Lenis config, page transitions, store logic).
- Runtime measurements: `walk-results.json` (list-enter samples, menu-open width samples
  showing spring overshoot, project DOM), `walk2-results.json` (component computed styles,
  letter-jiggle samples, tab order, ARIA audit, Escape-closes-player).
- Screenshots: 30+ states × 5 viewports (`shots/` — entry, spiral, list, hovers, cursor
  trail, menu, case top/mid/footer, about, player, mobile/tablet/wide sweeps).
- Live-site checks: project deep links return 404 (client-side-only routes); Typekit font
  `indivisible-variable` (two variable faces, wght 110–900 + italic).

## Appendix B — Stack (for reference, not prescription)
Nuxt 3 (SSR, prerendered `/` + `/about`), Vue 3 + Pinia, three.js + postprocessing (WebGL
stage, draco), GSAP + ScrollTrigger + SplitText, Lenis (wheelMultiplier .8, duration 1.2),
Howler (15 sounds, html5 audio), hls.js + Mux (video), vue3-lottie (loader/pictographs),
Sanity CMS (9 projects: title/slug/year/shortDescription/behanceUrl/thumbnail/3
styleframes/mux video), Typekit.
