"""Tests for scorecard / report rendering and the source taxonomy."""

from chordential_oia.models import Tier
from chordential_oia.scoring import ScoringEngine
from chordential_oia.sources import AVAILABLE_SOURCES, TIERED_SOURCES
from chordential_oia.sources.sample import SampleSource
from chordential_oia.formatting import (
    render_breakdown,
    render_ranked_report,
    render_scorecard,
)


def test_sample_source_returns_opportunities():
    opps = SampleSource().fetch()
    assert len(opps) >= 3
    assert all(o.client and o.need for o in opps)


def test_all_ten_tiered_sources_registered_and_fetch():
    expected = {
        "rfpdb", "sam_gov", "govwin", "agency_spotter", "adforum",
        "campaign_us", "productionhub", "staffmeup", "mandy", "hitmarker",
    }
    assert expected <= set(AVAILABLE_SOURCES)
    assert expected == set(TIERED_SOURCES)
    for key in expected:
        src = AVAILABLE_SOURCES[key]()
        opps = src.fetch()
        assert opps and src.source_tier in (1, 2, 3, 4)
        assert all(o.source == src.name and o.source_tier == src.source_tier for o in opps)


def test_scorecard_contains_required_fields():
    engine = ScoringEngine()
    scored = engine.score(SampleSource().fetch()[0])
    card = render_scorecard(scored)
    for field in (
        "Opportunity Score:",
        "Tier:",
        "Client:",
        "Need:",
        "Buyer:",
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


def test_ranked_report_groups_by_tier():
    engine = ScoringEngine()
    # Pull from a spread of tiers across the taxonomy.
    opps = []
    for key in ("agency_spotter", "productionhub", "sam_gov"):
        opps.extend(AVAILABLE_SOURCES[key]().fetch())
    report = render_ranked_report(engine.rank(opps))
    assert "OPPORTUNITY INTELLIGENCE REPORT" in report
    assert "A-TIER" in report


def test_agency_spotter_is_a_tier():
    engine = ScoringEngine()
    top = engine.rank(AVAILABLE_SOURCES["agency_spotter"]().fetch())[0]
    assert top.tier is Tier.A


def test_government_sources_are_c_tier():
    engine = ScoringEngine()
    for key in ("sam_gov", "rfpdb"):
        scored = engine.rank(AVAILABLE_SOURCES[key]().fetch())[0]
        assert scored.tier is Tier.C
