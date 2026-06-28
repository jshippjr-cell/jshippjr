"""Music Opportunity Engine — the synthesis layer. A 0–100 score from explainable
sub-scores, a tier, movement/history, and a full sales strategy. Pure reasoning
over stored data; no network. The score must never be a black box, and it must be
alive (outreach and new signals move it).
"""

import importlib

from chordential_oia.web import db as dbm
from chordential_oia.web import enrichment as en
from chordential_oia.web import intelligence as intel
from chordential_oia.web import opportunity_signals as osig
from chordential_oia.web import music_opportunity as mo


_PROFILE = en.AgencyProfile(
    name="AKQA", website="https://akqa.com",
    services=["Brand Films", "Advertising", "Experiential"],
    industries=["Technology", "Luxury"],
    portfolio=["Nike cinematic brand film"], clients=["Nike", "Verizon"],
    awards=["Cannes Lions 2026"], offices=["NY", "London", "Tokyo"],
    open_roles=["Executive Producer"],
    news=[{"title": "AKQA wins global Nike account", "url": "u"}])

_DM = {"dedup_key": "sarah", "name": "Sarah Johnson", "title": "Executive Producer",
       "role_category": "Production", "priority": "Very High",
       "music_relevance": "High", "email": "sarah@akqa.com", "linkedin": "",
       "linkedin_verified": 0, "confidence": 92, "relevance_reason": "x"}


def _seed(tmp_path, *, profile=_PROFILE, dm=_DM, with_intel=True, with_signals=True):
    conn = dbm.connect(str(tmp_path / "mo.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "akqa.com", "company": "AKQA",
        "website": "https://akqa.com", "employees": "50 - 100"})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    dbm.save_agency_enrichment(conn, aid, {"status": "complete", "profile": profile.to_dict()})
    if dm:
        dbm.upsert_decision_maker(conn, aid, dm)
    conn.commit()
    if with_intel:
        intel.generate_intelligence(conn, aid)
    if with_signals:
        osig.detect_signals(conn, aid)
    return conn, aid


def test_score_is_sum_of_subscores_and_each_cites_evidence(tmp_path):
    conn, aid = _seed(tmp_path)
    mo.score_agency(conn, aid)
    b = dbm.get_agency_score(conn, aid)

    assert b["score"] == sum(s["value"] for s in b["subscores"])    # transparent total
    names = {s["name"] for s in b["subscores"]}
    assert names == {"Creative Fit", "Business Momentum", "Music Need Probability",
                     "Relationship Readiness", "Contact Confidence", "Timing (bonus)"}
    for s in b["subscores"]:
        assert s["evidence"], f"{s['name']} has no evidence"      # never a black box
        assert s["value"] <= s["max"]
    assert b["tier"] in ("A", "B", "C", "D")
    assert b["score"] >= 60 and b["tier"] in ("A", "B")          # strong fit here


def test_recommendation_contact_and_talking_points(tmp_path):
    conn, aid = _seed(tmp_path)
    mo.score_agency(conn, aid)
    b = dbm.get_agency_score(conn, aid)
    assert b["recommended_contact"]["name"] == "Sarah Johnson"
    assert b["best_timing"] and b["recommended_action"]
    pts = " ".join(p["text"] for p in b["talking_points"])
    assert "Nike" in pts                                          # cites the real signal
    assert all(p["source"] for p in b["talking_points"])         # every point traceable


def test_score_is_alive_outreach_lowers_readiness(tmp_path):
    conn, aid = _seed(tmp_path)
    mo.score_agency(conn, aid)
    before = dbm.get_agency_score(conn, aid)["score"]
    rr_before = next(s for s in dbm.get_agency_score(conn, aid)["subscores"]
                     if s["name"] == "Relationship Readiness")["value"]
    assert rr_before == 15                                        # never contacted

    dbm.log_agency_outreach(conn, aid, kind="email", note="intro")
    conn.commit()
    res = mo.score_agency(conn, aid)
    after = dbm.get_agency_score(conn, aid)
    assert res["score"] < before and res["movement"] < 0         # the score dropped
    rr_after = next(s for s in after["subscores"]
                    if s["name"] == "Relationship Readiness")["value"]
    assert rr_after < rr_before
    assert "wait" in after["recommended_action"].lower()


def test_new_signal_raises_score_and_records_movement(tmp_path):
    conn, aid = _seed(tmp_path)
    mo.score_agency(conn, aid)
    base = dbm.get_agency_score(conn, aid)["score"]

    # a fresh win lands on the timeline (as re-enrichment + detection would do)
    p = en.AgencyProfile.from_dict(_PROFILE.to_dict())
    p.news.append({"title": "AKQA wins global Coca-Cola account", "url": "u2"})
    dbm.save_agency_enrichment(conn, aid, {"status": "complete", "profile": p.to_dict()})
    conn.commit()
    osig.detect_signals(conn, aid)
    res = mo.score_agency(conn, aid)
    assert res["score"] >= base and res["movement"] >= 0
    hist = dbm.get_agency_score(conn, aid)["history"]
    assert len(hist) == 2 and hist[-1]["score"] == res["score"]   # history grows per run


def test_tiers_and_top_movers_ranking(tmp_path):
    conn, aid = _seed(tmp_path)
    # a weak second agency (no intel/signals/dm) scores far lower
    dbm.upsert_agency(conn, "thedrum", {
        "dedup_key": "weak", "company": "Weak Co", "website": "https://weak.example"})
    conn.commit()
    wid = next(r["id"] for r in dbm.list_agencies(conn) if r["company"] == "Weak Co")
    dbm.save_agency_enrichment(conn, wid, {
        "status": "complete", "profile": en.AgencyProfile(name="Weak Co").to_dict()})
    conn.commit()
    intel.generate_intelligence(conn, wid)

    mo.score_batch(conn, limit=10)
    top = dbm.top_opportunities(conn, limit=10)
    assert top[0]["company"] == "AKQA"                            # strongest first
    akqa_score = next(r["opportunity_score"] for r in top if r["company"] == "AKQA")
    weak_score = next(r["opportunity_score"] for r in top if r["company"] == "Weak Co")
    assert akqa_score > weak_score


def test_detail_page_shows_opportunity_headline(tmp_path, monkeypatch):
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
    assert "Recommended action" in html
    assert "Creative Fit" in html and "Music Need Probability" in html
    assert "Sarah Johnson" in html and "Nike" in html


def test_scheduler_manual_score_guarded(monkeypatch):
    from chordential_oia.web import scheduler as sch
    monkeypatch.setenv("CHORDENTIAL_AUTOSCORE", "0")
    assert sch.start_manual_score(5) is False
    monkeypatch.setenv("CHORDENTIAL_AUTOSCORE", "1")
    sch._score_status["running"] = True
    try:
        assert sch.start_manual_score(5) is False
    finally:
        sch._score_status["running"] = False
