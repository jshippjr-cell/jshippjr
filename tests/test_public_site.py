"""Public front-of-house site (Cycle 1.1) — brochure surface, no logins.

Verifies the public pages render on their own standalone layout, share the app
without leaking the internal dashboard chrome, and stay decoupled from internal
pipeline state.
"""

import re
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


def test_public_home_is_the_score(client):
    # The front door is the Commission — the live score, ending at the intake. The
    # World film and the Experience film that preceded it were deleted rather than
    # parked at second addresses (their masters are archived in media/masters/).
    r = client.get("/")
    assert r.status_code == 200
    assert "scoretracks" in r.text, "the front door is not the score page"
    assert "/start" in r.text
    # the Commission is the reference for what the score page rebuilds; links
    # handed out before the cutover still have to land somewhere real
    assert "The music department" in client.get("/commission").text
    for retired in ("/world", "/experience"):
        assert client.get(retired).status_code == 404, f"{retired} is back"


def test_public_home_at_root(client):
    assert client.get("/").status_code == 200


def test_public_uses_standalone_layout_not_internal_shell(client):
    # Public surfaces never leak the internal dashboard chrome.
    for path in ("/", "/commission"):
        r = client.get(path)
        assert "Procurement OS" not in r.text       # internal title suffix
        assert 'class="sidebar"' not in r.text      # internal nav must not leak
    # Brochure pages still render the public stylesheet/shell.
    assert "/static/public/site.css" in client.get("/start").text


def test_home_work_is_truthful_capability_demonstrations(client):
    # No public surface may imply delivered client engagements. This followed the
    # Commission to its address; the front door is asserted separately below.
    r = client.get("/commission")
    assert r.status_code == 200
    for past_claim in ("Recent work", "See all work", "How we solved it",
                       "Every engagement"):
        assert past_claim not in r.text
    # The recordings are AI-generated placeholders (showcase.PLACEHOLDER_AUDIO_NOTICE).
    # The human-authorship promise is true of what we deliver and was false of what
    # this page plays; it may not sit over placeholder audio.
    assert "never AI-generated audio" not in r.text
    assert "AI-generated placeholders" in r.text


def test_the_front_door_claims_no_client_work(client):
    """Same guarantee, expressed against the page that is actually at `/`."""
    r = client.get("/")
    assert r.status_code == 200
    for past_claim in ("Recent work", "See all work", "How we solved it",
                       "Every engagement", "Trusted by"):
        assert past_claim not in r.text


def test_delivery_sample_page(client):
    # The branded sample delivery package renders and is clearly a demo.
    r = client.get("/delivery-sample")
    assert r.status_code == 200
    for doc in ("Deliverables Manifest", "Rights", "Campaign Rollout", "Final Approval"):
        assert doc in r.text
    assert "SAMPLE" in r.text and "wordmark-ko.png" in r.text  # honest + real logo
    assert "Save as PDF" in r.text and "window.print()" in r.text  # crisp browser PDF


def test_internal_dashboard_unaffected_by_public_mount(client):
    # The internal app still works and still shows its own shell.
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Procurement OS" in r.text


def test_the_retired_brochure_pages_are_gone(client):
    """/capabilities and /samples were a second and third telling of the work. The
    landing world carries it now; both are 301s so no old link dies."""
    for path in ("/capabilities", "/samples"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == "/#hear"


def test_public_nav_links_resolve(client):
    # Every primary marketing nav target is a real, 200-returning page.
    for path in ("/", "/commission", "/start", "/book", "/for-artists"):
        assert client.get(path).status_code == 200
