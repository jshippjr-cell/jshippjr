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
    r = client.get("/")
    assert r.status_code == 200
    # Hero + the marketing CTAs are present.
    assert "Start a project" in r.text
    assert "Book a call" in r.text


def test_public_home_at_root(client):
    assert client.get("/").status_code == 200


def test_public_uses_standalone_layout_not_internal_shell(client):
    r = client.get("/")
    # Public pages render the public stylesheet/shell, NOT the internal dashboard.
    assert "/static/public/site.css" in r.text
    assert "Procurement OS" not in r.text          # internal title suffix
    assert 'class="sidebar"' not in r.text          # internal nav must not leak


def test_capabilities_lists_every_discipline(client):
    r = client.get("/capabilities")
    assert r.status_code == 200
    for headline in ("Original composition", "Sonic branding", "Sound design",
                     "Music supervision"):
        assert headline in r.text


def test_samples_page_renders_capability_demos(client):
    r = client.get("/samples")
    assert r.status_code == 200
    # CMO-led copy: confident + truthful, never apologetic about being new.
    assert "Capability Demonstrations" in r.text and "Built to brief." in r.text
    assert "new studio" not in r.text and "aren’t client commissions" not in r.text
    # Expandable brief on each demo.
    assert "See how we’d approach this brief" in r.text
    # Audio-only: all four demos render <audio> players, no video players.
    for track in ("demo-holiday-strings.mp3", "demo-financial-theme.mp3",
                  "demo-title-sequence.mp3", "demo-retail-anthem.mp3"):
        assert track in r.text
    assert r.text.count("<audio") == 4 and "<video" not in r.text


def test_home_work_section_is_truthful_capability_demos(client):
    # The home "work" section must not imply delivered client engagements.
    r = client.get("/")
    assert r.status_code == 200
    for past_claim in ("Recent work", "See all work", "How we solved it",
                       "Every engagement"):
        assert past_claim not in r.text
    # It shows the real demo players and routes to the demos page.
    assert "Capability Demonstrations" in r.text
    assert "demo-holiday-strings.mp3" in r.text and "See the brief" in r.text


def test_internal_dashboard_unaffected_by_public_mount(client):
    # The internal app still works and still shows its own shell.
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Procurement OS" in r.text


def test_public_nav_links_resolve(client):
    # Every primary marketing nav target is a real, 200-returning page.
    for path in ("/", "/capabilities", "/samples"):
        assert client.get(path).status_code == 200
