"""The Commission page — the scroll-world score with the delivery packing.

Standalone front-of-house surface: it carries its own header rather than the
marketing chrome, and it depends on three.js being served as a real static
asset. That dependency is the thing worth guarding: an earlier build of this
page shipped calling `new THREE.WebGLRenderer(...)` with the library never
loaded at all, and because the page guards its own units the failure showed up
as a silently missing 3D layer rather than an error anybody noticed.
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


def test_commission_renders(client):
    r = client.get("/commission")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_commission_carries_the_closer(client):
    """Four denials and one instruction. If the copy is edited the test should
    be edited with it, deliberately."""
    body = client.get("/commission").text
    for line in ("Nothing should still be", "Not the music.", "Not the versions.",
                 "Not the rights.", "Not the paperwork.", "Just press"):
        assert line in body, line


def test_commission_reaches_its_three_interactive_beats(client):
    """The note on a cue, the planning band, and the crate that packs itself."""
    body = client.get("/commission").text
    for hook in ('id="notePin"', 'id="priceBtn"', 'id="packBtn"', 'id="closeBtn"'):
        assert hook in body, hook


def test_commission_requests_three_and_the_asset_exists(client):
    """The page is inert without the library, so assert both halves: that the
    page asks for it, and that the path it asks for actually serves."""
    body = client.get("/commission").text
    assert "/static/public/vendor/three.min.js" in body

    lib = client.get("/static/public/vendor/three.min.js")
    assert lib.status_code == 200
    assert len(lib.content) > 100_000
    assert b"WebGLRenderer" in lib.content


def test_commission_does_not_replace_the_front_door(client):
    """The World is still the homepage; the Commission is its own address."""
    home = client.get("/")
    assert home.status_code == 200
    assert "Nothing should still be" not in home.text
