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


def test_public_home_is_the_commission(client):
    # The front door is the Commission — the live score, ending at the intake. The
    # World film and the Experience film that preceded it were deleted rather than
    # parked at second addresses (their masters are archived in media/masters/).
    r = client.get("/")
    assert r.status_code == 200
    assert "The music department" in r.text
    assert "/start" in r.text
    for retired in ("/world", "/experience"):
        assert client.get(retired).status_code == 404, f"{retired} is back"


def test_public_home_at_root(client):
    assert client.get("/").status_code == 200


def test_public_uses_standalone_layout_not_internal_shell(client):
    # Public surfaces never leak the internal dashboard chrome.
    for path in ("/", "/capabilities"):
        r = client.get(path)
        assert "Procurement OS" not in r.text       # internal title suffix
        assert 'class="sidebar"' not in r.text      # internal nav must not leak
    # Brochure pages still render the public stylesheet/shell.
    assert "/static/public/site.css" in client.get("/capabilities").text


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
    # Audio-only: all four demos render <audio> players, no video. ADR-0040 moved the
    # files off the third-party CDN onto our own /static/public/, so assert the
    # substance — four working players — rather than a hostname that is incidental.
    assert r.text.count("<audio") == 4 and "<video" not in r.text
    for src in re.findall(r'<audio[^>]*src="([^"]+)"', r.text):
        assert client.get(src).status_code == 200, f"{src} does not serve"


def test_home_work_is_truthful_capability_demonstrations(client):
    # The front door must not imply delivered client engagements, and the no-AI-audio
    # rule has to be stated on it — that claim moved with the front door rather than
    # being left behind on the page that used to carry it.
    r = client.get("/")
    assert r.status_code == 200
    for past_claim in ("Recent work", "See all work", "How we solved it",
                       "Every engagement"):
        assert past_claim not in r.text
    assert "never AI-generated audio" in r.text


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


def test_public_nav_links_resolve(client):
    # Every primary marketing nav target is a real, 200-returning page.
    for path in ("/", "/capabilities", "/samples"):
        assert client.get(path).status_code == 200
