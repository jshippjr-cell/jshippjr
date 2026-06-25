"""Phase 1 — block composer: route render, default assembly, persistence, mailto."""

import importlib
from urllib.parse import unquote

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def _preview_body(html: str) -> str:
    """The assembled preview text from the #compose-body div (not the editors)."""
    import html as _h
    import re
    m = re.search(r'id="compose-body"[^>]*>(.*?)</div>', html, re.S)
    assert m, "no preview body rendered"
    return _h.unescape(m.group(1))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:  # triggers lifespan seeding
        yield c


def test_compose_renders_blocks_and_preview(client):
    r = client.get("/opportunity/3/compose")
    assert r.status_code == 200
    # Block toggles (on/off checkboxes) + a live preview panel.
    assert 'name="on"' in r.text
    assert "Live preview" in r.text
    # Every block key offers an editable textarea.
    for key in ("opener", "understanding", "track", "call_offer", "page_link",
                "signoff", "credibility", "ps"):
        assert f'name="text_{key}"' in r.text


def test_default_body_includes_on_blocks_excludes_off(client):
    body = _preview_body(client.get("/opportunity/3/compose").text)
    # The assembled preview body lives in #compose-body. Assert the default-ON
    # content is present and the default-OFF blocks are not.
    assert "Hi " in body                                  # opener greeting
    assert "music partner to shape its sound" in body     # understanding synopsis
    assert "isn't always ideal" in body                   # call offer phrase
    assert "short page I put together for your brief" in body  # soft page link
    assert "— Jon Shipp · Chordential" in body            # sign-off
    # Default-OFF blocks must NOT appear in the default preview body.
    assert "original and cleared, with a fixed scope" not in body   # credibility
    assert "P.S. Happy to send a couple more references" not in body  # ps


def test_compose_state_persists_and_preview_reflects(client):
    # Turn credibility ON and track OFF (drop track from the default set).
    on_keys = ["opener", "understanding", "call_offer", "page_link", "signoff",
               "credibility"]
    r = client.post(
        "/opportunity/3/compose",
        data={"on": on_keys},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/opportunity/3/compose"
    body = _preview_body(client.get("/opportunity/3/compose").text)
    # Credibility now present; track (the "speaks directly" line) now absent.
    assert "original and cleared, with a fixed scope" in body
    assert "One piece I think speaks directly to your brief" not in body


def test_open_in_mail_client_mailto_carries_body(client):
    page = client.get("/opportunity/3/compose").text
    # Extract the mailto href and confirm the assembled body is in it.
    import re
    m = re.search(r'href="(mailto:[^"]+)"', page)
    assert m, "no mailto link rendered"
    decoded = unquote(m.group(1))
    assert "— Jon Shipp · Chordential" in decoded
    assert "isn't always ideal" in decoded
