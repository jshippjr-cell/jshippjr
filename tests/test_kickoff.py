"""Kickoff — the Production Readiness Workspace (ADR-0018, Phase 4).

The Sales→Production handoff: the client's Commercial approval creates the project (award)
and the workspace enters Kickoff; the operator confirms Start Production to reach Production.
Everything is projected from CI + the approved Review + the project; the only new state is the
project's kickoff gate. Backward compatibility: legacy won projects skip Kickoff.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
from chordential_oia.web import kickoff, workspace as ws
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia.web import campaign_intelligence  # noqa: E402


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes", "campaigns",
              "commercial", "kickoff", "meeting_scheduler", "workspace", "app"):
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


def _to_approved(app_mod, c, conn_factory, opp_id):
    """Drive an opp through discovery→release→approval so it lands in Kickoff."""
    conn = conn_factory()
    ci = campaign_intelligence
    row = app_mod.db.get_opportunity(conn, opp_id)
    ci_id = ci.ensure_for_opportunity(conn, row)["id"]
    for f, k, v in [("direction", "campaign_objective", "Own Q4 retail"),
                    ("engagement", "deliverables", ":60 + cutdowns + stems"),
                    ("engagement", "deadline", "November 10")]:
        ci.edit_or_create(conn, ci_id, f, k, "fact", v, actor="operator")
    app_mod.db.create_meeting(conn, opp_id=opp_id, start_at="2026-07-01T14:00:00+00:00",
                              status="ingested")
    token = app_mod.db.ensure_share_token(conn, opp_id)
    conn.close()
    c.post(f"/opportunity/{opp_id}/commercial/release")
    c.post(f"/workspace/{token}/approve", data={"approver_name": "Sarah Chen",
           "approver_email": "sarah@halcyon.com", "scope_ok": "1", "pricing_ok": "1",
           "terms_ok": "1"})
    return token


# --------------------------------------------------------------------------- #
# Phase engine: KICKOFF sits between approval and production.
# --------------------------------------------------------------------------- #
def test_phase_engine_kickoff_gate():
    # approved + project + not-yet-complete → KICKOFF (not PRODUCTION)
    assert ws.compute_phase({"has_project": True, "commercial_approved": True}) == ws.KICKOFF
    # operator completes kickoff → PRODUCTION
    assert ws.compute_phase({"has_project": True, "commercial_approved": True,
                             "kickoff_complete": True}) == ws.PRODUCTION
    # a legacy project with NO approved review skips Kickoff → PRODUCTION (backward compat)
    assert ws.compute_phase({"has_project": True}) == ws.PRODUCTION


# --------------------------------------------------------------------------- #
# Approval creates the project (award) and the workspace enters Kickoff.
# --------------------------------------------------------------------------- #
def test_approval_awards_project_and_enters_kickoff(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        # no project before approval
        conn = app_mod.db.connect()
        assert app_mod.db.project_for_opp(conn, opp_id) is None; conn.close()
        token = _to_approved(app_mod, c, app_mod.db.connect, opp_id)
        # approval created the project (award) …
        conn = app_mod.db.connect()
        proj = app_mod.db.project_for_opp(conn, opp_id)
        assert proj is not None
        assert proj["share_token"] == token          # inherits the workspace token
        assert proj["kickoff_completed_at"] is None   # still in Kickoff
        conn.close()
        # … and the SAME url now lands the CLIENT in the room, because approving is what
        # creates the project. The readiness view is still built — the operator reads it —
        # but it is no longer what a client is shown.
        #
        # THAT CLOSED A LEAK: the kickoff document's "Meet your team" printed
        # `talent_name` and `talent_email` on a client-facing page, which is exactly what
        # `room.CAPS` refuses a buyer — "the roster is the business, and it walks out of
        # the door with the name".
        page = c.get(f"/workspace/{token}", follow_redirects=True)
        assert "Before we start" in page.text, "the client landed with no kickoff ask"
        assert "Meet your team" not in page.text, "the room handed over the roster"
        conn2 = app_mod.db.connect()
        readiness = kickoff.build_readiness(
            conn2, app_mod.db, app_mod.db.get_opportunity(conn2, opp_id), proj,
            app_mod.db.current_commercial_review(conn2, opp_id))
        conn2.close()
        assert readiness["checklist"], "the operator's readiness view stopped being built"
        # the deposit gates production — until it's in, Start Production is a no-op
        conn = app_mod.db.connect()
        proj = app_mod.db.project_for_opp(conn, opp_id)
        c.post(f"/opportunity/{opp_id}/start-production")
        assert app_mod.db.project_for_opp(conn, opp_id)["kickoff_completed_at"] is None
        # settle the deposit → Start Production now advances the workspace to Production
        conn.execute("INSERT INTO invoices (project_id, kind, status, created_at) "
                     "VALUES (?,?,?,?)", (proj["id"], "Deposit", "paid", "x"))
        conn.commit(); conn.close()
        c.post(f"/opportunity/{opp_id}/start-production")
    conn = app_mod.db.connect()
    proj = app_mod.db.project_for_opp(conn, opp_id)
    assert proj["kickoff_completed_at"]              # gate stamped
    conn.close()


# --------------------------------------------------------------------------- #
# The readiness view + the "everything is ready" concierge state.
# --------------------------------------------------------------------------- #
def test_readiness_all_ready_when_no_client_actions(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        token = _to_approved(app_mod, c, app_mod.db.connect, opp_id)
        # TWO client actions stand after approval — the deposit and the cut the music is
        # written to. Settle both and the readiness reaches its genuine all-clear state.
        # It used to reach it with the deposit alone, which is how a client read
        # "Everything is ready" while the composer's room sat waiting on footage nobody
        # had asked them for (see test_the_client_has_something_to_do).
        conn = app_mod.db.connect()
        proj = app_mod.db.project_for_opp(conn, opp_id)
        conn.execute("INSERT INTO invoices (project_id, kind, status, created_at) "
                     "VALUES (?,?,?,?)", (proj["id"], "Deposit", "paid", "x"))
        conn.commit()
        app_mod.db.update_delivery(conn, proj["id"], "picture",
                                   {"n": 1, "orig": "cut.mp4", "at": "2026-01-01"})
        conn.close()
        # Both settled → the room asks the client for nothing. The all-clear IS the
        # absence of the ask; a room whose content is the work needs no banner saying
        # there is nothing else to do.
        page = c.get(f"/workspace/{token}", follow_redirects=True).text
    assert "Before we start" not in page, "it still asked for something already done"
    assert "Pay deposit" not in page and "Send us the cut" not in page
    # …and WHAT THEY BOUGHT still reaches them. It was on the workspace's campaign
    # summary and would have been lost in the move; the room carries it now.
    assert "Original, cleared worldwide" in page
    assert "November 10" in page                       # target delivery from CI
    assert "Original, cleared worldwide" in page      # rights from music requirement


def test_readiness_surfaces_client_action_when_deposit_awaiting(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        token = _to_approved(app_mod, c, app_mod.db.connect, opp_id)
        # an unpaid deposit invoice → the client owes an action → NOT all-ready
        conn = app_mod.db.connect()
        proj = app_mod.db.project_for_opp(conn, opp_id)
        conn.execute("INSERT INTO invoices (project_id, kind, status, created_at) "
                     "VALUES (?,?,?,?)", (proj["id"], "Deposit", "Sent", "x"))
        conn.commit(); conn.close()
        page = c.get(f"/workspace/{token}").text
    assert "Everything is ready." not in page
    assert "Send your deposit" in page
