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
    brief_deliverables,
    brief_rollup,
    build_manifest,
    build_timeline,
    cue_sheet_csv,
    current_version,
    manifest_text,
    metadata_json,
    reconcile_brief,
    revision_status,
    rights_certificate_text,
    seed_brief,
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
    # IP3 SCOPE: documented & original, indemnity later — NO indemnification clause
    # AND no indemnity mention anywhere (the half-promise is removed entirely).
    blob = " ".join([
        cert.warranty, cert.clearance_line, str(cert.license),
        cert.content_id, str(cert.signatory),
    ]).lower()
    assert "indemnif" not in blob
    # IP3: a signatory block is present (entity + an authorized signer).
    assert cert.signatory["entity"]
    assert cert.signatory["signer"]


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
# Creative brief + campaign timeline (Phase 4) — deterministic engine tests
# --------------------------------------------------------------------------- #
def test_seed_brief_defaults_from_opportunity_then_stored_wins():
    project = {"id": 1, "need": "Find Your Horizon", "deadline": "2026-07-15",
               "opp_id": 9}
    opp = {"need": "Find Your Horizon", "description": "Warm, cinematic, hopeful."}
    # No stored brief → seeded from the opportunity/project.
    brief = seed_brief(project, opp, {})
    assert "Find Your Horizon" in brief["objective"]
    assert brief["references"] == "Warm, cinematic, hopeful."
    assert brief["tone"] == "Warm, cinematic, hopeful."
    assert brief["deadline"] == "2026-07-15"
    # A stored brief wins field-by-field.
    brief2 = seed_brief(project, opp, {"brief": {"objective": "Drive trial signups"}})
    assert brief2["objective"] == "Drive trial signups"
    assert brief2["tone"] == "Warm, cinematic, hopeful."  # still seeded


# --------------------------------------------------------------------------- #
# Brief-as-contract (re-review top-5 #5) — parse + reconcile the brief.
# --------------------------------------------------------------------------- #
def test_brief_deliverables_parses_comma_and_newline_list():
    brief = {"deliverables_needed": ":60 master, :30 cutdown; :15 cutdown\nstems"}
    items = brief_deliverables(brief)
    assert items == [":60 master", ":30 cutdown", ":15 cutdown", "stems"]
    # Blanks dropped, duplicates (case-insensitively) collapsed.
    assert brief_deliverables({"deliverables_needed": "stems,, Stems"}) == ["stems"]
    assert brief_deliverables({}) == []


def test_reconcile_brief_marks_delivered_and_pending():
    brief = {"deliverables_needed": ":60 master, :06 bumper"}
    assets = [{"label": "AURORA :60 master broadcast", "kind": "audio"}]
    recon = reconcile_brief(brief, assets)
    by_item = {r["item"]: r for r in recon}
    # The :60 master is plausibly satisfied by the uploaded master.
    assert by_item[":60 master"]["status"] == "Delivered"
    assert by_item[":60 master"]["matched"] == "AURORA :60 master broadcast"
    # The :06 bumper has no plausible asset → Pending, no match.
    assert by_item[":06 bumper"]["status"] == "Pending"
    assert by_item[":06 bumper"]["matched"] == ""
    # Synonym match: "social cutdowns" ↔ a 9:16 vertical cut.
    recon2 = reconcile_brief(
        {"deliverables_needed": "social cutdowns"},
        [{"label": "9:16 vertical cut", "kind": "audio"}],
    )
    assert recon2[0]["status"] == "Delivered"
    # The rollup reads "N of M".
    roll = brief_rollup(recon)
    assert roll == {"delivered": 1, "total": 2,
                    "text": "1 of 2 brief items delivered"}


def test_build_timeline_orders_brief_version_comment_and_approval():
    project = {"id": 1, "need": "Find Your Horizon",
               "created_at": "2026-06-20T09:00:00+00:00"}
    delivery = {
        "versions": [
            {"n": 1, "label": "v1 Concept", "name": "FIND_Master_v1",
             "created_at": "2026-06-22T10:00:00+00:00"},
        ],
        "delivery_zip": {"built_at": "2026-06-26T12:00:00+00:00"},
        "released_at": "2026-06-27",
    }
    comments = [
        {"kind": "comment", "author": "Dana", "body": "Tighten the intro",
         "t_seconds": 5.0, "version": "1", "created_at": "2026-06-23T11:00:00+00:00"},
        {"kind": "approval", "author": "Dana", "body": "Approved.",
         "t_seconds": None, "version": "1", "created_at": "2026-06-25T15:00:00+00:00"},
    ]
    tl = build_timeline(project, delivery, comments)
    labels = [e["label"] for e in tl]
    # The version, comment, and approval all appear.
    assert any("Creative brief" in l for l in labels)
    assert any("Version" in l for l in labels)
    assert any("Comment from Dana" in l for l in labels)
    assert any("Approved by Dana" in l for l in labels)
    # Time-ordered (oldest first): brief < version < comment < approval < zip.
    whens = [e["when"] for e in tl]
    assert whens == sorted(whens)
    brief_i = next(i for i, e in enumerate(tl) if "Creative brief" in e["label"])
    ver_i = next(i for i, e in enumerate(tl) if e["label"].startswith("Version"))
    com_i = next(i for i, e in enumerate(tl) if "Comment from" in e["label"])
    app_i = next(i for i, e in enumerate(tl) if "Approved by" in e["label"])
    assert brief_i < ver_i < com_i < app_i
    # The comment carries its timecode in the detail.
    com = tl[com_i]
    assert "0:05" in com["detail"]


# --------------------------------------------------------------------------- #
# Delivery automation (Phase 3) — document generators (deterministic, stdlib)
# --------------------------------------------------------------------------- #
def test_cue_sheet_csv_has_header_and_rows():
    import csv as _csv
    import io as _io

    text = cue_sheet_csv(_fake_project(), _fake_assignments())
    rows = list(_csv.reader(_io.StringIO(text)))
    # IP3: fileable cue sheet — Duration / ISRC / ISWC columns present.
    assert rows[0] == ["Cue", "Usage", "Duration", "ISRC", "ISWC",
                       "Composer", "Publisher", "PRO", "Share%"]
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
    # IP3: release is refused until the license is explicitly confirmed.
    client.post(f"/project/{pid}/delivery/license/confirm",
                data={"by": "Jon Shipp"}, follow_redirects=True)
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
# Console UX fixes — anchor redirects, brief moved down, no doubled version chips
# --------------------------------------------------------------------------- #
def test_brief_mutation_redirects_to_brief_anchor(client):
    """FIX 1: a console mutation lands back on the card it acted in (not the top)."""
    pid = _win_and_make_project(client, 1)
    r = client.post(f"/project/{pid}/delivery/brief",
                    data={"objective": "Original music for the launch."},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith("#brief")


def test_console_anchor_redirects_per_card(client):
    """FIX 1: each mutation redirects to the matching card anchor."""
    pid = _win_and_make_project(client, 1)
    cases = [
        ("delivery/license",
         {"type": "Buyout", "territory": "Worldwide", "term": "Perpetuity",
          "exclusivity": "Exclusive", "content_id": "Registrable"}, "#license"),
        ("delivery/signatory",
         {"entity": "Chordential", "signer": "Jon", "title": "Founder"}, "#license"),
        ("delivery/reviewer",
         {"action": "add", "name": "Dana", "email": "d@x.com", "role": "Producer"},
         "#reviewers"),
        ("delivery/license/confirm", {"by": "Jon"}, "#license"),
        ("delivery/cue", {"cue": "Launch", "duration": "0:60"}, "#license"),
        ("delivery/build", {}, "#delivery"),
        ("delivery/release", {}, "#delivery"),
    ]
    for path, data, anchor in cases:
        r = client.post(f"/project/{pid}/{path}", data=data, follow_redirects=False)
        assert r.status_code == 303, path
        assert r.headers["location"].endswith(anchor), (path, r.headers["location"])


def test_console_brief_card_below_versions_and_timeline(client):
    """FIX 2: the Creative brief card sits AFTER the Versions/timeline section."""
    pid = _win_and_make_project(client, 1)
    html = client.get(f"/project/{pid}/delivery").text
    timeline_pos = html.find("Campaign timeline")
    brief_pos = html.find("Creative brief")
    assert timeline_pos != -1 and brief_pos != -1
    # The campaign-timeline marker appears before the creative-brief marker.
    assert timeline_pos < brief_pos


def test_console_version_rail_has_no_doubled_v_prefix(client):
    """FIX 3: version chips render as the label only (no "v1 v1" doubling)."""
    pid = _win_and_make_project(client, 1)
    # Log two versions of the master so the rail has multiple chips.
    for _ in range(2):
        client.post(f"/project/{pid}/delivery/version",
                    data={"action": "add"},
                    files={"file": ("master.mp3", b"ID3fakeaudio", "audio/mpeg")},
                    follow_redirects=True)
    html = client.get(f"/project/{pid}/delivery").text
    assert "v1 v1" not in html
    assert "v2 v2" not in html
    # The single, correct label is present, and the latest reads as current.
    assert "v1 Concept" in html
    assert "· current" in html


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


def _add_reviewer(client, pid, name="Dana", email="dana@agency.com",
                  role="Senior Producer"):
    """Verified-identity approval: invite a named reviewer via the admin route and
    return their minted personal token (used as ``?r=`` to approve)."""
    client.post(f"/project/{pid}/delivery/reviewer",
                data={"action": "add", "name": name, "email": email, "role": role},
                follow_redirects=True)
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        roster = db_mod.list_delivery_reviewers(conn, pid)
    finally:
        conn.close()
    match = next(r for r in roster if r["name"] == name)
    return match["token"]


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
                data={"k": token, "author": "Dana", "email": "dana@agency.com",
                      "t": "12.4", "body": "Can we remove percussion?"})
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    assert "Review &amp; approve" in page          # the Frame.io-for-music section
    assert "Can we remove percussion?" in page     # the comment body
    assert "0:12" in page                          # the timecode (12.4s → 0:12)
    assert 'name="k"' in page                      # forms carry the token


def test_client_approve_sets_state_via_portal(client):
    pid = _win_and_make_project(client, 1)
    rtoken = _add_reviewer(client, pid, name="Dana (Agency)")
    client.post(f"/project/{pid}/review/approve", data={"r": rtoken})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        # Phase 3: APPROVE auto-assembles the package and delivers it.
        assert db_mod.get_delivery(conn, pid).get("state") == "Delivered"
        kinds = {c["kind"] for c in db_mod.list_review_comments(conn, pid)}
    finally:
        conn.close()
    assert "approval" in kinds


def test_approve_with_share_token_only_is_refused(client):
    """(a) The generic share link (?k=) cannot approve — even with a posted
    name + email, state does not advance. Approval requires a verified ?r= link."""
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    r = client.post(f"/project/{pid}/review/approve",
                    data={"k": token, "author": "Anyone", "email": "x@x.com"},
                    follow_redirects=False)
    # Not a 404 (the share token is valid for viewing/commenting) — it just no-ops.
    assert r.status_code == 303
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
        kinds = {c["kind"] for c in db_mod.list_review_comments(conn, pid)}
    finally:
        conn.close()
    # State did NOT advance, and no approval was recorded.
    assert d.get("state") != "Delivered"
    assert "approval" not in kinds


def test_verified_reviewer_approve_records_roster_identity(client):
    """(b) A reviewer added via /delivery/reviewer can approve via their ?r= token:
    it locks FINAL, builds the ZIP, and records the ROSTER name + email — not a
    free-typed name posted on the form."""
    pid = _win_and_make_project(client, 1)
    rtoken = _add_reviewer(client, pid, name="Dana Whitfield",
                           email="dana@agency.com", role="Senior Producer")
    # A spoofed name + email is posted alongside the verified token — it's ignored.
    client.post(f"/project/{pid}/review/approve",
                data={"r": rtoken, "author": "Imposter", "email": "evil@x.com"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
        approval = next(c for c in db_mod.list_review_comments(conn, pid)
                        if c["kind"] == "approval")
    finally:
        conn.close()
    assert d.get("state") == "Delivered"          # built the ZIP (locks FINAL)
    assert d.get("delivery_zip")
    # The sign-off carries the LOCKED roster identity, not the free-typed spoof.
    assert approval["author"] == "Dana Whitfield"
    assert approval["email"] == "dana@agency.com"
    assert approval["verified"] == 1


def test_guest_can_still_comment_with_share_token(client):
    """(c) A guest on the generic ?k= link can still post a comment."""
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "author": "Guest", "email": "guest@agency.com",
                      "t": "8", "body": "Love the intro"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        rows = db_mod.list_review_comments(conn, pid)
    finally:
        conn.close()
    note = next(c for c in rows if c["kind"] == "comment")
    assert note["body"] == "Love the intro"
    assert note["verified"] == 0                  # a guest comment is not verified


def test_portal_guest_vs_verified_identity(client):
    """(d) Guest mode shows the "approval requires your personal link" note and a
    free-entry identity block; reviewer mode locks the identity (no free-entry name
    field) and enables Approve."""
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    rtoken = _add_reviewer(client, pid, name="Dana Whitfield",
                           email="dana@agency.com", role="Senior Producer")
    # Guest (share link): the approval-requires-personal-link note + free-entry.
    guest = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    assert "Approval requires your personal review link" in guest
    assert 'id="who-name"' in guest                # free-entry name field is shown
    # Verified (personal link): identity is locked, no free-entry name field.
    rev = client.get(f"/project/{pid}/delivery-portal", params={"r": rtoken}).text
    assert "Verified reviewer" in rev
    assert "Dana Whitfield" in rev
    assert 'id="who-name"' not in rev              # no free-entry name field
    assert "Approval requires your personal review link" not in rev


def test_console_renders_reviewer_roster_and_link(client):
    """(e) The console renders the reviewer roster + a copyable ?r= personal link."""
    pid = _win_and_make_project(client, 1)
    rtoken = _add_reviewer(client, pid, name="Dana Whitfield",
                           email="dana@agency.com", role="Senior Producer")
    page = client.get(f"/project/{pid}/delivery").text
    assert "Reviewers" in page
    assert "Dana Whitfield" in page
    assert f"?r={rtoken}" in page                  # the copyable personal link
    assert "Copy link" in page


def test_reviewer_link_works_without_share_token(client):
    """A reviewer's ?r= link is itself an access token — it opens the portal on its
    own (no ?k= needed) and is exempt/validated like the share token."""
    pid = _win_and_make_project(client, 1)
    rtoken = _add_reviewer(client, pid)
    ok = client.get(f"/project/{pid}/delivery-portal", params={"r": rtoken})
    assert ok.status_code == 200
    assert "Your Delivery" in ok.text
    # A bogus reviewer token with no share token → 404.
    bad = client.get(f"/project/{pid}/delivery-portal", params={"r": "nope"})
    assert bad.status_code == 404


def test_request_changes_logs_and_bumps_revisions(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/changes",
                data={"k": token, "author": "CD", "email": "cd@agency.com",
                      "note": "Strings should swell at 0:34"})
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
    rtoken = _add_reviewer(client, pid)
    _upload_version(client, pid, "v1.mp3")
    client.post(f"/project/{pid}/review/approve", data={"r": rtoken})
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
                data={"k": token, "author": "Dana", "email": "dana@agency.com",
                      "t": "5", "body": "Tighten the intro"})
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
    rtoken = _add_reviewer(client, pid)
    _upload_version(client, pid, "v1.mp3")
    client.post(f"/project/{pid}/review/approve", data={"r": rtoken})
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
    rtoken = _add_reviewer(client, pid)
    # The agency presses APPROVE on their verified personal review link — the trigger.
    client.post(f"/project/{pid}/review/approve", data={"r": rtoken})

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
    rtoken = _add_reviewer(client, pid)
    client.post(f"/project/{pid}/review/approve", data={"r": rtoken})
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
    rtoken = _add_reviewer(client, pid)
    client.post(f"/project/{pid}/review/approve", data={"r": rtoken})
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
    rtoken = _add_reviewer(client, pid)
    r = client.post(f"/project/{pid}/review/approve",
                    data={"r": rtoken}, follow_redirects=False)
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


# --------------------------------------------------------------------------- #
# Campaign Dashboard / Delivery Console (Phase 4)
# --------------------------------------------------------------------------- #
def test_delivery_console_renders_with_campaign_agents_and_brief(client):
    pid = _win_and_make_project(client, 1)
    name = _assign_a_creator(client, pid)
    # The project's campaign name (from its linked opportunity) anchors the page.
    project_need = client.get(f"/project/{pid}").text
    campaign = re.search(r'class="detail-title">([^<]+)<', project_need).group(1).strip()
    r = client.get(f"/project/{pid}/delivery")
    assert r.status_code == 200
    body = r.text
    # The campaign + the contributor + the five-agent labels.
    assert campaign in body
    assert name in body
    for label in ("Rights", "Revisions", "Metadata", "Approvals", "Assets"):
        assert label in body
    # The creative brief section is present (seeded from the opportunity's need).
    assert "Creative brief" in body
    assert campaign in body  # objective seeded from the need


def test_console_brief_edit_persists_and_shows(client):
    pid = _win_and_make_project(client, 1)
    client.post(f"/project/{pid}/delivery/brief",
                data={"objective": "Drive summer trial signups",
                      "references": "Warm, anthemic", "tone": "Hopeful",
                      "deliverables_needed": ":60, :30, stems", "deadline": "2026-07-15"},
                follow_redirects=True)
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert d["brief"]["objective"] == "Drive summer trial signups"
    assert d["brief"]["deadline"] == "2026-07-15"
    # And it renders back on the console.
    page = client.get(f"/project/{pid}/delivery").text
    assert "Drive summer trial signups" in page
    assert ":60, :30, stems" in page


def test_console_shows_client_review_link_and_version_rail(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    _upload_version(client, pid, "v1.mp3")
    _upload_version(client, pid, "v2.mp3")
    page = client.get(f"/project/{pid}/delivery").text
    # The client review link (the token portal URL) is on the toolbar.
    assert f"/project/{pid}/delivery-portal?k={token}" in page
    assert "Open client review link" in page
    # The version rail shows the v1/v2 ladder with the current version marked.
    assert "Version history" in page
    assert "current" in page
    # The campaign timeline is present.
    assert "Campaign timeline" in page


# --------------------------------------------------------------------------- #
# Improvement Pass 1 — Trust & coordination (identity, approve-guard, push,
# provenance after delivery)
# --------------------------------------------------------------------------- #
def _comments(pid):
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        return db_mod.list_review_comments(conn, pid)
    finally:
        conn.close()


def test_approve_without_identity_is_rejected(client):
    """Approve — the action that locks FINAL + builds the ZIP — now requires a
    VERIFIED reviewer link (?r=). A share-link guest no-ops even with a complete
    free-typed name + email; only the verified reviewer's token approves."""
    pid = _win_and_make_project(client, 1)
    _seed_asset(client, pid)
    token = _project_token(client, pid)
    # A bare name over the share token → no-op (still a 303 redirect).
    r = client.post(f"/project/{pid}/review/approve",
                    data={"k": token, "author": "Dana"}, follow_redirects=False)
    assert r.status_code == 303
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    assert d.get("state") != "Delivered"
    assert not any(c["kind"] == "approval" for c in _comments(pid))
    # Even a COMPLETE free-typed identity over the share token cannot approve.
    client.post(f"/project/{pid}/review/approve",
                data={"k": token, "author": "Dana", "email": "dana@agency.com"})
    assert not any(c["kind"] == "approval" for c in _comments(pid))
    # The verified reviewer's personal token DOES approve.
    rtoken = _add_reviewer(client, pid, name="Dana", email="dana@agency.com")
    client.post(f"/project/{pid}/review/approve", data={"r": rtoken})
    assert any(c["kind"] == "approval" for c in _comments(pid))


def test_comment_stores_email_and_renders_attribution(client):
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "author": "Marcus (CD)", "email": "marcus@agency.com",
                      "t": "12.4", "body": "Lift the hook"})
    rows = _comments(pid)
    note = next(c for c in rows if c["kind"] == "comment")
    # The email is persisted on the review_comments row.
    assert note["email"] == "marcus@agency.com"
    assert note["author"] == "Marcus (CD)"


def test_reviewer_cookie_prefills_identity(client):
    """First action sets the cdl_reviewer cookie; a later GET prefills the name/email."""
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    r = client.post(f"/project/{pid}/review/comment",
                    data={"k": token, "author": "Dana Whitfield",
                          "email": "dana@agency.com", "t": "3", "body": "Warmer pads"},
                    follow_redirects=False)
    # The cookie is set on the first action.
    assert "cdl_reviewer" in r.headers.get("set-cookie", "")
    # And it's remembered on the client, so a subsequent GET prefills the identity.
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    assert "Dana Whitfield" in page
    assert "dana@agency.com" in page
    # The hidden identity fields carry the remembered values.
    assert 'class="ident-email"' in page


def test_review_history_survives_after_released(client):
    """Provenance: once Delivered/Released the comment + approval tape stays visible."""
    pid = _win_and_make_project(client, 1)
    _seed_asset(client, pid)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "author": "Dana", "email": "dana@agency.com",
                      "t": "5", "body": "Bring up the strings at 0:34"})
    client.post(f"/project/{pid}/review/approve",
                data={"k": token, "author": "Dana", "email": "dana@agency.com"})
    # IP3: confirm the license before release (release is refused otherwise).
    client.post(f"/project/{pid}/delivery/license/confirm",
                data={"by": "Jon Shipp"}, follow_redirects=True)
    client.post(f"/project/{pid}/delivery/release", follow_redirects=True)
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        assert db_mod.get_delivery(conn, pid).get("state") == "Released"
    finally:
        conn.close()
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    # The read-only review history is shown with the prior comment + the approval.
    assert "Review history" in page
    assert "Bring up the strings at 0:34" in page
    assert "dana@agency.com" in page          # attribution by email survives


def test_review_action_pushes_the_operator(client, monkeypatch):
    """The operator (Jon) gets a push when the agency comments / requests changes /
    approves — the coordination signal 'one link, no email' would otherwise drop."""
    from chordential_oia.web import app as app_mod
    calls = []
    monkeypatch.setattr(app_mod.webpush, "send_web_push",
                        lambda *a, **k: calls.append((a, k)) or {"sent": 1})
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/changes",
                data={"k": token, "author": "Marcus", "email": "marcus@agency.com",
                      "note": "Punch up the drums"})
    assert calls, "operator push was not invoked on a review action"
    # The push is linked to the project's delivery console.
    assert any(f"/project/{pid}/delivery" in str(c) for c in calls)


# --------------------------------------------------------------------------- #
# Delivery OS IP2 (Frame.io review polish) — resolve, reply, version navigation
# --------------------------------------------------------------------------- #
def test_resolve_toggles_comment_flag_and_requires_identity(client):
    """Per-comment resolve flips the resolved flag (and needs a complete identity),
    and the portal reflects open/resolved state."""
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    # Seed a comment via a raw db insert (no remembered-identity cookie set on the
    # client) so the identity guard on resolve can be exercised from a clean state.
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        cid = db_mod.add_review_comment(
            conn, pid, version="0", t_seconds=5.0, author="Dana",
            email="dana@agency.com", body="Tighten the intro", kind="comment")
    finally:
        conn.close()
    # A resolve with no identity (no email, no cookie) no-ops (still flagged 0).
    client.post(f"/project/{pid}/review/resolve",
                data={"k": token, "author": "Dana", "comment_id": cid})
    conn = db_mod.connect()
    try:
        assert (db_mod.get_review_comment(conn, cid)["resolved"] or 0) == 0
    finally:
        conn.close()
    # A complete identity resolves it.
    client.post(f"/project/{pid}/review/resolve",
                data={"k": token, "author": "Dana", "email": "dana@agency.com",
                      "comment_id": cid})
    conn = db_mod.connect()
    try:
        assert db_mod.get_review_comment(conn, cid)["resolved"] == 1
    finally:
        conn.close()
    # The portal reflects it: 0 open · 1 resolved, and a Reopen control appears.
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    assert "0</b> open" in page and "1 resolved" in page
    assert "Reopen" in page
    # Toggling again reopens it.
    client.post(f"/project/{pid}/review/resolve",
                data={"k": token, "author": "Dana", "email": "dana@agency.com",
                      "comment_id": cid})
    conn = db_mod.connect()
    try:
        assert (db_mod.get_review_comment(conn, cid)["resolved"] or 0) == 0
    finally:
        conn.close()


def test_open_and_resolved_counts_render(client):
    """The 'N open · M resolved' count renders for the version under review."""
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    for body in ("Note one", "Note two"):
        client.post(f"/project/{pid}/review/comment",
                    data={"k": token, "author": "Dana", "email": "dana@agency.com",
                          "t": "5", "body": body})
    rows = [c for c in _comments(pid) if c["kind"] == "comment"]
    assert len(rows) == 2
    # Resolve one of the two.
    client.post(f"/project/{pid}/review/resolve",
                data={"k": token, "author": "Dana", "email": "dana@agency.com",
                      "comment_id": rows[0]["id"]})
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    assert "1</b> open" in page and "1 resolved" in page


def test_reply_nests_under_parent_and_renders_indented(client):
    """A reply (parent_id) threads one level under its parent and renders in the
    indented thread block. Replies carry no timecode."""
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "author": "Dana", "email": "dana@agency.com",
                      "t": "5", "body": "Drums too loud at 0:34"})
    parent = next(c for c in _comments(pid) if c["kind"] == "comment")
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "author": "Composer", "email": "comp@studio.com",
                      "body": "Fixed in this pass", "parent_id": parent["id"]})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        rows = db_mod.list_review_comments(conn, pid)
    finally:
        conn.close()
    reply = next(c for c in rows if c["body"] == "Fixed in this pass")
    # It nests under its parent and (being a reply) carries no timecode.
    assert reply["parent_id"] == parent["id"]
    assert reply["t_seconds"] is None
    # The portal renders the reply inside the indented thread block.
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    assert "rc-thread" in page
    assert "Fixed in this pass" in page


def test_selecting_a_version_loads_its_track_and_comments(client):
    """?v=<n> opens that version: its track is the player src and only its comments
    show (seed 2 versions with a comment on each)."""
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    # Two versions, with a comment landing on each as it's the current one.
    _upload_version(client, pid, "v1.mp3")
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "author": "Dana", "email": "dana@agency.com",
                      "t": "5", "body": "v1 note about the hook"})
    _upload_version(client, pid, "v2.mp3")
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "author": "Dana", "email": "dana@agency.com",
                      "t": "8", "body": "v2 note about the drums"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        d = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    versions = d["versions"]
    v1_url, v2_url = versions[0]["url"], versions[1]["url"]

    # Default (no ?v=): the current version (v2) plays, only v2's comment shows.
    cur = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    assert v2_url in cur and v1_url not in cur
    assert "v2 note about the drums" in cur
    assert "v1 note about the hook" not in cur

    # ?v=1: v1's track is the player src and only v1's comment shows.
    sel = client.get(f"/project/{pid}/delivery-portal", params={"k": token, "v": "1"}).text
    assert v1_url in sel and v2_url not in sel
    assert "v1 note about the hook" in sel
    assert "v2 note about the drums" not in sel


# --------------------------------------------------------------------------- #
# Improvement Pass 3 — Defensible rights + finished package
# --------------------------------------------------------------------------- #
def test_rights_cert_text_has_signatory_version_no_indemnif_honest_content_id():
    """IP3: the cert text shows a signatory block + the version it certifies, NO
    indemnity mention at all, and honest Content-ID language."""
    from chordential_oia.delivery import build_clearance_certificate as _bcc

    cert = _bcc(
        _fake_project(), _fake_assignments(), {"type": "Full buyout"},
        signatory={"entity": "Chordential Music", "signer": "Jon Shipp",
                   "title": "Founder"},
        certified_version="v3 FINAL", certified_date="2026-06-26",
    )
    text = rights_certificate_text(cert)
    # Signatory block: entity + authorized signer present.
    assert "SIGNATORY" in text
    assert "Chordential Music" in text
    assert "Jon Shipp" in text
    # The version it certifies + the date.
    assert "v3 FINAL" in text
    assert "2026-06-26" in text
    # NO indemnity mention anywhere (the half-promise is removed entirely).
    assert "indemnif" not in text.lower()
    # Honest Content-ID language — not a bare "Content-ID-safe" claim.
    assert "no third-party content-id claims" in text.lower()
    assert "registrable with content id" in text.lower()


def test_rights_cert_license_reads_as_draft_until_confirmed():
    """IP3: unconfirmed → the grant reads DRAFT; confirmed → it asserts the grant."""
    from chordential_oia.delivery import build_clearance_certificate as _bcc

    draft = _bcc(_fake_project(), _fake_assignments())
    assert draft.license_draft is True
    assert "DRAFT — pending confirmation" in rights_certificate_text(draft)

    confirmed = _bcc(
        _fake_project(), _fake_assignments(),
        license_confirmed={"by": "Jon Shipp", "date": "2026-06-26"},
    )
    assert confirmed.license_draft is False
    txt = rights_certificate_text(confirmed)
    assert "DRAFT — pending confirmation" not in txt
    assert "Confirmed:" in txt and "Jon Shipp" in txt


def test_release_refused_until_license_confirmed_then_succeeds(client):
    """IP3: /delivery/release is REFUSED until the license is explicitly confirmed,
    then succeeds after the operator confirms."""
    from chordential_oia.web import db as db_mod

    pid = _win_and_make_project(client, 1)
    # Release with no confirmation → refused (state not Released; flagged on bounce).
    r = client.post(f"/project/{pid}/delivery/release", follow_redirects=False)
    assert r.status_code == 303
    assert "release=needs_license" in r.headers["location"]
    conn = db_mod.connect()
    try:
        assert db_mod.get_delivery(conn, pid).get("state") != "Released"
    finally:
        conn.close()
    # Confirm the license terms (records who + when).
    client.post(f"/project/{pid}/delivery/license/confirm",
                data={"by": "Jon Shipp"}, follow_redirects=True)
    conn = db_mod.connect()
    try:
        conf = db_mod.get_delivery(conn, pid).get("license_confirmed")
    finally:
        conn.close()
    assert conf and conf["by"] == "Jon Shipp" and conf["date"]
    # Now release succeeds.
    client.post(f"/project/{pid}/delivery/release", follow_redirects=True)
    conn = db_mod.connect()
    try:
        assert db_mod.get_delivery(conn, pid).get("state") == "Released"
    finally:
        conn.close()


def test_editing_license_invalidates_a_prior_confirmation(client):
    """IP3: re-editing the license terms drops the confirmation so the operator must
    re-confirm the new terms before they're asserted (release refused again)."""
    from chordential_oia.web import db as db_mod

    pid = _win_and_make_project(client, 1)
    client.post(f"/project/{pid}/delivery/license/confirm",
                data={"by": "Jon Shipp"}, follow_redirects=True)
    # Editing the license clears the confirmation.
    client.post(f"/project/{pid}/delivery/license",
                data={"type": "Limited 12-month", "territory": "US"},
                follow_redirects=True)
    conn = db_mod.connect()
    try:
        assert db_mod.get_delivery(conn, pid).get("license_confirmed") is None
    finally:
        conn.close()
    # So release is refused again until re-confirmed.
    r = client.post(f"/project/{pid}/delivery/release", follow_redirects=False)
    assert "release=needs_license" in r.headers["location"]


def test_uploaded_local_audio_is_in_the_zip(client):
    """IP3: an uploaded LOCAL audio asset is actually inside the built ZIP."""
    import os
    import zipfile as _zip
    from chordential_oia.web import db as db_mod, app as app_mod

    pid = _win_and_make_project(client, 1)
    files = {"file": ("anthem_master.wav", b"RIFF....WAVEfakeaudio", "audio/wav")}
    client.post(f"/project/{pid}/delivery/asset",
                data={"label": "Anthem :60 master", "action": "add"},
                files=files, follow_redirects=True)
    # The stored on-disk filename for the asset.
    conn = db_mod.connect()
    try:
        asset = db_mod.get_delivery(conn, pid)["assets"][0]
    finally:
        conn.close()
    stored = asset["filename"]
    assert stored  # a real local file, not URL-only
    # Build the package and open the ZIP — the local file is a member.
    client.post(f"/project/{pid}/delivery/build", follow_redirects=True)
    conn = db_mod.connect()
    try:
        url = db_mod.get_delivery(conn, pid)["delivery_zip"]["url"]
    finally:
        conn.close()
    zip_path = os.path.join(app_mod.UPLOAD_DIR, os.path.basename(url))
    with _zip.ZipFile(zip_path) as zf:
        names = zf.namelist()
        # The actual uploaded audio file is bundled under a folder.
        assert any(n.endswith(stored) for n in names), names


def test_referenced_only_asset_listed_in_zip_readme(client):
    """IP3: a remote-URL-only asset (blank filename) is listed in Docs/README.txt as
    'referenced, not bundled' rather than silently dropped — and doesn't crash."""
    import os
    import zipfile as _zip
    from chordential_oia.web import db as db_mod, app as app_mod

    pid = _win_and_make_project(client, 1)
    # Inject a URL-only asset (mirrors the demo seed) with a blank filename.
    conn = db_mod.connect()
    try:
        db_mod.update_delivery(conn, pid, "assets", [
            {"label": "Anthem :60 (demo)", "url": "https://example.com/a.mp3",
             "filename": "", "kind": "audio"},
        ])
    finally:
        conn.close()
    # Build does not crash on the blank filename.
    client.post(f"/project/{pid}/delivery/build", follow_redirects=True)
    conn = db_mod.connect()
    try:
        url = db_mod.get_delivery(conn, pid)["delivery_zip"]["url"]
    finally:
        conn.close()
    zip_path = os.path.join(app_mod.UPLOAD_DIR, os.path.basename(url))
    with _zip.ZipFile(zip_path) as zf:
        readme = zf.read("Docs/README.txt").decode("utf-8")
    assert "REFERENCED, NOT BUNDLED" in readme
    assert "Anthem :60 (demo)" in readme
    assert "https://example.com/a.mp3" in readme


def test_operator_assigned_folder_places_asset_in_that_folder(client):
    """IP3: an operator-assigned folder files the asset in that folder in the ZIP,
    overriding the keyword heuristic."""
    import os
    import zipfile as _zip
    from chordential_oia.web import db as db_mod, app as app_mod

    pid = _win_and_make_project(client, 1)
    # Label says nothing folder-ish, but the operator assigns it to Stems.
    files = {"file": ("track01.wav", b"RIFFfakeaudio", "audio/wav")}
    client.post(f"/project/{pid}/delivery/asset",
                data={"label": "Track One", "action": "add"},
                files=files, follow_redirects=True)
    conn = db_mod.connect()
    try:
        stored = db_mod.get_delivery(conn, pid)["assets"][0]["filename"]
    finally:
        conn.close()
    # Assign the folder explicitly.
    client.post(f"/project/{pid}/delivery/asset/folder",
                data={"filename": stored, "folder": "Stems"}, follow_redirects=True)
    conn = db_mod.connect()
    try:
        assert db_mod.get_delivery(conn, pid)["assets"][0]["folder"] == "Stems"
    finally:
        conn.close()
    client.post(f"/project/{pid}/delivery/build", follow_redirects=True)
    conn = db_mod.connect()
    try:
        url = db_mod.get_delivery(conn, pid)["delivery_zip"]["url"]
    finally:
        conn.close()
    zip_path = os.path.join(app_mod.UPLOAD_DIR, os.path.basename(url))
    with _zip.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert f"Stems/{stored}" in names, names


def test_cue_sheet_csv_has_isrc_iswc_duration_columns_fillable(client):
    """IP3: cue_sheet_csv has ISRC/ISWC/Duration columns, and per-cue meta set on the
    console fills them."""
    import csv as _csv
    import io as _io
    from chordential_oia.web import db as db_mod
    from chordential_oia.delivery import build_cue_sheet as _bcs

    pid = _win_and_make_project(client, 1)
    # Resolve the project's primary cue name to set its meta.
    conn = db_mod.connect()
    try:
        proj = db_mod.get_project(conn, pid)
        assigns = db_mod.list_assignments(conn, pid)
    finally:
        conn.close()
    primary_cue = _bcs(proj, assigns)[0].cue
    client.post(f"/project/{pid}/delivery/cue",
                data={"cue": primary_cue, "duration": "0:60",
                      "isrc": "US-ABC-26-00001", "iswc": "T-123.456.789-0"},
                follow_redirects=True)
    conn = db_mod.connect()
    try:
        delivery = db_mod.get_delivery(conn, pid)
    finally:
        conn.close()
    text = cue_sheet_csv(proj, assigns, delivery=delivery)
    rows = list(_csv.reader(_io.StringIO(text)))
    assert rows[0] == ["Cue", "Usage", "Duration", "ISRC", "ISWC",
                       "Composer", "Publisher", "PRO", "Share%"]
    body = "\n".join(",".join(r) for r in rows[1:])
    assert "0:60" in body
    assert "US-ABC-26-00001" in body
    assert "T-123.456.789-0" in body


def test_console_shows_signatory_and_license_confirm_control(client):
    """IP3: the console renders the signatory block + a confirm-license control, and
    the rights agent shows the license as draft until confirmed."""
    pid = _win_and_make_project(client, 1)
    page = client.get(f"/project/{pid}/delivery").text
    assert "Confirm license terms" in page
    assert "Certificate signatory" in page
    assert "DRAFT — pending confirmation" in page


# --------------------------------------------------------------------------- #
# Per-asset approval — granular sign-off (the :60 master Approved while the :30
# cutdown still awaits), not just the whole-version Approve.
# --------------------------------------------------------------------------- #
def _asset_keys(pid):
    """The stable per-asset approval keys for a project's deliverable assets,
    in upload order (each is the asset's stored filename)."""
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        assets = db_mod.get_delivery(conn, pid).get("assets") or []
        return [db_mod.asset_key(a) for a in assets]
    finally:
        conn.close()


def test_verified_reviewer_approves_one_asset(client):
    """(a) A verified reviewer approves a single deliverable → that asset's
    asset_approvals[key].status == "Approved" with the ROSTER identity, while a
    second asset stays Pending (granular, not whole-version)."""
    pid = _win_and_make_project(client, 1)
    _seed_asset(client, pid, name="master60.mp3", label=":60 master")
    _seed_asset(client, pid, name="cut30.mp3", label=":30 cutdown")
    rtoken = _add_reviewer(client, pid, name="Dana Whitfield",
                           email="dana@agency.com", role="Senior Producer")
    key60, key30 = _asset_keys(pid)
    # Approve ONLY the :60 master (a spoofed name is ignored — roster identity wins).
    r = client.post(f"/project/{pid}/review/asset",
                    data={"r": rtoken, "filename": key60, "action": "approve",
                          "author": "Imposter", "email": "evil@x.com"},
                    follow_redirects=False)
    assert r.status_code == 303
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        store = db_mod.get_delivery(conn, pid).get("asset_approvals") or {}
    finally:
        conn.close()
    assert store[key60]["status"] == "Approved"
    assert store[key60]["by"] == "Dana Whitfield"     # roster identity, not spoof
    assert store[key60]["email"] == "dana@agency.com"
    assert store[key60]["date"]                        # today stamped
    # The :30 cutdown was NOT touched — still Pending.
    assert key30 not in store


def test_verified_reviewer_requests_changes_on_an_asset(client):
    """(b) Requesting changes on a different asset records "Changes requested"."""
    pid = _win_and_make_project(client, 1)
    _seed_asset(client, pid, name="master60.mp3", label=":60 master")
    _seed_asset(client, pid, name="cut30.mp3", label=":30 cutdown")
    rtoken = _add_reviewer(client, pid, name="Dana Whitfield",
                           email="dana@agency.com")
    key60, key30 = _asset_keys(pid)
    client.post(f"/project/{pid}/review/asset",
                data={"r": rtoken, "filename": key60, "action": "approve"})
    client.post(f"/project/{pid}/review/asset",
                data={"r": rtoken, "filename": key30, "action": "changes",
                      "note": "Trim the tail by half a second"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        store = db_mod.get_delivery(conn, pid).get("asset_approvals") or {}
    finally:
        conn.close()
    assert store[key60]["status"] == "Approved"
    assert store[key30]["status"] == "Changes requested"


def test_guest_cannot_change_per_asset_status(client):
    """(c) A guest on the generic ?k= link (no ?r=) cannot change a per-asset status
    — the route no-ops, no record is written."""
    pid = _win_and_make_project(client, 1)
    _seed_asset(client, pid, name="master60.mp3", label=":60 master")
    token = _project_token(client, pid)
    (key60,) = tuple(_asset_keys(pid))
    r = client.post(f"/project/{pid}/review/asset",
                    data={"k": token, "filename": key60, "action": "approve",
                          "author": "Guest", "email": "guest@agency.com"},
                    follow_redirects=False)
    # Valid share token → not a 404, but a no-op (303 back to the portal).
    assert r.status_code == 303
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        store = db_mod.get_delivery(conn, pid).get("asset_approvals") or {}
        kinds = {c["kind"] for c in db_mod.list_review_comments(conn, pid)}
    finally:
        conn.close()
    assert store == {}                                  # nothing recorded
    assert "asset_approval" not in kinds                # nothing on the review tape


def test_per_asset_rollup_renders_n_of_m(client):
    """(d) The per-asset rollup ("N of M approved") renders on the verified portal."""
    pid = _win_and_make_project(client, 1)
    _seed_asset(client, pid, name="master60.mp3", label=":60 master")
    _seed_asset(client, pid, name="cut30.mp3", label=":30 cutdown")
    rtoken = _add_reviewer(client, pid, name="Dana Whitfield",
                           email="dana@agency.com")
    key60, _ = _asset_keys(pid)
    client.post(f"/project/{pid}/review/asset",
                data={"r": rtoken, "filename": key60, "action": "approve"})
    page = client.get(f"/project/{pid}/delivery-portal", params={"r": rtoken}).text
    assert "Deliverable sign-off" in page
    assert "1 of 2" in page                             # 1 of 2 deliverables approved


def test_per_asset_event_lands_on_tape_and_pushes_operator(client, monkeypatch):
    """(e) The per-asset event lands in the review tape (kind asset_approval) AND the
    operator push fires (reuse of _notify_operator_review)."""
    import chordential_oia.web.app as app_mod
    pushed = []
    monkeypatch.setattr(app_mod, "_notify_operator_review",
                        lambda *a, **k: pushed.append((a, k)))
    pid = _win_and_make_project(client, 1)
    _seed_asset(client, pid, name="master60.mp3", label=":60 master")
    rtoken = _add_reviewer(client, pid, name="Dana Whitfield",
                           email="dana@agency.com")
    (key60,) = tuple(_asset_keys(pid))
    client.post(f"/project/{pid}/review/asset",
                data={"r": rtoken, "filename": key60, "action": "approve"})
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        rows = db_mod.list_review_comments(conn, pid)
    finally:
        conn.close()
    ev = next(c for c in rows if c["kind"] == "asset_approval")
    assert ev["author"] == "Dana Whitfield"
    assert ev["verified"] == 1
    assert ":60 master" in ev["body"]                   # body names the asset
    assert pushed                                       # the operator push fired


# --------------------------------------------------------------------------- #
# Brief-as-contract — the brief on the portal + scope reconciliation (HTTP).
# --------------------------------------------------------------------------- #
def test_portal_renders_brief_card_and_scope_checklist(client):
    """(c)+(d) The client portal shows "The brief" card + a scope checklist with a
    Delivered and a Pending item, plus the "N of M" rollup. Seed a brief with two
    deliverables + one matching asset."""
    pid = _win_and_make_project(client, 1)
    token = _project_token(client, pid)
    # A brief scoping two deliverables.
    client.post(f"/project/{pid}/delivery/brief",
                data={"objective": "Energetic :60 anthem for the launch.",
                      "deliverables_needed": ":60 master, :06 bumper"},
                follow_redirects=True)
    # One uploaded asset that plausibly satisfies the :60 master, not the bumper.
    _seed_asset(client, pid, name="master60.mp3", label=":60 master broadcast")
    page = client.get(f"/project/{pid}/delivery-portal", params={"k": token}).text
    # The brief card + its agreed-scope copy.
    assert "The brief" in page
    assert "Energetic :60 anthem for the launch." in page
    # The scope checklist: one Delivered, one Pending.
    assert "✓ Delivered" in page
    assert "⧗ Pending" in page
    assert ":06 bumper" in page
    # The rollup ("N of M brief items delivered").
    assert "1 of 2" in page
    assert "brief item" in page


def test_console_renders_scope_reconciliation(client):
    """(e) The operator console shows the brief-vs-delivered scope reconciliation."""
    pid = _win_and_make_project(client, 1)
    client.post(f"/project/{pid}/delivery/brief",
                data={"objective": "Anthem", "deliverables_needed": ":60 master, stems"},
                follow_redirects=True)
    _seed_asset(client, pid, name="master60.mp3", label=":60 master")
    page = client.get(f"/project/{pid}/delivery").text
    assert "Against the brief" in page
    assert "✓ Delivered" in page
    assert "⧗ Pending" in page          # stems not delivered
    assert "1 of 2" in page
