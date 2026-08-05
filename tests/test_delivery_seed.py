"""Delivery OS (Phase 5) — seeded fictional campaigns.

Three invented-but-realistic campaigns at different lifecycle stages so the whole
delivery experience is walkable end to end: just-briefed, in-review (the review
portal — versions + timestamped comments + a change request), and approved &
delivered (FINAL locked, the delivery ZIP built). HONESTY: invented brands only.

The ``client`` fixture triggers the app lifespan, which runs the demo seed when
``CHORDENTIAL_SEED_DEMO`` is on (conftest sets it) — so the campaigns are present
after the fixture, exactly as in the running demo.
"""

import importlib
import json
import zipfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

DEMO_CLIENTS = ("Lumen Health", "Vance Athletic", "Northwind Coffee")


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


def _demo_projects(conn):
    return conn.execute(
        "SELECT * FROM projects WHERE client IN (?,?,?) ORDER BY id",
        DEMO_CLIENTS,
    ).fetchall()


def _by_client(conn, name):
    return conn.execute(
        "SELECT * FROM projects WHERE client = ? LIMIT 1", (name,)
    ).fetchone()


# --------------------------------------------------------------------------- #
# Engine-level seeding (no web layer)
# --------------------------------------------------------------------------- #
def test_seed_delivery_demo_creates_three_campaigns(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    from chordential_oia.web import db as db_mod
    from chordential_oia.web import seed as seed_mod
    conn = db_mod.connect(str(tmp_path / "seed.db"))
    db_mod.init_db(conn)

    assert seed_mod.seed_delivery_demo(conn) is True
    rows = _demo_projects(conn)
    assert len(rows) == 3
    assert {r["client"] for r in rows} == set(DEMO_CLIENTS)


def test_seed_delivery_demo_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    from chordential_oia.web import db as db_mod
    from chordential_oia.web import seed as seed_mod
    conn = db_mod.connect(str(tmp_path / "seed.db"))
    db_mod.init_db(conn)

    assert seed_mod.seed_delivery_demo(conn) is True
    # Second run is a no-op — no duplicate campaigns.
    assert seed_mod.seed_delivery_demo(conn) is False
    assert len(_demo_projects(conn)) == 3


def test_in_review_campaign_has_comments_change_request_and_versions(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    from chordential_oia.web import db as db_mod
    from chordential_oia.web import seed as seed_mod
    conn = db_mod.connect(str(tmp_path / "seed.db"))
    db_mod.init_db(conn)
    seed_mod.seed_delivery_demo(conn)

    vance = _by_client(conn, "Vance Athletic")
    delivery = json.loads(vance["delivery_json"])
    assert delivery["state"] == "In review"
    assert len(delivery.get("versions", [])) >= 2

    comments = db_mod.list_review_comments(conn, vance["id"])
    # At least two timestamped comments (a real timecode) + one change request.
    timestamped = [c for c in comments if c["kind"] == "comment" and c["t_seconds"] is not None]
    change_requests = [c for c in comments if c["kind"] == "change_request"]
    assert len(timestamped) >= 2
    assert len(change_requests) >= 1
    # Named agency people, not "Anonymous".
    assert any("Producer" in (c["author"] or "") for c in comments)


def test_delivered_campaign_is_released_with_zip_and_checklist(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    from chordential_oia.web import db as db_mod
    from chordential_oia.web import seed as seed_mod
    conn = db_mod.connect(str(tmp_path / "seed.db"))
    db_mod.init_db(conn)
    seed_mod.seed_delivery_demo(conn)

    northwind = _by_client(conn, "Northwind Coffee")
    delivery = json.loads(northwind["delivery_json"])
    assert delivery["state"] == "Released"
    assert delivery.get("released_at")
    zip_desc = delivery.get("delivery_zip")
    assert zip_desc and zip_desc.get("filename", "").endswith("_Delivery.zip")
    assert delivery.get("delivery_checklist")
    # The generated docs are in the checklist (real, deterministic).
    checklist = delivery["delivery_checklist"]
    assert "Rights Certificate" in checklist
    assert "Cue Sheet" in checklist


def test_delivered_zip_bundles_real_audio(tmp_path, monkeypatch):
    """Showcase honesty: Northwind's "Download everything" ZIP contains a REAL
    audio member (a bundled local master), not just the Docs/ folder."""
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(upload_dir))
    upload_dir.mkdir()
    from chordential_oia.web import db as db_mod
    from chordential_oia.web import seed as seed_mod
    conn = db_mod.connect(str(tmp_path / "seed.db"))
    db_mod.init_db(conn)
    seed_mod.seed_delivery_demo(conn)

    northwind = _by_client(conn, "Northwind Coffee")
    delivery = json.loads(northwind["delivery_json"])
    zip_name = delivery["delivery_zip"]["filename"]
    zip_path = upload_dir / zip_name
    assert zip_path.is_file()
    with zipfile.ZipFile(str(zip_path)) as zf:
        names = zf.namelist()
    audio = [n for n in names if n.lower().endswith((".mp3", ".wav"))]
    # A real audio file is bundled (not just the generated Docs/).
    assert audio, f"ZIP has no audio member — only {names}"
    assert any(n.startswith("Masters/") for n in audio)


def test_delivered_certificate_uses_honest_content_id(tmp_path, monkeypatch):
    """Showcase honesty: the delivered clearance certificate drops the bare
    "Content-ID-safe" claim and uses the engine's honest IP3 language."""
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(upload_dir))
    upload_dir.mkdir()
    from chordential_oia.web import db as db_mod
    from chordential_oia.web import seed as seed_mod
    conn = db_mod.connect(str(tmp_path / "seed.db"))
    db_mod.init_db(conn)
    seed_mod.seed_delivery_demo(conn)

    northwind = _by_client(conn, "Northwind Coffee")
    delivery = json.loads(northwind["delivery_json"])
    zip_path = upload_dir / delivery["delivery_zip"]["filename"]
    with zipfile.ZipFile(str(zip_path)) as zf:
        cert_text = zf.read("Docs/For-filing/rights_certificate.txt").decode("utf-8")
    assert "Content-ID-safe" not in cert_text
    assert "registrable with Content ID" in cert_text


def test_in_review_default_view_shows_comment_and_change_request(client):
    """Showcase honesty: the in-review portal's DEFAULT view (no ``v=``) shows a
    seeded timestamped comment body + the standing change request — not "no notes
    yet" — because the discussion is tagged to the current under-review version."""
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    vance = _by_client(conn, "Vance Athletic")
    token = db_mod.connect().execute(
        "SELECT share_token FROM projects WHERE id = ?", (vance["id"],)
    ).fetchone()["share_token"]
    portal = client.get(f"/project/{vance['id']}/delivery-portal?k={token}")
    assert portal.status_code == 200
    body = portal.text
    # A current-version timestamped comment body is visible by default.
    assert "the drums get a touch busy under the VO bed" in body
    # The standing change request is visible by default (not just post-delivery).
    assert "lengthen the hook" in body
    assert "changes requested" in body
    # A prior-version note stays on v1 (history navigation), not the default view.
    assert "Love the energy out of the gate" not in body
    earlier = client.get(f"/project/{vance['id']}/delivery-portal?k={token}&v=1")
    assert "Love the energy out of the gate" in earlier.text


def test_the_portal_player_says_so_when_a_file_will_not_load(client):
    """Silence was the whole response to a broken file.

    A client pressing play on a version whose object is missing or truncated got
    nothing: no message, no error state, and the button did not even change — so they
    could not tell a broken file from their own speakers being muted. Diagnosed the hard
    way, over several rounds, because the product itself reported nothing.

    This asserts the wiring is shipped, which is as far as a server-side test can see;
    the behaviour was verified in a real browser against both a missing object (media
    error 4, the failed state and the message appear) and a healthy one (still plays).
    """
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    vance = _by_client(conn, "Vance Athletic")
    token = conn.execute("SELECT share_token FROM projects WHERE id = ?",
                         (vance["id"],)).fetchone()["share_token"]
    body = client.get(f"/project/{vance['id']}/delivery-portal?k={token}").text
    assert "addEventListener('error'" in body, "the player ignores load failures"
    assert "cap-audio-err" in body
    assert "Nothing is wrong with your speakers" in body
    # The failed state must survive the `pause` event that follows `error`, or the ▶
    # comes straight back and the only signal the listener gets is undone.
    assert "if (!failed) btn.textContent = '▶';" in body


def test_just_briefed_campaign_has_brief_no_comments(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    from chordential_oia.web import db as db_mod
    from chordential_oia.web import seed as seed_mod
    conn = db_mod.connect(str(tmp_path / "seed.db"))
    db_mod.init_db(conn)
    seed_mod.seed_delivery_demo(conn)

    lumen = _by_client(conn, "Lumen Health")
    delivery = json.loads(lumen["delivery_json"])
    assert delivery["version_state"] == "v1 Concept"
    assert delivery.get("brief", {}).get("objective")
    assert not delivery.get("versions")
    assert db_mod.list_review_comments(conn, lumen["id"]) == []


def test_no_real_trademarks_in_seeded_clients(tmp_path, monkeypatch):
    """Honesty sweep: invented brands only — never real trademarks."""
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    from chordential_oia.web import db as db_mod
    from chordential_oia.web import seed as seed_mod
    conn = db_mod.connect(str(tmp_path / "seed.db"))
    db_mod.init_db(conn)
    seed_mod.seed_delivery_demo(conn)

    blob = " ".join(r["client"] for r in _demo_projects(conn)).lower()
    for trademark in ("nike", "apple", "starbucks", "adidas", "google", "amazon"):
        assert trademark not in blob


# --------------------------------------------------------------------------- #
# Walkable end-to-end (via the lifespan-seeded app)
# --------------------------------------------------------------------------- #
def test_seeded_campaigns_appear_on_projects_page(client):
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    rows = _demo_projects(conn)
    assert len(rows) == 3
    body = client.get("/projects").text
    for r in rows:
        assert r["client"] in body


def test_each_seeded_delivery_console_renders_200(client):
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    for r in _demo_projects(conn):
        resp = client.get(f"/project/{r['id']}/delivery")
        assert resp.status_code == 200, r["client"]


def test_in_review_portal_shows_comments_and_versions(client):
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    vance = _by_client(conn, "Vance Athletic")
    # The console mints/holds the share token; the portal is token-gated.
    console = client.get(f"/project/{vance['id']}/delivery").text
    assert "Marcus Lindell" in console            # a named commenter
    token = db_mod.connect().execute(
        "SELECT share_token FROM projects WHERE id = ?", (vance["id"],)
    ).fetchone()["share_token"]
    portal = client.get(f"/project/{vance['id']}/delivery-portal?k={token}")
    assert portal.status_code == 200


def test_delivered_campaign_package_renders(client):
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    northwind = _by_client(conn, "Northwind Coffee")
    resp = client.get(f"/project/{northwind['id']}/delivery-package")
    assert resp.status_code == 200
    assert "Clearance Certificate" in resp.text
