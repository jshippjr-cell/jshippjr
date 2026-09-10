# Voice review — read as the buyer

*Read 2026-09-10 by the seat this copy is aimed at: senior producer / head of production,
agency, Miami–Atlanta, fifteen years, commissions music four or five times a year. I am
not hostile. I am busy, and I delete almost everything.*

---

## 1. The three-second verdict

**The profile headline.** *"Founder, Chordential — a music house. Original music for
campaigns: composed, cleared, delivered · AV Director at Encore"*
(`04a-the-first-posts.md`). I keep reading — because of the last five words. Encore is a
name I know from every ballroom job I've run in this city, and "AV Director" tells me this
person has sat on my side of a purchase order. That is the credibility in the line and it
is in last position, behind a company I've never heard of and a three-beat vendor cadence.
Lead with the seat you actually hold.

**The About, first two lines.** *"I run Chordential, a music house. We make original music
for campaigns, and we finish it."* The first sentence is fine. **"and we finish it" is
where I flinched.** It is a swipe at whoever burned me last, delivered by a house that has
finished nothing commercially, and it is the one claim on the page he cannot back. Two
paragraphs later he tells me he has no clients — so the boast and the confession are on
the same screen. The next line recovers it: *"A composer's name goes on the cue sheet."*
That is someone who knows what I file.

**The front door, first screen** (`public/score.html`). *"Original music for campaigns —
composed, cleared, delivered."* / *"The music arrives finished. We write it for your
campaign, by people, and we deliver every version, approval, cue sheet and rights document
finished, in one package. At any moment you can see where it stands."* I continue, barely.
"Finished" twice in two sentences. **"by people"** is the AI badge the brief itself says
never to wave, waved in the hero. And I stop cold at *"At any moment you can see where it
stands"* — that is a software sentence, and I am not buying software.

---

## 2. Every line that made me wince

| Line | File | What's wrong | Fix |
|---|---|---|---|
| "Music rarely fails creatively. It fails operationally." | `showcase.py` PROBLEM | A law of my industry handed to me by a house with zero deliveries. It is also half wrong — music fails creatively all the time, that's why I sit through five rounds. | Cut it. |
| Step timelines: "Day 1–2 … Day 3–6 … Day 7–9 … Day 10" | `showcase.py` STEPS | A delivery schedule from a house that has never delivered, and it **directly contradicts his own post**: *"Any number about how long a job takes here, because no job has run."* One of these two surfaces is lying to me. | Cut the days. Keep the four stages. |
| "Every conversation becomes momentum." | `score.html` beat 03 | Poster. Means nothing. | Cut it. |
| "Every campaign begins with understanding." / "…what success looks like before a single cue is discussed" | `score.html` beat 02 | Agency-deck boilerplate. I have written this slide. | "Tell me the film, the media plan and the date. I'll tell you what I'd need to assume." |
| "Our job is to turn complexity into a direction everyone can build from." | `score.html` beat 03 | Thought-leader cadence. A company talking, not a person. | Cut it. |
| "Creative judgment is still the most important instrument in the room." | `score.html` beat 04 | Being taught my own religion, and "still" implies someone argued otherwise. | Cut it. |
| "Creative conversations should move the work forward, not create more work." | `score.html` beat 05 | Telling me what I already believe so I'll nod. | Cut it. |
| "structure first, not noodling" | `showcase.py` STEPS 2 | Calling composers noodlers, to a producer who hires composers. Wrong room. | "Built to the picture and the media plan." |
| "There are no case studies yet, and we say so." | `score.html` beat 07 | **"and we say so"** asks for credit for honesty. That's the moment integrity turns into a personality trait I'm supposed to admire. | "There are no case studies yet." Full stop. |
| "Every brand here is invented. There is no client work yet." | `score.html` beat 07 meta | Correct — but it's the *second* time on the same screen. | Keep this one, cut the other. |
| National retail brand case: "Five stakeholders, two rounds of legal, a moving deadline." | `showcase.py` CASES | An invented case with invented friction, labelled a demonstration. A fake war story is worse than no war story. | Cut both CASES entries. |
| Field Notes ×3 "Coming soon" | `showcase.py` FIELD_NOTES | Three empty headlines. Furniture. | Cut until one exists. |
| "See how your next campaign could sound." | `showcase.py` CLOSE | Vendor. Every vendor. | "Send me the brief. I'll tell you what I'd assume." |
| "runs the process so it stays contained" | `showcase.py` ABOUT | Process language about the thing I care about least. | Cut. |
| "I Dream of Dancing With My Seductress in Hell" | `showcase.py` DEMOS | This is the **only** audio on the site. On a page selling to a national brand, that title is the loudest thing present, and it tells me nothing about whether he can land a :30. | Keep it if it must stay, but it cannot be the only track (see §6). |
| "Something real, while the roster is built." | `showcase.py` DEMOS objective | Says out loud that the work on display is a placeholder for the work. | Cut the line; let the music do it. |
| "Everyone who plays on your score signs to us before a note leaves the building." | `commission.html` §paper | There is no building. | "…signs before anything ships." |
| "The session cellist's release is out for signature" | `commission.html` cert | Fabricated specificity on an invented brand. I notice invented cellists. | Genericise or cut the clause. |
| "Just press *publish*." | `commission.html` close | Poster line. | Cut. |
| "Nothing to chase, nothing to rename, nothing outstanding." | `commission.html` §deliver | Three claims, zero deliveries. | "Named the same way every time" — which the manifest actually shows. |
| "and we finish it" | About | See §1. | "We deliver on the date we agreed, and I'll tell you the date before you commit." |
| "What I post here. Mondays… Wednesdays… Fridays…" | About | A content calendar in a bio. Nobody has ever cared. | Cut. |
| "Chordential is one founder, building a roster one signed agreement at a time." | About | "One X at a time" is LinkedIn cadence. | "Right now Chordential is me. I read every brief and I'm on every call." |
| "No paying engagement yet; I say so." | Experience blurb | "I say so" congratulates himself for the previous clause. | "No paying engagement yet." |
| "Real briefs, not spec… We bring you scoped, paid work." | `for_artists.html` | Promising paid work to composers from a house with no work. | "When I have a brief, it's paid and it's scoped. I don't have one yet." |
| "When you're on the roster, you're on the roster." | `for_artists.html` | Says nothing twice. | Cut. |
| "steady paycheck. that wouldn't be honest." | `for_artists.html` | Lowercase 't' after a period. On a page about rigour. | Fix. |
| "A range makes the number *yours*. It never sets the price." | `start.html` | A pricing lecture on a form field. | "Optional. It helps me tell you fast if we're not a fit." |

Two things I would **not** touch: *"Read by the founder, not sorted by a machine."*
(`start.html`) and *"Nothing here is sent and nothing leaves this browser."*
(`score.html` review demo). Both are plain, both are checkable.

**Where I disagree with the brief.** §7's *never about money in public* is wrong for my
seat. The planning band on `commission.html` — three dropdowns, a range, and *"A planning
band, not a quote… Nobody should hold either of us to this one"* — is the most useful
object on the site. Producers shop quietly precisely because nobody will show a number;
the house that shows one first gets the call. Enforcing §7 would delete it and leave the
site with nothing but adjectives. Keep the band; keep the disclaimer exactly as written.

---

## 3. The six posts

**1 · "I have a folder full of unfinished things."** I read past the first line — that is
a real sentence, not a hook. I finish it. It makes me *like* him, which is not nothing.
But note what he just told a prospective buyer: the founder of the music house does not
finish things. *"So I'm building the place that pays the people who can"* saves it by one
sentence. I'd like it. I would not reply.

**2 · The 0:42 / 0:44 note.** *"If you've ever had a music note travel through an email
thread, you know the shape of it."* Yes. This is the only opening line in the six that
describes my actual week. I finish it. This is the post I would **comment on** — and
comments are how strangers become calls. Then the last line, *"That's from a demonstration
on an invented brand. There's no client work to show yet,"* lets the air out of a post
that had earned its close. Move the disclaimer up, or trust the pin at the top of the feed
to carry it.

**3 · "What is true on day one."** Right idea, wrong order. The *"What exists"* paragraph
is a 120-word wall of features and I skim it — that's software copy, and it's guarding the
good part. The *"What doesn't exist"* list is the best writing on the profile: *"A paying
client. A delivered job. A case study. A testimonial. A logo on a wall."* That's my own
diligence checklist read back to me. And the Clearance Read offer at the bottom is the
single most repliable thing in the whole plan, buried in position five. **Flip it: the
denials first, the offer second, the feature wall cut to three lines.** As written I skim
to the end and don't act. Rebuilt, this is the post that gets me to write back.

**4 · "The studio I did not buy."** Best of the six by a distance. It has stakes, a
refusal, and a principle he *earned* instead of stating: *"You don't buy a business on a
story about a business."* I finish it, and it does more for my trust than every mechanism
on the front door combined, because it shows judgment under money pressure — which is
exactly what I'm buying. Only misstep is the tidy tie-back at the end; the story didn't
need a moral.

**5 · The Approve button.** *"Locks the master as the version you chose. Spends no round.
Releases no payment. Can be undone until the package is built."* — good, and *"I've pressed
buttons in other people's software at hours when there was nobody left to call"* is real.
But it is a post about his software, and I do not buy software; I buy music and I tolerate
whatever tool comes with it. Scroll past. Save this one for the composers.

**6 · The 2,500 square feet.** Strong content, weak opening — *"What I'm actually building
toward"* is a throat-clear. And it closes *"If you write, and you've never heard your own
work played by real players…"* — I don't write, so it tells me I'm not the audience.
Scroll past as a buyer. But it is the post I would **remember**, and the one I'd forward to
a composer friend, which may be worth more.

Honest arithmetic: five of these six get scrolled past by me on a normal Tuesday. That is
normal and not a criticism. Posts 2 and 4 are the two with a real chance, and 3 could join
them if it were reordered.

---

## 4. The five outbound messages

**Touch one (connection request).** Accepted. Not replied to — connection requests don't
get replies, and shouldn't. The whole thing rides on `{one thing}`: a real observation
about my work. If that slot is filled with "great work" this is dead on arrival, and in my
experience it is filled with "great work" nineteen times out of twenty.

**Touch two (the delivery checklist).** Read to the end. Not replied to — and it says *"No
reply needed,"* so it did its job. The list is right; *"A manifest naming every file, so
nobody asks 'is this everything?' at six"* is a producer's sentence. **What damages it is
the signature:** `Chordential — Written for this campaign. Cleared. In the box on the
date.` That's a tagline stapled to a no-ask email, and it converts a gift into an ad. It
also violates the brief's own §6, which bans "in the box on the date" as a signature — all
four emails carry it. Strip it to `Jon Shipp · Chordential · Miami`.

**Touch three (the Clearance Read).** **This is the one that gets a reply.** It names a
problem I actually have — a client brings a track from their last agency and nobody can say
what it covers — it is bounded to an hour, it is not spec, and it disarms itself: *"It
costs me an hour. It isn't legal advice, and the page says nothing about my studio."* That
last clause is the best sentence in the outbound plan. And *"If nothing's live, ignore
this"* is how you write to someone at 8am. This should be touch **two**, not three; by day
17 I have already filed him.

**Touch four (the breakdown).** Deleted. *"I priced an invented brief in public this
month"* — nobody outside this plan cares what he did in public, and two attached pages from
a stranger at touch four is presumption. The idea inside it is good (*"The column marked
'assumed' is [the point]"*), but it needs to be one paragraph about a job shape I recognise,
pasted, no attachment.

**Touch five (twenty minutes).** Deleted. By touch five with no reply from me, I have
decided. *"I learn more from producers than from anyone"* is flattery and I can hear it.
The salvageable part is *"I'll send you what I heard, in writing, the same day, so you can
correct it"* — that's a real offer, and it should be inside touch three.

**Net:** one reply out of five, and only from touch three, and only if it arrives before
I've pattern-matched the sender to a sequence. What kills the rest: every email is the same
shape — a paragraph, a list, a self-effacing close — so by the third one I can see the
machine behind them, and the brief's whole premise is that there isn't one.

---

## 5. The no-clients admission

**Integrity, but it has become a mannerism.** As a fact, once, in the right place, it buys
him something: it makes every *other* claim on the page more likely to be true, which is
the whole return on it. That is real, and I'd rather have it than the alternative.

**Where it lands well.** Post 3's *"What doesn't exist"* list — because it is itemised, it
is my own diligence checklist, and it is followed by what he's doing about it. And in the
About, *"This is written on the day I start selling and I'd rather tell you than let you
find out"* — because it is dated and therefore checkable.

**Where it is too much.** Three of the six posts end on the same disclaimer. The front door
says it twice on one screen. `for_artists.html` has a whole section titled *"What we won't
promise."* At that density it stops being information and becomes a posture — and
*"and we say so"* is where it tips over into asking me to grade him on it. Honesty is table
stakes with me, not a differentiator; the copy treats it as the offer.

**The deeper problem.** He admits the gap and then puts nothing in it. Six surfaces tell me
there is no proof; not one of them replaces proof with something else I can judge. State it
**once**, on the About, dated, and let every other surface spend its words on work.

---

## 6. What is missing

**One piece of music, written to a brief I recognise, with the brief printed beside it.**

The entire audio evidence on this site is one old personal track called *"I Dream of
Dancing With My Seductress in Hell"*, described as *"written years ago, not to a brief,"*
by a man who says on his own profile that he doesn't finish things. Every mechanism on the
front door — the pin at 0:42, the certificate, the manifest, the numbered rounds — is
downstream of the only question I have, which is *can the music be good*. None of it is an
answer.

Concretely: commission one composer, at his own cost, to score an invented :30 for a
category I actually buy — automotive, QSR, financial. Publish the brief he was given, the
:60, the :30, the :15 and the :06 bumper, three variations, and the cue sheet. Then I can
hear whether he can hold a hook through a six-second cutdown, which is the thing that gets
music killed in my edit. This requires no client, no case study and no permission — only
money he says the digital side exists to spend.

Second, smaller: **name one composer.** *"A composer's name goes on the cue sheet"* — whose?
One signed writer with credits I recognise would outrank the whole delivery apparatus. Right
now the roster is a promise about a promise.

Do the first of those and I stop reading and start replying.
