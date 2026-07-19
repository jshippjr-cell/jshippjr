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


def test_all_review_actions_bypass_the_admin_gate(tmp_path, monkeypatch):
    """Regression: the client review portal is opened from a token-gated link, so
    EVERY review action must bypass the admin login gate (the route validates the
    token itself and 404s a bad one). The exemption regex once drifted from the
    routes — 'resolve' and 'asset' were added but not exempted, so agency clients
    clicking Resolve/Reopen or per-asset Approve got 303-bounced to Chordential's
    internal admin login and their action was silently lost. Assert all five."""
    app_mod = _build(tmp_path, monkeypatch, gated=True)
    with TestClient(app_mod.app) as c:
        for action in ("comment", "approve", "changes", "resolve", "asset"):
            r = c.post(f"/project/1/review/{action}", data={"k": "bad-token"},
                       follow_redirects=False)
            # Bypasses the gate → route runs and 404s the bad token, rather than
            # 303-redirecting to /admin/login. The bug would send it to login.
            loc = r.headers.get("location", "")
            assert not (r.status_code == 303 and "/admin/login" in loc), (
                f"review/{action} bounced to the admin login instead of bypassing "
                f"the gate (status={r.status_code}, location={loc!r})")


def test_review_action_exemption_lists_every_review_route(tmp_path, monkeypatch):
    """Belt-and-suspenders: the exemption action list must match the actual review
    routes registered on the app, so a newly-added review action can't silently
    drift out of the gate exemption again."""
    app_mod = _build(tmp_path, monkeypatch, gated=True)
    import re
    registered = set()
    for route in app_mod.app.routes:
        m = re.match(r"^/project/\{project_id\}/review/(\w+)$",
                     getattr(route, "path", ""))
        if m:
            registered.add(m.group(1))
    assert registered, "no review routes found — test wiring is stale"
    exempted = set(app_mod._REVIEW_ACTIONS)
    missing = registered - exempted
    assert not missing, f"review routes not exempted from the admin gate: {missing}"


def test_every_creator_portal_post_bypasses_the_gate(tmp_path, monkeypatch):
    """Drift guard (CTO master-review P0): EVERY /creator/{token}/... POST route
    must be covered by _CREATOR_PORTAL_RE, or the gate silently 303s the composer
    to /admin/login on their own token-gated page. reply/address/capture were
    omitted once and broke Phase 4.3/4.7 in prod — this asserts the regex matches
    every registered creator POST path so it can't recur."""
    app_mod = _build(tmp_path, monkeypatch, gated=True)
    import re
    missing = []
    for route in app_mod.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if not path.startswith("/creator/") or "POST" not in methods:
            continue
        # substitute concrete values for the path params, then test the regex
        concrete = (path.replace("{token}", "TOKENabc123")
                        .replace("{project_id}", "1")
                        .replace("{comment_id}", "2"))
        if not app_mod._CREATOR_PORTAL_RE.match(concrete):
            missing.append(path)
    assert not missing, f"creator POST routes not gate-exempt: {missing}"
