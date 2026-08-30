"""A client behind a share token must never be shown the internal login.

Reported live, and about as bad as a client-facing bug gets. A client opened her
Discovery Summary from the link in her email, read it, typed her name, drew her
signature, pressed **Sign and accept** — and was shown a page saying
*"Procurement OS — internal / Password or passphrase"*.

The cause was a one-word gap. `/workspace/{token}/sign` had been added to the router and
not to `app._WORKSPACE_RE`, the alternation that exempts token-gated client paths from the
admin gate. The GET was exempt, so the summary rendered perfectly and the gap appeared
only at the single moment the whole document exists for.

The list cannot be trusted to keep up with the router by hand, so the first test here
derives it FROM the router. That is the part that matters: the specific fix is one word,
and the same word will go missing again on the next route.
"""
import importlib
import re

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def gated(tmp_path, monkeypatch):
    """The app with the admin gate ON — the only configuration where this can fail."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "gate.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "a-shared-passphrase")
    for m in ("db", "campaign_intelligence", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    from chordential_oia.web import publicpaths as _gate
    with TestClient(app_mod.app) as c:
        yield c, app_mod


def _signable_deal(app_mod):
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    db = app_mod.db
    conn = db.connect()
    try:
        oid = db.insert_opportunity(conn, Opportunity(
            client="The Larkspur Trust", need="Winter appeal film",
            description="Three-minute charity film with a 90-second wordless middle "
                        "section, plus a 30-second social cut.",
            buyer_type=BuyerType.BRAND, music_requirement=MusicRequirement.ORIGINAL))
        db.create_meeting(conn, opp_id=oid, start_at="2026-07-01T14:00:00+00:00",
                          status="ingested")
        return oid, db.ensure_share_token(conn, oid)
    finally:
        conn.close()


def test_every_workspace_route_is_exempt_from_the_admin_gate():
    """Derived from the router, so the exemption cannot fall behind it.

    Checking the one missing path would have fixed this bug and not the next one. A
    route added behind the client's token and left out of the gate is invisible until a
    client presses the button, which is the worst possible moment to discover it.
    """
    from pathlib import Path

    from chordential_oia.web import app as app_mod, workspace_routes
    from chordential_oia.web import publicpaths as _gate

    src = Path(workspace_routes.__file__).read_text(encoding="utf-8")
    declared = re.findall(r'^@router\.[a-z]+\("(/workspace/[^"]*)"', src, re.M)
    assert len(declared) >= 5, "the router scrape found nothing — the pattern drifted"

    missing = []
    for path in declared:
        # Substitute a realistic token for the path parameter.
        concrete = path.replace("{token}", "Ab3xY9zQ_-01")
        if not _gate.is_public(concrete):
            missing.append(path)
    assert missing == [], (
        f"these client routes sit behind the admin gate and will bounce a client to "
        f"the internal login: {missing}")


def test_a_client_can_sign_without_ever_seeing_the_gate(gated):
    """The exact reported journey, end to end, with the gate on."""
    c, app_mod = gated
    oid, token = _signable_deal(app_mod)

    page = c.get(f"/workspace/{token}", follow_redirects=False)
    assert page.status_code == 200
    assert "Password or passphrase" not in page.text

    r = c.post(f"/workspace/{token}/sign",
               data={"typed_name": "Nadia Okonjo", "signer_email": "nadia@larkspur.example",
                     "consent": "1"},
               follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" not in r.headers.get("location", ""), (
        "the client was bounced to the internal login at the moment of signing")

    from chordential_oia.signing import DOC_PROPOSAL
    conn = app_mod.db.connect()
    try:
        sig = app_mod.db.latest_opportunity_signature(conn, oid, DOC_PROPOSAL)
    finally:
        conn.close()
    assert sig is not None and sig["typed_name"] == "Nadia Okonjo", (
        "the signature never landed — the gate ate the POST")


def test_an_old_link_still_works(gated):
    """The share token is durable by design (ADR-0018): one URL that never changes. The
    operator's first guess was that his wife's link had gone stale after a deploy, and it
    had not — worth pinning, because 'your link is old' is the kind of explanation that
    sounds right and sends everyone looking in the wrong place."""
    c, app_mod = gated
    oid, token = _signable_deal(app_mod)
    conn = app_mod.db.connect()
    try:
        assert app_mod.db.ensure_share_token(conn, oid) == token, "the token rotated"
    finally:
        conn.close()
    assert c.get(f"/workspace/{token}", follow_redirects=False).status_code == 200


def test_a_bad_token_is_not_found_rather_than_a_login(gated):
    """The gate exemption is on the PATH, so the route does its own stricter check
    (CLAUDE.md). A wrong token must 404 — never leak into the console, and never ask a
    stranger for our passphrase."""
    c, _app_mod = gated
    r = c.post("/workspace/not-a-real-token/sign",
               data={"typed_name": "Someone", "signer_email": "x@y.example", "consent": "1"},
               follow_redirects=False)
    assert r.status_code == 404


def test_the_login_page_renders_real_punctuation(gated):
    """A Python escape written into HTML means nothing there. The failed-password screen
    read `That didn\\u2019t match. Try again.` — the raw escape, on the one page a
    misdirected client actually reaches."""
    c, _app_mod = gated
    page = c.get("/admin/login?err=1").text
    assert "\\u2019" not in page and "\\u2014" not in page
    r = c.post("/admin/login", data={"email": "", "password": "wrong"},
               follow_redirects=True)
    assert "\\u" not in r.text, "an escape sequence is being shown to a human"
