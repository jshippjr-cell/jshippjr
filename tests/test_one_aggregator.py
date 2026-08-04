"""One authority for "what is waiting on me".

The launch review found the dashboard reporting **2** decisions waiting while
/queue reported **11** on the same database, because each surface computed the
answer independently — the dashboard summed six things inline, the Disposition
Queue ranks ten. It also found a **Won** deal, with a project staffed and in
delivery, featured on the dashboard as "Schedule the discovery call", because the
next-action ladder infers position from artifacts and that deal had no meeting
rows to infer from.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "agg.db"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    return mod


def test_dashboard_and_queue_report_the_same_number(app_mod):
    """The headline disagreement. Both surfaces must answer from one computation,
    so no seeded state can make them differ."""
    from chordential_oia.web import db, queue as queue_mod

    with TestClient(app_mod.app) as c:
        page = c.get("/dashboard").text
        assert c.get("/queue").status_code == 200

    conn = db.connect()
    try:
        expected = len(queue_mod.compute_queue(conn, db))
    finally:
        conn.close()

    import re
    m = re.search(r'class="mc-count"[^>]*>\s*(\d+)\s*<', page)
    assert m, "the dashboard no longer shows a waiting-on-you count"
    assert int(m.group(1)) == expected, (
        f"dashboard says {m.group(1)}, the queue computes {expected}")


def test_the_dashboard_does_not_list_the_same_decision_twice(app_mod):
    """A "▶ Your move" table listed the same deals the Mission Control hero
    features from the same set — on a page whose own comment says ONE number owns
    it. The hero features the top move; /queue is the full ranked list."""
    with TestClient(app_mod.app) as c:
        page = c.get("/dashboard").text
    assert 'id="operator-moves"' not in page
    assert "/queue" in page, "the hero must point at the full list"


def test_a_won_deal_is_never_told_to_schedule_the_discovery_call(app_mod):
    """The ladder reads artifacts — meeting rows, a brief snapshot, a commercial
    review — and a deal can reach Won without them. The recorded stage is a floor:
    winning is a decision a human made, and it outranks a missing artifact."""
    from chordential_oia.web import db, next_action

    with TestClient(app_mod.app):      # the lifespan is what seeds the demo data
        pass
    conn = db.connect()
    try:
        won = [o for o in db.list_opportunities(conn) if (o["status"] or "") == "Won"]
        assert won, "seed no longer contains a Won deal — this test needs one"
        for opp in won:
            project = None
            for p in db.list_projects(conn):
                if p["opp_id"] == opp["id"]:
                    project = p
                    break
            na = next_action.compute(conn, db, db.get_opportunity(conn, opp["id"]), project)
            assert "discovery call" not in na["label"].lower(), (
                f"Won deal {opp['id']} was told to {na['label']!r}")
            assert "discovery summary" not in na["label"].lower()
    finally:
        conn.close()


def test_a_project_alone_floors_the_ladder_past_discovery(app_mod):
    """Belt and braces: a deal with a project has demonstrably passed discovery
    and the commercial gate, whatever its recorded status says."""
    from chordential_oia.web import db, next_action

    with TestClient(app_mod.app):      # the lifespan is what seeds the demo data
        pass
    conn = db.connect()
    try:
        projects = db.list_projects(conn)
        assert projects, "seed no longer contains a project — this test needs one"
        for p in projects:
            if not p["opp_id"]:
                continue
            opp = db.get_opportunity(conn, p["opp_id"])
            if opp is None or (opp["status"] or "") in ("Lost", "Passed"):
                continue
            na = next_action.compute(conn, db, opp, p)
            assert "discovery call" not in na["label"].lower(), (
                f"project {p['id']} was told to {na['label']!r}")
    finally:
        conn.close()
