"""One open-pipeline number.

The launch review found three surfaces asserting three different pipelines on the
same database: the dashboard KPI read **$15,000** (a `SUM(budget_max)` — the
client's stated ceiling), the Tentative column read **$4,847** (a `SUM(outcome_value)`
— what we bid), and /revenue read **$0**, because `revenue_summary` sourced open
pipeline from the `proposals` table and `insert_proposal` requires a `project_id`,
which only exists once a deal has already been won.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "pipe.db"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    return mod


def _money_after(text: str, marker: str) -> str:
    """The first dollar figure following a marker in the rendered page."""
    import re
    i = text.find(marker)
    assert i >= 0, f"{marker!r} not on the page"
    m = re.search(r"\$[\d,]+", text[i:i + 400])
    assert m, f"no figure after {marker!r}"
    return m.group(0)


def test_every_surface_reports_the_same_open_pipeline(app_mod):
    """The headline disagreement — three sums, one question."""
    from chordential_oia.web import db

    with TestClient(app_mod.app) as c:
        dash = c.get("/dashboard").text
        rev = c.get("/revenue").text

    conn = db.connect()
    try:
        expected = db.open_pipeline(conn)["value"]
    finally:
        conn.close()
    want = "${:,.0f}".format(expected)

    assert _money_after(dash, "in flight") == want, "dashboard KPI disagrees"
    assert _money_after(rev, "Open pipeline") == want, "/revenue disagrees"


def test_revenue_open_pipeline_is_not_sourced_from_a_post_award_table(app_mod):
    """`proposals` rows require a project, and projects only exist after a deal is
    won — so sourcing OPEN pipeline from that table can only ever yield $0. The
    seeded DB has open deals and no proposals: the number must still be non-zero."""
    from chordential_oia.web import db

    with TestClient(app_mod.app):
        pass
    conn = db.connect()
    try:
        proposals = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        summary = db.revenue_summary(conn)
        pipe = db.open_pipeline(conn)
    finally:
        conn.close()

    assert proposals == 0, "seed now has proposals — pick a fixture that still has none"
    assert pipe["deals"] > 0, "seed has no open deals — this test needs one"
    assert summary["pipeline_open"] > 0, (
        "open pipeline is $0 with open deals on the books — it is reading the "
        "post-award proposals table again")


def test_the_number_prefers_what_we_bid_over_what_the_client_said(app_mod):
    """Precedence, best evidence first: our bid, then the disclosed budget's
    midpoint, then nothing. The old KPI summed `budget_max`, the client's ceiling,
    which flatters the pipeline on every deal that discloses a range."""
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    from chordential_oia.web import db

    with TestClient(app_mod.app):
        pass
    conn = db.connect()
    try:
        before = db.open_pipeline(conn)["value"]
        oid = db.insert_opportunity(conn, Opportunity(
            client="Precedence Co", need="Anthem", description="x",
            buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
            budget_min=10000, budget_max=30000))

        # disclosed budget only → the midpoint, never the ceiling
        db.update_status(conn, oid, "Pursuing")
        mid = db.open_pipeline(conn)
        assert mid["value"] == pytest.approx(before + 20000), "should use the midpoint"
        assert mid["from_budgets"] >= 1

        # once we bid, the bid wins
        db.update_status(conn, oid, "Submitted", 24000.0)
        bid = db.open_pipeline(conn)
        assert bid["value"] == pytest.approx(before + 24000), "our bid should win"
        assert bid["from_bids"] >= 1
    finally:
        conn.close()


def test_won_and_lost_deals_are_not_open_pipeline(app_mod):
    """Pipeline is what is still live. A settled deal has a settled number."""
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    from chordential_oia.web import db

    with TestClient(app_mod.app):
        pass
    conn = db.connect()
    try:
        before = db.open_pipeline(conn)["value"]
        oid = db.insert_opportunity(conn, Opportunity(
            client="Settled Co", need="Spot", description="x",
            buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
            budget_min=5000, budget_max=5000))
        for settled in ("Won", "Lost", "Passed"):
            db.update_status(conn, oid, settled, 5000.0)
            assert db.open_pipeline(conn)["value"] == pytest.approx(before), (
                f"a {settled} deal is still being counted as open pipeline")
    finally:
        conn.close()
