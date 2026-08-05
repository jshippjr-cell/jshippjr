"""Deleting a demo account: the opportunity + everything anchored to it, with confirmation."""
import importlib

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia.web import campaign_intelligence  # noqa: E402


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.setenv("CHORDENTIAL_INTAKE_LLM", "0")
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "procurement", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def test_delete_opportunity_cascades_and_confirms(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    db = app_mod.db
    conn = db.connect(); db.init_db(conn)
    # a fully-populated demo account: opp + CI + capture + meeting + procurement + project
    oid = db.insert_opportunity(conn, Opportunity(
        client="Fake Client A", need="Demo anthem", description="x",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    row = db.get_opportunity(conn, oid)
    cid = campaign_intelligence.ensure_for_opportunity(conn, row)["id"]
    campaign_intelligence.contribute(conn, cid, "commercial",
        "procurement_requirements", "We need a W-9.", kind="fact", source="discovery_call")
    db.create_meeting(conn, opp_id=oid, start_at="2026-07-01T14:00:00+00:00", status="ingested")
    # Reached directly, not through `app_mod`: ADR-0044 moved the /opportunity routes
    # out, and with them app.py's need to import this engine. app.py is the route
    # layer, not a namespace for the package.
    from chordential_oia.web import procurement
    procurement.discover_from_ci(conn, oid, cid)
    token = db.ensure_share_token(conn, oid)
    pid = db.insert_project(conn, oid, "Fake Client A", "Demo anthem", 0, 0, ["Composer"],
                            share_token=token)
    # a SECOND opp for the same client — must survive (client-scoped data isn't wiped)
    oid2 = db.insert_opportunity(conn, Opportunity(
        client="Fake Client A", need="Second deal", description="x",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    conn.close()

    with TestClient(app_mod.app) as c:
        # the inbox row carries a delete control
        page = c.get("/inbox").text
        assert f"/opportunity/{oid}/delete" in page
        assert "cannot be undone" in page          # the confirm() copy is in the DOM
        # delete it
        r = c.post(f"/opportunity/{oid}/delete", data={"return_to": "/inbox"},
                   follow_redirects=False)
        assert r.status_code == 303 and "deleted=" in r.headers["location"]

    conn = db.connect()
    # the opp and ALL its anchored rows are gone
    assert db.get_opportunity(conn, oid) is None
    assert db.project_for_opp(conn, oid) is None
    assert db.list_procurement_requirements(conn, oid) == []
    assert db.list_meetings(conn, oid) == []
    assert conn.execute("SELECT COUNT(*) n FROM campaign_intelligence WHERE opp_id=?",
                        (oid,)).fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) n FROM campaign_intelligence_field WHERE ci_id=?",
                        (cid,)).fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) n FROM projects WHERE id=?",
                        (pid,)).fetchone()["n"] == 0
    # the sibling deal for the same client is untouched
    assert db.get_opportunity(conn, oid2) is not None
    # deleting a non-existent opp is a safe no-op
    assert db.delete_opportunity(conn, 999999) == {"deleted": False}
    conn.close()
