# Voice edit — making the copy sound like Jon and not like a company

*Line edit, 2026-09-10. Brief: make it him. Sources are his own messages, quoted in the
task. Six faults hunted: **1** definition/explanation · **2** aphorism · **3** company
voice · **4** cadence tic · **5** borrowed authority · **6** too even. No money in public;
no claimed client, case study, testimonial or signed composer; nothing invented about him.*

---

## 1. Findings

| Line (quoted) | File | Fault | Rewrite |
|---|---|---|---|
| "Every campaign begins with understanding." | `templates/public/score.html` | 2, 4 | "Tell me what the film is doing and who it's for." |
| "Every conversation becomes momentum." | score.html | 2, 3 | **Cut.** It says nothing. Replace the beat's head with "Everyone leaves the call knowing the same thing." |
| "Every decision serves the story." | score.html | 2, 4 | "Written for your campaign. Not pulled off a shelf." |
| "Every comment stays with the music." | score.html | 2, 4 | "Your note stays on the second you meant." |
| "Everything arrives together." | score.html | 2, 4 | "One folder. Everything in it." |
| The five headings above, read down the page | score.html | 4, 6 | Five headings starting **Every/Everything** is a template, not a person. Break at least three. |
| "Our job is to turn complexity into a direction everyone can build from." | score.html | 3 | "My job is to get everyone pointed the same way before a composer starts." |
| "Creative judgment is still the most important instrument in the room." | score.html | 2, 3 | **Cut.** Pure epigram, and a pun on "instrument". |
| "Creative conversations should move the work forward, not create more work." | score.html | 2, 3 | **Cut.** Vendor sentence with a chiasmus in it. |
| "We begin by understanding the creative, the constraints, and what success looks like before a single cue is discussed." | score.html | 3, 6 | "Before anyone writes anything I want the picture, the deadline, and what it has to do." |
| "No libraries. No recycled tracks. Just original music shaped around the picture, the audience, and the emotion you're trying to create." | score.html | 4, 3 | "Nothing from a library, nothing reused. It gets written for your spot." |
| "One delivery. Nothing missing." | score.html | 2, 4 | "That is the whole package." |
| "Original music, finished." (close head) | score.html | — | Keep. It is the spine, not an aphorism. |
| "Music rarely fails creatively. It fails operationally." | `showcase.py` `PROBLEM` | 2, 3 | "The music is usually fine. What goes wrong is everything around it." (Note: keep well clear of the banned "the music is the easy part" — this line is already leaning on it.) |
| "Direction Lock / Structural Composition / Controlled Variation / Bounded Delivery" | showcase.py `STEPS` | 3, 4 | Four two-word Title Case nouns is a consultancy deck. "Agree the direction · Write it · A bounded set of variations · Hand it over packed." |
| "structure first, not noodling" | showcase.py | 5 | He is not a working composer; this is craft talk from a chair he does not sit in. **Cut** — "built to the picture and the brief." |
| "Chordential is a music house that delivers original music finished: composed by people, cleared under a certificate we sign, packaged completely." | showcase.py `ABOUT` | 3, 6 | "Chordential is a music house. We write original music for campaigns, clear it under a certificate we sign, and hand it over in one package." |
| "runs the process so it stays contained: clear direction, bounded rounds, and a package that says what is in it" | showcase.py `ABOUT` | 3, 4 | "reads every brief, is on every call, and prices every note before a composer works on it." |
| "See how your next campaign could sound." | showcase.py `CLOSE` | 3 | "Tell me about the campaign." |
| "Built to brief." | showcase.py `DEMOS_INTRO` | 2 | "What's here is my own writing." |
| "Press play for the sound; send a brief to hear how we would score yours." | showcase.py | 4 | Semicolon parallelism. "Press play. If you want to hear how we'd score yours, send the brief." |
| "Hear how we'd score your brief." | showcase.py, commission.html | — | Keep. Plain, active, addressed to them. |
| "Finished the way a delivery is: a mix, not a sketch." | showcase.py `DEMOS` | 2 | "It's mixed, not a sketch." |
| "That the music here is made by a person. Nothing more is claimed for it." | showcase.py | — | Keep. Honest and flat, which is right. |
| "The music arrives with its **paperwork**." | commission.html | — | Keep. |
| "Everything, named the **same way**, every time." | commission.html | 4 | "Your editor opens one folder and works." (which is already the next line — promote it, cut the head) |
| "Not the music. / Not the versions. / Not the rights. / Not the paperwork." then "Just press **publish**." | commission.html | 2, 4 | Four fragments building to a two-word closer is the most manufactured thing on the site. **Cut all five.** Replace: "Nothing about the music should still be open the week you ship." |
| "Know the range before we **talk**." / "size the line before you spend an hour with anyone" / the price band | commission.html | 3 + brief §7 | Money in public. Out of scope for a voice edit, but flag it: the page renders a band, brief §7 and §13.10 say a figure lives on the proposal. |
| "Real briefs. Clean terms. Chosen, not bidding." | `for_artists.html` | 2, 4 | Three-beat headline. "Real briefs, and terms you can read in one pass." |
| "we'd rather treat a few people exceptionally than run a marketplace" | for_artists.html | 3 | "I'd rather work with a few people properly than run a marketplace." |
| "The music is always yours to be proud of; the paperwork is ours to carry" | for_artists.html | 2, 3 | "You write it. I carry the paperwork." |
| "When you're on the roster, you're on the roster." | for_artists.html | 2 | **Cut.** Says nothing twice. |
| "Your work, your credit, your reputation, organized and delivered well." | for_artists.html | 4, 3 | "Your name goes on the cue sheet." |
| "We work with a curated roster of creators" | for_artists.html | 5 | No creator has signed (brief §13.8). "I'm building a roster one signed agreement at a time." |
| "Reliability is how we intend to earn the relationship." | for_artists.html | 2, 3 | "I'd rather be early and boring about paying you than impressive about anything else." |
| "We review every reel personally. No automated screening." | for_artists.html | — | Keep. |
| "A range makes the number *yours*. It never sets the price." | `start.html` | 2 | "Whatever you put here, it doesn't set the price. It tells me whether I'm the right call." |
| "Read by the founder, not sorted by a machine." | start.html | 3 | "I read these myself." |
| "Nothing here commits you." | start.html | — | Keep. |
| "Chordential — Written for this campaign. Cleared. In the box on the date." (×4 sig) | `06-outbound-strategy.md` §2 | 2, 4 + brief §6 | The brief bans *"in the box on the date"* as a signature from a studio with zero deliveries. Use: "Jon Shipp · Chordential · Miami". |
| "One thing I keep seeing from the music side: the file arrives and the paper doesn't." | 06 §2 touch two | 5 | He has not been on the music side commercially. "One thing I keep getting caught by on my own jobs: the file shows up and the paper doesn't." |
| "Here is the list I hold my own studio to. It works on anyone you commission." | 06 §2 touch two | 3 | "This is the list I'm holding myself to. Use it on anybody." |
| "It costs me an hour. It isn't legal advice, and the page says nothing about my studio." | 06 §2 touch three | — | Keep. Best sentence in the sequence. |
| "The number isn't the point. The column marked 'assumed' is." | 06 §2 touch four | 2, 4 | "What I'd actually look at is the column marked assumed. Anything sitting in it on your job is a change order waiting to happen." (also drops one of the two money references in the touch) |
| "Anything in that column on your next job is a change order waiting to happen." | 06 §2 touch four | 6 | Folded into the line above; two epigrams back to back is one too many. |
| "Last one from me." | 06 §2 touch five | — | Keep. Exactly him. |
| "I'm building a small music house in {city} and I learn more from producers than from anyone." | 06 §2 touch five | — | Keep. |
| "We clear it so your business affairs team can sign without a cover note" | `04a` About | — | Keep. This is the §6 rule done right — what we do *for you*, not a definition. |
| "A composer's name goes on the cue sheet. Nothing generated, nothing pulled from a library." | 04a About | 4 | Light: "A composer's name goes on the cue sheet — nothing generated, nothing pulled from a library." |
| "Two things I'll say plainly." | 04a About | 2 | Announcing plainness is not plain. "Two things you'd find out anyway, so:" |
| "Nobody has to remember what anyone meant." | 04a post 2 | 2 | **Cut.** Standing alone as its own paragraph, it is reaching. |
| "Except it was 0:44. And it was on v2, and we're on v3 now. And the composer read it as the whole passage, not the hit." | 04a post 2 | 4 | Three *And*s. Rewritten in §3 below. |
| "You don't buy a business on a story about a business." | 04a post 4 | 2 | **Cut.** The most quotable line in the file and the least like him. |
| "nothing gets claimed that can't be shown" | 04a post 4 | 2, 6 | Second epigram in the same post. **Cut one; keep neither here.** See §3. |
| "That's the room in my head. It does not exist and I'm not pretending it's close." | 04a post 6 | — | Keep the second half; it is the honest, lumpy sentence the post needs. |
| "If you write, and you've never heard your own work played by real players in a real room, that's who this is for." | 04a post 6 | 2, 6 | A closer reaching for profundity. See §3. |
| "I'd rather ask you how you buy music than tell you how I sell it." | 04a post 3 | 2 | Borderline — it *is* an epigram. But it is also the ask, and it is true. **Keep, one per file.** |

---

## 2. The LinkedIn About, rewritten in full

*2,268 characters.*

> I run Chordential, a music house in Miami. We make original music for campaigns.
>
> I'm not a composer. Melodies and rhythms arrive most days and I have a folder full of
> things I never finished — I don't have the discipline to flush them out, and I stopped
> pretending I would. I still like making music. I can't help it.
>
> Some people did commit. They gave up other lives for it, and they can sit with an idea
> for six weeks and come out holding something finished. I want to own the place where
> those people get paid. I started with advertising because that is where the budget to
> pay them properly is still left.
>
> So here is what we do for you.
>
> We write the music for your campaign. A composer's name goes on the cue sheet — nothing
> generated, nothing pulled from a library.
>
> We clear it so your business affairs team can sign without a cover note: media,
> territory, term, exclusivity and publishing, on a certificate we sign, with releases on
> file for everyone who worked on it.
>
> We hand over what you approved, in one package — masters, cutdowns, stems, cue sheet,
> certificate, and a manifest naming every file. On the date we agreed.
>
> The whole job runs in one room at one link. You play the take, mark the second you mean,
> and the note stays on that version. A round is numbered and buys one version. Every note
> gets read before a composer touches it, so nothing turns into a change order by accident.
>
> Two things you'd find out anyway, so: Chordential has no paying client yet — I'm writing
> this the day I start selling. And no machine-made music, anywhere, including the
> demonstrations on my own site.
>
> What I post here. Mondays, something I learned building this. Wednesdays, one thing the
> room does. Fridays, what changed and what still isn't true.
>
> If you're carrying a music licence on a live campaign and you're not sure what it covers,
> send it over. I'll read it and send back one page: what it covers, and where it doesn't.
> Costs me an hour. It isn't a pitch.
>
> I'm one person, building a roster one signed agreement at a time. I read every brief and
> I'm on every call. I'm also AV director at Encore, which is where I learned what a real
> load-in does to a schedule.

**What changed and why.** The three-part offer keeps the §6 structure (*we write it for
your campaign / we clear it so… / we hand over…*) because that rule is right and the old
draft already obeyed it — but the paragraphs before it were a company describing itself
before it had a reason to. Now the reason comes first, in his own facts, and the offer is
the answer to it. "Two things I'll say plainly" became "two things you'd find out anyway",
because announcing your plainness is a pose. The Encore line moved to the end and got a
reason to be there. Nothing claims a client, a composer or a delivery.

---

## 3. The posts I marked failing, rewritten

### Monday 14 Sep — why this exists

> **I have a folder full of unfinished things.**
>
> Melodies and rhythms show up most days. They come fast and they leave faster, and I've
> never had the discipline to chase one all the way down. I used to compose. I stopped.
>
> Some people don't stop. They surrendered other lives to keep going, and they can sit
> with one idea for six weeks and come out the other side holding something finished. I
> can't do that, and at some point I quit being annoyed about it.
>
> What I can do is build the place that pays them. That's Chordential — original music for
> campaigns, written by a composer whose name goes on the cue sheet, handed over with the
> paper that lets you actually use it.
>
> I started with advertising because that's where the budget to pay a composer properly is
> still left.

*Fix: the old "I can't do that. So I'm building the place that pays the people who can."
was a two-beat aphorism sitting alone. The new version admits something instead.*

### Wednesday 16 Sep — one thing the room does

> **If you've ever had a music note travel through an email thread you know how this goes.**
>
> "Can we try the thing at 0:42 again?" Except it was 0:44, and it was on v2 and we're on
> v3, and the composer took it as the whole passage when you meant one hit.
>
> In our room you click the bar at 0:42 and the music stops. You type what you heard. The
> note is pinned to that second, on that version, and it stays there. If you meant 0:44,
> drag it. Nobody has to reconstruct later what anybody meant.
>
> That's from a demonstration on an invented brand. There's no client work to show yet.

*Fix: the three-*And* fragment run collapsed into one lumpy sentence, and the standalone
epigram folded back into the paragraph it belongs to.*

### Monday 21 Sep — the studio I did not buy

> **I tried to buy a recording studio last year.**
>
> I've wanted to own one for as long as I can remember. The listing came up, I got
> excited, and I asked for the financials.
>
> He didn't have any. Nothing I could make a sound decision on.
>
> So I offered him something else: let me operate it for a year and pay you rent. You get
> to see whether I run it well. I get to see what the place is actually worth. Then we talk
> about a sale with real numbers on the table.
>
> He said no. That was the end of it, and I walked.
>
> I'd make the same ask again. I'm doing the digital side first now, and I'm running it the
> same way — I'd rather show you a thing than tell you about it.

*Fix: both epigrams gone ("You don't buy a business on a story about a business"; "nothing
gets claimed that can't be shown"). "Nothing I could make a sound decision on" is his own
phrasing. Note this post touches money — it is his own deal, not a client's, and no figure
appears; if the founder reads §7 strictly, the ask is describable without the word rent.*

### Friday 25 Sep — what this is for

> **What I'm actually building toward.**
>
> Twenty-five hundred square feet, built for chamber orchestra. A composer anywhere dials
> in and conducts the session in real time — their score, real players, no plane ticket.
>
> That's the room in my head. It does not exist and I'm not pretending it's close.
>
> The digital side comes first because it's what I could build, and because it has to earn
> the room. Most composers I know of will never get to book an ensemble on their own. I'd
> like there to be one place where that isn't true, and every job that runs through this is
> a step toward paying for it.

*Fix: the manufactured "that's who this is for" closer is gone. The post now ends on the
thing he wants rather than on a line pointed at the reader.*

**Left as they are: Friday 18 Sep and Wednesday 23 Sep.** Post 3's two-list structure
(what exists / what doesn't) is honest, uneven and unquotable — the best writing in the
file. Post 5's "That's the whole list" earns its shortness because it is a claim about an
actual list directly above it, and the button anecdote is a real thing that happened to
him. Two line fixes only: post 3's "checkable" is a slightly writerly word (use "true
while I can still be held to it"); post 5's "Demonstration, invented brand. Nothing
shipped yet." should be a sentence — "That's a demonstration on an invented brand. Nothing
has shipped yet."

---

## 4. The voice card

Twelve lines. Every DON'T is lifted from the copy as it stands.

1. **He says "I", not "we", about himself.** DO: "I read every brief." DON'T: "The founder,
   Jon Shipp, reads every brief" (showcase.py `ABOUT`). *"We" is only for the studio doing
   the work for a client.*
2. **He admits before he claims.** DO: "I don't have the discipline nor the willpower to
   flush them out." DON'T: "Reliability is how we intend to earn the relationship."
3. **He never defines a word.** DO: "we clear it so your business affairs team can sign
   without a cover note." DON'T: "Composed means written for this campaign…" (struck from
   his own About) or any "in other words".
4. **He does not land a line.** DO: "he didn't have any financials to support me making a
   sound decision on buying it." DON'T: "You don't buy a business on a story about a
   business."
5. **No three-beat headlines.** DO: "The music arrives finished." DON'T: "Real briefs.
   Clean terms. Chosen, not bidding." (for_artists.html)
6. **Verbs, not abstract nouns.** DO: "we hand over what you approved." DON'T: "Bounded
   Delivery", "Direction Lock", "Controlled Variation" (showcase.py `STEPS`).
7. **Never the same opening word five headings running.** DON'T: Every / Every / Every /
   Every / Everything (score.html). Fragments and parallels are fine once a page.
8. **Warmth about creative people is stated, not performed.** DO: "why not support people
   that have surrendered and sacrificed their life so that they could create." DON'T:
   "Your work, your credit, your reputation, organized and delivered well."
9. **He only speaks from chairs he has sat in** — live production, hiring vendors, buying,
   the studio he didn't buy. DON'T: "structure first, not noodling" (showcase.py) or "one
   thing I keep seeing from the music side" (06 §2).
10. **Evidence or nothing.** DO: "there's no client work to show yet." DON'T: "a curated
    roster of creators" (for_artists.html) when none has signed.
11. **Money stays out of public.** His own rule: "producers dont like talking about budget."
    DON'T: "Know the range before we talk" plus a rendered band (commission.html).
12. **Sentences should be uneven.** A long one, then a short one, then a long one — not
    three short ones in a row. If a paragraph scans, break it.

---

## 5. What I would leave alone

- **The About's three-part offer** (*we write it / we clear it / we hand over*). It is the
  §6 rule executed correctly and it is the one place the copy already sounds like a man
  telling you what he'll do. I kept the structure and the clause about the cover note
  verbatim.
- **Friday 18 Sep, nearly whole.** Two flat lists of nouns, no rhythm, one hard admission.
  Every instinct a line editor has wants to smooth it. Don't. Its unevenness is the proof.
- **"It costs me an hour. It isn't legal advice, and the page says nothing about my
  studio."** (06 §2 touch three.) Three facts in a row with no persuasion attached. Best
  sentence in the outbound file.
- **The Clearance Read offer wherever it appears.** Concrete, bounded, gives something,
  asks nothing. It is the only piece of copy here that would work if he were a worse writer.
- **The six objection answers in 06 §5.** They already read as speech — "I am." as an
  answer to "you're in a weird middle" is exactly his register. They are also the only
  place money is discussed correctly, because it is one-to-one after a call.
- **score.html's close** ("There are no case studies yet, and we say so.") and its
  standing footer ("Every brand here is invented.") — plain, load-bearing, unimprovable.
- **The demo copy in showcase.py's `DEMOS`** — "Nothing more is claimed for it" is the
  honesty rule in five words and doesn't try to be more.
- **Every engineering comment in these files.** They are not copy and several of them are
  better written than the copy. Out of scope; leave them.
