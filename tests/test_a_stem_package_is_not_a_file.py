"""A lane holds a folder, and the person who has to mix it can get the master.

Two from the delivery stage (operator, 2026-08-19):

  *"The mix ready stems, cues, cuts, mixes are going to be multiple files because they're
  stems. so each lane will need to be able to house multiple files, and i'll upload each
  lane separately or all lanes at once."*

  *"if i had individual people assuming the individual role its at this point where they
  will be invited to download the composer's approved final version and mix it, or edit
  it down to 30 or 15 sec cuts, and then re-upload them for my final approval before it
  gets pushed out to the client — i want to make sure that has been built."*

The first was a real dead end: a lane took ONE file and then closed itself, so a
twelve-stem package was a row reading "with the studio · under review" with one stem in
it and nowhere to put the other eleven.

The second was mostly built and missing its first step. The gate existed — a deliverable
lands PENDING, the studio publishes it, the client signs it off per asset, and delivery
only ships when every one is approved. What did not exist is the thing the mixer starts
from: the room knew which version was approved and offered no way to download it. They
were being asked to mix something they could only stream.
"""
import io
import os
import re

import pytest
from fastapi.testclient import TestClient

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent


@pytest.fixture()
def crew(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    import importlib
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db, production
    c = TestClient(app_mod.app)
    conn = db.connect()
    db.init_db(conn)
    pid = db.insert_project(conn, None, "The Larkspur Trust", "Fundraising film",
                            1000, 2000, ["Composer", "Mixer", "Music Editor"])

    def hire(name, mail, role):
        tid = db.insert_talent(conn, Talent(name=name, email=mail,
                                            disciplines=[MusicDiscipline.COMPOSITION]))
        db.add_assignment(conn, pid, role, tid)
        return db.ensure_talent_portal_token(conn, tid)

    toks = {"composer": hire("Ada Cheng", "ada@x.com", "Composer"),
            "mixer": hire("Ben Iyer", "ben@x.com", "Mixer"),
            "editor": hire("Cleo Ross", "cleo@x.com", "Music Editor")}
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v1 FINAL", "url": "/uploads/v1.wav",
                         "name": "Larkspur_Master_v1"}])
    db.update_delivery(conn, pid, "version_state", "v1 FINAL")
    production.set_creative_lock(conn, db, pid, version_n=1, by="Marta")
    ktok = db.rotate_share_token(conn, project_id=pid)
    conn.close()
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    return (c, db, pid, toks, ktok, (ADMIN_COOKIE, admin_cookie_value("letmein")))


def _send(c, pid, tok, label, names):
    files = [("file", (n, io.BytesIO(b"RIFF0000WAVE" + os.urandom(48)), "audio/wav"))
             for n in names]
    return c.post(f"/creator/{tok}/project/{pid}/deliverable",
                  data={"label": label}, files=files,
                  headers={"X-Requested-With": "fetch"}).json()


def _lane(page, asset):
    for m in re.finditer(r'<div class="deliv-row">(.*?)</form>', page, re.S):
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        if asset.lower() in txt.lower():
            return txt
    return ""


# ── a lane is a folder ──────────────────────────────────────────────────────────────
def test_a_lane_takes_a_whole_stem_package(crew):
    c, _db, pid, toks, _k, _a = crew
    got = _send(c, pid, toks["mixer"], "Mix-ready stem package",
                ["kick.wav", "snare.wav", "bass.wav", "gtr_l.wav", "gtr_r.wav", "vox.wav"])
    assert got["ok"] and got["added"] == 6 and got["count"] == 6, got


def test_a_lane_stays_open_for_the_rest(crew):
    """The defect exactly: the row closed on the first file."""
    c, _db, pid, toks, _k, _a = crew
    _send(c, pid, toks["mixer"], "Mix-ready stem package", ["kick.wav", "snare.wav"])
    later = _send(c, pid, toks["mixer"], "Mix-ready stem package",
                  ["strings.wav", "brass.wav", "fx.wav"])
    assert later["count"] == 5, later
    lane = _lane(c.get(f"/room/{pid}?t={toks['mixer']}").text, "Mix-ready stem package")
    assert "5 files with the studio" in lane, lane
    assert "Add more" in lane, "the lane closed itself again"


def test_each_lane_counts_only_its_own(crew):
    c, _db, pid, toks, _k, _a = crew
    _send(c, pid, toks["mixer"], "Mix-ready stem package", ["a.wav", "b.wav", "c.wav"])
    cuts = _send(c, pid, toks["editor"], ":30 / :15 / :06 cutdowns",
                 ["cut30.wav", "cut15.wav"])
    assert cuts["count"] == 2, "the count is a running total of everything ever sent"
    page = c.get(f"/room/{pid}?t={toks['editor']}").text
    assert "3 files with the studio" in _lane(page, "Mix-ready stem package")
    assert "2 files with the studio" in _lane(page, ":30 / :15")


def test_one_bad_file_does_not_lose_the_others(crew):
    """An empty file in a batch of twelve must not take the other eleven with it."""
    c, _db, pid, toks, _k, _a = crew
    files = [("file", ("kick.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(48)), "audio/wav")),
             ("file", ("empty.wav", io.BytesIO(b""), "audio/wav")),
             ("file", ("snare.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(48)), "audio/wav"))]
    got = c.post(f"/creator/{toks['mixer']}/project/{pid}/deliverable",
                 data={"label": "Mix-ready stem package"}, files=files,
                 headers={"X-Requested-With": "fetch"}).json()
    assert got["ok"] and got["added"] == 2, got


def test_nothing_at_all_is_still_refused(crew):
    c, _db, pid, toks, _k, _a = crew
    got = c.post(f"/creator/{toks['mixer']}/project/{pid}/deliverable",
                 data={"label": "Mix-ready stem package"},
                 files=[("file", ("empty.wav", io.BytesIO(b""), "audio/wav"))],
                 headers={"X-Requested-With": "fetch"})
    assert got.status_code == 400


def test_the_lanes_accept_multiple_and_offer_one_press_for_all(crew):
    c, _db, pid, toks, _k, _a = crew
    page = c.get(f"/room/{pid}?t={toks['mixer']}").text
    assert page.count('name="file" multiple') >= 4, (
        "a lane still takes one file at a time")
    assert 'id="deliv-all"' in page, (
        "no way to fill several lanes and send them together")


# ── the file the rest of the work is made from ──────────────────────────────────────
def test_the_mixer_can_download_the_approved_master(crew):
    """The missing first step. They are invited to mix a version they could only stream."""
    c, _db, pid, toks, _k, _a = crew
    for who in ("mixer", "editor", "composer"):
        page = c.get(f"/room/{pid}?t={toks[who]}").text
        assert "download the approved master" in page, f"the {who} cannot get the master"
        assert "v1 FINAL" in page


def test_the_client_is_not_handed_the_source(crew):
    """They receive what they signed off, in the package, once it is paid for."""
    c, _db, pid, _t, ktok, _a = crew
    page = c.get(f"/room/{pid}?k={ktok}").text
    assert "download the approved master" not in page


def test_the_studio_can_get_it_too(crew):
    c, _db, pid, _t, _k, admin = crew
    c.cookies.set(*admin)
    assert "download the approved master" in c.get(f"/room/{pid}").text


# ── the gate the operator asked me to confirm ───────────────────────────────────────
def test_every_delivered_file_waits_for_the_studio(crew):
    """*"re-upload them for my final approval before it gets pushed out to the client"* —
    the uniform publish gate, stems included."""
    c, db, pid, toks, ktok, _a = crew
    _send(c, pid, toks["mixer"], "Mix-ready stem package", ["a.wav", "b.wav"])
    conn = db.connect()
    d = db.get_delivery(conn, pid)
    conn.close()
    pend = d.get("pending_assets") or []
    assert len(pend) == 2, pend
    assert not (d.get("assets") or []), "a deliverable reached the ladder unvetted"
    client = c.get(f"/room/{pid}?k={ktok}").text
    for a in pend:
        assert a["filename"] not in client, "the client can already see an unvetted file"


def test_the_operator_sees_every_file_waiting(crew):
    c, db, pid, toks, _k, admin = crew
    _send(c, pid, toks["mixer"], "Mix-ready stem package",
          ["a.wav", "b.wav", "c.wav", "d.wav"])
    c.cookies.set(*admin)
    console = c.get(f"/project/{pid}/delivery").text
    conn = db.connect()
    pend = db.get_delivery(conn, pid).get("pending_assets") or []
    conn.close()
    missing = [a["filename"] for a in pend if a["filename"] not in console]
    assert not missing, f"the console hides {missing} — they cannot be vetted"


def test_the_hand_off_email_names_the_master_and_what_is_owed():
    """The approval email thanked everyone and said we would handle it. It is the moment
    the mixer and the editor are UP."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "delivery_ops.py").read_text(encoding="utf-8")
    body = src[src.index("Creative approved · {campaign}"):]
    body = body[:body.index("return approved_n")]
    assert "Still owed" in body, "the email does not say what is left to deliver"
    assert "Your room has it to download" in body, (
        "the email does not point at the master everything else is made from")
