"""Match Board — opportunities x qualified talent, drag/tap to assign (earmark)."""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.models import BuyerType, MusicDiscipline, MusicRequirement, Opportunity
from chordential_oia.talent import ReviewStatus, Talent


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def _seed_pair(db_mod):
    conn = db_mod.connect()
    try:
        opp_id = db_mod.insert_opportunity(conn, Opportunity(
            client="Acme Agency", need="Original brand spot music",
            description="National campaign, original composition.",
            buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
            budget_min=8000, budget_max=15000,
        ))
        tid = db_mod.insert_talent(conn, Talent(
            name="Composer Cay", disciplines=[MusicDiscipline.COMPOSITION],
            credits="Two national spots.", review_status=ReviewStatus.APPROVED,
        ))
    finally:
        conn.close()
    return opp_id, tid


def test_board_loads_with_opps_and_talent(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    r = client.get("/matchboard")
    assert r.status_code == 200
    assert "Match Board" in r.text
    assert "Original brand spot music" in r.text     # opportunity on the left
    assert "Composer Cay" in r.text                  # talent bubble on the right
    assert "matchboard.js" in r.text                 # drag/drop script wired


def test_assign_creates_earmark(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    r = client.post("/matchboard/assign",
                    data={"opp_id": opp_id, "talent_id": tid},
                    follow_redirects=False)
    assert r.status_code == 303
    conn = db_mod.connect()
    try:
        crew = db_mod.list_opp_assignments(conn, opp_id)
    finally:
        conn.close()
    assert len(crew) == 1
    assert crew[0]["talent_name"] == "Composer Cay"
    assert crew[0]["role"] == "Original composition"   # role from primary discipline
    # chip now shows on the board
    assert "Composer Cay" in client.get("/matchboard").text


def test_assign_is_deduped(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    client.post("/matchboard/assign", data={"opp_id": opp_id, "talent_id": tid})
    client.post("/matchboard/assign", data={"opp_id": opp_id, "talent_id": tid})
    conn = db_mod.connect()
    try:
        assert len(db_mod.list_opp_assignments(conn, opp_id)) == 1
    finally:
        conn.close()


def test_unassign_removes(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    client.post("/matchboard/assign", data={"opp_id": opp_id, "talent_id": tid})
    conn = db_mod.connect()
    aid = db_mod.list_opp_assignments(conn, opp_id)[0]["id"]
    conn.close()
    client.post("/matchboard/unassign", data={"assignment_id": aid})
    conn = db_mod.connect()
    try:
        assert db_mod.list_opp_assignments(conn, opp_id) == []
    finally:
        conn.close()


def test_focus_ranks_by_fit(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    r = client.get(f"/matchboard?opp={opp_id}")
    assert r.status_code == 200
    assert "Ranked by fit" in r.text
