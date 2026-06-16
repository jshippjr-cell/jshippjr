"""Tests for the Buyer Relationship Intelligence engine (the Buyer Graph)."""

from chordential_oia.web.buyer_intel import assess_relationship, days_since


def _rel(**kw):
    base = dict(opps=1, qualified=1, won=0, lost=0, open_pursuits=0,
                touches=0, last_contacted_days=None, strategic_tier=None)
    base.update(kw)
    return assess_relationship(**base)


def test_cold_when_no_outreach():
    r = _rel(touches=0)
    assert r.stage == "Cold"
    assert "first outreach" in r.next_best_action.lower() or "qualify" in r.next_best_action.lower()
    assert any("no outreach" in s.lower() for s in r.signals)


def test_warming_when_touched_but_stale():
    r = _rel(touches=2, last_contacted_days=40)
    assert r.stage == "Warming"
    assert "follow up" in r.next_best_action.lower()


def test_engaged_when_touched_recently():
    r = _rel(touches=3, last_contacted_days=5, open_pursuits=1)
    assert r.stage == "Engaged"
    assert r.score > _rel(touches=0).score


def test_client_when_won_before():
    r = _rel(won=1, touches=1, last_contacted_days=2)
    assert r.stage == "Client"
    # Won beats recency — a prior win is the strongest signal.
    assert r.score >= 80


def test_strategic_tier_and_momentum_raise_score():
    low = _rel(touches=1, last_contacted_days=3)
    high = _rel(touches=1, last_contacted_days=3, strategic_tier="Door-opener", open_pursuits=1)
    assert high.score > low.score
    assert any("Door-opener" in s for s in high.signals)


def test_score_is_bounded_and_deterministic():
    r1 = _rel(won=3, touches=99, last_contacted_days=0, strategic_tier="Door-opener", open_pursuits=5)
    r2 = _rel(won=3, touches=99, last_contacted_days=0, strategic_tier="Door-opener", open_pursuits=5)
    assert 0 <= r1.score <= 100
    assert r1.score == r2.score and r1.stage == r2.stage


def test_days_since_handles_missing_and_bad_input():
    assert days_since(None) is None
    assert days_since("") is None
    assert days_since("not-a-date") is None
    assert days_since("2020-01-01T00:00:00+00:00") > 0
