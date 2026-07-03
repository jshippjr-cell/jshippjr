"""Campaign Workspace (Creative OS) — increment 1: the campaign foundation +
structured creative direction, behind the CHORDENTIAL_CAMPAIGN_WORKSPACE flag.

The workspace elevates a project into "one screen, one campaign, everything." This
increment establishes the campaign container (lazy-created per project, no bulk
migration), the creative-timeline phase model, and the structured, checklist-able
creative direction — the single most "Creative OS, not generic PM" object. See
docs/campaign-workspace-prd.md.
"""

import importlib

import pytest

from chordential_oia.web import campaigns

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


# --------------------------------------------------------------------------- #
# Domain model (no web) — the creative timeline + direction sections.
# --------------------------------------------------------------------------- #
def test_phase_model_is_a_creative_arc_not_a_kanban():
    # The phases are the campaign's creative arc, in order.
    assert campaigns.PHASES[0] == "Briefing"
    assert "Internal Review" in campaigns.PHASES and "Agency Review" in campaigns.PHASES
    assert campaigns.PHASES[-1] == "Archived"
    assert campaigns.next_phase("Briefing") == "Direction"
    assert campaigns.next_phase("Archived") is None          # end of the arc
    assert campaigns.phase_index("Agency Review") > campaigns.phase_index("Briefing")


def test_direction_sections_are_the_music_brief():
    keys = campaigns.DIRECTION_KEYS
    # The composer's brief, as structured sections — not a description field.
    for expected in ("emotional_arc", "reference_playlist", "brand_history",
                     "previous_campaigns"):
        assert expected in keys
    assert campaigns.DIRECTION_LABELS["emotional_arc"] == "Emotional Arc"


def test_workspace_enabled_defaults_on(monkeypatch):
    # Dogfooding in prod: the flag defaults ON (a code default deploys reliably);
    # only an explicit "0"/false disables it.
    monkeypatch.delenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", raising=False)
    assert campaigns.workspace_enabled() is True
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "0")
    assert campaigns.workspace_enabled() is False
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    assert campaigns.workspace_enabled() is True


def test_hydrate_phase_from_delivery_maps_in_flight_work():
    assert campaigns.hydrate_phase_from_delivery({"state": "Delivered"}) == "Delivered"
    assert campaigns.hydrate_phase_from_delivery({"state": "In review"}) == "Agency Review"
    assert campaigns.hydrate_phase_from_delivery({}) == "Briefing"


# --------------------------------------------------------------------------- #
# Storage — lazy campaign creation + direction upsert (no web).
# --------------------------------------------------------------------------- #
def test_ensure_campaign_for_project_is_lazy_and_idempotent(tmp_path):
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "c.db"))
    dbm.init_db(conn)
    pid = dbm.insert_project(conn, None, "Nike", "Holiday 2027 anthem",
                             18000, 24000, ["Composer"], "2027-11-01")
    c1 = dbm.ensure_campaign_for_project(conn, pid)
    assert c1 is not None
    # hydrated from the project
    assert c1["title"] == "Holiday 2027 anthem" and c1["brand"] == "Nike"
    assert c1["project_id"] == pid and c1["budget_min"] == 18000
    # idempotent — opening again returns the same campaign, never a duplicate
    c2 = dbm.ensure_campaign_for_project(conn, pid)
    assert c2["id"] == c1["id"]
    assert len(dbm.list_campaigns(conn)) == 1
    # no such project → None (never a stray campaign)
    assert dbm.ensure_campaign_for_project(conn, 99999) is None


def test_direction_upsert_merges_one_field(tmp_path):
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "d.db"))
    dbm.init_db(conn)
    pid = dbm.insert_project(conn, None, "Acme", "Spot", 0, 0, ["Composer"], None)
    cid = dbm.ensure_campaign_for_project(conn, pid)["id"]
    dbm.update_campaign_direction(conn, cid, "emotional_arc", body="Warm to triumphant.")
    dbm.update_campaign_direction(conn, cid, "emotional_arc", complete=True)  # body preserved
    d = dbm.get_campaign_direction(conn, cid)
    assert d["emotional_arc"]["body"] == "Warm to triumphant."
    assert d["emotional_arc"]["complete"] == 1
    assert campaigns.direction_completeness(d) == {"done": 1, "total": 6, "pct": 17}


# --------------------------------------------------------------------------- #
# Buyer link — agency_id threads Opportunity → Project → Campaign (step 1 of the
# Discovery Intelligence lineage). The point: the campaign reaches the agency's
# intelligence, not just a client name.
# --------------------------------------------------------------------------- #
def _agency_with_intel(dbm, conn, company="Halcyon Creative"):
    dbm.upsert_agency(conn, "manual", {"dedup_key": company.lower(),
                                       "company": company, "website": "https://x.example"})
    aid = conn.execute("SELECT id FROM agencies WHERE company=?", (company,)).fetchone()["id"]
    dbm.save_agency_intel(conn, aid, {"status": "complete",
                                      "executive_summary": {"value": "A brand-films shop."}})
    conn.commit()
    return aid


def test_agency_id_threads_opp_to_project_to_campaign(tmp_path):
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "thread.db"))
    dbm.init_db(conn)
    aid = _agency_with_intel(dbm, conn)
    oid = conn.execute(
        "INSERT INTO opportunities (client, need, budget_min, budget_max, created_at) "
        "VALUES (?,?,?,?,?)", ("Halcyon Creative", "Anthem", 18000, 24000, "2026-01-01")
    ).lastrowid
    conn.commit()

    # the source of the thread: resolve the opp's agency by name (and record it)
    resolved = dbm.resolve_opportunity_agency(conn, dbm.get_opportunity(conn, oid))
    assert resolved == aid
    assert dbm.get_opportunity(conn, oid)["agency_id"] == aid   # recorded on the opp

    # project inherits it; campaign inherits it from the project
    pid = dbm.insert_project(conn, oid, "Halcyon Creative", "Anthem",
                             18000, 24000, ["Composer"], agency_id=resolved)
    assert dbm.get_project(conn, pid)["agency_id"] == aid
    camp = dbm.ensure_campaign_for_project(conn, pid)
    assert camp["agency_id"] == aid

    # the whole point: the campaign can now REACH the agency's intelligence
    assert dbm.get_agency_intel(conn, camp["agency_id"])["status"] == "complete"


def test_campaign_backfills_agency_from_opp_when_project_unlinked(tmp_path):
    # An older project created before the link exists: the campaign still connects,
    # falling back to the opportunity's resolved agency.
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "bf.db"))
    dbm.init_db(conn)
    aid = _agency_with_intel(dbm, conn, company="Northwind")
    oid = conn.execute(
        "INSERT INTO opportunities (client, need, created_at) VALUES (?,?,?)",
        ("Northwind", "Spot", "2026-01-01")).lastrowid
    conn.commit()
    pid = dbm.insert_project(conn, oid, "Northwind", "Spot", 0, 0, ["Composer"])  # no agency_id
    assert dbm.get_project(conn, pid)["agency_id"] is None
    camp = dbm.ensure_campaign_for_project(conn, pid)
    assert camp["agency_id"] == aid                            # backfilled via the opp/name


def test_no_false_agency_link_without_exact_name_match(tmp_path):
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "nf.db"))
    dbm.init_db(conn)
    _agency_with_intel(dbm, conn, company="Halcyon Creative")
    oid = conn.execute(
        "INSERT INTO opportunities (client, need, created_at) VALUES (?,?,?)",
        ("Totally Different Co", "Spot", "2026-01-01")).lastrowid
    conn.commit()
    # exact match only — a wrong link would attach the wrong buyer intel (worse than none)
    assert dbm.resolve_opportunity_agency(conn, dbm.get_opportunity(conn, oid)) is None
    pid = dbm.insert_project(conn, oid, "Totally Different Co", "Spot", 0, 0, ["Composer"])
    camp = dbm.ensure_campaign_for_project(conn, pid)
    assert camp["agency_id"] is None


# --------------------------------------------------------------------------- #
# Web — flagged routes. OFF by default (product untouched); ON = the workspace.
# --------------------------------------------------------------------------- #
def _app(tmp_path, monkeypatch, *, flag: bool):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    # The flag defaults ON now (dogfooding in prod); "0" explicitly hides it.
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1" if flag else "0")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import campaigns as camp_mod
    importlib.reload(camp_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    return app_mod


def test_workspace_disabled_hides_everything(tmp_path, monkeypatch):
    # CHORDENTIAL_CAMPAIGN_WORKSPACE=0 hides the whole module (routes 404, no entry
    # point), so it can always be turned back off cleanly.
    app_mod = _app(tmp_path, monkeypatch, flag=False)
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    pid = app_mod.db.insert_project(conn, None, "Acme", "Spot", 0, 0, ["Composer"], None)
    conn.close()
    with TestClient(app_mod.app) as c:
        # routes 404 when the module is disabled
        assert c.get("/campaign/1").status_code == 404
        assert c.post(f"/project/{pid}/campaign/open",
                      follow_redirects=False).status_code == 404
        # the project page is unchanged — no workspace entry point
        page = c.get(f"/project/{pid}").text
        assert "Campaign workspace" not in page
        assert c.get(f"/project/{pid}").status_code == 200


def test_open_campaign_and_edit_direction_and_phase(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch, flag=True)
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    pid = app_mod.db.insert_project(conn, None, "Nike", "Nike Holiday 2027",
                                    18000, 24000, ["Composer"], "2027-11-01")
    conn.close()
    with TestClient(app_mod.app) as c:
        # the project page now offers the workspace
        assert "Campaign workspace" in c.get(f"/project/{pid}").text
        # open (lazy-create) → redirect to the campaign
        r = c.post(f"/project/{pid}/campaign/open", follow_redirects=False)
        assert r.status_code == 303
        cid = r.headers["location"].split("/")[-1]
        home = c.get(f"/campaign/{cid}").text
        # the Creative OS surface: creative timeline + structured direction
        assert "Nike Holiday 2027" in home
        assert "Briefing" in home and "Agency Review" in home        # the arc
        assert "Emotional Arc" in home and "Brand History" in home   # the brief
        # edit a direction section — saves + surfaces + moves the meter
        c.post(f"/campaign/{cid}/direction",
               data={"section": "emotional_arc",
                     "body": "Warm nostalgia to triumphant release.", "complete": "1"})
        home2 = c.get(f"/campaign/{cid}").text
        assert "Warm nostalgia to triumphant release." in home2
        assert "<b>1</b>/6" in home2
        # advance the phase (human-driven)
        c.post(f"/campaign/{cid}/phase", data={"phase": "Direction"})
        assert "Phase · <b>Direction</b>" in c.get(f"/campaign/{cid}").text
        # opening again is idempotent — same campaign, no duplicate
        r2 = c.post(f"/project/{pid}/campaign/open", follow_redirects=False)
        assert r2.headers["location"].split("/")[-1] == cid


def test_direction_and_phase_reject_unknown_values(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch, flag=True)
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    pid = app_mod.db.insert_project(conn, None, "X", "Y", 0, 0, ["Composer"], None)
    cid = app_mod.db.ensure_campaign_for_project(conn, pid)["id"]
    conn.close()
    with TestClient(app_mod.app) as c:
        assert c.post(f"/campaign/{cid}/direction",
                      data={"section": "not_a_section", "body": "x"}).status_code == 400
        assert c.post(f"/campaign/{cid}/phase",
                      data={"phase": "Not A Phase"}).status_code == 400
        assert c.get("/campaign/99999").status_code == 404


def test_campaign_home_surfaces_and_manages_the_agency_link(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch, flag=True)
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    aid = _agency_with_intel(app_mod.db, conn, company="Halcyon Creative")
    oid = conn.execute(
        "INSERT INTO opportunities (client, need, created_at) VALUES (?,?,?)",
        ("Halcyon Creative", "Anthem", "2026-01-01")).lastrowid
    conn.commit()
    resolved = app_mod.db.resolve_opportunity_agency(conn, app_mod.db.get_opportunity(conn, oid))
    pid = app_mod.db.insert_project(conn, oid, "Halcyon Creative", "Anthem",
                                    0, 0, ["Composer"], agency_id=resolved)
    cid = app_mod.db.ensure_campaign_for_project(conn, pid)["id"]
    conn.close()
    with TestClient(app_mod.app) as c:
        home = c.get(f"/campaign/{cid}").text
        # the buyer thread is visible + intelligence is reachable to inherit next
        assert "Linked to agency intelligence" in home
        assert "Halcyon Creative" in home
        assert "company intelligence available to inherit" in home
        # unlink, then re-match by name
        c.post(f"/campaign/{cid}/agency", data={"action": "unlink"})
        assert "No agency linked" in c.get(f"/campaign/{cid}").text
        c.post(f"/campaign/{cid}/agency", data={"action": "match"})
        assert "Linked to agency intelligence" in c.get(f"/campaign/{cid}").text
