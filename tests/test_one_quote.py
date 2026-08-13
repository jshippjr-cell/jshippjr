"""One quote authority.

The launch review's finding 7 left one thread open: "the outreach cadence quoting a
different figure from the commercial engine." Pulling it found four surfaces deriving
a client quote four different ways:

* the **client's Campaign Brief** used ``capabilities._price_band`` — the estimator's
  band;
* the **client's Commercial Review** used its own private ``_quote_band`` — operator
  override → the disclosed budget → the estimator's band;
* the **pursuit checklist** printed ``estimate.cost_range`` — what production costs
  *us* — under the label "Provide an indicative quote";
* the **outreach cadence** printed ``estimate.suggested_price`` as a point figure.

On the seeded book that put the two documents the *same buyer* reads $20,000–$40,000
apart (Brightline: brief $7,200–$15,100, review $20,000–$40,000), and told the operator
to quote $4,342 to a client who had disclosed a $20,000–$40,000 budget.

ADR-0034: ``capabilities.quote_band`` is the one authority; every surface renders it.
"""

import importlib

import pytest

from chordential_oia.capabilities import (
    _price_band, build_capabilities_doc, default_toggles, quote_band, quote_phrase,
)
from chordential_oia.models import Opportunity
from chordential_oia.web import opportunity_routes
from chordential_oia.web.estimate import estimate_for
from chordential_oia.web.evaluate import evaluate

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia.web.opportunity_ops import _brief_ci_context  # noqa: E402
from chordential_oia.web.opportunity_ops import _load  # noqa: E402
from chordential_oia.web.opportunity_ops import _quote_band_for  # noqa: E402


def _opp(**kw):
    base = dict(client="Vance Athletic", need="Original :30 brand spot",
                description="National broadcast campaign.")
    base.update(kw)
    return Opportunity(**base)


# --------------------------------------------------------------------------- #
# The authority itself
# --------------------------------------------------------------------------- #
def test_the_disclosed_budget_beats_the_estimator():
    """ADR-0020: what the client told us they'd spend is what we quote to. This is the
    rule the Commercial Review already followed and the other three ignored."""
    opp = _opp(budget_min=20000, budget_max=40000)
    est = estimate_for(opp)
    assert quote_band(opp, est) == (20000, 40000)
    assert _price_band(est) != (20000, 40000), "fixture no longer proves anything"


def test_an_operator_override_beats_the_disclosed_budget():
    """The machine proposes, Jon disposes — a human price wins over every derivation."""
    opp = _opp(budget_min=20000, budget_max=40000)
    est = estimate_for(opp)
    assert quote_band(opp, est,
                      commercial_overrides={"fee_low": 26000, "fee_high": 33000}) == (26000, 33000)


def test_campaign_intelligence_beats_the_opportunity_columns():
    """CI is the source of truth (ADR-0017/0020): what the client said in the meeting
    outranks whatever the original posting listed."""
    opp = _opp(budget_min=5000, budget_max=9000)
    est = estimate_for(opp)
    assert quote_band(opp, est, ci_fields={"budget_band": "$18,000–$24,000"}) == (18000, 24000)


def test_with_nothing_discovered_it_falls_back_to_the_estimator():
    opp = _opp()
    est = estimate_for(opp)
    assert quote_band(opp, est) == _price_band(est)


def test_it_never_invents_a_number():
    """No budget, no override, no estimate → say so. Every surface's old fallback
    produced a figure regardless."""
    assert quote_band(_opp(), None) == (None, None)
    assert "TBD" in quote_phrase((None, None))
    assert "$" not in quote_phrase(None)


def test_the_quote_is_never_the_cost_range():
    """The checklist's actual defect: it labelled our production cost 'indicative
    quote'. Cost must never be what a buyer is shown."""
    opp = _opp()
    est = estimate_for(opp)
    lo, hi = quote_band(opp, est)
    assert lo > est.cost_low and hi > est.cost_high, (
        "the quote is at or below what the work costs us to make")


# --------------------------------------------------------------------------- #
# Every surface renders it — the divergence itself
# --------------------------------------------------------------------------- #
@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "quote.db"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    return mod


def _band_text(lo, hi):
    return f"${lo:,.0f} to ${hi:,.0f}"


def test_all_four_surfaces_quote_the_same_number(app_mod):
    """The headline. Two client documents and two operator surfaces, one figure —
    checked on every seeded deal that has a disclosed budget, not just one."""
    from chordential_oia.web import db

    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM opportunities WHERE qualified = 1 AND budget_max > 0"
        ).fetchall()
        assert len(rows) >= 3, "not enough seeded deals to prove agreement"
        for row in rows:
            oid = row["id"]
            _r, opp, ev = _load(conn, oid)
            qual, _scored = ev
            est = estimate_for(opp, qual=qual)
            expected = _quote_band_for(conn, row, opp, est)
            assert expected[0], f"opp {oid} resolved no quote"
            want = _band_text(*expected)

            ci_view, met = _brief_ci_context(conn, row)
            toggles = default_toggles(row["status"])
            toggles.update({"cost": True})
            doc = build_capabilities_doc(
                opp, qual, est, toggles=toggles, ci_view=ci_view, met=met,
                overrides=db.get_doc_overrides(conn, oid))
            assert (doc.price_low, doc.price_high) == expected, (
                f"opp {oid}: the CLIENT's Campaign Brief quotes something else")

            _rr, review = opportunity_routes._build_review_for_opp(conn, oid)
            assert (review.fee_low, review.fee_high) == expected, (
                f"opp {oid}: the CLIENT's Commercial Review quotes something else")

            _r2, _o2, plan = opportunity_routes._outreach_for(conn, oid)
            step = [s for s in plan.steps if "indicative quote" in s.talking_point]
            assert step and want in step[0].talking_point, (
                f"opp {oid}: the outreach cadence quotes something else")

            _r3, _o3, brief = opportunity_routes._brief_for(conn, oid)
            line = [c for c in brief.checklist if "indicative quote" in c]
            assert line and want in line[0], (
                f"opp {oid}: the pursuit checklist quotes something else")
    finally:
        conn.close()


def test_the_operators_surfaces_never_quote_our_cost(app_mod):
    """The pursuit checklist used to read 'Provide an indicative quote: $4,342–$9,018'
    — the estimate's cost range."""
    from chordential_oia.web import db

    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM opportunities WHERE qualified = 1 LIMIT 8").fetchall()
        for row in rows:
            oid = row["id"]
            _r, opp, ev = _load(conn, oid)
            est = estimate_for(opp, qual=ev[0])
            _r3, _o3, brief = opportunity_routes._brief_for(conn, oid)
            _r2, _o2, plan = opportunity_routes._outreach_for(conn, oid)
            quoting = ([c for c in brief.checklist if "indicative quote" in c]
                       + [s.talking_point for s in plan.steps
                          if "indicative quote" in s.talking_point])
            for text in quoting:
                assert est.cost_range not in text, (
                    f"opp {oid}: our production cost is being quoted to the buyer")
    finally:
        conn.close()


def _code(path):
    """Source with comment lines dropped — prose about a defect is not the defect."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_the_engines_do_not_derive_a_quote_of_their_own():
    """Structural: ``prepare`` and ``outreach`` render the band the caller resolved.
    If either reaches back into the estimate for a client figure, this returns."""
    from pathlib import Path
    import chordential_oia

    root = Path(chordential_oia.__file__).parent
    out = _code(root / "outreach.py")
    assert "estimate.suggested_price" not in out
    assert "estimate.cost_range" not in out

    # prepare keeps exactly one of each — both inside `budget_line`, the internal
    # margin read ("Estimated $X–$Y; suggested price $Z at 40% target margin"). That
    # line is honest analysis and is labelled as such. A second occurrence means a
    # cost or a point price has leaked back onto an action the operator will take.
    prep = _code(root / "prepare.py")
    assert prep.count("estimate.cost_range") == 1, (
        "our production cost is back on a pursuit-brief action")
    assert prep.count("estimate.suggested_price") == 1
    assert "target margin" in prep
    for line in prep.splitlines():
        if "quote" in line.lower():
            assert "estimate." not in line, f"a quote line reads the estimate: {line.strip()}"


# --------------------------------------------------------------------------- #
# The money surfaces — a quote the client never agreed to is worse than a wrong label
# --------------------------------------------------------------------------- #
def test_a_proposal_totals_the_quote_not_the_estimate():
    """The proposal is a client document. Its total was ``estimate.suggested_price``,
    so a generated proposal read $9,712 on a deal quoted $6,000–$10,000 — whose own
    Commercial Review had already told the client the deposit implied $8,000."""
    from chordential_oia.proposals import build_proposal

    opp = _opp(budget_min=6000, budget_max=10000)
    qual, _ = evaluate(opp)
    est = estimate_for(opp, qual=qual)
    band = quote_band(opp, est)
    quoted = build_proposal(opp, qual, est, quote_band=band)
    assert quoted.total_price == 8000
    assert quoted.deposit_amount + quoted.balance_due == quoted.total_price
    assert build_proposal(opp, qual, est).total_price == est.suggested_price, (
        "without a band the estimator's number still stands — callers wanting terms only")


def test_the_generated_proposal_and_the_review_agree_on_the_deposit(app_mod):
    """Two paths create a proposal: from an approved review (which rewrote the money
    correctly) and the project's Generate-proposal button (which did not). The client
    was told one deposit and invoiced from another."""
    from chordential_oia.proposals import build_proposal
    from chordential_oia.web import db

    conn = db.connect()
    try:
        prow = conn.execute(
            "SELECT * FROM projects WHERE opp_id IS NOT NULL ORDER BY id").fetchone()
        assert prow is not None
        oid = prow["opp_id"]
        row, opp, ev = _load(conn, oid)
        qual, _scored = ev
        est = estimate_for(opp, conn=conn, project_id=prow["id"], qual=qual)
        band = _quote_band_for(conn, row, opp, est)
        proposal = build_proposal(opp, qual, est, quote_band=band)
        _rr, review = opportunity_routes._build_review_for_opp(conn, oid)
    finally:
        conn.close()

    assert review.deposit_amount == round(proposal.deposit_amount), (
        "the generated proposal's deposit differs from the one the client approved")


def test_the_briefs_pay_deposit_sits_under_the_band_it_shows(app_mod):
    """The client brief shows a quoted band and a Pay-deposit button. The button was a
    fraction of the estimator's number, so the two disagreed on the same page."""
    from chordential_oia.proposals import DEFAULT_DEPOSIT_PCT
    from chordential_oia.web import db

    import re

    expected = {}
    conn = db.connect()
    try:
        # The Deposit block only renders at the proposal/contract stage — the statuses
        # where a client is actually being asked for money.
        rows = conn.execute(
            "SELECT * FROM opportunities WHERE qualified = 1 AND budget_max > 0 "
            "AND status IN ('Submitted','Won')"
        ).fetchall()
        for row in rows:
            _r, opp, ev = _load(conn, row["id"])
            est = estimate_for(opp, qual=ev[0])
            lo, hi = _quote_band_for(conn, row, opp, est)
            expected[row["id"]] = (lo, hi, round(((lo + hi) / 2) * DEFAULT_DEPOSIT_PCT))
    finally:
        conn.close()

    assert expected, "no seeded deal with a disclosed budget"
    checked = 0
    with TestClient(app_mod.app) as c:
        for oid, (lo, hi, want) in expected.items():
            page = c.get(f"/opportunity/{oid}/capabilities").text
            m = re.search(r"\$([\d,]+)\s*<small>deposit to begin work", page)
            if not m:
                continue                       # deposit element off at this stage
            checked += 1
            shown = int(m.group(1).replace(",", ""))
            assert abs(shown - want) <= 1, (
                f"opp {oid}: deposit ${shown:,} is not {DEFAULT_DEPOSIT_PCT:.0%} of the "
                f"${lo:,}–${hi:,} band shown on the same page (expected ${want:,})")
    assert checked, "no brief rendered a Pay-deposit element — test proves nothing"


def test_the_brief_has_one_action_list_not_three():
    """The HTML page rendered `checklist`; brief.txt rendered `response_outline` +
    `next_steps`. Same brief, two different instruction sets — and the wrong quote
    lived in all three, which is why it survived."""
    from chordential_oia.prepare import PursuitBrief

    names = {f for f in PursuitBrief.__dataclass_fields__}
    assert "response_outline" not in names
    assert "next_steps" not in names
    assert "checklist" in names


def test_brief_text_and_the_brief_page_show_the_same_steps(app_mod):
    """What the collapse buys: the export and the page can no longer disagree."""
    from chordential_oia.web import db

    conn = db.connect()
    try:
        oid = conn.execute(
            "SELECT id FROM opportunities WHERE qualified = 1 LIMIT 1").fetchone()["id"]
        _r, _o, brief = opportunity_routes._brief_for(conn, oid)
    finally:
        conn.close()

    with TestClient(app_mod.app) as c:
        text = c.get(f"/opportunity/{oid}/brief.txt").text
        page = c.get(f"/opportunity/{oid}/brief").text
    for step in brief.checklist:
        assert step in text, f"brief.txt is missing a checklist step: {step!r}"
    quote_step = [s for s in brief.checklist if "indicative quote" in s][0]
    assert quote_step.rstrip(".") in page.replace("&#34;", '"').replace("&amp;", "&")
