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
Opportunity Score: 87/100

Client: Acme Marketing
Need: Campaign Music Package
Budget: Estimated $5,000-$15,000
Decision Maker: Likely Producer / Creative Director
Reason For Fit:
  - Requires original music
  - Budget ~$10,000 sits in the sweet spot
  - 14-day turnaround fits Chordential's fast process
Win Probability: High
Risks:
  - No major risks flagged
Source: Creative Agency Partner Network (https://example.com/opps/acme-campaign)
```

…and a full report grouping everything into **Highest / Medium / Long-shot**
bands.

## The ranking engine

Each opportunity is scored 0–100 across seven weighted criteria (the
defaults match Chordential's spec and sum to 100):

| Criterion             | Weight |
| --------------------- | -----: |
| Music Needed          |     25 |
| Budget Fit            |     20 |
| Turnaround Fit        |     15 |
| Competition           |     15 |
| Agency Size           |     10 |
| Existing Relationship |     10 |
| Geography             |      5 |

Each criterion's scorer turns the opportunity's facts into a normalized
0–100% signal; `score = Σ(weight × signal)`. The score maps to a win band:

- **High** ≥ 70
- **Medium** 45–69
- **Long-shot** < 45

Weights are configurable — pass `--weights config/weights.example.json` (or
your own copy) to retune the model without code changes.

## Install & run

```bash
pip install -e .

# Ranked report from the sample source
chordential-oia

# Show the per-criterion breakdown tables
chordential-oia --breakdown

# Hide long-shots and emit JSON for downstream tooling
chordential-oia --min-score 45 --json

# List available sources
chordential-oia --list-sources
```

No install needed for a quick look:

```bash
PYTHONPATH=src python -m chordential_oia.cli --breakdown
```

## Project layout

```
src/chordential_oia/
  models.py        # Opportunity, ScoredOpportunity, enums
  scoring.py       # ScoringEngine + per-criterion scorers + weights
  formatting.py    # scorecard & ranked-report rendering
  cli.py           # command-line agent runner
  sources/
    base.py        # OpportunitySource interface (implement fetch())
    sample.py      # built-in mock opportunities (demo + test fixture)
config/weights.example.json
tests/
```

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

- Live connectors: SAM.gov / government RFP feeds, agency & corporate
  procurement portals, newsletter (RSS/email) parsers, LinkedIn search.
- LLM-assisted normalization to map messy free-text briefs onto the scoring
  signals (music requirement, budget, turnaround, competition).
- De-duplication across sources and persistence so opportunities can be
  tracked over time.
- Notifications (digest of new High-probability opportunities).
```
