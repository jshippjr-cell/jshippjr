"""Tests for the qualification layer (docs/qualification-spec.md)."""

import json

from chordential_oia.models import (
    BuyerType,
    Confidence,
    MusicDiscipline,
    MusicRequirement,
    Opportunity,
    QualificationAction,
)
from chordential_oia.qualification import (
    QUALIFICATION_WEIGHTS,
    QualificationEngine,
    classify_discipline,
    hard_disqualifiers,
    record_label,
)


def _qualified_agency() -> Opportunity:
    # Concrete, original, agency, budget over floor -> should sail through.
    return Opportunity(
        client="Acme (agency)",
        need="Original :30 campaign spot music",
        description="National brand campaign; original music, multiple cutdowns, fast.",
        buyer_type=BuyerType.AGENCY,
        commercial_campaign=True,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=6_000,
        budget_max=12_000,
        tags=["original", "cutdowns"],
    )


# --------------------------------------------------------------------------- #
# Weights / config
# --------------------------------------------------------------------------- #
def test_qualification_weights_sum_to_100():
    assert sum(QUALIFICATION_WEIGHTS.values()) == 100


def test_craft_fit_is_weighted_above_budget():
    # Decision #6: qualification accuracy first — craft must outweigh money.
    assert QUALIFICATION_WEIGHTS["Craft Fit"] > QUALIFICATION_WEIGHTS["Budget Signal"]


def test_unknown_dimension_raises():
    try:
        QualificationEngine(weights={"Vibes": 100})
    except ValueError as exc:
        assert "Vibes" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown dimension")


# --------------------------------------------------------------------------- #
# Stage 0 — hard disqualifiers (the junk gate)
# --------------------------------------------------------------------------- #
def test_cover_band_disqualified():
    opp = Opportunity(client="Joe", need="Wedding cover band for reception")
    q = QualificationEngine().qualify(opp)
    assert q.qualified is False
    assert q.recommended_action is QualificationAction.PASS
    assert q.discipline is MusicDiscipline.NON_CRAFT
    assert q.disqualifiers


def test_karaoke_dj_playlist_lessons_all_disqualified():
    junk = [
        "Karaoke host for corporate party",
        "Need a DJ for our launch event",
        "Curate a Spotify playlist for our store",
        "Looking for guitar lessons",
    ]
    eng = QualificationEngine()
    for need in junk:
        q = eng.qualify(Opportunity(client="X", need=need))
        assert q.qualified is False, need
        assert q.recommended_action is QualificationAction.PASS, need


def test_dj_substring_does_not_false_fire():
    # "adjust" / "adjacent" must not trip the " dj " token.
    opp = _qualified_agency()
    opp.description = "Please adjust the cue to be adjacent to the logo reveal."
    assert "DJ booking — performance, not creation" not in hard_disqualifiers(opp)


def test_no_music_need_disqualified():
    opp = Opportunity(
        client="Agency",
        need="Social video editing retainer",
        buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.NONE,
    )
    q = QualificationEngine().qualify(opp)
    assert q.qualified is False


# --------------------------------------------------------------------------- #
# Stage 1 — discipline classification
# --------------------------------------------------------------------------- #
def test_classify_sonic_branding_beats_composition():
    opp = Opportunity(
        client="Brand",
        need="Sonic logo / audio identity, original",
        music_requirement=MusicRequirement.ORIGINAL,
    )
    primary, _ = classify_discipline(opp)
    assert primary is MusicDiscipline.SONIC_BRANDING


def test_classify_composition_default_for_original():
    primary, _ = classify_discipline(_qualified_agency())
    assert primary is MusicDiscipline.COMPOSITION


def test_classify_licensing():
    opp = Opportunity(
        client="Studio",
        need="License a pre-existing track for our spot",
        music_requirement=MusicRequirement.LICENSED,
    )
    primary, _ = classify_discipline(opp)
    assert primary is MusicDiscipline.LICENSING


def test_team_shape_handed_to_estimator():
    q = QualificationEngine().qualify(_qualified_agency())
    assert "Composer" in q.team_shape  # composition -> composer on the team


# --------------------------------------------------------------------------- #
# Stage 2 — alignment, routing, confidence
# --------------------------------------------------------------------------- #
def test_strong_opportunity_pursued_and_alertable():
    q = QualificationEngine().qualify(_qualified_agency())
    assert q.qualified is True
    assert q.alignment_pct >= 70
    assert q.recommended_action is QualificationAction.PURSUE
    assert q.alertable is True
    assert q.confidence is Confidence.HIGH
    assert "% aligned" in q.fit_summary


def test_low_confidence_is_not_alertable():
    # Implied need, unknown buyer, no budget -> low confidence -> never Pursue.
    opp = Opportunity(client="Someone", need="We might need some music maybe")
    q = QualificationEngine().qualify(opp)
    assert q.confidence is Confidence.LOW
    assert q.recommended_action is not QualificationAction.PURSUE
    assert q.needs_human_review is True
    assert q.alertable is False


def test_human_confirm_unlocks_pursue_for_medium_confidence():
    opp = _qualified_agency()
    opp.commercial_campaign = None  # drop one explicit signal -> medium confidence
    eng = QualificationEngine()
    auto = eng.qualify(opp)
    confirmed = eng.qualify(opp, human_confirmed=True)
    if auto.alignment_pct >= eng.alert_floor and auto.confidence is not Confidence.HIGH:
        assert auto.recommended_action is QualificationAction.REVIEW
        assert confirmed.recommended_action is QualificationAction.PURSUE


def test_alignment_bounded():
    q = QualificationEngine().qualify(_qualified_agency())
    assert 0.0 <= q.alignment_pct <= 100.0


def test_soft_flag_caps_alignment_and_forces_review():
    opp = _qualified_agency()
    opp.need = "Need royalty-free background music for our spot"
    q = QualificationEngine().qualify(opp)
    assert q.qualified is True
    assert q.alignment_pct <= 60.0
    assert q.needs_human_review is True


def test_clearance_risk_lowers_clearable_score():
    opp = _qualified_agency()
    opp.description = "We want a cover of a famous hit song; master rights needed."
    q = QualificationEngine().qualify(opp)
    clearable = next(b for b in q.breakdown if b.name == "Clearable")
    assert clearable.normalized <= 0.4


def test_configurable_alert_floor():
    opp = _qualified_agency()
    strict = QualificationEngine(alert_floor=100.5)
    q = strict.qualify(opp)
    # With an unreachable floor, even a strong lead falls back to review/watch.
    assert q.recommended_action is not QualificationAction.PURSUE


# --------------------------------------------------------------------------- #
# Moat capture (§9)
# --------------------------------------------------------------------------- #
def test_record_label_writes_jsonl_with_agreement(tmp_path):
    opp = _qualified_agency()
    q = QualificationEngine().qualify(opp)
    path = tmp_path / "labels.jsonl"
    # Human agrees with the prediction.
    rec = record_label(
        opp, q, corrected_qualified=True,
        corrected_discipline=q.discipline, reason="looks right", path=str(path),
    )
    assert rec["agreement"] is True
    # Human overrides discipline -> disagreement captured.
    rec2 = record_label(
        opp, q, corrected_qualified=True,
        corrected_discipline=MusicDiscipline.SOUND_DESIGN,
        reason="actually sound design", path=str(path),
    )
    assert rec2["agreement"] is False
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["predicted"]["discipline"] == q.discipline.value
