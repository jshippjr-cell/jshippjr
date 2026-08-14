"""Phase 1 — block composer: route render, default assembly, persistence, mailto."""

import importlib
from urllib.parse import unquote

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia import mailer  # noqa: E402


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
    # Understanding inherits from Campaign Intelligence (ADR-0017): opp 3 has a seeded
    # business_objective, so the block is the CI-derived short version, not the generic
    # stock restatement. The old assertion matched the serializer's lead-in ("This
    # reflects our current understanding of the campaign"), which was boilerplate wrapped
    # around a serialized field table — exactly what client_voice replaced.
    assert "Here's the short version" in body               # CI-derived understanding
    assert "isn't always ideal" in body                   # call offer phrase
    assert "Here's our understanding of your campaign" in body  # summary link (ADR-0020)
    assert "Jon Shipp · Chordential" in body            # sign-off
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
    assert "Jon Shipp · Chordential" in decoded
    assert "isn't always ideal" in decoded


def test_send_now_button_hidden_when_mail_not_configured(client):
    """Reported live: "when I send the outreach email out, it sits in my
    outbox in my mail app" — the compose page only ever offered a mailto:
    draft. Send now must not appear (and must not be implied) when there's
    no real mail provider configured — the mailto fallback stays the only
    option, exactly as before."""
    page = client.get("/opportunity/3/compose").text
    assert "Send now to" not in page
    assert 'action="/opportunity/3/compose/send"' not in page


def test_compose_send_falls_back_to_manual_when_mail_not_configured(client):
    r = client.post("/opportunity/3/compose/send", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/opportunity/3/compose?sent=manual"


def test_compose_send_actually_sends_when_mail_configured(client, monkeypatch):
    """The real fix: when mail is configured, Send now calls the mailer
    directly — no mailto:, no local mail client, no draft left sitting in
    an outbox."""
    from chordential_oia.web import app as app_mod
    from chordential_oia.web import db as db_mod

    conn = db_mod.connect()
    try:
        db_mod.update_outreach(conn, 3, contact_email="buyer@brand.com")
    finally:
        conn.close()

    sent = {}

    def fake_send(to, subject, text, html=None):
        sent.update(to=to, subject=subject, text=text, html=html)
        return "sent"

    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email", fake_send)

    page = client.get("/opportunity/3/compose").text
    assert "Send now to buyer@brand.com" in page

    r = client.post("/opportunity/3/compose/send", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/opportunity/3/compose?sent=sent"
    assert sent["to"] == "buyer@brand.com"
    assert sent["html"] is not None
    assert "wordmark-dark.png" in sent["html"]

    page = client.get(r.headers["location"]).text
    assert "✓ Email sent to buyer@brand.com" in page


def test_capabilities_doc_links_to_compose_to_email_it(client):
    """The combined flow: the capabilities doc page doesn't have its own,
    separate "email it" send action — "Email this" routes to the same
    outreach composer that actually sends, so there's one real place to
    email a contact, not two disconnected ones."""
    page = client.get("/opportunity/3/capabilities").text
    assert 'href="/opportunity/3/compose">✉ Email this</a>' in page


def test_compose_music_upload_returns_to_composer_and_plays_on_page(client):
    """Uploading a track from the composer returns to the composer, lists the
    track, and the client's Campaign Brief then plays it."""
    # the composer shows the music section + a preview link (to the Campaign Brief)
    page = client.get("/opportunity/3/compose").text
    assert "Campaign Brief · client link" in page
    # upload an audio file with return_to=compose
    r = client.post(
        "/opportunity/3/doc/upload",
        data={"action": "add", "label": "Score sketch",
              "return_to": "/opportunity/3/compose"},
        files={"file": ("sketch.mp3", b"ID3fake-mp3-bytes", "audio/mpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/opportunity/3/compose"
    # the composer now lists the track
    assert "Score sketch" in client.get("/opportunity/3/compose").text
    # and the client's Campaign Brief plays it (token-gated public link)
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        token = db_mod.ensure_share_token(conn, 3)
    finally:
        conn.close()
    brief = client.get(f"/opportunity/3/capabilities?k={token}").text
    assert "<audio" in brief and "Score sketch" in brief
    # the client link hides the admin toolbar (no "Back to Opportunity" / edit chrome)
    assert "Back to Opportunity" not in brief
