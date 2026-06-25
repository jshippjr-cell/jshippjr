"""Talent rate → project proposal (Council §5).

A founder-set talent rate overrides the global role default in the estimate that
backs the project proposal. Conversions: hourly → hours × rate; day → ceil(h/8)
days × rate; project → flat rate. The pre-assignment opportunity price band (no
overrides) is unchanged.
"""

import importlib
import math

import pytest

from chordential_oia.estimation import ROLE_HOURS, ROLE_RATES, build_estimate
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


# --------------------------------------------------------------------------- #
# Unit-level: build_estimate rate_overrides conversions
# --------------------------------------------------------------------------- #
def test_hourly_override_changes_line_cost_and_total():
    team = ["Composer", "Mixer"]
    base = build_estimate(_opp(), team, MusicDiscipline.COMPOSITION)
    over = build_estimate(
        _opp(), team, MusicDiscipline.COMPOSITION,
        rate_overrides={"Composer": {"rate": 300.0, "unit": "hourly"}},
    )
    comp_hours = ROLE_HOURS["Composer"]
    comp = next(l for l in over.lines if l.role == "Composer")
    assert comp.rate == 300.0
    assert comp.cost == comp_hours * 300.0          # hours × rate
    # Total moved by the per-line delta vs the default composer rate.
    delta = comp_hours * (300.0 - ROLE_RATES["Composer"])
    assert abs((over.base_cost - base.base_cost) - delta) < 1e-6
    assert over.estimated_cost > base.estimated_cost


def test_day_rate_override_uses_ceil_hours_over_eight():
    over = build_estimate(
        _opp(), ["Composer", "Mixer"], MusicDiscipline.COMPOSITION,
        rate_overrides={"Composer": {"rate": 1200.0, "unit": "day"}},
    )
    hours = ROLE_HOURS["Composer"]
    days = max(1, math.ceil(hours / 8.0))
    comp = next(l for l in over.lines if l.role == "Composer")
    assert comp.cost == days * 1200.0


def test_project_flat_override_replaces_line_cost():
    over = build_estimate(
        _opp(), ["Composer", "Mixer"], MusicDiscipline.COMPOSITION,
        rate_overrides={"Composer": {"rate": 5000.0, "unit": "project"}},
    )
    comp = next(l for l in over.lines if l.role == "Composer")
    # Flat: cost = rate regardless of hours.
    assert comp.cost == 5000.0


def test_no_override_is_byte_for_byte_unchanged():
    a = build_estimate(_opp(), ["Composer", "Mixer"], MusicDiscipline.COMPOSITION)
    b = build_estimate(
        _opp(), ["Composer", "Mixer"], MusicDiscipline.COMPOSITION, rate_overrides=None
    )
    assert [(l.role, l.hours, l.rate, l.cost) for l in a.lines] == \
        [(l.role, l.hours, l.rate, l.cost) for l in b.lines]
    assert a.base_cost == b.base_cost
    assert a.estimated_cost == b.estimated_cost
    assert a.suggested_price == b.suggested_price


# --------------------------------------------------------------------------- #
# End-to-end: talent rate flows assignment → estimate → proposal
# --------------------------------------------------------------------------- #
@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def _sample_opp():
    return Opportunity(
        client="Acme Agency", need="Original :30 brand spot music",
        description="National campaign, original composition.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=8000, budget_max=15000,
    )


def test_assigned_day_rate_flows_into_proposal(ctx):
    client, db_mod = ctx
    conn = db_mod.connect()
    opp_id = db_mod.insert_opportunity(conn, _sample_opp())
    conn.close()

    # Create a project from the opportunity, then read its scoped roles.
    r = client.post(f"/opportunity/{opp_id}/project", follow_redirects=False)
    pid = int(r.headers["location"].split("/project/")[1])
    conn = db_mod.connect()
    prow = db_mod.get_project(conn, pid)
    import json as _json
    roles = _json.loads(prow["roles"])
    conn.close()
    role = "Composer" if "Composer" in roles else roles[0]

    # Create a talent with a day rate and assign to that role. $2,000/day is
    # deliberately distinct from any default so the total visibly moves.
    r = client.post(
        "/talent",
        data={"name": "Maya Okafor", "disciplines": [], "rate": "2000",
              "rate_unit": "day"},
        follow_redirects=False,
    )
    tid = int(r.headers["location"].split("/talent/")[1])
    client.post(f"/project/{pid}/assign", data={"role": role, "talent_id": tid})

    # Generate the proposal — the assigned talent's day rate must drive the line.
    client.post(f"/project/{pid}/proposal")
    conn = db_mod.connect()
    prop = db_mod.proposal_for_project(conn, pid)
    conn.close()

    items = _json.loads(prop["line_items"])
    line = next(i for i in items if i["role"] == role)
    hours = ROLE_HOURS.get(role, 4.0)
    days = max(1, math.ceil(hours / 8.0))
    assert line["rate"] == 2000.0
    assert line["cost"] == days * 2000.0          # day-rate cost, not the default

    # The proposal total must match the override-driven estimate, and differ
    # from the no-rate (default) estimate for the same team.
    opp = _sample_opp()
    override_est = build_estimate(
        opp, roles, MusicDiscipline.COMPOSITION,
        rate_overrides={role: {"rate": 2000.0, "unit": "day"}},
    )
    default_est = build_estimate(opp, roles, MusicDiscipline.COMPOSITION)
    assert round(prop["total_price"], 2) == round(override_est.suggested_price, 2)
    assert round(override_est.suggested_price, 2) != round(default_est.suggested_price, 2)


def test_opportunity_price_band_path_unchanged(ctx):
    """The pre-assignment estimate (no overrides) must keep its numbers."""
    client, db_mod = ctx
    opp = _sample_opp()
    from chordential_oia.web.evaluate import evaluate
    qual, _ = evaluate(opp)
    team = qual.team_shape or qual.discipline.team_shape
    a = build_estimate(opp, team, qual.discipline)
    b = build_estimate(opp, team, qual.discipline, rate_overrides={})
    assert a.suggested_price == b.suggested_price
    assert a.cost_low == b.cost_low and a.cost_high == b.cost_high
