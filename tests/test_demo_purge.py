"""Demo-data purge: production starts clean, real promoted opps are preserved."""

from chordential_oia.models import Opportunity
from chordential_oia.web import db, seed


def test_purge_removes_demo_keeps_real():
    conn = db.connect(":memory:")
    db.init_db(conn)
    db.insert_opportunity(conn, Opportunity(client="Meridian Beverage Co.",
                                            need="Sonic branding", source="sample"))
    db.insert_opportunity(conn, Opportunity(client="Brightline Films",
                                            need="Original score", source="agency_intel"))
    keep_id = db.insert_opportunity(conn, Opportunity(
        client="Unknown", need="[PAID] Looking for Music Composer", source="signal"))

    removed = seed.purge_demo_data(conn)
    assert removed == 2                                  # the two placeholders
    rows = conn.execute("SELECT id, source FROM opportunities").fetchall()
    assert [r["id"] for r in rows] == [keep_id]          # only the real promote remains
    assert rows[0]["source"] == "signal"

    # Idempotent: a clean DB is left untouched.
    assert seed.purge_demo_data(conn) == 0


def test_seed_demo_flag(monkeypatch):
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    assert seed.seed_demo_enabled() is False             # production default
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    assert seed.seed_demo_enabled() is True
