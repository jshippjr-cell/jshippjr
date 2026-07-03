"""Campaign Intake anchored on the Opportunity (ADR-0013).

CI is born on the opportunity while qualifying/pursuing; human edits are authoritative and
the machine never clobbers them (disagreements surface as conflicts); confirmed engagement
facts write back to the opportunity so downstream engines recompute; and at Won the campaign
adopts the SAME CI in place — nothing recreated.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
from chordential_oia.web import campaign_intake as intake
from chordential_oia.web import campaign_intelligence as ci

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def _opp(dbm, conn, *, budget_min=8000, budget_max=15000, contact="Sarah Chen"):
    o = Opportunity(client="Halcyon Creative", need="Holiday anthem",
                    description="National holiday campaign, original composition.",
                    buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
                    budget_min=budget_min, budget_max=budget_max)
    opp_id = dbm.insert_opportunity(conn, o)
    if contact:
        conn.execute("UPDATE opportunities SET contact_name=?, contact_role=? WHERE id=?",
                     (contact, "Creative Director", opp_id))
        conn.commit()
    return opp_id


def _db(tmp_path):
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "o.db"))
    dbm.init_db(conn)
    return dbm, conn


# --------------------------------------------------------------------------- #
# Birth on the opportunity + seed.
# --------------------------------------------------------------------------- #
def test_ci_is_born_on_the_opportunity_and_seeds_from_it(tmp_path):
    dbm, conn = _db(tmp_path)
    opp_id = _opp(conn=conn, dbm=dbm)
    row = dbm.get_opportunity(conn, opp_id)
    ci_row = ci.ensure_for_opportunity(conn, row)
    # anchored to the opportunity; no campaign yet
    assert ci_row["opp_id"] == opp_id and ci_row["campaign_id"] is None
    # idempotent
    assert ci.ensure_for_opportunity(conn, row)["id"] == ci_row["id"]
    fields = {(f["facet"], f["key"]): f for f in dbm.list_ci_fields(conn, ci_row["id"])}
    assert fields[("engagement", "budget_band")]["value"].startswith("$")
    assert "Sarah Chen" in fields[("buyer", "decision_makers")]["value"]
    # seeded facts await a human — machine proposes (not confirmed)
    assert fields[("engagement", "budget_band")]["status"] == "needs_review"


# --------------------------------------------------------------------------- #
# Write-back — a confirmed engagement fact flows to the opportunity + re-evaluates.
# --------------------------------------------------------------------------- #
def test_ingest_writes_budget_back_to_the_opportunity(tmp_path):
    dbm, conn = _db(tmp_path)
    opp_id = _opp(conn=conn, dbm=dbm, budget_min=8000, budget_max=15000)
    row = dbm.get_opportunity(conn, opp_id)
    intake.ingest_opportunity(conn, row, intake.OBJECTIVE,
                              "Budget is $30,000 to $40,000. Need it by November.")
    after = dbm.get_opportunity(conn, opp_id)
    assert after["budget_min"] == 30000 and after["budget_max"] == 40000


# --------------------------------------------------------------------------- #
# Human edits are authoritative; the machine never clobbers them.
# --------------------------------------------------------------------------- #
def test_human_edit_is_authoritative_and_a_disagreement_becomes_a_conflict(tmp_path):
    dbm, conn = _db(tmp_path)
    opp_id = _opp(conn=conn, dbm=dbm)
    row = dbm.get_opportunity(conn, opp_id)
    ci_row = ci.ensure_for_opportunity(conn, row)
    # the human fixes the budget by hand → authoritative
    ci.edit_or_create(conn, ci_row["id"], "engagement", "budget_band", "fact",
                      "$50,000 flat", actor="operator")
    fld = [f for f in dbm.list_ci_fields(conn, ci_row["id"])
           if f["key"] == "budget_band"][0]
    assert fld["human_value"] == 1 and fld["value"] == "$50,000 flat"
    # a later capture proposes a DIFFERENT budget → parked as a conflict, human value stands
    intake.ingest_opportunity(conn, row, intake.OBJECTIVE, "Budget is $12,000.")
    fld = dbm.get_ci_field(conn, fld["id"])
    assert fld["value"] == "$50,000 flat"            # not clobbered
    assert (fld["proposed_value"] or "").strip()     # the disagreement is surfaced
    # resolve by accepting the machine's value
    ci.resolve_conflict(conn, fld["id"], accept=True, actor="operator")
    fld = dbm.get_ci_field(conn, fld["id"])
    assert "12,000" in fld["value"] and not fld["proposed_value"]


# --------------------------------------------------------------------------- #
# Won → the campaign adopts the SAME CI in place (nothing recreated).
# --------------------------------------------------------------------------- #
def test_won_campaign_inherits_the_same_ci_in_place(tmp_path):
    dbm, conn = _db(tmp_path)
    opp_id = _opp(conn=conn, dbm=dbm)
    row = dbm.get_opportunity(conn, opp_id)
    ci_row = ci.ensure_for_opportunity(conn, row)
    # a fact the operator confirmed while pursuing
    ci.edit_or_create(conn, ci_row["id"], "direction", "emotional_arc", "fact",
                      "nostalgic, warm, not saccharine", actor="operator")
    # convert to a project + open its campaign
    pid = dbm.insert_project(conn, opp_id, row["client"], row["need"],
                             row["budget_min"], row["budget_max"], ["Composer"], None)
    camp = dbm.get_campaign(conn, dbm.ensure_campaign_for_project(conn, pid)["id"])
    adopted = ci.ensure_for_campaign(conn, camp)
    # SAME record — adopted in place, campaign link now set, opp link preserved
    assert adopted["id"] == ci_row["id"]
    assert adopted["campaign_id"] == camp["id"] and adopted["opp_id"] == opp_id
    # only one CI exists for this opportunity (never a second)
    n = conn.execute("SELECT COUNT(*) c FROM campaign_intelligence WHERE opp_id=?",
                     (opp_id,)).fetchone()["c"]
    assert n == 1
    # the pursued fact carried across the Won boundary
    arc = [f for f in dbm.list_ci_fields(conn, adopted["id"])
           if f["key"] == "emotional_arc"][0]
    assert "nostalgic" in arc["value"]


# --------------------------------------------------------------------------- #
# Web — the Update Intelligence panel, edit, and identity routes.
# --------------------------------------------------------------------------- #
def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    for m in ("db", "campaign_intelligence", "campaign_intake", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def test_opportunity_panel_analyze_edit_and_identity(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    opp_id = _opp(conn=conn, dbm=app_mod.db)
    conn.close()
    with TestClient(app_mod.app) as c:
        # the panel renders above the tabs on the opportunity page
        home = c.get(f"/opportunity/{opp_id}").text
        assert "Campaign Intelligence" in home and "Analyze &amp; update" in home
        # Analyze a discovery note → summary params + facts land
        r = c.post(f"/opportunity/{opp_id}/intelligence/analyze", follow_redirects=False,
                   data={"stance": "objective", "modality": "notes",
                         "text": "Budget is $18,000 to $24,000. Need it by November. "
                                 ":60 anthem plus stems."})
        loc = r.headers["location"]
        assert "understood=" in loc and "#intelligence" in loc
        # edit a field by hand → authoritative
        conn = app_mod.db.connect()
        ci_row = app_mod.db.ci_for_opportunity(conn, opp_id)
        fld = [f for f in app_mod.db.list_ci_fields(conn, ci_row["id"])
               if f["key"] == "deadline"][0]
        conn.close()
        c.post(f"/opportunity/{opp_id}/intelligence/field",
               data={"field_id": str(fld["id"]), "facet": "engagement",
                     "key": "deadline", "kind": "fact", "value": "Nov 15 air date"})
        conn = app_mod.db.connect()
        fld = app_mod.db.get_ci_field(conn, fld["id"])
        conn.close()
        assert fld["value"] == "Nov 15 air date" and fld["human_value"] == 1
        # rename the title + buyer via the identity route
        c.post(f"/opportunity/{opp_id}/identity",
               data={"need": "Halcyon holiday film", "client": "Halcyon Creative Co"})
        conn = app_mod.db.connect()
        row = app_mod.db.get_opportunity(conn, opp_id)
        conn.close()
        assert row["need"] == "Halcyon holiday film" and row["client"] == "Halcyon Creative Co"
