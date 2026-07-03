"""Phase 2 + Phase 3 — the tailored first-touch page (token-gated public page)
and the engagement measurement surfaced on the outreach view.

Option C (Gmail HTML send) is intentionally NOT built — these tests cover only the
token-gated page and its view counter, the gate that decides whether Option C is
ever worth building.
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
    with TestClient(app_mod.app) as c:  # triggers lifespan seeding
        yield c


def _token(client, opp_id=3):
    """Mint/fetch the opp's share token directly via the db helper."""
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        return db_mod.ensure_share_token(conn, opp_id)
    finally:
        conn.close()


def test_first_touch_wrong_or_empty_token_404(client):
    # No token at all → 404 (never leaks existence).
    assert client.get("/opportunity/3/first-touch").status_code == 404
    # Empty token → 404.
    assert client.get("/opportunity/3/first-touch?k=").status_code == 404
    # Wrong token → 404.
    assert client.get("/opportunity/3/first-touch?k=not-the-token").status_code == 404


def test_first_touch_correct_token_renders_client_and_synopsis(client):
    token = _token(client)
    assert token  # a real, unguessable token was minted
    r = client.get(f"/opportunity/3/first-touch?k={token}")
    assert r.status_code == 200
    # The page is "Prepared for {client}" and carries the brief synopsis.
    from chordential_oia.web import db as db_mod
    from chordential_oia import capabilities
    conn = db_mod.connect()
    try:
        row = db_mod.get_opportunity(conn, 3)
        opp = db_mod.opportunity_from_row(row)
    finally:
        conn.close()
    assert f"Prepared for {row['client']}" in r.text
    # The understanding synopsis (same source as the doc). Jinja HTML-escapes the
    # apostrophe, so compare against the escaped rendering.
    import markupsafe
    assert str(markupsafe.escape(capabilities.build_understanding(opp))) in r.text


def test_first_touch_page_is_public_shell_no_admin_nav(client):
    token = _token(client)
    r = client.get(f"/opportunity/3/first-touch?k={token}")
    assert r.status_code == 200
    # Self-contained public shell — none of the admin nav / chrome leaks in.
    assert "nav-rail" not in r.text
    assert 'href="/dashboard"' not in r.text
    assert "/static/app.js" not in r.text


def test_first_touch_view_increments_and_shows_on_outreach(client):
    token = _token(client)
    # Two valid loads → two views.
    assert client.get(f"/opportunity/3/first-touch?k={token}").status_code == 200
    assert client.get(f"/opportunity/3/first-touch?k={token}").status_code == 200
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        row = db_mod.get_opportunity(conn, 3)
        assert row["first_touch_views"] == 2
        assert row["first_touch_viewed_at"]
    finally:
        conn.close()
    # The outreach view surfaces the engagement signal.
    out = client.get("/opportunity/3/outreach")
    assert out.status_code == 200
    assert "First-touch page viewed 2×" in out.text


def test_first_touch_not_yet_viewed_label(client):
    # Mint a token but never load the page → outreach shows the "not yet viewed" line.
    _token(client)
    out = client.get("/opportunity/3/outreach")
    assert out.status_code == 200
    assert "First-touch page not yet viewed" in out.text


def test_compose_page_link_carries_real_token(client):
    token = _token(client)
    page = client.get("/opportunity/3/compose").text
    # The composer's client link IS the Campaign Brief (one artifact), carrying the real
    # unguessable token — NOT the old ?k=3 stub, and no longer a divergent first-touch page.
    assert f"capabilities?k={token}" in page
    assert "capabilities?k=3" not in page
    # The link must be ABSOLUTE so it's clickable in an email — not a bare path.
    assert f"https://chordential.com/opportunity/3/capabilities?k={token}" in page
    # The tokened brief opens publicly (client link) …
    assert client.get(f"/opportunity/3/capabilities?k={token}").status_code == 200
    # … but a bad token on the brief 404s (never leaks the doc).
    assert client.get("/opportunity/3/capabilities?k=not-the-token").status_code == 404


def test_first_touch_falls_back_to_showcase_music_when_none_picked(client):
    """The page must never dead-end the highest-intent click with silence: when
    no example was hand-picked for the opp, it plays the showcase demo tracks."""
    token = _token(client)
    r = client.get(f"/opportunity/3/first-touch?k={token}")
    assert r.status_code == 200
    from chordential_oia.web.showcase import get_showcase
    demo_urls = [d.audio_url for d in get_showcase().demos if d.audio_url]
    assert demo_urls, "showcase has no demo audio to fall back to"
    # At least the first demo track's audio is embedded in a player on the page.
    assert demo_urls[0] in r.text


def test_first_touch_reply_cta_has_a_real_recipient(client):
    """The 'Reply' CTA must open a draft addressed to a real inbox, not the old
    recipient-less mailto:?subject=… that opened a blank To: line."""
    token = _token(client)
    r = client.get(f"/opportunity/3/first-touch?k={token}")
    assert "mailto:?subject=" not in r.text          # the old empty-recipient bug
    assert "mailto:hello@chordential.com?subject=" in r.text


def test_favicon_route_serves_an_image_not_404(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_first_touch_reachable_when_admin_gate_on(tmp_path, monkeypatch):
    """With the admin gate active, the token-gated page is still reachable (it
    bypasses the login gate) while a normal internal route redirects to login."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "gated.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "s3cret")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        conn = db_mod.connect()
        try:
            token = db_mod.ensure_share_token(conn, 3)
        finally:
            conn.close()
        # An internal route is gated → redirect to the admin login.
        gated = c.get("/opportunity/3/outreach", follow_redirects=False)
        assert gated.status_code == 303
        assert "/admin/login" in gated.headers["location"]
        # The first-touch page bypasses the gate but stays token-protected.
        ok = c.get(f"/opportunity/3/first-touch?k={token}")
        assert ok.status_code == 200
        bad = c.get("/opportunity/3/first-touch?k=wrong", follow_redirects=False)
        assert bad.status_code == 404  # token-gated, not login-redirected
