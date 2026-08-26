"""The pricing model, readable without a deal in front of you.

Every other pricing surface in the product hangs off one opportunity — the estimate, the
proposal, the call prep sheet's guide. That is right for pricing a job and useless for
LEARNING the model, and the model is the thing that has to be in the operator's head while
a client is talking: *"I need to understand the pricing around our product"* (2026-08-26).

The whole risk of a page like this is that it becomes a SECOND pricing authority. A
reference that restates the tables is correct on the day it ships and wrong on the first
day somebody edits `pricing.py` — and wrong quietly, because nothing fails. So most of what
follows checks the page is a reporter and not a source (ADR-0033 / ADR-0065: one quote
authority, wired to the work).
"""
import importlib
import re

import pytest

from chordential_oia import pricing as P
from chordential_oia.estimation import BAND_SPREAD, ROLE_RATES, TARGET_MARGIN


@pytest.fixture()
def page(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    return c


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ── it is a reporter, not a second source ───────────────────────────────────────────
def test_every_factor_the_engine_multiplies_is_on_the_page(page):
    """Printed from the dicts `build_quote` uses. Add a media type or move a multiplier in
    `pricing.py` and it appears here; a page that had them typed out would go stale in
    silence, which is the failure mode a reference cannot have."""
    body = _text(page.get("/pricing").text)
    for table, labels in ((P.MEDIA_FACTORS, P.MEDIA_LABELS),
                          (P.TERRITORY_FACTORS, P.TERRITORY_LABELS),
                          (P.EXCLUSIVITY_FACTORS, P.EXCLUSIVITY_LABELS)):
        for key, factor in table.items():
            assert labels[key] in body, f"{labels[key]} is missing"
            assert f"×{factor:.2f}" in body, f"{labels[key]} factor {factor} is missing"
    for years, factor in P.TERM_FACTORS.items():
        assert f"×{factor:.2f}" in body, f"term {years} factor {factor} is missing"


def test_the_worked_example_is_the_engine_not_a_restatement(page):
    """The number on the page must be the number `build_quote` returns for those settings,
    to the dollar. This is the test that would fail if anybody ever 'simplified' the page
    by computing the arithmetic in the template."""
    body = _text(page.get("/pricing?cost=9000").text)
    quote = P.build_quote(P.reference_estimate(9000), P.LicenceTerms())
    assert f"${quote.creative_fee:,}" in body
    assert f"${quote.licence_fee:,}" in body
    assert f"${quote.total:,}" in body
    assert f"${quote.floor:,}" in body


def test_moving_a_lever_moves_the_number_the_engine_says_it_should(page):
    body = _text(page.get("/pricing?cost=9000&territory=global").text)
    quote = P.build_quote(P.reference_estimate(9000),
                          P.LicenceTerms(territory="global"))
    assert f"${quote.total:,}" in body
    baseline = P.build_quote(P.reference_estimate(9000), P.LicenceTerms())
    assert quote.total > baseline.total, "worldwide did not cost more than national"


def test_the_cap_and_the_margins_are_read_not_typed(page):
    body = _text(page.get("/pricing").text)
    assert f"×{P.LICENCE_FACTOR_CAP:.1f}" in body
    assert f"{int(P.BASE_LICENCE_SHARE * 100)}% baseline share" in body
    assert f"{int(TARGET_MARGIN * 100)}% target margin" in body
    assert f"{int(P.MIN_MARGIN * 100)}% margin" in body
    assert f"±{int(BAND_SPREAD * 100)}%" in body


def test_the_rates_behind_the_estimate_are_the_real_rates(page):
    body = _text(page.get("/pricing").text)
    for role, rate in ROLE_RATES.items():
        assert role in body, f"{role} is missing"
        assert f"${int(rate)}/hr" in body, f"{role} rate is wrong or missing"


def test_the_market_benchmarks_are_all_there(page):
    body = _text(page.get("/pricing").text)
    for who, what, lo, _hi in P.MARKET_BENCHMARKS:
        assert who in body and what in body
        assert f"${lo:,}" in body


# ── honesty ─────────────────────────────────────────────────────────────────────────
def test_the_page_says_these_are_priors_not_measurements(page):
    """The factor tables have the same standing here as in `estimation`: expert priors,
    ratified but uncalibrated. A reference page is exactly where a prior starts being read
    as a fact, so it carries its own disclaimer."""
    body = _text(page.get("/pricing").text)
    assert P.PRIOR_NOTE in body
    assert "market-pricing-research.md" in body


def test_the_page_says_the_budget_does_not_set_the_price(page):
    """ADR-0065. A price that moves to meet a number the client happened to say is not a
    price, it is an echo — and this page is where a salesperson learns which way round it
    goes."""
    body = _text(page.get("/pricing").text).lower()
    assert "never sets" in body
    assert "verdict" in body


# ── it holds up to being poked ──────────────────────────────────────────────────────
def test_a_hand_typed_url_cannot_price_a_factor_that_does_not_exist(page):
    r = page.get("/pricing?cost=abc&media=nonsense&territory=mars&term=zzz&exclusivity=x")
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        body = _text(r.text)
        assert f"${P.build_quote(P.reference_estimate(9000), P.LicenceTerms()).total:,}" in body


def test_the_cost_is_clamped_rather_than_believed(page):
    body = _text(page.get("/pricing?cost=99999999").text)
    biggest = P.build_quote(P.reference_estimate(500_000), P.LicenceTerms())
    assert f"${biggest.total:,}" in body


def test_the_client_never_sees_it(page):
    """Rate cards, floors and margins. This is the single most internal page in the
    product and it sits behind the admin gate like everything else in the console."""
    from chordential_oia.web import app as app_mod
    assert not app_mod._is_public_path("/pricing")
    bare = type(page)(app_mod.app)
    assert bare.get("/pricing", follow_redirects=False).status_code in (302, 303, 401, 403)


def test_it_is_reachable_from_the_nav(page):
    """A reference nobody can find is a document, not a feature. It earns a nav slot
    because it is read between deals, not inside one."""
    assert 'href="/pricing"' in page.get("/dashboard").text


# ── the stand-in estimate ───────────────────────────────────────────────────────────
def test_the_reference_estimate_carries_a_cost_and_no_opinions():
    """`build_quote` reads exactly two fields off an estimate. `suggested_price` is left at
    zero deliberately: it folds usage into the creative number and `build_quote` ignores it
    (ADR-0065), so a plausible figure there would be a number nobody should read."""
    est = P.reference_estimate(9000)
    assert est.estimated_cost == 9000
    assert est.cost_high > est.estimated_cost > est.cost_low
    assert est.suggested_price == 0.0
    assert est.lines == [] and est.multipliers == []


def test_the_reference_estimate_prices_the_same_as_any_other(page):
    """It is a carrier, not a special case: the same cost through the same engine gives the
    same quote whether it arrived from a real opportunity or from this page."""
    from chordential_oia.estimation import Estimate
    from chordential_oia.models import MusicDiscipline
    hand = Estimate(discipline=MusicDiscipline.COMPOSITION, lines=[], multipliers=[],
                    base_cost=9000, multiplier_total=1.0, revision_uplift=0.0,
                    estimated_cost=9000, suggested_price=0.0, expected_margin_pct=0.0,
                    disclosed_budget=None, budget_delta_note="",
                    cost_low=9000 * (1 - BAND_SPREAD), cost_high=9000 * (1 + BAND_SPREAD))
    assert P.build_quote(hand).total == P.build_quote(P.reference_estimate(9000)).total
