"""Quoting one number, on purpose.

    "if we collected the information from the discovery call for their needs. Why is there
     still a range being presented in the discovery summary? why not a firm number?"
                                                              — the operator, 2026-08-27

Because the range was never about the client. Discovery can close every licence lever —
media, territory, term, exclusivity all stated, no `assumed` badge left — and the band does
not move by a dollar, because it describes what we do not know about OURSELVES. The
estimate is hours × rate priors, and `estimation.BAND_SPREAD` says so in as many words:
"wide on purpose (uncalibrated)". No question you can ask a client narrows it.

Which exposed the real flaw the question was pointing at: the band is a FIXED ±17.5%
whatever discovery captured, so a fully-discovered deal wears exactly the width of an
undiscovered one. The number was not communicating confidence; it was a constant dressed as
one.

There is no honest arithmetic that turns it into one figure. There is a decision: the
operator absorbing the variance instead of showing it. That is a person's call (ADR-0033 —
the machine proposes), so it is a button.
"""
import importlib
import re

import pytest


@pytest.fixture()
def doc(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    c.post("/opportunity/1/doc/toggle", data={"cost": "1"}, follow_redirects=True)
    return c, db


def _price(html):
    m = re.search(r'class="price">(.*?)</div>', html, re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""


def _edit(c):
    return c.get("/opportunity/1/capabilities?edit=1").text


# ── why the band cannot close itself ────────────────────────────────────────────────
def test_answering_every_licence_question_does_not_narrow_the_band():
    """The evidence for the whole feature. If this ever stops being true — if the spread
    learns to respond to how much is stated — a firm quote becomes a smaller decision and
    this test should be revisited rather than deleted quietly."""
    from chordential_oia.pricing import (LicenceTerms, build_quote, licence_from_ci,
                                         reference_estimate)
    est = reference_estimate(9000)
    nothing = build_quote(est, LicenceTerms())
    everything = build_quote(est, licence_from_ci({
        "media": "all media including cinema", "territory": "worldwide",
        "license_term": "1 year", "exclusivity": "fully exclusive"}))
    assert not everything.licence_basis.count("assumed"), "the licence is fully stated"
    width = lambda q: (q.high - q.low) / q.total          # noqa: E731
    assert abs(width(nothing) - width(everything)) < 1e-9, (
        "the band now responds to evidence; the firm-quote rationale has changed")


def test_the_band_width_is_the_uncalibrated_estimate_saying_so():
    from chordential_oia.estimation import BAND_SPREAD
    from chordential_oia.pricing import build_quote, reference_estimate
    q = build_quote(reference_estimate(9000))
    assert abs((q.high - q.low) / q.total - BAND_SPREAD) < 0.01


# ── the control ─────────────────────────────────────────────────────────────────────
def test_pinning_a_number_replaces_the_band_with_it(doc):
    c, _db = doc
    assert " to " in _price(_edit(c)), "started firm; nothing to pin"
    c.post("/opportunity/1/doc/firm-fee", data={"fee": "26,500"}, follow_redirects=False)
    price = _price(_edit(c))
    assert price.startswith("$26,500")
    assert " to " not in price


def test_a_firm_number_stops_calling_itself_a_ballpark(doc):
    """The caption is part of the claim. A figure the operator committed to, still labelled
    "ballpark, firmed up after a scoping call", invites the negotiation the commitment was
    made to end."""
    c, _db = doc
    assert "ballpark" in _price(_edit(c))
    c.post("/opportunity/1/doc/firm-fee", data={"fee": "26500"}, follow_redirects=False)
    price = _price(_edit(c))
    assert "ballpark" not in price
    assert "fixed for the scope described above" in price


def test_the_client_sees_the_firm_number_too(doc):
    """It is the same document. A price pinned for the operator's benefit and not the
    client's would be a note to self."""
    c, _db = doc
    c.post("/opportunity/1/doc/firm-fee", data={"fee": "26500"}, follow_redirects=False)
    assert _price(c.get("/opportunity/1/capabilities").text).startswith("$26,500")


def test_it_can_be_let_back_to_the_band(doc):
    """A commitment you cannot withdraw before sending it is a trap, not a decision."""
    c, _db = doc
    before = _price(_edit(c))
    c.post("/opportunity/1/doc/firm-fee", data={"fee": "26500"}, follow_redirects=False)
    c.post("/opportunity/1/doc/firm-fee", data={"release": "1"}, follow_redirects=False)
    assert _price(_edit(c)) == before


def test_the_control_shows_which_state_it_is_in(doc):
    c, _db = doc
    page = _edit(c)
    assert 'name="fee"' in page and "Quoted firm at" not in page
    c.post("/opportunity/1/doc/firm-fee", data={"fee": "26500"}, follow_redirects=False)
    page = _edit(c)
    assert "Quoted firm at $26,500" in page
    assert 'name="release"' in page


def test_the_control_is_ours_and_not_the_clients(doc):
    c, _db = doc
    assert "firm-row" in _edit(c)
    assert "firm-row" not in c.get("/opportunity/1/capabilities").text


@pytest.mark.parametrize("bad", ["", "   ", "abc", "0", "-500"])
def test_a_number_that_is_not_a_number_pins_nothing(doc, bad):
    c, _db = doc
    before = _price(_edit(c))
    c.post("/opportunity/1/doc/firm-fee", data={"fee": bad}, follow_redirects=False)
    assert _price(_edit(c)) == before


def test_it_is_stored_where_the_commercial_review_already_looks(doc):
    """ONE place a price can be pinned. A second would be a second price, and the first day
    they disagreed would be a day nobody noticed — the failure ADR-0034 exists to prevent,
    where the brief and the Review quoted the same buyer two different bands."""
    c, db = doc
    c.post("/opportunity/1/doc/firm-fee", data={"fee": "26500"}, follow_redirects=False)
    conn = db.connect()
    try:
        ov = db.get_doc_overrides(conn, 1).get("commercial") or {}
    finally:
        conn.close()
    assert ov.get("fee_low") == ov.get("fee_high") == 26500
    # …and `quote_band` honours that blob as tier 1, proven through the rendered document,
    # which is the thing a client actually reads.
    assert _price(c.get("/opportunity/1/capabilities").text).startswith("$26,500")


def test_the_rail_says_what_pinning_actually_means(doc):
    """Not a calculation. The operator is taking the variance rather than showing it, and
    the control should not imply the system got more certain."""
    c, _db = doc
    page = _edit(c)
    assert "You take the variance instead of showing it." in page
