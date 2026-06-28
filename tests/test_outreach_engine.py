"""Outreach Engine — three engines: Strategy (if/when/why/whom), Content
Generation (three drafts), Relationship Continuity (next best action by what
changed). Deterministic by default; LLM is an optional seam. It DRAFTS only —
nothing is sent, nothing is invented.
"""

import importlib

from chordential_oia.web import db as dbm
from chordential_oia.web import enrichment as en
from chordential_oia.web import intelligence as intel
from chordential_oia.web import opportunity_signals as osig
from chordential_oia.web import music_opportunity as mo
from chordential_oia.web import outreach_engine as oe


_PROFILE = en.AgencyProfile(
    name="AKQA", website="https://akqa.com", services=["Brand Films"],
    industries=["Automotive"], portfolio=["Verizon cinematic anthem film"],
    clients=["Nike"], awards=["Cannes Lions 2026"], offices=["NY", "London", "Tokyo"],
    open_roles=["Executive Producer"],
    news=[{"title": "AKQA wins global Verizon account", "url": "u"}])
_DM = {"dedup_key": "sarah", "name": "Sarah Johnson", "title": "Executive Producer",
       "role_category": "Production", "priority": "Very High", "music_relevance": "High",
       "email": "sarah@akqa.com", "linkedin": "", "linkedin_verified": 0,
       "confidence": 92, "relevance_reason": "owns production"}


def _seed(tmp_path, *, dm=_DM):
    conn = dbm.connect(str(tmp_path / "oe.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "akqa.com", "company": "AKQA",
        "website": "https://akqa.com", "employees": "50 - 100"})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    dbm.save_agency_enrichment(conn, aid, {"status": "complete", "profile": _PROFILE.to_dict()})
    if dm:
        dbm.upsert_decision_maker(conn, aid, dm)
    conn.commit()
    intel.generate_intelligence(conn, aid)
    osig.detect_signals(conn, aid)
    mo.score_agency(conn, aid)
    return conn, aid


# --------------------------------------------------------------------------- #
# Outreach Strategy Engine — if / when / why / to whom.
# --------------------------------------------------------------------------- #
def test_strategy_decides_yes_with_reason_and_objective(tmp_path):
    conn, aid = _seed(tmp_path)
    s = oe.build_strategy(conn, aid)
    assert s["decision"] == "YES"                       # reachable, strong tier
    assert s["objective"] == "Congratulations"          # fresh win signal
    assert "Verizon" in s["brief"]["why_now"]           # the reason-to-reach-out
    assert s["brief"]["why_now_source"].startswith("Signal")
    assert any("AI-generated" in a for a in s["brief"]["avoid"])   # honesty guardrail


def test_strategy_waits_after_recent_outreach(tmp_path):
    conn, aid = _seed(tmp_path)
    dbm.log_agency_outreach(conn, aid, kind="email")    # contacted just now
    conn.commit()
    mo.score_agency(conn, aid)
    s = oe.build_strategy(conn, aid)
    assert s["decision"] == "WAIT" and "wait" in s["detail"].lower()


def test_strategy_monitors_when_unreachable(tmp_path):
    conn, aid = _seed(tmp_path, dm=None)               # no decision maker → no channel
    mo.score_agency(conn, aid)
    s = oe.build_strategy(conn, aid)
    assert s["decision"] == "MONITOR" and "contact" in s["detail"].lower()


# --------------------------------------------------------------------------- #
# Content Generation Engine — three drafts; LLM optional.
# --------------------------------------------------------------------------- #
def test_three_distinct_drafts_from_brief(tmp_path):
    conn, aid = _seed(tmp_path)
    brief = oe.build_strategy(conn, aid)["brief"]
    drafts = oe.generate_drafts(brief)
    assert [d["angle"] for d in drafts] == ["relationship", "creative", "business"]
    bodies = [d["body"] for d in drafts]
    assert len(set(bodies)) == 3                        # genuinely different approaches
    for d in drafts:
        assert d["generated_by"] == "template"
        assert d["body"].startswith("Hi Sarah,")        # personalized to the contact
        assert "I saw" in d["body"]                      # opens with the reason
        assert "clearance-certified" in d["body"]        # the honest value prop
        assert "AI-generated" in d["body"]               # the honest disclaimer


def test_llm_seam_used_when_provided(tmp_path):
    conn, aid = _seed(tmp_path)
    brief = oe.build_strategy(conn, aid)["brief"]
    calls = []

    def fake_llm(b, angle):
        calls.append(angle)
        return {"subject": f"AI {angle}", "body": f"Custom {angle} body for {b['agency']}."}
    drafts = oe.generate_drafts(brief, llm=fake_llm)
    assert calls == ["relationship", "creative", "business"]
    assert all(d["generated_by"] == "ai" for d in drafts)
    assert drafts[0]["subject"] == "AI relationship"


def test_llm_failure_falls_back_to_template(tmp_path):
    conn, aid = _seed(tmp_path)
    brief = oe.build_strategy(conn, aid)["brief"]
    drafts = oe.generate_drafts(brief, llm=lambda b, a: None)   # seam returns nothing
    assert all(d["generated_by"] == "template" for d in drafts)


# --------------------------------------------------------------------------- #
# Relationship Continuity Engine — follows reality, not a calendar.
# --------------------------------------------------------------------------- #
def test_continuity_intelligent_followup_on_change(tmp_path):
    conn, aid = _seed(tmp_path)
    assert oe.next_best_action(conn, aid)["kind"] == "introduce"   # no outreach yet

    dbm.log_agency_outreach(conn, aid, kind="email",
                            occurred_at="2026-06-01T00:00:00+00:00")
    conn.commit()
    # an agency CHANGE lands after the email
    p = en.AgencyProfile.from_dict(_PROFILE.to_dict())
    p.awards.append("D&AD 2026 Black Pencil")
    dbm.save_agency_enrichment(conn, aid, {"status": "complete", "profile": p.to_dict()})
    conn.commit()
    osig.detect_signals(conn, aid)

    nba = oe.next_best_action(conn, aid)
    assert nba["kind"] == "followup"
    assert "since your last email" in nba["reason"].lower()
    assert nba["changed"]                                # cites what changed


def test_continuity_waits_when_nothing_changed(tmp_path):
    conn, aid = _seed(tmp_path)
    dbm.log_agency_outreach(conn, aid, kind="email")    # just now, no change after
    conn.commit()
    nba = oe.next_best_action(conn, aid)
    assert nba["kind"] == "wait"


# --------------------------------------------------------------------------- #
# Workspace + render (drafts only, nothing sent).
# --------------------------------------------------------------------------- #
def test_outreach_section_renders_and_log_as_sent(tmp_path, monkeypatch):
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
        html = c.get(f"/agencies/{aid}").text
        assert "Outreach" in html and "Why today" in html
        assert "relationship-focused" in html and "business-focused" in html
        assert "Verizon" in html
        # "Log as sent" records a touch (does not send) → an interaction appears
        c.post(f"/agencies/{aid}/outreach",
               data={"kind": "email", "contact": "Sarah Johnson", "note": "creative: hi"})
    conn = app_mod.db.connect()
    assert len(app_mod.db.list_agency_outreach(conn, aid)) == 1
    conn.close()
