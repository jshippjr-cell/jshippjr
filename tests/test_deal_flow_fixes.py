"""Operator-reported deal-flow fixes: pricing from the discovered budget, pipeline
auto-advance, editable commercial price, and email URL linkification.
"""
import importlib

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.setenv("CHORDENTIAL_INTAKE_LLM", "0")
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "commercial", "campaigns", "kickoff", "production", "next_action", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _opp(app_mod, conn, budget="$30,000"):
    oid = app_mod.db.insert_opportunity(conn, Opportunity(
        client="Medtech", need="Product launch campaign", description="x",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    conn.execute("UPDATE opportunities SET contact_email=?, contact_name=? WHERE id=?",
                 ("buyer@medtech.com", "Freddy", oid)); conn.commit()
    row = app_mod.db.get_opportunity(conn, oid)
    cid = app_mod.campaign_intelligence.ensure_for_opportunity(conn, row)["id"]
    app_mod.campaign_intelligence.edit_or_create(conn, cid, "engagement", "budget_band",
                                                 "fact", budget, actor="operator")
    return oid


# `_build_review_for_opp` is an /opportunity-only helper and travelled with those
# routes when ADR-0044 moved them out of app.py.
from chordential_oia.web import opportunity_routes  # noqa: E402


def test_commercial_pricing_follows_discovered_budget(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = _opp(app_mod, conn, "$30,000")
    _row, review = opportunity_routes._build_review_for_opp(conn, oid)
    conn.close()
    # the quote reflects the $30k budget, NOT the estimator's low cost band
    assert review.fee_low == 30000 and review.fee_high == 30000
    assert review.deposit_amount == 15000            # 50% of the quoted band


def test_commercial_price_is_editable(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = _opp(app_mod, conn, "$30,000"); conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{oid}/commercial").text
        # The edit affordance grew from price-only to the whole agreement (walkthrough:
        # "everything needs to be editable before release, not just the price").
        assert "Edit this agreement before releasing" in page
        c.post(f"/opportunity/{oid}/commercial/edit",
               data={"fee_low": "40000", "fee_high": "48000", "deposit_pct": "40"})
    conn = app_mod.db.connect()
    _row, review = opportunity_routes._build_review_for_opp(conn, oid)
    conn.close()
    assert review.fee_low == 40000 and review.fee_high == 48000        # override wins
    assert abs(review.deposit_pct - 0.40) < 1e-6
    assert review.deposit_amount == int((40000 + 48000) / 2 * 0.40)


def test_pipeline_status_auto_advances(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = _opp(app_mod, conn)
    # discovery happened → status should reconcile forward off "New"
    app_mod.db.create_meeting(conn, opp_id=oid, start_at="2026-07-01T14:00:00+00:00",
                              status="ingested")
    token = app_mod.db.ensure_share_token(conn, oid); conn.close()
    with TestClient(app_mod.app) as c:
        c.get(f"/opportunity/{oid}")                 # self-heal on view
        conn = app_mod.db.connect()
        assert app_mod.db.get_opportunity(conn, oid)["status"] == "Pursuing"  # Reaching out
        conn.close()
        # release the proposal → Submitted (Proposal out)
        c.post(f"/opportunity/{oid}/commercial/release")
        conn = app_mod.db.connect()
        assert app_mod.db.get_opportunity(conn, oid)["status"] == "Submitted"
        conn.close()
        # client approves → Won
        c.post(f"/workspace/{token}/approve",
               data={"approver_name": "Freddy", "approver_email": "buyer@medtech.com",
                     "scope_ok": "1", "pricing_ok": "1", "timeline_ok": "1", "terms_ok": "1"})
    conn = app_mod.db.connect()
    assert app_mod.db.get_opportunity(conn, oid)["status"] == "Won"
    conn.close()


def test_email_html_linkifies_urls():
    from chordential_oia import mailer
    html = mailer.branded_html("https://chordential.com",
                               "Open your workspace:\nhttps://chordential.com/workspace/abc123")
    # the bare URL became a real clickable <a href> (mobile clients need this)
    assert '<a href="https://chordential.com/workspace/abc123"' in html
    assert 'target="_blank"' in html
