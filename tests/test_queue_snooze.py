"""The Disposition Queue is clearable — without becoming a liar.

A card is COMPUTED, not stored, so a snooze cannot be a flag on a row. It is keyed by
the card's identity and it EXPIRES: the decision comes back if it still needs making.
That is the whole point. A permanent dismiss would let the operator hide a client who
is waiting and get a "queue clear" that is false, and this surface's only job is to be
the one place that tells the truth about what is outstanding.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "q.sqlite"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    import importlib

    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:      # the lifespan is what builds the schema
        yield c


def _seed_a_waiting_card(conn, db):
    """One discovery request — rung 0, 'a client is waiting'."""
    from chordential_oia.models import Opportunity
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Campaign anthem", description=""))
    db.create_discovery_request(
        conn, opp_id=opp_id, name="Dana Reyes", email="dana@aurora.example",
        company="AURORA", preferred_type="zoom", message="")
    return opp_id


def test_a_snoozed_card_leaves_the_queue_and_is_counted(client):
    from chordential_oia.web import db, queue as queue_mod
    conn = db.connect()
    try:
        _seed_a_waiting_card(conn, db)
        before = queue_mod.compute_queue(conn, db)
        assert before, "the seed should put at least one card on the queue"
        card = before[0]

        db.snooze_queue_card(conn, card["key"], 7)
        after = queue_mod.compute_queue(conn, db)
        assert card["key"] not in {c["key"] for c in after}

        view = queue_mod.queue_view(conn, db)
        assert view["snoozed"] >= 1, "the surface must say how many it is withholding"

        # ...and asking for them brings it straight back, unchanged.
        both = queue_mod.compute_queue(conn, db, include_snoozed=True)
        assert card["key"] in {c["key"] for c in both}
    finally:
        conn.close()


def test_the_snooze_expires_and_the_decision_returns(client):
    """The guarantee that makes snoozing safe: nothing is hidden for ever."""
    from chordential_oia.web import db, queue as queue_mod
    conn = db.connect()
    try:
        _seed_a_waiting_card(conn, db)
        card = queue_mod.compute_queue(conn, db)[0]
        db.snooze_queue_card(conn, card["key"], 7)
        assert card["key"] not in {c["key"] for c in queue_mod.compute_queue(conn, db)}

        # wind its timer into the past, exactly as the clock would
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        conn.execute("UPDATE queue_snooze SET until_at = ? WHERE key = ?",
                     (past, card["key"]))
        conn.commit()

        back = queue_mod.compute_queue(conn, db)
        assert card["key"] in {c["key"] for c in back}, "an expired snooze must not hide it"
        # the expired row is reaped rather than accumulating for ever
        assert conn.execute("SELECT COUNT(*) c FROM queue_snooze").fetchone()["c"] == 0
    finally:
        conn.close()


def test_snoozing_the_same_card_twice_resets_rather_than_raising(client):
    from chordential_oia.web import db, queue as queue_mod
    conn = db.connect()
    try:
        _seed_a_waiting_card(conn, db)
        key = queue_mod.compute_queue(conn, db)[0]["key"]
        db.snooze_queue_card(conn, key, 1)
        first = conn.execute("SELECT until_at FROM queue_snooze WHERE key = ?",
                             (key,)).fetchone()["until_at"]
        db.snooze_queue_card(conn, key, 30)          # upsert, not a primary-key error
        second = conn.execute("SELECT until_at FROM queue_snooze WHERE key = ?",
                              (key,)).fetchone()["until_at"]
        assert second > first
        assert conn.execute("SELECT COUNT(*) c FROM queue_snooze").fetchone()["c"] == 1
    finally:
        conn.close()


def test_bring_all_back_clears_every_snooze(client):
    from chordential_oia.web import db, queue as queue_mod
    conn = db.connect()
    try:
        _seed_a_waiting_card(conn, db)
        for c in queue_mod.compute_queue(conn, db):
            db.snooze_queue_card(conn, c["key"], 7)
        assert queue_mod.compute_queue(conn, db) == []
        db.clear_queue_snoozes(conn)
        assert queue_mod.compute_queue(conn, db), "un-snoozing must restore the queue"
    finally:
        conn.close()


def test_the_route_snoozes_and_returns_you_where_you_were(client):
    from chordential_oia.web import db, queue as queue_mod
    conn = db.connect()
    try:
        _seed_a_waiting_card(conn, db)
        key = queue_mod.compute_queue(conn, db)[0]["key"]
    finally:
        conn.close()

    r = client.post("/queue/snooze", data={"key": key, "days": "7", "next": "/queue"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/queue"

    conn = db.connect()
    try:
        assert key not in {c["key"] for c in queue_mod.compute_queue(conn, db)}
    finally:
        conn.close()

    # an off-site `next` is not honoured — these handlers must not be an open redirect
    r = client.post("/queue/unsnooze", data={"next": "https://evil.example/x"},
                    follow_redirects=False)
    assert r.headers["location"] == "/queue"


def test_the_page_names_what_it_is_hiding(client):
    """A queue that withholds silently reads 'clear' when it is not."""
    from chordential_oia.web import db, queue as queue_mod
    conn = db.connect()
    try:
        _seed_a_waiting_card(conn, db)
        key = queue_mod.compute_queue(conn, db)[0]["key"]
        db.snooze_queue_card(conn, key, 7)
    finally:
        conn.close()
    page = client.get("/queue").text
    assert "snoozed" in page.lower()
    assert "/queue?all=1" in page, "it must offer to show what it is holding back"
