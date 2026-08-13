"""Operator-reported: the client must be able to approve from their OWN share link (no
verified reviewer link needed), and EVERY upload — including the operator's — is gated at
the taste gate before the client sees it.
"""
import importlib


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "production", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _project(app_mod, conn):
    from chordential_oia.models import Opportunity, BuyerType, MusicRequirement
    oid = app_mod.db.insert_opportunity(conn, Opportunity(
        client="X", need="Anthem", description="x", buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL, budget_min=0, budget_max=0))
    tok = app_mod.db.ensure_share_token(conn, oid)
    pid = app_mod.db.insert_project(conn, oid, "X", "Anthem", 0, 0, ["Composer"],
                                    share_token=tok)
    return oid, pid, app_mod.db.ensure_project_share_token(conn, pid)


def test_client_can_approve_from_share_link(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid, pid, ptok = _project(app_mod, conn)
    app_mod.db.update_delivery(conn, pid, "versions",
        [{"n": 1, "label": "v1 Concept", "url": "/uploads/x.mp3", "filename": "x.mp3",
          "name": "a", "created_at": "2026-07-08T00:00:00"}])
    app_mod.db.update_delivery(conn, pid, "state", "In review")
    conn.close()
    with TestClient(app_mod.app) as c:
        # the portal now shows a working Approve once the client has entered their name
        # (no "personal review link" wall)
        page = c.get(f"/project/{pid}/delivery-portal?k={ptok}").text
        assert "no separate link needed" in page.lower() or "review/approve" in page
        # client approves from the SHARE link with a typed identity — succeeds
        r = c.post(f"/project/{pid}/review/approve",
                   data={"k": ptok, "author": "Sarah Chen", "email": "sarah@x.com",
                         "deliver_partial": "1"}, follow_redirects=False)
        assert r.status_code == 303                       # not 404 / refused
    conn = app_mod.db.connect()
    d = app_mod.db.get_delivery(conn, pid)
    approvals = [x for x in app_mod.db.list_review_comments(conn, pid) if x["kind"] == "approval"]
    conn.close()
    assert d["state"] in ("Delivered", "Approved")        # the approval drove delivery
    assert d.get("creative_lock")                          # lock recorded
    assert approvals and approvals[0]["author"] == "Sarah Chen"


def test_operator_upload_is_gated_at_the_taste_gate(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid, pid, ptok = _project(app_mod, conn)
    conn.close()
    with TestClient(app_mod.app) as c:
        # the operator uploads a version via the delivery console
        c.post(f"/project/{pid}/delivery/version",
               files={"file": ("take.mp3", b"ID3\x00\x00\x00audio", "audio/mpeg")},
               data={"action": "add"})
        conn = app_mod.db.connect()
        d = app_mod.db.get_delivery(conn, pid)
        conn.close()
        # it lands PENDING — not in the client-visible ladder, not "In review"
        assert d.get("pending_version")
        assert not (d.get("versions"))                     # client sees nothing yet
        assert d.get("state") != "In review"
        # publishing is the explicit gate that shows it to the client
        c.post(f"/project/{pid}/delivery/publish", data={"action": "publish"})
        conn = app_mod.db.connect()
        d2 = app_mod.db.get_delivery(conn, pid)
        conn.close()
        assert d2.get("versions") and not d2.get("pending_version")
        assert d2.get("state") == "In review"              # NOW the client can see it
