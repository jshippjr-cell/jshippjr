# SEO & Website — deliverable

*Wave 2, 2026-09-09. Reads under `docs/marketing/00-brief.md`; extends the Brand
Strategist's §7 audit rather than repeating it. No web access, so no search volume is cited.
Quotations are from the templates as served today, via the test client.
Revenue is zero; no client, case study or testimonial exists.*

---

## 1. The query map

What a producer, head of production or business-affairs person types, and the page that
answers it once §2 (P1–P6) is built.

| Intent | What they type | Page |
|---|---|---|
| Learn | music licence terms explained · what do media, territory, term mean in a music licence · what is exclusivity · what does publishing mean in a sync licence | P1 |
| Learn | what is chain of title for music · what is a contributor release | P2 |
| Learn | what is a cue sheet and who files it | P4, post 11 |
| Learn | how to brief a composer for a commercial · what to put in a music brief | P5 |
| Compare | original vs library music for advertising · custom vs stock music cost · music house vs freelance composer · supervisor vs composer | P3, P6 |
| Compare | can we use AI-generated music in a commercial · is AI music copyrightable | P3 (facts, cited, *verify*) |
| Compare | is royalty-free music safe for paid social ads | P1, post 2 |
| Buy | how much does original music for a commercial cost · composer fee for a :30 · how long does it take | P6, P5 |
| Buy | commission original music for a campaign · music house for advertising | `/`, `/start` |
| Verify | what should a music delivery include, stems, cutdowns | P4, `/delivery-sample` |
| Verify | what does business affairs check before music airs · what is a clearance certificate | P2 (enumerated, never adjectivised) |
| Verify | can we run this music on paid social / cross-channel / cutdowns | P1, the Clearance Read |
| Verify | licence expired, campaign still running · Content ID claim on our own commercial | posts 1, 3 |

## 2. The six pillar pages, in build order

Order is the roadmap's §14. All under `/learn/`; titles are H1s and obey §6; each carries
one ungated download (§4) and ends with the Clearance Read as the only offer. A new public
route must be added to `publicpaths._PUBLIC_PATHS` (l.30-43) or production's admin gate
answers it with the login.

**P1 · `/learn/licence-terms` — Music licence terms, explained.**
*Question:* what do the words in a music licence mean, and which ones decide whether the
campaign can run where it will actually run? *H2s:* The five terms: media, territory, term,
exclusivity, publishing · What paid spend changes · Cutdowns, cross-channel and reposts: the
same licence? · When a term ends · What the Clearance Certificate states (enumerated).
*Download:* D1. *Links:* P2, P3, P6, `/delivery-sample`, the Clearance Read.

**P2 · `/learn/what-business-affairs-checks` — What business affairs checks before music runs.**
*Question:* what does legal need to see, in what order, before signing off the music?
*H2s:* Who wrote it, and can they show it · Every contributor, released · The grant, term by
term · Publishing and PRO registration: who collects · Chain of title, writer to you · When
the paper and the music stop matching. *Download:* D1 (the same file, so one link
compounds). *Links:* P1, P4, `/delivery-sample`.

**P3 · `/learn/original-library-or-machine-made` — Original, library or machine-made: what each leaves you holding.**
*Question:* commission it, license it or generate it — and what do we own afterwards?
*H2s:* A library licence is a rental · A commission: the music is yours · Machine-made output under current US copyright guidance (US Copyright Office, Jan
2025; federal appeals court, Mar 2025 — **verify before publishing**) · The cost comparison,
honestly · Who is on the cue sheet in each case · A decision table. *Download:* D3.
*Links:* P6, P1, P2.

**P4 · `/learn/what-a-delivery-contains` — What a finished music delivery contains.**
*Question:* what should be in the box, and how do I know nothing is missing? *H2s:*
Masters and the TV/instrumental mix · Cutdowns and verticals · Stems, and the groups an
editor needs · The cue sheet · The rights document · The manifest: every file, with its spec ·
Version history, with the approvals attached · A checklist to hold any music house to. Rows
mirror `landing.sample_package_lines()`. *Download:* D2. *Links:* `/delivery-sample`, P2, P5.

**P5 · `/learn/how-to-brief-a-composer` — How to brief a composer.**
*Question:* what does a composer need to write the right thing the first time? *H2s:* The
picture, the cut and the timings · References: what they are for · The feeling, in the
producer's words · Where it will run (that is the licence) · Approvers, and
who decides · Dates, honestly · The one-page brief. *Download:* D4. *Links:* `/start`, P6, P1.

**P6 · `/learn/what-original-music-costs` — What original music for a campaign costs, and why.**
*Question:* what is a fair number, and what moves it? *H2s:* Two fees: creative fee and
licence fee · What moves each · Why the budget is not the price · What a round buys · The
number comes with its reasons. Any figure is rendered from `estimation.PUBLIC_BANDS`, the
bands `/commission` already shows — never typed (one pricing authority). *Download:* D4.
*Links:* P1, P5, `/start`.

## 3. Twenty supporting posts

Series are the brief's §9 six. Each post is a LinkedIn piece first and a `/learn/` page
second.

| # | Title | Pillar | Series |
|---|---|---|---|
| 1 | What "term" means when the campaign gets extended | P1 | Music Myths |
| 2 | Paid social is not organic social: the licence line | P1 | How Agencies Actually Buy Music |
| 3 | A Content ID claim on your own commercial: how it happens | P1 | Music Myths |
| 4 | Exclusivity: what you are paying for and what you are not | P1 | How Agencies Actually Buy Music |
| 5 | Who collects the publishing on a commission | P2 | Music Myths |
| 6 | The session cellist signs too: contributor releases | P2 | What Actually Happens After Approval? |
| 7 | Reading a grant of rights in five minutes | P2 | How Agencies Actually Buy Music |
| 8 | "No longer matches": a signature bound to its text | P2 | What Actually Happens After Approval? |
| 9 | Why a library track is a rental | P3 | Music Myths |
| 10 | What the Copyright Office said about machine-made music (verify) | P3 | Music Myths |
| 11 | The composer's name on the cue sheet | P3 | How Agencies Actually Buy Music |
| 12 | What a manifest is for | P4 | What Actually Happens After Approval? |
| 13 | Stems: the groups an editor actually asks for | P4 | What Actually Happens After Approval? |
| 14 | One round buys one version | P4 | What Actually Happens After Approval? |
| 15 | Vertical cuts and loudness: the delivery nobody briefs | P4 | Producer's Notebook |
| 16 | References are a direction, not a target | P5 | Producer's Notebook |
| 17 | Five approvers, one decision: naming who decides | P5 | How Agencies Actually Buy Music |
| 18 | Why a change request is priced before anyone works | P6 | What Actually Happens After Approval? |
| 19 | Creative fee and licence fee: why they are two numbers | P6 | How Agencies Actually Buy Music |
| 20 | Why the budget you tell us does not set the price | P6 | Producer's Notebook |

*Why This Commercial Works* and *Behind the Brief* carry no posts here — see §7.

## 4. The four downloadables

Each is an HTML page first (it ranks) and a PDF second (it gets forwarded to business
affairs). Every example row is on an invented brand, marked *demonstration*.

**D1 · The licence-terms glossary** (P1, P2). §1 The five terms — each with a definition,
what it usually reads as, and the one question to ask. §2 Six words that are not terms but
decide things: paid spend, cross-channel, cutdowns, in perpetuity, buyout (defined because
clients meet it; never our offer), most-favoured. §3 Chain of title in a paragraph. §4
Before you sign: eight questions.

**D2 · The delivery checklist** (P4). One page. Masters (sample rate, bit depth,
TV/instrumental mix) · Cutdowns and verticals · Stems (groups, naming) · Documents: cue
sheet with ISRC/ISWC where issued, rights document, manifest · Version history · One naming
convention, written down · Ten checks before you accept. Rows mirror `sample_package_lines()`.

**D3 · The cue-sheet template** (P3). Production header (title, agency, client, air date) ·
per-cue rows: title, duration, usage code, writer(s) with PRO and share, publisher(s) with
PRO and share, ISRC/ISWC · who files (varies by network — *verify*) · one filled row over
AURORA. Uses the usage codes `delivery.py` writes, so template and real cue sheet cannot
differ.

**D4 · The one-page brief** (P5, P6). The campaign (client, agency, air date, where it runs)
· The picture (cut lengths, timings, lock status) · The feeling, in your words · Three
references and what each is for · What it must not sound like · Approvers, and who decides
· Dates · Budget range, optional: *it makes the number yours; it never sets the price.*

**Ungated in year one, because:** §9 allows no ask until three gives, and an email gate is
an ask; the leading metrics are saves, shares and organic search (§11), which a gated PDF
cannot earn and business affairs cannot be forwarded; and a list cannot be worked at founder
capacity before the Q2 newsletter. Revisit in year two.

## 5. The front-door audit

### What the pages say now

**`/`** (`score.html`): `<title>` "Every part in the air · Chordential" (l.5). Eyebrow
"Original music • Cleared • Delivered" (l.490). H1 "Every note finds its place." (l.491).
Lede "We compose original music for commercials and brand campaigns, then organize every
version, approval, cue sheet, rights document, and deliverable into one complete production
workflow." (l.492-494). Under it: "728 pieces · 7,419 marks · real engraving, drawn live"
(l.496). H2s: "Every campaign begins with understanding." · "Every conversation becomes
momentum." · "Every decision serves the story." · "Every comment stays with the music." ·
"Everything arrives together." · "Great campaigns deserve more than great music."
(l.502-632). CTAs "Start a brief" (l.422), "Start with a brief" (l.636), "We'll take it
from there." (l.637).

**`/capabilities`** (`public.py:193-195`): a 301 to `/#hear`. There is no page.

**`/start`** (`start.html`): title and eyebrow "Start a project". H1 "Tell us what you're
making." Lede "A few details is all we need to come back with an approach and a price range.
No commitment. This just opens the conversation." CTA "Send it over".

**`/commission`** (`commission.html`): title "Original music for campaigns · Chordential"
(l.1). Meta "The music department you don't have to build. Original score for campaigns,
written and recorded in house, cleared before it ships…" (l.3). H1 l.600; H2s l.637-824.

### Contradictions beyond the Brand Strategist's list

1. **The front door plays machine-made music with no disclosure.** `/` serves the four
   `ex-demo-*.mp3` excerpts from the lit notes and scrubs the first in the review beat
   (`score.html:568`). The served page does not contain `PLACEHOLDER_AUDIO_NOTICE` —
   fetched and checked — and `tests/test_hear_the_work.py:150-156` confirms it is
   deliberate, walking `/commission` and `/showreel` only because `/` "carries no row of
   players to sit a disclosure beside". The Strategist's item 9 says every played surface
   prints the sentence; the highest-traffic one does not. This is §8.1 on the page it
   names first.
2. Title and H1 caption the picture, not the offer, and the H1 is a pun (§5). "728 pieces ·
   7,419 marks · real engraving, drawn live" is internal chrome (§8.4) in the hero.
3. Beats 02-03 offer nothing a producer can verify (roadmap §00). The Discovery Summary —
   the thing she signs — is never named.
4. "…legal review, and archive" (l.604): archiving is on the no-claim register (§7).
5. "We'll take it from there." (l.637) is *we handle everything* by another spelling.
6. `/start` promises "a price range"; `public.py:365-368` stores the band and, by founder
   ruling, never shows it.
7. One CTA, four spellings: "Start a brief" / "Start with a brief" / "Start your brief" /
   "Start a Brief" (`score.html:422,636`; `public_base.html:20`; `commission.html:833`).
8. `/commission`: "written and recorded in house" (meta) and "before a note leaves the
   building" (l.764) claim premises we do not have; "warranty" and "Title from one
   counterparty, not five" (l.765-766) are counsel-adjacent (Ruling 4). Nothing links to
   it (grep), yet it is public and indexable.
9. `/stills` (public, `publicpaths.py:35`) labels the two `showcase.CASES` "Case study"
   (`public.py:233`) under "read how it was solved" (`stills.html:19`) — fabricated proof
   (§7). `/showreel` puts "Original music. Cleared to use." over the placeholder files.
10. `public_base.html:34` "Original music, sound & sonic identity for campaigns." is a
    fourth spine; its nav "Hear the work" (l.19) sends every form page to the placeholders.
11. `/capabilities` — what a producer types for "what do you do" — lands her mid-scroll at
    a beat that says press a glowing note, unlit on a slow connection (`score.html:440-465`).
    The five disciplines in `showcase.CAPABILITIES` render nowhere (`public.py:305`).

### The rewrite

Tests pin the current copy and move with it: `test_score_page.py:43-49,103-107` ("Every
note", "one complete production workflow"), `test_public_site.py:39` and
`test_hear_the_work.py:310` ("The music department").

**`/` — one page, both outcomes of decision (a).**

- `<title>` Chordential · Original music for campaigns — composed, cleared, delivered
- meta: *A music house that delivers original music finished: composed by a named person,
  approved in one room you can see into, cleared under a certificate we sign, packaged
  completely. Every brand shown is invented; there is no client work to show yet.*
- Eyebrow *Chordential · a music house*. H1 *Original music for campaigns — composed,
  cleared, delivered.* Lede *The music arrives finished. We write it for your campaign, by
  people, and we deliver every version, approval, cue sheet and rights document finished, in
  one package. At any moment you can see where it stands.* Renderer line deleted.
- 02 H2 *It starts with the brief.* Before a note is written you get a one-page Discovery
  Summary — scope, fee, terms — and sign it; anything the brief did not state is named as
  assumed.
- 03 H2 *Written for this campaign, by a person whose name is on the cue sheet.* No library,
  no recycled track, no generator; the composer agreement in force first.
- 04, players present (human-made): H2 *Hear a demonstration.* Each piece answers a brief
  we set ourselves, on an invented brand, written and recorded by [role]. Hint *Press a lit
  note.* Players down: the beat goes and 03 gains one line — *Demonstrations arrive with
  the first recorded sessions. Not yet: we would rather show you the room than play you
  something we did not make.*
- 05 H2 *One room. Every note stays with the music.* Play the take, mark the second, say
  what you heard; the note stays with that version, and a round buys one version. Players
  present: the rail scrubs a human-made take. Players down: it runs a silent 45-second
  timeline labelled *silent timeline — the take arrives with the first session*; the label
  says what it is. Disclosure: *…the composer answers it in the room.*
- 06 H2 *Everything arrives together.* What you approved is what you receive, and
  the package says so — masters, cutdowns, stems, cue sheet, the certificate, a manifest
  naming every file. "archive" removed; engine rows kept. CTA *Open the sample package*.
- 07 H2 *Original music, finished.* *Start with a brief; Jon reads it himself and replies
  with the next step. There are no case studies yet, and we say so. What we show is the room
  and the package.* Close: *Every brand here is invented. There is no client work yet.*
- One CTA string everywhere, `public_base` and `/commission` included: **Start a brief**.

**`/capabilities`** — a `public_base` page, not a redirect. Title *What we make ·
Chordential*; meta *Original composition, arrangement, sound design, sonic branding and
music supervision for campaigns — each delivered finished, under a certificate we sign.*;
eyebrow *What we make*; H1 *Original music for campaigns, in five crafts.*; one H2 per
discipline rendered from `showcase.CAPABILITIES`, then *How it is delivered* (P4, the
sample) and *What we do not do* (library, machine-made, spec); CTA *Start a brief*. Until
built, 301 to `/`, not `/#hear`.

**`/start`** — title *Start a brief · Chordential*; eyebrow *The brief*; H1 *Tell us about
the campaign.*; lede, and the meta with it: *A few lines is enough — what it is for, where it
will run, when it is due. Jon reads every brief himself and replies with questions, a
direction and a time to talk. Nothing here commits you.* Budget hint *A range makes the
number yours. It never sets the price.* CTAs *Send the brief* / *Prefer a call*. Footer
*Read by the founder, not sorted by a machine.*

**`/commission`** — title kept; meta and eyebrow as `/`; H1 *The music arrives finished.*;
lede *Original music for campaigns — composed, cleared, delivered: masters, stems, cutdowns,
cue sheet, the certificate and a manifest, in one package.* H2s: *Hear a demonstration.*
(removed under B) · *One room. Every note stays with the music.* · *The number comes with
its reasons.* · *Cleared under a certificate we sign.* — the demonstration reads *Four of
five contributors have signed; the session cellist's release is out for signature, and the
certificate issues once it is back*, and the "warranty" row becomes *Original work · stated*
· *Everything arrives together.* · *Nothing should still be waiting.* CTAs *Start a brief* /
*Book a call*. Add `<link rel="canonical" href="https://chordential.com/">` until the page
is retired.

## 6. Technical — only what I verified

- **Document shell.** `/` and `/commission` are served without `<!DOCTYPE>`, `<html lang>`,
  `<head>` or a charset: the templates begin at `<title>` (`score.html:5`,
  `commission.html:1`) and so do the served bodies — quirks mode, no language declared. The
  `public_base.html` pages and `/delivery-sample` have the full shell.
- **Titles and descriptions.** Titles: `/` "Every part in the air"; `/start` "Start a
  project"; `/book` "Book a call"; `/for-artists` "For creators"; `/delivery-sample` "Sample
  Delivery Package" — only `/commission`'s says what we sell. Meta descriptions: two in the
  whole templates tree (`score.html:7`, `commission.html:3`); `public_base.html` has no
  description block, so every page on it, present and future, has none.
- **Headings.** `/` has one H1, six H2s, no H3 — sound. `/delivery-sample` has **eight H1s**
  (one per document, l.117-382): the cover should be the H1, the documents H2s.
  `/for-artists` runs H1 → H3 before its only H2. `/start` and `/book` have no H2.
- **Canonical / OG / Twitter.** None anywhere in `web/` (grep). `/` and `/score` render one
  page (`public.py:269-271`) with no canonical; `/commission` is a third copy of the offer.
- **robots.txt, sitemap.xml.** Both 404. Whoever adds them must also add them to
  `publicpaths._PUBLIC_PATHS`, or production's admin gate 303s the crawler to the login.
  The sitemap lists `/`, `/capabilities`, `/start`, `/book`, `/delivery-sample`,
  `/for-artists`, `/learn/*`; `/showreel`, `/stills`, `/reel`, `/commission` carry `noindex`
  until fixed or retired.
- **Crawlable text on the WebGL front door.** All copy is static HTML in
  `<main id="scroll">`: H1, six H2s and manifest rows are in the served body (34,735 bytes)
  before any script runs. The scene (`score-scene.bin` 429,920 B + `score-scene.json`
  67,111 B) and `score-gl.js` (40,864 B) draw pictures only. Cautions: beats after the first
  sit at `opacity:0` until scrolled (`score.html:42-57`), and `<canvas id="gl">` has no
  accessible name — `#fail` text appears only when WebGL2 is absent.
- **Images and alt text.** The only public images are the wordmark (`alt="Chordential"`,
  eight times on the sample package) and an aria-hidden mark. Nothing to caption; no OG
  image.
- **Internal linking.** From `/` the only outbound links are `/start` and
  `/delivery-sample`; `public_base` links `/#hear`, `/start`, `/apply`. No `/about` (404),
  no footer navigation, nowhere for `/learn/` to hang. Needed: a footer on both shells —
  What we make · Learn · Sample package · For composers · Start a brief.
- **Weight.** Static assets cache seven days behind an mtime buster (`app.py:369-370`,
  `public.py:48-56`). Each demo excerpt is 1,080,215 bytes; `/` sets `preload="none"`,
  `/commission` `preload="metadata"`. Load time: unmeasured here, so unclaimed.

## 7. What I cut, and why

- **Local SEO** ("music house Atlanta") — the thirty are reached by hand (Ruling 5), and a
  city page with no address invites inventing one.
- **Posts for *Why This Commercial Works* and *Behind the Brief*** — Q2 and post-first-job;
  mapping them now writes as if a job had happened.
- **A certificate explainer page** — Ruling 4; P2 enumerates the fields and stops.
- **Gated downloads, list capture on the pillars, review or award schema** — no ask before
  three gives; no proof that is not real.
- **`/showreel` and `/stills`** — retire, not rewrite: two more addresses for placeholder
  audio and one "Case study" label.
- **Search volumes and speed claims** — no source I could name, and nothing I can measure.

## Objection to the brief

One. **§8.1 offers "replace it with human-made music *or disclose it*"; §7 says "no
machine-made music, anywhere, including as a demo."** Disclosure is the weaker rule, and
`/` currently meets neither. I would strike "or disclose it" from §8.1 so the front door has
one instruction. I continue under the brief as written: the `/` rewrite covers the page with
players and the page without, and under either the players are human-made or absent — never
disclosed placeholders.
