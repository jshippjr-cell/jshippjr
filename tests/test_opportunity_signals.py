"""Signal Detection Framework — change detection over the collected Agency
Profile, emitting standardized opportunity Signals with a Music Trigger on each.
Pure computation; no network. The cardinal behaviour: baseline first, then emit
only NEW changes, never duplicates, each with evidence + an expiry.
"""

import importlib

from chordential_oia.web import db as dbm
from chordential_oia.web import enrichment as en
from chordential_oia.web import opportunity_signals as osig
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia.web import opportunity_signals  # noqa: E402


def _seed(tmp_path, profile, *, status="complete"):
    conn = dbm.connect(str(tmp_path / "sig.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "agencyspotter", {
        "dedup_key": "akqa.com", "company": "AKQA", "website": "https://akqa.com"})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    dbm.save_agency_enrichment(conn, aid, {"status": status, "profile": profile.to_dict()})
    conn.commit()
    return conn, aid


_BASE = en.AgencyProfile(
    name="AKQA", website="https://akqa.com",
    open_roles=["Executive Producer", "Senior Editor"],
    news=[{"title": "AKQA wins global Nike account", "url": "u1"},
          {"title": "AKQA opens new Tokyo office", "url": "u2"}],
    portfolio=["Old cinematic brand film", "Old web project"],
    awards=["Cannes Lions 2023"], clients=["IBM"],
    leadership=[{"name": "Jane Doe", "title": "CEO"}])


# --------------------------------------------------------------------------- #
# Music Trigger Detector — the distinction that makes outreach well-timed.
# --------------------------------------------------------------------------- #
def test_music_trigger_distinguishes_events():
    assert osig.music_trigger("Hiring", "Music Producer")[0] == "Very High"
    assert osig.music_trigger("Hiring", "Executive Producer")[0] == "Very High"
    assert osig.music_trigger("Hiring", "HR Coordinator")[0] == "Low"
    assert osig.music_trigger("New work", "cinematic brand film")[0] == "Very High"
    assert osig.music_trigger("New work", "new website design")[0] == "Low"
    assert osig.music_trigger("New client", "global agency of record")[0] == "Very High"
    assert osig.music_trigger("Expansion", "new office")[0] == "Low"


# --------------------------------------------------------------------------- #
# Baseline vs change.
# --------------------------------------------------------------------------- #
def test_baseline_emits_current_activity_only(tmp_path):
    conn, aid = _seed(tmp_path, _BASE)
    res = osig.detect_signals(conn, aid)
    assert res["status"] == "complete" and res["baselined"] is True
    tl = osig.agency_timeline(conn, aid)
    types = sorted(s["event_type"] for s in tl)
    # hiring + news emit on baseline; back-catalogue (portfolio/awards/clients/
    # leadership) is baselined SILENTLY
    assert "Hiring" in types and "New client" in types        # the Nike win
    assert "Award" not in types and "New work" not in types
    assert len(tl) == 4                                        # 2 hires + 2 news


def test_rescan_unchanged_emits_nothing(tmp_path):
    conn, aid = _seed(tmp_path, _BASE)
    osig.detect_signals(conn, aid)
    before = dbm.count_opportunity_signals(conn, aid)
    res = osig.detect_signals(conn, aid)
    assert res["status"] == "unchanged" and res["new"] == 0
    assert dbm.count_opportunity_signals(conn, aid) == before   # no duplicates


def test_change_after_baseline_emits_only_new(tmp_path):
    conn, aid = _seed(tmp_path, _BASE)
    osig.detect_signals(conn, aid)                              # baseline

    changed = en.AgencyProfile.from_dict(_BASE.to_dict())
    changed.awards.append("D&AD Pencil 2026")                  # new back-catalogue item
    changed.portfolio.append("New cinematic brand film for Verizon")
    changed.clients.append("Verizon")
    changed.open_roles.append("Music Producer")
    dbm.save_agency_enrichment(conn, aid, {"status": "complete", "profile": changed.to_dict()})
    conn.commit()

    res = osig.detect_signals(conn, aid)
    assert res["new"] == 4
    newest = osig.agency_timeline(conn, aid)[:4]
    summaries = " ".join(s["summary"] for s in newest)
    assert "Verizon" in summaries and "D&AD" in summaries and "Music Producer" in summaries
    # the new cinematic work + music hire are flagged Very High music relevance
    vh = [s for s in newest if s["music_relevance"] == "Very High"]
    assert any("cinematic" in s["summary"].lower() for s in vh)
    # every signal carries evidence + an expiry
    for s in newest:
        assert s["evidence"] and s["expires_at"]


def test_signals_skipped_until_enriched(tmp_path):
    conn, aid = _seed(tmp_path, _BASE, status="running")
    res = osig.detect_signals(conn, aid)
    assert res["status"] == "skipped" and dbm.count_opportunity_signals(conn, aid) == 0


def test_batch_scans_only_enriched_and_rotates(tmp_path):
    conn, aid = _seed(tmp_path, _BASE)
    dbm.upsert_agency(conn, "thedrum", {
        "dedup_key": "noenrich", "company": "NoEnrich", "website": "https://x.example"})
    conn.commit()
    res = osig.detect_batch(conn, limit=10)
    assert res["scanned"] == 1 and res["new"] >= 1             # only the enriched one
    assert res["considered"] == 1                             # the un-enriched is excluded


def test_expired_signals_filtered_from_active(tmp_path):
    conn, aid = _seed(tmp_path, _BASE)
    osig.detect_signals(conn, aid)
    # force one signal to be already expired
    conn.execute("UPDATE opportunity_signals SET expires_at='2000-01-01T00:00:00+00:00' "
                 "WHERE agency_id=? LIMIT 1", (aid,))
    conn.commit()
    active = dbm.count_opportunity_signals(conn, aid, active_only=True)
    allsig = dbm.count_opportunity_signals(conn, aid)
    assert active == allsig - 1


def test_detail_page_renders_timeline(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
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
    app_mod.db.save_agency_enrichment(conn, aid, {"status": "complete", "profile": _BASE.to_dict()})
    conn.commit()
    opportunity_signals.detect_signals(conn, aid)
    conn.close()

    with TestClient(app_mod.app) as c:
        html = c.get(f"/agencies/{aid}").text
    assert "Opportunity timeline" in html
    assert "Nike" in html and "Very High" in html             # the win + a music tag
