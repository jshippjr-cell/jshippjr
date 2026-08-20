"""ADR-0024 — the A-3 supply-side floor: no assignment without an executed
Composer Agreement + rate. The gate is server-side on BOTH assign paths (the
project page and the matchboard), mirrors the payment gate on release, and the
refusal surfaces as an actionable banner. Founder-ratified: hard block."""

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


def _win_and_make_project(client, opp_id=1):
    client.post(f"/opportunity/{opp_id}/status",
                data={"status": "Won", "outcome_value": "9000"}, follow_redirects=True)
    r = client.post(f"/opportunity/{opp_id}/project", follow_redirects=False)
    return int(re.search(r"/project/(\d+)", r.headers["location"]).group(1))


def _unsigned_talent_id(client, disciplines=None):
    """A brand-new approved creator with NO agreement and NO rate — blocked.

    They carry a CRAFT by default, because since ADR-0082 the craft is what decides which
    of the two standing agreements governs them. A profile with none gets neither
    document, which is a different (and also correct) screen — see
    `test_a_creator_with_no_craft_gets_neither_agreement`.
    """
    from chordential_oia.models import MusicDiscipline
    db = _db()
    from chordential_oia.talent import InviteStatus, ReviewStatus, Talent
    conn = db.connect()
    try:
        tid = db.insert_talent(conn, Talent(
            name="Gate Testcase", email="gate@example.com",
            credits="Test credits", review_status=ReviewStatus.APPROVED,
            invite_status=InviteStatus.JOINED,
            disciplines=([MusicDiscipline.COMPOSITION] if disciplines is None
                         else list(disciplines)),
        ))
    finally:
        conn.close()
    return tid


def test_blockers_computed():
    db = _db()

    class Row(dict):
        def keys(self):  # sqlite3.Row-alike
            return list(super().keys())

        def __getitem__(self, k):
            return super().__getitem__(k)

    assert db.talent_assignment_blockers(None) == ["agreement", "rate"]
    assert db.talent_assignment_blockers(
        Row(agreement_executed_at="", rate=None)) == ["agreement", "rate"]
    assert db.talent_assignment_blockers(
        Row(agreement_executed_at="2026-07-18", rate=None)) == ["rate"]
    assert db.talent_assignment_blockers(
        Row(agreement_executed_at="", rate=90.0)) == ["agreement"]
    assert db.talent_assignment_blockers(
        Row(agreement_executed_at="2026-07-18", rate=90.0)) == []


def test_project_assign_refused_without_agreement(client):
    pid = _win_and_make_project(client, 1)
    tid = _unsigned_talent_id(client)
    r = client.post(f"/project/{pid}/assign",
                    data={"role": "Composer", "talent_id": tid},
                    follow_redirects=False)
    assert r.status_code == 303
    assert f"err=agreement&t={tid}" in r.headers["location"]
    # No side effects: nothing was assigned.
    page = client.get(f"/project/{pid}").text
    assert "Unassign" not in page
    # The refusal banner is actionable — names the creator and links the fix.
    banner = client.get(r.headers["location"]).text
    assert "Assignment blocked" in banner
    assert "Gate Testcase" in banner
    assert f"/talent/{tid}" in banner


def test_matchboard_assign_refused_without_agreement(client):
    tid = _unsigned_talent_id(client)
    r = client.post("/matchboard/assign",
                    data={"opp_id": 1, "talent_id": tid},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "err=agreement" in r.headers["location"]
    banner = client.get(r.headers["location"]).text
    assert "Assignment blocked" in banner


def test_assign_allowed_after_agreement_and_rate(client):
    pid = _win_and_make_project(client, 1)
    tid = _unsigned_talent_id(client)
    db = _db()
    # Rate via the profile; agreement via the operator action (the real flow).
    conn = db.connect()
    try:
        conn.execute("UPDATE talent SET rate = ? WHERE id = ?", (90.0, tid))
        conn.commit()
    finally:
        conn.close()
    client.post(f"/talent/{tid}/agreement",
                data={"executed": "1", "ref": "Dropbox/agreements/gate.pdf"},
                follow_redirects=True)
    r = client.post(f"/project/{pid}/assign",
                    data={"role": "Composer", "talent_id": tid},
                    follow_redirects=False)
    assert "err=" not in r.headers["location"]
    assert "Unassign" in client.get(f"/project/{pid}").text


def test_talent_page_shows_agreement_state(client):
    """The manual tick survives as the FALLBACK — a paper agreement signed before the
    portal existed is a real agreement. It is relabelled "Mark executed by hand" because
    the primary path is now the composer signing it in their portal, where the system can
    still produce the text they agreed to.

    The creator carries a DISCIPLINE now: since ADR-0082 there are two standing
    agreements and which one governs is read from their craft, so a blank profile gets
    neither (asserted in the test below). This one is about a writer.
    """
    tid = _unsigned_talent_id(client)
    page = client.get(f"/talent/{tid}").text
    assert "Mark executed by hand" in page
    assert "Composer Agreement not signed yet" in page, (
        "the operator should be able to see, and send, the real thing")
    assert "Not assignable yet" in page
    client.post(f"/talent/{tid}/agreement",
                data={"executed": "1", "ref": "Drive/agr.pdf"}, follow_redirects=True)
    page = client.get(f"/talent/{tid}").text
    assert "Composer Agreement executed" in page
    assert "Drive/agr.pdf" in page
    # Clearing wipes both the date and the ref (no dangling reference).
    client.post(f"/talent/{tid}/agreement",
                data={"executed": "0"}, follow_redirects=True)
    page = client.get(f"/talent/{tid}").text
    assert "Mark executed by hand" in page
    assert "Drive/agr.pdf" not in page


def test_a_creator_with_no_craft_gets_neither_agreement(client):
    """The gate's other half, since ADR-0082. The Composer Agreement conveys a publishing
    share and the Service Agreement conveys none, so serving one to a blank profile is a
    guess about what someone does for a living — the exact defect that made mixers sign
    a writer's agreement. The page asks for the evidence instead."""
    tid = _unsigned_talent_id(client, disciplines=[])
    page = client.get(f"/talent/{tid}").text
    assert "No standing agreement can be issued yet" in page
    assert "Add at least one discipline" in page
    assert "Composer Agreement not signed yet" not in page
    assert "Not assignable yet" in page


def test_seeded_demo_composers_clear_the_gate(client):
    """The demo models the compliant state: seeded APPROVED creators carry an
    executed agreement + rate, so the existing demo flows still assign."""
    db = _db()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT name, agreement_executed_at, rate FROM talent "
            "WHERE review_status = 'Approved'").fetchall()
    finally:
        conn.close()
    assert rows, "demo seed should include approved creators"
    for r in rows:
        assert (r["agreement_executed_at"] or "").strip(), r["name"]
        assert (r["rate"] or 0) > 0, r["name"]
