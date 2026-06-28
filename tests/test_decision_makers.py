"""Decision Maker Discovery Engine — the six single-responsibility agents, the
hybrid (rules → LLM → learn) title classifier, and the end-to-end pipeline that
stores every decision maker for an agency. Network + LLM are faked; nothing here
touches the wire or calls a real model.
"""

import json

from chordential_oia.web import db as dbm
from chordential_oia.web import decision_makers as dm


# A small agency site: a team page with two heading cards (one with a LinkedIn +
# email + bio, one sparse) and the homepage linking to it.
SITE = {
    "https://acme.example/": """<html><head><title>Acme</title></head><body><nav>
        <a href="/team">Our Team</a><a href="/contact">Contact</a></nav></body></html>""",
    "https://acme.example/team": """<body><h1>Leadership</h1>
        <div class="card">
            <img src="/img/dana.jpg">
            <h3>Dana Reed</h3><p>Executive Producer</p>
            <p>Dana has led branded content production for over a decade, overseeing
               music and post for global campaigns at Acme.</p>
            <a href="https://www.linkedin.com/in/dana-reed-1a2b">LinkedIn</a>
            <a href="mailto:dana@acme.example">Email</a>
        </div>
        <div class="card">
            <h3>Sam Okafor</h3><p>Office Manager</p>
        </div>
        <div class="card">
            <h3>Jamie Lin</h3><p>Creative Director</p>
            <a href="https://www.linkedin.com/in/someone-else-9z">LinkedIn</a>
        </div>
    </body>""",
}


def fake_fetch(url, timeout=15.0):
    u = url if url in SITE else (url + "/" if url + "/" in SITE else url)
    return (SITE.get(u, ""), u in SITE)


def _seed(tmp_path, website="https://acme.example", company="Acme"):
    conn = dbm.connect(str(tmp_path / "dm.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "acme.example", "company": company, "website": website})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    return conn, aid


# --------------------------------------------------------------------------- #
# Agent 1 — Leadership Discovery (find every person, no judgment)
# --------------------------------------------------------------------------- #
def test_extract_people_finds_every_person_with_fields():
    people = dm.extract_people(SITE["https://acme.example/team"],
                              "https://acme.example/team")
    by_name = {p["name"]: p for p in people}
    # the Office Manager is found too — Agent 1 does NOT judge importance
    assert set(by_name) == {"Dana Reed", "Sam Okafor", "Jamie Lin"}
    dana = by_name["Dana Reed"]
    assert dana["title"] == "Executive Producer"
    assert dana["photo_url"] == "https://acme.example/img/dana.jpg"
    assert dana["bio"].startswith("Dana has led branded content")
    # "Leadership" section heading is not mistaken for a person
    assert "Leadership" not in by_name


# --------------------------------------------------------------------------- #
# Agent 2 — Role Classification (rules → LLM → learn)
# --------------------------------------------------------------------------- #
def test_classify_by_rules_assigns_priority_and_reason(tmp_path):
    conn, _ = _seed(tmp_path)
    ep = dm.classify_title(conn, "Executive Producer")
    assert ep["priority"] == "Very High" and ep["music_relevance"] == "High"
    assert ep["classified_by"] == "rules" and "production" in ep["relevance_reason"].lower()

    om = dm.classify_title(conn, "Office Manager")
    assert om["priority"] == "Low" and om["music_relevance"] == "Low"
    assert "not involved" in om["relevance_reason"].lower()

    cd = dm.classify_title(conn, "Creative Director")
    assert cd["priority"] == "High" and cd["role_category"] == "Creative"


def test_classifier_learns_then_serves_from_taxonomy_cache(tmp_path):
    conn, _ = _seed(tmp_path)
    # First confident rule match is written into the taxonomy...
    dm.classify_title(conn, "Executive Producer")
    row = dbm.taxonomy_get(conn, "executive producer")
    assert row is not None and row["source"] == "rules" and row["hits"] == 1
    # ...and a second identical title is a cache hit (hits increments by the bump).
    dm.classify_title(conn, "Executive Producer")
    assert dbm.taxonomy_get(conn, "executive producer")["hits"] == 2  # learn(1) + 1 bump


def test_llm_only_for_unknown_titles_and_result_is_learned(tmp_path):
    conn, _ = _seed(tmp_path)
    calls = []

    def fake_llm(title, context):
        calls.append(title)
        return {"role_category": "Production", "department": "Production",
                "priority": "High", "music_relevance": "High",
                "relevance_reason": "Bespoke production role.", "confidence": 80}

    # A confident rule title must NOT hit the LLM.
    dm.classify_title(conn, "Creative Director", llm=fake_llm)
    assert calls == []

    # A title the rules can't place falls through to the LLM exactly once...
    res = dm.classify_title(conn, "Sonic Brand Whisperer", llm=fake_llm)
    assert res["classified_by"] == "llm" and res["priority"] == "High"
    assert calls == ["Sonic Brand Whisperer"]
    # ...and is then learned, so the next time it's a rules/cache answer (no LLM).
    res2 = dm.classify_title(conn, "Sonic Brand Whisperer", llm=fake_llm)
    assert calls == ["Sonic Brand Whisperer"]          # not called again
    assert res2["role_category"] == "Production"
    learned = dbm.taxonomy_get(conn, "sonic brand whisperer")
    assert learned["source"] == "llm" and learned["confidence"] == 80


def test_unknown_title_without_llm_is_unclassified_and_not_cached(tmp_path):
    conn, _ = _seed(tmp_path)
    res = dm.classify_title(conn, "Vibe Curator", llm=lambda t, c: None)
    assert res["classified_by"] == "unclassified" and res["priority"] == "Low"
    # not learned -> it gets another shot on a later run (when an LLM may exist)
    assert dbm.taxonomy_get(conn, "vibe curator") is None


# --------------------------------------------------------------------------- #
# Agent 3 — Contact Discovery (public only, never invented)
# --------------------------------------------------------------------------- #
def test_discover_contacts_reads_only_present_details():
    card = SITE["https://acme.example/team"]
    got = dm.discover_contacts(card, {"name": "Dana Reed"}, "https://acme.example/team")
    assert got["linkedin"] == "https://www.linkedin.com/in/dana-reed-1a2b"
    assert got["email"] == "dana@acme.example"
    # nothing is invented when absent
    empty = dm.discover_contacts("<div>no contacts here</div>",
                                {"name": "Sam Okafor"}, "https://acme.example/team")
    assert empty["linkedin"] == "" and empty["email"] == "" and empty["phone"] == ""


# --------------------------------------------------------------------------- #
# Agent 4 — LinkedIn Verification (structural name↔slug check)
# --------------------------------------------------------------------------- #
def test_verify_linkedin_matches_name_to_slug():
    assert dm.verify_linkedin("Dana Reed", "https://www.linkedin.com/in/dana-reed-1a2b")
    assert not dm.verify_linkedin("Dana Reed", "https://www.linkedin.com/in/someone-else-9z")
    assert not dm.verify_linkedin("Dana Reed", "")            # nothing to verify


# --------------------------------------------------------------------------- #
# Agent 5 — Confidence Scoring (deterministic)
# --------------------------------------------------------------------------- #
def test_confidence_reflects_signal_strength():
    strong = dm.score_confidence(
        {"title": "Executive Producer", "bio": "x" * 120, "photo_url": "y"},
        {"linkedin": "u", "email": "e"},
        {"classified_by": "rules", "confidence": 92}, True)
    weak = dm.score_confidence(
        {"title": "Producer", "bio": "", "photo_url": ""},
        {"linkedin": "", "email": ""},
        {"classified_by": "unclassified", "confidence": 0}, False)
    assert strong >= 90 and weak <= 50 and strong > weak


# --------------------------------------------------------------------------- #
# End-to-end — discover and store every decision maker
# --------------------------------------------------------------------------- #
def test_discover_decision_makers_stores_all_people_ranked(tmp_path):
    conn, aid = _seed(tmp_path)
    summary = dm.discover_decision_makers(conn, aid, fetch=fake_fetch)
    assert summary["status"] == "complete" and summary["found"] == 3

    rows = dbm.list_decision_makers(conn, aid)
    names = [r["name"] for r in rows]
    # all three stored; ranked by priority (Exec Producer + Creative Director above
    # the Office Manager)
    assert names[-1] == "Sam Okafor"
    assert set(names) == {"Dana Reed", "Sam Okafor", "Jamie Lin"}

    dana = next(r for r in rows if r["name"] == "Dana Reed")
    assert dana["priority"] == "Very High"
    assert dana["linkedin"] == "https://www.linkedin.com/in/dana-reed-1a2b"
    assert dana["linkedin_verified"] == 1
    assert dana["email"] == "dana@acme.example"
    assert dana["relevance_reason"]                      # the WHY is always present
    assert dana["confidence"] >= 90

    # Jamie's LinkedIn slug doesn't match her name -> not verified, lower confidence
    jamie = next(r for r in rows if r["name"] == "Jamie Lin")
    assert jamie["linkedin_verified"] == 0
    assert jamie["confidence"] < dana["confidence"]


def test_discover_is_idempotent_and_resettable(tmp_path):
    conn, aid = _seed(tmp_path)
    dm.discover_decision_makers(conn, aid, fetch=fake_fetch)
    again = dm.discover_decision_makers(conn, aid, fetch=fake_fetch)
    assert again["found"] == 0 and dbm.count_decision_makers(conn, aid) == 3  # no dupes
    reset = dm.discover_decision_makers(conn, aid, fetch=fake_fetch, reset=True)
    assert reset["found"] == 3 and dbm.count_decision_makers(conn, aid) == 3


def test_discover_blocked_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "scrape_enabled", lambda: False)
    conn, aid = _seed(tmp_path)
    summary = dm.discover_decision_makers(conn, aid)        # no fetch + scraping off
    assert summary["status"] == "blocked" and dbm.count_decision_makers(conn, aid) == 0


def test_discover_errors_without_website(tmp_path):
    conn, aid = _seed(tmp_path, website="")
    summary = dm.discover_decision_makers(conn, aid, fetch=fake_fetch)
    assert summary["status"] == "error"


def test_default_llm_is_off_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert dm._default_llm("Anything", "") is None


# --------------------------------------------------------------------------- #
# External search seam — fill LinkedIn / press when the site doesn't expose them.
# --------------------------------------------------------------------------- #
def test_web_search_is_null_without_provider(monkeypatch):
    from chordential_oia.web import web_search
    monkeypatch.delenv("CHORDENTIAL_SEARCH_PROVIDER", raising=False)
    assert web_search.search_enabled() is False
    assert web_search.search("anyone acme linkedin") == []


def test_search_enrich_accepts_only_matching_linkedin_and_collects_press():
    person = {"name": "Sam Okafor"}
    # the search returns a LinkedIn that doesn't match + a wrong-person one + press
    def fake_search(query):
        if "linkedin" in query:
            return [{"title": "Someone Else", "url": "https://linkedin.com/in/someone-else-1"},
                    {"title": "Sam Okafor", "url": "https://www.linkedin.com/in/sam-okafor-9a"}]
        return [{"title": "Acme hires Sam Okafor", "url": "https://adage.com/article"},
                {"title": "Acme team", "url": "https://acme.example/team"},   # own site -> excluded
                {"title": "Sam on LinkedIn", "url": "https://linkedin.com/in/x"}]  # social -> excluded
    got = dm.search_enrich(person, {"linkedin": ""}, "Acme", "acme.example", fake_search)
    # the matching profile is chosen (the first non-matching one is skipped)
    assert got["linkedin"] == "https://www.linkedin.com/in/sam-okafor-9a"
    # press is the off-site, non-social result only
    assert [p["url"] for p in got["press"]] == ["https://adage.com/article"]


def test_search_enrich_never_overwrites_unverifiable_profile():
    # if nothing the search returns matches the name, we keep LinkedIn empty
    got = dm.search_enrich(
        {"name": "Dana Reed"}, {"linkedin": ""}, "Acme", "acme.example",
        lambda q: [{"title": "x", "url": "https://linkedin.com/in/totally-different-9"}])
    assert got["linkedin"] == ""


def test_discover_uses_search_to_fill_linkedin_and_press(tmp_path):
    conn, aid = _seed(tmp_path)

    def fake_search(query):
        # Sam Okafor has no LinkedIn on the site; the search supplies a matching one
        if "Sam Okafor" in query and "linkedin" in query:
            return [{"title": "Sam Okafor", "url": "https://www.linkedin.com/in/sam-okafor-44"}]
        if "Sam Okafor" in query:
            return [{"title": "Sam Okafor joins Acme", "url": "https://shootonline.com/x"}]
        return []

    dm.discover_decision_makers(conn, aid, fetch=fake_fetch, search=fake_search)
    sam = next(r for r in dbm.list_decision_makers(conn, aid) if r["name"] == "Sam Okafor")
    assert sam["linkedin"] == "https://www.linkedin.com/in/sam-okafor-44"
    assert sam["linkedin_verified"] == 1                       # searched + verified
    press = json.loads(sam["press_json"])
    assert press and press[0]["url"] == "https://shootonline.com/x"


def test_discover_batch_runs_over_agencies(tmp_path):
    conn, aid = _seed(tmp_path)
    dbm.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "nosite", "company": "No Site", "website": ""})
    conn.commit()
    res = dm.discover_batch(conn, fetch=fake_fetch, limit=10)
    # only the website-bearing agency is queued (no-site rows are excluded)
    assert res["found"] == 3 and res["complete"] == 1


def test_batch_marks_agencies_and_queue_advances(tmp_path):
    conn, aid = _seed(tmp_path)
    # before: the agency is awaiting discovery
    assert len(dbm.agencies_needing_decision_makers(conn)) == 1
    dm.discover_batch(conn, fetch=fake_fetch, limit=10)
    # after: marked complete -> drops out of the queue (no re-clog), even though
    # found could have been 0 for some agency
    assert dbm.agencies_needing_decision_makers(conn) == []
    assert dbm.get_agency_dm(conn, aid)["status"] == "complete"
    # a second batch does nothing; a reset re-queues it
    again = dm.discover_batch(conn, fetch=fake_fetch, limit=10)
    assert again["total"] == 0
    dm.discover_decision_makers(conn, aid, fetch=fake_fetch, reset=True)
    assert dbm.get_agency_dm(conn, aid)["status"] == "complete"  # re-marked


def test_needing_decision_makers_skips_no_website(tmp_path):
    conn, _ = _seed(tmp_path)
    dbm.upsert_agency(conn, "thedrum", {
        "dedup_key": "nosite", "company": "No Site", "website": ""})
    conn.commit()
    rows = dbm.agencies_needing_decision_makers(conn)
    assert [r["company"] for r in rows] == ["Acme"]


def test_start_manual_dm_guarded(tmp_path, monkeypatch):
    from chordential_oia.web import scheduler as sch
    monkeypatch.setattr(sch.discovery, "scrape_enabled", lambda: False)
    assert sch.start_manual_dm(5) is False              # disabled here
    monkeypatch.setattr(sch.discovery, "scrape_enabled", lambda: True)
    sch._dm_status["running"] = True
    try:
        assert sch.start_manual_dm(5) is False          # already running
    finally:
        sch._dm_status["running"] = False


# --------------------------------------------------------------------------- #
# Web surface — the per-agency trigger route + the detail-page render.
# --------------------------------------------------------------------------- #
def test_agency_detail_shows_decision_makers(tmp_path, monkeypatch):
    import importlib
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
        "website": "https://acme.example"})
    conn.commit()
    aid = app_mod.db.list_agencies(conn)[0]["id"]
    # discover synchronously (the route fires the same engine live)
    app_mod.decision_makers.discover_decision_makers(conn, aid, fetch=fake_fetch)
    conn.close()

    with TestClient(app_mod.app) as c:
        html = c.get(f"/agencies/{aid}").text
    assert "Decision makers" in html
    assert "Dana Reed" in html and "Executive Producer" in html
    assert "Very High" in html and "commissions" in html.lower()  # the WHY renders
