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
    got = _send(c, pid, toks["composer"], "Mix-ready stem package",
                ["kick.wav", "snare.wav", "bass.wav", "gtr_l.wav", "gtr_r.wav", "vox.wav"])
    assert got["ok"] and got["added"] == 6 and got["count"] == 6, got


def test_a_lane_stays_open_for_the_rest(crew):
    """The defect exactly: the row closed on the first file. Sent from the COMPOSER's
    room — the stem package is theirs to bounce (ADR-0075)."""
    c, _db, pid, toks, _k, _a = crew
    _send(c, pid, toks["composer"], "Mix-ready stem package", ["kick.wav", "snare.wav"])
    later = _send(c, pid, toks["composer"], "Mix-ready stem package",
                  ["strings.wav", "brass.wav", "fx.wav"])
    assert later["count"] == 5, later
    lane = _lane(c.get(f"/room/{pid}?t={toks['composer']}").text, "Mix-ready stem package")
    assert "5 files with the studio" in lane, lane
    assert "Add more" in lane, "the lane closed itself again"


def test_each_lane_counts_only_its_own(crew):
    c, _db, pid, toks, _k, _a = crew
    _send(c, pid, toks["composer"], "Mix-ready stem package", ["a.wav", "b.wav", "c.wav"])
    cuts = _send(c, pid, toks["editor"], ":30 / :15 / :06 cutdowns",
                 ["cut30.wav", "cut15.wav"])
    assert cuts["count"] == 2, "the count is a running total of everything ever sent"
    page = c.get(f"/room/{pid}?t={toks['composer']}").text
    assert "3 files with the studio" in _lane(page, "Mix-ready stem package")
    page = c.get(f"/room/{pid}?t={toks['editor']}").text
    assert "2 files with the studio" in _lane(page, ":30 / :15")


def test_one_bad_file_does_not_lose_the_others(crew):
    """An empty file in a batch of twelve must not take the other eleven with it."""
    c, _db, pid, toks, _k, _a = crew
    files = [("file", ("kick.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(48)), "audio/wav")),
             ("file", ("empty.wav", io.BytesIO(b""), "audio/wav")),
             ("file", ("snare.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(48)), "audio/wav"))]
    got = c.post(f"/creator/{toks['composer']}/project/{pid}/deliverable",
                 data={"label": "Mix-ready stem package"}, files=files,
                 headers={"X-Requested-With": "fetch"}).json()
    assert got["ok"] and got["added"] == 2, got


def test_nothing_at_all_is_still_refused(crew):
    c, _db, pid, toks, _k, _a = crew
    got = c.post(f"/creator/{toks['composer']}/project/{pid}/deliverable",
                 data={"label": "Mix-ready stem package"},
                 files=[("file", ("empty.wav", io.BytesIO(b""), "audio/wav"))],
                 headers={"X-Requested-With": "fetch"})
    assert got.status_code == 400


def test_every_lane_offered_accepts_many_files(crew):
    """Asserted as a PROPERTY, not a count: lanes became role-scoped (ADR-0075), so how
    many boxes a given room shows depends on who is looking."""
    c, _db, pid, toks, _k, admin = crew
    c.cookies.set(*admin)                       # the studio sees every lane
    page = c.get(f"/room/{pid}").text
    boxes = re.findall(r'<input type="file" name="file"([^>]*)>', page)
    # Two lanes are open at this point: the composer's stems and the mixer's TV mix. The
    # editor's two are legitimately closed — they wait on the mix (ADR-0075).
    assert len(boxes) == 2, boxes
    assert all("multiple" in b for b in boxes), (
        f"a lane still takes one file at a time: {boxes}")
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
    _send(c, pid, toks["composer"], "Mix-ready stem package", ["a.wav", "b.wav"])
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
    _send(c, pid, toks["composer"], "Mix-ready stem package",
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


# ── the lane you can still add to ───────────────────────────────────────────────────
def test_the_lane_never_deletes_its_own_form():
    """*"once i click upload in the lane it doesnt allow me to upload more. what if i
    missed 1 file and i need to add it?"* (operator, 2026-08-19).

    The in-page handler deleted the form on success and appended its own badge — so the
    first upload closed the lane, and the row showed TWO badges: the server's count and
    the JS's bare one. The server-rendered template had already been taught to keep the
    lane open; the JS had not, so a reload showed the right thing and the page you were
    standing on did not.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "templates" / "creator_portal.html").read_text(encoding="utf-8")
    fn = src[src.index("document.querySelectorAll(\"form.deliv-form\")"):]
    # end at the NEXT block — the vetting handler legitimately removes its own two
    # buttons once a file is published, and it sits between here and the drop code
    fn = fn[:fn.index("Vetting a file WITHOUT leaving the sheet")]
    assert "f.remove()" not in fn, "the lane deletes its own upload form again"
    assert 'btn.textContent = "Add more"' in fn, (
        "the lane does not invite the file you missed")
    assert "row.querySelector(\".lane-count\")" in fn, (
        "the handler makes a second badge instead of updating the one that is there")


def test_the_lane_lists_what_is_in_it(crew):
    """A count says something landed. It does not say whether all twelve stems did."""
    c, _db, pid, toks, _k, _a = crew
    _send(c, pid, toks["composer"], "Mix-ready stem package",
          ["kick.wav", "snare.wav", "bass.wav"])
    page = c.get(f"/room/{pid}?t={toks['composer']}").text
    lane = re.search(r'data-lane="Mix-ready stem package".*?</ul>', page, re.S)
    assert lane, "the lane renders no file list"
    names = re.findall(r'download="([^"]+)"', lane.group(0))
    assert names == ["kick.wav", "snare.wav", "bass.wav"], names


def test_the_file_you_missed_joins_the_list(crew):
    c, _db, pid, toks, _k, _a = crew
    _send(c, pid, toks["composer"], "Mix-ready stem package", ["kick.wav", "snare.wav"])
    _send(c, pid, toks["composer"], "Mix-ready stem package", ["perc.wav"])
    page = c.get(f"/room/{pid}?t={toks['composer']}").text
    lane = re.search(r'data-lane="Mix-ready stem package".*?</ul>', page, re.S)
    assert re.findall(r'download="([^"]+)"', lane.group(0)) == \
        ["kick.wav", "snare.wav", "perc.wav"]
    assert 'class="deliv-form"' in lane.group(0), "the lane closed after the first upload"
    assert "Add more" in lane.group(0)


def test_the_upload_reports_the_names_it_took(crew):
    """So the page can list them without a reload."""
    c, _db, pid, toks, _k, _a = crew
    got = _send(c, pid, toks["composer"], "Mix-ready stem package", ["a.wav", "b.wav"])
    assert got["names"] == ["a.wav", "b.wav"], got


def test_only_your_startable_lanes_take_a_drop(crew):
    """`data-drop` is set by the SERVER, so a drag cannot offer a lane the room has
    already said belongs to someone else or is waiting on the mix."""
    c, _db, pid, toks, _k, _a = crew
    page = c.get(f"/room/{pid}?t={toks['editor']}").text
    lanes = dict(re.findall(r'data-lane="([^"]+)"([^>]*)>', page))
    assert "data-drop" not in lanes[":30 / :15 / :06 cutdowns"], (
        "a blocked lane accepts a drop")
    assert "data-drop" not in lanes["Mix-ready stem package"], (
        "the editor can drop stems into the composer's lane")
    comp = dict(re.findall(r'data-lane="([^"]+)"([^>]*)>',
                           c.get(f"/room/{pid}?t={toks['composer']}").text))
    assert 'data-drop="1"' in comp["Mix-ready stem package"]


def test_a_drop_on_a_lane_is_not_read_as_a_new_master():
    """The page-wide drop handler behind the take uploader would otherwise take a stem
    dropped on a lane and submit it as the next version."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "templates" / "creator_portal.html").read_text(encoding="utf-8")
    fn = src[src.index("DROP FILES ON A LANE"):]
    fn = fn[:fn.index("…and one press for everything")]
    assert "e.stopPropagation()" in fn, "a lane drop bubbles to the take uploader"
    assert "dragReset()" in fn, "the page-wide drop veil is left standing after a drop"


# ── and something has to SAY they are waiting ───────────────────────────────────────
def _badge(page):
    m = re.search(r'id="queue-badge"[^>]*style="display:([a-z-]+)[^>]*>([^<]*)<', page)
    return None if not m else (m.group(1), m.group(2).strip())


def test_delivered_files_raise_the_badge(crew):
    """*"The files have been uploaded for the studio to review.. but the dashboard
    doesnt tell me there are files to review"* (operator, 2026-08-19).

    The gate counted the composer's TAKE and not their deliverables, though both wait
    for the same press — so a stem package could sit in the building with nothing on any
    page saying so. Counted per FILE: twelve stems are twelve things to listen to.
    """
    c, _db, pid, toks, _k, admin = crew
    c.cookies.set(*admin)
    assert _badge(c.get("/dashboard").text) == ("none", "")
    c.cookies.clear()
    _send(c, pid, toks["composer"], "Mix-ready stem package",
          ["kick.wav", "snare.wav", "bass.wav", "perc.wav"])
    c.cookies.set(*admin)
    assert _badge(c.get("/dashboard").text) == ("inline-block", "4")


def test_the_queue_has_a_card_for_them(crew):
    c, _db, pid, toks, _k, admin = crew
    _send(c, pid, toks["composer"], "Mix-ready stem package", ["kick.wav", "snare.wav"])
    c.cookies.set(*admin)
    q = c.get("/queue").text
    assert "deliverable files to vet" in q, "the queue never mentions them"
    assert "Mix-ready stem package (2)" in q, "the card does not say what or how many"


def test_the_room_says_what_is_waiting_on_you(crew):
    """*"nor do i see anything to review when i log into 'the room'"*. The whisper read
    "In delivery: 0 of 4 assets in" — true, and useless, while four stems sat unvetted."""
    c, _db, pid, toks, _k, admin = crew
    _send(c, pid, toks["composer"], "Mix-ready stem package", ["a.wav", "b.wav", "c.wav"])
    c.cookies.set(*admin)
    page = c.get(f"/room/{pid}").text
    whisper = re.search(r'class="whisper sr-whisper">.*?<span>(.*?)</span>', page, re.S)
    said = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", whisper.group(1))).strip()
    assert "3 deliverable files waiting on your call" in said, said


def test_the_studio_can_vet_a_file_where_it_sits(crew):
    """Deliverables waited for the same press as the master and could only be pressed on
    the console — so the studio opened the room, found nothing to review, and the files
    stayed put."""
    c, db, pid, toks, _k, admin = crew
    _send(c, pid, toks["composer"], "Mix-ready stem package", ["a.wav", "b.wav"])
    c.cookies.set(*admin)
    page = c.get(f"/room/{pid}").text
    assert page.count('class="lf-gate"') == 2, "the room offers no gate on the files"
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    r = c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": pend[0]["filename"], "action": "publish",
                     "origin": "room"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/room/{pid}")
    conn = db.connect()
    d = db.get_delivery(conn, pid)
    conn.close()
    assert len(d["assets"]) == 1 and len(d["pending_assets"]) == 1


def test_the_console_still_returns_to_the_console(crew):
    c, db, pid, toks, _k, admin = crew
    _send(c, pid, toks["composer"], "Mix-ready stem package", ["a.wav"])
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    c.cookies.set(*admin)
    r = c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": pend[0]["filename"], "action": "publish"},
               follow_redirects=False)
    assert r.headers["location"] == f"/project/{pid}/delivery#assets"


def test_only_the_studio_is_offered_the_file_gate(crew):
    c, _db, pid, toks, ktok, _a = crew
    _send(c, pid, toks["composer"], "Mix-ready stem package", ["a.wav"])
    for who, page in (("composer", c.get(f"/room/{pid}?t={toks['composer']}").text),
                      ("client", c.get(f"/room/{pid}?k={ktok}").text)):
        assert 'class="lf-gate"' not in page, f"the {who} can publish their own work"
