"""One pricing voice.

The launch review found four numbers for the same job: the public planning band
quoted $9,000–18,000 for a national :30, the engine costed it at $4,847, the
client-facing proposal band rendered ≈$3,100–6,600, and the outreach cadence told
the operator to quote a fifth figure. The public band is the researched,
operator-ratified prior, so the engine is calibrated toward it — and these tests
are what stops the two drifting apart again.
"""

import importlib

import pytest

from chordential_oia.estimation import (
    PUBLIC_BANDS, PUBLIC_LENGTHS, PUBLIC_USAGE, USAGE_FACTORS,
    build_estimate, public_band,
)
from chordential_oia.models import MusicDiscipline, Opportunity


def _price(need, description=""):
    est = build_estimate(
        Opportunity(client="X", need=need, description=description),
        ["Composer", "Mixer"], MusicDiscipline.COMPOSITION,
    )
    return est


def test_engine_lands_inside_the_public_band_for_a_national_spot():
    """The headline disagreement: what a visitor is quoted, and what the engine
    would have the operator quote, for the same brief."""
    low, high = public_band("spot", "30", "national")
    est = _price("Original :30 brand spot, national broadcast")
    assert low <= est.suggested_price <= high, (
        f"engine suggests ${est.suggested_price:,.0f}, public band is "
        f"${low:,.0f}-${high:,.0f}")


def test_engine_lands_inside_the_public_band_for_an_anthem():
    low, high = public_band("anthem", "60", "national")
    est = _price("Original :60 anthem, strings, national broadcast")
    assert low <= est.suggested_price <= high, (
        f"engine suggests ${est.suggested_price:,.0f}, public band is "
        f"${low:,.0f}-${high:,.0f}")


def test_the_public_estimator_renders_the_engine_constants(tmp_path, monkeypatch):
    """The band's priors were hardcoded JavaScript inside the template, free to
    drift from the engine — and they had. The page now renders them from the
    engine, so there is one definition."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)

    with TestClient(app_mod.app) as c:
        # the estimator lives on the Commission, which moved to /commission
        body = c.get("/commission").text
    for kind, (low, high) in PUBLIC_BANDS.items():
        assert f'"{kind}": [{low}, {high}]' in body, f"{kind} band not rendered from the engine"
    for length, factor in PUBLIC_LENGTHS.items():
        assert f'"{length}": {factor}' in body
    for usage, factor in PUBLIC_USAGE.items():
        assert f'"{usage}": {factor}' in body


def test_public_usage_factors_are_the_engine_usage_factors():
    """Same licence, same multiplier, wherever it is quoted."""
    assert PUBLIC_USAGE["national"] == USAGE_FACTORS["national"]
    assert PUBLIC_USAGE["global"] == USAGE_FACTORS["global"]
    assert PUBLIC_USAGE["social"] == USAGE_FACTORS["local"]


def test_the_client_facing_band_brackets_the_suggested_price():
    """capabilities._price_band is what the client actually reads on the proposal.
    It is derived from the estimate, so it must contain the number it derives
    from — it rendered a range the suggested price sat outside of."""
    from chordential_oia.capabilities import _price_band

    est = _price("Original :30 brand spot, national broadcast")
    low, high = _price_band(est)
    assert low <= est.suggested_price <= high


def test_session_players_are_paid_and_scale_with_the_ensemble():
    """'Full orchestra' was a ×4 on desk hours — including the project manager's —
    and never paid a player. Instrumentation now selects a real session cost."""
    simple = _price("Original :30 spot, piano, national")
    hybrid = _price("Original :30 spot, strings, national")
    orch = _price("Original :30 spot, full orchestra, national")
    assert simple.session_cost < hybrid.session_cost < orch.session_cost
    assert orch.session_cost > 20000
    for est in (simple, hybrid, orch):
        assert est.session_cost > 0, "every recording costs something to record"
