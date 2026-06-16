"""Tests for scorecard / report rendering and the sample source."""

from chordential_oia.formatting import (
    render_breakdown,
    render_ranked_report,
    render_scorecard,
)
from chordential_oia.scoring import ScoringEngine
from chordential_oia.sources import AVAILABLE_SOURCES
from chordential_oia.sources.sample import SampleSource


def test_sample_source_returns_opportunities():
    opps = SampleSource().fetch()
    assert len(opps) >= 5
    assert all(o.client and o.need for o in opps)


def test_strategic_roadmap_sources_registered():
    # Roadmaps A/B/C must each be discoverable and yield valid opportunities.
    for key in ("agency_campaign", "indie_game", "creator_streamer"):
        assert key in AVAILABLE_SOURCES
        opps = AVAILABLE_SOURCES[key]().fetch()
        assert opps and all(o.client and o.need for o in opps)


def test_agency_campaign_lead_scores_well():
    # The beachhead lead type should rank as a real opportunity, not a dud.
    engine = ScoringEngine()
    opps = AVAILABLE_SOURCES["agency_campaign"]().fetch()
    top = engine.rank(opps)[0]
    assert top.score >= 60


def test_scorecard_contains_required_fields():
    engine = ScoringEngine()
    scored = engine.score(SampleSource().fetch()[0])
    card = render_scorecard(scored)
    for field in (
        "Opportunity Score:",
        "Client:",
        "Need:",
        "Budget:",
        "Decision Maker:",
        "Reason For Fit:",
        "Win Probability:",
        "Risks:",
    ):
        assert field in card


def test_breakdown_includes_total():
    engine = ScoringEngine()
    scored = engine.score(SampleSource().fetch()[0])
    table = render_breakdown(scored)
    assert "Total" in table
    assert "Criterion" in table


def test_ranked_report_groups_by_band():
    engine = ScoringEngine()
    ranked = engine.rank(SampleSource().fetch())
    report = render_ranked_report(ranked)
    assert "OPPORTUNITY INTELLIGENCE REPORT" in report
    assert "HIGHEST PROBABILITY" in report
