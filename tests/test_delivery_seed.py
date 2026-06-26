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
