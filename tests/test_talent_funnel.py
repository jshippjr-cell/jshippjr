"""Talent funnel (Cycle 2.2) — provenance, ingest, applicant intake, blend.

Sourced prospects and public applicants flow into the SAME roster and review
gate as manual talent, carry provenance, and rank together once approved.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def test_ingest_adds_sourced_prospects_pending(ctx):
    _, db_mod = ctx
    conn = db_mod.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM talent WHERE source = 'sample'"
        ).fetchall()
    finally:
        conn.close()
    assert rows, "sample source candidates should have been ingested on boot"
    for r in rows:
        assert r["review_status"] == "Pending"   # enters the review gate
        assert r["invite_status"] == "Prospect"
        assert r["source"] == "sample"


def test_ingest_is_idempotent(ctx):
    _, db_mod = ctx
    from chordential_oia.web import seed
    conn = db_mod.connect()
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM talent WHERE source='sample'"
        ).fetchone()[0]
        added = seed.ingest_talent_prospects(conn)
        after = conn.execute(
            "SELECT COUNT(*) FROM talent WHERE source='sample'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert added == 0          # all sample candidates already present
    assert after == before


def test_manual_talent_gets_manual_provenance(ctx):
    client, db_mod = ctx
    client.post("/talent", data={"name": "Manual Mae", "disciplines": ["composition"]})
    conn = db_mod.connect()
    try:
        row = conn.execute(
            "SELECT source FROM talent WHERE name='Manual Mae'"
        ).fetchone()
    finally:
        conn.close()
    assert row["source"] == "manual"


def test_apply_form_renders(ctx):
    client, _ = ctx
    r = client.get("/site/apply")
    assert r.status_code == 200
    assert "Create with Chordential" in r.text


def test_apply_creates_pending_applicant(ctx):
    client, db_mod = ctx
    r = client.post(
        "/site/apply",
        data={"name": "Casey Reed", "email": "casey@x.com",
              "disciplines": ["composition", "sound_design"],
              "credits": "Two short films.", "demo_reel_url": "https://x.com/reel"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/site/thanks?kind=apply"
    conn = db_mod.connect()
    try:
        row = conn.execute(
            "SELECT * FROM talent WHERE name='Casey Reed'"
        ).fetchone()
    finally:
        conn.close()
    assert row["source"] == "applicant"
    assert row["review_status"] == "Pending"     # not matchable until reviewed
    t = db_mod.talent_from_row(row)
    assert not t.matchable


def test_applicant_becomes_matchable_after_approval(ctx):
    client, db_mod = ctx
    client.post(
        "/site/apply",
        data={"name": "Dev Shah", "disciplines": ["composition"],
              "credits": "Scored a spot."},
    )
    conn = db_mod.connect()
    tid = conn.execute("SELECT id FROM talent WHERE name='Dev Shah'").fetchone()[0]
    conn.close()
    # Jon approves the reel; now the applicant is matchable alongside everyone else.
    client.post(f"/talent/{tid}/review", data={"review_status": "Approved"})
    conn = db_mod.connect()
    try:
        t = db_mod.talent_from_row(db_mod.get_talent(conn, tid))
    finally:
        conn.close()
    assert t.matchable
    assert t.source_label == "Applied"


def test_roster_shows_source_badges(ctx):
    client, _ = ctx
    page = client.get("/talent").text
    # Sourced prospects ingested on boot show a provenance badge.
    assert "src-badge" in page
    assert "Sourced" in page
