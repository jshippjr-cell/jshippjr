"""Two submit buttons on one card threw away whichever file the other was holding.

Reported live: *"I clicked 'add a reference' … as soon as I added the reference, it took
the file but refreshed the page. I had a video loaded in the box 'drop your cut here' but
that disappeared because I clicked add a reference."*

The picture card carried two independent forms, each with its own submit. Whichever fired
first navigated, and the browser discarded the file chosen in the other — silently, so
the client believed they had sent a cut they had not. And each button also *delivered*,
so there was no way to gather a cut and two references and hand them over together, which
is how anyone actually briefs a composer.

The card now stages, and `/project/<id>/review/assets` is the one door: every part
optional, one handover, one notification. The per-file routes remain the operator's door
and the no-JS fallback.
"""
import importlib
import re

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def portal(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "hand.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        conn = app_mod.db.connect()
        try:
            pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
            tok = app_mod.db.ensure_project_share_token(conn, pid)
        finally:
            conn.close()
        yield c, app_mod, pid, tok


def _mp4(name="cut.mp4"):
    return (name, b"\x00\x00\x00\x18ftypmp42" + b"0" * 600, "video/mp4")


def _wav(name="ref.wav"):
    return (name, b"RIFF" + b"0" * 400, "audio/wav")


def _delivery(app_mod, pid):
    conn = app_mod.db.connect()
    try:
        return app_mod.db.get_delivery(conn, pid) or {}
    finally:
        conn.close()


# ── one act ─────────────────────────────────────────────────────────────────────────
def test_a_cut_and_references_arrive_together(portal):
    c, app_mod, pid, tok = portal
    r = c.post(f"/project/{pid}/review/assets",
               data={"k": tok, "author": "Marta Reyes",
                     "ref_label": ["The Bonobo track, 1:10–1:40", "Our last spot"]},
               files=[("file", _mp4()),
                      ("ref_file", _wav("bonobo.wav")),
                      ("ref_file", _wav("last-spot.wav"))],
               follow_redirects=False)
    assert r.status_code == 303
    d = _delivery(app_mod, pid)
    assert d.get("picture", {}).get("orig") == "cut.mp4", "the cut did not survive"
    labels = [x["label"] for x in d.get("references", [])]
    assert "The Bonobo track, 1:10–1:40" in labels
    assert "Our last spot" in labels, "the second reference was dropped"


def test_each_part_is_optional(portal):
    """A client with only references, or only a cut, must not be forced to invent the
    other half."""
    c, app_mod, pid, tok = portal
    c.post(f"/project/{pid}/review/assets",
           data={"k": tok, "author": "Marta", "ref_label": ["Just a mood"]},
           files=[("ref_file", _wav("mood.wav"))], follow_redirects=False)
    d = _delivery(app_mod, pid)
    assert d.get("picture") is None
    assert [x["label"] for x in d.get("references", [])] == ["Just a mood"]

    c.post(f"/project/{pid}/review/assets", data={"k": tok, "author": "Marta"},
           files=[("file", _mp4("locked.mp4"))], follow_redirects=False)
    d = _delivery(app_mod, pid)
    assert d.get("picture", {}).get("orig") == "locked.mp4"
    assert len(d.get("references", [])) == 1, "sending a cut wiped the references"


def test_sending_nothing_changes_nothing(portal):
    c, app_mod, pid, tok = portal
    before = _delivery(app_mod, pid)
    r = c.post(f"/project/{pid}/review/assets", data={"k": tok, "author": "Marta"},
               follow_redirects=False)
    assert r.status_code == 303
    assert _delivery(app_mod, pid).get("picture") == before.get("picture")


def test_a_bad_token_is_refused(portal):
    c, _app_mod, pid, _tok = portal
    r = c.post(f"/project/{pid}/review/assets", data={"k": "nope"},
               files=[("file", _mp4())], follow_redirects=False)
    assert r.status_code == 404


def test_the_client_never_meets_the_login(portal):
    """The payer/uploader is a buyer with a link, not a user. This route must be exempt
    from the admin gate like every other review action."""
    from fastapi.testclient import TestClient
    _c, app_mod, pid, tok = portal
    with TestClient(app_mod.app) as buyer:          # fresh client == no admin cookie
        r = buyer.post(f"/project/{pid}/review/assets",
                       data={"k": tok, "author": "Marta"},
                       files=[("file", _mp4())], follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" not in r.headers.get("location", "")


# ── the card itself ─────────────────────────────────────────────────────────────────
def test_the_card_has_one_form_and_one_send(portal):
    """The defect was structural — two <form>s. If a second one comes back, so does the
    bug, and it will be silent again."""
    c, _app_mod, pid, tok = portal
    page = c.get(f"/project/{pid}/delivery-portal?k={tok}").text
    card = page[page.index('id="picture"'):page.index('id="review"')]
    assert card.count("<form") == 1, (
        "the picture card has more than one form — whichever submits first discards the "
        "files staged in the other")
    assert card.count('type="submit"') == 1
    assert "/review/assets" in card
    # Adding a reference must be a staging act, never a submit.
    assert 'id="ref-add"' in card and 'type="button"' in card
    assert re.search(r'id="ref-add"[^>]*type="button"|type="button"[^>]*id="ref-add"',
                     card), "the add-a-reference control can still submit the form"
