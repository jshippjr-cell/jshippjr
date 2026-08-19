"""A gate exemption is a promise the route makes, and three routes were not keeping it.

Found by a security review of THE room (ADR-0068). The pattern is one mistake wearing
three faces, and this codebase had already fixed it once — which is exactly why it needs
a test and not another fix.

`_is_delivery_portal_path` exempts a set of paths from the admin login gate so a client
with a link and a creator with a token can reach them. Every exempted route is supposed
to make its OWN, stricter check. These did not, and their tokenless arm was written back
when the gate was the check:

* `review_reopen` validated `if k or r:` and did nothing otherwise. An anonymous POST
  cleared the creative lock, dropped FINAL back to a round label, **un-shipped a
  Delivered package and revoked a paid client's download** — and logged itself as
  "Studio".
* `session_room_poll` / `session_room_presence` call `_session_role`, whose no-token arm
  returned `("operator", "Studio")`. Anonymous GET returned the operator-audience event
  stream — note bodies, author names, the presence roster — and anonymous POST injected
  a forged participant under any name, as an operator.

The fix is at the source: `_session_role` proves an admin session when no credential is
presented, so its callers inherit it and a fourth caller cannot forget. `review_reopen`
makes the same check in its own arm.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def gated(tmp_path, monkeypatch):
    """The gate ON — production's shape. Without it there is nothing to exempt from."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "sec.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as jon:
        jon.post("/admin/login", data={"email": "", "password": "passphrase"},
                 follow_redirects=False)
        conn = app_mod.db.connect()
        try:
            pid = conn.execute(
                "SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        finally:
            conn.close()
        yield jon, app_mod, pid


def _stranger(app_mod):
    from fastapi.testclient import TestClient
    return TestClient(app_mod.app)          # a fresh client == no admin cookie


# ── the destructive one ─────────────────────────────────────────────────────────────
def test_a_stranger_cannot_reopen_a_delivered_project(gated):
    """The worst of the three: it does not read, it DESTROYS. On a Delivered project it
    un-ships the package and locks the client out of a download they paid for."""
    jon, app_mod, pid = gated
    with _stranger(app_mod) as anon:
        r = anon.post(f"/project/{pid}/review/reopen", data={}, follow_redirects=False)
    assert r.status_code == 404, (
        "an anonymous POST can clear the creative lock and un-ship a delivery")


def test_the_studio_can_still_reopen(gated):
    """Approval is not a one-way door for the operator — the fix must not take that."""
    jon, app_mod, pid = gated
    assert jon.post(f"/project/{pid}/review/reopen", data={},
                    follow_redirects=False).status_code == 303


# ── the leaking pair ────────────────────────────────────────────────────────────────
def test_a_stranger_gets_no_event_stream(gated):
    """It answered with the OPERATOR audience: note bodies, author names, who is in the
    room. Role filtering is server-side and was doing its job — it was simply being
    asked the wrong question."""
    jon, app_mod, pid = gated
    with _stranger(app_mod) as anon:
        assert anon.get(f"/project/{pid}/session.json").status_code == 404


def test_a_stranger_cannot_forge_their_way_into_the_room(gated):
    """Presence with no credential was accepted AS AN OPERATOR under any name — a face
    in the room that nobody let in."""
    jon, app_mod, pid = gated
    with _stranger(app_mod) as anon:
        r = anon.post(f"/project/{pid}/presence",
                      data={"name": "Not Invited"}, follow_redirects=False)
    assert r.status_code == 404
    seen = jon.get(f"/project/{pid}/session.json").json()
    assert not any(p["name"] == "Not Invited" for p in seen["presence"])


def test_the_studio_still_holds_the_room(gated):
    jon, app_mod, pid = gated
    assert jon.get(f"/project/{pid}/session.json").status_code == 200
    assert jon.post(f"/project/{pid}/presence",
                    data={"name": "Studio"}, follow_redirects=False).status_code == 200


def test_a_client_and_a_creator_still_reach_the_bus(gated):
    """The exemption exists FOR them. Closing the hole must not close the door."""
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    jon, app_mod, pid = gated
    db = app_mod.db
    conn = db.connect()
    try:
        ktok = db.ensure_project_share_token(conn, pid)
        tid = db.insert_talent(conn, Talent(name="Ada Verano", email="a@e.com",
                                            rate=90.0,
                                            disciplines=[MusicDiscipline.COMPOSITION]))
        db.add_assignment(conn, pid, "Composer", tid)
        ttok = db.ensure_talent_portal_token(conn, tid)
    finally:
        conn.close()
    with _stranger(app_mod) as anon:
        assert anon.get(f"/project/{pid}/session.json",
                        params={"k": ktok}).status_code == 200
        assert anon.get(f"/project/{pid}/session.json",
                        params={"t": ttok}).status_code == 200


# ── the rule itself ─────────────────────────────────────────────────────────────────
def test_the_tokenless_arm_is_proved_at_the_source(gated):
    """One root, three doors. `_session_role` is where the assumption lived, so it is
    where the proof belongs — a fourth caller then cannot re-open this by forgetting."""
    from chordential_oia.web.project_routes import _session_role
    jon, app_mod, pid = gated
    conn = app_mod.db.connect()
    try:
        # No request object at all → the caller is inside the gate (the console). That is
        # the only remaining way to be handed "operator" without proving it.
        role, _ = _session_role(conn, pid, "", "", "")
        assert role == "operator"

        class _Anon:
            cookies: dict = {}
            headers: dict = {}
        role2, _ = _session_role(conn, pid, "", "", "", _Anon())
        assert role2 is None, "a request with no credential resolved to the operator"
    finally:
        conn.close()


# ── the client's words ──────────────────────────────────────────────────────────────
def test_a_change_request_from_the_room_keeps_what_was_asked(gated):
    """The room posts `body`; the route read only `note`. Every change request raised in
    the room logged "Requested changes.", notified with an empty note, and still burned a
    revision round — a round spent with no record of what was wanted."""
    jon, app_mod, pid = gated
    db = app_mod.db
    conn = db.connect()
    try:
        ktok = db.ensure_project_share_token(conn, pid)
        db.update_delivery(conn, pid, "versions",
                           [{"n": 1, "label": "v1 Concept", "url": "/uploads/v1.wav"}])
    finally:
        conn.close()
    with _stranger(app_mod) as client:
        client.post(f"/project/{pid}/review/changes",
                    data={"k": ktok, "author": "Marta Reyes", "email": "m@e.org",
                          "body": "The strings are too bright at 0:12."},
                    follow_redirects=False)
    conn = db.connect()
    try:
        said = " ".join((c["body"] or "") for c in db.list_review_comments(conn, pid))
    finally:
        conn.close()
    assert "too bright" in said, "the client's words were discarded, the round was not"
