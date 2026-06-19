# Launchpad Keywords & Channels — Council Deliberation

**Convened:** 2026-06-19 · **Chair:** Jon Shipp (CEO) · **Trigger:** Jon found a
real gig the launchpad should have surfaced — r/gameDevClassifieds, *"[PAID]
Looking for a Music Composer. Post-apocalyptic game,"* flair **PAID – Musician**.

**Mandate:** decide the keywords and channels to embed in the manual-assist
searches so "Open search" reliably lands on real PAID music/audio roles.

---

## What the example teaches us

**Competitive Intelligence Analyst:** Three signals in that one post: the **role**
("Music Composer"/"soundtrack"), the **intent** ("[PAID]", "Looking for"), and the
**channel** (r/gameDevClassifieds, which flairs posts "PAID – Musician"). A good
search has to hit all three axes at once.

**Demand-Gen Manager:** Precision matters more than recall here — a bare
`composer` search drowns in `[For Hire]` self-promo and unpaid "rev-share" asks.
We must **exclude** those explicitly. The buyer we want literally tags posts
"PAID."

**RFP Intelligence Director:** Don't over-fit to "composer." The same buyers post
"sound design," "game audio," "original music," "soundtrack," "music producer."
Cast the role net wide with an OR group; narrow with intent + exclusions.

**Estimation Director:** Adjacent game-audio communities carry the same demand —
**r/INAT** ("I Need A Team") and **r/gameaudio** are where studios post the same
PAID roles. Add them as channels.

**CTO:** Reddit blocks our bot, so this is launchpad-only. Bake the query into the
"Open search" URL (newest-first, restricted to the sub, last month) so one click
lands on fresh results in Jon's own session.

---

## Ratified keyword bank

**Role terms (OR):** composer · "music composer" · soundtrack · "original music" ·
score · "sound design" · "sound designer" · "game audio" · "music producer" ·
"music supervisor" · "sonic branding" · "additional music"

**Intent terms (OR):** hiring · paid · "looking for" · seeking · commission

**Exclusions (NOT):** "for hire" · "rev share" · revshare · unpaid · royalty ·
volunteer

**Sort/scope:** newest first, restricted to the subreddit, last month.

Embedded search shape:
`(role OR …) (intent OR …) -"for hire" -"rev share" -revshare -unpaid …`

## Ratified channels (manual-assist launchpad)

| Channel | Why |
|---|---|
| r/forhire | General `[Hiring]` composer/music gigs. |
| r/gameDevClassifieds | The example's home — flairs roles "PAID – Musician." |
| **r/INAT** *(new)* | "I Need A Team" — game projects posting PAID audio roles. |
| **r/gameaudio** *(new)* | Game-audio community; studios hiring composers/SD. |
| LinkedIn · X · TAXI · ProductionHub | Login/ToS-walled — open in your session. |

## Addendum (2026-06-19) — Reddit search is keyword-only

Field test killed the clever query: Reddit's search **does not support boolean**
— `(role OR …) (intent OR …) -exclusions` returned **zero** results on r/INAT.
Revised approach: offer a few **simple one-click searches per channel** (composer ·
music · "sound design" · "game audio" · soundtrack), each newest-first and
restricted to the sub. Each is a working query; the user clicks whichever fits and
skims. Precision comes from the human eye, not an over-clever string.

## Power tips (for later)

- **Flair search** on r/gameDevClassifieds: `flair:"PAID - Musician"` is the
  highest-precision filter — a candidate for a per-sub override.
- **X/Twitter:** `#composerwanted`, `#gameaudiojobs`, `#musicgig` + "hiring".
- Tune the bank as Jon flags hits/misses — it's one list in `discovery_sources.py`.
