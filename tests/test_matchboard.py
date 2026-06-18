"""Match Board — assigning talent staffs the opportunity's PROJECT (shows on the
Projects page) and broadcasts to the crew feed."""

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


def test_board_loads(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    r = client.get("/matchboard")
    assert r.status_code == 200
    assert "Original brand spot music" in r.text   # opportunity (left)
    assert "Composer Cay" in r.text                # talent bubble (right)


def test_assign_creates_project_and_crew_and_broadcast(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    r = client.post("/matchboard/assign",
                    data={"opp_id": opp_id, "talent_id": tid},
                    follow_redirects=False)
    assert r.status_code == 303

    conn = db_mod.connect()
    try:
        proj = db_mod.project_for_opp(conn, opp_id)
        assert proj is not None                     # project now exists
        crew = db_mod.list_assignments(conn, proj["id"])
        names = [a["talent_name"] for a in crew]
        updates = db_mod.list_updates(conn, proj["id"])
    finally:
        conn.close()
    assert "Composer Cay" in names                  # real project crew
    # broadcast to the team feed naming who joined + the current team
    assert any("Composer Cay" in u["body"] and "team" in u["body"].lower()
               for u in updates)


def test_assignment_shows_on_projects_page(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    client.post("/matchboard/assign", data={"opp_id": opp_id, "talent_id": tid})
    projects = client.get("/projects").text
    assert "Original brand spot music" in projects   # project surfaced on /projects
    # and the crew shows on the project page
    conn = db_mod.connect()
    pid = db_mod.project_for_opp(conn, opp_id)["id"]
    conn.close()
    detail = client.get(f"/project/{pid}").text
    assert "Composer Cay" in detail


def test_assign_is_deduped(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    client.post("/matchboard/assign", data={"opp_id": opp_id, "talent_id": tid})
    client.post("/matchboard/assign", data={"opp_id": opp_id, "talent_id": tid})
    conn = db_mod.connect()
    try:
        pid = db_mod.project_for_opp(conn, opp_id)["id"]
        crew = db_mod.list_assignments(conn, pid)
    finally:
        conn.close()
    assert sum(1 for a in crew if a["talent_id"] == tid) == 1


def test_unassign_removes_and_notifies(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    client.post("/matchboard/assign", data={"opp_id": opp_id, "talent_id": tid})
    conn = db_mod.connect()
    pid = db_mod.project_for_opp(conn, opp_id)["id"]
    aid = db_mod.list_assignments(conn, pid)[0]["id"]
    conn.close()

    client.post("/matchboard/unassign", data={"assignment_id": aid})
    conn = db_mod.connect()
    try:
        crew = db_mod.list_assignments(conn, pid)
        updates = db_mod.list_updates(conn, pid)
    finally:
        conn.close()
    assert crew == []
    assert any("left the crew" in u["body"] for u in updates)


def test_focus_ranks_by_fit(ctx):
    client, db_mod = ctx
    opp_id, tid = _seed_pair(db_mod)
    r = client.get(f"/matchboard?opp={opp_id}")
    assert r.status_code == 200
    assert "Ranked by fit" in r.text
