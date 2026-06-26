"""Delivery OS (Phase 0, Pass A) — engine + routes + portal.

Covers the deterministic delivery engine (clearance certificate, cue sheet,
manifest, revision status) and the web layer (the generated delivery package,
asset upload into the delivery state, the token-gated client portal, and the
approve/release sign-off flow). Mirrors the test_web fixture style.
"""

import importlib
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


# --------------------------------------------------------------------------- #
# Engine unit tests (no web layer)
# --------------------------------------------------------------------------- #
from chordential_oia.delivery import (  # noqa: E402
    build_clearance_certificate,
    build_cue_sheet,
    build_manifest,
    revision_status,
)


def _fake_project(client="AURORA Outdoor Co.", need="Find Your Horizon", opp_id=None):
    return {"id": 1, "client": client, "need": need, "opp_id": opp_id}


def _fake_assignments():
    return [
        {"role": "Composer", "talent_name": "J. Shipp"},
        {"role": "Mixer", "talent_name": "A. Reyes"},
    ]


def test_clearance_certificate_has_contributors_license_and_no_indemnity():
    cert = build_clearance_certificate(
        _fake_project(), _fake_assignments(),
        {"type": "Full buyout", "exclusivity": "Exclusive to client"},
    )
    # Client + campaign.
    assert cert.client == "AURORA Outdoor Co."
    assert cert.campaign == "Find Your Horizon"
    # Contributors (chain of title) carried through from assignments.
    names = {c.name for c in cert.contributors}
    roles = {c.role for c in cert.contributors}
    assert "J. Shipp" in names and "A. Reyes" in names
    assert "Composer" in roles
    # License grant present (override + defaults merged).
    assert cert.license["type"] == "Full buyout"
    assert cert.license["territory"]  # default filled
    assert cert.content_id  # Content-ID-safe status present
    # The original-work warranty + cleared line are stated.
    assert "original" in cert.warranty.lower()
    assert "no samples" in cert.clearance_line.lower()
    # SCOPE: documented & original, indemnity later — NO indemnification clause.
    blob = " ".join([
        cert.warranty, cert.clearance_line, str(cert.license),
        cert.content_id,
    ]).lower()
    assert "indemnif" not in blob
    # The only indemnity mention is the muted "available on request" note.
    assert cert.indemnity_note == "Indemnification available on request."


def test_cue_sheet_rows_from_project_data():
    rows = build_cue_sheet(_fake_project(), _fake_assignments())
    assert len(rows) >= 1
    primary = rows[0]
    assert "Find Your Horizon" in primary.cue
    assert "J. Shipp" in primary.composers
    assert primary.publisher == "Chordential Music"
    assert primary.share == "100%"


def test_manifest_combines_standard_types_and_uploaded_assets():
    assets = [{"label": "Anthem master", "filename": "proj1-1.wav", "kind": "audio"}]
    rows = build_manifest(_fake_project(), assets=assets)
    # Standard scoped deliverable types present.
    assert any(r.status == "Scoped" for r in rows)
    # The uploaded asset appears as a Delivered row.
    delivered = [r for r in rows if r.status == "Delivered"]
    assert any("Anthem master" in r.asset for r in delivered)


def test_revision_status_scoped_used_remaining():
    rs = revision_status(_fake_project(), 3, {"revisions_used": 2})
    assert rs == {"scoped": 3, "used": 2, "remaining": 1, "state": "v1 Concept"}
    # Overrun floors remaining at zero.
    rs2 = revision_status(_fake_project(), 2, {"revisions_used": 5,
                                               "version_state": "v3 FINAL"})
    assert rs2["remaining"] == 0
    assert rs2["state"] == "v3 FINAL"


# --------------------------------------------------------------------------- #
# Web integration tests
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c


def _win_and_make_project(client, opp_id=1):
    client.post(f"/opportunity/{opp_id}/status",
                data={"status": "Won", "outcome_value": "9000"}, follow_redirects=True)
    r = client.post(f"/opportunity/{opp_id}/project", follow_redirects=False)
    return int(re.search(r"/project/(\d+)", r.headers["location"]).group(1))


def _assign_a_creator(client, pid):
    """Assign the first matched creator to the Composer role; return their name."""
    view = client.get(f"/project/{pid}").text
    m = re.search(r'<option value="(\d+)">([^<]+) — fit', view)
    assert m, "no matched creator option on the project page"
    talent_id, name = m.group(1), m.group(2).strip()
    client.post(f"/project/{pid}/assign",
                data={"role": "Composer", "talent_id": talent_id}, follow_redirects=True)
    return name


def test_delivery_package_renders_with_client_contributor_and_certificate(client):
    pid = _win_and_make_project(client, 1)
    name = _assign_a_creator(client, pid)
    r = client.get(f"/project/{pid}/delivery-package")
    assert r.status_code == 200
    body = r.text
    # The client name, an assigned contributor, and the clearance certificate.
    assert name in body
    assert "Clearance Certificate" in body
    assert "Grant of rights" in body
    # No indemnification promise on the artifact.
    assert "indemnif" not in body.lower() or "available on request" in body.lower()


def test_uploading_asset_stores_it_and_it_appears_in_package(client):
    pid = _win_and_make_project(client, 1)
    files = {"file": ("anthem.mp3", b"ID3fakeaudio", "audio/mpeg")}
    client.post(f"/project/{pid}/delivery/asset",
                data={"label": "Anthem master", "action": "add"},
                files=files, follow_redirects=True)
    # It is stored in the delivery state.
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        delivery = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert delivery.get("assets")
    assert delivery["assets"][0]["label"] == "Anthem master"
    assert delivery["assets"][0]["kind"] == "audio"
    # And it appears in the generated package.
    pkg = client.get(f"/project/{pid}/delivery-package").text
    assert "Anthem master" in pkg


def test_portal_404s_on_bad_token_and_200s_with_right_token(client):
    pid = _win_and_make_project(client, 1)
    # Mint the token by hitting the admin package once (ensure_project_share_token).
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        token = db_mod.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    assert token
    # Wrong token → 404.
    assert client.get(f"/project/{pid}/delivery-portal", params={"k": "nope"}).status_code == 404
    # No token → 404.
    assert client.get(f"/project/{pid}/delivery-portal").status_code == 404
    # Right token → 200, branded client page.
    r = client.get(f"/project/{pid}/delivery-portal", params={"k": token})
    assert r.status_code == 200
    assert "Your Delivery" in r.text
    assert "Cleared" in r.text


def test_approve_and_release_mutate_state(client):
    pid = _win_and_make_project(client, 1)
    # Approve logs a sign-off (approved_by + date).
    client.post(f"/project/{pid}/delivery/approve",
                data={"asset": ":60 master", "approver": "Client Lead"},
                follow_redirects=True)
    # Release flips state to Released + stamps released_at.
    client.post(f"/project/{pid}/delivery/release", follow_redirects=True)
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        delivery = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert delivery["approvals"][0]["approver"] == "Client Lead"
    assert delivery["approvals"][0]["asset"] == ":60 master"
    assert delivery["approvals"][0]["date"]  # today's date stamped
    assert delivery["state"] == "Released"
    assert delivery["released_at"]
    # The released state shows on the package.
    pkg = client.get(f"/project/{pid}/delivery-package").text
    assert "RELEASED" in pkg


def test_license_and_revision_mutations(client):
    pid = _win_and_make_project(client, 1)
    client.post(f"/project/{pid}/delivery/license",
                data={"type": "Cross-channel buyout", "territory": "Worldwide",
                      "term": "Perpetuity", "exclusivity": "Exclusive",
                      "content_id": "Content-ID-safe"},
                follow_redirects=True)
    client.post(f"/project/{pid}/delivery/revision",
                data={"action": "log"}, follow_redirects=True)
    client.post(f"/project/{pid}/delivery/revision",
                data={"action": "version", "version_state": "v2 Direction-lock"},
                follow_redirects=True)
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        delivery = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert delivery["license"]["type"] == "Cross-channel buyout"
    assert delivery["revisions_used"] == 1
    assert delivery["version_state"] == "v2 Direction-lock"
    pkg = client.get(f"/project/{pid}/delivery-package").text
    assert "Cross-channel buyout" in pkg


# --------------------------------------------------------------------------- #
# Review Portal (Phase 1) — timestamped comments + approve / request-changes
# --------------------------------------------------------------------------- #
def _project_token(client, pid):
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        return db_mod.ensure_project_share_token(conn, pid)
    finally:
        conn.close()


def test_review_comment_requires_valid_token(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    # Wrong token → 404, no comment stored.
    bad = client.post(f"/project/{pid}/review/comment",
                      data={"k": "nope", "author": "X", "t": "12", "body": "hi"},
                      follow_redirects=False)
    assert bad.status_code == 404
    # Right token → 303 back to the portal.
    ok = client.post(f"/project/{pid}/review/comment",
                     data={"k": token, "author": "Dana (Agency)", "t": "12.4",
                           "body": "Can we remove percussion?"},
                     follow_redirects=False)
    assert ok.status_code == 303


def test_timestamped_comment_renders_on_portal(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "author": "Dana", "t": "12.4",
                      "body": "Can we remove percussion?"})
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    assert "Review &amp; approve" in page          # the Frame.io-for-music section
    assert "Can we remove percussion?" in page     # the comment body
    assert "0:12" in page                          # the timecode (12.4s → 0:12)
    assert 'name="k"' in page                      # forms carry the token


def test_client_approve_sets_state_via_portal(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/approve",
                data={"k": token, "author": "Dana (Agency)"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        assert db_mod.get_delivery(conn, pid).get("state") == "Approved"
        kinds = {c["kind"] for c in db_mod.list_review_comments(conn, pid)}
    finally:
        conn.close()
    assert "approval" in kinds


def test_request_changes_logs_and_bumps_revisions(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/changes",
                data={"k": token, "author": "CD", "note": "Strings should swell at 0:34"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
        rows = db_mod.list_review_comments(conn, pid)
    finally:
        conn.close()
    assert d.get("revisions_used") == 1
    assert any(c["kind"] == "change_request" and "swell" in c["body"] for c in rows)
