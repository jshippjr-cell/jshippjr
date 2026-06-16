# Chordential — Opportunity Intelligence Agent (OIA)

Finds, scores, and ranks opportunities **Chordential** can win — across
government RFPs, agency and corporate procurement portals, creative-agency
partner networks, production-company vendor requests, event-production and
music-supervision requests, LinkedIn, industry newsletters, and marketing
tenders.

This first iteration is the **core scoring engine + a runnable demo**. It
runs end-to-end with no credentials using a built-in sample source, and
exposes a pluggable interface so live data connectors drop in later without
touching the scoring or reporting code.

## What it produces

For every opportunity it emits a scorecard:

```
Opportunity Score: 100/100
Tier: A-Tier — Pursue Immediately

Client: Meridian Beverage Co. (brand)
Need: Sonic Branding + Anthem for National Launch
Buyer: Brand
Budget: Estimated $15,000-$30,000
Decision Maker: Likely Brand / Marketing Lead
Reason For Fit:
  - Original music + commercial campaign + >$5k + agency/brand buyer
  - Commercial / video campaign work
  - Sonic branding mentioned
  - Miami / Southeast location (Miami, FL)
Win Probability: High
Risks:
  - No major risks flagged
Source: Campaign US Tier 2 (https://example.com/campaignus/meridian-launch)
```

…and a full report grouping everything into **A / B / C / Watch** tiers.

## The ranking engine

Each opportunity is scored 0–100 across seven weighted signals — Chordential's
commercial model (default), tuned to surface fast-turnaround branded/commercial
music work (sums to 100):

| Signal                              | Weight |
| ----------------------------------- | -----: |
| Commercial / video campaign         |     25 |
| Agency or production-company buyer  |     20 |
| Budget disclosed                    |     15 |
| Original music requested            |     15 |
| Sonic branding mentioned            |     10 |
| Video production included           |     10 |
| Miami / Southeast location          |      5 |

`score = Σ(weight × signal)`. Miami/Southeast is a **soft bonus** — out-of-region
work scores neutrally, never penalized. Signals a source leaves unset are
inferred from the opportunity text.

### A / B / C tiers (rule-based)

The **tier** is assigned by combination-rules (not a score threshold); the
score ranks opportunities *within* a tier:

- **A-Tier — Pursue Immediately:** original music **+** commercial campaign
  **+** budget > $5k **+** agency/brand buyer
- **B-Tier — Strong Lead:** production-company buyer with a likely music
  component, or a commercial agency/brand lead missing one A condition (e.g.
  undisclosed budget)
- **C-Tier — Government / Needs Teaming:** government media contract with music
  buried in a larger scope
- **Watch — Monitor Only:** matches none of the above

A secondary **Win Probability** label (High/Medium/Long-shot) is derived from
the raw score.

### Weight profiles

Weights are configurable — pass `--weights <file>` to retune without code:

- `config/weights.example.json` — the commercial model (default)
- `config/weights.win-probability.json` — the alternate fit/win-probability
  model (music-need, budget-fit, turnaround, competition, agency-size,
  relationship, geography)

## Install & run

```bash
pip install -e .

# Ranked report from the sample source
chordential-oia

# Show the per-criterion breakdown tables
chordential-oia --breakdown

# Hide long-shots and emit JSON for downstream tooling
chordential-oia --min-score 45 --json

# Run the qualification gate FIRST, then rank only what qualifies
chordential-oia --qualify
chordential-oia --qualify --qualify-weights config/qualification_weights.example.json

# Find real leads: parse a forwarded saved-search alert email
chordential-oia --email samples/mandy_alert.txt --qualify
chordential-oia --email path/to/intake-inbox/   --qualify   # a whole folder

# List available sources
chordential-oia --list-sources
```

## Email-alert intake (`--email`) — finding real leads

Demo sources return representative data. To evaluate **real** opportunities,
forward your saved-search alert emails (Mandy, ProductionHub, Hitmarker, …) to an
intake inbox and point the tool at them. The parser splits a multi-job digest into
one opportunity per posting, extracts client / budget / location / discipline, and
feeds them straight into qualify → rank:

```
forwarded alert email → parse → qualify (gate + align) → rank → your PURSUE board
```

It is provider-agnostic and heuristic — it reads labeled digests
(`Title:` / `Company:` / `Budget:` / `Location:`) and infers buyer type and music
requirement from the text. See `samples/` for example alerts and `intake.py`.

## Qualification layer (`--qualify`)

Scoring answers *"how attractive is this opportunity?"*. **Qualification** answers
the prior question — *"is this real, original, Chordential-shaped music craft at
all, and how well does it fit?"* — and can **hard-reject** junk the scorer would
otherwise rank (cover bands, karaoke, DJs, playlists, lessons, gear). It runs
*before* Rank:

```
Ingest → QUALIFY (gate → classify discipline → alignment %) → Rank → Estimate → Prepare
```

Each opportunity gets a `QualificationResult`: `qualified`, music `discipline`,
an `alignment_pct` (the "87% aligned" number), a one-line `fit_summary`, a
precision-biased `recommended_action` (Pursue / Review / Watch / Pass), a
`confidence`, and a `team_shape` hint handed to the estimator. Only high-alignment,
high-confidence work is `Pursue` (alertable); everything else stays queryable in
the DB (full recall). Rubric weights are editable config
(`config/qualification_weights.example.json`). See `docs/qualification-spec.md`.

No install needed for a quick look:

```bash
PYTHONPATH=src python -m chordential_oia.cli --breakdown
```

## Project layout

```
src/chordential_oia/
  models.py        # Opportunity, ScoredOpportunity, QualificationResult, enums
  scoring.py       # ScoringEngine, signal scorers, weights, tier rules
  qualification.py # QualificationEngine: gate, discipline, alignment rubric
  intake.py        # email-alert parser: forwarded alert -> opportunities
  formatting.py    # scorecard, qualification & ranked-report rendering
  cli.py           # command-line agent runner
  sources/
    base.py        # OpportunitySource interface (implement fetch())
    sample.py      # built-in mock opportunities (demo + test fixture)
    tiered.py      # the 10-source, 4-tier Chordential taxonomy
config/weights.example.json
config/weights.win-probability.json
config/qualification_weights.example.json
docs/             # market research, product spec
tests/
```

## Source taxonomy (4 tiers, 10 sources)

`chordential-oia --list-sources` shows them with tier + realistic access method:

| Tier | Sources | Typical output |
| ---- | ------- | -------------- |
| 1 — Gov / corporate RFP | RFPDB, SAM.gov, GovWin IQ | C-Tier |
| 2 — Agency intelligence | Agency Spotter, AdForum, Campaign US | A/B-Tier |
| 3 — Film/TV/production | ProductionHUB, Staff Me Up, Mandy Network | B-Tier |
| 4 — Gaming / interactive | Hitmarker | B-Tier |

Access reality (see `docs/market-research.md`): only **SAM.gov** has a clean
official API; **RFPDB / Campaign US** offer RSS; **Mandy / ProductionHUB /
Hitmarker** are ingested via **saved-search email alerts** (ToS-safe);
**GovWin IQ / Agency Spotter / AdForum / Staff Me Up** are paid/login-gated and
surfaced manually. All are currently mock stubs.

## Adding a live source

Implement one method:

```python
from chordential_oia.sources.base import OpportunitySource
from chordential_oia.models import Opportunity, MusicRequirement

class SamGovSource(OpportunitySource):
    key = "sam_gov"
    name = "SAM.gov Government RFPs"
    category = "government"

    def fetch(self, limit: int = 50) -> list[Opportunity]:
        # call the API, map each result onto Opportunity(...)
        ...
```

Register it in `sources/__init__.py`'s `AVAILABLE_SOURCES`, and it's
immediately scored, ranked, and reported alongside every other source.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Roadmap

This engine is the brain of the **Chordential Opportunity Hub** web app (see
`docs/` for the market research and product spec). Planned:

- Live connectors per the tier table: SAM.gov API, RFPDB/Campaign US RSS, and
  email-alert intake for Mandy / ProductionHUB / Hitmarker.
- LLM-assisted normalization to map messy free-text RFPs onto the scoring
  signals (commercial campaign, buyer type, budget, music requirement).
- Persistence + de-duplication across sources.
- Web app: FastAPI backend (this package as the engine), React/Next.js front
  end, Clerk auth (invite-only team), Supabase Realtime alerts, Resend email,
  and end-to-end project status tracking.
