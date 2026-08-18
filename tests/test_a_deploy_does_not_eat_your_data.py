"""Every deal you typed in by hand was deleted on the next deploy.

Found while checking that a rehearsal deal would survive long enough to be tested with.
It did not — and neither did anything else a human had made.

`purge_demo_data` runs at every boot when demo seeding is off, which is production, and
it identified the build's placeholders by *elimination*: delete every opportunity whose
`source` is not one of ``("signal", "front_of_house", "lead_indicator")``. That is a
whitelist nobody could keep complete, and `+ Add a deal` writes ``source='manual'``.
So a hand-added deal — with its project, proposals, outreach and brief progress — was
removed on the next start, and with `autoDeploy: true` that is every push. Nothing
failed and nothing logged; afterwards the dashboard simply looked empty.

The supply side had the identical shape: ``DELETE FROM talent WHERE source != 'applicant'``
took every creator added by hand, along with their agreement, rate and portal token,
unless an assignment happened to be holding them.

The rule is now positive: delete only what the seeder itself creates, asked of the
seeder. Everything else is somebody's work.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def prod(tmp_path, monkeypatch):
    """Production's shape: the admin gate on, demo seeding OFF."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "prod.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    for m in ("db", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _boot(app_mod):
    """One deploy: start the app, run its lifespan, stop it."""
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as c:
        yield_ = c.get("/healthz")
    return yield_


def _opps(app_mod):
    conn = app_mod.db.connect()
    try:
        return [(r["client"], r["source"]) for r in
                conn.execute("SELECT client, source FROM opportunities ORDER BY id")]
    finally:
        conn.close()


def _talent(app_mod):
    conn = app_mod.db.connect()
    try:
        return [r["name"] for r in conn.execute("SELECT name FROM talent ORDER BY id")]
    finally:
        conn.close()


# ── the demand side ─────────────────────────────────────────────────────────────────
def test_a_deal_added_by_hand_survives_a_deploy(prod):
    from fastapi.testclient import TestClient
    app_mod = prod
    with TestClient(app_mod.app) as c:
        c.post("/admin/login", data={"email": "", "password": "passphrase"},
               follow_redirects=False)
        r = c.post("/opportunity/new",
                   data={"client": "Real Buyer Ltd", "need": "A deal typed in by hand",
                         "budget_min": "5000", "budget_max": "9000",
                         "buyer_type": "brand"}, follow_redirects=False)
        assert r.status_code == 303
    assert _opps(app_mod) == [("Real Buyer Ltd", "manual")]

    _boot(app_mod)                      # the next push redeploys
    assert _opps(app_mod) == [("Real Buyer Ltd", "manual")], (
        "the deal was deleted by a deploy — this is how a hand-added pipeline vanished")


def test_a_rehearsal_survives_long_enough_to_rehearse_with(prod):
    from fastapi.testclient import TestClient
    app_mod = prod
    with TestClient(app_mod.app) as c:
        c.post("/admin/login", data={"email": "", "password": "passphrase"},
               follow_redirects=False)
        c.post("/rehearsal", follow_redirects=False)
    assert [s for _c, s in _opps(app_mod)] == ["rehearsal"]
    _boot(app_mod)
    assert [s for _c, s in _opps(app_mod)] == ["rehearsal"]


def test_everything_hanging_off_a_hand_added_deal_survives_too(prod):
    """The purge cascaded — project, proposals, outreach, brief progress. A deal that
    comes back without its project is not a deal that survived."""
    from fastapi.testclient import TestClient
    app_mod = prod
    db = app_mod.db
    with TestClient(app_mod.app) as c:
        c.post("/admin/login", data={"email": "", "password": "passphrase"},
               follow_redirects=False)
        c.post("/opportunity/new",
               data={"client": "Real Buyer Ltd", "need": "Hand-typed", "budget_min": "5000",
                     "budget_max": "9000", "buyer_type": "brand"}, follow_redirects=False)
    conn = db.connect()
    try:
        opp_id = conn.execute("SELECT id FROM opportunities").fetchone()["id"]
        pid = db.insert_project(conn, opp_id, "Real Buyer Ltd", "Hand-typed",
                                5000.0, 9000.0, ["Composer"])
    finally:
        conn.close()

    _boot(app_mod)

    conn = db.connect()
    try:
        assert db.get_project(conn, pid) is not None, "the project went with it"
        assert db.get_opportunity(conn, opp_id) is not None
    finally:
        conn.close()


# ── the supply side ─────────────────────────────────────────────────────────────────
def test_a_creator_added_by_hand_survives_a_deploy(prod):
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    app_mod = prod
    _boot(app_mod)                      # first boot creates the schema
    conn = app_mod.db.connect()
    try:
        app_mod.db.insert_talent(conn, Talent(
            name="Hand Added Composer", email="hc@example.com", source="manual",
            disciplines=[MusicDiscipline.COMPOSITION], rate=80.0))
    finally:
        conn.close()
    assert _talent(app_mod) == ["Hand Added Composer"]

    _boot(app_mod)
    assert _talent(app_mod) == ["Hand Added Composer"], (
        "the creator was deleted by a deploy — with their agreement, rate and portal "
        "token, and no assignment to hold them")


def test_an_applicant_still_survives(prod):
    """The one case the old rule got right must keep working."""
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    app_mod = prod
    _boot(app_mod)
    conn = app_mod.db.connect()
    try:
        app_mod.db.insert_talent(conn, Talent(
            name="Applied Themselves", email="a@example.com", source="applicant",
            disciplines=[MusicDiscipline.COMPOSITION]))
    finally:
        conn.close()
    _boot(app_mod)
    assert _talent(app_mod) == ["Applied Themselves"]


# ── and the purge still does its actual job ─────────────────────────────────────────
def test_the_build_placeholders_are_still_removed(prod):
    """The purge exists for a reason: a dev database that was seeded once must come back
    clean when demo mode is turned off. Fixing it must not turn it off."""
    from chordential_oia.web import seed
    app_mod = prod
    _boot(app_mod)
    conn = app_mod.db.connect()
    try:
        seed.seed(conn)
        before = conn.execute("SELECT COUNT(*) c FROM opportunities").fetchone()["c"]
        assert before > 0, "nothing was seeded, so this proves nothing"
    finally:
        conn.close()

    _boot(app_mod)
    assert _opps(app_mod) == [], "the build's placeholders were left in a clean instance"


def test_the_demo_sources_are_asked_of_the_seeder_not_listed(prod):
    """A hard-coded list drifts from what it describes — which is the whole bug. The
    purge must enumerate the seeder, so a source the seeder drops stops being purged."""
    from chordential_oia.web import seed
    sources = set(seed._demo_opp_sources())
    assert sources, "the purge could not enumerate the seeder"
    assert sources == {(o.source or "") for o in seed.gather_opportunities()}
    for real in ("manual", "rehearsal", "signal", "front_of_house", "lead_indicator"):
        assert real not in sources, f"{real!r} is somebody's work, not a placeholder"


def test_a_purge_that_cannot_enumerate_deletes_nothing(prod, monkeypatch):
    """Fail closed. If the seeder cannot be read, the safe answer is to touch nothing —
    the alternative is what this file exists to prevent."""
    from chordential_oia.web import seed
    app_mod = prod
    _boot(app_mod)
    conn = app_mod.db.connect()
    try:
        seed.seed(conn)
        monkeypatch.setattr(seed, "_demo_opp_sources", lambda: ())
        assert seed.purge_demo_data(conn) == 0
        assert conn.execute("SELECT COUNT(*) c FROM opportunities").fetchone()["c"] > 0
    finally:
        conn.close()
