"""Phase 3 — The Cue Layer: cues + hits on delivery_json, the operator doors that
build them, per-cue state (incl. human-pressed approval), conform surfacing, and
the composer room rendering cue regions + hit diamonds on its spine."""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod, app_mod


def _composer_with_project(db_mod):
    from chordential_oia.talent import InviteStatus, ReviewStatus, Talent
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="Devin Test", email="devin@example.com", credits="c",
        review_status=ReviewStatus.APPROVED, invite_status=InviteStatus.JOINED,
        rate=90.0))
    db_mod.set_talent_agreement(conn, tid, "2026-07-18", "test")
    pid = db_mod.insert_project(
        conn, opp_id=None, client="Acme", need="Brand spot", budget_min=4000,
        budget_max=8000, deadline="2026-08-10", roles=["Composer"])
    db_mod.add_assignment(conn, pid, "Composer", tid)
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    conn.close()
    return tid, pid, tok


# ── the data model ──────────────────────────────────────────────────────────
def test_cue_model_timecode_parsing_and_state(ctx):
    _, db_mod, _ = ctx
    _, pid, _ = _composer_with_project(db_mod)
    conn = db_mod.connect()
    cue = db_mod.add_cue(conn, pid, name="Held breath", t_in="0:00", t_out="0:14",
                         direction="sparse")
    assert cue["code"] == "m01" and cue["t_in"] == 0.0 and cue["t_out"] == 14.0
    assert cue["state"] == "open"
    # clock form and h:m:s both parse
    c2 = db_mod.add_cue(conn, pid, name="Lift", t_in="1:00", t_out="1:02:03")
    assert c2["code"] == "m02" and c2["t_in"] == 60.0 and c2["t_out"] == 3723.0
    # a hit inside a cue
    db_mod.add_hit(conn, pid, cue["id"], t="0:06", name="logo")
    # approval stamps approved_at; reset clears it
    db_mod.set_cue_state(conn, pid, cue["id"], "approved")
    cues = db_mod.get_cues(conn, pid)
    m01 = next(c for c in cues if c["code"] == "m01")
    assert m01["state"] == "approved" and m01["approved_at"]
    assert m01["hits"] and m01["hits"][0]["t"] == 6.0
    db_mod.set_cue_state(conn, pid, cue["id"], "open")
    m01 = next(c for c in db_mod.get_cues(conn, pid) if c["code"] == "m01")
    assert m01["state"] == "open" and not m01.get("approved_at")
    conn.close()


def test_bad_timecode_is_guarded(ctx):
    _, db_mod, _ = ctx
    _, pid, _ = _composer_with_project(db_mod)
    conn = db_mod.connect()
    cue = db_mod.add_cue(conn, pid, name="bad", t_in="1e999", t_out="-5")
    assert cue["t_in"] is None and cue["t_out"] is None
    conn.close()


def test_conform_surfacing_which_cues_a_cut_touches(ctx):
    _, db_mod, _ = ctx
    _, pid, _ = _composer_with_project(db_mod)
    conn = db_mod.connect()
    db_mod.add_cue(conn, pid, name="a", t_in="0", t_out="5")     # m01
    db_mod.add_cue(conn, pid, name="b", t_in="10", t_out="20")   # m02
    # a whole-timeline recut touches every cue
    assert set(db_mod.cues_touched_by_cut(conn, pid)) == {"m01", "m02"}
    # a windowed recut only touches overlapping cues
    assert db_mod.cues_touched_by_cut(conn, pid, 12, 15) == ["m02"]
    assert db_mod.cues_touched_by_cut(conn, pid, 1, 3) == ["m01"]
    assert db_mod.cues_touched_by_cut(conn, pid, 6, 9) == []
    conn.close()


# ── the operator doors ──────────────────────────────────────────────────────
def test_operator_can_build_and_approve_cues(ctx):
    client, db_mod, _ = ctx
    _, pid, _ = _composer_with_project(db_mod)
    r = client.post(f"/project/{pid}/delivery/cues/add",
                    data={"name": "Held breath", "t_in": "0:00", "t_out": "0:05",
                          "direction": "sparse, tense"}, follow_redirects=False)
    assert r.status_code == 303
    conn = db_mod.connect()
    cues = db_mod.get_cues(conn, pid)
    conn.close()
    assert len(cues) == 1 and cues[0]["code"] == "m01"
    cid = cues[0]["id"]
    client.post(f"/project/{pid}/delivery/cues/{cid}/hit",
                data={"t": "0:03", "name": "logo"}, follow_redirects=False)
    client.post(f"/project/{pid}/delivery/cues/{cid}/state",
                data={"state": "approved"}, follow_redirects=False)
    conn = db_mod.connect()
    cue = db_mod.get_cues(conn, pid)[0]
    conn.close()
    assert cue["state"] == "approved" and cue["hits"][0]["name"] == "logo"
    # console shows the cue panel
    page = client.get(f"/project/{pid}/delivery").text
    assert "Cue list" in page and "m01" in page and "Held breath" in page


def test_bad_state_string_ignored(ctx):
    client, db_mod, _ = ctx
    _, pid, _ = _composer_with_project(db_mod)
    client.post(f"/project/{pid}/delivery/cues/add", data={"name": "x"},
                follow_redirects=False)
    conn = db_mod.connect(); cid = db_mod.get_cues(conn, pid)[0]["id"]; conn.close()
    client.post(f"/project/{pid}/delivery/cues/{cid}/state",
                data={"state": "banana"}, follow_redirects=False)
    conn = db_mod.connect(); cue = db_mod.get_cues(conn, pid)[0]; conn.close()
    assert cue["state"] == "open"        # unchanged by the invalid state


def test_delete_cue_and_hit(ctx):
    client, db_mod, _ = ctx
    _, pid, _ = _composer_with_project(db_mod)
    client.post(f"/project/{pid}/delivery/cues/add", data={"name": "x"},
                follow_redirects=False)
    conn = db_mod.connect(); cid = db_mod.get_cues(conn, pid)[0]["id"]; conn.close()
    client.post(f"/project/{pid}/delivery/cues/{cid}/hit",
                data={"t": "0:02", "name": "h"}, follow_redirects=False)
    conn = db_mod.connect(); hid = db_mod.get_cues(conn, pid)[0]["hits"][0]["id"]; conn.close()
    client.post(f"/project/{pid}/delivery/cues/{cid}/hit/{hid}/delete",
                follow_redirects=False)
    conn = db_mod.connect(); assert not db_mod.get_cues(conn, pid)[0]["hits"]; conn.close()
    client.post(f"/project/{pid}/delivery/cues/{cid}/delete", follow_redirects=False)
    conn = db_mod.connect(); assert db_mod.get_cues(conn, pid) == []; conn.close()


# ── the composer room ───────────────────────────────────────────────────────
def test_composer_room_renders_cue_lane(ctx):
    client, db_mod, _ = ctx
    _, pid, tok = _composer_with_project(db_mod)
    # no cues → no cue LANE div (fail-soft: the room is the audio-and-notes room).
    # The CSS rule + empty data array are always present; the lane div is not.
    assert 'class="lane sr-lane-cues"' not in client.get(f"/creator/{tok}").text
    conn = db_mod.connect()
    cue = db_mod.add_cue(conn, pid, name="Held breath", t_in="0", t_out="5")
    db_mod.add_hit(conn, pid, cue["id"], t="3", name="logo")
    conn.close()
    page = client.get(f"/creator/{tok}").text
    assert 'class="lane sr-lane-cues"' in page and "sr-cues-data" in page
    assert "Held breath" in page and '"code": "m01"' in page
