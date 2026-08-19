"""Four things the review panel found, and the room now holds.

A composer, an audio engineer, a picture editor, an agency executive producer, a software
engineer and the executive team each reviewed THE room (ADR-0068). Four of their findings
were structural rather than cosmetic, and this file is what keeps them fixed.

1. **A note was free and got worked on anyway.** "Request changes" spent a revision round;
   a plain note spent nothing — and both reached the composer. That is an unpriced
   revision channel running beside a counter that reads "Round 1 of 2", and a buyer
   learns which lane is free within one project. Every note is now classified by a human
   before it becomes work, and an unclassified note is invisible to the creator.
2. **The timecode was a lie.** Frames were hardcoded to 24 and the hour to "00:", so every
   timecode was wrong on any 23.976 or 25 cut and wrong by an hour on anything mastered at
   01:00:00:00 — and it is the number people type into notes and cue sheets.
3. **A re-cut moved the ground and left the notes where they were.** A new cut replaced
   the old one silently; a note reading "hit the door slam" then pointed into the next
   shot. A new cut is now parked until a human states how far the picture moved.
4. **Approve did not say what it committed.** The EP would not press it: "approve for
   what — that the music is locked, that a round is burned, that I owe money?"
"""
import importlib

import pytest

pytest.importorskip("fastapi")

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 500


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "priced.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    from chordential_oia.web import app as app_mod
    db = app_mod.db
    with TestClient(app_mod.app) as jon:
        jon.post("/admin/login", data={"email": "", "password": "passphrase"},
                 follow_redirects=False)
        conn = db.connect()
        try:
            pid = conn.execute(
                "SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
            db.update_delivery(conn, pid, "versions",
                               [{"n": 1, "label": "v1 Concept", "url": "/uploads/v1.wav"}])
            ktok = db.ensure_project_share_token(conn, pid)
            tid = db.insert_talent(conn, Talent(
                name="Ada Verano", email="ada@example.com", rate=90.0,
                disciplines=[MusicDiscipline.COMPOSITION]))
            db.add_assignment(conn, pid, "Composer", tid)
            ttok = db.ensure_talent_portal_token(conn, tid)
        finally:
            conn.close()
        yield jon, app_mod, pid, tid, ttok, ktok


def _composer_notes(app_mod, tid):
    from chordential_oia.web.creator_routes import _creator_assignment_view
    conn = app_mod.db.connect()
    try:
        return _creator_assignment_view(conn, tid)[0]["feedback"]["notes"]
    finally:
        conn.close()


def _note(app_mod, pid, body="Darker at 0:12?", t=12.0):
    conn = app_mod.db.connect()
    try:
        return app_mod.db.add_review_comment(conn, pid, author="Marta", body=body,
                                             t_seconds=t, version="1")
    finally:
        conn.close()


def _rounds(app_mod, pid):
    conn = app_mod.db.connect()
    try:
        return int((app_mod.db.get_delivery(conn, pid) or {}).get("revisions_used") or 0)
    finally:
        conn.close()


# ── 1. a note is not work until a human has priced it ───────────────────────────────
def test_an_unpriced_note_never_reaches_the_composer(studio):
    _jon, app_mod, pid, tid, _t, _k = studio
    _note(app_mod, pid)
    assert _composer_notes(app_mod, tid) == [], (
        "the composer is being handed work nobody priced")


def test_the_studio_sees_it_waiting(studio):
    jon, app_mod, pid, _tid, _t, _k = studio
    _note(app_mod, pid)
    page = jon.get(f"/project/{pid}/delivery").text
    assert "to price" in page and "Darker at 0:12?" in page


def test_pricing_it_a_revision_releases_it_and_spends_a_round(studio):
    jon, app_mod, pid, tid, _t, _k = studio
    cid = _note(app_mod, pid)
    before = _rounds(app_mod, pid)
    assert jon.post(f"/project/{pid}/note/{cid}/disposition",
                    data={"how": "revision"}, follow_redirects=False).status_code == 303
    assert len(_composer_notes(app_mod, tid)) == 1
    assert _rounds(app_mod, pid) == before + 1


def test_a_conform_is_free(studio):
    jon, app_mod, pid, tid, _t, _k = studio
    cid = _note(app_mod, pid)
    before = _rounds(app_mod, pid)
    jon.post(f"/project/{pid}/note/{cid}/disposition", data={"how": "conform"},
             follow_redirects=False)
    assert len(_composer_notes(app_mod, tid)) == 1
    assert _rounds(app_mod, pid) == before, "a conform spent a round"


def test_out_of_scope_never_becomes_free_work(studio):
    """The whole commercial point: beyond the brief is quoted, not absorbed."""
    jon, app_mod, pid, tid, _t, _k = studio
    cid = _note(app_mod, pid, body="Can we also get a 60-second version?")
    before = _rounds(app_mod, pid)
    jon.post(f"/project/{pid}/note/{cid}/disposition", data={"how": "out_of_scope"},
             follow_redirects=False)
    assert _composer_notes(app_mod, tid) == []
    assert _rounds(app_mod, pid) == before


def test_reclassifying_cannot_spend_a_round_twice(studio):
    jon, app_mod, pid, _tid, _t, _k = studio
    cid = _note(app_mod, pid)
    base = _rounds(app_mod, pid)
    for how in ("revision", "revision", "conform", "revision"):
        jon.post(f"/project/{pid}/note/{cid}/disposition", data={"how": how},
                 follow_redirects=False)
    assert _rounds(app_mod, pid) == base + 1, "the ledger drifted on re-classification"


def test_only_the_studio_prices_a_note(studio):
    """This route is NOT gate-exempt, so a stranger meets the login — and, crucially,
    the note stays unpriced. The status is the gate's business; the state is the point."""
    from fastapi.testclient import TestClient
    _jon, app_mod, pid, tid, _t, _k = studio
    cid = _note(app_mod, pid)
    with TestClient(app_mod.app) as anon:
        r = anon.post(f"/project/{pid}/note/{cid}/disposition",
                      data={"how": "conform"}, follow_redirects=False)
    assert r.status_code != 200
    assert "/admin/login" in r.headers.get("location", "") or r.status_code == 404
    assert _composer_notes(app_mod, tid) == [], "a stranger priced a note into existence"


def test_an_unknown_disposition_is_refused(studio):
    jon, app_mod, pid, _tid, _t, _k = studio
    cid = _note(app_mod, pid)
    assert jon.post(f"/project/{pid}/note/{cid}/disposition",
                    data={"how": "free"}, follow_redirects=False).status_code == 400


# ── 2. the cut's own clock ──────────────────────────────────────────────────────────
def test_a_cut_carries_its_frame_rate_and_start(studio):
    jon, app_mod, pid, _tid, ttok, ktok = studio
    jon.post(f"/project/{pid}/review/picture",
             data={"k": ktok, "author": "Marta", "fps": "23.976",
                   "tc_start": "01:00:00:00"},
             files={"file": ("cut1.mp4", MP4, "video/mp4")}, follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        pic = app_mod.db.get_delivery(conn, pid)["picture"]
    finally:
        conn.close()
    assert pic["fps"] == "23.976" and pic["tc_start"] == "01:00:00:00"
    page = jon.get(f"/creator/{ttok}").text
    assert 'data-fps="23.976"' in page and 'data-tc0="01:00:00:00"' in page


def test_the_room_no_longer_hardcodes_24_frames(studio):
    jon, _app_mod, _pid, _tid, ttok, _k = studio
    page = jon.get(f"/creator/{ttok}").text
    assert "(x%1)*24" not in page, "frames are hardcoded again"


# ── 3. a re-cut moves the notes with the picture ────────────────────────────────────
def _upload_cut(jon, pid, ktok, name):
    return jon.post(f"/project/{pid}/review/picture",
                    data={"k": ktok, "author": "Marta"},
                    files={"file": (name, MP4, "video/mp4")}, follow_redirects=False)


def test_a_second_cut_is_parked_not_swapped(studio):
    jon, app_mod, pid, _tid, _t, ktok = studio
    _upload_cut(jon, pid, ktok, "cut1.mp4")
    _upload_cut(jon, pid, ktok, "cut2.mp4")
    conn = app_mod.db.connect()
    try:
        d = app_mod.db.get_delivery(conn, pid)
    finally:
        conn.close()
    assert d["picture"]["n"] == 1, "the room swapped the picture under everyone's notes"
    assert (d.get("conform_pending") or {}).get("n") == 2


def test_conforming_moves_every_note_with_the_picture(studio):
    jon, app_mod, pid, _tid, _t, ktok = studio
    _upload_cut(jon, pid, ktok, "cut1.mp4")
    _note(app_mod, pid, body="Hit the door slam", t=30.0)
    _upload_cut(jon, pid, ktok, "cut2.mp4")
    jon.post(f"/project/{pid}/conform", data={"offset": "4.5", "action": "apply"},
             follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        d = app_mod.db.get_delivery(conn, pid)
        at = app_mod.db.list_review_comments(conn, pid)[0]["t_seconds"]
    finally:
        conn.close()
    assert d["picture"]["n"] == 2 and d.get("conform_pending") in (None, {}, "")
    assert abs(at - 34.5) < 0.01, "the note stayed where the picture used to be"


def test_a_note_never_falls_off_the_front(studio):
    """A negative offset past the head clamps to 0 — a note nobody can find is worse
    than one in the wrong place."""
    jon, app_mod, pid, _tid, _t, ktok = studio
    _upload_cut(jon, pid, ktok, "cut1.mp4")
    _note(app_mod, pid, body="Early hit", t=2.0)
    _upload_cut(jon, pid, ktok, "cut2.mp4")
    jon.post(f"/project/{pid}/conform", data={"offset": "-30", "action": "apply"},
             follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        at = app_mod.db.list_review_comments(conn, pid)[0]["t_seconds"]
    finally:
        conn.close()
    assert at == 0.0


def test_a_parked_cut_can_be_discarded(studio):
    jon, app_mod, pid, _tid, _t, ktok = studio
    _upload_cut(jon, pid, ktok, "cut1.mp4")
    _upload_cut(jon, pid, ktok, "cut2.mp4")
    jon.post(f"/project/{pid}/conform", data={"action": "discard"},
             follow_redirects=False)
    conn = app_mod.db.connect()
    try:
        d = app_mod.db.get_delivery(conn, pid)
    finally:
        conn.close()
    assert d["picture"]["n"] == 1 and not d.get("conform_pending")


def test_only_the_studio_conforms(studio):
    """Gated, not exempt — a stranger meets the login, and the parked cut stays parked."""
    from fastapi.testclient import TestClient
    jon, app_mod, pid, _tid, _t, ktok = studio
    _upload_cut(jon, pid, ktok, "cut1.mp4")
    _upload_cut(jon, pid, ktok, "cut2.mp4")
    with TestClient(app_mod.app) as anon:
        r = anon.post(f"/project/{pid}/conform", data={"offset": "5"},
                      follow_redirects=False)
    assert r.status_code != 200
    conn = app_mod.db.connect()
    try:
        d = app_mod.db.get_delivery(conn, pid)
    finally:
        conn.close()
    assert d["picture"]["n"] == 1 and (d.get("conform_pending") or {}).get("n") == 2, (
        "a stranger conformed the room")


def test_the_creator_is_told_the_room_is_holding(studio):
    jon, app_mod, pid, _tid, ttok, ktok = studio
    _upload_cut(jon, pid, ktok, "cut1.mp4")
    _upload_cut(jon, pid, ktok, "cut2.mp4")
    page = jon.get(f"/creator/{ttok}").text
    assert "not\n      conformed yet" in page or "not conformed yet" in page.replace(
        "\n      ", " ")


# ── 4. approve says what it commits ─────────────────────────────────────────────────
def test_approve_states_its_consequence(studio):
    from fastapi.testclient import TestClient
    _jon, app_mod, pid, _tid, _t, ktok = studio
    with TestClient(app_mod.app) as client:
        page = client.get(f"/room/{pid}", params={"k": ktok}).text
    assert "What approving commits" in page
    assert "Locks" in page and "revision round" in page.lower()
    assert "confirm(" in page, "an irreversible commercial action with no confirm step"


def test_the_client_is_shown_what_they_are_licensing(studio):
    """"I cannot approve music whose usage I cannot see." The grant is shown; the FEE
    stays operator-only."""
    from fastapi.testclient import TestClient
    _jon, app_mod, pid, _tid, _t, ktok = studio
    with TestClient(app_mod.app) as client:
        page = client.get(f"/room/{pid}", params={"k": ktok}).text
    assert "You are licensing" in page
    assert "Worldwide" in page or "Perpetuity" in page
