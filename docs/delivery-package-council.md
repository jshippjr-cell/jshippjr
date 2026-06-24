# Demo Agency Delivery Package — Design Council (CMO-led)

*Board simulation. **CMO leads** (per CEO directive). Goal: design a **demo delivery
package** — the branded artifact a creative agency / producer / brand team receives
from a premium music vendor — to showcase in the site's **"What Delivery Actually
Looks Like"** section. Eight documents, Chordential-branded. This doc is the design
spec + the website-integration plan. **Nothing ships to the site until Jon approves.***

Date: 2026-06-24.

---

## Why this exists (CMO framing)

Our positioning is *"clarity, control, and confidence in delivery"* — but the site
currently *asserts* that with a bullet list. **Buyers don't believe assertions; they
believe artifacts.** A premium agency producer has received hundreds of deliveries;
the package itself is the proof of operational maturity. So the demo package must look
like it came from a vendor who has done this a thousand times — not a startup's first
attempt (which is exactly what the ReportLab draft reads as).

**The standard to beat:** the music-industry cue sheet Jon referenced — dense, formal,
trusted. Ours should feel *that* credible but *designed*, not clerical.

**Truthfulness rule (carried from the demos work):** every page is watermarked
**SAMPLE / DEMONSTRATION** and uses a clearly fictional campaign. We are showing
*format and rigor*, not claiming a real client.

---

## Shared design system (applies to all 8)

**CMO:** one system so the package reads as a single premium object.
- **Palette:** charcoal `#1F1E1E` ink, **wine `#44161E`** for headers/letterhead,
  **orange `#E4671F`** as the single accent (rules, status ticks, the "o" mark),
  cream `#FCF7F8` / sand `#D8CDB6` for panels. Generous white space.
- **Type:** serif display (the brand serif) for titles; clean sans for tables/data.
- **Furniture:** every page carries the **chordential wordmark letterhead**, a thin
  wine rule, a footer with `Package ID · campaign · page x/8 · "Prepared by Chordential"`,
  and a faint **SAMPLE** watermark.
- **Demo campaign (fictional):** **AURORA Outdoor Co. — "Find Your Horizon" (Spring 2026)**,
  via **Northlight Creative (sample agency)**. Deliverable: original :60 anthem +
  :30/:15/:06 cutdowns + a sonic logo.

**Head of Production (input):** the data must be *internally consistent* across all 8 —
the same cue names, durations, version numbers, and file names everywhere. A producer
will cross-check; one mismatch and the illusion of rigor collapses. — *Accepted as a
hard requirement.*

---

## The eight documents

### 1. Branded cover page
- **Shows the buyer:** taste and seriousness in the first 2 seconds.
- **Design:** near-full-bleed charcoal/wine, the wordmark large, campaign title in
  serif, a restrained metadata block (client, agency, package ID, delivery date,
  "Final — Approved"). One orange hairline. No clutter. Cinematic, like a title card.

### 2. Deliverables manifest
- **Shows:** completeness — *everything* promised is here, nothing loose.
- **Design:** a clean table — Asset · Format/Spec (WAV 24-bit/48k, MP3 320) · Duration ·
  Status (orange ✓ Delivered). Grouped: Masters / Cutdowns / Social verticals / Sonic
  logo / Stems / Alt mixes (instrumental, TV mix) / Documentation. A count chip up top
  ("23 assets · 100% delivered").
- **CFO (input):** include the deposit/balance line as *Paid* — closes the money loop
  visibly. — *Accepted (subtle, in the footer band).*

### 3. Music asset map
- **Shows:** the **version naming system** — anyone on the campaign can find any file.
- **Design:** the folder tree (monospace) + a legend decoding the convention
  `AURORA_Anthem_60_MASTER_v3_FINAL.wav` → CAMPAIGN_CUE_LENGTH_ROLE_VERSION_STATE.
  This is the "named so anyone can find them" promise, made literal.

### 4. Version tree visualization
- **Shows:** *controlled* variation — "3 controlled variations, not an open-ended
  revision spiral" (our core process claim), made visual.
- **Design:** a left-to-right node tree: **v1 Concept → v2 Direction Lock → v3 FINAL
  (Approved)**, with bounded branches (e.g., v2 → :30/:15/:06 cutdowns, alt-mix). Approved
  node ringed in orange. A small caption: "Locked in 3 rounds."
- **CTO (input):** pure CSS/SVG, no JS — it must print cleanly. — *Accepted.*

### 5. Rights & ownership certificate
- **Shows:** the scary part handled — clean rights, no PRO/clearance surprises.
- **Design:** mirrors the referenced cue-sheet format but *designed*: cue table (Cue · Usage ·
  Duration · Composer/Writer · Publisher · PRO · % shares) **plus** an ownership block
  (work-for-hire / buyout vs license, territory: Worldwide, term: Perpetuity, exclusivity).
  Certificate framing with a seal. **Head of Production:** the % shares must total 100
  per cue — a real producer checks. — *Hard requirement.*

### 6. Stem inventory
- **Shows:** mix-ready professionalism — every stem labeled and delivered.
- **Design:** table — Stem · File · Format · Notes. Grouped (Rhythm / Harmonic /
  Melodic / FX / Vox). Mirrors the asset-map naming. Quiet, dense, confident.

### 7. Campaign rollout infographic
- **Shows:** we think about *their* campaign, not just the track — which version goes
  where. This is the most "premium vendor" page.
- **Design:** an infographic mapping **version → channel → spec**: :60 anthem → brand
  film / YouTube; :30 → TV/CTV; :15 → pre-roll; :06 → bumper/social; vertical → IG/TikTok;
  sonic logo → all endcards. A horizontal channel band with orange connectors. CMO owns
  this page as the differentiator.

### 8. Final approval certificate
- **Shows:** closure — signed, locked, done. The feeling every stakeholder wants.
- **Design:** formal certificate — "Approved for Release", campaign, locked version
  (v3 FINAL), approver/role, date, two signature lines (Client + Chordential), an orange
  seal. Premium, ceremonial.

> **Dissent on order (Founder's Advocate):** lead the package with the *rollout
> infographic* (#7), not the manifest — open with the buyer's win, not our file list.
> **CMO holds:** cover → manifest sets credibility first; rollout is the mid-package
> "wow." **CEO to break if needed.**

---

## Website integration (CMO plan)

**Where:** the existing **"What Delivery Actually Looks Like"** section on the home page.
Today it's a bullet list + a stock photo. Replace the stock photo with a **package
preview** (the cover + a fanned peek of inner pages) and add a CTA.

**How (two options for Jon to pick):**
- **(A) Branded web page** — a `/delivery-sample` route rendering the package as a
  scrollable branded page with a **"Save as PDF"** button (matches our existing
  capabilities-doc pattern, zero new dependency). Best for SEO + instant view.
- **(B) Downloadable PDF** — a "Download the sample package (PDF)" button. Feels most
  like a real deliverable, but is a static file to maintain.
- **CMO recommendation:** **both** — the web page is the showcase; a "Download PDF"
  on it satisfies the producer who wants the artifact. Phase the PDF if needed.

**CTA copy (CMO):** *"See exactly what lands in your inbox →"* / *"Sample delivery package."*

**Honesty:** the section keeps the truthful framing — this is a *sample* of our format,
labeled as such.

---

## Ratified decisions (pending Jon's approval)
1. One design system, eight documents, fictional **AURORA** campaign, **SAMPLE** watermark.
2. Internally-consistent data across all 8 (hard requirement).
3. Build as a **self-contained branded HTML package** first (print-ready → PDF), so it's
   showable everywhere and becomes the `/delivery-sample` page on approval.
4. Website: replace the delivery-section photo with a package preview + a *"See exactly
   what lands in your inbox"* CTA → the sample page (web view + Save-as-PDF).

**Status: awaiting Jon's final approval before any site integration.** The demo package
itself is generated for review alongside this doc.
