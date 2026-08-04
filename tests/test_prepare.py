"""Tests for the Prepare layer (pursuit brief generator)."""

from chordential_oia.estimation import EstimationEngine
from chordential_oia.models import BuyerType, MusicDiscipline, MusicRequirement, Opportunity
from chordential_oia.prepare import PursuitBrief, build_pursuit_brief
from chordential_oia.qualification import QualificationEngine
from chordential_oia.scoring import ScoringEngine
from chordential_oia.strategic import assess_strategic_value


def _brief_for(opp: Opportunity) -> PursuitBrief:
    qual = QualificationEngine().qualify(opp)
    scored = ScoringEngine().score(opp)
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = EstimationEngine().estimate(opp, qual.team_shape, discipline)
    strat = assess_strategic_value(opp)
    return build_pursuit_brief(opp, qual, scored, est, strat)


def _agency() -> Opportunity:
    return Opportunity(
        client="Acme (agency)",
        need="Original :30 national campaign spot",
        description="National brand campaign; original music, cutdowns, fast.",
        buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=6_000, budget_max=12_000,
    )


def test_brief_assembles_from_engines():
    b = _brief_for(_agency())
    assert b.client == "Acme (agency)"
    assert "Pursue" in b.recommendation
    assert b.team  # composer etc.
    assert "$" in b.budget_line
    assert b.checklist
    assert b.why_fit and b.why_fit != ["—"]


def test_render_text_is_copyable_and_complete():
    """ADR-0034: one action list. ``render_text`` used to print `response_outline` +
    `next_steps` while the HTML page printed `checklist` — the same brief giving two
    different instruction sets depending on how it was opened."""
    brief = _brief_for(_agency())
    text = brief.render_text()
    for marker in ("PURSUIT BRIEF", "Recommendation:", "Why it fits:",
                   "Pursuit checklist:", "Budget:"):
        assert marker in text
    for step in brief.checklist:
        assert step in text


def test_discipline_hint_appears_for_sonic_branding():
    opp = Opportunity(
        client="Brandco",
        need="Sonic logo and audio identity for launch",
        buyer_type=BuyerType.BRAND,
        sonic_branding=True,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=20_000, budget_max=30_000,
    )
    b = _brief_for(opp)
    assert any("mnemonic" in line.lower() for line in b.checklist)


def test_strategic_callout_used_as_angle_when_present():
    # Small budget + agency -> strategic door-opener callout should drive the angle.
    opp = Opportunity(
        client="Major Agency",
        need="Original cue for a brand spot",
        buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=2_000, budget_max=2_000,
    )
    b = _brief_for(opp)
    assert "ranked above" in b.strategic_angle.lower() or "door" in b.strategic_angle.lower()


def test_brief_handles_disqualified_opportunity():
    opp = Opportunity(client="Joe", need="Wedding cover band for reception")
    b = _brief_for(opp)
    assert b.qualified is False
    # Should still render without crashing.
    assert "PURSUIT BRIEF" in b.render_text()
