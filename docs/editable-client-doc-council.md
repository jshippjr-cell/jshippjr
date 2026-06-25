# Editable Client Document — Cabinet Deliberation

**Convened:** 2026-06-25 · **Chair:** Jon Shipp (CEO) · **Mandate:** turn the
combined client document (capabilities framing + delivery-package outline) from a
fixed generated artifact into an **editable, tailorable** document the founder can
correct and customize per deal — including a drag/click **support-descriptor
library**, lead-driven delivery content, and the right ordering of price/terms.
**The cabinet deliberates and returns options + a ready-to-use descriptor library;
Jon makes the final call.**

Governing rule unchanged: **the machine proposes, Jon disposes.** The document
should make that literal — the engine drafts, Jon edits. Agents disagree where they
actually disagree.

Roster: **Head of Product** (lead), **CTO**, **CMO**, **Creative Director**,
**Head of Production**, **CRO**, **CFO**, **Founder's Advocate**.

---

## The trigger

Jon opened the combined doc for a real lead — *"Looking for a music producer for an
indie feature film,"* client shown as **"Prepared for Unknown,"** discovery stage —
and found three things wrong:

1. **"What we understand you need"** printed the *internal* qualification summary
   verbatim — *"69% aligned … → Review."* Scoring jargon, not client-facing
   (`capabilities.py:217`, `understanding = qual.fit_summary`).
2. **"Prepared for Unknown"** — the lead arrived with no company; the doc prints the
   raw fallback with no way to fix it by hand.
3. The **delivery package assumes a brand campaign** (`_BASE_DELIVERABLES`,
   `_rollout_for`) — :30/:15/:06 ad cutdowns, TV/pre-roll/Stories rollout — which is
   **wrong for a feature-film score.** It barely reads the lead (only the campaign
   name + a sonic-branding branch); everything else is a fixed standard list.

The fix Jon wants: an **editable document** with **support bubbles** he can drop into
sections, a delivery package **derived from the lead**, and price/terms that **only
appear when he chooses, and then sit at the bottom.**

---

## 1. The editing model — drag-and-drop vs click-in/click-out

**Head of Product (lead):** Jon offered the out himself — "if drag and drop is too
difficult, make it click in click out." I'd take it, and not reluctantly. **Click-to-
insert is the better primitive here**, for concrete reasons: (a) the document is also
the **print/PDF** surface — drag libraries fight `@media print` and contenteditable;
(b) Jon works on **iPad/phone**, where HTML5 drag-and-drop is famously broken on
touch; (c) click is **accessible and undoable** by default. So: tap a section to make
it active, tap a bubble in the library rail, it drops in; tap an inserted bubble to
remove it; small ↑/↓ to reorder. No drag fragility.

**CTO:** Strong agree. Native drag-and-drop on touch needs a polyfill and still feels
broken; we'd spend the budget fighting the interaction instead of building the
content. Click-to-insert is a few lines of vanilla JS, matches the app's no-framework
style, and persists trivially. If we ever want drag as a *nicety* on desktop, add it
later behind the same insert action — but it is not v1.

**CRO (dissent — partial):** I'll defend drag *only* on the feel: dropping a chip into
a doc is satisfying and "premium," and this document is a sales instrument. But I
concede the cross-device tax. Compromise I can live with: **click-to-insert now**, and
make the inserted chips visually feel like physical, removable tokens so it still
reads as tactile.

**Head of Product:** Accepted — click-to-insert, chips styled as tactile removable
tokens. Drag is a future enhancement, not v1.

---

## 2. What's editable, and where edits live

**Head of Product:** Don't make "every word" editable — that's a CMS, and it'll rot
the brand voice. Make the **high-leverage fields** editable, keep the boilerplate
fixed:
- **Editable:** the "Prepared for ___" client name, the "What we understand you need"
  synopsis, the support bubbles in each editable section, the relevant-work links, the
  delivery assumptions line, and a per-deal note. An **"Edit mode"** toggle in the
  non-printing toolbar (next to the existing section toggles) flips fields to
  editable; off, it's clean preview/PDF.
- **Fixed:** "Who we are" (the value prop — brand voice, don't let it drift), the
  rights standard, the legal terms.

**CTO:** Persistence: add a single **`doc_overrides` JSON column on `opportunities`**
(migrated the same way Phase 3/5 added columns — `_OUTREACH_COLUMNS` pattern). Keys:
`client`, `understanding`, `support_chips` (per section: list of chip ids + any custom
text), `relevant_links`, `delivery_template`, `delivery_assumptions`, `deliverable_
overrides`. The builder reads overrides **on top of** the generated defaults — so an
un-touched deal looks exactly as today, and an edited one reflects Jon's changes. One
JSON blob, not twelve columns; it's display data, never queried relationally.

**Founder's Advocate:** The non-negotiable: an edit must **survive a refresh and a
re-open** and show in the PDF. Jon's whole complaint is "I can't fix it." If edits
don't persist per-deal, we've failed. Also: a **"reset to generated"** per field, so a
bad edit isn't permanent.

**CTO:** Accepted — overrides are per-field, and clearing a field falls back to the
generated default. Reset is free with that design.

---

## 3. "What we understand you need" — make it the client's brief, not our scoring

**CMO (lead):** This is the most important fix. The section that's currently leaking
"69% aligned → Review" should be the **single most flattering paragraph in the
document** — a confident restatement of *their* brief that makes them feel understood.
Never a score, never "Review," never "buyer." The default text should be generated
from the lead's **own words** (`description` / `project_type`), e.g.:

> *"You're scoring an independent feature and need a music producer to shape its
> sound end-to-end — composition, production, and final mixes, delivered to picture."*

…then Jon edits it and drops in **support bubbles** to sharpen it.

**Creative Director:** And the bubbles in this section aren't decoration — each one is
a **craft commitment** phrased from the client's side. "Original composition" shouldn't
read as a tag; inserted, it should expand to a sentence: *"Original composition —
written for your project from a blank page, not licensed stock."* That's what makes a
bubble worth dropping in. (Full library in §4 / Appendix.)

**Founder's Advocate (dissent — scope):** Careful the auto-generated synopsis doesn't
become a *new* way to embarrass us — an LLM paraphrase of a two-line lead can hallucinate
specifics. Keep the **generated default conservative** (restate only what's in the
lead), and lean on Jon's edit + bubbles to enrich. Better a plain true sentence than a
confident wrong one.

**CMO:** Accepted — conservative generated default, enriched by hand. The bubbles carry
the polish.

---

## 4. The support-descriptor library — the cabinet's content deliverable

*Jon asked the team to "come up with some great common descriptors." Here is the
starter library, organized so a bubble can drop into the matching section. Each chip =
a short label (what Jon sees in the rail) + the sentence it inserts (what the client
reads). Full list in the Appendix; the debate is below.*

**Creative Director (lead):** Four families, because a brief has four kinds of
reassurance: **what we'll make** (craft), **how it should feel** (aesthetic), **what
you'll get** (deliverable), **why it's safe to hire us** (assurance). A good document
pulls one or two from each. I drafted ~28 chips across them (Appendix).

**Head of Production:** The "what you'll get" family must stay **honest to the
engagement type** — don't let Jon drop "broadcast masters & cutdowns" onto a *film*
brief where the deliverable is cues-to-picture. So the library should **filter by the
delivery template** (§6): film-score briefs surface film chips, campaign briefs surface
campaign chips. A chip that contradicts the deal is worse than no chip.

**CMO (dissent):** Don't over-filter. Some chips are universal ("Original & cleared,"
"Fixed scope, dependable delivery") and should always be available. Filter the
*deliverable* family by template; keep **craft / aesthetic / assurance universal.**

**Creative Director:** Agreed — deliverable chips are template-scoped; the other three
families are always available. And every section gets a **"+ Write your own"** chip
that opens a one-line input and inserts Jon's custom text as a token (Jon's explicit
ask). Custom chips can be **saved to "My chips"** so a phrase he types once is reusable.

**CFO:** Don't gold-plate the taxonomy. Ship the ~28 in the Appendix; let "My chips"
grow the library organically from real use. No admin screen to manage chips in v1.

---

## 5. Relevant-work links — make the proof specific to *this* lead

**Head of Production (lead):** Today "Relevant work" pulls generic showcase reels by
discipline (`_relevant_examples`). Jon wants to **attach a link to music that fits this
specific lead.** Add, in edit mode, a **"+ Add a relevant track"** control on that
section: a **label + URL** (and we render it as a play link; if it's a SoundCloud/
YouTube/Spotify URL we can embed a player, else a clean link). Stored in
`doc_overrides.relevant_links`. The generated reels stay as fallback when Jon hasn't
added his own.

**CMO:** Order matters — **Jon's hand-picked track for *this* client outranks the
generic reel.** A buyer who hears something close to their own brief converts harder
than one who hears our greatest hits. Hand-picked first, generic below (or hidden once
he's added his own).

**CTO:** Embeds add weight/JS to a print doc — make the **player a screen-only**
element and the link the print fallback, so the PDF stays clean. Accepted by CMO.

---

## 6. The delivery package — derive it from the lead, and show the assumptions

**Head of Production (lead):** This is the substantive build. Replace the single
brand-campaign `_BASE_DELIVERABLES` with a small set of **engagement templates**, each
a deliverables set + rollout + rights variant. Pick the template from the lead's
`project_type` + `description`; let Jon override the pick. Start with four (CFO will
hold us to not boiling the ocean):

1. **Film / TV score** — score cues to picture, a spotting session, score stems,
   M&E (music-&-effects) mix, cue sheet. *(This is what Jon's current lead actually
   needs.)*
2. **Brand / advertising campaign** — the existing set (anthem, :30/:15/:06 cutdowns,
   social verticals, rollout map).
3. **Sonic identity / branding** — sonic logo + variations, app/UI cues, usage guide.
4. **Artist / song production** — produced master, instrumental, TV track, stems.

**Each delivery section opens with an explicit assumptions banner** — Jon's exact
request to "just want to know the assumptions":

> *"Assumed engagement: **feature-film score** (~20–30 cues, delivered to picture).
> Not right? Switch template or edit below."*

**CTO:** Template selection = keyword match on `project_type`/`description` (film/score/
feature → template 1; spot/campaign/brand → 2; logo/sonic/mnemonic → 3; song/artist/
single → 4), with a **manual override dropdown** so a wrong guess is one click to fix.
Deliverable lines remain individually editable/removable (stored in
`deliverable_overrides`). No fabricated specifics — still *types* of assets, never fake
filenames/dates.

**CFO (dissent — scope guard):** Four templates, hand-authored, no more in v1. Do
**not** build a template editor or a per-discipline matrix now — that's a project. Four
covers the real inbound mix; add a fifth only when a real lead doesn't fit.

**Founder's Advocate:** And the assumptions banner is **mandatory, not optional** — if
the doc makes an inference, it says so, every time. That's the whole trust mechanism.

---

## 7. Price + terms placement — hidden in discovery, and at the bottom when shown

**CRO (lead):** Jon settled the policy: **don't show price/terms on a scoping-call
(discovery) doc** — keep the current default that hides them. But **when he toggles
them on, they belong at the bottom**, as the document's closing ask. Today the section
order is fixed by template position; we need them to **always render last**, after the
delivery package, regardless of toggle.

**CMO:** This is correct sales structure, not just a preference: the buyer should read
**value → understanding → team → proof → what they'll receive → *then* price → terms →
sign/pay.** Money lands after they want it. So the rule is unconditional: **whenever
cost/terms are on, they are the final blocks**, in the order Investment → Terms →
(later) sign/pay.

**CTO:** Trivial — move the cost/terms/DocuSign blocks to the end of the template and
gate on their toggles; the Phase-6 Stripe "Pay deposit" button rides at the very
bottom with them. No logic change, just order + a guarantee they're last.

**Head of Product:** And in discovery they stay **off by default** (unchanged), so a
scoping-call doc never shows a number unless Jon deliberately flips it. Both halves of
Jon's rule satisfied.

---

## 8. The two display bugs (fold into the edit work)

**Head of Product:** Both are absorbed by §2–§3, noting them so they're not lost:
- **"Prepared for Unknown"** → the client field becomes editable (and we improve the
  promote-time fallback to "this engagement" instead of "Unknown" when no company).
- **Understanding = jargon** → replaced by the conservative client-facing synopsis
  (§3), never `qual.fit_summary`.

---

## Decisions for the founder (Jon decides — cabinet recommendation in *italics*)

1. **Editing interaction (§1).** *Recommend **click-in/click-out** (tap-to-insert,
   tap-to-remove, ↑/↓ reorder), chips styled as tactile tokens; drag deferred.* —
   Your call: click (rec.) / insist on drag.
2. **Editable scope + persistence (§2).** *Recommend editable = client name,
   understanding, support chips, relevant-work links, delivery assumptions/lines;
   fixed = value prop, rights, legal terms. Per-deal `doc_overrides` JSON, with
   per-field "reset to generated."* — Confirm scope.
3. **Understanding section (§3).** *Recommend a conservative auto-synopsis from the
   lead's own words, enriched by support chips; never the scoring summary.* — Confirm.
4. **Descriptor library (§4 + Appendix).** *Recommend shipping the ~28 starter chips in
   four families (craft / aesthetic / deliverable / assurance), deliverable family
   template-scoped, others universal, plus "+ Write your own" with save-to-"My chips."*
   — **Review the Appendix and strike/add any chips.**
5. **Relevant-work links (§5).** *Recommend a per-deal "+ Add a relevant track"
   (label + URL, screen-only player, hand-picked outranks generic reels).* — Confirm.
6. **★ Lead-driven delivery templates (§6).** *Recommend four hand-authored templates
   (Film/TV score · Brand campaign · Sonic identity · Artist/song), auto-picked from
   the lead with a manual override, each opening with a mandatory assumptions banner.*
   — Your call: four (rec.) / different set / more.
7. **Price + terms placement (§7).** *Settled per your direction: off in discovery;
   when toggled on, always render **last** (Investment → Terms → pay), Stripe button at
   the very bottom.* — Confirm.

Build order if greenlit (cheap/high-value first): **#3 understanding fix + #2 edit
shell → #7 ordering → #4 chip library → #1 insert interaction → #5 relevant links →
#6 delivery templates.**

---

## Appendix — the starter support-descriptor library

*Label (what Jon sees) → inserted sentence (what the client reads). Strike or edit
freely; "+ Write your own" covers anything missing.*

**Craft — "what we'll make"** *(universal)*
- **Original composition** → "Original composition — written for your project from a blank page, not licensed stock."
- **Score to picture** → "Scored to your edit — music written to hit the story's beats, cue by cue."
- **Production & arrangement** → "Full production and arrangement — from first sketch to a finished, mix-ready record."
- **Topline / song writing** → "Topline and song writing — memorable melody and lyric built around your message."
- **Sonic identity** → "A sonic identity — a short, ownable musical signature that travels across everything you make."
- **Arrangement for multiple cuts** → "Arranged so one piece flexes into every length and format you need."

**Aesthetic — "how it should feel"** *(universal)*
- **Brand aesthetic** → "Tuned to your brand's aesthetic — the sound matches the look and the voice."
- **Cinematic / orchestral** → "A cinematic, orchestral palette — scale and emotion without the stock-music sheen."
- **Warm & hopeful** → "Warm, hopeful, human — music that leaves the audience feeling something."
- **Modern & current** → "Contemporary production that sounds current, not dated on arrival."
- **Gritty / textural** → "Gritty, textural, real — character over polish where the story calls for it."
- **Minimal & restrained** → "Restrained and minimal — space and intention, never wall-to-wall."

**Deliverable — "what you'll get"** *(template-scoped)*
- *(Film/TV)* **Cues to picture** → "Every cue delivered to picture, conformed to your locked edit."
- *(Film/TV)* **Score stems + M&E** → "Full score stems and an M&E mix for dub-stage flexibility and international versions."
- *(Film/TV)* **Spotting session** → "A spotting session up front so we agree where music lives before a note is written."
- *(Campaign)* **Broadcast masters** → "Broadcast-ready masters plus an instrumental/TV mix."
- *(Campaign)* **Multi-format cutdowns** → "All the cutdowns you need — :30, :15, :06 — and 9:16 social verticals."
- *(Sonic ID)* **Logo + variations** → "A primary sonic logo plus short/long variations for every placement."
- *(Artist/song)* **Produced master + stems** → "A produced master, instrumental, TV track, and the stems."
- *(universal)* **Stems for flexibility** → "Delivered with stems, so the music can be re-versioned as your campaign grows."

**Assurance — "why it's safe to hire us"** *(universal)*
- **Original & cleared** → "100% original and cleared — no samples, no third-party masters, no PRO surprises."
- **Full buyout** → "Delivered as a full buyout — you own it, worldwide, in perpetuity."
- **Fixed scope & timeline** → "A fixed scope and a dependable timeline — no open-ended creative drift."
- **Vetted craft team** → "Made by a vetted craft team matched to your brief, not a faceless library."
- **Revisions included** → "Revision rounds built into the scope — we land it, together."
- **One accountable partner** → "One accountable partner from brief to final delivery."
- **+ Write your own** → *(opens a one-line input; inserts Jon's text; offer "save to My chips")*
