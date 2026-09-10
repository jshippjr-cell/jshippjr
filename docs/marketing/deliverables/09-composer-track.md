# The Composer Track — the supply side, deliverable

*Wave 4, 2026-09-10. Reads under `docs/marketing/00-brief.md`; the brief wins any
difference. Every term below is READ OUT of `composer_agreement.py`,
`service_agreement.py`, `compensation.py`, `agreements.py`, `talent.py`, `matching.py`,
`web/room.py`, `web/creator_routes.py`. Nothing is invented. Revenue is zero, no client
exists, no roster is signed (brief §13.8), and nothing here may tell a composer that work
is waiting.*

**Fix before this is used.** `recruiting.py` composes an invite saying *"real, paid briefs
(never spec)"* and `templates/public/for_artists.html` says *"We bring you scoped, paid
work"* — present tense, zero engagements sold. Both read as work in hand. The honest form
is conditional: *when a brief fits, you hear first, and it will be paid.* A copy fix on
two surfaces, not a build. The messages in §4 are written the corrected way.

---

## 1. What we are actually offering a composer today

Two standing agreements, and **`agreements.kind_for` decides which** — read from recorded
disciplines, never guessed. Composition, sonic branding or arrangement → **Composer
Agreement**. Mixing, sound design, supervision or licensing → **Service Agreement**. No
discipline recorded → the surface says so and offers *neither*.

### Composer Agreement v2.0 — people who author the music

- **Fee: 30% of net creative revenue**, rising to **40%** where the writer also
  orchestrates or produces the session (`COMPOSER_SHARE`, `COMPOSER_SHARE_WITH_SESSION`).
- **"Net"** = the creative fee the client pays, less money passing to *unconnected third
  parties on that job* — players and their pension/health, room and gear hire, session
  engineers, licences bought for that job alone. "Nothing else is deducted — not the
  studio's own time, overhead, software, insurance, commission, travel." Not a share of
  gross: *"booking an orchestra is not a fact about the writer's work."*
- **Licence income is shared too.** If the client later pays to extend term, widen
  territory, add media, take exclusivity or upgrade to a buyout, the writer gets **the
  same 30% of the net of that payment, for as long as the work earns** — and it does not
  stop when the agreement ends (cl. 3C).
- **A demo we request that loses is paid $400 flat** (`DEMO_FEE`).
- **Publishing:** the composition is assigned to Chordential Music for life of copyright,
  and **50% of the publisher's share belongs to the writers**, 50% to the studio
  (`PUBLISHER_SPLIT_TO_WRITERS = 0.50`).
- **What the writer keeps: their writer's share of public performance income**, paid
  direct by the PRO. *"It is not the studio's to take, and this agreement does not take
  it."*
- **No publishing entity yet?** The studio **holds** the writers' half for them, says so
  in writing, and files or pays it over **within 30 days** of them naming an entity. *"The
  studio does not keep it by default and does not keep it by silence."*
  (`compensation.unassigned_publishing` turns that into a chased task.)
- **Cue sheet:** *"The studio credits the writer as composer on the cue sheet it files,
  every time. That one is in the studio's hands, and it is a promise."* Filed within 30
  days of first broadcast, copy sent. A client's own credit list is a **promise to ask**,
  not a promise it happens — and the studio tells the writer if it is refused.
- **Payment:** client invoiced within **10 working days** of acceptance; writer paid
  within 30 days of the client settling and **in any event within 120 days of the client
  accepting delivery, whether or not the client has paid** (`PAYMENT_BACKSTOP_DAYS`). If
  the studio hasn't invoiced within 30 days, the writer is paid as though it had.
- **The estimate holds.** If the client pays more, the fee rises; it is never cut below
  the estimate without written agreement — *"a discount the studio chose to give is not a
  fact about the writer's work."*
- **If the job dies:** **50%** of the estimated fee before delivery, **100%** after; same
  if the studio replaces them for anything but failure to deliver.
- **Checkable:** every payment carries an itemised statement (fee invoiced, each deduction
  and who it went to, share applied, result), plus an **audit once in any 12 months** —
  the studio pays for it and the shortfall if the writer was underpaid by more than 5%.
- **Exclusivity: none over their time, ever** — *"this agreement claims no exclusivity
  over the writer's time and never will."* Only limits: the cue isn't re-licensed, and for
  **12 months from first broadcast** no knowingly similar cue for a competing brand in the
  same category.
- **Their reel:** after public release, the finished track and **up to 60 seconds** of the
  finished spot, and they may say they wrote it.
- **Their risk:** they warrant the work is human-made and clean; liability for one
  engagement is **capped at the greater of $25,000 and 3× the fees paid to them for it**,
  uncapped only where they knew it was untrue. Florida law, Miami-Dade courts (defaults).
  Independent contractor; W-9 or W-8BEN before first payment.

### Service Agreement v1.0 — craft on music somebody else wrote

Covers mixing and mastering; music editing (cutdowns, verticals, conforms, versioning);
sound design; music supervision and clearance research.

- **A fee, not a share** — computed from their own recorded rate (hourly, day, project),
  in writing before acceptance, rising with scope.
- **No publishing, said out loud** — plus one exception theirs to raise: original musical
  material must be declared *before delivering*, then settled as authorship under the
  Composer Agreement or not used. *"Raising this is never a breach and never a reason not
  to book someone again."*
- **They assign only what they make** — mixes, edits, conforms, stems, session files —
  and the document never purports to grant the underlying composition.
- **The chain is a clause:** a mix comes from the composer's approved stems; an edit from
  the mixer's approved master. Never a bounce off a review link.
- **Named targets, so nobody guesses:** 48 kHz / 24-bit WAV; US broadcast −24 LKFS ±2
  (ATSC A/85), TP −2 dBTP; European −23 LUFS ±1 (EBU R128), TP −1; streaming −14 LUFS
  integrated, TP −1; cinema as the engagement states, no default assumed.
- Same 5-working-day acceptance, 50% kill fee, 120-day backstop, $25,000 / 3× cap, Florida
  forum, and credit by role on the delivery documentation every time.

### What the room gives them that a normal gig does not

- **Notes arrive priced.** `room.priced_notes_only`: a client note reaches a creator only
  once a human has called it **conform** (free), **revision** (spends a round) or **out of
  scope** (quoted, never actioned for nothing). Out-of-scope notes stop at the studio.
- **Rounds are bounded** — one round buys one version, and a second change request while
  the studio still owes a version is refused server-side.
- **A new cut is parked** until the studio states the frame offset, so every note moves
  with the picture.
- **The client never has their name or email.** `room.CAPS` gives the client no
  `see_who`: they hire the studio and never learn a creator exists. The creator keeps
  `see_pending`, `upload_take`, `comment`, `download_source`, `ask_studio`, `capture`.
- **They never see the client's budget** (`recruiting.compose_project_assignment` states
  scope, deadline and their own rate, nothing more).
- **Signatures bind to text** — `signing.py` stores a SHA-256 of the exact words and
  reports **SUPERSEDED** the moment they change.

### What we are NOT offering — said first, in the agreement's own words

> *"This is a standing agreement, not a booking. It commits you to no work and guarantees
> you none. Each engagement is offered and accepted separately, with its own scope and
> fee, and this document sets the terms that apply when you accept one."*

Plainly: **no work today.** No retainer, no minimum, no volume. No exclusivity, now or
later. No spec — a demo we ask for is paid whether it wins or not. Nothing signed until it
means something (§5). No promise that a client credits them, only a promise to ask and to
say when the answer is no.

---

## 2. Who we are looking for

Counts are **before the first job**, and deliberately small — a roster larger than the
work is a roster of people we are disappointing. `talent.matchable` needs an approved reel
**and** a recorded discipline, so each count means *approved and described*.

| Profile (code discipline) | The work | Evidence that qualifies | Need |
|---|---|---|---|
| **Spot composer, to picture** (`COMPOSITION`) | :60/:30/:15 to a near-locked cut; hits, a button on the logo; stems and cutdowns from one session | 2+ released spots or brand films where they wrote the cue; a reel of music *against picture*, not tracks; works to timecode | **3** — never one; one composer is a single point of failure on a date tied to an air date |
| **Sonic identity writer** (`SONIC_BRANDING`) | A mnemonic that survives 10,000 plays, plus its family of variants | A sound logo you can hear in the wild, or a mnemonic system with variants | **1**, may be the same person |
| **Arranger / orchestrator** (`ARRANGEMENT`) | Charts, session prep, conducting; making a sampled mock-up sound played | Charts they wrote; a session prepped or conducted; a mock-up beside the live take | **1**. Also the 40% share, and the bridge to the room Jon wants |
| **Mix / master engineer** (`MIXING`) | Mix from the composer's approved stems, to the medium's loudness target, with measured integrated loudness and true peak stated | Talks about −24 LKFS / ATSC A/85 without looking it up; broadcast or streaming credits; a TV mix in their history | **1** |
| **Music editor / versioning** (`MIXING`, conform craft) | Cutdowns, verticals, conforms to a re-cut picture, alternates from the same session state | A job where the picture changed and the music followed; comfort with EDLs, fps, start timecode | **1**, usually the same person as the mixer |
| **Sound designer** (`SOUND_DESIGN`) | Designed elements under and around the cue | A design reel; can say which library elements are licensed and whether the licence permits stem delivery | **1** |
| **Supervisor / clearance researcher** (`SUPERVISION`) | Reads other people's paper; could help staff the Clearance Read | Clearance research done; a cue sheet filed; PRO registration fluency | **0–1**. Useful, not needed to deliver |

**Five to seven people, five to eight agreements.** Jon's stated gap — "none in the style
I'd hire" — is profile one, so that is where the evening in §6 goes.

---

## 3. Where they actually are

**The doctrine inverts here.** Client-side, a room is never used to reach a target.
Supply-side, composers gather in these rooms *to find work*, so a real opportunity is the
contribution rather than the intrusion.

**Where the line still is.** Only in rooms whose rules permit it, in the channel they
designate. **No money in public, ever** (brief §7) — a fee is one-to-one with a named
person. **Never post a brief that does not exist**: "building a roster, here are the
terms" is honest, "work is coming" is not. One post per room, then answer replies. And
reading other people's threads still comes first.

| Place | Who is there, and why it matters | How to approach — and what we contribute |
|---|---|---|
| **VI-Control** (vi-control.net), free | Media composers writing in mock-up — film, TV, trailer, game, ad. Founded 2004; reports ~114K unique visitors/month. The densest concentration of people who write to picture: profiles 1 and 3 | Read two weeks. Post only in the jobs section *(verify its name and rules)*. We bring plain answers on ad-side paper: what a cue sheet needs, what a grant of rights actually says |
| **Society of Composers & Lyricists** (thescl.com) | Film/TV/game/media composers. Confirmed: *"Music creators for commercials … are welcome to apply … case by case."* The credentialled end of profile 1, and a room that can judge our terms | Join as the studio side; attend before asking *(verify which category a studio operator fits)*. A studio that publishes its standing terms is unusual there |
| **Airwiggles** (airwiggles.com), free | Sound designers; launched Jan 2023, reports 8,000+ members; runs the Audio Challenge and Noisevember. Profile 6, with public dated work | Contribute to a challenge first. A craft room, not a job board — *(verify whether a work post is welcome at all)*. Useful replies only until the rules say otherwise |
| **Game Audio Network Guild** (audiogang.org) | The largest game-audio body. Game audio trains *interactive versioning* — the cousin of cutdowns and verticals: profiles 1, 5, 6 | Member events and webinars; the student competition names people early. We bring ad-side delivery literacy, which game audio rarely touches |
| **Soundlister** (soundlister.com), free | Composers, designers, supervisors, engineers. The one place a real opening can simply be posted | **Post only when an engagement exists** — an honest listing with named scope. Until then, read who is looking |
| **SoundBetter** (soundbetter.com) | Mixers, mastering engineers, producers, players; reports $80M+ paid out. Fastest route to profiles 4 and 5, with reviews and audio attached | Browse, reach out one to one. Never run a job through it — fee, paper and rights live in our agreements. A directory, not a room: we contribute nothing here |
| **Reddit** — r/composer, r/WeAreTheMusicMakers, r/audioengineering, r/GameAudio *(verify each: name, size, self-promo rules)* | Working and emerging composers and engineers; free, searchable, public reel threads | Every one has a hard self-promo rule; message the mods **before** posting. We bring straight answers on rights and cue sheets |
| **UM Frost — Media Scoring & Production**, Miami (mediascoring.frost.miami.edu) | Writers trained for media, plus the faculty who taught them. **Local** — able to come to a session later, which is the whole point of the room Jon wants | The department lists admission.music@miami.edu, 305-284-6168. **Ask faculty which alumni are working**, and be explicit that students are not who he is hiring. We offer a local operator who will explain how an ad job is papered — a guest lecture, not a pitch |
| **Berklee — Film and Media Scoring** (Career Manager / Connect); **Full Sail**, Winter Park FL; **SCAD Atlanta** sound design *(verify program names and alumni boards)* | The largest US pipeline of trained media composers, plus Southeast engineers and designers — profile 1 nationally, 4–6 within driving distance | Alumni tools *(verify whether a non-alumnus studio may post or must go via Career Services)*. Alumni, not students. We bring an opening, when one exists |
| **Recording Academy — Florida Chapter** (311 Lincoln Rd #301, Miami Beach; 305-672-4060) | The Florida/Puerto Rico recording community since 1995. Miami's actual working music room — not ad-dense, but where players, engineers and introductions are | Chapter events, repeatedly, before asking anyone for anything. We bring a local studio that pays and papers properly |
| **AFM Local 655 — South Florida Musicians Association** (afm655.org; Key West to Vero Beach) | Union players. **For session players later, not for signing composers now** — clause 6A forbids engaging anyone under a union agreement without the studio's prior written agreement, so any union session is a deliberate, papered decision | Introduce himself as a studio that intends to hire locally, and say plainly he has not run a union session and would need to learn the paper first. We bring honesty about what he does not yet know |

First month, in order: **Frost, VI-Control, SoundBetter** — two free and searchable today,
one local and tied to the room he wants to build.

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
> written by people, cleared under a certificate I sign, delivered with the stems, the
> cutdowns and the cue sheet in the box.
>
> Where it stands, straight: I have no client work today. I started this in November 2025
> and I'm selling the first engagement by hand. So I'm not offering you a job, and I'd
> rather say that in the first email than let you find out in the third.
>
> What I am doing is building a very small roster — a handful of people, {craft} among
> them — so that when a brief lands I'm calling someone whose work I already know instead
> of searching. If that's worth a reply, I'll send you the terms I'd work under, in full,
> before I ask you for anything.
>
> Either way, thanks for {piece}.
>
> Jon Shipp
> Chordential — Miami

**No fee in it, and what replaces it.** The brief forbids money in public, and the fee is
genuinely job-dependent — a share of net creative revenue on a job that does not exist. He
says instead: **"I'll send you the terms I'd work under, in full, before I ask you for
anything."** That is checkable: the document exists, it is complete, and it states the
share.

### Message two — they replied with interest

> {first},
>
> Glad you wrote back. Here's the whole thing so you can decide with the facts.
>
> **What I'd eventually ask you to sign** is one standing agreement. It is not a booking:
> in its own words, *it commits you to no work and guarantees you none.* Each job is
> offered and accepted separately, with its scope and fee in writing before you accept.
>
> **What it pays.** A share of the creative fee on each job — net of money that goes
> straight out to players, rooms and engineers, because an orchestra being booked isn't a
> fact about your writing. If I ask you for a demo and it doesn't win, that's paid too.
> The percentages are in the document, and I'll put a real number against a real brief; I
> do that on a call, and I don't discuss numbers in public at all.
>
> **What you keep.** Your writer's share of performance income — the PRO pays you direct
> and I never touch it. Half the publisher's share belongs to the writers. Your name goes
> on the cue sheet I file, every time, within 30 days of first broadcast, and I send you a
> copy. No publishing entity yet? I hold your half *for* you, tell you in writing I'm doing
> it, and hand it over within 30 days of you naming one. I don't keep it by silence.
>
> **What it doesn't ask for.** No exclusivity over your time, now or ever. Work for anyone.
> The only limits are that the cue itself isn't re-licensed and that for a year you don't
> knowingly write a near-identical cue for a competing brand.
>
> **What I do that a normal gig doesn't.** Client notes never reach you raw — I classify
> each one first as a conform, a revision or out of scope, and the out-of-scope ones stop
> at me. Rounds are counted, so a revision spiral has to get past a number. The client
> never gets your name or your email; they hire the studio. And you're paid within 120 days
> of the client accepting the work, whether or not the client has paid me.
>
> **What I won't say.** That work is coming. It isn't yet. I'll send you the full agreement
> to read whenever you want it, with no signature attached, and I won't ask you to sign
> anything until there's a brief with your name against it.
>
> Twenty minutes on a call if you'd like one — mostly me asking what you've been burned by,
> so I don't do it.
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
> **Where it honestly stands.** No paying client yet. I'm selling the first by hand. I am
> not hiring today and I won't pretend otherwise.
>
> **Why I'm doing it.** I have musical ideas most days and stopped finishing them years
> ago; I know what I am and what I'm not. What I'm good at is running things to a deadline
> in front of a room full of people, and I'd rather own the place where people who did
> commit their lives to this get paid properly than pretend to be one of them. The longer
> aim is a room — 2,500 to 3,000 square feet, built for chamber orchestra, where the
> composer conducts the session from wherever they are. The digital side exists to earn
> that room.
>
> **What I built while there's no client.** Two standing agreements in plain language,
> reviewed once by an entertainment lawyer whose findings I acted on. A share of the
> creative fee, not a flat buyout. Half the publisher's share to the writers. Your writer's
> share never touched. Your name on every cue sheet I file. Paid within 120 days of the
> client accepting, whether or not the client has paid me. Fifty percent if a job is killed
> before delivery, a hundred after. An audit right once a year. Sixty seconds of the
> finished spot for your reel once it's out.
>
> **What I won't do.** No AI-generated music anywhere, including as a demo — the agreement
> warrants it, and it's the one thing that would contradict everything else. No spec: a
> demo I ask for is paid whether it wins or not. No exclusivity over your time. No promise
> of volume.
>
> **What I'd like.** To know your work before I need it. Send me something you're proud of,
> and tell me what you've been burned by on ad jobs — that's the more useful half.
>
> Jon Shipp · Chordential · Miami

---

## 5. What they sign, and when

**A roster entry before any job** is a `talent` row: name, email, disciplines, credits,
location, reel URL, `review_status` (Pending → Approved / Declined), `invite_status`
(Prospect → Invited → Joined), source, rate and unit. `talent.matchable` is true only when
Jon has **approved the reel** and **one discipline is recorded**. `matching.match_talent`
then ranks approved creators against a brief — 60% discipline fit, 30% overlap between the
brief's words and their credits, 10% profile completeness — and **explains every score**.
It never assigns. Assignment is Jon's button.

**The agreement is standing, not a hire.** It sets the terms that apply *when* an
engagement is accepted. It conveys real things immediately — clauses 4 and 5 take effect
"on each work the moment it is created" — but only in respect of work done under it. It
binds neither side to any job, and either side can end it in writing at any time.

**Where the code puts the gate.** `db.talent_assignment_blockers` refuses assignment
unless `agreement_executed_at` is set **and** a rate above zero is on file. So a signature
must exist **before assignment** — which is *after* a real job exists. Nothing requires a
signature at roster time.

**So signing at first contact is the wrong shape, and the code agrees.** Asking a stranger
to assign a composition for the life of copyright before a single brief is a large ask at
the moment of least trust, and a drawer of unused signatures is a pile of promises going
stale. The right shape is three stages:

1. **Roster entry.** Reel reviewed by Jon personally, disciplines recorded, credits
   captured, rate agreed and stored. The agreement text is **sent to read, unsigned**, the
   moment they ask — `creator_routes` already serves it at the creator's own door.
2. **Signature, when a brief has their name against it** — sent with the scope and fee
   already in writing, so document and job arrive together. `agreements` picks the
   document, `signing.py` binds a SHA-256 to the exact text, the studio countersigns, and
   the digest reports **SUPERSEDED** if terms ever change.
3. **Engagement acceptance**, separately, per job — which is what clauses 2 and 3A require
   anyway.

**What signing does not mean**, in these words: work is not coming; it does not stop them
working for anyone else; it does not touch their writer's share; it does not bind them to
a job they have not accepted.

---

## 6. The first ten, as a method

One evening, ten slots, no individuals named. Each enters as a `talent` row with
`source_url` filled from where it was found; a name with no public evidence beside it does
not enter — ADR-0050's rule applied to supply.

| # | Profile | Where | The search that finds them |
|---|---|---|---|
| 1 | Spot composer | Trade credit boxes on Southeast work — SHOOT, Little Black Book, Muse by Clio *(verify each publishes composer credits)* | Read the *music* credit on Southeast spots from the last 24 months; the house named there lists the composer on its own site |
| 2 | Spot composer | VI-Control | Search members' own work threads for `commercial`, `advertising`, `:30 spot`; keep the ones posting finished spots, not library demos |
| 3 | Spot composer | Frost Media Scoring & Production | Email the department: *which alumni of the last ten years work in advertising music?* Then find their own sites |
| 4 | Spot composer | Berklee Film and Media Scoring | Alumni directory / Career Manager *(verify access)*, filtered to advertising and Miami / Atlanta / Nashville |
| 5 | Sonic identity writer | LinkedIn | `"sound logo" OR "sonic identity" OR mnemonic composer`, then confirm against a mnemonic you can actually hear |
| 6 | Arranger / orchestrator | Recording Academy Florida Chapter; AFM Local 655 | Ask in person who charts and conducts locally. A conversation, not a search string |
| 7 | Mix / master engineer | SoundBetter | Mixing/mastering filter plus `broadcast`, `commercial`, `LUFS`; read reviews, verify a broadcast credit off-site |
| 8 | Music editor / conform | Soundlister; LinkedIn | `"music editor" advertising`, `conform`, `cutdowns`, `versioning` — in a profile written by someone who has done it |
| 9 | Sound designer | Airwiggles | Audio Challenge and Noisevember threads: dated, public, and the work is the evidence |
| 10 | Second mixer, or a supervisor | Referral | Ask slots 1–9 once each at the end of a real conversation: *who would you want mixing your cue?* The highest-quality row in the table |

Rule for the evening: **ten rows, each with a link, no emails sent that night.** Message
one goes out next morning, three a day, so replies are answerable the same day.

---

## 7. How this changes the ninety days

The existing plan (`roadmap.md` §03, m01–m06) is entirely demand-side and stays. Supply
takes **four hours a week out of the twenty**, from build, not from selling — Ruling 5's
test is that selling exceeds build, and sourcing composers is neither marketing nor build.

**Where the sides depend on each other.**

- **Demand leads.** Nothing on the supply side needs finishing before the first discovery
  call. A brief is what makes a roster real, and a composer's first honest question is
  *what have you got.*
- **Supply gates delivery, not selling.** He can sell with no signed roster; he cannot
  **deliver** — `talent_assignment_blockers` refuses assignment without a signed agreement
  and a rate, and `/capabilities` lists no craft until a signed creator does it. So the
  roster must be *reachable* by the time a proposal is countersigned. Reachable, not
  signed.
- **The one shared blocker is already ruled.** Brief §13.5 replaced the machine-made demo
  audio with the founder's own recording. That recording is his, not a roster composer's —
  so "what does your work sound like" gets an honest answer today and a better one after
  engagement one.

**Weeks 1–4, in order, at twenty hours a week.**

| Week | Supply (≈4h) | Must not displace |
|---|---|---|
| **1** | Fix the two present-tense copy faults (`for_artists.html`, `recruiting.invite_blocks`) — 30 min. Build the ten rows of §6 in one evening — 2h. Read the agreement end to end as a composer would and write down every question he can't answer — 1h | m01's front door; the first five sequences |
| **2** | Message one to slots 1–5, three a day, same-day replies; send the one-page note to anyone who asks — 2h. Join and read VI-Control, post nothing — 1h. Email Frost the alumni question — 30 min | m03's posts; the next five sequences |
| **3** | Message one to slots 6–10. Two calls with anyone who replied — the questions are his to ask, not answer — 2h. Record disciplines, credits and rate on every warm row so `matchable` and `kind_for` both resolve — 1h | The Clearance Reads. A Read requested is worth more than a composer sourced |
| **4** | One Recording Academy Florida Chapter or AFM Local 655 event, in person — 3h, evening. Second referral pass: ask every warm row for one name — 30 min | m02's proof surfaces |

**The ordering rule for the quarter:** *a name on the roster is cheap and a signature is
expensive — collect names now, signatures only when a brief has one against it.* By week
four the target is **six to eight approved rows with rates on file and zero signatures**,
which is what the code wants and what he can say out loud without one sentence that is not
yet true.

### Objection to the brief

None to the brief. One to two shipped surfaces, recorded at the top: `for_artists.html`
and `recruiting.py` describe paid briefs in the present tense while none exist — the
honesty rule failing on the supply side the way §8 records it failing on the demand side.
Correct it before message one goes to anybody.

---

*Verified 2026-09-10:* [VI-Control](https://vi-control.net/portal/vi-control-a-community-of-composers-developers/) ·
[SCL](https://thescl.com/join/) · [Airwiggles](https://www.airwiggles.com/c/general/sound-design-challenge) ·
[G.A.N.G.](https://www.audiogang.org/membership/) · [Soundlister](https://soundlister.com/audio-job/composer/) ·
[SoundBetter](https://soundbetter.com/about) · [Frost Media Scoring & Production](https://mediascoring.frost.miami.edu/degrees/bm-in-media-scoring-and-production/index.html) ·
[Berklee Film and Media Scoring](https://college.berklee.edu/film-scoring/careers) and [Career Manager](https://www.berklee.edu/berklee-career-manager-alumni) ·
[Recording Academy Florida Chapter](https://www.recordingacademy.com/membership/chapters/florida) ·
[AFM Local 655](https://www.afm655.org/about/).
*Unconfirmed, marked (verify) above:* the Reddit communities and their self-promotion
rules; VI-Control's current jobs-section rules; whether Airwiggles permits a work post at
all; which SCL category a studio operator fits; non-alumnus access to Berklee's alumni
tools; Full Sail and SCAD Atlanta program names and alumni boards; which trade outlets
publish composer credit lines.
