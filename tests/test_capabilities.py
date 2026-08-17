"""Capabilities/proposal document — deterministic assembly + stage gating."""

import importlib

import pytest

from chordential_oia.capabilities import (
    _price_band, build_capabilities_doc, default_toggles, quote_band,
)
from chordential_oia.models import MusicDiscipline, Opportunity
from chordential_oia.web.estimate import build_estimate
from chordential_oia.web.evaluate import evaluate


def _doc_opp():
    return Opportunity(
        client="Acme Agency", need="Original :30 brand spot music",
        description="Original composition for a national TV spot. Budget: $12,000.",
        budget_min=12000, budget_max=12000,
    )


def _doc(status, **override):
    opp = _doc_opp()
    qual, _ = evaluate(opp)
    disc = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or disc.team_shape, disc)
    toggles = default_toggles(status)
    toggles.update(override)
    return build_capabilities_doc(opp, qual, est, toggles=toggles), est


def test_discovery_hides_cost_and_terms():
    doc, _ = _doc("New")
    assert doc.stage == "discovery"
    assert doc.show_cost is False and doc.price_low is None
    assert doc.show_terms is False and doc.terms == []
    assert doc.show_docusign is False
    # the always-on sections are present
    assert doc.value_prop and doc.understanding and doc.team


def test_proposal_stage_shows_price_band_and_terms():
    doc, est = _doc("Submitted")
    assert doc.stage == "proposal"
    assert doc.show_cost is True
    # ADR-0034: the band the CLIENT sees is the quote authority, not the estimator's
    # own band. This assertion used to read ``== _price_band(est)`` — which is exactly
    # how the brief came to quote $7,200–$15,100 to a client the Commercial Review
    # quoted $20,000–$40,000. That the authority is rendered is the durable claim.
    assert (doc.price_low, doc.price_high) == quote_band(_doc_opp(), est)
    # It used to also pin (12000, 12000) — the fixture's disclosed budget, back when the
    # budget WAS the quote (ADR-0065 ended that). A hardcoded figure here only ever
    # restated the line above in a form that breaks when the price legitimately moves.
    assert doc.price_low > 0
    assert doc.price_low <= doc.price_high
    assert doc.show_terms is True and len(doc.terms) > 0
    assert doc.show_docusign is False


def test_contract_stage_adds_terms_and_docusign():
    doc, _ = _doc("Won")
    assert doc.stage == "contract"
    assert doc.show_terms is True and doc.show_docusign is True


def test_brief_does_not_autoinject_placeholder_reels():
    # The client-facing brief must not fabricate "relevant work" — the auto
    # placeholder sample reels (e.g. the national-brand anthem) were removed;
    # the section is now driven only by operator-curated tracks.
    doc, _ = _doc("New")
    assert doc.examples == []


def test_manual_toggle_overrides_stage_default():
    # Submitted defaults cost ON; explicitly turning it off must win.
    doc, _ = _doc("Submitted", cost=False)
    assert doc.show_cost is False and doc.price_low is None


# --- route smoke test (keeps the tabbed app wiring honest) ---
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c


def test_capabilities_route_renders_and_toggles(client):
    page = client.get("/opportunity/1/capabilities")
    assert page.status_code == 200
    assert "Campaign Brief" in page.text and "Save as PDF" in page.text
    # The toggle bar drives each section explicitly (independent of stage default).
    off = client.get("/opportunity/1/capabilities?submitted=1&examples=1")  # cost unchecked
    assert "Indicative investment" not in off.text
    on = client.get("/opportunity/1/capabilities?submitted=1&cost=1&examples=1")
    assert "Indicative investment" in on.text
