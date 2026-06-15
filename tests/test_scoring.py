"""Tests for the scoring and ranking engine."""

from chordential_oia.models import (
    AgencySize,
    CompetitionLevel,
    MusicRequirement,
    Opportunity,
    Relationship,
    WinProbability,
)
from chordential_oia.scoring import DEFAULT_WEIGHTS, ScoringEngine


def _strong_opp() -> Opportunity:
    return Opportunity(
        client="Acme Marketing",
        need="Campaign Music Package",
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=5_000,
        budget_max=15_000,
        turnaround_days=14,
        location="USA",
        competition=CompetitionLevel.LOW,
        agency_size=AgencySize.MID,
        relationship=Relationship.PAST_CLIENT,
    )


def _weak_opp() -> Opportunity:
    return Opportunity(
        client="Meridian Global",
        need="Master Service Agreement",
        music_requirement=MusicRequirement.NONE,
        budget_min=2_000,
        budget_max=4_000,
        turnaround_days=90,
        location="Germany",
        remote_friendly=False,
        competition=CompetitionLevel.HIGH,
        agency_size=AgencySize.ENTERPRISE,
        relationship=Relationship.NONE,
    )


def test_default_weights_sum_to_100():
    assert sum(DEFAULT_WEIGHTS.values()) == 100


def test_strong_opportunity_scores_high():
    engine = ScoringEngine()
    scored = engine.score(_strong_opp())
    assert scored.score >= 70
    assert scored.win_probability == WinProbability.HIGH


def test_weak_opportunity_is_long_shot():
    engine = ScoringEngine()
    scored = engine.score(_weak_opp())
    assert scored.score < 45
    assert scored.win_probability == WinProbability.LONG_SHOT


def test_score_is_bounded_0_to_100():
    engine = ScoringEngine()
    for opp in (_strong_opp(), _weak_opp()):
        scored = engine.score(opp)
        assert 0.0 <= scored.score <= 100.0


def test_breakdown_points_sum_to_score():
    engine = ScoringEngine()
    scored = engine.score(_strong_opp())
    raw = sum(b.points for b in scored.breakdown)
    # Default weights sum to 100, so raw points already equal the 0-100 score.
    assert abs(raw - scored.score) < 0.1


def test_rank_orders_best_first():
    engine = ScoringEngine()
    ranked = engine.rank([_weak_opp(), _strong_opp()])
    assert ranked[0].client == "Acme Marketing"
    assert ranked[0].score >= ranked[1].score


def test_custom_weights_are_normalized():
    # Weights that don't sum to 100 should still yield a 0-100 score.
    engine = ScoringEngine(weights={"Music Needed": 1, "Budget Fit": 1})
    scored = engine.score(_strong_opp())
    assert 0.0 <= scored.score <= 100.0
    # Both criteria are maxed for the strong opp, so the score is ~100.
    assert scored.score > 95


def test_unknown_criterion_raises():
    try:
        ScoringEngine(weights={"Telepathy": 50})
    except ValueError as exc:
        assert "Telepathy" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown criterion")


def test_missing_budget_scores_neutral_not_crash():
    engine = ScoringEngine()
    opp = _strong_opp()
    opp.budget_min = None
    opp.budget_max = None
    scored = engine.score(opp)
    assert 0.0 <= scored.score <= 100.0
    assert opp.budget_display() == "Unknown"


def test_decision_maker_inference():
    engine = ScoringEngine()
    opp = Opportunity(client="X", need="Brand campaign commercial")
    scored = engine.score(opp)
    assert "Creative Director" in scored.decision_maker
