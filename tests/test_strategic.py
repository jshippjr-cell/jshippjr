"""Tests for the CMO Strategic-Value lens."""

from chordential_oia.models import BuyerType, BuyerValue, MusicRequirement, Opportunity
from chordential_oia.strategic import assess_strategic_value


def _agency_small() -> Opportunity:
    # The CMO's headline case: $2k brief from a major agency.
    return Opportunity(
        client="Halcyon Creative (agency)",
        need="Original cue for a brand spot",
        buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=2_000, budget_max=2_000,
    )


def _gov_large() -> Opportunity:
    return Opportunity(
        client="City of Lakeshore",
        need="Municipal tourism video music",
        buyer_type=BuyerType.GOVERNMENT,
        music_requirement=MusicRequirement.LICENSED,
        budget_min=10_000, budget_max=10_000,
    )


def test_small_agency_beats_large_municipal_strategically():
    agency = assess_strategic_value(_agency_small())
    gov = assess_strategic_value(_gov_large())
    # The whole point of the lens: $2k agency outranks $10k municipal on strategy.
    assert agency.score > gov.score
    assert agency.tier == "Door-opener"
    assert gov.tier in ("Low", "Medium")


def test_small_strategic_sets_override_callout():
    sv = assess_strategic_value(_agency_small())
    assert sv.callout is not None
    assert "$2,000" in sv.callout
    assert "ranked above" in sv.callout.lower()


def test_large_municipal_has_no_callout():
    assert assess_strategic_value(_gov_large()).callout is None


def test_enterprise_repeat_maxes_relationship():
    opp = _agency_small()
    opp.buyer_value = BuyerValue.ENTERPRISE
    sv = assess_strategic_value(opp)
    assert sv.relationship_value == 1.0
    assert sv.score >= 95
    assert sv.inferred is False  # explicit buyer_value, not inferred


def test_explicit_buyer_value_overrides_inference():
    opp = _agency_small()
    opp.buyer_value = BuyerValue.ONE_TIME
    sv = assess_strategic_value(opp)
    assert sv.buyer_value is BuyerValue.ONE_TIME
    assert sv.inferred is False


def test_marquee_inferred_from_text_adds_bonus():
    opp = Opportunity(
        client="Brandco",
        need="National flagship campaign anthem",
        buyer_type=BuyerType.BRAND,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=3_000,
    )
    sv = assess_strategic_value(opp)
    assert sv.marquee is True
    assert sv.tier == "Door-opener"


def test_enterprise_keyword_inferred():
    opp = Opportunity(
        client="Two Rivers",
        need="Composer for an ongoing episodic branded series (retainer)",
        buyer_type=BuyerType.PRODUCTION_COMPANY,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=12_000, budget_max=18_000,
    )
    sv = assess_strategic_value(opp)
    assert sv.buyer_value is BuyerValue.ENTERPRISE
    assert sv.inferred is True


def test_educational_buyer_desirability():
    opp = Opportunity(
        client="State University",
        need="Original music for campus campaign",
        buyer_type=BuyerType.EDUCATIONAL,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=6_000,
    )
    sv = assess_strategic_value(opp)
    assert sv.buyer_desirability == 0.4


def test_score_bounded():
    for opp in (_agency_small(), _gov_large()):
        sv = assess_strategic_value(opp)
        assert 0.0 <= sv.score <= 100.0
