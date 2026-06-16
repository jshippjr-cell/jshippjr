"""Tests for the commercial scoring model and A/B/C/Watch tiering."""

from chordential_oia.models import (
    BuyerType,
    MusicRequirement,
    Opportunity,
    Tier,
)
from chordential_oia.scoring import (
    DEFAULT_WEIGHTS,
    WIN_PROBABILITY_WEIGHTS,
    ScoringEngine,
    classify_tier,
)


def _a_tier() -> Opportunity:
    # original + commercial + budget > $5k + agency buyer
    return Opportunity(
        client="Acme (agency)",
        need="Original Campaign Music",
        buyer_type=BuyerType.AGENCY,
        commercial_campaign=True,
        video_production=True,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=6_000,
        budget_max=12_000,
        location="Miami, FL",
    )


def test_default_and_alternate_weights_sum_to_100():
    assert sum(DEFAULT_WEIGHTS.values()) == 100
    assert sum(WIN_PROBABILITY_WEIGHTS.values()) == 100


def test_a_tier_rule():
    tier, _ = classify_tier(_a_tier())
    assert tier is Tier.A


def test_b_tier_production_company():
    opp = Opportunity(
        client="Two Rivers",
        need="Composer for branded series",
        buyer_type=BuyerType.PRODUCTION_COMPANY,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=10_000,
        budget_max=18_000,
    )
    assert classify_tier(opp)[0] is Tier.B


def test_b_tier_agency_without_budget():
    # Agency + commercial + music likely but budget undisclosed -> B, not A.
    opp = _a_tier()
    opp.budget_min = None
    opp.budget_max = None
    assert classify_tier(opp)[0] is Tier.B


def test_c_tier_government_buried_music():
    opp = Opportunity(
        client="Federal Agency",
        need="PSA video production",
        buyer_type=BuyerType.GOVERNMENT,
        commercial_campaign=False,
        video_production=True,
        music_requirement=MusicRequirement.IMPLIED,
    )
    assert classify_tier(opp)[0] is Tier.C


def test_watch_when_no_music():
    opp = Opportunity(
        client="Pixel (agency)",
        need="Social video editing retainer",
        buyer_type=BuyerType.AGENCY,
        commercial_campaign=True,
        music_requirement=MusicRequirement.NONE,
    )
    assert classify_tier(opp)[0] is Tier.WATCH


def test_a_tier_scores_higher_than_watch():
    engine = ScoringEngine()
    a = engine.score(_a_tier())
    watch = engine.score(
        Opportunity(client="X", need="No music here", buyer_type=BuyerType.UNKNOWN,
                    commercial_campaign=False, music_requirement=MusicRequirement.NONE)
    )
    assert a.score > watch.score
    assert a.tier is Tier.A and watch.tier is Tier.WATCH


def test_score_bounded_and_disclosed_budget_signal():
    engine = ScoringEngine()
    s = engine.score(_a_tier())
    assert 0.0 <= s.score <= 100.0
    budget_sig = next(b for b in s.breakdown if b.name == "Budget Disclosed")
    assert budget_sig.normalized == 1.0


def test_miami_is_soft_bonus_not_penalty():
    engine = ScoringEngine()
    miami = _a_tier()
    elsewhere = _a_tier()
    elsewhere.location = "Seattle, WA"
    geo_miami = next(b for b in engine.score(miami).breakdown if b.name == "Miami/Southeast")
    geo_else = next(b for b in engine.score(elsewhere).breakdown if b.name == "Miami/Southeast")
    assert geo_miami.normalized == 1.0
    assert geo_else.normalized == 0.5  # neutral, not zero -> no penalty


def test_rank_orders_by_tier_then_score():
    engine = ScoringEngine()
    gov = Opportunity(client="Gov", need="PSA video", buyer_type=BuyerType.GOVERNMENT,
                      commercial_campaign=False, video_production=True,
                      music_requirement=MusicRequirement.IMPLIED)
    ranked = engine.rank([gov, _a_tier()])
    assert ranked[0].tier is Tier.A
    assert ranked[-1].tier is Tier.C


def test_alternate_profile_still_works():
    engine = ScoringEngine(weights=WIN_PROBABILITY_WEIGHTS)
    s = engine.score(_a_tier())
    assert 0.0 <= s.score <= 100.0


def test_unknown_criterion_raises():
    try:
        ScoringEngine(weights={"Telepathy": 50})
    except ValueError as exc:
        assert "Telepathy" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown criterion")


def test_text_inference_for_unset_signals():
    # No explicit commercial flag, but text reads commercial.
    opp = Opportunity(
        client="Agency",
        need="Brand campaign advert with sonic logo and video spot",
        buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=7_000,
        budget_max=10_000,
    )
    s = ScoringEngine().score(opp)
    sonic = next(b for b in s.breakdown if b.name == "Sonic Branding")
    assert sonic.normalized == 1.0  # inferred from "sonic logo"
    assert s.tier is Tier.A
