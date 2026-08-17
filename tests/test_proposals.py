"""Proposals (Cycle 3.1) — deterministic paperwork from the estimator.

Line items come straight from the estimator; the deposit is a simple fraction of the
total. No independent pricing math lives here.

Since ADR-0034 the *total* is the **quote** — what this buyer was actually told, via
``capabilities.quote_band`` — rather than the estimator's internal suggested price.
Conflating the two let a generated proposal contradict the Commercial Review the same
client had already approved. ``build_proposal`` without a band still falls back to the
estimator, which is correct for callers that only want the terms.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.capabilities import quote_band
from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
from chordential_oia.estimation import build_estimate
from chordential_oia.proposals import DEFAULT_DEPOSIT_PCT, build_proposal
from chordential_oia.web.evaluate import evaluate


def _qual_and_estimate(opp):
    qual, _ = evaluate(opp)
    disc = qual.discipline
    est = build_estimate(opp, qual.team_shape or disc.team_shape, disc)
    return qual, est


def _sample_opp():
    return Opportunity(
        client="Acme Agency", need="Original :30 brand spot music",
        description="National campaign, original composition, orchestral.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=8000, budget_max=15000,
    )


def test_proposal_total_equals_estimator():
    """The no-band path: with no quote resolved, the estimator's number stands."""
    opp = _sample_opp()
    qual, est = _qual_and_estimate(opp)
    p = build_proposal(opp, qual, est)
    assert p.total_price == est.suggested_price          # no new pricing math
    # Line items mirror the estimate's lines exactly.
    assert [(l.role, l.hours, l.rate) for l in p.lines] == \
           [(l.role, l.hours, l.rate) for l in est.lines]


def test_deposit_and_balance_math():
    opp = _sample_opp()
    qual, est = _qual_and_estimate(opp)
    p = build_proposal(opp, qual, est)
    assert p.deposit_pct == DEFAULT_DEPOSIT_PCT
    assert p.deposit_amount == round(p.total_price * DEFAULT_DEPOSIT_PCT, 2)
    assert round(p.deposit_amount + p.balance_due, 2) == round(p.total_price, 2)


def test_render_text_is_complete():
    opp = _sample_opp()
    qual, est = _qual_and_estimate(opp)
    text = build_proposal(opp, qual, est).render_text()
    assert "PROPOSAL" in text
    assert "Total:" in text and "Deposit" in text and "Terms:" in text


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def _project_from_new_opp(client, db_mod):
    conn = db_mod.connect()
    opp_id = db_mod.insert_opportunity(conn, _sample_opp())
    conn.close()
    r = client.post(f"/opportunity/{opp_id}/project", follow_redirects=False)
    return int(r.headers["location"].split("/project/")[1])


def test_generate_and_view_proposal(ctx):
    client, db_mod = ctx
    pid = _project_from_new_opp(client, db_mod)
    # No proposal yet → page offers to generate.
    assert "Generate proposal" in client.get(f"/project/{pid}/proposal").text

    client.post(f"/project/{pid}/proposal")
    page = client.get(f"/project/{pid}/proposal")
    assert page.status_code == 200
    assert "Total" in page.text

    # ADR-0034: the stored total is the QUOTE — what this buyer was told — not the
    # estimator's internal suggestion. The two used to be conflated, so a generated
    # proposal could contradict the Commercial Review the client had already approved.
    conn = db_mod.connect()
    try:
        opp_row = db_mod.get_project(conn, pid)
        prop = db_mod.proposal_for_project(conn, pid)
    finally:
        conn.close()
    assert prop is not None
    opp = _sample_opp()
    _, est = _qual_and_estimate(opp)
    lo, hi = quote_band(opp, est)
    # This used to assert (8000, 15000) — the fixture's disclosed budget, because the
    # budget WAS the quote. That fixture is a NATIONAL ORCHESTRAL spot: $25,700 of it is
    # players and the room, and it costs $34,468 to deliver. Quoting the client's $8–15k
    # was quoting less than half of cost, on every deal shaped like this one, silently.
    # Under ADR-0065 the price derives from the work and the shortfall is reported.
    assert round(prop["total_price"], 2) == round((lo + hi) / 2, 2)
    assert lo > est.cost_high, "still quoting under what the work costs"
    from chordential_oia.capabilities import quote_for
    assert quote_for(opp, est).budget_verdict == "below_floor", (
        "a budget less than half of cost must be reported, not accepted in silence")
    # Line items still come from the estimate — the crew and cost are real.
    assert prop["deposit_amount"] + prop["balance_due"] == prop["total_price"]


def test_proposal_status_and_export(ctx):
    client, db_mod = ctx
    pid = _project_from_new_opp(client, db_mod)
    client.post(f"/project/{pid}/proposal")
    conn = db_mod.connect()
    prop_id = db_mod.proposal_for_project(conn, pid)["id"]
    conn.close()

    client.post(f"/proposal/{prop_id}/status", data={"status": "Accepted"})
    conn = db_mod.connect()
    assert db_mod.get_proposal(conn, prop_id)["status"] == "Accepted"
    conn.close()

    txt = client.get(f"/project/{pid}/proposal.txt")
    assert txt.status_code == 200
    assert "PROPOSAL" in txt.text
    assert "Acme Agency" in txt.text


def test_custom_price_override_recomputes_deposit_and_balance(ctx):
    """Hand-sold deals are priced per contract, not by the estimator — Jon can
    override the total and everything downstream (deposit, balance, invoices)
    follows the custom number."""
    client, db_mod = ctx
    pid = _project_from_new_opp(client, db_mod)
    client.post(f"/project/{pid}/proposal")
    conn = db_mod.connect()
    try:
        prop = db_mod.proposal_for_project(conn, pid)
    finally:
        conn.close()
    estimator_total = prop["total_price"]

    r = client.post(f"/proposal/{prop['id']}/price",
                    data={"total_price": "2950", "deposit_pct": "50"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/project/{pid}/proposal"

    conn = db_mod.connect()
    try:
        prop2 = db_mod.proposal_for_project(conn, pid)
    finally:
        conn.close()
    assert prop2["total_price"] == 2950.0
    assert prop2["total_price"] != estimator_total
    assert prop2["deposit_amount"] == 1475.0
    assert prop2["balance_due"] == 1475.0


def test_custom_price_flows_into_invoice_amount(ctx):
    client, db_mod = ctx
    pid = _project_from_new_opp(client, db_mod)
    client.post(f"/project/{pid}/proposal")
    conn = db_mod.connect()
    try:
        prop = db_mod.proposal_for_project(conn, pid)
    finally:
        conn.close()
    client.post(f"/proposal/{prop['id']}/price",
               data={"total_price": "2950", "deposit_pct": "50"})
    client.post(f"/project/{pid}/invoice", data={"kind": "Deposit"})
    conn = db_mod.connect()
    try:
        inv = db_mod.list_invoices(conn, pid)[0]
    finally:
        conn.close()
    assert inv["amount"] == 1475.0   # the custom deposit, not the estimator's


def test_custom_price_form_renders_on_proposal_page(ctx):
    client, db_mod = ctx
    pid = _project_from_new_opp(client, db_mod)
    client.post(f"/project/{pid}/proposal")
    page = client.get(f"/project/{pid}/proposal").text
    assert "Set custom price" in page
