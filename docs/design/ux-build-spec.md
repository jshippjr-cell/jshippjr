# ChordOS UI Build Specification

> **Hand-off document.** A front-end engineer should be able to implement everything here
> without reading the teardown. Derived from the forensic analysis of pacomepertant.com
> (`ux-teardown-pacomepertant.md`) translated to Chordential's brand and constraints
> (`ux-translation-chordos.md`). Stack: server-rendered Jinja templates + one
> `static/style.css` + vanilla JS. No frameworks. All motion is progressive
> enhancement — every screen must be fully functional with JS disabled and with
> `prefers-reduced-motion: reduce`.

---

## 1. Design tokens (add to `:root` in `static/style.css`)

Keep every existing Chordential token. Add:

```css
:root {
  /* ---- motion ---- */
  --ease-out:  cubic-bezier(.19, 1, .22, 1);        /* optical: opacity, color */
  --ease-inout: cubic-bezier(.455, .03, .515, .955); /* two-sided moves */
  --ease-spring: linear(
    0, .0036 1.2%, .0185 2.7%, .0863 6.4%, .2100 10.6%, .3312 13.8%,
    .5320 18.6%, .7050 23.2%, .8375 27.7%, .9250 31.8%, .9765 36%,
    1.0030 40.4%, 1.0120 45.5%, 1.0115 52%, 1.0060 61%, 1.0015 74%, 1
  ); /* ~1.2% overshoot, settles once, no second bounce. physical: transform,
        width/height, panel movement. NEVER on opacity or color. */

  --t-micro: .15s;   /* pressed states, icon swaps, focus rings        */
  --t-react: .25s;   /* hover feedback, dims, pill flips, dismissals   */
  --t-move:  .4s;    /* content enter, row/card arrival, crossfades    */
  --t-panel: .6s;    /* drawers, modals, covers                        */

  /* ---- attention ---- */
  --dim-sibling: .55;   /* de-emphasized peers on hover/focus-within */
  --dim-stack-2: .4;    /* second item in a focus stack  */
  --dim-stack-3: .25;   /* third+ item in a focus stack  */

  /* ---- elevation (blur+scrim, not heavier shadows) ---- */
  --scrim: rgba(31, 30, 30, .4);      /* ink at 40% behind drawers/modals */
  --scrim-blur: 6px;                  /* backdrop-filter for open drawers */

  /* ---- spacing rhythm (document surfaces; component spacing keeps current values) ---- */
  --gap-xs: 10px; --gap-s: 15px; --gap-m: 30px; --gap-l: 60px; --gap-xl: 90px;
}

/* Hard rule enforced by convention + review:
   transform / width / height / inset  →  var(--ease-spring)
   opacity / color / background        →  var(--ease-out) or ease
   Every exit duration = 0.6 × its entrance duration. */

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
  }
}
```

**Type contract** (audit existing screens against this; no new fonts):
- Display (one per page): 22–28px, weight 700–740, letter-spacing −0.4px, ink.
- Body: 13.5–15px, weight 400–500, line-height 1.35–1.5.
- Chrome: 11–12px, `--muted`, used for labels/meta/pills. Nothing between 16–20px unless
  it is a KPI value.

---

## 2. Component specs

### 2.1 `.btn-live` — THE primary action (one per screen, no exceptions)
```css
.btn-live {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--accent); color: #fff;
  border: 0; border-radius: 999px;             /* pill */
  height: 40px; padding: 0 22px 0 16px;        /* asymmetric: dot lane on right */
  font-size: 13.5px; font-weight: 650; cursor: pointer;
  transition: transform var(--t-react) var(--ease-spring),
              background-color var(--t-react) ease,
              box-shadow var(--t-react) ease;
}
.btn-live .dot {
  width: 6px; height: 6px; border-radius: 50%; background: #fff;
  animation: dot-breathe 2s ease-in-out infinite;
  transition: transform var(--t-react) var(--ease-spring);
}
@keyframes dot-breathe { 0%,100% { opacity: .5 } 50% { opacity: 1 } }
.btn-live:hover { transform: translateY(-1px); box-shadow: var(--shadow); }
.btn-live:hover .dot { transform: translateX(2px); }
.btn-live:active { transform: translateY(0) scale(.98); transition-duration: var(--t-micro); }
.btn-live:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
```
Markup: `<button class="btn-live">Qualify this opportunity <span class="dot"></span></button>`
- **Usage rules:** exactly one per screen; it names the *state machine's* next action
  (Qualify / Schedule discovery / Send brief / Confirm all / Approve / Release). All other
  buttons keep the existing `.btn` styles. When the state advances, the *new* next action
  receives `.btn-live` and the old one demotes to `.btn` — primary is a role, not a color
  that accumulates.

### 2.2 Status / provenance pill (`.pill`)
```css
.pill {
  display: inline-flex; align-items: center; gap: 5px;
  height: 20px; padding: 0 9px; border-radius: 999px;
  font-size: 11px; font-weight: 650; letter-spacing: .1px;
  border: 1px solid var(--border2); background: var(--panel); color: var(--ink);
  transition: background-color var(--t-react) ease, color var(--t-react) ease;
}
.pill--machine  { background: var(--panel);  color: var(--olive); }   /* machine · proposed */
.pill--human    { background: #fff;          color: var(--ink); border-color: var(--border2); } /* you · confirmed */
.pill--review   { background: #FBEFE4;       color: var(--accent); border-color: #F2D9C2; }     /* needs review */
.pill--conflict { background: #F6E9EB;       color: var(--wine);  border-color: #E8D3D7; }      /* conflict */
.pill--done     { background: var(--wine);   color: #fff; border-color: var(--wine); }          /* terminal states */
```
- **Rules:** pills annotate, never act (clickable elements are buttons/links styled as
  such). Provenance pills always carry source + date (`machine · transcript 07-02`).
  Facts / insights / recommendations / open questions each use a *distinct* pill variant —
  never the same pill in different colors. On client-facing documents only, corner-pinned
  pills may rotate −2 to 2° ("sticker" flavor); operator UI keeps them level.

### 2.3 Drawer (right-side action panel)
For Schedule Discovery / Compose / Update Intelligence / Review detail — anywhere the
operator acts *on* an entity without leaving it.
```css
.drawer-backdrop {
  position: fixed; inset: 0; background: var(--scrim);
  backdrop-filter: blur(var(--scrim-blur)); -webkit-backdrop-filter: blur(var(--scrim-blur));
  opacity: 0; pointer-events: none; transition: opacity var(--t-move) ease; z-index: 60;
}
.drawer {
  position: fixed; top: 0; right: 0; bottom: 0;
  width: min(520px, 92vw);
  background: var(--card); border-left: 1px solid var(--border);
  border-radius: 16px 0 0 16px;
  transform: translateX(105%);
  transition: transform var(--t-panel) var(--ease-spring);
  z-index: 61; overflow-y: auto; visibility: hidden;
}
.drawer.open            { transform: translateX(0); visibility: visible; }
.drawer-backdrop.open   { opacity: 1; pointer-events: auto; }
.drawer.closing         { transition-duration: calc(var(--t-panel) * .6); } /* leave < enter */
```
Behavior contract (implement once in `ui.js`):
- Content = the existing server-rendered form partial, fetched into the drawer;
  the standalone route remains as no-JS fallback.
- ✕ close button **always top-right** inside the drawer (36px round, `--panel` bg, ink ✕).
- Escape closes. Backdrop click closes. Focus is trapped while open; on close, focus
  returns to the trigger. When closed: `visibility: hidden` + `inert` (no tab-reachable
  ghost UI).
- On successful submit: drawer closes (0.36s), then the affected page region re-renders
  and **arrives** (see 3.2 enter animation) — state changes are witnessed.

### 2.4 View switch (`.viewswitch`)
Same-data representation toggle (lanes↔table, timeline↔checklist, cards↔table).
```css
.viewswitch { display: inline-flex; align-items: center; gap: 10px; font-size: 12.5px; }
.viewswitch button {
  background: none; border: 0; padding: 4px 2px; cursor: pointer;
  color: var(--muted); opacity: .55; font-weight: 600;
  transition: opacity var(--t-react) ease, color var(--t-react) ease;
}
.viewswitch button.active { color: var(--ink); opacity: 1; }
.viewswitch .sep { width: 4px; height: 4px; border-radius: 50%; background: var(--border2); }
```
- Placement: top-center of the content region (it changes *everything you see*).
- Switching: old view leaves (rows translateY(10px)→fade, `--t-react`, stagger 30ms),
  new view enters (translateY(-10px)→0 + fade, `--t-move`, stagger 40ms, 150ms delay).
  Persist choice per surface in `localStorage` (`chordential.view.<surface>`).

### 2.5 Focus stack (Review Queue)
```css
.qstack .qitem { transition: opacity var(--t-react) ease, transform var(--t-move) var(--ease-spring); }
.qstack .qitem[data-pos="0"] { opacity: 1; }
.qstack .qitem[data-pos="1"] { opacity: var(--dim-stack-2); transform: scale(.985); }
.qstack .qitem[data-pos="2"] { opacity: var(--dim-stack-3); transform: scale(.97); }
```
- Deciding pos-0 (confirm/dismiss): it translates Y −12px + fades out over `--t-react`;
  every item promotes one position over `--t-move`; the counter updates. Auto-advance,
  no page reload (form posts via fetch; full-page post remains the fallback).
- Keyboard: `j/k` moves a visible focus ring through items, `Enter` = primary decision,
  `x` = dismiss. Focus ring: `outline: 2px solid var(--accent); outline-offset: 2px`.

### 2.6 Sibling dim (utility)
```css
.dim-peers:hover > .dimmable         { opacity: var(--dim-sibling); }
.dim-peers:hover > .dimmable:hover   { opacity: 1; }
.dimmable { transition: opacity var(--t-react) ease; }
```
Apply `dim-peers` to: lane column inner (`.opp-card` = dimmable), table `tbody`
(`tr` = dimmable), CI field list, roster grids, buyer-graph node layer (JS applies
class to SVG nodes). Never combine with heavy hover decoration on the target — the
subtraction *is* the highlight (keep the existing subtle border-color change).

### 2.7 Hover peek (popover chip)
```css
.peek {
  position: absolute; z-index: 50; max-width: 300px;
  background: #fff; border: 1px solid var(--border); border-radius: 12px;
  box-shadow: var(--shadow); padding: 10px 12px;
  transform: scale(.92); opacity: 0; transform-origin: var(--peek-origin, top left);
  transition: transform .3s var(--ease-spring), opacity .2s ease;
  pointer-events: none;
}
.peek.show { transform: scale(1); opacity: 1; }
```
- Opens after 150ms hover intent (and on focus); closes in `--t-micro` (leave < enter).
- Content: entity name, 2–3 chrome-size facts, status pills. **Identifies, never acts** —
  no buttons inside; clicking the underlying element navigates.

### 2.8 Progress (eased) — replaces spinners
```css
.progress-hairline { height: 2px; background: var(--panel2); border-radius: 1px; overflow: hidden; }
.progress-hairline > i { display: block; height: 100%; background: var(--accent); width: 0; }
```
```js
// ui.js — eased progress: value pursues target at 4%/frame; done fires ≥99.5
function easedProgress(el, getTarget, onDone) {
  let v = 0; const bar = el.querySelector('i');
  (function tick() {
    v += (getTarget() - v) * 0.04;
    bar.style.width = v + '%';
    if (v >= 99.5) { bar.style.width = '100%'; onDone && onDone(); return; }
    requestAnimationFrame(tick);
  })();
}
```
Use for: transcript analysis, brief generation, package assembly. Label always states the
verb ("Analyzing transcript…"). Indeterminate work still uses this with target 90 until
the server responds, then 100 — motion stays organic, and the bar never lies backwards.

### 2.9 The mat (framed document surface)
```css
.mat-field { background: var(--panel); padding: var(--gap-m); border-radius: 18px; }
.mat      { background: #fff; border: 1px solid var(--border); border-radius: 14px;
            box-shadow: var(--shadow-sm); overflow: hidden; }
```
- Use for: Proposal preview, Brief evidence blocks, Evidence transcript panel, Delivery
  package chapters. Rule: what's inside `.mat` on an operator screen is exactly what the
  client sees — editing chrome lives outside the frame.

### 2.10 Threshold cover (client-facing pages only)
Brief / Delivery portal / meeting-manage token pages.
- Structure: full-viewport section on `--bg`: chrome-size context line (buyer name),
  display-size statement (campaign need), sticker pills (prepared-by, date), scroll hint.
- Assets below preload while the cover is visible (`loading="eager"` above fold,
  content sections `content-visibility: auto`).
- Cover content enters on load: three elements stagger 80ms, rise 12px, `--t-move`.
- **Never** on operator screens. No click-gates anywhere — scroll is the consent.

### 2.11 Enter animation (content arrival)
```css
.arrive { opacity: 0; transform: translateY(10px); }
.arrive.in { opacity: 1; transform: none;
  transition: opacity var(--t-move) ease, transform var(--t-move) var(--ease-spring); }
```
```js
// ui.js — stagger arrivals; cap total at 300ms regardless of count
const io = new IntersectionObserver(es => es.forEach(e => {
  if (!e.isIntersecting) return;
  const kids = [...e.target.querySelectorAll('.arrive')];
  const step = Math.min(40, 300 / Math.max(kids.length, 1));
  kids.forEach((k, i) => setTimeout(() => k.classList.add('in'), i * step));
  io.unobserve(e.target);
}, { rootMargin: '0px 0px -5% 0px' }));
document.querySelectorAll('[data-arrive]').forEach(el => io.observe(el));
```
- Apply `data-arrive` to: KPI rows, lane columns, CI field list, brief/proposal sections
  (client view), queue batches. **Never** to sidebar/topbar/sub-nav (chrome pre-exists).
- Triggered `once`; scrolling back up never re-animates.

---

## 3. Interaction rules (global contracts)

1. **Acknowledge <100ms, embellish after.** Hover/press feedback starts immediately
   (`--t-micro/--t-react`); arrival choreography (`--t-move/--t-panel`) rides on top.
2. **Leave < enter** — exits at 0.6× entrance duration, sitewide.
3. **State changes are witnessed:** any mutation triggered from a drawer/inline action
   re-renders the affected region with `.arrive` — never a silent full-page swap when JS
   is available (full-page reload remains the no-JS path).
4. **Exits:** every layer (drawer, modal, peek) closes via ✕ top-right *and* Escape *and*
   backdrop click. No layer traps the user.
5. **Momentum tails:** every terminal action answers "what's next" in-place — queue
   auto-advances; opportunity footer names the next best action with the *only*
   `.btn-live`; debrief links to the CI it changed; delivery stage points at the next
   agent. A screen may never end in a void.
6. **One primary:** exactly one `.btn-live` per rendered page. CI review states may
   temporarily move it (e.g., "Confirm 6 updates" outranks "Send brief" until resolved) —
   the state machine, not the template, decides.
7. **Orange is action, never status.** Status = pills (sand/slate/wine variants). If
   orange appears anywhere non-interactive, it's a bug.
8. **Pills annotate, buttons act, peeks identify** — no hybrids.

---

## 4. Layout & spacing rules

- Grid: keep Chordential's current layout system. For *new* client-facing documents:
  content column `max-width: 720px`, page margin ≥ `--gap-m`, section spacing `--gap-l`,
  intra-section `--gap-s/--gap-m`. Use the gap scale; no ad-hoc verticals.
- The type contract (§1) governs every screen: one display element, body, chrome —
  nothing in the 16–20px dead zone.
- Density belongs to the operator: console screens keep current compact spacing; only
  client-facing surfaces adopt the airier document rhythm.
- Empty states (queues, lanes): chrome-size line + one action, centered in the region —
  never a bare "No items."

## 5. Responsive behavior

- Keep existing breakpoints; verify the five-anchor rule survives mobile: title top-left,
  primary action visible without scroll (sticky footer bar ≤640px: the `.btn-live`
  docks bottom, full-width, safe-area padded), nav via existing burger.
- Drawers become full-width sheets ≤640px (border-radius 16px 16px 0 0, slide from
  bottom, same physics).
- Hover-dependent features (peeks, sibling-dim) gate behind
  `@media (hover:hover) and (pointer:fine)`; touch gets tap-to-peek (first tap peeks,
  second navigates) only where peek adds real value (buyer graph); otherwise skip.
- The mental model never changes across devices — same anchors, same components, denser.

## 6. Accessibility (fixes the source site's real flaws)

- `prefers-reduced-motion: reduce` collapses all motion (§1 block). Eased progress bars
  render instantly at their target value.
- Visible focus: `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }`
  on every interactive element. Never `outline: none` without a replacement.
- Closed layers are `inert` + `visibility: hidden` — nothing off-screen is tabbable.
- Focus trap in open drawers/modals; focus returns to trigger on close.
- Icon-only buttons carry `aria-label` (mute/close/✕). Pills that convey state also exist
  as text for screen readers (they're real text — keep it that way).
- Landmarks: every page keeps `nav` + `main`; drawers are `role="dialog"
  aria-modal="true"` with `aria-labelledby`.
- Contrast: dimmed siblings (0.55 on ink) still pass AA for large text; dimmed *chrome*
  must not carry sole meaning — dimming is always redundant with position/pills.
- Every entity URL stays stable, shareable, server-rendered (the anti-404 lesson).

## 7. State management

- **Server state is truth** (SQLite via existing routes). JS never owns entity state.
- **UI state** (view-switch choice, drawer open, queue position) lives in DOM +
  `localStorage` (`chordential.view.*`), read on load, never blocking render.
- **Optimistic UI is forbidden** for decisions (machine proposes, Jon disposes — a
  confirm must round-trip before the pill flips). The witnessed-arrival pattern (§3.3)
  makes the round-trip *feel* instant without lying.
- **Progressive enhancement seam:** `ui.js` binds by `data-*` attributes
  (`data-drawer-src`, `data-arrive`, `data-peek`, `data-viewswitch`, `data-qstack`);
  templates render complete, functional HTML without it. This is the null-provider
  pattern applied to the front end.

## 8. Implementation order (each step ships alone, suite stays green)

1. Tokens + reduced-motion block + focus-visible + type-contract audit (pure CSS).
2. `.pill` system → CI panel + queue + lanes (replaces ad-hoc badges; visual only).
3. `.arrive` + `ui.js` IntersectionObserver (dashboard, detail, brief client view).
4. `.btn-live` + one-primary audit per screen (template-level, no logic changes).
5. Sibling-dim on lanes/tables/CI list; hairline eased progress on intake analyze.
6. Drawer component → Schedule Discovery first (route stays as fallback), then Compose,
   then Update Intelligence.
7. View switches (pipeline, workspace, roster) + localStorage persistence.
8. Review Queue focus stack + keyboard + auto-advance.
9. Client-facing: Brief cover/threshold + mat blocks + momentum tail; then Delivery
   portal cover; then scheduler request/manage pages.
10. Peeks (buyer graph last — SVG integration is the fiddly one).

Acceptance for every step: works without JS; works with reduced motion; exits per §3.4;
one primary per screen; no orange-as-status; tab order sane with visible focus.
