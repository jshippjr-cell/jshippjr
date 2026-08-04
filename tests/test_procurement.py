"""Procurement Intelligence (ADR-0022): discover from CI (never hardcoded), adaptive checklist,
document generation from the one Company Profile, the workspace, audit, and client learning.
"""
import importlib

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
# Reached directly, not through `app_mod`: ADR-0044 moved the /opportunity routes
# out of app.py and with them app.py's need to import this engine.
from chordential_oia.web import procurement


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.setenv("CHORDENTIAL_INTAKE_LLM", "0")
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "procurement", "campaigns", "kickoff", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _opp_with_procurement(app_mod, conn, client="Vance Athletic", text=None):
    oid = app_mod.db.insert_opportunity(conn, Opportunity(
        client=client, need="Holiday anthem", description="x",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    row = app_mod.db.get_opportunity(conn, oid)
    cid = app_mod.campaign_intelligence.ensure_for_opportunity(conn, row)["id"]
    text = text or ("We'll need your W-9 before issuing the PO, plus a COI, and you'll "
                    "register in our vendor portal. We pay Net 60.")
    app_mod.campaign_intelligence.contribute(
        conn, cid, "commercial", "procurement_requirements", text,
        kind="fact", source="discovery_call", confidence=95)
    return oid


# --------------------------------------------------------------------------- #
# Discovery is adaptive — two clients, two different checklists; never hardcoded.
# --------------------------------------------------------------------------- #
def test_discovery_is_adaptive_per_client(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    P = procurement
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    a = _opp_with_procurement(app_mod, conn, "Client A",
                              text="Just send us a W-9 and an ACH form.")
    b = _opp_with_procurement(app_mod, conn, "Client B",
                              text="You'll need a COI, an MSA, vendor portal registration, "
                                   "and a security questionnaire.")
    P.discover_from_ci(conn, a)
    P.discover_from_ci(conn, b)
    keys_a = sorted(r["req_key"] for r in app_mod.db.list_procurement_requirements(conn, a))
    keys_b = sorted(r["req_key"] for r in app_mod.db.list_procurement_requirements(conn, b))
    conn.close()
    assert keys_a == ["ach", "w9"]
    assert set(keys_b) == {"coi", "msa", "vendor_portal", "security_questionnaire"}
    assert keys_a != keys_b            # no two clients need be alike


# --------------------------------------------------------------------------- #
# Document generation: real docs from the profile; placeholders when it can't.
# --------------------------------------------------------------------------- #
def test_generation_real_and_placeholder(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    P = procurement
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = _opp_with_procurement(app_mod, conn)
    P.discover_from_ci(conn, oid)
    app_mod.db.save_company_profile(conn, {
        "legal_name": "Chordential LLC", "ein": "88-1234567",
        "business_address": "1 Studio Way", "bank_name": "First Bank",
        "routing": "123456789", "account": "000111", "finance_contact": "ap@chordential.com"})
    w9 = P.generate_document(conn, oid, "w9")
    assert not w9["placeholder"] and "88-1234567" in w9["text"] and not w9["missing"]
    coi = P.generate_document(conn, oid, "coi")
    assert coi["placeholder"] and "cannot auto-generate" in coi["text"].lower()
    # missing-info detection: a bare profile flags the gaps rather than faking them
    app_mod.db.save_company_profile(conn, {"legal_name": "Chordential LLC"})
    ach = P.generate_document(conn, oid, "ach")
    assert "routing" in [m for m in ach["missing"]] or "bank_name" in ach["missing"]
    conn.close()


# --------------------------------------------------------------------------- #
# The workspace routes: discover on load, generate, mark complete, audit, learn.
# --------------------------------------------------------------------------- #
def test_workspace_flow_and_learning(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = _opp_with_procurement(app_mod, conn)
    app_mod.db.save_company_profile(conn, {"legal_name": "Chordential LLC", "ein": "88-1"})
    conn.close()

    with TestClient(app_mod.app) as c:
        # loading the workspace discovers requirements from CI
        page = c.get(f"/opportunity/{oid}/procurement").text
        assert "Procurement readiness" in page
        assert "W-9" in page and "Certificate of Insurance" in page   # discovered
        assert "Upload to the client's procurement portal" in page    # portal detected
        conn = app_mod.db.connect()
        reqs = {r["req_key"]: r for r in app_mod.db.list_procurement_requirements(conn, oid)}
        conn.close()
        # generate the W-9 → status advances, artifact viewable, audit logs it
        c.post(f"/opportunity/{oid}/procurement/{reqs['w9']['id']}/generate")
        view = c.get(f"/opportunity/{oid}/procurement/{reqs['w9']['id']}/view")
        assert view.status_code == 200 and "FORM W-9" in view.text
        # mark every active requirement complete
        conn = app_mod.db.connect()
        for r in app_mod.db.list_procurement_requirements(conn, oid):
            c.post(f"/opportunity/{oid}/procurement/{r['id']}/status", data={"status": "complete"})
        conn.close()
        # complete → learns for this client
        c.post(f"/opportunity/{oid}/procurement/complete")
        conn = app_mod.db.connect()
        hist = app_mod.db.get_client_procurement_history(conn, "Vance Athletic")
        events = app_mod.db.list_procurement_events(conn, oid)
        conn.close()
        assert set(hist["required"]) >= {"w9", "coi", "vendor_portal"}
        assert any(e["verb"] == "complete" for e in events)         # audit trail
        assert any(e["verb"] == "generated" for e in events)

        # a NEW campaign for the SAME client pre-loads from history (onboarding compounds)
        conn = app_mod.db.connect()
        oid2 = app_mod.db.insert_opportunity(conn, Opportunity(
            client="Vance Athletic", need="Spring push", description="x",
            buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
            budget_min=0, budget_max=0))
        conn.close()
        c.get(f"/opportunity/{oid2}/procurement")   # seeds on load
        conn = app_mod.db.connect()
        keys2 = {r["req_key"] for r in app_mod.db.list_procurement_requirements(conn, oid2)}
        conn.close()
        assert "w9" in keys2 and "vendor_portal" in keys2          # inherited, no re-discovery


# --------------------------------------------------------------------------- #
# Kickoff checklist now reflects REAL procurement state (no more hardcoded placeholder).
# --------------------------------------------------------------------------- #
def test_kickoff_procurement_line_is_real(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    # a client with real procurement needs
    oid = _opp_with_procurement(app_mod, conn)
    opp = app_mod.db.get_opportunity(conn, oid)
    line = app_mod.kickoff._procurement_line(conn, app_mod.db, opp)
    assert line["state"] == "pending" and "portal onboarding" in line["na_note"]
    # a client that mentioned nothing → honestly "Nothing required"
    oid2 = app_mod.db.insert_opportunity(conn, Opportunity(
        client="Quiet Co", need="Jingle", description="x",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    app_mod.campaign_intelligence.ensure_for_opportunity(conn, app_mod.db.get_opportunity(conn, oid2))
    line2 = app_mod.kickoff._procurement_line(conn, app_mod.db, app_mod.db.get_opportunity(conn, oid2))
    conn.close()
    assert line2["state"] == "na" and line2["na_note"] == "Nothing required"
