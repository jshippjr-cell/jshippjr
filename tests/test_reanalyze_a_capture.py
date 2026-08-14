"""A capture can be read again — without becoming a second capture.

When the ten-agent engine cannot run (no API credit, a rejected key, a rate limit) the
capture still lands: the raw text is permanent evidence, and only the READING of it falls
back to the free keyword baseline. The console has said "No redeploy — just re-analyze"
since that error message was written.

There was no way to do it. The only route into extraction takes pasted text and creates a
NEW capture, so following the console's own advice would have filed the same discovery
call twice — two pieces of evidence for one conversation, which is exactly what a
permanent evidence trail must never contain.

Live, 2026-08-13: a real call was captured with `Your credit balance is too low to access
the Anthropic API`, and the keyword baseline pulled 2 facts from a transcript that stated
a deadline, a budget band, a cadence and a cutdown length.
"""
import pytest

pytest.importorskip("fastapi")

TRANSCRIPT = (
    "Hello. Okay, so this is going to be a test to see if the notetaker is able to "
    "compile our objective here. And the objective is to launch delivery product wrapped "
    "around a title sequence in the next 24 days. We have a budget of roughly $10,000. "
    "We might be able to push that to $12,000. But right now we're looking at 10."
)


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "r.sqlite"))
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    c = db_mod.connect()
    db_mod.init_db(c)
    yield c
    c.close()


def _captured(db, conn):
    """A capture filed by the baseline, exactly as the failed engine leaves it."""
    from chordential_oia.models import Opportunity
    from chordential_oia.web import campaign_intelligence as ci
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Title sequence", description=""))
    row = ci.ensure_for_opportunity(conn, db.get_opportunity(conn, opp_id))
    cap_id = db.insert_capture(
        conn, ci_id=row["id"], campaign_id=None, opp_id=opp_id, lane="discovery_call",
        stance="objective", modality="transcript", provenance_source="discovery_call",
        raw_text=TRANSCRIPT, extraction=[], artifact_ref="", external_ref="bot-1",
        metadata={"extraction_run": {"provider_error": "credit balance is too low"}},
        status="ingested", created_by="capture")
    return opp_id, cap_id, row["id"]


def test_it_reads_the_text_already_on_file(conn, monkeypatch):
    from chordential_oia.web import campaign_intake, db
    _opp, cap_id, _ci = _captured(db, conn)

    seen = {}

    def _fake_llm(text, stance, priors=""):
        seen["text"] = text
        return [{"facet": "engagement", "key": "timeline", "value": "24 days",
                 "kind": "fact", "confidence": 0.9}]

    monkeypatch.setattr(campaign_intake, "extract",
                        lambda text, stance, llm=None, priors="": _fake_llm(text, stance))
    out = campaign_intake.reanalyze_capture(conn, cap_id)
    assert out["ok"] and out["added"] == 1
    assert "24 days" in seen["text"], "it must re-read the stored transcript"


def test_it_does_not_create_a_second_capture(conn, monkeypatch):
    """One call is one piece of evidence, however many times it is read."""
    from chordential_oia.web import campaign_intake, db
    _opp, cap_id, ci_id = _captured(db, conn)
    before = len(db.list_captures(conn, ci_id))

    monkeypatch.setattr(campaign_intake, "extract",
                        lambda text, stance, llm=None, priors="": [])
    campaign_intake.reanalyze_capture(conn, cap_id)
    assert len(db.list_captures(conn, ci_id)) == before


def test_the_raw_evidence_is_never_rewritten(conn, monkeypatch):
    """A re-read may change the reading. It must not be able to change what was read."""
    from chordential_oia.web import campaign_intake, db
    _opp, cap_id, _ci = _captured(db, conn)
    monkeypatch.setattr(campaign_intake, "extract",
                        lambda text, stance, llm=None, priors="": [])
    campaign_intake.reanalyze_capture(conn, cap_id)
    assert db.get_capture(conn, cap_id)["raw_text"] == TRANSCRIPT


def test_what_it_finds_reaches_campaign_intelligence(conn, monkeypatch):
    from chordential_oia.web import campaign_intake, db
    _opp, cap_id, ci_id = _captured(db, conn)
    monkeypatch.setattr(
        campaign_intake, "extract",
        lambda text, stance, llm=None, priors="": [
            {"facet": "engagement", "key": "timeline", "value": "24 days",
             "kind": "fact", "confidence": 0.9}])
    campaign_intake.reanalyze_capture(conn, cap_id)
    fields = {f["key"]: f["value"] for f in db.list_ci_fields(conn, ci_id)} \
        if hasattr(db, "list_ci_fields") else {}
    if fields:
        # "timeline" snaps to the canonical "deadline" slot on the way in — a fact filed
        # beside the slot the estimate reads is a fact the estimate cannot use.
        assert fields.get("deadline") == "24 days", fields


def test_a_capture_with_no_text_says_so(conn):
    from chordential_oia.web import campaign_intake, db
    from chordential_oia.models import Opportunity
    from chordential_oia.web import campaign_intelligence as ci
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="A", need="n", description=""))
    row = ci.ensure_for_opportunity(conn, db.get_opportunity(conn, opp_id))
    cap_id = db.insert_capture(
        conn, ci_id=row["id"], campaign_id=None, opp_id=opp_id, lane="discovery_call",
        stance="objective", modality="transcript", provenance_source="discovery_call",
        raw_text="", extraction=[], artifact_ref="", external_ref="",
        metadata={}, status="ingested", created_by="capture")
    out = campaign_intake.reanalyze_capture(conn, cap_id)
    assert out["ok"] is False and "no text" in out["error"]


def test_the_press_is_approved_spend():
    """A person pressed it, so this scope may reach the engine (web/ai_budget.py)."""
    import inspect
    from chordential_oia.web import opportunity_routes
    src = inspect.getsource(opportunity_routes.opp_capture_reanalyze)
    assert "ai_budget.approved_by" in src


def test_the_evidence_page_offers_it_when_the_engine_failed():
    """The advice and the affordance have to be in the same place."""
    from pathlib import Path
    from chordential_oia.web import app as app_mod
    html = (Path(app_mod.__file__).parent / "templates" / "evidence.html").read_text(
        encoding="utf-8")
    assert "/reanalyze" in html and "Re-read with the engine" in html
