"""One estimate call path.

The launch review found the four lines that turn an opportunity into an estimate
— resolve a discipline, derive a team shape, fetch rate overrides, call the
engine — copy-pasted at nine call sites in the web layer, in three versions:

* seven applied a **qualified-fallback** (an unqualified deal is priced as
  ``COMPOSITION`` rather than against ``NON_CRAFT``, which has an empty team);
* two — the dashboard KPI's ``_suggested_price`` and the project estimate —
  used ``qual.discipline`` raw, so the *same* disqualified deal priced at
  $7,810 on the dashboard and $8,350 on its own estimate page;
* only the project estimate resolved ``assigned_rate_overrides``, so the number
  a client approved could differ from the proposal generated after assignment.

ADR-0033 collapses all of them into ``web.estimate.estimate_for``.
"""

import importlib
from pathlib import Path

import pytest

from chordential_oia.models import Opportunity
from chordential_oia.web.estimate import estimate_for
from chordential_oia.web.evaluate import evaluate

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia.web.delivery_ops import _project_estimate  # noqa: E402
from chordential_oia.web.console_routes import _suggested_price  # noqa: E402

# A deal the qualification engine hard-fails (DJ booking + playlist curation).
# Disqualified is the case that exposed the divergence: NON_CRAFT carries an
# EMPTY team shape, so the two variants hand the engine different crews.
DISQUALIFIED = Opportunity(
    client="Northwind Events", need="DJ for the launch party",
    description="Need a DJ and a Spotify playlist for the event.",
)


def test_the_fixture_really_is_disqualified():
    """Guards the rest of the file: if the classifier ever starts qualifying this,
    the divergence tests below would pass vacuously."""
    qual, _ = evaluate(DISQUALIFIED)
    assert not qual.qualified
    assert qual.team_shape == [], "NON_CRAFT's empty team is what made the variants differ"


# --------------------------------------------------------------------------- #
# The structural half — one home, so a tenth variant cannot appear
# --------------------------------------------------------------------------- #
def test_only_the_seam_calls_the_engine():
    """``build_estimate`` is the intelligence layer's entry point; the web layer
    reaches it through ``estimate_for`` and nowhere else. Re-deriving the
    arguments by hand is how the three variants happened."""
    web = Path(importlib.import_module("chordential_oia.web").__file__).parent
    offenders = [
        p.relative_to(web).as_posix()
        for p in sorted(web.rglob("*.py"))
        if p.name != "estimate.py" and "build_estimate(" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        "these modules call the estimation engine directly instead of "
        f"web.estimate.estimate_for: {offenders}"
    )


def test_the_discipline_fallback_lives_in_exactly_one_place():
    """The literal idiom that was pasted nine times. It may survive for deriving
    *project roles* (``_ensure_project_for_opp``), but not for pricing."""
    web = Path(importlib.import_module("chordential_oia.web").__file__).parent
    idiom = "qual.discipline if qual.qualified else"
    hits = [
        p.relative_to(web).as_posix()
        for p in sorted(web.rglob("*.py"))
        if idiom in p.read_text(encoding="utf-8")
    ]
    assert "estimate.py" in hits
    assert len(hits) <= 2, f"the fallback is drifting back out across the web layer: {hits}"


# --------------------------------------------------------------------------- #
# The behavioural half — the numbers the variants disagreed on
# --------------------------------------------------------------------------- #
def test_the_dashboard_kpi_prices_a_deal_the_way_its_estimate_page_does():
    """``_suggested_price`` was variant (a). Same opportunity, two numbers."""
    from chordential_oia.web import app as app_mod

    assert _suggested_price(DISQUALIFIED) == estimate_for(DISQUALIFIED).suggested_price


def test_the_public_price_band_prices_it_the_same_way_too():
    """The band a prospect is quoted at intake and the estimate Jon opens after
    that lead lands are the same engine call — or the first conversation starts
    by walking a number back."""
    from chordential_oia.web import public

    est = estimate_for(Opportunity(
        client="(prospect)", need="DJ for the launch party",
        description="Need a DJ and a Spotify playlist for the event.",
    ))
    band = public.public_price_band(
        "DJ for the launch party", "Need a DJ and a Spotify playlist for the event.")
    ratio = est.suggested_price / est.estimated_cost
    assert band["low"] <= est.cost_low * ratio + 100
    assert band["high"] >= est.cost_high * ratio - 100


def test_an_unqualified_deal_is_priced_against_a_real_team():
    """The fallback's substance: NON_CRAFT has no crew, so variant (a) estimated
    a crew the discipline never specified. Composition is the honest default."""
    est = estimate_for(DISQUALIFIED)
    roles = [line.role for line in est.lines]
    assert "Music Editor" in roles, "the composition team shape was not applied"
    assert est.suggested_price > 0


# --------------------------------------------------------------------------- #
# Rate overrides — the second divergence: assigned cost vs role defaults
# --------------------------------------------------------------------------- #
@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "est.db"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass                      # the lifespan is what seeds the database
    return mod


def test_the_project_estimate_still_honours_assigned_rates(app_mod):
    """The one thing the consolidation must NOT lose: with a project in play the
    assigned creator's own rate replaces the role default, so the internal number
    and the client-facing proposal cannot diverge after assignment."""
    from chordential_oia.web import db

    conn = db.connect()
    try:
        prow = conn.execute(
            "SELECT * FROM projects WHERE opp_id IS NOT NULL ORDER BY id"
        ).fetchone()
        assert prow is not None, "the demo seed did not produce a project"
        overrides = db.assigned_rate_overrides(conn, prow["id"])
        assert overrides, "the demo project has no assigned rates — test proves nothing"

        opp = db.opportunity_from_row(db.get_opportunity(conn, prow["opp_id"]))
        with_project = _project_estimate(conn, prow)
        without = estimate_for(opp)
    finally:
        conn.close()

    assert with_project.estimated_cost != without.estimated_cost, (
        "assigned rate overrides were dropped by the consolidation")


def test_estimate_for_ignores_overrides_when_there_is_no_project():
    """A conn alone must not reach for rates — the pre-award estimate is priced at
    role defaults, which is what the client sees on the brief."""
    from chordential_oia.web import db

    conn = db.connect()
    try:
        a = estimate_for(DISQUALIFIED, conn=conn)
        b = estimate_for(DISQUALIFIED)
    finally:
        conn.close()
    assert a.estimated_cost == b.estimated_cost


def test_a_precomputed_qualification_is_honoured_not_recomputed():
    """Call sites that already hold a qualification pass it in; if it were quietly
    re-evaluated the seam would double the engine work on every page."""
    qual, _ = evaluate(DISQUALIFIED)
    qual.team_shape = ["Mix Engineer"]                # a shape evaluate() never returns
    est = estimate_for(DISQUALIFIED, qual=qual)
    assert [line.role for line in est.lines if line.role == "Mix Engineer"], (
        "estimate_for re-evaluated instead of using the qualification it was given")
