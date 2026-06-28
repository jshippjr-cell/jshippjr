"""Company Intelligence Engine — evidence-backed, deterministic intelligence from
the collected Agency Profile. Every conclusion must cite its evidence; thin
evidence must say so, never fabricate. No network; pure computation.
"""

import importlib

from chordential_oia.web import db as dbm
from chordential_oia.web import enrichment as en
from chordential_oia.web import intelligence as intel


def _seed(tmp_path, *, profile=None, enrich_status="complete", dms=None,
          employees="50 - 100"):
    conn = dbm.connect(str(tmp_path / "intel.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "acme.example", "company": "Acme",
        "website": "https://acme.example", "employees": employees,
        "industries": ""})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    if profile is not None:
        dbm.save_agency_enrichment(conn, aid, {
            "status": enrich_status, "profile": profile.to_dict()})
    for d in (dms or []):
        dbm.upsert_decision_maker(conn, aid, d)
    conn.commit()
    return conn, aid


_RICH = en.AgencyProfile(
    name="Acme", website="https://acme.example",
    description="Acme is a global advertising agency producing cinematic brand films.",
    services=["Brand Films", "Advertising", "Social", "Experiential"],
    industries=["Healthcare", "Technology", "Luxury"],
    portfolio=["IBM cinematic brand film", "Coca-Cola broadcast commercial"],
    clients=["IBM", "Coca-Cola", "Nestlé", "Verizon", "Dove"],
    awards=["Cannes Lions Grand Prix 2023", "One Show Gold", "D&AD Pencil"],
    offices=["New York", "London", "Singapore", "São Paulo"],
    open_roles=["Executive Producer"],
    news=[{"title": "Acme wins global Dove account", "url": "x"}])

_PROD_DM = {"dedup_key": "dana reed", "name": "Dana Reed",
            "title": "Executive Producer", "role_category": "Production",
            "priority": "Very High", "music_relevance": "High",
            "relevance_reason": "x", "confidence": 92}


def test_industry_classification_is_word_bounded():
    # "care" inside "healthcare" must NOT trigger Automotive ("car")
    f = intel.classify_industries(
        en.AgencyProfile(industries=["Healthcare"], services=[], clients=[],
                         description=""), "")
    assert f["value"] == ["Healthcare"]
    assert "Automotive" not in f["value"]


def test_full_profile_is_evidence_backed(tmp_path):
    conn, aid = _seed(tmp_path, profile=_RICH, dms=[_PROD_DM])
    intel.generate_intelligence(conn, aid)
    p = dbm.get_agency_intel(conn, aid)

    assert p["status"] == "complete"
    # industries (deduped, real)
    assert set(p["primary_industries"]["value"]) == {"Healthcare", "Technology", "Luxury"}
    # creative focus picked from services/portfolio
    assert "Brand Films" in p["creative_focus"]["value"]
    # production complexity High, with the signals as evidence + high confidence
    pc = p["production_complexity"]
    assert pc["value"] == "High" and pc["confidence"] >= 80
    assert any("offices" in e.lower() for e in pc["evidence"])
    assert any("award" in e.lower() for e in pc["evidence"])
    # EVERY inferred field carries evidence
    for key in ("executive_summary", "primary_industries", "creative_focus",
                "production_complexity", "music_procurement", "momentum"):
        assert p[key]["evidence"], f"{key} has no evidence"
    # momentum reflects hiring + the news win + awards
    assert "Hiring" in p["momentum"]["value"]
    assert any("Dove" in e for e in p["momentum"]["evidence"])
    # procurement reasons from the production decision maker + complexity
    assert "Dana Reed" in " ".join(p["music_procurement"]["evidence"])
    assert p["overall_confidence"] >= 70


def test_music_usage_is_only_what_is_observed(tmp_path):
    # no music words anywhere -> empty value + an explicit "needs research" note
    conn, aid = _seed(tmp_path, profile=_RICH)
    intel.generate_intelligence(conn, aid)
    mu = dbm.get_agency_intel(conn, aid)["music_usage"]
    assert mu["value"] == [] and "additional research" in mu["evidence"][0].lower()

    # a portfolio that mentions an original score -> flagged WITH the evidence
    scored = en.AgencyProfile(
        name="Acme", services=["Sound Design"],
        portfolio=["Brand film with an original score composed for the campaign"],
        offices=[], awards=[], clients=[], industries=[])
    conn2, aid2 = _seed(tmp_path, profile=scored)
    intel.generate_intelligence(conn2, aid2)
    mu2 = dbm.get_agency_intel(conn2, aid2)["music_usage"]
    assert "Uses Original Score" in mu2["value"] and "Uses Sound Design" in mu2["value"]
    assert any("original score" in e.lower() for e in mu2["evidence"])


def test_thin_data_yields_low_confidence_and_says_so(tmp_path):
    bare = en.AgencyProfile(name="Acme", website="https://acme.example")
    conn, aid = _seed(tmp_path, profile=bare, employees="")
    intel.generate_intelligence(conn, aid)
    p = dbm.get_agency_intel(conn, aid)
    assert p["overall_confidence"] <= 40
    assert p["production_complexity"]["value"] == "Unknown"
    assert "additional research" in p["music_procurement"]["value"].lower() or \
           "insufficient" in p["music_procurement"]["value"].lower()


def test_preliminary_when_enrichment_incomplete(tmp_path):
    conn, aid = _seed(tmp_path, profile=_RICH, enrich_status="running")
    intel.generate_intelligence(conn, aid)
    p = dbm.get_agency_intel(conn, aid)
    assert p["enrichment_complete"] is False
    assert p["overall_confidence"] <= 35 and p["note"]


def test_batch_only_runs_enriched_and_advances_queue(tmp_path):
    conn, aid = _seed(tmp_path, profile=_RICH)
    # a second agency that's NOT enriched -> excluded from the queue
    dbm.upsert_agency(conn, "thedrum", {
        "dedup_key": "noenrich", "company": "NoEnrich",
        "website": "https://x.example"})
    conn.commit()
    assert [r["company"] for r in dbm.agencies_needing_intelligence(conn)] == ["Acme"]
    res = intel.generate_batch(conn, limit=10)
    assert res["generated"] == 1
    # marker set -> drops out of the queue
    assert dbm.agencies_needing_intelligence(conn) == []


def test_detail_page_renders_intelligence(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from fastapi.testclient import TestClient

    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    app_mod.db.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "acme.example", "company": "Acme",
        "website": "https://acme.example", "employees": "50 - 100"})
    conn.commit()
    aid = app_mod.db.list_agencies(conn)[0]["id"]
    app_mod.db.save_agency_enrichment(conn, aid, {
        "status": "complete", "profile": _RICH.to_dict()})
    conn.commit()
    app_mod.intelligence.generate_intelligence(conn, aid)
    conn.close()

    with TestClient(app_mod.app) as c:
        html = c.get(f"/agencies/{aid}").text
    assert "Company intelligence" in html
    assert "Production complexity" in html and "High" in html
    assert "evidence" in html                      # the evidence disclosure renders
