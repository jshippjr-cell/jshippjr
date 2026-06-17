# Discovery Sources — Executive Council Deliberation

**Convened:** 2026-06-17 · **Chair:** Jon Shipp (CEO) · **Mandate:** decide where the
human-gated crawler should comb for music opportunities (and talent), replacing the
rejected broad Google/Bing sweep with curated, industry-expert-vetted venues.

Governing rule unchanged: **the machine proposes, Jon disposes.** This memo decides
the *starting set* of sites and the *suggested* set that awaits Jon's per-site
approval before the crawler may touch them.

---

## Why not broad search

**RFP Intelligence Director:** A generic `google.com/search?q=music RFP` is noise.
The buyers we want — producers, directors, creative/production managers, agency
producers, game audio leads — don't post to "the open web," they post to a known
short list of trade boards and communities. Combing those *is* the edge; combing
Google is what a commodity scraper does (the exact drift `company-strategy.md`
rejects). Precision over recall, on the supply discovery side too.

**Competitive Intelligence Analyst:** Agreed. ~95% of A-tier briefs surface in a
handful of production job boards and composer communities. We name them, we own
them, we monitor them. Everything else is a *suggestion* Jon vets.

**COO:** Every source gets an owner + SLA + health check or it rots. Cap the active
set; promote a suggested site only when we can support it.

**CTO:** Respect each site's ToS and robots; some (TAXI, LinkedIn) gate content
behind login — we point at public listing pages only and fail soft. Per-site
parsers plug in by `source_key`; the generic parser is the floor.

---

## Ratified STARTER set (Established — active on launch)

Where producers/directors/creative PMs post the work (demand), plus the core
composer communities that carry both gig posts and talent (supply):

| Site | Why (industry rationale) | Champion |
|---|---|---|
| **ProductionHub** | Film/video production job board; producers post crew + music calls. | RFP Intelligence Director |
| **Mandy.com** | Long-standing film/TV/commercial crew + jobs board. | RFP Intelligence Director |
| **Stage 32** | Film-industry network with an active jobs board; directors/producers hire here. | Competitive Intelligence Analyst |
| **TAXI (A&R)** | Independent A&R — music licensing/placement opportunities (libraries, film, ad). | Competitive Intelligence Analyst |
| **VI-Control · Job Offerings** | The composer community; the "Job Offerings / For Hire" subforum is dense with real gigs. | RFP Intelligence Director |
| **Soundlister** | Film/TV music industry jobs (composer assistants, supervisors, additional music). | RFP Intelligence Director |
| **Film Music Network** | Music-for-media job listings, US + international. | Competitive Intelligence Analyst |
| **Reddit · r/forhire** | "[Hiring] composer/music" posts from indie producers/devs. | Demand-Gen Manager |
| **Reddit · r/gameDevClassifieds** | Game studios hiring composers/sound designers. | Demand-Gen Manager |
| **Gearspace · Employment** | Pro-audio community employment board; mix/score/sound work. | RFP Intelligence Director |
| **SoundBetter** *(talent)* | Marketplace of vetted music creators — supply-side discovery. | Estimation Director |
| **AirGigs** *(talent)* | Online session/music services marketplace — supply-side discovery. | Estimation Director |

## SUGGESTED set (await Jon's per-site approval before any scan)

Plausibly valuable, but unproven / ToS-sensitive / higher-noise. The crawler
**presents these and does nothing** until Jon approves each one:

| Site | Why it might help | Caveat |
|---|---|---|
| **LinkedIn (niche music-jobs query)** | Agencies/brands post composer/sound roles. | Login-gated; narrow query only, not broad search. |
| **X/Twitter · #composerwanted / #gameaudiojobs** | Real-time indie gig calls. | High noise; needs a tight query. |
| **Behance (Sound/Music field)** | Portfolio discovery of sound/music creators. | Talent-side; portfolio not gig. |
| **Craigslist · creative gigs** | Local/indie music gigs. | Noisy, spam-prone; per-market. |
| **Discord composer/game-audio communities** | Active gig channels. | No clean public listing URL; manual entry. |

**Standing instruction to the council:** as new venues surface, add them to the
SUGGESTED set with a one-line rationale and a champion — never straight to active.
Jon approves promotion to the starter set.
