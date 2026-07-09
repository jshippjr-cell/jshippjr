"""Delivery gate (operator feedback): approving the master version approves the CREATIVE only;
the full download unlocks only when every deliverable is uploaded + signed off; approval is
reversible (reopen).
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


def _proj(app_mod, conn):
    from chordential_oia.models import Opportunity, BuyerType, MusicRequirement
    oid = app_mod.db.insert_opportunity(conn, Opportunity(
        client="X", need="Anthem", description="x", buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL, budget_min=0, budget_max=0))
    tok = app_mod.db.ensure_share_token(conn, oid)
    pid = app_mod.db.insert_project(conn, oid, "X", "Anthem", 0, 0, ["Composer"], share_token=tok)
    return oid, pid, app_mod.db.ensure_project_share_token(conn, pid)


def test_creative_approval_does_not_ship_incomplete_package(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid, pid, ptok = _proj(app_mod, conn)
    app_mod.db.update_delivery(conn, pid, "versions",
        [{"n": 2, "label": "v2", "url": "/uploads/x.mp3", "filename": "x.mp3",
          "name": "a", "created_at": "2026-07-08T00:00:00"}])
    app_mod.db.update_delivery(conn, pid, "state", "In review")
    conn.close()
    with TestClient(app_mod.app) as c:
        # client approves the master version — the CREATIVE
        r = c.post(f"/project/{pid}/review/approve",
                   data={"k": ptok, "author": "Sarah", "email": "s@x.com"}, follow_redirects=False)
        assert r.status_code == 303
    conn = app_mod.db.connect(); d = app_mod.db.get_delivery(conn, pid); conn.close()
    # creative is locked, but the package did NOT build and delivery did NOT happen
    assert d.get("creative_lock")
    assert d.get("state") == "Approved"                  # NOT "Delivered"
    assert not d.get("delivery_zip")                     # no package → no download
    assert not d.get("download_unlocked")


def test_reopen_reverses_the_approval(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid, pid, ptok = _proj(app_mod, conn)
    app_mod.db.update_delivery(conn, pid, "versions",
        [{"n": 1, "label": "v1", "url": "/uploads/x.mp3", "filename": "x.mp3",
          "name": "a", "created_at": "2026-07-08T00:00:00"}])
    app_mod.db.update_delivery(conn, pid, "state", "In review")
    conn.close()
    with TestClient(app_mod.app) as c:
        c.post(f"/project/{pid}/review/approve",
               data={"k": ptok, "author": "Sarah", "email": "s@x.com"})
        # reopen — approval is not a one-way door
        r = c.post(f"/project/{pid}/review/reopen", data={"k": ptok}, follow_redirects=False)
        assert r.status_code == 303
    conn = app_mod.db.connect(); d = app_mod.db.get_delivery(conn, pid); conn.close()
    assert not d.get("creative_lock")                    # lock cleared
    assert d.get("state") == "In review"                 # back in review
    assert not d.get("download_unlocked")


def test_client_can_approve_each_deliverable(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid, pid, ptok = _proj(app_mod, conn)
    # an uploaded deliverable asset the client can sign off
    app_mod.db.update_delivery(conn, pid, "assets",
        [{"label": "Final master", "filename": "master.wav", "url": "/uploads/m.wav", "kind": "audio"}])
    app_mod.db.update_delivery(conn, pid, "state", "In review")
    conn.close()
    with TestClient(app_mod.app) as c:
        r = c.post(f"/project/{pid}/review/asset",
                   data={"k": ptok, "filename": "master.wav", "action": "approve",
                         "author": "Sarah", "email": "s@x.com"}, follow_redirects=False)
        assert r.status_code == 303
    conn = app_mod.db.connect()
    d = app_mod.db.get_delivery(conn, pid)
    roll = app_mod.db.asset_approval_rollup(d)
    conn.close()
    assert roll["approved"] == 1                          # the client's per-deliverable sign-off landed


def test_partial_package_offers_client_no_download(tmp_path, monkeypatch):
    """The bug the screenshot caught: a Delivered project with a PARTIAL package (0/5
    deliverables) was still rendering a '⤓ Download what's ready' link. A client must never
    be able to download an incomplete package — the portal shows 'still being assembled'."""
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid, pid, ptok = _proj(app_mod, conn)
    # a project stuck Delivered under the old rule: partial package + download unlocked
    app_mod.db.update_delivery(conn, pid, "state", "Delivered")
    app_mod.db.update_delivery(conn, pid, "download_unlocked", True)
    app_mod.db.update_delivery(conn, pid, "delivery_zip", {
        "filename": "pkg.zip", "url": "/x/pkg.zip", "built_at": "2026-07-08T00:00:00",
        "partial": True, "descriptor": "Partial delivery — 0 of 5 deliverables",
        "completeness": {"missing": ["Final master", "TV mix", "Cutdowns", "Verticals", "Stems"]}})
    conn.close()
    with TestClient(app_mod.app) as c:
        html = c.get(f"/project/{pid}/delivery-portal?k={ptok}").text
    assert "Still being assembled" in html
    assert "Download what" not in html                    # no partial download offered
    assert "⤓ Download" not in html                        # no download link at all while partial


def test_operator_can_reopen_delivered_project_from_console(tmp_path, monkeypatch):
    """The operator must be able to un-deliver a stuck Delivered project (tokenless reopen),
    since the portal's client review block is hidden once state is Delivered."""
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid, pid, ptok = _proj(app_mod, conn)
    app_mod.db.update_delivery(conn, pid, "versions",
        [{"n": 2, "label": "v2 FINAL", "url": "/uploads/x.mp3", "filename": "x.mp3",
          "name": "a", "created_at": "2026-07-08T00:00:00"}])
    app_mod.db.update_delivery(conn, pid, "state", "Delivered")
    app_mod.db.update_delivery(conn, pid, "download_unlocked", True)
    app_mod.production.set_creative_lock(conn, app_mod.db, pid, version_n=2, by="Sarah")
    conn.close()
    with TestClient(app_mod.app) as c:
        # tokenless operator reopen (the console button posts with no k/r)
        r = c.post(f"/project/{pid}/review/reopen", data={}, follow_redirects=False)
        assert r.status_code == 303
    conn = app_mod.db.connect(); d = app_mod.db.get_delivery(conn, pid); conn.close()
    assert not d.get("creative_lock")
    assert d.get("state") == "In review"
    assert not d.get("download_unlocked")
