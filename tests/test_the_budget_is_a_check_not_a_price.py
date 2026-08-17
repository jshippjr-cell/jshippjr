"""What the client said stops being what the client pays.

`capabilities.quote_band` had three tiers and the second one was the disclosed budget —
which fires on essentially every deal that has had a discovery call, because discovering
the budget is what a discovery call does. The product was a name-your-price: measured on
one charity film, cost to deliver $4,062–$8,435, quoted **$6,000** to a client who said
$6,000 and **$90,000** to one who said $90,000.

ADR-0065 wires the authority to `pricing.build_quote`. The budget is still read — it is
the only number that says whether a deal is worth having — but it produces a VERDICT
rather than a price, and the verdict reaches the operator instead of quietly becoming the
quote.
"""
import importlib

import pytest

from chordential_oia.capabilities import quote_band, quote_for, stated_budget_text
from chordential_oia.models import Opportunity
from chordential_oia.web.estimate import estimate_for

pytest.importorskip("fastapi")


def _opp(**kw):
    base = dict(client="The Larkspur Trust", need="Winter appeal film",
                description="Three-minute charity film with a 90-second wordless middle "
                            "section, plus a 30-second social cut.")
    base.update(kw)
    return Opportunity(**base)


# ── the price is the work, not the buyer's wallet ────────────────────────────────────
@pytest.mark.parametrize("said", [
    "$6,000 for music", "$90,000 appeal budget", "$250,000", "we have about 40k", "",
])
def test_one_job_has_one_price_whatever_the_buyer_admitted_to(said):
    """The headline defect, at the authority rather than in the engine underneath it."""
    opp, est = _opp(), estimate_for(_opp())
    assert quote_band(opp, est, ci_fields={"budget_band": said}) == quote_band(opp, est)


def test_a_generous_budget_is_no_longer_quoted_back():
    opp, est = _opp(), estimate_for(_opp())
    q = quote_for(opp, est, ci_fields={"budget_band": "$250,000"})
    assert q.total < 100_000
    assert q.budget_verdict == "above_band"


def test_a_budget_below_the_floor_never_becomes_the_quote():
    """The expensive direction. This used to take the deal at a loss with nobody
    deciding to — the quote simply WAS their number."""
    opp, est = _opp(), estimate_for(_opp())
    q = quote_for(opp, est, ci_fields={"budget_band": "$6,000 for music"})
    assert q.budget_verdict == "below_floor"
    assert q.total >= q.floor
    assert "$6,000" in q.budget_note and f"${q.floor:,}" in q.budget_note


def test_the_operator_still_outranks_the_engine():
    opp, est = _opp(), estimate_for(_opp())
    q = quote_for(opp, est, commercial_overrides={"fee_low": 26000, "fee_high": 33000})
    assert q.band == (26000, 33000) and q.overridden
    assert q.creative_fee + q.licence_fee == q.total, "an overridden document must add up"
    assert q.floor == quote_for(opp, est).floor, (
        "the floor describes what the work costs; choosing a price did not change it")


def test_an_override_below_cost_is_still_reported_as_below_cost():
    """A human may decide to go under. They may not do it without being told."""
    opp, est = _opp(), estimate_for(_opp())
    q = quote_for(opp, est, commercial_overrides={"fee_low": 900, "fee_high": 1100})
    assert q.floored, "an override under the floor stopped reporting that it was"


def test_no_estimate_means_no_number():
    assert quote_band(_opp(), None) == (None, None)
    assert quote_for(_opp(), None) is None


# ── the budget is still read, just not obeyed ────────────────────────────────────────
def test_campaign_intelligence_outranks_the_posting_for_the_reading():
    opp = _opp(budget_min=5000, budget_max=9000)
    assert stated_budget_text(opp, {"budget_band": "$18,000–$24,000"}) == "$18,000–$24,000"
    assert "5,000" in stated_budget_text(opp, {}) and "9,000" in stated_budget_text(opp, {})
    assert stated_budget_text(_opp(), {}) == ""


def test_a_deal_with_no_budget_is_not_a_verdict():
    q = quote_for(_opp(), estimate_for(_opp()))
    assert q.budget_verdict == "unknown" and q.stated_budget is None


# ── the operator is told, on the page where they decide ──────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "q.db"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    for m in ("db", "campaign_intelligence", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c, app_mod


def _deal(app_mod, budget_min=0, budget_max=0):
    from chordential_oia.models import BuyerType, MusicRequirement
    db = app_mod.db
    conn = db.connect()
    try:
        return db.insert_opportunity(conn, Opportunity(
            client="The Larkspur Trust", need="Winter appeal film",
            description="Three-minute charity film with a 90-second wordless middle "
                        "section, plus a 30-second social cut.",
            budget_min=budget_min, budget_max=budget_max,
            buyer_type=BuyerType.BRAND, music_requirement=MusicRequirement.ORIGINAL))
    finally:
        conn.close()


def test_the_deal_page_flags_a_budget_below_the_floor(client):
    """The half of the decision the operator could not previously see. It must name BOTH
    numbers — an adjective is not something you can act on."""
    c, app_mod = client
    page = c.get(f"/opportunity/{_deal(app_mod, 1000, 6000)}").text
    assert "BELOW OUR FLOOR" in page
    assert "$6,000" in page and "floor for this scope is" in page
    assert "Reduce the scope" in page or "decline" in page


def test_the_deal_page_flags_a_budget_above_the_band(client):
    """Money left on the table is worth surfacing too — quietly quoting their number was
    how it got left there."""
    c, app_mod = client
    page = c.get(f"/opportunity/{_deal(app_mod, 240000, 250000)}").text
    assert "ABOVE OUR BAND" in page
    assert "Quote the work, not their number" in page


def test_a_budget_inside_the_band_says_nothing(client):
    """A banner on every deal is a banner nobody reads."""
    c, app_mod = client
    oid = _deal(app_mod)
    lo, hi = quote_band(_opp(), estimate_for(_opp()))
    conn = app_mod.db.connect()
    try:
        conn.execute("UPDATE opportunities SET budget_min = ?, budget_max = ? WHERE id = ?",
                     (lo, hi, oid))
        conn.commit()
    finally:
        conn.close()
    page = c.get(f"/opportunity/{oid}").text
    assert "BELOW OUR FLOOR" not in page and "ABOVE OUR BAND" not in page


def test_the_flag_shows_the_derivation_not_just_a_total(client):
    """"Your price is wrong" is not actionable. "Creative X plus licence Y for these
    terms" tells the operator which lever to pull on the call."""
    c, app_mod = client
    page = c.get(f"/opportunity/{_deal(app_mod, 1000, 6000)}").text
    assert "creative $" in page and "licence $" in page
    assert "non-exclusive" in page, "the licence being priced is named"
