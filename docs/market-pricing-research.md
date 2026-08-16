# What the competition charges — August 2026

Gathered to answer a live question: *"I have no idea how I am pricing the product."* The
answer to that was `capabilities.quote_band`, which quoted the client's own stated budget.
This document is the outside evidence that the replacement (`pricing.py`) is calibrated
against something real rather than against itself.

**Read this before changing a factor in `pricing.py`.** The tables there are priors; these
are the observations they are meant to answer to.

---

## 1. The closest comparator: a music house with a published rate card

**Swell Music + Sound** publishes prices, which almost nobody in this market does. This is
the number a buyer will already have in their head when they talk to us.

| Package | What it includes | Price |
|---|---|---|
| Custom library track | One original track from their catalogue, full stems, unlimited use | **$5,000** |
| Original score — 1 demo | One direction, up to 5 revision rounds, full stems | **$10,000** |
| Original score — 5 demos | Five directions, 5 revision rounds on the selected one, stems | **$15,000** |
| Original score — 8 demos | Eight directions, 5 revision rounds, stems | **$18,000** |
| Hourly | Studio/engineering outside a package | **$375/hr** |

Every package bundles full stems so the client can make their own cutdowns without coming
back. Ownership is deal-by-deal: *"depending on the deal structure, you may own the master
and publishing outright."*

**Where this puts us.** Chordential's creative fee for the Larkspur three-minute film comes
out at **$10,300** — within rounding of Swell's entry package. The cost model is not out of
line with the market, which is worth knowing, because the per-minute freelance figures in
§3 suggest it is until you notice they price a different thing.

**Where it puts us at risk.** Swell quotes **one number**, licence included. We quote a
creative fee *plus* a licence fee. A buyer comparing like for like sees $10,000 against our
$14,000–$28,500 and needs to be told why. That is a positioning problem, not a pricing
error — but it is the objection to have an answer ready for, and it is the reason the
itemised derivation on the proposal matters more than it looks.

## 2. Bespoke advertising music, by campaign shape

**Synchro Music (UK)** — the clearest public statement of the range:

| Shape | Price (GBP) | ≈ USD |
|---|---|---|
| Simple, digital-only piece | £3,000 | ~$3,800 |
| Mid-scale commission (most work) | £8,000–15,000 | ~$10,000–19,000 |
| Flagship TV campaign, full buyout | £30,000+ | ~$38,000+ |

A **10× spread** between the cheapest and dearest bespoke jobs, driven by usage scope,
musical complexity, rights model and timeline — exactly the four levers `pricing.py` prices.

Broader industry guides put custom composition for a **:30 spot at $2,000–25,000**, and note
that full-service agencies add **15–25%** in overhead on top of any production budget.

## 3. Per-minute rates — and why they are the wrong comparator

| Tier | Rate per finished minute |
|---|---|
| Independent / student | £100–500 |
| Mid-level professional (commercials, short films) | £500–1,500 |
| Top-tier (live orchestra, advanced sound design) | £1,500–5,000+ |

Another source puts a working professional at "at least $200/minute" and indie budgets at
$80–100/minute, with a 3-minute piece at $800–2,500.

**These describe a freelance composer, not a music house.** They price one person's writing
time. They do not price a producer, a mixer, a session, clearance, cue sheets, stems,
delivery, or the guarantee that any of it arrives. Comparing our fee to them is comparing a
studio to a session player — and it is the comparison a price-shopping buyer will make, so
the answer needs to be ready: *what we sell is the delivery and the clearance, and the
music is the part you can also buy cheaper somewhere else.*

Also worth stealing: **most composers include one or two revision rounds**; Swell includes
**five**. We currently promise two. That is a real competitive gap and it is cheap to close.

## 4. Licence multipliers — the part we were getting wrong

From the 2026 sync rate cards. Their baseline is *1-year, North America, background,
non-exclusive*:

| Lever | Market |
|---|---|
| 1 year, North America | 1.0× (baseline) |
| 3 years, worldwide | **+80%** (≈1.8×) |
| Perpetual, worldwide, all media | **2.5×** |
| Non-exclusive | 1.0× |
| **Limited / category exclusivity** | **+50%** |
| **Full exclusivity** | **+150% or more** (a second source: 2×–5×) |
| Featured rather than background placement | +50% |
| Needle drop under 30s | 0.5× |
| Needle drop over 60s | +30% |

Territory expansion beyond the initial quote *"can double the total"*, and campaign
licences typically run **6–12 months** before renegotiation — which makes the prep sheet's
renewal question (added last week) a directly monetised one.

### What this changed in `pricing.py`

| Factor | Was | Now | Evidence |
|---|---|---|---|
| Category exclusivity | 1.40 | **1.50** | Market: limited exclusivity +50% |
| Full exclusivity | 1.85 | **2.50** | Market: +150% or more; second source 2×–5× |

Exclusivity was the clearest miss, and it is the term clients most often assume is free —
which the prep sheet already warned about (*"Exclusivity is a real cost to us and clients
often assume it is free"*) without pricing it.

### And what it exposed: compounding

Four factors multiplied compound faster than the market moves. Normalised to a common
baseline, our tables reached **7.6×** for "perpetual, worldwide, all media" where the
market pays **2.5×**. Each factor is individually defensible; their product is not, because
a buyer refusing to pay is a fact no rate card overrides.

Rather than quietly shave the factors — which would have destroyed the evidence for each
one — there is now a documented ceiling, `LICENCE_FACTOR_CAP = 4.0`. It sits above the
market's top because bespoke work is not catalogue sync: a buyout here transfers an asset
that did not previously exist. `LicenceTerms.capped` reports when a deal hits it, because
being at the ceiling is a negotiating position rather than an arithmetic result.

## 5. What is still unanswered

- **No public data on procurement-grade clearance as a premium.** The Constitution's central
  claim — that clearance certification is what the market pays extra for — is not something
  any of these sources price. It may be real and unpriced by competitors, which would be the
  moat; it may be assumed rather than bought. Worth testing on a live deal by quoting it as
  a line and seeing whether anyone strikes it.
- **Nothing here is calibrated on Chordential actuals**, because there are none yet. Every
  figure in `pricing.py` remains a prior. The first three closed deals are worth more than
  this entire document.
- **Agency vs direct-to-brand.** Agencies add 15–25% overhead, which implies a brand paying
  us directly should expect to pay less than the agency-mediated number they may be
  benchmarking against — or that there is room to price at the agency-inclusive level when
  we *are* the agency-replacement. Untested.

---

## Sources

- [Swell Music + Sound — Custom Music for Advertising & Branded Content](https://swellmusicsound.com/learn-more/custom-music-for-advertising-branded-content/) (published rate card)
- [Synchro Music — Music Composition for Advertising](https://synchromusic.uk/music-composition-for-advertising/)
- [Chartlex — Sync Licensing Rate Card 2026](https://www.chartlex.com/blog/business/sync-licensing-rate-card-2026)
- [Nick Pike Music — How Much Does a Custom Music Score Cost?](https://www.nickpikemusic.com/post/how-much-does-a-custom-music-score-cost-a-complete-pricing-guide)
- [Foxi — How Much Does It Cost To License Music For A Commercial 2026](https://www.foximusic.com/blog/how-much-does-it-cost-to-license-music-for-a-commercial/)
- [Twine — Cost to Commission an Original Music Composition](https://www.twine.net/blog/cost-to-commission-an-original-music-composition/)
- [Green Frog Labs — 30 Second Commercial Cost (2026)](https://greenfroglabs.com/blog/30-second-commercial-cost)
