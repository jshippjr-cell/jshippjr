# The Composer Track — the supply side, deliverable

*Wave 4, 2026-09-10. Reads under `docs/marketing/00-brief.md`; the brief wins. Every term is
READ OUT of `composer_agreement.py`, `service_agreement.py`, `compensation.py`,
`agreements.py`, `talent.py`, `matching.py`, `room.py`, `creator_routes.py` — nothing is
invented. Revenue is zero, no roster is signed (brief §13.8), and nothing here may tell a
composer work is waiting.*

**Fix before this is used.** `recruiting.py` says *"real, paid briefs (never spec)"* and
`for_artists.html` *"We bring you scoped, paid work"* — present tense, zero engagements
sold. Honest form: *when a brief fits, you hear first, and it will be paid.*

---

## 1. What we are actually offering a composer today

**`agreements.kind_for` decides which of two documents governs**, from recorded disciplines
and never guessed. Composition, sonic branding or arrangement → **Composer Agreement**.
Mixing, sound design, supervision or licensing → **Service Agreement**. No discipline
recorded → the surface says so and offers *neither*.

**Composer Agreement v2.0 — people who author the music.**

- **30% of net creative revenue**, rising to **40%** where they also orchestrate or produce
  the session (`COMPOSER_SHARE`, `COMPOSER_SHARE_WITH_SESSION`). "Net" is the creative fee
  less money passing to *unconnected third parties on that job* — players and their
  pension/health, room and gear hire, session engineers. *"Nothing else is deducted — not
  the studio's own time, overhead, software, insurance, commission, travel."* Not gross:
  *"booking an orchestra is not a fact about the writer's work."*
- **Licence income is shared too:** if the client later pays to extend term, widen
  territory, add media or buy out, the writer gets **the same 30% of the net of that
  payment, for as long as the work earns**, surviving the agreement's end. **A demo we
  request that loses is paid $400 flat** (`DEMO_FEE`).
- **Publishing:** the composition is assigned to Chordential Music for life of copyright,
  and **50% of the publisher's share belongs to the writers**. They keep **their writer's
  share of performance income**, paid direct by the PRO — *"not the studio's to take, and
  this agreement does not take it."* With no publishing entity, the studio **holds** the
  writers' half, says so in writing, and files or pays it over **within 30 days** of them
  naming one: *"not by default and not by silence."*
- **Cue sheet:** *"The studio credits the writer as composer on the cue sheet it files,
  every time … and it is a promise"* — filed within 30 days of first broadcast, copy sent.
  A client's own credit list is a **promise to ask**.
- **Paid within 30 days of the client settling, and in any event within 120 days of the
  client accepting delivery, whether or not the client has paid.** The estimate holds: it
  rises if the client pays more and is never cut below without written agreement. **If the
  job dies:** 50% before delivery, 100% after. An itemised statement with every payment,
  and an **audit once in any 12 months** — the studio pays for it, and the shortfall, if
  they were underpaid by over 5%.
- **No exclusivity over their time, ever** — *"this agreement claims no exclusivity over
  the writer's time and never will."* The cue isn't re-licensed, and for **12 months from
  first broadcast** no knowingly similar cue for a competing brand in the same category.
  After public release they may put the finished track and **up to 60 seconds** of the spot
  on their reel and say they wrote it.
- **Their risk:** they warrant the work is human-made and clean, with liability per
  engagement **capped at the greater of $25,000 and 3× the fees paid them for it**. Florida
  law, Miami-Dade courts (defaults).

**Service Agreement v1.0 — mixing and mastering, music editing, sound design,
supervision.** A **fee, not a share**, from their own recorded rate, in writing before
acceptance. **No publishing, said out loud** — with one exception theirs to raise: original
musical material is declared *before delivering* and settled as authorship under the
Composer Agreement, or not used; *"raising this is never a breach and never a reason not to
book someone again."* They assign only what they make, never the underlying composition. A
mix comes from the composer's approved stems, an edit from the mixer's approved master.
Delivery targets are named per medium (48 kHz / 24-bit WAV; US broadcast −24 LKFS ±2, ATSC
A/85; streaming −14 LUFS). Same acceptance window, kill fee, backstop, cap and credit.

**What the room gives them that a normal gig does not.** Notes arrive **priced**:
`room.priced_notes_only` lets a note reach a creator only after a human has called it
*conform* (free), *revision* (spends a round) or *out of scope* (quoted, never actioned for
nothing). Rounds are bounded — one round buys one version, and a second change request
while the studio still owes a version is refused server-side. A new cut is parked until the
studio states the frame offset. **The client never has their name or email** (`room.CAPS`
gives the client no `see_who`), and the creator never sees the client's budget.

**What we are NOT offering**, in the agreement's own words:

> *"This is a standing agreement, not a booking. It commits you to no work and guarantees
> you none. Each engagement is offered and accepted separately, with its own scope and fee,
> and this document sets the terms that apply when you accept one."*

Plainly: **no work today**, no retainer, no minimum, no volume, no exclusivity, no spec,
and nothing signed until it means something (§5).

---

## 2. Who we are looking for

Counts are **before the first job**, deliberately small: a roster larger than the work is a
roster of people we are disappointing. `talent.matchable` needs an approved reel **and** a
recorded discipline, so a count means *approved and described*, not emailed.

| Profile (code discipline) | The work | Evidence that qualifies | Need |
|---|---|---|---|
| **Spot composer, to picture** (`COMPOSITION`) | :60/:30/:15 to a near-locked cut; hits, a button on the logo; stems and cutdowns from one session | 2+ released spots where they wrote the cue; a reel of music *against picture*, not tracks | **3**. Never one: a single composer is one point of failure on an air date |
| **Sonic identity writer** (`SONIC_BRANDING`) | A mnemonic that survives 10,000 plays, and its variants | A sound logo you can hear in the wild, or a mnemonic with its family | **1**, may be the same person |
| **Arranger / orchestrator** (`ARRANGEMENT`) | Charts, session prep, conducting; making a mock-up sound played | Charts they wrote; a session prepped or conducted | **1**. Also the 40% share, and the bridge to the room |
| **Mix / master engineer** (`MIXING`) | Mix from the composer's approved stems to the medium's loudness target | Talks about −24 LKFS / ATSC A/85 without looking it up; broadcast credits | **1** |
| **Music editor / versioning** (`MIXING`) | Cutdowns, verticals, conforms to a re-cut picture | A job where the picture changed and the music followed; EDLs, fps, timecode | **1**, usually the mixer |
| **Sound designer** (`SOUND_DESIGN`) | Designed elements under and around the cue | A design reel; knows whether a library licence permits stem delivery | **1** |

**Six people, six agreements** — a supervisor (`SUPERVISION`) is worth knowing but not
needed to deliver. Jon's gap, "none in the style I'd hire", is profile one, so that is
where the evening in §6 goes.

---

## 3. Where they actually are

**The doctrine inverts here.** Client-side, a room is never used to reach a target.
Supply-side, composers gather in these rooms *to find work*, so a real opportunity is the
contribution rather than the intrusion. **Where the line still is:** only in rooms whose
rules permit it, in the channel they designate; **no money in public, ever** (brief §7);
**never post a brief that does not exist**; one post per room, then answer replies — and
reading other people's threads comes first.

| Place | Who is there, and why it matters | Approach — and what we contribute |
|---|---|---|
| **VI-Control** (vi-control.net), free | Media composers writing to picture in mock-up; founded 2004, ~114K unique visitors a month. Profiles 1 and 3 | Read two weeks; post only in the jobs section *(verify its rules)*. We bring plain answers on ad-side paper |
| **Society of Composers & Lyricists** (thescl.com) | Media composers; confirmed to consider *"music creators for commercials … case by case."* The credentialled end of profile 1 | Join as the studio side, attend before asking *(verify which category fits a studio operator)* |
| **Airwiggles** (airwiggles.com), free | Sound designers; 8,000+ members, runs the Audio Challenge and Noisevember. Profile 6, with public dated work | Contribute to a challenge first. A craft room, not a job board *(verify whether a work post is welcome)* |
| **Game Audio Network Guild** (audiogang.org) | The largest game-audio body; game audio trains interactive versioning, the cousin of cutdowns | Member events and the student competition. We bring ad-side delivery literacy |
| **ASCAP and BMI member resources** — workshops, member directories, local reps *(verify program names and whether a non-member may attend)* | Every writer we want is affiliated with one, and a rep knows who writes to picture in their territory | Ask the membership rep for an introduction, not a list. We bring a studio that registers works and files cue sheets within 30 days |
| **Soundlister** (soundlister.com), free | Composers, designers, supervisors, engineers | **Post only when an engagement exists.** Until then, read who is looking |
| **SoundBetter** (soundbetter.com) | Mixers and mastering engineers with reviews and audio attached. Profiles 4 and 5 | Browse, reach out one to one. Never run a job through it: fee, paper and rights live in our agreements |
| **Reddit** — r/composer, r/WeAreTheMusicMakers, r/audioengineering, r/GameAudio *(verify each)* | Working and emerging composers and engineers; public reel threads | Hard self-promo rules; message the mods **before** posting. We bring straight answers on rights |
| **UM Frost — Media Scoring & Production**, Miami | Writers trained for media, and their faculty. **Local**, so able to come to a session later | Published contacts (admission.music@miami.edu, 305-284-6168). **Ask faculty which alumni are working** — students are not who he is hiring |
| **Berklee — Film and Media Scoring**; **Full Sail**; **SCAD Atlanta** *(verify programs and alumni boards)* | The largest US pipeline of trained media composers, plus Southeast engineers | Alumni tools *(verify non-alumnus access)*. Alumni, not students |
| **Recording Academy — Florida Chapter**, Miami Beach | The Florida/Puerto Rico recording community since 1995 — where players and introductions are | Chapter events, repeatedly, before asking anyone for anything |
| **AFM Local 655**, South Florida | Union players. **Session players later, not composers now:** clause 6A forbids engaging anyone under a union agreement without prior written agreement | Say plainly he has not run a union session and would need to learn the paper first |

First month, in order: **Frost, VI-Control, SoundBetter.**

---

## 4. The approach, written out

Slots: `{first}` `{piece}` `{one thing}` `{craft}` `{where}`.

### Message one — a composer whose work he found

**Subject:** Your {piece}

> {first},
>
> I found {piece} through {where} and listened to the whole thing. {one thing}
>
> I run a small music house in Miami called Chordential. Original music for ad campaigns —
> written by people, cleared under a certificate I sign, delivered with the stems, cutdowns
> and cue sheet in the box.
>
> Where it stands, straight: I have no client work today. I started this in November 2025
> and I'm selling the first engagement by hand. So I'm not offering you a job, and I'd
> rather say that in the first email than let you find out in the third.
>
> What I am doing is building a very small roster — a handful of people, {craft} among them
> — so that when a brief lands I'm calling someone whose work I already know. If that's
> worth a reply, I'll send you the terms I'd work under, in full, before I ask you for
> anything. Either way, thanks for {piece}.
>
> Jon Shipp
> Chordential — Miami

**No fee in it.** The brief forbids money in public, and the fee is job-dependent anyway.
He says instead: **"I'll send you the terms I'd work under, in full, before I ask you for
anything"** — checkable, because the document exists and states the share.

### Message two — they replied with interest

> {first},
>
> Glad you wrote back. Here's the whole thing so you can decide with the facts.
>
> **What I'd eventually ask you to sign** is one standing agreement. It is not a booking:
> in its own words, *it commits you to no work and guarantees you none.* Each job is offered
> and accepted separately, scope and fee in writing before you accept.
>
> **What it pays.** A share of the creative fee on each job — net of money that goes
> straight out to players, rooms and engineers, because an orchestra being booked isn't a
> fact about your writing. A demo I ask for is paid whether or not it wins. The percentages
> are in the document, and I'll put a real number against a real brief; I do that on a
> call, and I don't discuss numbers in public at all.
>
> **What you keep.** Your writer's share of performance income — the PRO pays you direct
> and I never touch it. Half the publisher's share belongs to the writers. Your name goes on
> the cue sheet I file, every time, within 30 days of first broadcast. No publishing entity
> yet? I hold your half *for* you, tell you in writing I'm doing it, and hand it over within
> 30 days of you naming one. I don't keep it by silence.
>
> **What it doesn't ask for.** No exclusivity over your time, now or ever. The cue itself
> isn't re-licensed, and for a year you don't knowingly write a near-identical cue for a
> competing brand. That's the whole of it.
>
> **What I do that a normal gig doesn't.** Client notes never reach you raw — I classify
> each as a conform, a revision or out of scope first, and the out-of-scope ones stop at me.
> Rounds are counted. The client never gets your name or email. And you're paid within 120
> days of the client accepting the work, whether or not the client has paid me.
>
> **What I won't say.** That work is coming. It isn't yet. I'll send you the agreement to
> read whenever you want, with no signature attached, and I won't ask you to sign anything
> until there's a brief with your name against it.
>
> Twenty minutes on a call if you'd like — mostly me asking what you've been burned by.
>
> Jon

### The one-page note he can send anyone

> **Chordential, in one page — for composers and engineers**
>
> I'm Jon Shipp. I'm in Miami, I direct AV for live events, and I started Chordential in
> November 2025. It makes original music for ad campaigns: written by a person, cleared
> under a certificate I sign, delivered complete — stems, cutdowns, cue sheet, manifest,
> the rights paper — on the date agreed.
>
> **Where it honestly stands.** No paying client yet. I'm selling the first by hand, I am
> not hiring today, and I won't pretend otherwise.
>
> **Why I'm doing it.** I have musical ideas most days and stopped finishing them years
> ago, so I know what I am and what I'm not. What I'm good at is running things to a
> deadline in front of a room full of people, so rather than pretend to be one of them, I'd
> rather help the people who did commit their lives to this get their work made and get
> paid properly for it. The
> longer aim is a room — 2,500 to 3,000 square feet, built for chamber orchestra, where the
> composer conducts the session from wherever they are. The digital side earns that room.
>
> **What I built while there's no client.** Two standing agreements, written in plain
> language rather than in the usual fog. Ask and I'll send you whichever one would govern
> you, whole and unsigned, to read at your own pace — and have your own person look at it
> before you ever sign. I'd think less of you if you didn't.
>
> **What I won't do.** No AI-generated music anywhere, including as a demo. No spec. No
> exclusivity over your time. No promise of volume.
>
> **What I'd like.** To know your work before I need it. Send me something you're proud of,
> and tell me what you've been burned by on ad jobs.
>
> Jon Shipp · Chordential · Miami

---

## 5. What they sign, and when

**A roster entry before any job** is a `talent` row: name, email, disciplines, credits,
location, reel URL, review and invite status, source and rate. `talent.matchable` is true
only when Jon has **approved the reel** and **one discipline is recorded**.
`matching.match_talent` then ranks approved creators against a brief — 60% discipline fit,
30% credit overlap, 10% completeness — and **explains every score**. It never assigns.

**The agreement is standing, not a hire.** It sets the terms that apply *when* an
engagement is accepted, conveys rights only for work done under it, and either side can end
it in writing at any time. **`db.talent_assignment_blockers` refuses assignment unless
`agreement_executed_at` is set and a rate above zero is on file** — so a signature must
exist before assignment, which is *after* a real job exists, and nothing requires one at
roster time.

**So signing at first contact is the wrong shape, and the code agrees.** Asking a stranger
to assign a composition for the life of copyright before a single brief is a large ask at
the moment of least trust. Three stages instead:

1. **Roster entry.** Reel reviewed by Jon, disciplines recorded, credits captured, rate
   agreed. The agreement text is **sent to read, unsigned**, the moment they ask —
   `creator_routes` already serves it at the creator's own door.
2. **Signature, when a brief has their name against it**, with scope and fee already in
   writing, so the document and the job arrive together.
3. **Engagement acceptance**, separately, per job, as clauses 2 and 3A require.

**What signing does not mean:** work is not coming, it does not stop them working for
anyone else, and it does not touch their writer's share.

---

## 6. The first ten, as a method

One evening, ten slots, no individuals named. Each enters as a `talent` row with
`source_url` from where it was found; no public evidence, no row.

| # | Profile | Where | The search that finds them |
|---|---|---|---|
| 1 | Spot composer | Trade credit boxes on Southeast work — SHOOT, Little Black Book, Muse by Clio *(verify each publishes composer credits)* | The *music* credit on spots of the last 24 months; the house named there lists its composers |
| 2 | Spot composer | VI-Control | Members' work threads for `commercial`, `advertising`, `:30 spot`; keep those posting finished spots |
| 3 | Spot composer | Frost Media Scoring & Production | Email the department: *which alumni of the last ten years work in advertising music?* |
| 4 | Spot composer | Berklee Film and Media Scoring | Alumni directory *(verify access)*, filtered to advertising and the Southeast |
| 5 | Sonic identity writer | LinkedIn | `"sound logo" OR "sonic identity" OR mnemonic composer`, confirmed against one you can hear |
| 6 | Arranger / orchestrator | Recording Academy Florida Chapter; AFM Local 655 | Ask in person who charts and conducts locally. A conversation, not a search string |
| 7 | Mix / master engineer | SoundBetter | Mixing/mastering plus `broadcast`, `LUFS`; verify a credit off-site |
| 8 | Music editor / conform | Soundlister; LinkedIn | `"music editor" advertising`, `conform`, `cutdowns`, `versioning` |
| 9 | Sound designer | Airwiggles | Audio Challenge and Noisevember threads: dated, public, the work is the evidence |
| 10 | Second mixer, or a supervisor | Referral | Ask slots 1–9 once each: *who would you want mixing your cue?* |

Rule for the evening: **ten rows, each with a link, no emails sent that night.** Message
one goes out next morning, three a day.

---

## 7. How this changes the ninety days

The demand-side plan (`roadmap.md` §03) stays. Supply takes **four hours a week of the
twenty**, from build, not from selling — Ruling 5's test is that selling exceeds build.

**Where the sides depend on each other.** Demand leads: a composer's first honest question
is *what have you got.* **Supply gates delivery, not selling** — he can sell with no signed
roster but cannot deliver, because assignment is blocked without a signed agreement and a
rate. So the roster must be *reachable* by the time a proposal is countersigned. Reachable,
not signed.

| Week | Supply, ≈4h — it displaces build hours, never m01–m04 |
|---|---|
| **1** | Fix the two copy faults (30 min). Build the ten rows of §6 (2h). Read the agreement end to end as a composer would, writing down every question he can't answer (1h) |
| **2** | Message one to slots 1–5, three a day, same-day replies (2h). Join and read VI-Control, post nothing (1h). Email Frost the alumni question (30 min) |
| **3** | Message one to slots 6–10. Two calls with anyone who replied — the questions are his to ask (2h). Record disciplines, credits and rate on every warm row so `matchable` and `kind_for` resolve (1h) |
| **4** | One Recording Academy Florida or AFM Local 655 event, in person (3h). Second referral pass: one name from every warm row (30 min) |

**The ordering rule for the quarter:** *a name on the roster is cheap and a signature is
expensive — collect names now, signatures only when a brief has one against it.* By week
four: **six to eight approved rows, rates on file, zero signatures** — what the code wants,
and what he can say out loud without one sentence that is not yet true.

### Objection to the brief

None to the brief; one to the two shipped surfaces recorded at the top. That is the honesty
rule failing on the supply side, and it should be corrected before message one is sent.

---

*Verified 2026-09-10:* [VI-Control](https://vi-control.net/community/) ·
[SCL](https://thescl.com/join/) · [Airwiggles](https://www.airwiggles.com/) ·
[G.A.N.G.](https://www.audiogang.org/membership/) ·
[Soundlister](https://soundlister.com/audio-job/composer/) ·
[SoundBetter](https://soundbetter.com/about) ·
[Frost](https://mediascoring.frost.miami.edu/degrees/bm-in-media-scoring-and-production/index.html) ·
[Berklee](https://college.berklee.edu/film-scoring/careers) ·
[Recording Academy Florida](https://www.recordingacademy.com/membership/chapters/florida) ·
[AFM Local 655](https://www.afm655.org/about/). *Unconfirmed, marked (verify) above:* the
Reddit communities; VI-Control's jobs rules; whether Airwiggles permits a work post; which
SCL category fits a studio operator; non-alumnus access to Berklee's tools; Full Sail and
SCAD Atlanta programs; which trade outlets publish composer credits.
