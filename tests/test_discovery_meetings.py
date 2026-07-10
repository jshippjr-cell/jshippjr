"""Discovery meetings + the Campaign Brief CTA (ADR-0014 §4/§6).

The Campaign Brief is the primary client-facing artifact and carries the discovery-call CTA;
the Opportunity page shows discovery only contextually (an "Upcoming Discovery" panel) when a
meeting exists. Scheduling ties a meeting to the opportunity; the Zoom + Recall automation
lights up behind the same routes when the seams are configured (manual/honest until then).
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def _db(tmp_path):
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "m.db"))
    dbm.init_db(conn)
    return dbm, conn


def _opp(dbm, conn):
    return dbm.insert_opportunity(conn, Opportunity(
        client="Halcyon Creative", need="Holiday anthem", description="Campaign.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))


# --------------------------------------------------------------------------- #
# The meetings model — tied to the opportunity, most-recent-live wins.
# --------------------------------------------------------------------------- #
def test_meeting_is_tied_to_the_opportunity_and_contextual(tmp_path):
    dbm, conn = _db(tmp_path)
    opp_id = _opp(dbm, conn)
    assert dbm.meeting_for_opp(conn, opp_id) is None          # none → no panel
    mid = dbm.create_meeting(conn, opp_id=opp_id, start_at="2026-07-10T14:00",
                             join_url="https://zoom.us/j/1")
    m = dbm.meeting_for_opp(conn, opp_id)
    assert m is not None and m["id"] == mid and m["opp_id"] == opp_id
    # no notetaker configured → honest 'not connected', transcript not auto-pending
    assert m["notetaker_provider"] == "" and m["transcript_capture_id"] is None
    assert m["status"] == "scheduled"
    # canceling removes it from the contextual view (record retained)
    dbm.update_meeting(conn, mid, status="canceled")
    assert dbm.meeting_for_opp(conn, opp_id) is None


# --------------------------------------------------------------------------- #
# Web — the schedule route, the contextual panel, cancel, and the Brief CTA.
# --------------------------------------------------------------------------- #
def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.delenv("CHORDENTIAL_NOTETAKER_PROVIDER", raising=False)
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def test_opportunity_shows_brief_cta_and_no_standing_discovery_widget(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}").text
        # Campaign Brief is the primary artifact button (renamed from Capabilities doc)
        assert "Campaign Brief" in page and "/capabilities" in page
        assert "Capabilities doc" not in page
        # no standing discovery widget and no meeting yet → no Upcoming Discovery panel
        assert "Connect a notetaker to enable" not in page
        assert "Upcoming Discovery" not in page


def test_operator_schedule_creates_a_meeting_and_panel_appears_then_cancels(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        # the manual "Schedule discovery" path (ADR-0016) — same engine, operator-initiated
        c.post(f"/opportunity/{opp_id}/schedule",
               data={"mode": "direct", "meeting_type": "zoom", "date": "2026-07-10",
                     "time": "14:00", "duration_min": "30", "client_email": "s@x.com"})
        page = c.get(f"/opportunity/{opp_id}").text
        assert "Upcoming Discovery" in page and "2026-07-10" in page
        assert "Notetaker off" in page                    # honest notetaker state (no Recall)
        conn = app_mod.db.connect()
        mid = app_mod.db.meeting_for_opp(conn, opp_id)["id"]; conn.close()
        c.post(f"/opportunity/{opp_id}/discovery/{mid}/cancel")
        assert "Upcoming Discovery" not in c.get(f"/opportunity/{opp_id}").text


def test_campaign_brief_ends_with_the_request_cta(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        doc = c.get(f"/opportunity/{opp_id}/capabilities").text
        assert "Campaign Brief" in doc
        assert "Request a Discovery Call" in doc          # client requests, not books (ADR-0016)
        assert "/request?k=" in doc                        # → the token-gated request form
        assert "20 minutes" in doc
