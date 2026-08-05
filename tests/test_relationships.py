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
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia import mailer  # noqa: E402
from chordential_oia.web import intelligence  # noqa: E402
from chordential_oia.web import music_opportunity  # noqa: E402
from chordential_oia.web import opportunity_signals  # noqa: E402


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


def test_pipeline_stages_batched_matches_per_row_derivation(tmp_path):
    """The /relationships pipeline stages agencies with O(1) queries (one aggregate +
    one relationships fetch + one commit) instead of a query + commit per row. It must
    derive the SAME stage as the per-row current_stage/derive_stage logic for every
    case — no touch (warm/cold by score), recent responded, old unresponded, and a
    human override."""
    from datetime import datetime, timezone, timedelta
    conn = dbm.connect(str(tmp_path / "pipe.db"))
    dbm.init_db(conn)
    now = datetime.now(timezone.utc)

    def mk(company, score, touches=(), override=None):
        dbm.upsert_agency(conn, "s", {"dedup_key": company, "company": company,
                                      "website": "x"})
        aid = conn.execute("SELECT id FROM agencies WHERE company=?",
                           (company,)).fetchone()["id"]
        conn.execute("UPDATE agencies SET opportunity_score=?, opportunity_tier='B', "
                     "score_movement=0 WHERE id=?", (score, aid))
        for days_ago, responded in touches:
            dbm.log_agency_outreach(conn, aid, kind="email", responded=responded,
                                    occurred_at=(now - timedelta(days=days_ago)).isoformat())
        if override:
            dbm.upsert_relationship(conn, aid, stage=override, stage_overridden=1)
        conn.commit()

    mk("WarmNoTouch", 75)
    mk("ColdNoTouch", 20)
    mk("ActiveRecentResponded", 50, [(10, True)])
    mk("DormantOldNoResp", 50, [(200, False)])
    mk("ActiveRecentNoResp", 50, [(30, False)])
    mk("Overridden", 90, [(5, True)], override="Client")

    rows = dbm.top_opportunities(conn, limit=50)
    # Reference: the old per-row derivation.
    expected = {}
    for r in rows:
        rr = dbm.get_relationship(conn, r["id"])
        if rr and rr["stage_overridden"] and rr["stage"]:
            expected[r["company"]] = rr["stage"]
        else:
            inter = list(dbm.list_agency_outreach(conn, r["id"]))
            expected[r["company"]] = rel.derive_stage(
                score=r["opportunity_score"], interactions=inter,
                responded=any(o["responded"] for o in inter))
    got = {p["company"]: p["stage"] for p in rel.pipeline_stages(conn, rows)}
    assert got == expected


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
    intelligence.generate_intelligence(conn, aid)
    opportunity_signals.detect_signals(conn, aid)
    music_opportunity.score_agency(conn, aid)
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
        # The drafts are no longer a dead-end: Copy + Open-in-mail are always offered.
        assert "cdlCopyDraft" in detail and "Open in mail client" in detail


def test_agency_outreach_send_route_sends_and_logs(tmp_path, monkeypatch):
    """The drafts used to only 'Log as sent' (a touch that sent nothing). The send
    route actually mails the draft via the mailer seam and logs the touch."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "send.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient

    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    app_mod.db.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "akqa.com", "company": "AKQA", "website": "https://akqa.com"})
    conn.commit()
    aid = app_mod.db.list_agencies(conn)[0]["id"]
    conn.close()

    sent = {}
    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(
        mailer, "send_email",
        lambda to, subject, text, html=None: sent.update(
            to=to, subject=subject, text=text, html=html) or "sent")

    with TestClient(app_mod.app) as c:
        r = c.post(f"/agencies/{aid}/outreach/send", follow_redirects=False,
                   data={"subject": "Original music for your next campaign",
                         "body": "Hi Sarah,\n\nLoved your recent work.",
                         "email": "sarah@akqa.com", "contact": "Sarah",
                         "angle": "craft"})
    assert r.status_code == 303 and "sent=sent" in r.headers["location"]
    assert sent["to"] == "sarah@akqa.com"
    assert sent["html"] is not None and "wordmark-dark.png" in sent["html"]
    # The touch was logged (relationship history reflects the send).
    conn = app_mod.db.connect()
    try:
        touches = app_mod.db.list_agency_outreach(conn, aid)
    finally:
        conn.close()
    assert len(touches) == 1 and touches[0]["kind"] == "email"


def test_agency_outreach_send_falls_back_to_manual_without_mail(tmp_path, monkeypatch):
    """No recipient or mail unconfigured → no send, flagged manual, never crashes."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "manual.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    app_mod.db.upsert_agency(conn, "m", {"dedup_key": "x", "company": "X",
                                         "website": "https://x.example"})
    conn.commit()
    aid = app_mod.db.list_agencies(conn)[0]["id"]
    conn.close()
    with TestClient(app_mod.app) as c:
        r = c.post(f"/agencies/{aid}/outreach/send", follow_redirects=False,
                   data={"subject": "s", "body": "b", "email": ""})
    assert r.status_code == 303 and "sent=manual" in r.headers["location"]
