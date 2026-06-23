# Capability Demos — Look, Feel & Marketing Council

*Board simulation. CMO leads (per CEO directive). The question: how should the
public "Capability demos" page look, feel, and read — and how do we present
demonstrations **without** signalling inexperience or implying client work we
haven't done? Grounded in `cmo-positioning-brief.md` (Music Opportunity
Intelligence → human original-craft) and `company-definition.md`. Agents are
required to disagree; the CEO ratifies.*

Date: 2026-06-23.

---

## The trigger

The demos page shipped with this lede:

> *"Chordential is a new studio, so these aren't client commissions — they're
> demonstrations of how we'd approach a brief and the craft we bring to it."*

The founder's objection: **it turns buyers away.** It leads with our weakness
(new, no clients) instead of our strength (the music and the thinking). Separately,
the home page still says **"Recent work"** with case studies that imply real
engagements — an honesty problem in the other direction. The council must reconcile
**confident marketing** with **literal truth**.

---

## 1. The copy — CMO (lead)

**CMO:** Buyers don't buy your tenure; they buy their own outcome. The old lede
commits the cardinal sin of *apologising before you've played a note*. But the fix
is **not** to fake a client roster — it's to **reframe the frame**. A demonstration
isn't a lesser case study; for a craft studio it's the *purest* proof: "here is a
brief, here is what we'd do with it." That's confident **and** true.

The move: **lead with the brief and the buyer, never with our age.** Drop "new
studio," drop "aren't client commissions." Replace with language that treats each
demo as an answer to a real creative problem — which is exactly what it is.

Ratified copy:
- **Eyebrow:** `Capability Demonstrations`
- **Headline:** `Built to brief.`
- **Lede:** *"Every track here answers a campaign brief — an objective, a creative
  challenge, and our response in music. Press play for the sound; open the brief to
  see how we'd score yours."*

**Founder's Advocate (dissent):** "Built to brief" is strong, but make sure we
*never* state or imply these were paid jobs. Use **scenario/brief** language, never
**client/commission**. — *Accepted; the copy says "campaign brief," not "client."*

**Head of Production:** Good — and the per-demo framework (Objective / Creative
Brief / Approach / What It Demonstrates) already reads as a *method*, not a
testimonial. That's the honest tell that these are demonstrations. Keep it.

**CFO:** Cheap to change, high leverage. No objection — but kill the word "Sample"
chips and "asset coming" placeholders too; half-finished is worse than confident.

---

## 2. The honesty sweep — Founder's Advocate + Head of Production

**Founder's Advocate:** We cannot fix the demos page and leave the **home page
lying.** "Recent work" + "How we solved it / Outcome: *Approved without reopening
the creative conversation*" reads as a delivered client engagement. That's the
exact misrepresentation the demos page is trying to avoid. Unify them: the home
"work" section becomes the **same capability demonstrations**, framed identically.

**Head of Production:** Agreed. One vocabulary across the site: **Demonstrations**,
**briefs**, **approach** — never "recent work," "outcome," "engagement," "clients."
The process/delivery promises (clean files, clear rights) can stay, but phrased as
*how we deliver* (a standard), not *how it went* (a history).

Ratified sweep:
- Home **"Recent work"** → **"Capability Demonstrations"**; headline → *"Hear how
  we'd score your brief."*; **"See all work →"** → **"Open the full briefs →"**.
- Home featured cases (fabricated challenge/solved/**outcome**) → replaced by the
  real demo tracks, players included, each linking to `/samples`.
- **"Every engagement ends the same way…"** → **"We deliver the same way every
  time…"** (a standard, not a track record).
- Keep **"Built for teams across — Brands & agencies · Film & TV · Games ·
  Creators"** — that's market *fit* (who it's for), not a client claim. Honest.

---

## 3. Look & feel — CMO + design

**CMO:** Right now the demos sit in plain white cards on a light band — it reads
"portfolio template," not "premium music house." The brand has a strong palette
(wine `#44161E`, orange `#E4671F`, cream `#FCF7F8`, charcoal). **Use it.** Move the
demos onto a **dark, cinematic band** — continuous with the page's charcoal header —
and give each bubble a branded treatment so the page *feels* like the sound: warm,
considered, high-end.

Ratified aesthetic:
- **Dark band** behind the demos (charcoal→wine), cream type — premium, matches the
  hero film.
- **Branded bubbles:** deep wine-charcoal card, a thin **orange top-accent bar**, a
  subtle orange border that **warms on hover** with a gentle lift; discipline label
  and the *"See how we'd approach this brief"* toggle in brand **orange**; the audio
  player on a dark inset.
- **Consistency home ↔ demos:** the home featured demos use the same branded
  bubbles and the same tracks, so clicking through feels like one continuous story.

**CTO:** Keep it CSS-only — no JS framework for a marketing page. `<details>` for the
expand, native `<audio>` for the players, brand tokens already in `site.css`. Cache
the audio with `preload="none"` so the page stays fast. — *Accepted.*

**CFO:** One concern — four 4MB audio files autoplaying nothing is fine, but don't
let the page balloon. `preload="none"` + lazy is the rule. — *Accepted.*

---

## 4. Tie the home players into the demos page — CRO

**CRO:** The home page is the top of funnel; the demos page is the proof. They must
be **one motion**. So: the home "work" section shows the actual demo tracks (real
players, not placeholders), and every card + the section CTA routes to `/samples`
for the full brief. Also retarget the **hero's primary button** from the vague
"View Work" to **"Hear the demos" → /samples** — point the very first click at the
strongest asset. — *Accepted by CMO.*

---

## Ratified decisions (what gets built)

1. **New demos copy:** eyebrow *Capability Demonstrations*, headline *Built to
   brief.*, the confident buyer-facing lede above. No "new studio," no "clients."
2. **Honesty sweep on home:** "Recent work" → "Capability Demonstrations"; replace
   fabricated case outcomes with the real demo players; "See all work" → "Open the
   full briefs"; "Every engagement ends…" → "We deliver the same way every time…".
3. **Branded, dark demo bubbles** (wine-charcoal card, orange accent bar + hover,
   cream type) on a dark band — on **both** the demos page and the home feature.
4. **One funnel:** home demo players + hero primary CTA route to `/samples`.
5. **Truthful market line kept:** "Built for teams across…" stays.

**CEO ruling:** Approved. Confidence and honesty are not in tension — the fix is to
market the *demonstration* as the proof, not to apologise for it or fake a history.
Build it.
