"""Campaign Intelligence — the canonical, living per-engagement record.

Increment CI-1: the object exists, is lazy-created + seeded from upstream (opportunity,
the linked agency intelligence, the direction cards), carries per-field provenance
(kind × sources × status), and is disposed by a human. See
docs/architecture/CAMPAIGN_INTELLIGENCE.md.
"""

import importlib

import pytest

from chordential_oia.web import campaign_intelligence as ci

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


# --------------------------------------------------------------------------- #
# Domain — the epistemic-kind model + the provenance API (no web).
# --------------------------------------------------------------------------- #
def test_kind_model_is_the_four_epistemic_types():
    assert ci.KINDS == ["fact", "insight", "recommendation", "open_question"]
    # each kind has its own open + disposed status (the disposition is kind-aware)
    assert ci.KIND_OPEN_STATUS["fact"] == "needs_review"
    assert ci.KIND_DISPOSED_STATUS["recommendation"] == "accepted"
    assert ci.KIND_DISPOSED_STATUS["open_question"] == "answered"
    assert ci.is_open("needs_review") and ci.is_open("open")
    assert not ci.is_open("confirmed") and not ci.is_open("accepted")


def _seed_campaign(tmp_path, *, with_agency=True, with_direction=True):
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "ci.db"))
    dbm.init_db(conn)
    aid = None
    if with_agency:
        dbm.upsert_agency(conn, "m", {"dedup_key": "h", "company": "Halcyon Creative",
                                      "website": "x"})
        aid = conn.execute("SELECT id FROM agencies WHERE company='Halcyon Creative'"
                           ).fetchone()["id"]
        dbm.save_agency_intel(conn, aid, {"status": "complete",
            "executive_summary": {"value": "A brand-films shop, lean and anthemic."},
            "music_usage": {"value": "Original scores, brass-forward."}})
        dbm.save_agency_enrichment(conn, aid, {"status": "complete",
            "profile": {"portfolio": ["Nike Winter 2025", "Delta Skyward"]}})
    oid = conn.execute(
        "INSERT INTO opportunities (client, need, budget_min, budget_max, created_at) "
        "VALUES (?,?,?,?,?)", ("Halcyon Creative", "Holiday anthem", 18000, 24000,
                              "2026-01-01")).lastrowid
    conn.commit()
    res = dbm.resolve_opportunity_agency(conn, dbm.get_opportunity(conn, oid))
    pid = dbm.insert_project(conn, oid, "Halcyon Creative", "Holiday anthem",
                             18000, 24000, ["Composer"], "2027-11-01", agency_id=res)
    camp = dbm.ensure_campaign_for_project(conn, pid)
    if with_direction:
        dbm.update_campaign_direction(conn, camp["id"], "emotional_arc",
                                      body="Warm nostalgia to triumphant release.",
                                      complete=True)
    return dbm, conn, dbm.get_campaign(conn, camp["id"]), aid


def test_ensure_seeds_from_all_three_universes_and_is_idempotent(tmp_path):
    dbm, conn, camp, aid = _seed_campaign(tmp_path)
    ci_row = ci.ensure_for_campaign(conn, camp)
    v = ci.fields_view(conn, ci_row["id"])
    # seeded from engagement (opp) + buyer (linked agency) + direction (workspace)
    assert set(v["facets_present"]) >= {"engagement", "buyer", "direction"}
    by = {(facet, f["key"]): f for facet in v["by_facet"]
          for f in v["by_facet"][facet]}
    # engagement fact from the opportunity
    assert by[("engagement", "budget_band")]["sources"] == ["opportunity"]
    # BUYER fact reached through the Step-1 agency link — the moat now flows in
    assert by[("buyer", "how_they_work")]["sources"] == ["agency_intelligence"]
    assert "brand-films shop" in by[("buyer", "how_they_work")]["value"].lower()
    # direction fact from the workspace; marked complete → disposed (confirmed)
    d = by[("direction", "emotional_arc")]
    assert d["sources"] == ["workspace"] and d["status"] == "confirmed"
    # everything is a fact at seed; each cites a real source
    assert all(f["kind"] == "fact" for facet in v["by_facet"]
               for f in v["by_facet"][facet])
    # idempotent — same CI, same field count
    again = ci.ensure_for_campaign(conn, camp)
    assert again["id"] == ci_row["id"]
    assert ci.fields_view(conn, ci_row["id"])["counts"]["total"] == v["counts"]["total"]


def test_no_buyer_facts_without_a_linked_agency(tmp_path):
    # honesty: no link → no invented buyer intelligence
    dbm, conn, camp, _ = _seed_campaign(tmp_path, with_agency=False)
    v = ci.fields_view(conn, ci.ensure_for_campaign(conn, camp)["id"])
    assert "buyer" not in v["facets_present"]


def test_contribute_lands_open_and_dispose_is_the_human_gate(tmp_path):
    dbm, conn, camp, _ = _seed_campaign(tmp_path, with_agency=False, with_direction=False)
    ci_row = ci.ensure_for_campaign(conn, camp)
    # a producer's read is an INSIGHT, and a machine/non-owner contribution lands OPEN
    fid = ci.contribute(conn, ci_row["id"], "direction", "emotional_arc",
                        "They say warm but mean nostalgic, not saccharine.",
                        kind="insight", source="producer_debrief", contributed_by="operator")
    row = dbm.get_ci_field(conn, fid)
    assert row["kind"] == "insight" and row["status"] == "noted" and ci.is_open("noted")
    # a fact and an insight COEXIST on the same key (UNIQUE includes kind)
    ci.contribute(conn, ci_row["id"], "direction", "emotional_arc",
                  "Client asked for 'warm'.", kind="fact", source="transcript")
    keys = [(f["kind"]) for f in ci.fields_view(conn, ci_row["id"])["by_facet"]["direction"]]
    assert "fact" in keys and "insight" in keys
    # a second source merges into the SAME field's provenance, not a fork
    ci.contribute(conn, ci_row["id"], "direction", "emotional_arc",
                  "", kind="insight", source="ai")
    ins = [f for f in ci.fields_view(conn, ci_row["id"])["by_facet"]["direction"]
           if f["kind"] == "insight"][0]
    assert set(ins["sources"]) == {"producer_debrief", "ai"}
    # the human disposes → acknowledged (kind-aware)
    ci.dispose(conn, dbm.get_ci_field(conn, fid), actor="operator")
    assert dbm.get_ci_field(conn, fid)["status"] == "acknowledged"


def test_risk_flag_on_a_concern(tmp_path):
    dbm, conn, camp, _ = _seed_campaign(tmp_path, with_agency=False, with_direction=False)
    ci_row = ci.ensure_for_campaign(conn, camp)
    fid = ci.contribute(conn, ci_row["id"], "engagement", "signoff", "Unclear who signs off.",
                        kind="open_question", source="producer_debrief", is_concern=True)
    f = [x for facet in ci.fields_view(conn, ci_row["id"])["by_facet"]
         for x in ci.fields_view(conn, ci_row["id"])["by_facet"][facet] if x["id"] == fid][0]
    assert f["is_concern"] and f["kind"] == "open_question"


# --------------------------------------------------------------------------- #
# Web — the provenance panel + the disposition gate, behind the flag.
# --------------------------------------------------------------------------- #
def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import campaign_intelligence as ci_mod
    importlib.reload(ci_mod)
    from chordential_oia.web import campaigns as camp_mod
    importlib.reload(camp_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    return app_mod


def test_campaign_home_shows_intelligence_panel_and_disposes(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    app_mod.db.upsert_agency(conn, "m", {"dedup_key": "h", "company": "Halcyon Creative",
                                         "website": "x"})
    aid = conn.execute("SELECT id FROM agencies WHERE company='Halcyon Creative'"
                       ).fetchone()["id"]
    app_mod.db.save_agency_intel(conn, aid, {"status": "complete",
        "executive_summary": {"value": "A brand-films shop."}})
    oid = conn.execute(
        "INSERT INTO opportunities (client, need, budget_min, budget_max, created_at) "
        "VALUES (?,?,?,?,?)", ("Halcyon Creative", "Anthem", 18000, 24000, "2026-01-01")
    ).lastrowid
    conn.commit()
    res = app_mod.db.resolve_opportunity_agency(conn, app_mod.db.get_opportunity(conn, oid))
    pid = app_mod.db.insert_project(conn, oid, "Halcyon Creative", "Anthem",
                                    18000, 24000, ["Composer"], None, agency_id=res)
    cid = app_mod.db.ensure_campaign_for_project(conn, pid)["id"]
    conn.close()
    with TestClient(app_mod.app) as c:
        home = c.get(f"/campaign/{cid}").text
        assert "Campaign intelligence" in home
        assert "A brand-films shop." in home              # a buyer fact, inherited
        assert "agency_intelligence" in home              # its provenance
        assert ">Fact<" in home                           # the kind badge
        # dispose (confirm) an open field → one fewer Confirm button
        import re
        fid = re.search(r'name="field_id" value="(\d+)"', home).group(1)
        c.post(f"/campaign/{cid}/intelligence/dispose", data={"field_id": fid})
        home2 = c.get(f"/campaign/{cid}").text
        assert home2.count("Confirm</button>") < home.count("Confirm</button>")


def test_editing_direction_contributes_to_intelligence(tmp_path, monkeypatch):
    # the workspace writes THROUGH Campaign Intelligence — no private copy (the
    # anti-recreation contract). Editing a direction card contributes a fact to CI.
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    pid = app_mod.db.insert_project(conn, None, "Acme", "Spot", 0, 0, ["Composer"], None)
    cid = app_mod.db.ensure_campaign_for_project(conn, pid)["id"]
    conn.close()
    with TestClient(app_mod.app) as c:
        c.post(f"/campaign/{cid}/direction",
               data={"section": "producer_notes",
                     "body": "Keep it human, no synth pads.", "complete": "1"})
        conn = app_mod.db.connect()
        try:
            ci_row = app_mod.db.ci_for_campaign(conn, cid)
            fields = app_mod.db.list_ci_fields(conn, ci_row["id"])
        finally:
            conn.close()
        f = [x for x in fields if x["key"] == "producer_notes"][0]
        assert f["value"] == "Keep it human, no synth pads."
        assert "workspace" in f["sources"] and f["status"] == "confirmed"  # complete → disposed
