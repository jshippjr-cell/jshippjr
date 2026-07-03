"""The Meeting domain + provider seams (ADR-0015).

A Meeting is the business object; Zoom and Recall are swappable implementations. Everything
downstream (Campaign Intake → Campaign Intelligence) consumes a Meeting + a normalized
Transcript, never a provider event. These tests prove the abstraction end to end with a fake
capture provider — no credentials, no network.
"""
import importlib
import json

import pytest

from chordential_oia import meetings as M
from chordential_oia.models import BuyerType, MusicRequirement, Opportunity

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


# --------------------------------------------------------------------------- #
# The seams — null by default, provider-agnostic normalization.
# --------------------------------------------------------------------------- #
def test_providers_are_null_by_default(monkeypatch):
    monkeypatch.delenv("CHORDENTIAL_MEETING_PROVIDER", raising=False)
    monkeypatch.delenv("CHORDENTIAL_NOTETAKER_PROVIDER", raising=False)
    assert M.get_meeting_provider().name == "manual"
    assert M.get_capture_provider().name == "null"
    assert M.capture_configured() is False
    # a null capture never invents a transcript
    assert M.get_capture_provider().fetch_transcript("x") is None


def test_recall_webhook_normalizes_to_a_meeting_event(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_NOTETAKER_PROVIDER", "recall")
    monkeypatch.delenv("CHORDENTIAL_RECALL_WEBHOOK_SECRET", raising=False)  # no sig in this test
    cp = M.get_capture_provider()
    assert cp.name == "recall" and M.capture_configured()
    body = json.dumps({"event": "transcript.done", "id": "evt1", "data": {
        "bot_id": "bot-123",
        "transcript": [{"speaker": "Sarah Chen", "text": "our budget is around $20,000",
                        "start_time": 12, "end_time": 15}]}}).encode()
    ev = cp.parse_webhook({}, body)
    # the provider payload is normalized into a domain event + transcript
    assert ev.type == M.EV_TRANSCRIPT_READY and ev.external_ref == "bot-123"
    assert "20,000" in ev.transcript.text and ev.transcript.speakers == ["Sarah Chen"]


# --------------------------------------------------------------------------- #
# The boundary — ingest_transcript consumes a Meeting + Transcript (no provider).
# --------------------------------------------------------------------------- #
def _opp_and_meeting(dbm, conn):
    opp_id = dbm.insert_opportunity(conn, Opportunity(
        client="Halcyon Creative", need="Holiday anthem", description="Campaign.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    mid = dbm.create_meeting(conn, opp_id=opp_id, start_at="2026-07-10T14:00",
                             join_url="https://zoom.us/j/1")
    return opp_id, dbm.get_meeting(conn, mid)


def test_ingest_transcript_enriches_ci_and_marks_the_meeting(tmp_path):
    from chordential_oia.web import db as dbm
    from chordential_oia.web import campaign_intake as intake
    conn = dbm.connect(str(tmp_path / "m.db")); dbm.init_db(conn)
    opp_id, meeting = _opp_and_meeting(dbm, conn)
    transcript = M.Transcript(
        text=("Discovery call with Halcyon. Budget is $18,000 to $24,000. Need it by "
              "November. :60 anthem plus stems. Sarah Chen, the creative director, approves."),
        speakers=["Sarah Chen", "Jon"], duration_s=1920, provider="recall", external_ref="bot-9")
    summary = intake.ingest_transcript(conn, meeting, transcript)
    # CI enriched via the discovery_call lane, sourced to a capture citing the transcript
    fields = {(f["facet"], f["key"]): f for f in dbm.list_ci_fields(conn, summary["ci_id"])}
    assert fields[("engagement", "budget_band")]["value"].startswith("$")
    cap = dbm.get_capture(conn, summary["capture_id"])
    assert cap["lane"] == "discovery_call" and cap["provenance_source"] == "discovery_call"
    assert cap["external_ref"] == "bot-9"                    # the raw-evidence provider ref
    assert "Sarah Chen" in cap["metadata_json"]              # speaker metadata carried
    # the meeting advanced to ingested and links the capture (raw evidence)
    m2 = dbm.get_meeting(conn, meeting["id"])
    assert m2["status"] == "ingested" and m2["transcript_capture_id"] == summary["capture_id"]


# --------------------------------------------------------------------------- #
# End to end — a provider webhook drives the whole chain (fake Recall, no creds).
# --------------------------------------------------------------------------- #
def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.setenv("CHORDENTIAL_NOTETAKER_PROVIDER", "recall")
    monkeypatch.delenv("CHORDENTIAL_RECALL_WEBHOOK_SECRET", raising=False)
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "campaigns", "meetings_service", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def test_capture_webhook_drives_meeting_to_ci_end_to_end(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = app_mod.db.insert_opportunity(conn, Opportunity(
        client="Halcyon Creative", need="Holiday anthem", description="Campaign.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    # a scheduled meeting with a known capture bot id (as if Recall had been armed)
    mid = app_mod.db.create_meeting(conn, opp_id=opp_id, join_url="https://zoom.us/j/1",
                                    provider="zoom", notetaker_provider="recall",
                                    status="bot_invited")
    app_mod.db.update_meeting(conn, mid, bot_id="bot-777")
    conn.close()
    with TestClient(app_mod.app) as c:
        # the capture webhook is a PUBLIC surface (no admin login) — the signature is the gate
        r = c.post("/webhooks/capture/recall", content=json.dumps({
            "event": "transcript.done", "id": "evt-1", "data": {
                "bot_id": "bot-777",
                "transcript": [
                    {"speaker": "Sarah", "text": "Budget is $30,000 to $40,000.", "start_time": 5, "end_time": 8},
                    {"speaker": "Sarah", "text": "We need it by November, a :60 anthem plus stems.", "start_time": 9, "end_time": 13}]}}))
        assert r.status_code == 200 and r.json().get("ingested") is True
        # the meeting ingested, and CI on the opportunity was enriched via the Meeting
        conn = app_mod.db.connect()
        try:
            m = app_mod.db.get_meeting(conn, mid)
            assert m["status"] == "ingested"
            ci_row = app_mod.db.ci_for_opportunity(conn, opp_id)
            fields = {(f["facet"], f["key"]): f for f in app_mod.db.list_ci_fields(conn, ci_row["id"])}
            assert "30,000" in fields[("engagement", "budget_band")]["value"]
            # the budget wrote back to the opportunity (downstream consumes, ADR-0013)
            assert app_mod.db.get_opportunity(conn, opp_id)["budget_min"] == 30000
        finally:
            conn.close()
        # idempotent — a re-delivered webhook does not double-ingest
        r2 = c.post("/webhooks/capture/recall", content=json.dumps({
            "event": "transcript.done", "id": "evt-1",
            "data": {"bot_id": "bot-777", "transcript": [{"speaker": "x", "text": "again", "start_time": 0, "end_time": 1}]}}))
        assert r2.json().get("duplicate") is True


def test_capture_webhook_is_public_but_unmatched_bot_is_ignored(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    with TestClient(app_mod.app) as c:
        # a bot we never originated → acknowledged but not acted on (no guessing)
        r = c.post("/webhooks/capture/recall", content=json.dumps({
            "event": "transcript.done", "data": {"bot_id": "unknown-bot", "transcript": []}}))
        assert r.status_code == 200 and r.json().get("unmatched") is True
