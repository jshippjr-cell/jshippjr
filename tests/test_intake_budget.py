"""The intake asks what a project is worth to the client.

`/start` promises *"a few details is all we need to come back with an approach and a
price range"* — and rendered no budget field. Not because the plumbing was missing: the
POST handler had always accepted `budget_text`, `promote_lead` had always run it through
`extract_budget` into `opportunities.budget_min/max`, and those columns are **leg 2 of
`capabilities.quote_band`** (ADR-0034), the one authority on what we put in front of a
buyer. The form simply never asked, so the field was empty on every real submission and
the whole chain behind it ran dry.

Measured end to end before the fix: a lead that would have said **$25,000–$40,000** was
quoted **$7,200–$15,100** — our cost model, 3.4× under, on exactly the deals that arrive
through the front door.

Capturing it then exposed the next link. `public_price_band` still ignored the budget, so
a visitor would be shown $7,200–$15,100 at intake and quoted their own $25,000–$40,000
later — a jump that reads as a bait-and-switch. ADR-0034 had deliberately left that
function alone *because intake captured no budget*; ADR-0042 retires that reasoning.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

LEAD = dict(contact_name="Dana Reed", contact_email="dana@agency.com", phone="555-0100",
            company="AURORA", project_type="Original :30 brand spot",
            description="National broadcast campaign.", timeline="6 weeks")


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "intake.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    return mod


def _submit(client, **extra):
    """Send the intake form and return the stored lead."""
    from chordential_oia.web import db

    client.post("/start", data={**LEAD, **extra})
    conn = db.connect()
    try:
        return dict(conn.execute(
            "SELECT * FROM inbound_leads ORDER BY id DESC LIMIT 1").fetchone())
    finally:
        conn.close()


def _promote(client, app_mod, lead_id):
    """Promote the lead and return the opportunity it became."""
    from chordential_oia.web import db

    client.post(f"/leads/{lead_id}/promote", follow_redirects=False)
    conn = db.connect()
    try:
        return dict(conn.execute(
            "SELECT * FROM opportunities ORDER BY id DESC LIMIT 1").fetchone())
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# The form asks
# --------------------------------------------------------------------------- #
def test_the_form_has_a_budget_field(app_mod):
    with TestClient(app_mod.app) as c:
        html = c.get("/start").text
    assert 'name="budget_text"' in html, (
        "the page promises a price range and never asks what it is worth to them")


def test_the_budget_is_optional(app_mod):
    """A required budget on a first contact costs more leads than it saves — and the
    no-budget path has to keep working."""
    with TestClient(app_mod.app) as c:
        html = c.get("/start").text
        field = html.split('name="budget_text"')[0].rsplit("<div class=\"field\"", 1)[1]
        assert "required" not in field
        lead = _submit(c, budget_text="")
    assert lead["contact_email"] == "dana@agency.com", "a budget-less lead stopped landing"


def test_the_form_says_why_it_asks(app_mod):
    with TestClient(app_mod.app) as c:
        html = c.get("/start").text
    assert "never a commitment" in html


def test_a_validation_error_does_not_eat_the_budget(app_mod):
    """Retyping a budget after a validation bounce is how a form loses a lead."""
    with TestClient(app_mod.app) as c:
        r = c.post("/start", data={**LEAD, "phone": "", "contact_linkedin": "",
                                   "budget_text": "$25,000-$40,000"})
    assert r.status_code == 400
    assert "$25,000-$40,000" in r.text


# --------------------------------------------------------------------------- #
# What they say reaches the number we quote
# --------------------------------------------------------------------------- #
def test_a_stated_budget_reaches_the_opportunity(app_mod):
    """The chain that was running dry: form → lead → extract_budget → the columns
    `quote_band` reads."""
    with TestClient(app_mod.app) as c:
        lead = _submit(c, budget_text="$25,000-$40,000")
        assert lead["budget_text"] == "$25,000-$40,000"
        opp = _promote(c, app_mod, lead["id"])
    assert (opp["budget_min"], opp["budget_max"]) == (25000.0, 40000.0)


def test_we_quote_the_budget_they_stated(app_mod):
    from chordential_oia.capabilities import quote_band
    from chordential_oia.web import db
    from chordential_oia.web.estimate import estimate_for

    with TestClient(app_mod.app) as c:
        lead = _submit(c, budget_text="$25,000-$40,000")
        opp_row = _promote(c, app_mod, lead["id"])
    conn = db.connect()
    try:
        opp = db.opportunity_from_row(
            conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_row["id"],)).fetchone())
    finally:
        conn.close()
    assert quote_band(opp, estimate_for(opp)) == (25000, 40000)


def test_the_band_shown_at_intake_matches_what_we_quote_later(app_mod):
    """The divergence capturing a budget would otherwise have created: shown our cost
    model at intake, quoted their own number later."""
    from chordential_oia.capabilities import quote_band
    from chordential_oia.web import db
    from chordential_oia.web.estimate import estimate_for

    for budget in ("$25,000-$40,000", ""):
        with TestClient(app_mod.app) as c:
            lead = _submit(c, budget_text=budget)
            shown = (lead["shown_price_low"], lead["shown_price_high"])
            opp_row = _promote(c, app_mod, lead["id"])
        conn = db.connect()
        try:
            opp = db.opportunity_from_row(conn.execute(
                "SELECT * FROM opportunities WHERE id=?", (opp_row["id"],)).fetchone())
        finally:
            conn.close()
        later = quote_band(opp, estimate_for(opp))
        assert shown[0] and shown[1], f"no band recorded for budget={budget!r}"
        assert abs(shown[0] - later[0]) <= 200 and abs(shown[1] - later[1]) <= 200, (
            f"budget={budget!r}: shown ${shown[0]:,.0f}-${shown[1]:,.0f} at intake but "
            f"quoted ${later[0]:,.0f}-${later[1]:,.0f} later")


def test_no_budget_leaves_the_public_voice_unchanged(app_mod):
    """ADR-0028's single public pricing voice still governs when nothing is stated —
    this change adds a preference, it does not replace the estimator."""
    from chordential_oia.web.public import public_price_band

    band = public_price_band("Original :30 brand spot", "National broadcast campaign.")
    assert band and band["low"] < band["high"]
    assert band == public_price_band("Original :30 brand spot",
                                     "National broadcast campaign.", "")


def test_an_unparseable_budget_falls_back_rather_than_breaking(app_mod):
    """"we're flexible" is a normal thing to type into a budget box."""
    from chordential_oia.web.public import public_price_band

    plain = public_price_band("Original :30 brand spot", "National broadcast campaign.")
    for junk in ("we're flexible", "TBD", "not sure yet", "???"):
        assert public_price_band("Original :30 brand spot",
                                 "National broadcast campaign.", junk) == plain, junk
