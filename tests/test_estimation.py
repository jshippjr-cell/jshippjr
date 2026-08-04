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
    assert settings["Duration"] == 1.25         # :60 / anthem
    assert settings["Instrumentation"] == 1.6   # full orchestra — WRITING complexity
    assert settings["Usage / licence"] == 1.0   # national is the baseline licence
    assert settings["Revisions"] == 1.30        # 3 rounds
    # The orchestra is paid on its own line, not by inflating desk hours.
    assert est.session_cost > 20000 and est.session_label == "Full orchestra"


def test_longest_duration_wins_so_listing_cutdowns_cannot_cheapen_a_brief():
    """The engine tested ":15" before ":60", so a real campaign brief — which
    always enumerates its cutdown suite — was classified by its SHORTEST
    deliverable. ":60 anthem with :30 and :15 cutdowns" priced at half a bare
    :30: naming the extra work made the job cheaper."""
    bare = build_estimate(_opp(need="Original :30 brand spot, national"),
                          ["Composer", "Mixer"], MusicDiscipline.COMPOSITION)
    full = build_estimate(
        _opp(need="Original :30 brand spot, national",
             description=":60 anthem with :30 and :15 cutdowns"),
        ["Composer", "Mixer"], MusicDiscipline.COMPOSITION)
    assert full.suggested_price > bare.suggested_price, (
        "enumerating deliverables must never reduce the price")


def test_usage_is_a_fee_on_price_not_a_cost_of_production():
    """A wider licence does not make the session longer. Rolling it into cost
    implied it did, and inflated the margin calculation with it."""
    national = build_estimate(_opp(need="Original :30 spot, national"),
                              ["Composer", "Mixer"], MusicDiscipline.COMPOSITION)
    world = build_estimate(_opp(need="Original :30 spot, global"),
                           ["Composer", "Mixer"], MusicDiscipline.COMPOSITION)
    assert abs(world.estimated_cost - national.estimated_cost) < 1e-6
    assert abs(world.suggested_price - national.suggested_price * 2.0) < 1e-6


def test_regression_known_numbers():
    # Composer+Mixer+PM at campaign scale, :30 (1.0) x simple (1.0) x 2-rev (1.15),
    # plus the session line that pays the player and the room.
    # base    = 20*150 + 8*110 + 6*85 = 3000 + 880 + 510 = 4390
    # desk    = 4390 * 1.0 * 1.15 = 5048.5
    # session = (1*600 + 600) * 1.0 = 1200
    est = build_estimate(
        Opportunity(client="X", need="Original music"),
        ["Composer", "Mixer"], MusicDiscipline.COMPOSITION,
    )
    assert abs(est.base_cost - 4390.0) < 1e-6
    assert abs(est.session_cost - 1200.0) < 1e-6
    assert abs(est.estimated_cost - 6248.5) < 1e-6


def test_web_shim_reexports_engine():
    # The dashboard must import the same engine — no duplicated logic.
    from chordential_oia.web import estimate as web_estimate
    from chordential_oia import estimation
    assert web_estimate.build_estimate is estimation.build_estimate
    assert web_estimate.Estimate is estimation.Estimate
