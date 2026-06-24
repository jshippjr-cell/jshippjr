"""Internal admin gate — a light single-operator shared secret.

OFF unless CHORDENTIAL_ADMIN_TOKEN is set (so dev/tests/current behavior are
unchanged). When ON, internal routes require the cookie; the public site at /,
static, health, and login routes stay open.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

TOKEN = "open-sesame"


def _build(tmp_path, monkeypatch, gated: bool):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    if gated:
        monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", TOKEN)
    else:
        monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    return app_mod


def test_gate_off_by_default(tmp_path, monkeypatch):
    app_mod = _build(tmp_path, monkeypatch, gated=False)
    with TestClient(app_mod.app) as c:
        assert c.get("/", follow_redirects=False).status_code == 200
        assert c.get("/dashboard", follow_redirects=False).status_code == 200


def test_gate_on_blocks_internal_redirects_to_login(tmp_path, monkeypatch):
    app_mod = _build(tmp_path, monkeypatch, gated=True)
    with TestClient(app_mod.app) as c:
        r = c.get("/dashboard", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/admin/login")
        # another internal route too
        assert c.get("/leads", follow_redirects=False).status_code == 303


def test_gate_on_public_surfaces_stay_open(tmp_path, monkeypatch):
    app_mod = _build(tmp_path, monkeypatch, gated=True)
    with TestClient(app_mod.app) as c:
        assert c.get("/").status_code == 200
        assert c.get("/start").status_code == 200
        assert c.get("/static/public/site.css").status_code == 200
        assert c.get("/healthz").status_code == 200
        assert c.get("/admin/login").status_code == 200
        # public intake still works through the gate
        assert c.post("/start", data={"contact_name": "X",
                      "contact_email": "x@example.com", "phone": "555-0150"},
                      follow_redirects=False).status_code == 303


def test_head_probe_passes_through(tmp_path, monkeypatch):
    app_mod = _build(tmp_path, monkeypatch, gated=True)
    with TestClient(app_mod.app) as c:
        assert c.head("/").status_code == 200


def test_wrong_passphrase_denied(tmp_path, monkeypatch):
    app_mod = _build(tmp_path, monkeypatch, gated=True)
    with TestClient(app_mod.app) as c:
        r = c.post("/admin/login", data={"password": "nope", "next": "/dashboard"},
                   follow_redirects=False)
        assert r.status_code == 200          # re-renders with error, no cookie
        assert "cdl_admin" not in r.cookies
        # still blocked
        assert c.get("/dashboard", follow_redirects=False).status_code == 303


def test_correct_passphrase_grants_access(tmp_path, monkeypatch):
    app_mod = _build(tmp_path, monkeypatch, gated=True)
    with TestClient(app_mod.app) as c:
        r = c.post("/admin/login", data={"password": TOKEN, "next": "/dashboard"},
                   follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/dashboard"
        # cookie now set in the client jar → internal routes load
        assert c.get("/dashboard", follow_redirects=False).status_code == 200
        assert c.get("/leads", follow_redirects=False).status_code == 200


def test_logout_revokes_access(tmp_path, monkeypatch):
    app_mod = _build(tmp_path, monkeypatch, gated=True)
    with TestClient(app_mod.app) as c:
        c.post("/admin/login", data={"password": TOKEN, "next": "/dashboard"})
        assert c.get("/dashboard", follow_redirects=False).status_code == 200
        c.get("/admin/logout")
        assert c.get("/dashboard", follow_redirects=False).status_code == 303


def test_cookie_does_not_contain_raw_token(tmp_path, monkeypatch):
    app_mod = _build(tmp_path, monkeypatch, gated=True)
    with TestClient(app_mod.app) as c:
        r = c.post("/admin/login", data={"password": TOKEN, "next": "/dashboard"},
                   follow_redirects=False)
        set_cookie = r.headers.get("set-cookie", "")
        assert TOKEN not in set_cookie          # only a hash is stored
