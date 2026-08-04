"""A leaked client link can be cut.

The share token is the **only** credential on the delivery portal. Measured against a
gated instance, a bare `?k=` token opens: the unreleased master (streamable), the
client's brief and scope, the deliverables list — and the Request-changes form, which
writes the round ledger and therefore **spends a contractual revision round**
(ADR-0019). Without the token the portal 404s, so the URL *is* the credential.

`ensure_share_token` minted once and returned the same value forever. There was no
rotate, no revoke, no expiry anywhere in the codebase — a forwarded email, an exported
Slack channel, or a departed employee's inbox was permanent access, and the console's
own copy told the operator to "treat it as forwardable" while offering no remedy.

ADR-0039 adds rotation. The trap it has to avoid: a deal can carry **two** live tokens
— the opportunity's (brief / first-touch) and the project's (portal) — so rotating one
and not the other leaves the same work open under the old URL.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "rotate.db"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    return mod


def _a_project(with_opp=False):
    from chordential_oia.web import db
    conn = db.connect()
    try:
        sql = "SELECT * FROM projects WHERE share_token != ''"
        if with_opp:
            sql += " AND opp_id IS NOT NULL"
        row = conn.execute(sql + " ORDER BY id").fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _token(project_id):
    from chordential_oia.web import db
    conn = db.connect()
    try:
        r = conn.execute("SELECT share_token, share_token_rotated_at FROM projects "
                         "WHERE id = ?", (project_id,)).fetchone()
        return (r["share_token"], r["share_token_rotated_at"]) if r else (None, None)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# The exposure that makes rotation necessary
# --------------------------------------------------------------------------- #
def test_the_link_alone_opens_the_work(app_mod):
    """If the URL weren't the whole credential there'd be nothing to rotate."""
    p = _a_project()
    assert p, "no seeded project carries a share token"
    with TestClient(app_mod.app) as c:
        assert c.get(f"/project/{p['id']}/delivery-portal?k={p['share_token']}").status_code == 200
        assert c.get(f"/project/{p['id']}/delivery-portal").status_code == 404


# --------------------------------------------------------------------------- #
# Rotation
# --------------------------------------------------------------------------- #
def test_rotating_kills_the_old_link_and_mints_a_working_one(app_mod):
    p = _a_project()
    old = p["share_token"]
    with TestClient(app_mod.app) as c:
        assert c.post(f"/project/{p['id']}/delivery/rotate-link",
                      follow_redirects=False).status_code == 303
        new, stamp = _token(p["id"])
        assert new and new != old
        assert c.get(f"/project/{p['id']}/delivery-portal?k={old}").status_code == 404
        assert c.get(f"/project/{p['id']}/delivery-portal?k={new}").status_code == 200
    assert stamp, "the rotation was not recorded"


def test_rotating_covers_both_records_of_one_deal(app_mod):
    """The trap. A deal carries the opportunity's token (brief / first-touch) AND the
    project's (portal). Rotating half a credential is not rotating it."""
    from chordential_oia.web import db

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM projects WHERE opp_id IS NOT NULL ORDER BY id").fetchone()
        assert row is not None, "no seeded project is linked to an opportunity"
        p = dict(row)
        # Both links exist in the wild the moment either surface is shared; mint them
        # the same way the app does rather than depending on seed ordering.
        opp_before = db.ensure_share_token(conn, p["opp_id"])
        proj_before = p["share_token"] or db.ensure_project_share_token(conn, p["id"])
    finally:
        conn.close()
    assert opp_before and proj_before

    with TestClient(app_mod.app) as c:
        assert c.get(
            f"/opportunity/{p['opp_id']}/capabilities?k={opp_before}").status_code == 200
        c.post(f"/project/{p['id']}/delivery/rotate-link", follow_redirects=False)

        conn = db.connect()
        try:
            opp_after = conn.execute(
                "SELECT share_token FROM opportunities WHERE id=?",
                (p["opp_id"],)).fetchone()["share_token"]
            proj_after, _ = _token(p["id"])
        finally:
            conn.close()

        assert opp_after != opp_before, "the opportunity's link survived the rotation"
        assert proj_after != proj_before
        assert opp_after == proj_after, "the deal now has two different live links"
        assert c.get(
            f"/opportunity/{p['opp_id']}/capabilities?k={opp_before}",
            follow_redirects=False).status_code != 200, "the old brief link still opens"


def test_rotating_twice_gives_two_different_links(app_mod):
    p = _a_project()
    seen = {p["share_token"]}
    with TestClient(app_mod.app) as c:
        for _ in range(2):
            c.post(f"/project/{p['id']}/delivery/rotate-link", follow_redirects=False)
            tok, _stamp = _token(p["id"])
            assert tok not in seen, "rotation reused a token"
            seen.add(tok)


def test_reviewer_links_are_not_collateral(app_mod):
    """Cutting a leaked share link and revoking one named reviewer are different acts.
    Conflating them would make the safe action destructive — an operator who rotates
    because a link leaked must not silently lock out the people mid-approval."""
    from chordential_oia.web import db

    p = _a_project()
    conn = db.connect()
    try:
        rv = db.add_delivery_reviewer(conn, p["id"], name="Dana Whitfield",
                                      email="dana@agency.com", role="Producer")
    finally:
        conn.close()
    rtok = rv["token"]

    with TestClient(app_mod.app) as c:
        assert c.get(f"/project/{p['id']}/delivery-portal?r={rtok}").status_code == 200
        c.post(f"/project/{p['id']}/delivery/rotate-link", follow_redirects=False)
        assert c.get(f"/project/{p['id']}/delivery-portal?r={rtok}").status_code == 200, (
            "rotating the share link revoked a reviewer's personal link")


def test_a_rotation_is_recorded_on_the_project(app_mod):
    """It changes what the client can reach, so it belongs in the project's history."""
    from chordential_oia.web import db

    p = _a_project()
    with TestClient(app_mod.app) as c:
        c.post(f"/project/{p['id']}/delivery/rotate-link", follow_redirects=False)
    conn = db.connect()
    try:
        notes = " ".join((u["body"] or "") for u in db.list_updates(conn, p["id"]))
    finally:
        conn.close()
    assert "rotated" in notes.lower()


def test_rotating_a_missing_project_is_a_404_not_a_crash(app_mod):
    with TestClient(app_mod.app) as c:
        assert c.post("/project/999999/delivery/rotate-link").status_code == 404


def test_the_engine_refuses_when_nothing_resolves(app_mod):
    from chordential_oia.web import db

    conn = db.connect()
    try:
        assert db.rotate_share_token(conn) is None
        assert db.rotate_share_token(conn, project_id=999999) is None
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# The operator surface
# --------------------------------------------------------------------------- #
def test_the_console_offers_the_control_and_confirms_first(app_mod):
    """Destructive by design — the client's live link stops working — so it asks, and
    it is always an operator press. The machine never rotates on its own."""
    from pathlib import Path

    console = (Path(app_mod.__file__).parent / "templates"
               / "delivery_console.html").read_text(encoding="utf-8")
    assert "delivery/rotate-link" in console, "no way to rotate from the console"
    form = console.split("delivery/rotate-link")[1].split("</form>")[0]
    assert "data-confirm" in form, "a link-breaking action with no confirmation"
    assert "STOP WORKING" in form or "stop working" in form.lower()
    # and it says what it does NOT touch, so the operator isn't guessing
    assert "reviewer" in form.lower()


def test_nothing_rotates_a_link_automatically(app_mod):
    """A token that rotated on a schedule would break a client's bookmark with no
    human deciding to. Rotation has exactly one caller: the operator's route."""
    from pathlib import Path
    import re

    web = Path(app_mod.__file__).parent
    callers = []
    for path in sorted(web.rglob("*.py")):
        if path.name in ("db.py",):
            continue
        src = path.read_text(encoding="utf-8")
        if re.search(r"\brotate_share_token\s*\(", src):
            callers.append(path.name)
    assert callers == ["app.py"], f"unexpected rotation callers: {callers}"
    app_src = (web / "app.py").read_text(encoding="utf-8")
    assert app_src.count("rotate_share_token(") == 1
