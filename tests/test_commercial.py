"""The Commercial Review (ADR-0018, Phase 1) — the formal agreement, generated from Campaign
Intelligence, frozen at release, approved inside the same Workspace.

Covers: the CI projection, the operator release (freeze + version + supersede), frozen-ness
(CI changes don't move a released offer), the phase transitions (released→COMMERCIAL,
approved→KICKOFF), the inline workspace render, and the client approval audit record.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
from chordential_oia.web import commercial as C


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "campaigns", "commercial", "meeting_scheduler", "workspace", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _opp(dbm, conn):
    oid = dbm.insert_opportunity(conn, Opportunity(
        client="Halcyon Creative", need="Holiday anthem", description="National brand campaign.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=18000, budget_max=24000))
    conn.execute("UPDATE opportunities SET contact_email=?, contact_name=? WHERE id=?",
                 ("sarah@halcyon.com", "Sarah Chen", oid))
    conn.commit()
    return oid


def _seed_ci_and_met(app_mod, conn, opp_id):
    ci = app_mod.campaign_intelligence
    row = app_mod.db.get_opportunity(conn, opp_id)
    ci_id = ci.ensure_for_opportunity(conn, row)["id"]
    for facet, key, val in [
            ("direction", "campaign_objective", "A holiday anthem that owns Q4 retail"),
            ("engagement", "deliverables", ":60 anthem, :30/:15 cutdowns, full stems"),
            ("engagement", "deadline", "November 10")]:
        ci.edit_or_create(conn, ci_id, facet, key, "fact", val, actor="operator")
    app_mod.db.create_meeting(conn, opp_id=opp_id, start_at="2026-07-01T14:00:00+00:00",
                              status="ingested")
    return ci_id


# --------------------------------------------------------------------------- #
# The engine — a pure projection of CI + the estimation/proposals engines.
# --------------------------------------------------------------------------- #
def test_engine_projects_from_ci():
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.web.estimate import build_estimate
    from chordential_oia.web.evaluate import evaluate
    opp = Opportunity(client="Halcyon", need="Holiday anthem",
                      description="National brand campaign; original music.",
                      buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
                      budget_min=18000, budget_max=24000)
    qual, _ = evaluate(opp)
    disc = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or disc.team_shape, disc)
    ci = {"fields": {"campaign_objective": "Own Q4 retail", "deadline": "November 10",
                     "deliverables": ":60 + cutdowns + stems"}}
    r = C.build_commercial_review(opp, qual, est, ci, met=True)
    assert r.scope_summary == "Own Q4 retail"          # from CI
    assert r.timeline == "November 10"                 # from CI
    assert r.fee_low and r.fee_high                     # from estimation
    assert r.deposit_amount > 0 and len(r.payment_schedule) == 2
    assert any(t["title"] == "Revision philosophy" for t in r.terms)   # producer-voiced
    # round-trips for the frozen snapshot
    r2 = C.review_from_json(C.review_to_json(r))
    assert r2 is not None and r2.scope_summary == r.scope_summary
    assert len(r2.deliverables) == len(r.deliverables)


# --------------------------------------------------------------------------- #
# Release freezes the offer; re-release supersedes + bumps the version.
# --------------------------------------------------------------------------- #
def test_release_freezes_and_versions(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    ci_id = _seed_ci_and_met(app_mod, conn, opp_id); conn.close()
    with TestClient(app_mod.app) as c:
        c.post(f"/opportunity/{opp_id}/commercial/release")
        conn = app_mod.db.connect()
        rev = app_mod.db.current_commercial_review(conn, opp_id)
        assert rev["status"] == "released" and rev["version"] == 1
        frozen = C.review_from_json(rev["doc_json"])
        assert "owns Q4 retail" in frozen.scope_summary
        conn.close()
        # CI changes AFTER release …
        conn = app_mod.db.connect()
        app_mod.campaign_intelligence.edit_or_create(
            conn, ci_id, "direction", "campaign_objective", "fact", "Totally different now")
        conn.close()
        # … the released offer does NOT move (frozen)
        conn = app_mod.db.connect()
        still = C.review_from_json(app_mod.db.current_commercial_review(conn, opp_id)["doc_json"])
        assert "owns Q4 retail" in still.scope_summary
        assert "Totally different" not in still.scope_summary
        conn.close()
        # re-release supersedes v1 and captures the new CI as v2
        c.post(f"/opportunity/{opp_id}/commercial/release")
        conn = app_mod.db.connect()
        cur = app_mod.db.current_commercial_review(conn, opp_id)
        assert cur["version"] == 2
        v2 = C.review_from_json(cur["doc_json"])
        assert "Totally different" in v2.scope_summary
        # only one live offer
        live = [r for r in conn.execute(
            "SELECT * FROM commercial_reviews WHERE opp_id=? AND status='released'",
            (opp_id,)).fetchall()]
        assert len(live) == 1
        conn.close()


# --------------------------------------------------------------------------- #
# Phase transitions + the inline workspace render.
# --------------------------------------------------------------------------- #
def test_workspace_shows_commercial_then_kickoff(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    _seed_ci_and_met(app_mod, conn, opp_id)
    token = app_mod.db.ensure_share_token(conn, opp_id); conn.close()
    url = f"/workspace/{token}"
    with TestClient(app_mod.app) as c:
        # before release → still the Brief phase (brief inline, no commercial approval yet)
        pre = c.get(url).text
        assert 'class="page"' in pre and "Approve &amp; begin" not in pre and "Payment schedule" not in pre
        # operator releases → the SAME url now shows the Commercial Review inline
        c.post(f"/opportunity/{opp_id}/commercial/release")
        page = c.get(url)
        assert page.status_code == 200
        assert "Commercial Review" in page.text
        assert "Payment schedule" in page.text and "Revision philosophy" in page.text
        assert "Approve &amp; begin" in page.text            # the decision point
        # client approves → same url advances into Kickoff
        r = c.post(f"{url}/approve", data={"approver_name": "Sarah Chen",
                   "approver_email": "sarah@halcyon.com", "scope_ok": "1",
                   "pricing_ok": "1", "terms_ok": "1"}, follow_redirects=False)
        assert r.status_code == 303
        after = c.get(url)
        assert "Kickoff" in after.text
    conn = app_mod.db.connect()
    rev = app_mod.db.current_commercial_review(conn, opp_id)
    ap = app_mod.db.approval_for_opp(conn, opp_id)
    ci = app_mod.db.ci_for_opportunity(conn, opp_id)
    ev = conn.execute("SELECT * FROM campaign_intelligence_event WHERE ci_id=? AND "
                      "verb='commercial_approved'", (ci["id"],)).fetchall()
    conn.close()
    assert rev["status"] == "approved"
    # the audit record — bound to the frozen review, with the essentials captured
    assert ap is not None and ap["review_id"] == rev["id"]
    assert ap["approver_name"] == "Sarah Chen" and ap["approver_email"] == "sarah@halcyon.com"
    assert ap["scope_ok"] and ap["pricing_ok"] and ap["terms_ok"]
    assert ap["approved_at"]
    assert ev                                                 # the timeline recorded it


def test_operator_preview_renders_and_links_client(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    _seed_ci_and_met(app_mod, conn, opp_id); conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}/commercial")
        assert page.status_code == 200
        assert "Release to client" in page.text
        assert "Revision philosophy" in page.text            # the generated agreement
        # operator preview shows NO client approval form (that lives in the client workspace)
        assert "Approve &amp; begin" not in page.text
