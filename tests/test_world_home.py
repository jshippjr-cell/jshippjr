"""The front door (``/``) is the World — the scroll-scrubbed camera-flight
landing page (public/world.html). These pin its contract:

- ``/`` serves the world page: the scrub engine mounts, all five legs +
  posters are wired, and the journey ends at the /start intake CTA.
- It stays public under an enabled admin gate (front-of-house is never gated).
- The Experience film survives untouched at /experience (deep links).
- The video/engine assets actually exist on disk and are served.
"""
import pathlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    from chordential_oia.web.app import app
    with TestClient(app) as c:
        yield c


WORLD_DIR = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src" / "chordential_oia" / "web" / "static" / "public" / "world"
)


def test_home_serves_the_world(client):
    page = client.get("/").text
    assert "mountScrollWorld" in page
    assert "/static/public/world/scrub-engine.js" in page
    # clips are wired codec-aware: CLIP(n) → leg-n .mp4 (h264) or .webm (VP9)
    assert "function CLIP(n)" in page and ".webm" in page
    for i in range(1, 6):
        assert f"CLIP({i})" in page
        assert f"/static/public/world/leg{i}-m.mp4" in page
        assert f"/static/public/world/still{i}.jpg" in page
    # the journey lands on the intake
    assert "/start" in page and "Start your brief" in page
    # honesty line ships with the session scene
    assert "never AI-generated audio" in page


def test_home_is_public_with_admin_gate_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "g.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "secret")
    from chordential_oia.web.app import app
    with TestClient(app) as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 200
        assert "mountScrollWorld" in r.text


def test_experience_film_still_lives_at_its_route(client):
    page = client.get("/experience").text
    assert "AURORA_Anthem_60_MASTER_v3_FINAL" in page  # the film, untouched


def test_world_assets_are_packaged(client):
    """Package-data uses per-directory globs; a new static subdirectory ships to
    prod ONLY if pyproject covers it. The world/ dir 404'd in prod exactly this
    way — this pins the pattern so it can't silently regress."""
    import tomllib
    root = pathlib.Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    patterns = data["tool"]["setuptools"]["package-data"]["chordential_oia.web"]
    assert any(p.startswith("static/public/world/") for p in patterns), (
        "static/public/world/* missing from package-data — prod will 404 the world assets"
    )


def test_world_assets_exist_and_are_served(client):
    # on disk (a missing render must fail loudly, not 404 silently in prod)
    for name in ["scrub-engine.js"] + [f"leg{i}.mp4" for i in range(1, 6)] \
            + [f"leg{i}-m.mp4" for i in range(1, 6)] + [f"still{i}.jpg" for i in range(1, 6)]:
        assert (WORLD_DIR / name).is_file(), f"missing asset: {name}"
    r = client.get("/static/public/world/leg1.mp4")
    assert r.status_code == 200
    assert client.get("/static/public/world/scrub-engine.js").status_code == 200
