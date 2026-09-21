"""An empty panel has six causes and used to have one symptom (ADR-0098).

`ingest_line` already diagnosed itself — provider-not-active, rejected, unmatched,
stored — and handed that diagnosis to Recall in a 200 body, which Recall discards. So a
call that produced nothing left no trace of where it stopped.

This studio has already paid once for a silent link in this exact chain. From
`recall.py`: the transcript provider was one Zoom would not let a non-host enable, so
"the bot joined every call, recorded it, finished cleanly, and produced nothing. Nothing
in our system was wrong and nothing surfaced it." These tests are the second half of
that lesson: record the outcome rather than infer it from an absence.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "c.db"))
    for m in ("db", "copilot"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import copilot, db
    conn = db.connect(); db.init_db(conn)
    yield db, copilot, conn
    conn.close()


def test_every_arrival_is_recorded_with_what_became_of_it(mod):
    db, copilot, conn = mod
    for outcome in ("stored", "unmatched", "unmatched", "rejected-token"):
        db.log_live_ingest(conn, provider="recall", outcome=outcome, bot_id="b1")
    s = db.live_ingest_summary(conn)
    assert s["total"] == 4
    assert s["by_outcome"]["unmatched"]["count"] == 2
    assert s["last_at"], "an arrival with no time on it cannot answer 'is it live now'"


def test_the_log_never_breaks_the_call_it_is_logging(mod):
    """It runs inside a webhook while somebody is talking. A diagnostic that can break
    the thing it diagnoses is worse than no diagnostic."""
    db, copilot, conn = mod
    conn.execute("DROP TABLE live_ingest_log")
    conn.commit()
    db.log_live_ingest(conn, provider="recall", outcome="stored")  # must not raise


def test_the_verdict_names_the_furthest_upstream_failure_first(mod, monkeypatch):
    """Fixing a later link while an earlier one is broken proves nothing, so the
    sentence has to point at the first break, not the last."""
    db, copilot, conn = mod
    monkeypatch.setenv("CHORDENTIAL_CALL_COPILOT", "0")
    assert "switched off" in copilot.live_health(conn, None)["verdict"]
    monkeypatch.setenv("CHORDENTIAL_CALL_COPILOT", "1")
    # copilot on, but no stream was ever requested: a token refusal is not the story
    db.log_live_ingest(conn, provider="recall", outcome="rejected-token")
    assert "No stream was ever requested" in copilot.live_health(conn, None)["verdict"]


def test_nothing_arriving_is_a_different_sentence_from_nothing_matching(mod, monkeypatch):
    from chordential_oia.meetings import CAPTURE_PROVIDER_ENV as M_ENV
    """The two failures need different fixes: re-arm the bot, versus the bot id on the
    stream is not the one we stored."""
    db, copilot, conn = mod
    monkeypatch.setenv("CHORDENTIAL_CALL_COPILOT", "1")
    monkeypatch.setenv("CHORDENTIAL_COPILOT_TOKEN", "tok")
    monkeypatch.setenv("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.test")
    monkeypatch.setenv(M_ENV, "recall")
    monkeypatch.setenv("CHORDENTIAL_RECALL_API_KEY", "k")
    import chordential_oia.meetings as M
    importlib.reload(M)
    assert M.realtime_url(), "the fixture failed to ask for a stream at all"
    meeting = {"id": 1, "opp_id": 1, "external_id": "bot_abc"}

    class Row(dict):
        def keys(self):  # sqlite3.Row-alike
            return list(super().keys())

    nothing = copilot.live_health(conn, Row(meeting))
    assert "Nothing has arrived" in nothing["verdict"], nothing["verdict"]

    db.log_live_ingest(conn, provider="recall", outcome="unmatched", bot_id="bot_other")
    mismatched = copilot.live_health(conn, Row(meeting))
    assert "none matches a meeting we originated" in mismatched["verdict"]


def test_a_working_call_says_so_with_a_number(mod, monkeypatch):
    db, copilot, conn = mod
    monkeypatch.setenv("CHORDENTIAL_CALL_COPILOT", "1")
    db.add_live_line(conn, bot_id="b", meeting_id=1, opp_id=1, at_s=1.0,
                     speaker="Jon", text="hello")
    db.log_live_ingest(conn, provider="recall", outcome="stored", bot_id="b", meeting_id=1)

    class Row(dict):
        def keys(self):
            return list(super().keys())

    h = copilot.live_health(conn, Row({"id": 1, "opp_id": 1, "external_id": "b"}))
    assert h["stored_here"] == 1
    assert "Working" in h["verdict"]


def test_the_panel_shows_it_without_being_asked(mod, monkeypatch, tmp_path):
    """It is open by default until a line has been stored, because the person who needs
    it is the one looking at a panel that has not ticked."""
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "pw")
    for m in ("db", "copilot", "opportunity_routes", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    conn = db.connect(); db.init_db(conn)
    oid = db.insert_opportunity(conn, Opportunity(
        client="Test", need="Spot", description="x", buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL, budget_min=0, budget_max=0))
    conn.close()
    jon = TestClient(app_mod.app)
    jon.cookies.set(ADMIN_COOKIE, admin_cookie_value("pw"))
    page = jon.get(f"/opportunity/{oid}/copilot").text
    assert "cop-health" in page, "the panel does not say why it is empty"
    assert "<details class=\"cop-health\" open>" in page or "cop-health\" open" in page
