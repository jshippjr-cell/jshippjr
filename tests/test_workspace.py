"""The Client Workspace foundation (ADR-0018).

One durable, token-gated URL per client; contents evolve by a computed phase; the project
inherits the opportunity's workspace token so the URL survives award unchanged.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
from chordential_oia.web import workspace as ws


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "campaigns", "meeting_scheduler", "meetings_service", "workspace", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _opp(dbm, conn):
    oid = dbm.insert_opportunity(conn, Opportunity(
        client="Halcyon Creative", need="Holiday anthem", description="Campaign.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    conn.execute("UPDATE opportunities SET contact_email=?, contact_name=? WHERE id=?",
                 ("sarah@halcyon.com", "Sarah Chen", oid))
    conn.commit()
    return oid


# --------------------------------------------------------------------------- #
# The phase engine — pure mapping from signals to phase.
# --------------------------------------------------------------------------- #
def test_phase_engine_walks_the_lifecycle():
    assert ws.compute_phase({}) == ws.INTRO
    assert ws.compute_phase({"in_discovery": True}) == ws.DISCOVERY
    assert ws.compute_phase({"brief_ready": True}) == ws.BRIEF
    # brief_ready dominates a stale in_discovery signal
    assert ws.compute_phase({"in_discovery": True, "brief_ready": True}) == ws.BRIEF
    assert ws.compute_phase({"commercial_ready": True}) == ws.COMMERCIAL
    assert ws.compute_phase({"commercial_approved": True}) == ws.KICKOFF
    assert ws.compute_phase({"has_project": True}) == ws.PRODUCTION
    assert ws.compute_phase({"has_project": True, "delivered": True}) == ws.DELIVERY
    assert ws.compute_phase({"archived": True, "has_project": True}) == ws.ARCHIVE


def test_rail_marks_done_current_upcoming():
    r = ws.rail(ws.BRIEF)
    by = {s["phase"]: s["state"] for s in r}
    assert by[ws.INTRO] == "done" and by[ws.DISCOVERY] == "done"
    assert by[ws.BRIEF] == "current"
    assert by[ws.COMMERCIAL] == "upcoming" and by[ws.PRODUCTION] == "upcoming"


# --------------------------------------------------------------------------- #
# Durable token — the project inherits the opportunity's workspace token.
# --------------------------------------------------------------------------- #
def test_project_inherits_opportunity_workspace_token(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    token = app_mod.db.ensure_share_token(conn, opp_id)
    conn.close()
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as c:
        c.post(f"/opportunity/{opp_id}/project")     # award → project created
    conn = app_mod.db.connect()
    proj = app_mod.db.project_for_opp(conn, opp_id)
    # same token resolves BOTH the opp and its project — one URL across award
    assert proj["share_token"] == token
    assert app_mod.db.opportunity_by_share_token(conn, token)["id"] == opp_id
    assert app_mod.db.project_by_share_token(conn, token)["id"] == proj["id"]
    conn.close()


# --------------------------------------------------------------------------- #
# The /workspace/{token} route — resolves, computes phase, renders the shell.
# --------------------------------------------------------------------------- #
def test_workspace_url_is_stable_and_phase_advances(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    token = app_mod.db.ensure_share_token(conn, opp_id)
    conn.close()
    url = f"/workspace/{token}"
    with TestClient(app_mod.app) as c:
        # INTRO — no discovery yet
        page = c.get(url)
        assert page.status_code == 200
        assert "Welcome" in page.text and "Halcyon Creative" in page.text
        assert "Schedule your discovery call" in page.text
        # a completed discovery meeting → the SAME url now shows the Brief phase
        conn = app_mod.db.connect()
        app_mod.db.create_meeting(conn, opp_id=opp_id,
                                  start_at="2026-07-01T14:00:00+00:00", status="ingested")
        conn.close()
        page2 = c.get(url)                            # URL unchanged
        assert "Campaign Brief" in page2.text
        assert "Open your Campaign Brief" in page2.text
        # award → project; the SAME url now shows Production
        c.post(f"/opportunity/{opp_id}/project")
        page3 = c.get(url)                            # URL still unchanged
        assert "Production" in page3.text


def test_workspace_bad_token_404(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn); conn.close()
    with TestClient(app_mod.app) as c:
        assert c.get("/workspace/nope-not-a-token").status_code == 404


def test_workspace_bypasses_admin_gate(tmp_path, monkeypatch):
    """The unguessable token IS the access control — the workspace is reachable without the
    admin cookie, like first-touch and the delivery portal."""
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "sekret")
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    token = app_mod.db.ensure_share_token(conn, opp_id)
    conn.close()
    with TestClient(app_mod.app) as c:
        # an admin-gated page bounces to login without the cookie…
        assert c.get(f"/opportunity/{opp_id}",
                     follow_redirects=False).status_code in (302, 303, 307)
        # …but the workspace opens on its token alone
        assert c.get(f"/workspace/{token}").status_code == 200
