"""Public front-of-house site (Cycle 1.1) — brochure surface, no logins.

Verifies the public pages render on their own standalone layout, share the app
without leaking the internal dashboard chrome, and stay decoupled from internal
pipeline state.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c


def test_public_home_loads(client):
    r = client.get("/site")
    assert r.status_code == 200
    # Hero + the marketing CTAs are present.
    assert "Start a project" in r.text
    assert "Book a call" in r.text


def test_public_home_trailing_slash(client):
    assert client.get("/site/").status_code == 200


def test_public_uses_standalone_layout_not_internal_shell(client):
    r = client.get("/site")
    # Public pages render the public stylesheet/shell, NOT the internal dashboard.
    assert "/static/public/site.css" in r.text
    assert "Procurement OS" not in r.text          # internal title suffix
    assert 'class="sidebar"' not in r.text          # internal nav must not leak


def test_capabilities_lists_every_discipline(client):
    r = client.get("/site/capabilities")
    assert r.status_code == 200
    for headline in ("Original composition", "Sonic branding", "Sound design",
                     "Music supervision"):
        assert headline in r.text


def test_samples_page_renders_reel(client):
    r = client.get("/site/samples")
    assert r.status_code == 200
    assert "Selected work" in r.text
    # Placeholder reel is clearly marked until real assets are attached.
    assert "sample coming soon" in r.text


def test_internal_dashboard_unaffected_by_public_mount(client):
    # The internal app still works and still shows its own shell.
    r = client.get("/")
    assert r.status_code == 200
    assert "Procurement OS" in r.text


def test_public_nav_links_resolve(client):
    # Every primary marketing nav target is a real, 200-returning page.
    for path in ("/site", "/site/capabilities", "/site/samples"):
        assert client.get(path).status_code == 200
