"""The rejection nobody heard.

The master's send-back has carried a reason since ADR-0072: the take goes back with the
studio's words, the crew are emailed, and it lands in the room's event stream. That fix
was made because *"discarding cleared the submission, wrote a line into the project's own
updates, and told the composer NOTHING"*.

The DELIVERABLE gate — the mixer's stems, the editor's cutdowns — still worked the old
way. ``action=discard`` deleted the file from both copies, wrote a line into the project's
own updates that only the studio reads, and that was all. The mixer's stems simply stopped
existing, with no reason and no request for a replacement, on a lane they had been asked
to fill.

The same judgement deserves the same courtesy, and the reason is not politeness: a
rejection nobody hears cannot be acted on. So the deliverable send-back now takes a reason,
records it as an event the creator's room shows, and emails the person whose lane it is —
the mixer's stems go back to the mixer, not to everyone who has ever touched the project
(ADR-0075).
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    from chordential_oia.web.uploads import _persist_upload
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        tid = db.insert_talent(conn, Talent(
            name="Rae Okonkwo", email="rae@example.com", rate=80.0,
            disciplines=[MusicDiscipline.MIXING]))
        db.add_assignment(conn, pid, "Mixer", tid)
        _persist_upload(conn, "stem-1.wav", b"RIFFfake", "audio/wav")
        db.update_delivery(conn, pid, "pending_assets", [{
            # A real lane from the scoped list, and a MIXER-owned one: "Masters" is
            # the mixer's group, which is what makes the owner resolvable at all.
            "label": "Instrumental / TV mix", "url": "/uploads/stem-1.wav",
            "filename": "stem-1.wav", "orig": "TVmix_(Instrumental).wav",
            "kind": "audio", "by": "Rae Okonkwo", "at": "2026-08-20"}])
    finally:
        conn.close()
    return c, app_mod, db, pid


def _send_back(c, pid, note="The low end is fighting the VO. Pull 200Hz."):
    return c.post(f"/project/{pid}/delivery/asset/publish",
                  data={"filename": "stem-1.wav", "action": "send_back",
                        "origin": "room", "note": note},
                  headers={"X-Requested-With": "fetch"})


# ── the reason is recorded ──────────────────────────────────────────────────────────
def test_the_reason_reaches_the_creators_room(studio):
    """A project update is what the STUDIO reads. The event stream is what the creator
    sees — which is where the master's send-back has put its reason since ADR-0072."""
    c, _app, db, pid = studio
    assert _send_back(c, pid).json()["ok"] is True
    conn = db.connect()
    try:
        events = db.list_project_events(conn, pid, role="talent")
        client_sees = db.list_project_events(conn, pid, role="client")
    finally:
        conn.close()
    sent = [e for e in events if (e["kind"] or "") == "sent_back"]
    assert sent, "the send-back left no trace the creator can see"
    body = sent[0]["body"] or ""
    assert "Pull 200Hz" in body, "the reason was not carried"
    assert "TVmix_(Instrumental).wav" in body, "the creator cannot tell WHICH file"
    assert "talent" in (sent[0]["audience"] or ""), "the creator is not in the audience"
    assert not [e for e in client_sees if (e["kind"] or "") == "sent_back"], (
        "the BUYER can see us rejecting our own supplier's work")


def test_a_send_back_with_no_reason_says_so_rather_than_pretending(studio):
    c, _app, db, pid = studio
    _send_back(c, pid, note="")
    conn = db.connect()
    try:
        sent = [e for e in db.list_project_events(conn, pid, role="talent")
                if (e["kind"] or "") == "sent_back"]
    finally:
        conn.close()
    assert "No reason given." in (sent[0]["body"] or "")


def test_the_project_log_records_it_too(studio):
    c, _app, db, pid = studio
    _send_back(c, pid)
    conn = db.connect()
    try:
        text = " ".join((u["body"] or "") for u in db.list_updates(conn, pid))
    finally:
        conn.close()
    assert "Pull 200Hz" in text and "TVmix_(Instrumental).wav" in text


# ── and the person whose lane it is is emailed ──────────────────────────────────────
def test_the_lane_owner_is_emailed_and_not_the_whole_crew(studio, monkeypatch):
    """ADR-0075: the mixer's stems go back to the mixer. Broadcasting a rejection to
    everyone who has touched the project is how a private note becomes an audience."""
    from chordential_oia.web import project_routes
    sent = {}

    def _capture(fn, *a, **kw):
        sent.update(kw)
        sent["fn"] = getattr(fn, "__name__", "")

    monkeypatch.setattr(project_routes.signals, "fire_and_forget", _capture)
    c, _app, _db, pid = studio
    _send_back(c, pid)
    assert sent.get("fn") == "_notify_assigned_creators", "nobody was told"
    assert sent.get("only_craft") == "mixer", (
        f"addressed to {sent.get('only_craft')!r} instead of the lane's owner")
    assert "Pull 200Hz" in sent.get("body_text", "")
    assert "TVmix_(Instrumental).wav" in sent.get("subject", "")


def test_the_bytes_still_go(studio):
    """Send-back must keep deleting BOTH copies — a rejected file that still downloads
    was the defect fixed alongside this one."""
    from chordential_oia.web.uploads import media_present
    c, _app, db, pid = studio
    _send_back(c, pid)
    conn = db.connect()
    try:
        assert not media_present(conn, "stem-1.wav")
        assert (db.get_delivery(conn, pid).get("pending_assets") or []) == []
    finally:
        conn.close()


def test_discard_still_works_and_does_the_same_thing(studio):
    """The old verb stays wired — a submission that vanishes without a word is not a
    behaviour worth keeping a door open for, so `discard` now sends back too."""
    c, _app, db, pid = studio
    r = c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": "stem-1.wav", "action": "discard", "origin": "room",
                     "note": "Wrong session."},
               headers={"X-Requested-With": "fetch"})
    assert r.json()["ok"] is True
    conn = db.connect()
    try:
        sent = [e for e in db.list_project_events(conn, pid, role="talent")
                if (e["kind"] or "") == "sent_back"]
    finally:
        conn.close()
    assert sent and "Wrong session." in (sent[0]["body"] or "")


def test_publishing_is_untouched(studio):
    """The other half of the gate must still do exactly what it did."""
    c, _app, db, pid = studio
    r = c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": "stem-1.wav", "action": "publish", "origin": "room"},
               headers={"X-Requested-With": "fetch"})
    assert r.json()["ok"] is True
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, pid)
        assert any(a.get("filename") == "stem-1.wav"
                   for a in (delivery.get("assets") or []))
        assert not [e for e in db.list_project_events(conn, pid, role="talent")
                    if (e["kind"] or "") == "sent_back"]
    finally:
        conn.close()


def test_the_room_asks_for_the_reason_before_sending_back(studio):
    from pathlib import Path
    _c, app_mod, _db, _pid = studio
    tpl = (Path(app_mod.__file__).parent / "templates" / "creator_portal.html"
           ).read_text(encoding="utf-8")
    assert 'value="send_back"' in tpl, "the room still posts the silent verb"
    assert "data-sendback" in tpl and "What needs another pass?" in tpl, (
        "the room sends it back without asking why")


# ── and the hand-off that had never once fired ──────────────────────────────────────
def test_the_owner_of_a_lane_can_actually_be_resolved():
    """Found while wiring the send-back, and older than it.

    `deliverable_owner` keys off (asset, GROUP) — "Instrumental / TV mix" is the mixer's
    because it sits in *Masters*. Both callers passed the lane's LABEL only, which is the
    asset with no group, so every lookup returned "" and the code guarded by it did
    nothing at all. The ADR-0075 hand-off — telling the editor the mix they cut from has
    landed — could therefore never have fired since the day it shipped.
    """
    from chordential_oia.delivery import deliverable_owner, owner_for_asset_label
    assert deliverable_owner("Instrumental / TV mix") == "", (
        "the old one-argument call — kept here as the evidence it cannot work")
    assert deliverable_owner("Instrumental / TV mix", "Masters") == "mixer"


def test_the_editor_is_told_when_the_mix_they_cut_from_lands(studio, monkeypatch):
    from chordential_oia.web import project_routes
    sent = []
    monkeypatch.setattr(project_routes.signals, "fire_and_forget",
                        lambda fn, *a, **kw: sent.append(kw))
    c, _app, _db, pid = studio
    c.post(f"/project/{pid}/delivery/asset/publish",
           data={"filename": "stem-1.wav", "action": "publish", "origin": "room"},
           headers={"X-Requested-With": "fetch"})
    crafts = [s.get("only_craft") for s in sent]
    assert "editor" in crafts, (
        f"publishing the mix told nobody downstream (fired: {crafts})")
