# Brand Strategist — deliverable

*Wave 1, 2026-09-09. Reads under `docs/marketing/00-brief.md`; where this file and the brief
differ, the brief wins. Every other role reads this before writing.*

Revenue is zero. No engagement, no client, no testimonial exists. Every line below is
written from that fact, and every demo it mentions is an invented brand.

---

## 1. Positioning statement

> For agency producers and heads of production who commission original music for
> campaigns with several approvers and real rights exposure, Chordential is the music
> house that delivers original music finished — composed by people, approved in one room
> the client can see into, cleared under a certificate the studio signs, and packaged
> completely, on the date agreed. Unlike the incumbent music house, whose process lives in
> email and whose paper is deal-by-deal, and unlike libraries, freelancers and machine-made
> music, which deliver a file and leave the finishing to the buyer, Chordential runs its
> studio to leave nothing undone and to show the client every step — because it would
> rather prove than be trusted.

**Kept verbatim** (brief §1, Brand Foundation §3.5). I tested one change and rejected it:
"on the date agreed" tempts a schedule claim we have never kept for a paying client. It
stays because it is a *standard* the room makes visible, not a track record.

## 2. The line, and the three alternates

**Spine, every channel:** *Original music for campaigns — composed, cleared, delivered.*

| Alternate | Where | Why there and nowhere else |
|---|---|---|
| **The music arrives finished.** | The site: hero lede under the spine, the About page, the room's first screen. | Ruling 2: *finished* leads. Five words a stranger can repeat. The certificate is enumerated beneath it, never above it. |
| **Music your legal team can defend.** | Business affairs, legal, procurement only: the certificate's cover note, the Clearance Read reply, a call when that seat is on it. | Brief §2. It names the buyer's fear, not our craft. Never the site headline, never to a creative director, and never with *guaranteed* or *indemnified* near it (Ruling 4). |
| **Written for this campaign. Cleared. In the box on the date.** | A producer's inbox: the LinkedIn headline, the five-touch sequence, the email signature. | A producer skims. Three past-participle facts, one screen wide, each of which the room or the package can show. |

"Procurement-grade" appears in none of them and in no client-facing copy, anywhere
(Ruling 3).

## 3. The three pillars and their proof

| Pillar | The promise | Proof a producer can click | Objection answered |
|---|---|---|---|
| **Original** | Written for this campaign by a named human composer. | The brief in the room; the composer's name on the cue sheet; the composer agreement in force. | "Why not a library, why not a generator?" |
| **Cleared** | A grant of rights business affairs can read, sign and rely on. | The Clearance Certificate with media, territory, term, exclusivity and publishing stated; contributor releases; a signature bound to the text that reports *no longer matches* if a term changes. | "Can we defend this on paid spend, cross-channel?" |
| **Delivered** | What you approved is what you receive, and the package says so. | Published versions only; one round buys one version; the manifest names every file; the cue sheet is in the box. | "What actually happens after approval?" |

Rule for every seat: a pillar is *enumerated*, never adjectivised.

## 4. Vocabulary, extended

The brief's §6 stands whole. Additions, each with its reason.

**Use**

- **the room** for every client surface, including the one the code still calls the
  delivery portal. One noun, so a client never learns two names for one door.
- **a demonstration** for every piece of work shown. Not "sample", not "case study": the
  first implies we cut it from a job, the second that there was a client.
- **the founder, by name.** Jon Shipp is on every call and every post; "our team" is a
  scale claim we cannot back.
- **a Clearance Read.** The one give with a name; it is what the leading metric counts.
- **not yet.** The two words that make "finished" believable.

**Never** (added to the brief's list)

- **the music department you don't have to build** — the live hero at `/commission`.
  Overclaims headcount; the Foundation retired it and the brief's positioning replaced it.
- **production workflow** — the front door's lede. Software vocabulary by another name.
- **clearance-certified** as an adjective on the studio — the certificate is a document we
  sign, not a badge we wear (Foundation §5.4).
- **partner / creative partner** — says nothing checkable; every house says it.
- **department, team of, offices, studios** (plural) — scale we do not have.
- **certified** alone, **cleared** alone — always *cleared under the certificate*, so the
  proof travels with the claim.
- **on time, fast turnaround** — the schedule is a stated date, not an adjective.
- **AI** as a subject at all, outside the one sentence that explains why human authorship
  is a legal fact. We do not fear it, mock it, or brand against it.

## 5. Competitive positioning, never by name

**Libraries.** They win on speed, price and volume, and we say so; they are the right
answer for filler and we never punch down. Where they fail the ideal buyer: a licence is a
rental, paid spend and cross-channel reposts break it, a Content ID claim follows, and
nothing is owned. Our line is a fact, not a sneer: *a library is a file; this is yours,
with the paper business affairs asked for.*

**The incumbent music house.** The real competitor, displaced only at the moment it fails
a producer. It wins on relationships, taste the creative director already trusts, and
three free demos in forty-eight hours. Where it fails: the process lives in email, rounds
are unbounded, the paper is deal-by-deal. We never say we are better. We show the room.

**Machine-made music.** Fast, free, unlimited, and, per the US Copyright Office (January
2025) and the federal appeals court (March 2025), not copyrightable, so not cleanly
licensable, insurable or defensible. A fact the certificate records, not a villain we
fight; re-verify the citation before every use. We never stand on that shelf, including to
mock it, and never use its output, including as a demo.

**Freelancers** (the price-shopper's comparison): the music can be bought cheaper; the
finish cannot.

## 6. The narrative, for a producer to repeat to a creative director

> They are a small music house, one founder and a roster he chose. The music is written
> for our campaign by a composer whose name goes on the cue sheet; nothing generated,
> nothing pulled from a library. The whole job runs in one room at one link: you play the
> take, leave a note at the exact second, and the note stays with that version. Rounds are
> numbered. A note is priced before anyone works on it, so nothing becomes a change order
> by accident. When we approve, they sign a clearance certificate that says where it can
> run, for how long, and who holds publishing; business affairs can read it without a
> cover note, and the signature reports itself if a term changes. It arrives as one
> package: masters, cutdowns, stems, cue sheet, the certificate, a manifest of every file.
> They have no case studies yet and say so. What they show is the room and the package.
> The founder is on the call himself.

(149 words.)

## 7. Inconsistency audit

Quote, file, fix. Fixes marked **m01** are pre-conditions under brief §8 and the build
freeze does not cover them; the rest are copy edits or archive notes.

### The public site

1. **"then organize every version, approval, cue sheet, rights document, and deliverable
   into one complete production workflow."** — `web/templates/public/score.html`, the
   front-door hero. *Workflow* is software vocabulary (brief §6: never *tool / software /
   end-to-end*). Fix (m01): *…and deliver every version, approval, cue sheet and rights
   document finished, in one package.*
2. **Hero eyebrow "Original music • Cleared • Delivered"** — `score.html`. Reads as three
   labels, not the spine. Fix: *Original music for campaigns — composed, cleared,
   delivered.*
3. **"On a real campaign the note lands on the version under review and the composer
   answers it in the portal."** — `score.html`, review beat. *Portal* is banned. Fix:
   *…answers it in the room.*
4. **"They deserve a partner who understands the work…"** and **"Great campaigns deserve
   more than great music."** — `score.html`, close. *Partner* is a claim any house makes;
   the second line flirts with "the music is the easy part". Fix: *Original music, finished.
   Start with a brief; the founder reads it.*
5. **"The music department you don't have to build."** — `web/templates/public/
   commission.html`, the H1 and the meta description. Retired by the Foundation (§5.5) as
   a scale overclaim. Fix (m01): the spine, with *The music arrives finished* as the lede.
   Note that `/commission` is still linked from the front door's demos section, so it is
   live copy, not an archive.
6. **"Every commission comes with a portal."** and the three mentions that follow —
   `commission.html`. Fix: *the room*, throughout.
7. **"Four of five contributors have returned work-for-hire agreements."** —
   `commission.html`, the certificate demonstration. *Work-made-for-hire* is on the
   never-say list. Fix: *…have signed their composer agreements.*
8. **"Chordential is a small studio making original, clearance-certified music"** —
   `web/templates/public/for_artists.html`. Adjective on the studio. Fix: *…making
   original music for campaigns, cleared under a certificate we sign.* Same page: *"we
   handle the paperwork"* — Fix: *the paperwork is ours to carry.*
9. **The placeholder audio.** `web/showcase.py` discloses that every demo recording is
   "AI-generated placeholders" and every played surface prints that sentence. Disclosure is
   honest, but the brief's refusal is absolute: *no machine-made music, anywhere, including
   as a demo.* Fix (m01, the first): replace all four recordings with human-made music, or
   take the players down until they exist. The notice is not the fix.
10. **`web/showcase.py` ABOUT: "Chordential is a music procurement studio."** and HERO:
    *"Music that moves campaigns forward — and gets approved."* Retired category and an
    outcome claim. Both still render where the showcase is read. Fix: the positioning's
    first sentence; delete the hero line.
11. **`web/templates/public/delivery_sample.html`: "Locked in 3 rounds," "Signed off
    without reopening the creative conversation," "Paid in full," a dated *17 April 2026*
    package and "Released · J. Shipp".** Watermarked SAMPLE, but it narrates and signs an
    engagement that never happened. Fix: keep the format, strip the outcome sentences,
    the date and the signature; mark each *(demonstration)*.

### Product copy a client sees

12. **"Chordential is a procurement-grade music partner."** — `capabilities.py`
    VALUE_PROP, the client capabilities document. Banned client-facing. Fix: *Chordential is
    a music house that delivers original music finished: composed by people, cleared under
    a certificate we sign, packaged completely.*
13. **"Chordential · procurement-grade music · chordential.com"** — the footer of
    `web/templates/_brief_document.html`, the Discovery Summary the client signs. Fix:
    *Chordential · original music for campaigns · chordential.com.*
14. **"Chordential is a procurement-grade music studio: clearance-certified, human-composed
    original music (never AI-generated)."** — `web/outreach_engine.py`, the value line in
    outbound email, and the vendor-profile default in `web/procurement.py`. Two banned
    phrases and AI as a badge. Fix: the spine, then *composed by a named person; cleared
    under a certificate we sign.*
15. **"One workspace for your campaign"** and **"Your campaign workspace"** —
    `web/templates/workspace.html`, four times, reaching every pre-award client. Fix:
    *your room*.
16. **The certificate's clearance line: "100% original & cleared: no samples, no third-party
    masters, no PRO surprises."** — `delivery.py`. Asserted, not computed (brief §8.3), and
    *100%* is a guarantee by another spelling. Fix (m01): compute the line from the
    contributor releases actually on file: *Original work, cleared as granted above;
    releases on file for every named contributor.* Marketing describes the certificate as
    nothing more until counsel has reviewed it.
17. **"Procurement OS"** — `web/templates/base.html` title and brand tag,
    `admin_login.html`, `app.py` app title and PWA manifest name. Internal chrome, but the
    login page is what a client sees when a review link's exemption is missing, which
    CLAUDE.md records has happened. Fix: *Chordential* alone on anything reachable from a
    client link.
18. **Demo records are unlabelled** in the internal views and the room (brief §8.2). Fix
    (m01): a *demo* mark on every seeded record, on every surface.

### The call scripts

19. **`docs/call-scripts/discovery-call-studio.md`** is clean of banned words; its
    consent line, read-back and "I don't know" at publishing are the voice exactly. Two
    gaps: it never states the no-free-spec line, and it closes on *"You'll get a written
    summary today"* without naming the Discovery Summary as the thing she will sign
    (Bible OM2). Fix: one line each, in the founder's first person.

### The prior documents (archive; note, do not edit)

20. **CLAUDE.md line 18: "a procurement-grade music studio + the operating system that runs
    it."** An internal engineering file may keep the phrase; the brief bans it client-facing
    only. It should not keep it as the *first* description of the company, because agents
    copy opening lines into client surfaces (items 12 to 14 are how that happened).
    Recommended edit, for the founder: *a music house that delivers original music
    finished, and the operating system it runs on.* The same applies to the Constitution's
    line 23 and README line 112.
21. **Messaging Bible §3.1** permits *procurement-grade* to business affairs; **§2.1** puts
    it in the core message. Overruled by Ruling 3. The brief's core message still ends
    *"handed over the way procurement wants it"*; that survives because it names the
    buyer's seat, not our grade.
22. **Bible §3.1: "studio. What we are. Not agency, not house."** Overruled by Ruling 1:
    the category is *music house*. *Studio* remains fine for the place and the people.
23. **The Constitution's customer promise** ("removes the work of managing music") stands
    until the founder rules on the amendment (brief §13.1). Never a headline.
24. **Sales Playbook: "the music is the easy part."** Banned (Ruling 4). Archive only.
25. **Bible §2.2 SM1 and `web/simulator.py`** speak of "built-in indemnification". The
    shipped certificate carries no indemnity by the founder's own scope, and Ruling 4
    forbids the claim until counsel reviews. Nobody says it on a call.

## 8. Objection to the brief

One, and it is narrow.

**Brief §9 calls the Clearance Read "one hour, no pitch" and places it at touch three of a
sequence whose fifth touch is "the small ask."** A give inside a sequence engineered to
end in an ask is a pitch with a delay, and a producer will read it as one the second time
it arrives. I would let the Read stand alone as the thing anyone can request, with no
follow-up unless they write back.

I continue under the brief as written: the Read stays at touch three, and every seat
writing the sequence keeps the Read's own text free of any mention of us.

Otherwise none. Where I disagreed with a prior seat, the brief had already ruled my way.
