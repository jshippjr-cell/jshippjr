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
    cue_sheet_csv,
    current_version,
    manifest_text,
    metadata_json,
    revision_status,
    rights_certificate_text,
    version_label,
    version_name,
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


def test_version_name_is_deterministic_and_formatted():
    # The founder's canonical example.
    assert version_name("Aurora Outdoor", "Anthem", 60, "Master", 3, "FINAL") == \
        "AURORA_Anthem_60_MASTER_v3_FINAL"
    # Campaign slugs to its first significant word, uppercased.
    assert version_name("Vance Athletic — Launch", "Hook", 30, "Inst", 1, "MASTER") == \
        "VANCE_Hook_30_INST_v1_MASTER"
    # Blank length/role/state fields are skipped (no double underscores).
    nm = version_name("Aurora", "Master", "", "", 2, "")
    assert nm == "AURORA_Master_v2"
    assert "__" not in nm


def test_version_label_ladder_and_current_version_helper():
    assert version_label(1) == "v1 Concept"
    assert version_label(2) == "v2 Direction-lock"
    assert version_label(3) == "v3 FINAL"
    # final=True forces FINAL regardless of n.
    assert version_label(2, final=True) == "v2 FINAL"
    # current_version is the latest entry (or None for Phase-0).
    assert current_version({}) is None
    d = {"versions": [{"n": 1}, {"n": 2}, {"n": 3}]}
    assert current_version(d)["n"] == 3


def test_manifest_shows_deterministic_version_named_files():
    versions = [
        {"n": 1, "label": "v1 Concept"},
        {"n": 2, "label": "v2 Direction-lock"},
    ]
    rows = build_manifest(_fake_project(), versions=versions)
    version_rows = [r for r in rows if r.group == "Versions"]
    assert len(version_rows) == 2
    # Deterministic, version-named filenames in the manifest.
    assert any("_v1_" in r.asset for r in version_rows)
    assert any("_v2_" in r.asset for r in version_rows)
    # The campaign token leads the filename.
    assert all(r.asset.startswith("FIND") for r in version_rows)
    # The latest is flagged current.
    assert any("current" in r.asset for r in version_rows)


# --------------------------------------------------------------------------- #
# Delivery automation (Phase 3) — document generators (deterministic, stdlib)
# --------------------------------------------------------------------------- #
def test_cue_sheet_csv_has_header_and_rows():
    import csv as _csv
    import io as _io

    text = cue_sheet_csv(_fake_project(), _fake_assignments())
    rows = list(_csv.reader(_io.StringIO(text)))
    assert rows[0] == ["Cue", "Usage", "Duration", "Composer", "Publisher", "PRO", "Share%"]
    # The primary cue carries the campaign + the assigned composer(s).
    body = "\n".join(",".join(r) for r in rows[1:])
    assert "Find Your Horizon" in body
    assert "J. Shipp" in body
    assert "Chordential Music" in body
    assert "100%" in body


def test_metadata_json_is_clean_and_complete():
    import json as _json

    text = metadata_json(
        _fake_project(), _fake_assignments(),
        license={"type": "Full buyout"},
        versions=[{"n": 1, "label": "v1 Concept", "name": "FIND_Master_v1", "filename": "proj1-v1.wav"}],
        generated_at="2026-06-26T00:00:00+00:00",
    )
    doc = _json.loads(text)
    assert doc["campaign"] == "Find Your Horizon"
    assert doc["client"] == "AURORA Outdoor Co."
    assert doc["license"]["type"] == "Full buyout"
    assert {c["name"] for c in doc["contributors"]} == {"J. Shipp", "A. Reyes"}
    assert doc["versions"][0]["n"] == 1
    assert doc["generated_at"] == "2026-06-26T00:00:00+00:00"


def test_rights_certificate_text_has_contributors_license_no_indemnif():
    cert = build_clearance_certificate(
        _fake_project(), _fake_assignments(), {"type": "Full buyout"})
    text = rights_certificate_text(cert)
    # Contributors / chain of title.
    assert "J. Shipp" in text and "A. Reyes" in text
    # License grant present.
    assert "Full buyout" in text
    assert "Content-ID" in text
    # The original-work / cleared framing.
    assert "original" in text.lower()
    # SCOPE: NO indemnification clause anywhere except the muted note.
    assert "indemnif" not in text.lower().replace(
        "indemnification available on request.", "")


def test_manifest_text_renders_groups_and_status():
    rows = build_manifest(
        _fake_project(),
        assets=[{"label": "Anthem master", "filename": "proj1-1.wav", "kind": "audio"}],
    )
    text = manifest_text(rows)
    assert "DELIVERABLES MANIFEST" in text
    assert "Anthem master" in text
    assert "Delivered" in text


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
        # Phase 3: APPROVE auto-assembles the package and delivers it.
        assert db_mod.get_delivery(conn, pid).get("state") == "Delivered"
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


# --------------------------------------------------------------------------- #
# Versions + revisions + naming (Phase 2)
# --------------------------------------------------------------------------- #
def _upload_version(client, pid, name="cue.mp3"):
    files = {"file": (name, b"ID3fakeaudio-version", "audio/mpeg")}
    return client.post(f"/project/{pid}/delivery/version",
                       data={"action": "add"}, files=files, follow_redirects=True)


def test_second_version_becomes_current_review_track_and_advances_label(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    _upload_version(client, pid, "v1.mp3")
    _upload_version(client, pid, "v2.mp3")
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    versions = d.get("versions")
    assert versions and len(versions) == 2
    assert versions[-1]["n"] == 2
    # The label advanced along the ladder.
    assert d.get("version_state") == "v2 Direction-lock"
    assert versions[-1]["label"] == "v2 Direction-lock"
    # The latest version is the review track on the portal (its URL is the player src).
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    assert versions[-1]["url"] in page
    assert versions[0]["url"] not in page  # the prior version is no longer the player


def test_new_version_reopens_an_approved_delivery(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    _upload_version(client, pid, "v1.mp3")
    client.post(f"/project/{pid}/review/approve", data={"k": token, "author": "Dana"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        # Phase 3: approve delivers (auto-assembles the package).
        assert db_mod.get_delivery(conn, pid).get("state") == "Delivered"
    finally:
        conn.close()
    # A new version supersedes the approval → back to In review.
    _upload_version(client, pid, "v2.mp3")
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert d.get("state") == "In review"


def test_comment_is_tagged_with_current_version_number(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    _upload_version(client, pid, "v1.mp3")
    _upload_version(client, pid, "v2.mp3")
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "author": "Dana", "t": "5", "body": "Tighten the intro"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        rows = db_mod.list_review_comments(conn, pid)
    finally:
        conn.close()
    note = next(c for c in rows if c["kind"] == "comment")
    # Tagged with the current version NUMBER (2), not the version label string.
    assert str(note["version"]) == "2"


def test_portal_renders_version_rail_and_round_of(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    _upload_version(client, pid, "v1.mp3")
    _upload_version(client, pid, "v2.mp3")
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    # The version rail shows which version they're on.
    assert "(current)" in page
    assert "Version history" in page
    # "Round X of Y" surfaces the scoped-vs-used revision rounds.
    assert re.search(r"Round\s+\d+\s+of\s+\d+", page)


def test_approve_locks_current_version_to_final(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    _upload_version(client, pid, "v1.mp3")
    client.post(f"/project/{pid}/review/approve", data={"k": token, "author": "Dana"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert "FINAL" in d["versions"][-1]["label"]
    assert "FINAL" in (d.get("version_state") or "")


# --------------------------------------------------------------------------- #
# Delivery automation (Phase 3) — APPROVE → assemble → ZIP → "download everything"
# --------------------------------------------------------------------------- #
def _seed_asset(client, pid, name="anthem.mp3", label="Broadcast Mix",
                ctype="audio/mpeg"):
    files = {"file": (name, b"ID3fakeaudio-deliverable", ctype)}
    client.post(f"/project/{pid}/delivery/asset",
                data={"label": label, "action": "add"},
                files=files, follow_redirects=True)


def test_approving_via_portal_builds_a_delivery_zip(client):
    import zipfile as _zip

    pid = _win_and_make_project(client, 1)
    name = _assign_a_creator(client, pid)          # contributor for the docs
    _seed_asset(client, pid)                       # an uploaded deliverable
    token = _project_token(client, pid)
    # The agency presses APPROVE on the token-gated portal — the trigger.
    client.post(f"/project/{pid}/review/approve", data={"k": token, "author": "Dana"})

    from chordential_oia.web import db as db_mod, app as app_mod
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    # State flipped to Delivered + descriptor + checklist stored.
    assert d.get("state") == "Delivered"
    zip_desc = d.get("delivery_zip")
    assert zip_desc and zip_desc["url"].startswith("/uploads/")
    assert zip_desc["built_at"]
    checklist = d.get("delivery_checklist")
    assert "Broadcast Mix" in checklist
    assert "Cue Sheet" in checklist and "Rights Certificate" in checklist
    assert "Delivery ZIP" in checklist

    # The ZIP on disk contains the docs + at least one uploaded asset.
    import os
    zip_path = os.path.join(app_mod.UPLOAD_DIR, os.path.basename(zip_desc["url"]))
    assert os.path.isfile(zip_path)
    with _zip.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "Docs/cue_sheet.csv" in names
        assert "Docs/rights_certificate.txt" in names
        assert "Docs/metadata.json" in names
        # At least one uploaded asset is packaged into a named folder.
        assert any(n.startswith(("Masters/", "Cutdowns/", "Social/", "Stems/", "Assets/"))
                   and not n.startswith("Docs/") for n in names)
        # The rights cert text inside the ZIP carries the contributor, no indemnif.
        cert_txt = zf.read("Docs/rights_certificate.txt").decode("utf-8")
        assert name in cert_txt
        assert "indemnif" not in cert_txt.lower().replace(
            "indemnification available on request.", "")


def test_portal_shows_package_ready_and_download_everything(client):
    pid = _win_and_make_project(client, 1)
    _assign_a_creator(client, pid)
    _seed_asset(client, pid)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/approve", data={"k": token, "author": "Dana"})
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    assert "Your delivery package is ready" in page
    assert "Download everything" in page
    # The big button links to the assembled ZIP.
    assert "_Delivery.zip" in page
    # The checklist items are ticked.
    assert "Broadcast Mix" in page
    assert "Rights Certificate" in page


def test_delivery_zip_is_served_by_uploads_route(client):
    pid = _win_and_make_project(client, 1)
    _seed_asset(client, pid)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/approve", data={"k": token, "author": "Dana"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        url = db_mod.get_delivery(conn, pid)["delivery_zip"]["url"]
    finally:
        conn.close()
    r = client.get(url)
    assert r.status_code == 200
    # It's a real ZIP (PK magic bytes).
    assert r.content[:2] == b"PK"


def test_admin_rebuild_route_reassembles_package(client):
    pid = _win_and_make_project(client, 1)
    _seed_asset(client, pid)
    r = client.post(f"/project/{pid}/delivery/build", follow_redirects=False)
    assert r.status_code == 303
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        assert db_mod.get_delivery(conn, pid).get("delivery_zip")
    finally:
        conn.close()


def test_packaging_does_not_crash_without_ffmpeg(client, monkeypatch):
    # Force the "no ffmpeg" path — conversion is skipped, originals still packaged.
    import chordential_oia.delivery as deliv
    monkeypatch.setattr(deliv, "_ffmpeg_exe", lambda: None)
    pid = _win_and_make_project(client, 1)
    # Seed a WAV so the conversion branch is exercised (then skipped).
    _seed_asset(client, pid, name="master.wav", label="Broadcast Mix",
                ctype="audio/wav")
    token = _project_token(client, pid)
    r = client.post(f"/project/{pid}/review/approve",
                    data={"k": token, "author": "Dana"}, follow_redirects=False)
    assert r.status_code == 303
    from chordential_oia.web import db as db_mod, app as app_mod
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert d.get("state") == "Delivered"
    import os, zipfile as _zip
    zip_path = os.path.join(app_mod.UPLOAD_DIR, os.path.basename(d["delivery_zip"]["url"]))
    with _zip.ZipFile(zip_path) as zf:
        names = zf.namelist()
        # The original WAV is present; no MP3 was produced (conversion skipped).
        assert any(n.endswith(".wav") for n in names)
        assert not any(n.endswith(".mp3") for n in names)
