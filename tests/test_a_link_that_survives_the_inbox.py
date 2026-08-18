"""A link is only as good as the mail client that has to find it.

Reported live: a composer opened his portal link from the Gmail app on a phone and got
**Not found**. The same link worked on a desktop. Nothing was wrong with the server —
with the admin gate on and no cookie at all, ``/creator/<token>`` returns 200 — and
nothing was wrong with the token. What was wrong was the shape of the email.

Two faults compounded:

1. Five client- and creator-facing sends passed no ``html``, so the only copy of the
   link was a bare URL in plain text. The recipient's mail client then has to FIND the
   URL and guess where it ends.
2. Every public token was minted by ``secrets.token_urlsafe``, whose base64url alphabet
   includes ``-`` and ``_``. Roughly one link in thirty therefore ends in punctuation —
   his was ``ouLvIvWMxli-zHT-`` — and a linkifier reads a trailing hyphen as the end of
   a sentence and trims it. The trimmed token resolves to nobody: 404.

Both are fixed at the floor rather than per call site, because per call site is how it
was missed five times. ``send_email`` wraps any body containing a URL in the branded
shell (a real ``<a href>``, exact, nothing to guess), and ``db.public_token`` mints from
letters and digits only.
"""
import ast
import pathlib

import pytest

from chordential_oia import mailer

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"


# ── the token can no longer end in something a linkifier eats ────────────────────────
def test_a_public_token_is_letters_and_digits_only():
    from chordential_oia.web import db
    for _ in range(400):
        tok = db.public_token()
        assert tok.isalnum(), f"{tok!r} carries a character a URL parser may trim"
        assert len(tok) == 16


def test_the_length_is_honoured_and_the_entropy_is_real():
    from chordential_oia.web import db
    assert len(db.public_token(13)) == 13
    assert len({db.public_token(13) for _ in range(500)}) == 500


def test_nothing_public_facing_still_mints_from_base64url():
    """``accounts`` is the deliberate exception — a session token lives in a cookie, not
    in a link anybody has to retype."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "accounts.py":
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if "token_urlsafe(" in line and not line.lstrip().startswith("#"):
                offenders.append(f"{path.relative_to(SRC)}:{i}")
    assert offenders == [], (
        "these mint a link token from an alphabet containing - and _: "
        + ", ".join(offenders))


# ── a body with a link always gets a real anchor ─────────────────────────────────────
def _sent(monkeypatch):
    captured = {}

    def fake_smtp(to, subject, text, html, ics, files):
        captured.update(to=to, subject=subject, text=text, html=html)
        return "sent"

    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(mailer, "_send_smtp", fake_smtp)
    return captured


def test_a_plain_body_carrying_a_url_is_wrapped(monkeypatch):
    captured = _sent(monkeypatch)
    url = "https://chordential.com/creator/ouLvIvWMxli-zHT-"
    mailer.send_email("composer@example.com", "Your workspace",
                      f"Your workspace is here:\n\n{url}\n\nNo password needed.")
    html = captured["html"]
    assert html is not None, "a link went out with no HTML part to anchor it"
    assert f'href="{url}"' in html, (
        "the href must be the WHOLE url — a trailing hyphen is part of the token, "
        "and a client that trims it sends the composer to a 404")
    assert captured["text"].endswith("No password needed."), "the text part is untouched"


def test_a_body_with_no_link_stays_plain(monkeypatch):
    captured = _sent(monkeypatch)
    mailer.send_email("x@example.com", "Note", "The session moved to Tuesday.")
    assert captured["html"] is None


def test_an_explicit_html_argument_still_wins(monkeypatch):
    captured = _sent(monkeypatch)
    mailer.send_email("x@example.com", "Note", "See https://chordential.com/x",
                      html="<p>mine</p>")
    assert captured["html"] == "<p>mine</p>"


# ── the tripwire: no call site may send a link as bare text ──────────────────────────
def test_every_send_that_carries_a_link_carries_an_anchor():
    """``send_email`` now wraps automatically, so this cannot regress by omission — but
    a caller that passes ``html=`` explicitly can still hand-roll a shell that drops the
    anchor. Any such call must go through ``branded_html``."""
    bad = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        src = path.read_text()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", getattr(node.func, "id", "")) != "send_email":
                continue
            kwargs = {k.arg: k.value for k in node.keywords}
            if "html" not in kwargs:
                continue                      # wrapped by send_email itself
            seg = ast.get_source_segment(src, kwargs["html"]) or ""
            if "branded_html" not in seg:
                bad.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert bad == [], (
        "these pass their own html= without the branded shell, which is the only thing "
        "that guarantees a real <a href>: " + ", ".join(bad))


# ── end to end: the composer's actual link, from mail to page ────────────────────────
@pytest.fixture()
def gated(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "inbox.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    for m in ("db", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from chordential_oia.web import app as app_mod
    with fastapi_testclient.TestClient(app_mod.app) as c:
        yield c, app_mod


def test_the_emailed_link_opens_with_no_cookie(gated, monkeypatch):
    """The whole round trip: issue creator access, take the URL out of the *HTML* part
    the way a phone would, and open it with no session at all."""
    import re

    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent

    c, app_mod = gated
    captured = _sent(monkeypatch)
    conn = app_mod.db.connect()
    try:
        tid = app_mod.db.insert_talent(conn, Talent(
            name="Ada Verano", email="ada@example.com",
            disciplines=[MusicDiscipline.COMPOSITION]))
    finally:
        conn.close()

    c.post("/admin/login", data={"email": "", "password": "passphrase"},
           follow_redirects=False)
    c.post(f"/talent/{tid}/portal", follow_redirects=False)

    href = re.search(r'href="([^"]*/creator/[^"]+)"', captured["html"])
    assert href, "the creator's portal mail carried no anchored link"
    path = href.group(1).split("chordential.com", 1)[-1]

    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as phone:       # a fresh client == no admin cookie
        r = phone.get(path, follow_redirects=False)
    assert r.status_code == 200, f"the composer's own link returned {r.status_code}"
    assert "Password or passphrase" not in r.text
