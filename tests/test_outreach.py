"""Tests for the Outreach-to-Win layer (deterministic outreach plan generator)."""

from chordential_oia.estimation import EstimationEngine
from chordential_oia.models import BuyerType, MusicDiscipline, MusicRequirement, Opportunity
from chordential_oia.outreach import OutreachPlan, build_outreach_plan
from chordential_oia.qualification import QualificationEngine
from chordential_oia.scoring import ScoringEngine
from chordential_oia.strategic import assess_strategic_value


def _plan_for(opp: Opportunity) -> OutreachPlan:
    qual = QualificationEngine().qualify(opp)
    scored = ScoringEngine().score(opp)
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = EstimationEngine().estimate(opp, qual.team_shape, discipline)
    strat = assess_strategic_value(opp)
    return build_outreach_plan(opp, qual, scored, est, strat)


def _agency() -> Opportunity:
    return Opportunity(
        client="Acme (agency)",
        need="Original :30 national campaign spot",
        description="National brand campaign; original music, cutdowns, fast.",
        buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=6_000, budget_max=12_000,
    )


def test_plan_assembles_from_engines():
    p = _plan_for(_agency())
    assert p.target_contact  # inferred decision-maker
    assert p.steps and len(p.steps) >= 3
    # Steps are numbered sequentially starting at 1.
    assert [s.order for s in p.steps] == list(range(1, len(p.steps) + 1))
    # The first-touch message is the template-style proposal, adapted to the lead.
    assert "Acme (agency)" in p.first_touch_message
    assert "Chordential is built for" in p.first_touch_message
    # The concise email offers a call to walk through the examples (call-offer excerpt).
    assert "walk you through the examples" in p.first_touch_message
    # Examples are recommended to attach (the "audio examples").
    assert p.recommended_examples


def test_message_greeting_adapts_to_contact_name():
    qual = QualificationEngine().qualify(_agency())
    scored = ScoringEngine().score(_agency())
    est = EstimationEngine().estimate(_agency(), qual.team_shape, qual.discipline)
    strat = assess_strategic_value(_agency())
    named = build_outreach_plan(_agency(), qual, scored, est, strat, contact_name="Dana Reyes")
    anon = build_outreach_plan(_agency(), qual, scored, est, strat)
    assert named.first_touch_message.startswith("Hi Dana Reyes,")
    assert anon.first_touch_message.startswith("Hi there,")


def test_sonic_branding_recommends_matching_examples():
    opp = Opportunity(
        client="Beverage Co (brand)",
        need="Sonic logo + brand anthem + campaign cutdowns",
        description="Sonic branding: mnemonic sound logo, brand anthem, adaptations.",
        buyer_type=BuyerType.BRAND,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=15_000, budget_max=30_000,
    )
    p = _plan_for(opp)
    if p.qualified and "Sonic" in p.recommended_examples[0]:
        assert "Sonic logo example" in p.recommended_examples
        assert "Brand anthem example" in p.recommended_examples


def test_plan_supplies_an_email_subject():
    p = _plan_for(_agency())
    # A concrete subject line backs the one-click mailto draft.
    assert p.email_subject
    assert _agency().need in p.email_subject


def test_plan_builds_linkedin_research_link():
    p = _plan_for(_agency())
    # Deterministic lead enrichment: a LinkedIn people-search deep-link built
    # from the inferred decision-maker + buyer (parenthetical suffix stripped).
    assert "linkedin.com/search/results/people" in p.linkedin_search_url
    assert "Acme" in p.linkedin_search_url
    assert "Likely" not in p.linkedin_search_url  # qualifier stripped from terms


def test_linkedin_search_prefers_the_contact_name():
    qual = QualificationEngine().qualify(_agency())
    scored = ScoringEngine().score(_agency())
    est = EstimationEngine().estimate(_agency(), qual.team_shape, qual.discipline)
    strat = assess_strategic_value(_agency())
    p = build_outreach_plan(_agency(), qual, scored, est, strat, contact_name="Dana Reyes")
    # With a known contact, the people-search keys off their NAME, not the title.
    assert "Dana" in p.linkedin_search_url and "Reyes" in p.linkedin_search_url


def test_render_text_is_copyable_and_complete():
    text = _plan_for(_agency()).render_text()
    for marker in ("OUTREACH PLAN", "Contact:", "Urgency:", "First-touch message:",
                   "Cadence:"):
        assert marker in text


def test_door_opener_drives_24h_urgency():
    # Small budget + named agency -> strategic door-opener -> fast urgency.
    opp = Opportunity(
        client="Major Agency",
        need="Original cue for a brand spot",
        buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=2_000, budget_max=2_000,
        marquee=True,
    )
    p = _plan_for(opp)
    assert "24h" in p.urgency


def test_tight_turnaround_is_urgent():
    opp = _agency()
    opp.turnaround_days = 3
    p = _plan_for(opp)
    assert "24h" in p.urgency


def test_government_gets_a_compliance_step_and_formal_channel():
    opp = Opportunity(
        client="City of Springfield",
        need="Original music for a public-safety campaign",
        buyer_type=BuyerType.GOVERNMENT,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=8_000, budget_max=15_000,
    )
    p = _plan_for(opp)
    assert "portal" in p.primary_channel.lower() or "formal" in p.primary_channel.lower()
    assert any("submission" in s.action.lower() for s in p.steps)


def test_plan_is_deterministic():
    a = _plan_for(_agency())
    b = _plan_for(_agency())
    assert a.render_text() == b.render_text()


def test_plan_handles_disqualified_opportunity():
    opp = Opportunity(client="Joe", need="Wedding cover band for reception")
    p = _plan_for(opp)
    assert p.qualified is False
    # Should still render without crashing.
    assert "OUTREACH PLAN" in p.render_text()
