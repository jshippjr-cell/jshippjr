"""Demo-data purge: production starts clean, and everything a human made stays.

The purge used to identify placeholders by ELIMINATION — anything whose source was not
one of three known-real values. This test passed because it invented two sources
("sample", "agency_intel") that the elimination rule happened to catch. Neither is a
source the seeder writes, and the rule also caught `source='manual'`, which is what
`+ Add a deal` writes: every deal typed in by hand was deleted on the next boot. See
tests/test_a_deploy_does_not_eat_your_data.py.

The rule is now positive — delete only what the seeder itself creates — so the
placeholders here are real seeder sources.
"""

from chordential_oia.models import Opportunity
from chordential_oia.web import db, seed


def _a_real_placeholder_source() -> str:
    """Asked of the seeder, so this test cannot drift from it either."""
    sources = seed._demo_opp_sources()
    assert sources, "the seeder yielded no sources — the purge has nothing to identify"
    return sources[0]


def test_purge_removes_demo_keeps_real():
    conn = db.connect(":memory:")
    db.init_db(conn)
    placeholder = _a_real_placeholder_source()
    db.insert_opportunity(conn, Opportunity(client="Meridian Beverage Co.",
                                            need="Sonic branding", source=placeholder))
    db.insert_opportunity(conn, Opportunity(client="Brightline Films",
                                            need="Original score", source=placeholder))
    keep_id = db.insert_opportunity(conn, Opportunity(
        client="Unknown", need="[PAID] Looking for Music Composer", source="signal"))

    removed = seed.purge_demo_data(conn)
    assert removed == 2                                  # the two placeholders
    rows = conn.execute("SELECT id, source FROM opportunities").fetchall()
    assert [r["id"] for r in rows] == [keep_id]          # only the real promote remains
    assert rows[0]["source"] == "signal"

    # Idempotent: a clean DB is left untouched.
    assert seed.purge_demo_data(conn) == 0


def test_purge_keeps_everything_a_human_made():
    """The bug this file did not catch. A deal added by hand, a rehearsal, and a lead
    that arrived through the front door are all somebody's work."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    placeholder = _a_real_placeholder_source()
    db.insert_opportunity(conn, Opportunity(client="Placeholder Co", need="x",
                                            source=placeholder))
    for src in ("manual", "rehearsal", "front_of_house", "lead_indicator", "signal"):
        db.insert_opportunity(conn, Opportunity(client=f"{src} buyer", need="real work",
                                                source=src))

    assert seed.purge_demo_data(conn) == 1
    survived = {r["source"] for r in conn.execute("SELECT source FROM opportunities")}
    assert survived == {"manual", "rehearsal", "front_of_house", "lead_indicator",
                        "signal"}


def test_seed_demo_flag(monkeypatch):
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    assert seed.seed_demo_enabled() is False             # production default
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    assert seed.seed_demo_enabled() is True
