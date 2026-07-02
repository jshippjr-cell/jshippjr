"""Composer portal — a qualified creator's token-gated workspace.

A creator's only credential is an unguessable portal token (no password). The
portal shows their assigned briefs and lets them submit work versions into the
same delivery ladder the admin Assets agent uses — guarded by token AND a real
assignment to the project.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod, app_mod


def _approved_composer(db_mod, name="Mara Velez"):
    from chordential_oia.talent import Talent, ReviewStatus
    from chordential_oia.models import MusicDiscipline
    conn = db_mod.connect()
    try:
        tid = db_mod.insert_talent(conn, Talent(
            name=name, disciplines=[MusicDiscipline.COMPOSITION],
            review_status=ReviewStatus.APPROVED,
        ))
    finally:
        conn.close()
    return tid


def _project_with(db_mod, talent_id, role="Composer", need="Brand anthem"):
    conn = db_mod.connect()
    try:
        pid = db_mod.insert_project(conn, None, "AURORA", need, 0, 0, [role], "2026-08-01")
        db_mod.add_assignment(conn, pid, role, talent_id)
    finally:
        conn.close()
    return pid


def test_issue_token_and_open_portal(ctx):
    client, db_mod, _ = ctx
    tid = _approved_composer(db_mod)
    # Admin issues the access link from the talent detail page.
    client.post(f"/talent/{tid}/portal")
    conn = db_mod.connect()
    try:
        tok = conn.execute(
            "SELECT portal_token FROM talent WHERE id=?", (tid,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert tok
    r = client.get(f"/creator/{tok}")
    assert r.status_code == 200
    assert "Creator workspace" in r.text


def test_portal_shows_assigned_brief(ctx):
    client, db_mod, _ = ctx
    tid = _approved_composer(db_mod)
    _project_with(db_mod, tid, need="Lumen launch film")
    conn = db_mod.connect()
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    conn.close()
    page = client.get(f"/creator/{tok}").text
    assert "Lumen launch film" in page
    assert "Composer" in page


def _composer_with_email(db_mod, name="Ada Lin", email="ada@example.com"):
    from chordential_oia.talent import Talent, ReviewStatus
    from chordential_oia.models import MusicDiscipline
    conn = db_mod.connect()
    try:
        return db_mod.insert_talent(conn, Talent(
            name=name, email=email, disciplines=[MusicDiscipline.COMPOSITION],
            review_status=ReviewStatus.APPROVED))
    finally:
        conn.close()


def test_creator_submission_is_pending_not_client_visible(ctx):
    """A creator's submission must NOT go straight to the client — it waits as a
    pending submission for Jon to vet ('machine proposes, Jon disposes'). It is off
    the version ladder until published."""
    client, db_mod, app_mod = ctx
    tid = _approved_composer(db_mod)
    pid = _project_with(db_mod, tid)
    conn = db_mod.connect()
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    conn.close()
    r = client.post(
        f"/creator/{tok}/project/{pid}/version",
        files={"file": ("demo.mp3", b"ID3audio-bytes", "audio/mpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert not (d.get("versions") or [])               # NOT on the client ladder yet
    assert d.get("pending_version")                     # …held for Jon to publish
    assert d["pending_version"]["by"] == "Mara Velez"


def test_publish_moves_pending_into_ladder_and_notifies_client(ctx, monkeypatch):
    """Jon's 'Publish to client' moves the pending submission into the version ladder
    (now client-visible) and notifies the reviewers."""
    client, db_mod, app_mod = ctx
    tid = _approved_composer(db_mod)
    pid = _project_with(db_mod, tid)
    conn = db_mod.connect()
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    # a reviewer with an email, so publish has someone to notify
    db_mod.add_delivery_reviewer(conn, pid, name="Dana", email="dana@brand.com",
                                 role="Producer")
    conn.close()
    client.post(f"/creator/{tok}/project/{pid}/version",
                files={"file": ("v1.mp3", b"ID3fake", "audio/mpeg")})
    sent = []
    monkeypatch.setattr(app_mod.mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(app_mod.mailer, "send_email",
                        lambda to, s, t, html=None: sent.append(to) or "sent")
    monkeypatch.setattr(app_mod.signals, "fire_and_forget",
                        lambda fn, *a, **k: fn(*a, **k))
    r = client.post(f"/project/{pid}/delivery/publish",
                    data={"action": "publish"}, follow_redirects=False)
    assert r.status_code == 303
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert len(d.get("versions") or []) == 1            # now on the client ladder
    assert not d.get("pending_version")                 # …and consumed
    assert "dana@brand.com" in sent                     # reviewers notified on publish


def test_discard_drops_the_pending_submission(ctx):
    client, db_mod, app_mod = ctx
    tid = _approved_composer(db_mod)
    pid = _project_with(db_mod, tid)
    conn = db_mod.connect()
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    conn.close()
    client.post(f"/creator/{tok}/project/{pid}/version",
                files={"file": ("v1.mp3", b"ID3fake", "audio/mpeg")})
    client.post(f"/project/{pid}/delivery/publish", data={"action": "discard"})
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert not d.get("pending_version") and not (d.get("versions") or [])


def _publish(client, pid):
    """Jon vets + publishes the pending creator submission (test helper)."""
    client.post(f"/project/{pid}/delivery/publish", data={"action": "publish"})


def test_creator_portal_shows_client_feedback_on_current_version(ctx):
    """The composer must see the client's timecoded notes directly on their portal
    — the loop the review feature exists to close (no more hand-relayed feedback)."""
    client, db_mod, app_mod = ctx
    tid = _composer_with_email(db_mod)
    pid = _project_with(db_mod, tid)
    conn = db_mod.connect()
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    share = db_mod.ensure_project_share_token(conn, pid)
    conn.close()
    # Composer submits v1; Jon publishes it → it becomes the current version, tagged "1".
    client.post(f"/creator/{tok}/project/{pid}/version",
                files={"file": ("v1.mp3", b"ID3fake", "audio/mpeg")})
    _publish(client, pid)
    # Client requests changes on it (guest share-token path).
    client.post(f"/project/{pid}/review/changes",
                data={"k": share, "author": "Client", "email": "c@brand.com",
                      "note": "Bring the brass in later, around 0:14."})
    page = client.get(f"/creator/{tok}").text
    assert "Client feedback" in page
    assert "Bring the brass in later" in page          # the actual note, on the portal
    assert "changes" in page                            # the change-request tag


def test_review_changes_notifies_the_assigned_creator(ctx, monkeypatch):
    """When the client requests changes, the assigned composer is emailed directly
    (off the request thread) — not left waiting for a hand-relay."""
    client, db_mod, app_mod = ctx
    tid = _composer_with_email(db_mod, email="ada@example.com")
    pid = _project_with(db_mod, tid)
    conn = db_mod.connect()
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    share = db_mod.ensure_project_share_token(conn, pid)
    conn.close()
    client.post(f"/creator/{tok}/project/{pid}/version",
                files={"file": ("v1.mp3", b"ID3fake", "audio/mpeg")})
    _publish(client, pid)

    sent = []
    monkeypatch.setattr(app_mod.mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(app_mod.mailer, "send_email",
                        lambda to, s, t, html=None: sent.append((to, s, t)) or "sent")
    # Run the fire-and-forget notification inline so the assertion is deterministic.
    monkeypatch.setattr(app_mod.signals, "fire_and_forget",
                        lambda fn, *a, **k: fn(*a, **k))
    client.post(f"/project/{pid}/review/changes",
                data={"k": share, "author": "Client", "email": "c@brand.com",
                      "note": "Tighten the intro."})
    assert any(to == "ada@example.com" for to, _, _ in sent)
    assert any("changes requested" in s.lower() or "changes —" in s.lower()
               for _, s, _ in sent)


def test_review_changes_never_crashes_without_creator_email_or_mail(ctx):
    """No email on the creator (or mail unconfigured) must not break the client's
    change request — the notification is strictly additive."""
    client, db_mod, app_mod = ctx
    tid = _approved_composer(db_mod)                    # no email
    pid = _project_with(db_mod, tid)
    conn = db_mod.connect()
    share = db_mod.ensure_project_share_token(conn, pid)
    conn.close()
    r = client.post(f"/project/{pid}/review/changes",
                    data={"k": share, "author": "Client", "email": "c@brand.com",
                          "note": "Change it."}, follow_redirects=False)
    assert r.status_code == 303


def test_upload_blocked_when_not_assigned(ctx):
    client, db_mod, _ = ctx
    tid = _approved_composer(db_mod)
    conn = db_mod.connect()
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    # a project the creator is NOT assigned to
    other = db_mod.insert_project(conn, None, "X", "Other", 0, 0, ["Composer"], None)
    conn.close()
    r = client.post(
        f"/creator/{tok}/project/{other}/version",
        files={"file": ("x.mp3", b"x", "audio/mpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_bogus_token_404(ctx):
    client, _, _ = ctx
    assert client.get("/creator/not-a-real-token").status_code == 404


def test_w9_toggle(ctx):
    client, db_mod, _ = ctx
    tid = _approved_composer(db_mod)
    client.post(f"/talent/{tid}/w9", data={"received": "1"})
    conn = db_mod.connect()
    try:
        w9 = conn.execute(
            "SELECT w9_received_at FROM talent WHERE id=?", (tid,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert w9  # a date was recorded
    client.post(f"/talent/{tid}/w9", data={"received": "0"})
    conn = db_mod.connect()
    try:
        w9 = conn.execute(
            "SELECT w9_received_at FROM talent WHERE id=?", (tid,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert w9 is None


def test_portal_bypasses_admin_gate(ctx, monkeypatch):
    # With an admin token set, the creator portal is still reachable by its own token.
    client, db_mod, app_mod = ctx
    tid = _approved_composer(db_mod)
    conn = db_mod.connect()
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    conn.close()
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "secret")
    r = client.get(f"/creator/{tok}", follow_redirects=False)
    assert r.status_code == 200  # not redirected to /admin/login
