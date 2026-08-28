"""The Production Readiness page became a layer of the room, behind `C`.

    "Can we incorporate this into 'the room' within the 'C' key for checklist?"
                                                    — the operator, 2026-08-28

It was a page of its own — campaign summary, production checklist, "Meet your team", how
we work together, upcoming milestones — and every line of it describes the engagement the
room already IS. A second address for that is a second thing to keep in step, which is
the failure ADR-0029 keeps being written about; so it joins `B` brief, `N` notes and
`V` takes as a layer, and there is exactly one readiness behind all of them.

WHAT THE MOVE HAD TO SUBTRACT, and why the tests below are mostly about that: the page
was built for one reader and the room has three. Two things on it are not everyone's.

**The roster.** "Meet your team" printed `talent_name` and `talent_email`. `room.CAPS`
denies a buyer `see_who` on the stated ground that *the roster is the business, and it
walks out of the door with the name* — so shipping that page into the client's room
unchanged would have handed over the thing the capability model exists to protect. The
buyer still sees that a composer, a mixer and an editor exist and whether each is
assigned; never who they are. Their PRODUCER survives by name, because that one is ours
and is who they write to.

**The commercial rows.** The deposit, the procurement checklist and the budget line are
the buyer's money and the buyer's onboarding. The studio runs them, the buyer owns them,
and a creator has no business with any of it — least of all the budget, which is what the
client said they would spend on the person reading it.
"""
import importlib
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")

from chordential_oia.web import room


# --------------------------------------------------------------------------- #
# The subtraction itself — a pure function, so it is tested as one.
# --------------------------------------------------------------------------- #
def _ready():
    return {
        "summary": {"campaign": "Autumn film", "producer": "Jon",
                    "budget": "$55,000–$65,000, a hard ceiling",
                    "rights": "Original, cleared worldwide"},
        "checklist": [
            {"label": "Creative direction approved", "state": "done"},
            {"label": "Deposit received", "state": "pending", "lens": "commercial"},
            {"label": "Procurement", "state": "pending", "lens": "commercial"},
            {"label": "Your picture received", "state": "done"},
        ],
        "team": [
            {"role": "Producer", "name": "Jon Shipp", "email": "jon@chordential.com",
             "assigned": True, "house": True},
            {"role": "Composer", "name": "Maya Okafor", "email": "maya@roster.com",
             "assigned": True},
            {"role": "Mixer", "name": "Being assigned", "email": "", "assigned": False},
        ],
        "all_ready": False, "client_actions": [], "upcoming": [], "communication": {},
    }


def test_a_creator_is_not_shown_the_buyers_money():
    v = room.readiness_view(_ready(), room.TALENT)
    labels = [r["label"] for r in v["checklist"]]
    assert "Deposit received" not in labels and "Procurement" not in labels
    assert "Creative direction approved" in labels, "it subtracted more than the lens"
    assert "budget" not in v["summary"], (
        "the client's ceiling reached the person being paid out of it")
    assert v["summary"]["rights"], "the rights line is everyone's — it is what we sell"


def test_the_buyer_and_the_studio_keep_the_commercial_rows():
    for role in (room.CLIENT, room.OPERATOR):
        v = room.readiness_view(_ready(), role)
        labels = [r["label"] for r in v["checklist"]]
        assert "Deposit received" in labels, f"{role} lost their own deposit line"
        assert v["summary"]["budget"], f"{role} lost the budget"


def test_the_buyer_never_meets_the_roster():
    """The condition the exec review put on showing a real client the room."""
    v = room.readiness_view(_ready(), room.CLIENT)
    names = [m["name"] for m in v["team"]]
    mails = [m["email"] for m in v["team"]]
    assert "Maya Okafor" not in names, "the roster walked out of the door with the name"
    assert "maya@roster.com" not in mails
    # …but the section still does its job: the team is real and coming together.
    assert "Assigned" in names and "Being assigned" in names
    # …and the producer, who is OURS, is still someone they can write to.
    assert "Jon Shipp" in names and "jon@chordential.com" in mails


def test_the_people_doing_the_work_still_see_each_other():
    for role in (room.TALENT, room.OPERATOR):
        v = room.readiness_view(_ready(), role)
        assert "Maya Okafor" in [m["name"] for m in v["team"]]


def test_an_unknown_role_gets_nothing():
    """Fails closed, like `caps_for` — a typo must not open the whole page."""
    assert room.readiness_view(_ready(), "cliennt") is None
    assert room.readiness_view(None, room.OPERATOR) is None


def test_the_lens_is_a_tag_not_a_label_match():
    """The rows are selected by `lens`, so renaming the copy cannot silently start
    leaking them. Rename every label and the subtraction must be unchanged."""
    ready = _ready()
    for r in ready["checklist"]:
        r["label"] = "Renamed " + r["label"]
    v = room.readiness_view(ready, room.TALENT)
    assert len(v["checklist"]) == 2, "a renamed commercial row reached a creator"


# --------------------------------------------------------------------------- #
# …and the layer, rendered.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "c.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.opportunity_ops import agreement_doc_for
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    jon = TestClient(app_mod.app)
    jon.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))

    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    conn = db.connect()
    opp_id = None
    for r in conn.execute("SELECT id FROM opportunities ORDER BY id").fetchall():
        if not db.list_meetings(conn, r["id"]):
            db.create_meeting(conn, opp_id=r["id"], start_at=past, status="ingested")
        conn.execute("UPDATE meetings SET start_at=?, status='ingested' WHERE opp_id=?",
                     (past, r["id"]))
        conn.commit()
        *_rest, doc, _d = agreement_doc_for(conn, r["id"])
        if getattr(getattr(doc, "agreement", None), "price_low", None):
            opp_id = r["id"]
            break
    if opp_id is None:
        pytest.skip("no signable demo deal")
    token = db.ensure_share_token(conn, opp_id)
    conn.close()

    client = TestClient(app_mod.app)
    client.post(f"/workspace/{token}/sign",
                data={"typed_name": "Marta Reyes", "signer_email": "marta@example.com",
                      "consent": "1"}, follow_redirects=False)
    jon.post(f"/opportunity/{opp_id}/countersign",
             data={"typed_name": "Jon Shipp", "consent": "1"}, follow_redirects=False)

    conn = db.connect()
    pid = db.project_for_opp(conn, opp_id)["id"]
    # A real name on the roster, so there is something for the gate to fail to hold.
    tid = conn.execute("INSERT INTO talent (name, email, created_at) VALUES (?,?,?)",
                       ("Maya Okafor", "maya@roster.com", "2026-08-28")).lastrowid
    conn.execute(
        "INSERT INTO assignments (project_id, talent_id, role, created_at) VALUES (?,?,?,?)",
        (pid, tid, "Composer", "2026-08-28"))
    conn.commit()
    ptok = db.get_talent_by_id(conn, tid)["portal_token"] if hasattr(
        db, "get_talent_by_id") else None
    conn.close()
    return jon, client, app_mod, db, pid, token, tid, ptok


def test_the_room_carries_the_layer_and_the_key(studio):
    _jon, client, _app, _db, pid, token, _tid, _ptok = studio
    page = client.get(f"/room/{pid}?k={token}").text
    assert 'data-sheet="checklist"' in page, "the C layer is not in the room"
    assert "<b>C</b>Checklist" in page, "no way to reach it with a mouse"
    assert "C checklist" in page, "the key is not named in the room's own hint line"
    assert 'toggleSheet("checklist")' in page, "C is not bound"
    assert "Production checklist" in page and "Where this stands" in page


def test_the_clients_layer_does_not_carry_the_roster(studio):
    """The whole reason this needed a subtraction rather than a move."""
    _jon, client, _app, _db, pid, token, _tid, _ptok = studio
    page = client.get(f"/room/{pid}?k={token}").text
    assert "Maya Okafor" not in page, "the composer's name reached the buyer"
    assert "maya@roster.com" not in page
    assert "Being assigned" in page, "…and the section stopped saying anything at all"


def test_the_studio_sees_the_whole_thing(studio):
    jon, _client, _app, _db, pid, _token, _tid, _ptok = studio
    page = jon.get(f"/room/{pid}").text
    assert 'data-sheet="checklist"' in page
    assert "Maya Okafor" in page, "the studio cannot see who it hired"


def test_the_composers_portal_subtracts_too(studio):
    """The path that goes AROUND `room_view`.

    `/creator/{token}` calls `_room_fields` directly, so anything added there arrives
    UNCUT unless this route applies the same subtraction. That is not hypothetical: it is
    how the buyer's budget and the roster would have reached a composer — not through the
    room, but past it.
    """
    from fastapi.testclient import TestClient
    _jon, _client, app_mod, db, _pid, _token, tid, _ptok = studio
    conn = db.connect()
    try:
        portal = db.ensure_talent_portal_token(conn, tid)
    finally:
        conn.close()
    assert portal, "no portal token to test with"
    maya = TestClient(app_mod.app)
    r = maya.get(f"/creator/{portal}")
    assert r.status_code == 200, f"the composer's portal did not render ({r.status_code})"
    page = r.text
    # The room is really there — otherwise the absences below prove nothing.
    assert 'data-sheet="checklist"' in page, "the composer got no checklist to subtract from"
    assert "Where this stands" in page
    # …and their copy has no commercial rows and no budget line.
    assert "Deposit received" not in page, "a creator was shown the buyer's deposit"
    assert "Procurement" not in page
    assert "<span class=\"k\">BUDGET</span>" not in page, (
        "a creator was shown what the client said they would spend")
