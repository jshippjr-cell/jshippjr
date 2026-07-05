"""Health/readiness endpoints — the platform probe issues HEAD requests."""

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


def test_head_root_is_200_not_405(client):
    # Render's deploy probe HEADs "/"; it must not 405.
    assert client.head("/").status_code == 200


def test_healthz_get_and_head(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.head("/healthz").status_code == 200


def test_get_root_renders_public_home(client):
    # Root is the public marketing site now; the dashboard moved to /dashboard.
    r = client.get("/")
    assert r.status_code == 200
    assert "Start a conversation" in r.text


def test_dashboard_renders_at_dashboard(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Today" in r.text
