"""The Production OS spine (ADR-0019): Directions, the round ledger, Creative Lock, and the
computed court-state — built on the existing delivery_json machinery, no new tables.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
from chordential_oia.web import production as P
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia.web import production  # noqa: E402


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes", "campaigns",
              "commercial", "kickoff", "production", "workspace", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _project(app_mod, conn):
    oid = app_mod.db.insert_opportunity(conn, Opportunity(
        client="Halcyon Creative", need="Holiday anthem", description="Campaign.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=18000, budget_max=24000))
    pid = app_mod.db.insert_project(conn, oid, "Halcyon Creative", "Holiday anthem",
                                    18000, 24000, ["Composer"],
                                    share_token=app_mod.db.ensure_share_token(conn, oid))
    return oid, pid


# --------------------------------------------------------------------------- #
# The court-state — pure derivation, exactly one court, always.
# --------------------------------------------------------------------------- #
def test_court_state_walks_the_loop():
    # fresh project, no versions → studio, composing
    s = P.court_state(None, {})
    assert s["court"] == "studio" and s["what"] == "composing"
    assert "nothing is needed from you" in s["line"].lower()
    # a version in review → client's move
    d = {"state": "In review",
         "versions": [{"n": 1, "label": "v1 Concept", "created_at": "2026-07-08T00:00:00"}]}
    s = P.court_state(None, d)
    assert s["court"] == "client" and s["what"] == "version_ready"
    assert "v1 Concept" in s["line"]
    # changes requested → studio, revising
    d["state"] = "In production"
    s = P.court_state(None, d)
    assert s["court"] == "studio" and s["what"] == "revising"
    # a creator submission awaiting the taste gate → studio (operator disposition)
    d["pending_version"] = {"at": "2026-07-08T01:00:00"}
    d["state"] = "In review"
    s = P.court_state(None, d)
    assert s["court"] == "studio" and s["what"] == "reviewing"
    # delivered / released → scheduled: nothing owed
    assert P.court_state(None, {"state": "Delivered"})["court"] == "scheduled"
    assert P.court_state(None, {"state": "Released"})["court"] == "scheduled"


# --------------------------------------------------------------------------- #
# Directions — the creative journey, rejection reasons included.
# --------------------------------------------------------------------------- #
def test_directions_lifecycle_with_rejection_reasons(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    _oid, pid = _project(app_mod, conn)
    a = P.add_direction(conn, app_mod.db, pid, name="Warm / Human", thesis="the whistle motif")
    b = P.add_direction(conn, app_mod.db, pid, name="Epic / Cinematic")
    P.decide_direction(conn, app_mod.db, pid, b["id"], status="rejected",
                       reason="too literal for the brand")
    P.decide_direction(conn, app_mod.db, pid, a["id"], status="selected")
    delivery = app_mod.db.get_delivery(conn, pid)
    rows = P.directions(delivery)
    conn.close()
    assert [r["status"] for r in rows] == ["selected", "rejected"]
    assert rows[1]["reason"] == "too literal for the brand"   # RI raw material
    assert P.selected_direction(delivery)["thesis"] == "the whistle motif"


# --------------------------------------------------------------------------- #
# The round ledger — fed by the client's change request; post-lock stamped.
# --------------------------------------------------------------------------- #
def test_change_request_feeds_round_ledger_and_lock_stamps(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid, pid = _project(app_mod, conn)
    token = app_mod.db.get_project(conn, pid)["share_token"]
    # a version exists and is in review
    app_mod.db.update_delivery(conn, pid, "versions",
                               [{"n": 1, "label": "v1 Concept", "url": "/x.mp3",
                                 "filename": "x.mp3", "name": "x",
                                 "created_at": "2026-07-08T00:00:00"}])
    app_mod.db.update_delivery(conn, pid, "state", "In review")
    conn.close()
    with TestClient(app_mod.app) as c:
        c.post(f"/project/{pid}/review/changes",
               data={"k": token, "note": "More air in the intro",
                     "author": "Sarah Chen", "email": "sarah@halcyon.com"})
        conn = app_mod.db.connect()
        d = app_mod.db.get_delivery(conn, pid)
        assert d["revisions_used"] == 1                        # the counter (total)
        log = P.round_log(d)
        assert len(log) == 1 and log[0]["by"] == "Sarah Chen"
        assert log[0]["note"] == "More air in the intro" and log[0]["version"] == "1"
        assert log[0]["after_lock"] is False
        conn.close()
        # operator sets Creative Lock; the NEXT round is stamped after_lock
        c.post(f"/project/{pid}/creative-lock", data={"action": "set"})
        conn = app_mod.db.connect()
        app_mod.db.update_delivery(conn, pid, "state", "In review"); conn.close()
        c.post(f"/project/{pid}/review/changes",
               data={"k": token, "note": "Actually, new melody?",
                     "author": "Sarah Chen", "email": "sarah@halcyon.com"})
    conn = app_mod.db.connect()
    d = app_mod.db.get_delivery(conn, pid)
    lock = P.creative_lock(d)
    log = P.round_log(d)
    conn.close()
    assert lock and lock["version_n"] == 1
    assert log[1]["after_lock"] is True      # the scope conversation has its record


# --------------------------------------------------------------------------- #
# The workspace production view — the court question answered in concierge voice.
# --------------------------------------------------------------------------- #
def test_workspace_production_speaks_the_court(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid, pid = _project(app_mod, conn)
    token = app_mod.db.get_project(conn, pid)["share_token"]
    conn.close()
    url = f"/workspace/{token}"
    with TestClient(app_mod.app) as c:
        # composing → nothing needed from the client
        page = c.get(url).text
        assert "Nothing is needed from you" in page
        assert "composing" in page.lower()
        # a version lands in review → the client's move, with the listen CTA
        conn = app_mod.db.connect()
        app_mod.db.update_delivery(conn, pid, "versions",
                                   [{"n": 1, "label": "v1 Concept", "url": "/x.mp3",
                                     "filename": "x.mp3", "name": "x",
                                     "created_at": "2026-07-08T00:00:00"}])
        app_mod.db.update_delivery(conn, pid, "state", "In review")
        P.add_direction(conn, app_mod.db, pid, name="Warm / Human", thesis="the whistle motif")
        conn.close()
        page2 = c.get(url).text
        assert "A new version is waiting for you" in page2
        assert "Listen &amp; share your thoughts" in page2
        # The listening room is now THE room (ADR-0068): the client's durable link
        # leads into the shared surface, not a second one.
        assert f"/room/{pid}?k={token}" in page2
        # the creative journey renders — direction + thesis + version
        assert "Warm / Human" in page2 and "the whistle motif" in page2
        assert "v1 Concept" in page2


# --------------------------------------------------------------------------- #
# Operator-reported production fixes: publish→client court, approve-no-changes, Today.
# --------------------------------------------------------------------------- #
def test_publish_moves_ball_to_client_and_workspace_approve(tmp_path, monkeypatch):
    """Publishing a fresh v1 (from 'In production') must flip the court to the CLIENT — the
    workspace says 'a new version is waiting', not 'nothing needed'. And the client can approve
    with no changes straight from the workspace."""
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid, pid = _project(app_mod, conn)
    token = app_mod.db.get_project(conn, pid)["share_token"]
    # simulate a creator submission pending the taste gate, project mid-production
    app_mod.db.update_delivery(conn, pid, "state", "In production")
    app_mod.db.update_delivery(conn, pid, "pending_version",
                               {"url": "/x.mp3", "filename": "x.mp3", "orig": "x.mp3",
                                "by": "Maya Okafor", "at": "2026-07-08T00:00:00"})
    conn.close()
    with TestClient(app_mod.app) as c:
        # Today dashboard surfaces the pending review (composer waiting on the operator)
        dash = c.get("/dashboard").text
        assert "Versions to review" in dash and "Maya Okafor" in dash
        # publish → court flips to the client
        c.post(f"/project/{pid}/delivery/publish", data={"action": "publish"})
        conn = app_mod.db.connect()
        d = app_mod.db.get_delivery(conn, pid)
        court = production.court_state(app_mod.db.get_project(conn, pid), d)
        conn.close()
        assert d["state"] == "In review"
        assert court["court"] == "client" and court["what"] == "version_ready"
        # the workspace now says a version is waiting + offers approve-no-changes
        page = c.get(f"/workspace/{token}").text
        assert "A new version is waiting for you" in page
        assert "approve with no changes" in page.lower()
        assert "court.json" in page                       # the quiet live-refresh poll
        # the court signature endpoint responds
        assert c.get(f"/workspace/{token}/court.json").json()["sig"]
        # client approves with no changes from the workspace
        c.post(f"/workspace/{token}/approve-version", data={"approver_name": "Sarah Chen"})
    conn = app_mod.db.connect()
    d = app_mod.db.get_delivery(conn, pid)
    lock = production.creative_lock(d)
    conn.close()
    assert d["state"] in ("Delivered", "Approved")       # approval drove delivery
    assert lock and lock["by"] == "Sarah Chen"           # creative lock recorded, attributed
