"""Re-enrichment cadence — periodically refresh stale agencies so the Signal
Detection Framework has fresh data to diff. Network faked; deterministic.
"""

import json

from chordential_oia.web import db as dbm
from chordential_oia.web import enrichment as en

SITE = {
    "https://acme.example/": """<html><head><title>Acme</title></head><body><nav>
        <a href="/what-we-do">What We Do</a></nav></body></html>""",
    "https://acme.example/what-we-do": "<body><h2>What We Do</h2><ul>"
                                       "<li>Brand Strategy</li><li>Web Design</li></ul></body>",
}


def fake_fetch(url, timeout=15.0):
    u = url if url in SITE else (url + "/" if url + "/" in SITE else url)
    return (SITE.get(u, ""), u in SITE)


def _seed(tmp_path):
    conn = dbm.connect(str(tmp_path / "re.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "acme.example", "company": "Acme", "website": "https://acme.example"})
    conn.commit()
    return conn, conn.execute("SELECT id FROM agencies").fetchone()["id"]


def test_enrich_stamps_last_enriched(tmp_path):
    conn, aid = _seed(tmp_path)
    en.enrich_agency(conn, aid, fetch=fake_fetch)
    state = dbm.get_agency_enrichment(conn, aid)
    assert state["status"] == "complete" and state.get("last_enriched")


def test_fresh_agency_is_not_due_stale_one_is(tmp_path):
    conn, aid = _seed(tmp_path)
    en.enrich_agency(conn, aid, fetch=fake_fetch)
    # just enriched -> not due within a 7-day window
    assert dbm.agencies_due_for_reenrichment(conn, stale_days=7) == []
    # backdate the stamp -> now due
    state = dbm.get_agency_enrichment(conn, aid)
    state["last_enriched"] = "2000-01-01T00:00:00+00:00"
    dbm.save_agency_enrichment(conn, aid, state)
    conn.commit()
    due = dbm.agencies_due_for_reenrichment(conn, stale_days=7)
    assert [r["id"] for r in due] == [aid]


def test_untimestamped_complete_is_due(tmp_path):
    # an agency enriched before the timestamp existed (no last_enriched) is due
    conn, aid = _seed(tmp_path)
    dbm.save_agency_enrichment(conn, aid, {
        "status": "complete", "profile": en.AgencyProfile(name="Acme").to_dict()})
    conn.commit()
    assert [r["id"] for r in dbm.agencies_due_for_reenrichment(conn, stale_days=7)] == [aid]


def test_reenrich_batch_refreshes_and_restamps(tmp_path):
    conn, aid = _seed(tmp_path)
    en.enrich_agency(conn, aid, fetch=fake_fetch)
    # make it stale
    state = dbm.get_agency_enrichment(conn, aid)
    state["last_enriched"] = "2000-01-01T00:00:00+00:00"
    dbm.save_agency_enrichment(conn, aid, state)
    conn.commit()

    res = en.reenrich_batch(conn, stale_days=7, limit=10, fetch=fake_fetch)
    assert res["due"] == 1 and res["refreshed"] == 1
    # the refresh re-stamped it current -> no longer due, profile intact
    assert dbm.agencies_due_for_reenrichment(conn, stale_days=7) == []
    fresh = dbm.get_agency_enrichment(conn, aid)
    assert fresh["last_enriched"] > "2001"
    assert "Brand Strategy" in fresh["profile"]["services"]


def test_reenrich_then_signal_diff_emits_new(tmp_path):
    # the whole point: re-enrichment that changes the profile feeds a NEW signal
    from chordential_oia.web import opportunity_signals as osig
    conn, aid = _seed(tmp_path)
    en.enrich_agency(conn, aid, fetch=fake_fetch)
    osig.detect_signals(conn, aid)                      # baseline (services only -> silent)
    before = dbm.count_opportunity_signals(conn, aid)

    # a refresh discovers a new award on the site -> profile changes
    state = dbm.get_agency_enrichment(conn, aid)
    state["profile"]["awards"] = ["Cannes Lions 2026"]
    state["last_enriched"] = "2000-01-01T00:00:00+00:00"
    dbm.save_agency_enrichment(conn, aid, state)
    conn.commit()

    osig.detect_signals(conn, aid)                      # diff -> new award signal
    assert dbm.count_opportunity_signals(conn, aid) == before + 1


def test_reenrich_blocked_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(en, "scrape_enabled", lambda: False)
    conn, aid = _seed(tmp_path)
    dbm.save_agency_enrichment(conn, aid, {
        "status": "complete", "profile": en.AgencyProfile(
            name="Acme", website="https://acme.example").to_dict()})
    conn.commit()
    res = en.reenrich_batch(conn, stale_days=7, limit=10)   # no fetch + scraping off
    assert res["due"] == 1 and res["refreshed"] == 0       # blocked, not refreshed


def test_scheduler_manual_reenrich_guarded(tmp_path, monkeypatch):
    from chordential_oia.web import scheduler as sch
    monkeypatch.setattr(sch.discovery, "scrape_enabled", lambda: False)
    assert sch.start_manual_reenrich(5) is False           # disabled here
    monkeypatch.setattr(sch.discovery, "scrape_enabled", lambda: True)
    sch._reenrich_status["running"] = True
    try:
        assert sch.start_manual_reenrich(5) is False       # already running
    finally:
        sch._reenrich_status["running"] = False
