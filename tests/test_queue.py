"""The Disposition Queue (/queue) — every pending founder decision, one ranked
surface. Pure aggregation over existing decision routes; deterministic urgency
ladder (client-waiting > money-in > money-out > follow-ups > deal moves >
submissions > REVIEW-tier > reels > floor gaps > CI housekeeping)."""

import importlib
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c


def _db():
    from chordential_oia.web import db
    return db


def test_queue_renders(client):
    r = client.get("/queue")
    assert r.status_code == 200
    assert "Disposition Queue" in r.text
    assert "Every decision waiting on you" in r.text


def test_queue_is_in_nav(client):
    assert 'href="/queue"' in client.get("/dashboard").text


def test_followups_and_review_tier_surface(client):
    db = _db()
    conn = db.connect()
    try:
        # A follow-up due yesterday on an open opportunity.
        conn.execute(
            "UPDATE opportunities SET next_action = 'Send the deck', "
            "next_action_due = '2020-01-01' WHERE id = 1")
        # A REVIEW-tier opportunity (the volume the alert tier hides).
        conn.execute(
            "UPDATE opportunities SET needs_review = 1 WHERE id = 2")
        conn.commit()
    finally:
        conn.close()
    page = client.get("/queue").text
    assert "Follow-ups due" in page
    assert "Send the deck" in page
    assert "Worth a look" in page


def test_reel_and_floor_gap_surface(client):
    db = _db()
    from chordential_oia.talent import InviteStatus, ReviewStatus, Talent
    conn = db.connect()
    try:
        # Pending reel → rung 7.
        db.insert_talent(conn, Talent(
            name="Pending Reel Person", credits="c",
            review_status=ReviewStatus.PENDING, invite_status=InviteStatus.PROSPECT))
        # Approved but unsigned → the ADR-0024 floor gap, rung 8.
        db.insert_talent(conn, Talent(
            name="Unsigned Approved Person", credits="c",
            review_status=ReviewStatus.APPROVED, invite_status=InviteStatus.JOINED))
        conn.commit()
    finally:
        conn.close()
    page = client.get("/queue").text
    assert "Reel review — Pending Reel Person" in page
    assert "Not assignable — Unsigned Approved Person" in page
    assert "executed agreement" in page


def test_urgency_order_is_deterministic(client):
    """A follow-up (rung 3) must render before a REVIEW-tier card (rung 6),
    regardless of insertion order."""
    db = _db()
    conn = db.connect()
    try:
        conn.execute("UPDATE opportunities SET needs_review = 1 WHERE id = 1")
        conn.execute(
            "UPDATE opportunities SET next_action = 'Call them back', "
            "next_action_due = '2020-01-01' WHERE id = 2")
        conn.commit()
    finally:
        conn.close()
    page = client.get("/queue").text
    assert page.index("Follow-ups due") < page.index("Worth a look")


def test_queue_counts_pending_total(client):
    page = client.get("/queue").text
    m = re.search(r'data-total="(\d+)"', page)
    assert m, "queue total missing"
    # The demo seed stages real pending work — the total must reflect it, and
    # every group's card count must sum to the total.
    total = int(m.group(1))
    card_counts = [int(x) for x in re.findall(r"<h2>[^<]*<span class=\"muted\">— (\d+)</span>", page)]
    assert sum(card_counts) == total


def test_queue_admin_gated(tmp_path, monkeypatch):
    """With the admin token set, /queue is behind the gate like every internal
    surface (token-gated public portals stay exempt — this is not one)."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "gated.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "sesame")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    try:
        with TestClient(app_mod.app) as c:
            r = c.get("/queue", follow_redirects=False)
            assert r.status_code in (302, 303, 307, 401, 403)
    finally:
        monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN")
        importlib.reload(db_mod)
        importlib.reload(app_mod)
