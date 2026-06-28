"""Relationship Management Platform — consumes the engines' outputs and manages
the lifecycle. Auto-agents (stage, reminder, timeline, memory) are deterministic.
"""

import importlib

from chordential_oia.web import db as dbm
from chordential_oia.web import enrichment as en
from chordential_oia.web import intelligence as intel
from chordential_oia.web import opportunity_signals as osig
from chordential_oia.web import music_opportunity as mo
from chordential_oia.web import relationships as rel


_PROFILE = en.AgencyProfile(
    name="AKQA", website="https://akqa.com", services=["Brand Films"],
    industries=["Technology"], portfolio=["Nike cinematic film"], clients=["Nike"],
    awards=["Cannes Lions 2026"], offices=["NY", "London", "Tokyo"],
    open_roles=["Executive Producer"],
    news=[{"title": "AKQA wins global Nike account", "url": "u"}])
_DM = {"dedup_key": "sarah", "name": "Sarah Johnson", "title": "Executive Producer",
       "role_category": "Production", "priority": "Very High", "music_relevance": "High",
       "email": "sarah@akqa.com", "linkedin": "", "linkedin_verified": 0,
       "confidence": 92, "relevance_reason": "owns production budgets"}


def _seed(tmp_path):
    conn = dbm.connect(str(tmp_path / "rel.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "akqa.com", "company": "AKQA",
        "website": "https://akqa.com", "employees": "50 - 100"})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    dbm.save_agency_enrichment(conn, aid, {"status": "complete", "profile": _PROFILE.to_dict()})
    dbm.upsert_decision_maker(conn, aid, _DM)
    conn.commit()
    intel.generate_intelligence(conn, aid)
    osig.detect_signals(conn, aid)
    mo.score_agency(conn, aid)
    return conn, aid


# --------------------------------------------------------------------------- #
# Relationship Agent — stage derivation.
# --------------------------------------------------------------------------- #
def test_stage_derivation():
    assert rel.derive_stage(score=91, interactions=[], responded=False) == "Warm Prospect"
    assert rel.derive_stage(score=30, interactions=[], responded=False) == "Cold"
    recent = [{"occurred_at": "2999-01-01T00:00:00+00:00"}]   # "today"-ish (future-safe)
    assert rel.derive_stage(score=80, interactions=recent, responded=False) == "Active"
    old = [{"occurred_at": "2000-01-01T00:00:00+00:00"}]
    assert rel.derive_stage(score=80, interactions=old, responded=True) == "Dormant"


def test_view_advances_stage_and_manual_override(tmp_path):
    conn, aid = _seed(tmp_path)
    assert rel.relationship_view(conn, aid)["stage"] == "Warm Prospect"  # scored, no contact
    dbm.log_agency_outreach(conn, aid, kind="email", contact="Sarah")
    conn.commit()
    assert rel.relationship_view(conn, aid)["stage"] == "Active"         # auto-advanced
    # a human override pins it
    dbm.upsert_relationship(conn, aid, stage="Client", stage_overridden=1)
    conn.commit()
    assert rel.relationship_view(conn, aid)["stage"] == "Client"


# --------------------------------------------------------------------------- #
# Reminder Agent.
# --------------------------------------------------------------------------- #
def test_reminder_agent_creates_one_followup(tmp_path):
    conn, aid = _seed(tmp_path)
    assert rel.ensure_followup(conn, aid, days=14, contact="Sarah") is True
    assert rel.ensure_followup(conn, aid, days=14) is False             # not duplicated
    tasks = dbm.list_agency_tasks(conn, aid, status="open")
    assert len(tasks) == 1 and tasks[0]["kind"] == "followup" and tasks[0]["due_at"]


# --------------------------------------------------------------------------- #
# Memory Agent + Timeline Agent.
# --------------------------------------------------------------------------- #
def test_memory_seeded_and_deduped(tmp_path):
    conn, aid = _seed(tmp_path)
    n1 = rel.seed_memory(conn, aid)
    n2 = rel.seed_memory(conn, aid)
    assert n1 >= 1 and n2 == 0                                          # idempotent
    facts = " ".join(m["fact"] for m in dbm.list_agency_memory(conn, aid))
    assert "Sarah Johnson" in facts and "Technology" in facts


def test_timeline_merges_all_sources(tmp_path):
    conn, aid = _seed(tmp_path)
    dbm.log_agency_outreach(conn, aid, kind="email", contact="Sarah")
    dbm.add_agency_task(conn, aid, title="Send reel", due_at="")
    conn.commit()
    kinds = {e["kind"] for e in rel.relationship_timeline(conn, aid)}
    assert {"Interaction", "Signal", "Task", "Score"} <= kinds         # one unified view


# --------------------------------------------------------------------------- #
# Priorities dashboard.
# --------------------------------------------------------------------------- #
def test_daily_priorities_surfaces_actionable(tmp_path):
    conn, aid = _seed(tmp_path)
    p = rel.daily_priorities(conn)
    assert p["ep_hires_count"] >= 1                                     # the EP-hire signal
    assert "recommended" in p and "top_movers" in p


# --------------------------------------------------------------------------- #
# It consumes, never duplicates — and the workspace renders.
# --------------------------------------------------------------------------- #
def test_relationships_dashboard_and_detail_render(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient

    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    app_mod.db.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "akqa.com", "company": "AKQA",
        "website": "https://akqa.com", "employees": "50 - 100"})
    conn.commit()
    aid = app_mod.db.list_agencies(conn)[0]["id"]
    app_mod.db.save_agency_enrichment(conn, aid, {"status": "complete", "profile": _PROFILE.to_dict()})
    app_mod.db.upsert_decision_maker(conn, aid, _DM)
    conn.commit()
    app_mod.intelligence.generate_intelligence(conn, aid)
    app_mod.opportunity_signals.detect_signals(conn, aid)
    app_mod.music_opportunity.score_agency(conn, aid)
    conn.close()

    with TestClient(app_mod.app) as c:
        dash = c.get("/relationships").text
        assert "Today's priorities" in dash and "Relationship pipeline" in dash
        assert "AKQA" in dash
        detail = c.get(f"/agencies/{aid}").text
        assert "Relationship" in detail and "Relationship memory" in detail
        # logging outreach advances the stage + creates a follow-up
        c.post(f"/agencies/{aid}/outreach", data={"kind": "email", "contact": "Sarah"})
        detail2 = c.get(f"/agencies/{aid}").text
        assert "Active" in detail2 and "Follow up" in detail2
