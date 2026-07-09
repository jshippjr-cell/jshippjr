"""The operator's Next Action (ADR-0020 §6) — the deal always exposes one obvious move.

Walks the whole ladder on a single deal: schedule → send summary → waiting-confirm →
release proposal → waiting-approval → assign composer → start production → studio composing
→ publish version → waiting-feedback → send final invoice → waiting-payment → done.
"""
import importlib

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes", "campaigns",
              "commercial", "kickoff", "production", "next_action", "workspace", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _next(app_mod, opp_id):
    conn = app_mod.db.connect()
    opp = app_mod.db.get_opportunity(conn, opp_id)
    project = app_mod.db.project_for_opp(conn, opp_id)
    out = app_mod.next_action.compute(conn, app_mod.db, opp, project)
    conn.close()
    return out


def test_next_action_walks_the_whole_ladder(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = app_mod.db.insert_opportunity(conn, Opportunity(
        client="Halcyon Creative", need="Holiday anthem", description="Campaign.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=18000, budget_max=24000))
    conn.execute("UPDATE opportunities SET contact_email=?, contact_name=? WHERE id=?",
                 ("sarah@halcyon.com", "Sarah Chen", oid))
    conn.commit()
    token = app_mod.db.ensure_share_token(conn, oid); conn.close()

    # 1 — no discovery yet → schedule
    a = _next(app_mod, oid)
    assert a["court"] == "you" and "Schedule the discovery" in a["label"]

    # 2 — call happened → send the summary
    conn = app_mod.db.connect()
    app_mod.db.create_meeting(conn, opp_id=oid, start_at="2026-07-01T14:00:00+00:00",
                              status="ingested")
    ci = app_mod.campaign_intelligence
    row = app_mod.db.get_opportunity(conn, oid)
    ci_id = ci.ensure_for_opportunity(conn, row)["id"]
    ci.edit_or_create(conn, ci_id, "direction", "campaign_objective", "fact",
                      "Own Q4 retail", actor="operator")
    conn.close()
    a = _next(app_mod, oid)
    assert a["court"] == "you" and "Send the Discovery Summary" in a["label"]

    with TestClient(app_mod.app) as c:
        # 3 — summary sent (snapshot) → waiting on client confirmation
        conn = app_mod.db.connect()
        app_mod.db.create_brief_snapshot(conn, oid, "{}"); conn.close()
        a = _next(app_mod, oid)
        assert a["court"] == "client" and "confirming" in a["label"]

        # 4 — client confirms → release the proposal
        c.post(f"/workspace/{token}/confirm-scope", data={"confirmed_by": "Sarah Chen"})
        a = _next(app_mod, oid)
        assert a["court"] == "you" and "Release the proposal" in a["label"]

        # 5 — released → waiting on approval
        c.post(f"/opportunity/{oid}/commercial/release")
        a = _next(app_mod, oid)
        assert a["court"] == "client" and "approving the proposal" in a["label"]

        # 6 — approved → assign the composer
        c.post(f"/workspace/{token}/approve",
               data={"approver_name": "Sarah Chen", "approver_email": "sarah@halcyon.com",
                     "scope_ok": "1", "pricing_ok": "1", "timeline_ok": "1", "terms_ok": "1"})
        a = _next(app_mod, oid)
        assert a["court"] == "you" and a["label"].startswith("Assign the")

        # 7 — assigned → start production (a POST action)
        conn = app_mod.db.connect()
        pid = app_mod.db.project_for_opp(conn, oid)["id"]
        tid = conn.execute("SELECT id FROM talent LIMIT 1").fetchone()
        if tid is None:
            from chordential_oia.models import Talent
            conn.execute("INSERT INTO talent (name, email) VALUES ('Maya','m@x.com')")
            conn.commit()
            tid = conn.execute("SELECT id FROM talent LIMIT 1").fetchone()
        import json as _json
        role = _json.loads(app_mod.db.get_project(conn, pid)["roles"])[0]
        conn.close()
        c.post(f"/project/{pid}/assign", data={"role": role, "talent_id": str(tid["id"])})
        # cover remaining roles so "assign" clears
        conn = app_mod.db.connect()
        roles = _json.loads(app_mod.db.get_project(conn, pid)["roles"])
        for r_ in roles[1:]:
            app_mod.db.add_assignment(conn, pid, r_, tid["id"])
        conn.close()
        a = _next(app_mod, oid)
        assert a["court"] == "you" and a["label"] == "Start production" and a["post"]

        # 8 — production started, no version yet → studio composing
        c.post(f"/opportunity/{oid}/start-production")
        a = _next(app_mod, oid)
        assert a["court"] == "team" and "composing" in a["label"]

        # 9 — a version lands in review → waiting on client feedback
        conn = app_mod.db.connect()
        app_mod.db.update_delivery(conn, pid, "versions",
                                   [{"n": 1, "label": "v1 Concept", "url": "/x.mp3",
                                     "filename": "x.mp3", "name": "x",
                                     "created_at": "2026-07-08T00:00:00"}])
        app_mod.db.update_delivery(conn, pid, "state", "In review"); conn.close()
        a = _next(app_mod, oid)
        assert a["court"] == "client" and "listening" in a["label"]

        # 9.5 — client approved the MASTER (creative locked) but the derivative
        # deliverables aren't uploaded yet → the move is FINISHING delivery, NOT invoicing.
        conn = app_mod.db.connect()
        app_mod.production.set_creative_lock(conn, app_mod.db, pid, version_n=1, by="Sarah")
        app_mod.db.update_delivery(conn, pid, "state", "Approved"); conn.close()
        a = _next(app_mod, oid)
        assert a["court"] == "team" and "remaining deliverables" in a["label"]
        assert "final invoice" not in a["label"]        # the bug: it used to say this

        # 9.6 — composer UPLOADED every deliverable, but the client hasn't signed each off
        # yet → waiting on client sign-off, still NOT invoicing (the 2nd bug the walkthrough
        # caught: 'uploaded' was wrongly treated as 'done').
        conn = app_mod.db.connect()
        app_mod.db.update_delivery(conn, pid, "assets", [
            {"label": "Instrumental TV mix", "filename": "i.mp3", "url": "/u/i.mp3", "kind": "audio"},
            {"label": ":30 cutdown", "filename": "c.mp3", "url": "/u/c.mp3", "kind": "audio"},
            {"label": "9:16 vertical", "filename": "v.mp3", "url": "/u/v.mp3", "kind": "audio"},
            {"label": "Mix-ready stem package", "filename": "s.zip", "url": "/u/s.zip", "kind": "file"}])
        conn.close()
        a = _next(app_mod, oid)
        assert a["court"] == "client" and "signing off" in a["label"]
        assert "final invoice" not in a["label"]

        # 10 — every deliverable signed off / package shipped → send the final invoice
        conn = app_mod.db.connect()
        app_mod.db.update_delivery(conn, pid, "state", "Delivered"); conn.close()
        a = _next(app_mod, oid)
        assert a["court"] == "you" and "final invoice" in a["label"]

        # 11 — final invoice created (unpaid) → waiting on payment
        c.post(f"/project/{pid}/proposal")
        c.post(f"/project/{pid}/invoice", data={"kind": "Final"})
        a = _next(app_mod, oid)
        assert a["court"] == "client" and "payment" in a["label"]

        # 12 — paid → done
        conn = app_mod.db.connect()
        conn.execute("UPDATE invoices SET status='Paid' WHERE kind='Final'")
        conn.commit(); conn.close()
        a = _next(app_mod, oid)
        assert a["court"] == "done"

        # the card renders on the deal page
        page = c.get(f"/opportunity/{oid}").text
        assert 'id="next"' in page and "DONE" in page
