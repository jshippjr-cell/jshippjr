"""Tests for the Phase-1 estimation engine."""

from chordential_oia.estimation import (
    BAND_SPREAD,
    TARGET_MARGIN,
    EstimationEngine,
    build_estimate,
)
from chordential_oia.models import BuyerType, MusicDiscipline, MusicRequirement, Opportunity


def _opp(**kw) -> Opportunity:
    base = dict(
        client="Acme (agency)",
        need="Original :30 national campaign spot",
        buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL,
        budget_min=6_000, budget_max=12_000,
    )
    base.update(kw)
    return Opportunity(**base)


def test_engine_returns_point_and_band():
    est = EstimationEngine().estimate(
        _opp(), discipline=MusicDiscipline.COMPOSITION
    )
    assert est.cost_low < est.estimated_cost < est.cost_high
    assert est.cost_low == round(est.estimated_cost * (1 - BAND_SPREAD), 6) or \
        abs(est.cost_low - est.estimated_cost * (1 - BAND_SPREAD)) < 1e-6
    assert est.band_spread_pct == BAND_SPREAD * 100.0
    assert "–" in est.cost_range


def test_team_derived_from_discipline_when_absent():
    est = EstimationEngine().estimate(_opp(), discipline=MusicDiscipline.SOUND_DESIGN)
    roles = [l.role for l in est.lines]
    assert "Sound Designer" in roles  # from MusicDiscipline.SOUND_DESIGN.team_shape


def test_project_manager_always_included():
    est = EstimationEngine().estimate(_opp(), team_shape=["Composer"])
    assert any(l.role == "Project Manager" for l in est.lines)


def test_suggested_price_hits_target_margin():
    est = build_estimate(_opp(), ["Composer", "Mixer"], MusicDiscipline.COMPOSITION)
    # price = cost / (1 - margin)
    assert abs(est.suggested_price * (1 - TARGET_MARGIN) - est.estimated_cost) < 1e-6
    assert est.expected_margin_pct == TARGET_MARGIN * 100.0


def test_multipliers_inferred_from_text():
    est = build_estimate(
        _opp(need="Original :60 anthem, full orchestra, national, 3 rounds"),
        ["Composer", "Mixer"], MusicDiscipline.COMPOSITION,
    )
    settings = {m.name: m.factor for m in est.multipliers}
    assert settings["Duration"] == 1.5          # :60 / anthem
    assert settings["Instrumentation"] == 4.0   # full orchestra
    assert settings["Licensing reach"] == 1.2   # national
    assert settings["Revisions"] == 1.30        # 3 rounds


def test_regression_known_numbers():
    # Composer+Mixer+PM, :30 (1.0) x piano (1.0) x local (1.0) x 2-rev (1.15).
    # base = 8*150 + 5*110 + 2*85 = 1200 + 550 + 170 = 1920
    # estimated = 1920 * 1.0 * 1.15 = 2208
    est = build_estimate(
        Opportunity(client="X", need="Original music"),
        ["Composer", "Mixer"], MusicDiscipline.COMPOSITION,
    )
    assert abs(est.base_cost - 1920.0) < 1e-6
    assert abs(est.estimated_cost - 2208.0) < 1e-6


def test_web_shim_reexports_engine():
    # The dashboard must import the same engine — no duplicated logic.
    from chordential_oia.web import estimate as web_estimate
    from chordential_oia import estimation
    assert web_estimate.build_estimate is estimation.build_estimate
    assert web_estimate.Estimate is estimation.Estimate
