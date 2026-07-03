"""Client requests, operator schedules (ADR-0016).

The Campaign Brief lets a client REQUEST a call (creating a Discovery Request, scheduling
nothing); the operator reviews it and drives the one Meeting Scheduler (Zoom or Phone). The
manual "Schedule discovery" path uses the same engine. Phone never arms Recall.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "campaigns", "meeting_scheduler", "meetings_service", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _opp(dbm, conn, email="sarah@halcyon.com"):
    oid = dbm.insert_opportunity(conn, Opportunity(
        client="Halcyon Creative", need="Holiday anthem", description="Campaign.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    if email:
        conn.execute("UPDATE opportunities SET contact_email=?, contact_name=? WHERE id=?",
                     (email, "Sarah Chen", oid))
        conn.commit()
    return oid


# --------------------------------------------------------------------------- #
# Client REQUEST — token-gated, prefilled, schedules nothing.
# --------------------------------------------------------------------------- #
def test_request_form_is_token_gated_and_prefilled(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    token = app_mod.db.ensure_share_token(conn, opp_id); conn.close()
    with TestClient(app_mod.app) as c:
        assert c.get(f"/opportunity/{opp_id}/request?k=bad").status_code == 404
        page = c.get(f"/opportunity/{opp_id}/request?k={token}")
        assert page.status_code == 200
        assert "Request a discovery call" in page.text
        assert "sarah@halcyon.com" in page.text          # email prefilled from the opp
        assert "Zoom" in page.text and "Phone" in page.text


def test_client_request_creates_a_record_and_schedules_nothing(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    token = app_mod.db.ensure_share_token(conn, opp_id); conn.close()
    with TestClient(app_mod.app) as c:
        r = c.post(f"/opportunity/{opp_id}/request", follow_redirects=False,
                   data={"k": token, "name": "Sarah Chen", "email": "sarah@halcyon.com",
                         "company": "Halcyon", "preferred_type": "phone",
                         "message": "mornings are best"})
        assert r.status_code == 303 and "done=1" in r.headers["location"]
        conn = app_mod.db.connect()
        reqs = app_mod.db.list_discovery_requests(conn, opp_id)
        assert len(reqs) == 1 and reqs[0]["status"] == "new"       # nothing scheduled yet
        assert reqs[0]["preferred_type"] == "phone" and reqs[0]["name"] == "Sarah Chen"
        # no meeting exists — the request is only an ask (machine proposes, human disposes)
        assert app_mod.db.meeting_for_opp(conn, opp_id) is None
        conn.close()
        # the opportunity surfaces the pending request for the operator
        assert "Discovery requests" in c.get(f"/opportunity/{opp_id}").text


# --------------------------------------------------------------------------- #
# Operator SCHEDULE — from a request, and manually. Phone vs Zoom.
# --------------------------------------------------------------------------- #
def test_accepting_a_request_schedules_it_and_closes_the_request(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    rid = app_mod.db.create_discovery_request(conn, opp_id=opp_id, name="Sarah",
                                              email="s@x.com", preferred_type="phone")
    conn.close()
    with TestClient(app_mod.app) as c:
        # the scheduler form prefills from the request
        form = c.get(f"/opportunity/{opp_id}/schedule?req={rid}").text
        assert "From" in form and "Sarah" in form
        # schedule it as a PHONE call → meeting created, request closed, no Recall
        c.post(f"/opportunity/{opp_id}/schedule",
               data={"meeting_type": "phone", "date": "2026-07-12", "time": "10:00",
                     "duration_min": "30", "client_name": "Sarah", "client_email": "s@x.com",
                     "request_id": str(rid)})
        conn = app_mod.db.connect()
        try:
            m = app_mod.db.meeting_for_opp(conn, opp_id)
            assert m is not None and m["meeting_type"] == "phone"
            assert m["initiated_by"] == "client_request" and m["request_id"] == rid
            assert (m["notetaker_provider"] or "") == ""       # phone never arms Recall
            assert app_mod.db.get_discovery_request(conn, rid)["status"] == "scheduled"
        finally:
            conn.close()


def test_pasted_zoom_link_is_used_without_the_zoom_api(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        # operator pastes their Personal Meeting Room link — no Zoom provider needed; Recall
        # (when configured) can still join it. The Zoom API is optional (ADR-0016 shortcut).
        c.post(f"/opportunity/{opp_id}/schedule",
               data={"meeting_type": "zoom", "date": "2026-07-14", "time": "10:00",
                     "join_url": "https://zoom.us/j/MYPERSONALROOM", "client_email": "s@x.com"})
        conn = app_mod.db.connect()
        try:
            m = app_mod.db.meeting_for_opp(conn, opp_id)
            assert m["join_url"] == "https://zoom.us/j/MYPERSONALROOM" and m["provider"] == "zoom"
        finally:
            conn.close()


def test_manual_schedule_uses_the_same_engine_without_a_request(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        c.post(f"/opportunity/{opp_id}/schedule",
               data={"meeting_type": "zoom", "date": "2026-07-13", "time": "11:00",
                     "duration_min": "30", "client_email": "ref@x.com"})
        conn = app_mod.db.connect()
        try:
            m = app_mod.db.meeting_for_opp(conn, opp_id)
            assert m["meeting_type"] == "zoom" and m["initiated_by"] == "operator"
            assert m["request_id"] is None
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Client MANAGE — token-gated reschedule / cancel.
# --------------------------------------------------------------------------- #
def test_client_manage_link_cancels_the_call(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    mid = app_mod.db.create_meeting(conn, opp_id=opp_id, meeting_type="zoom",
                                    client_email="s@x.com", manage_token="mtok",
                                    start_at="2026-07-12T10:00:00+00:00", status="scheduled")
    conn.close()
    with TestClient(app_mod.app) as c:
        assert c.get(f"/meeting/{mid}/manage?k=wrong").status_code == 404
        assert c.get(f"/meeting/{mid}/manage?k=mtok").status_code == 200
        c.post(f"/meeting/{mid}/manage", data={"k": "mtok", "action": "cancel"})
        conn = app_mod.db.connect()
        assert app_mod.db.get_meeting(conn, mid)["status"] == "canceled"
        conn.close()
