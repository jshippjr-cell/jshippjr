"""Three crafts, in order — and the room knows which.

The operator's production model, stated 2026-08-19:

  *"The Composer writes the music, and upload the stems. The audio Engineer or mixer
  mixes the composer's work and makes it good for VO, instrumental, TV Mix, loudness
  codec for a specific medium specified by client. Editor makes the cutdowns and the
  verticals from the mix engineer's final work."*

That is a CHAIN, not three parallel piles. Until now every assigned creator saw every
lane with an open upload box on all of them — so the editor was invited to deliver
cutdowns of a mix that did not exist yet, and an empty box on work nobody can start reads
as a missed deadline rather than as a queue.

The mapping lives in `delivery.py` (ADR-0002: a fact about how the studio makes records
is not template logic), and three surfaces read it: whose lane a row is, whether that lane
is startable, and who gets the "you're up" email when the thing they work from lands.
"""
import io
import os
import re

import pytest
from fastapi.testclient import TestClient

from chordential_oia.delivery import deliverable_owner, owed_after, role_key
from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent


# ── the model itself ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("written,craft", [
    ("Composer", "composer"), ("Arranger", "composer"),
    ("Mixer", "mixer"), ("Audio Engineer", "mixer"), ("Mix Engineer", "mixer"),
    ("Music Editor", "editor"), ("Editor", "editor"),
    ("Producer", ""), ("", ""),
])
def test_one_craft_is_written_several_ways(written, craft):
    """"Mixer", "Audio Engineer" and "Mix engineer" are one person's job."""
    assert role_key(written) == craft


@pytest.mark.parametrize("asset,group,owner", [
    ("Instrumental / TV mix", "Masters", "mixer"),
    (":30 / :15 / :06 cutdowns", "Cutdowns", "editor"),
    ("9:16 vertical cuts (loudness-prepped)", "Social verticals", "editor"),
    ("Mix-ready stem package", "Production assets", "composer"),
    ("Cue sheet & rights certificate", "Documentation", ""),
])
def test_each_lane_has_an_owner(asset, group, owner):
    assert deliverable_owner(asset, group) == owner


def test_only_the_editor_waits_on_anyone():
    """The mixer works from the approved master, which exists the moment the client
    locks it. The editor works from the mixer's finished mix."""
    assert owed_after("editor") == "mixer"
    assert owed_after("mixer") == ""
    assert owed_after("composer") == ""


# ── the room ────────────────────────────────────────────────────────────────────────
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
            # written the OTHER way, on purpose
            "mixer": hire("Ben Iyer", "ben@x.com", "Audio Engineer"),
            "editor": hire("Cleo Ross", "cleo@x.com", "Music Editor")}
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v1 FINAL", "url": "/uploads/v1.wav"}])
    db.update_delivery(conn, pid, "version_state", "v1 FINAL")
    production.set_creative_lock(conn, db, pid, version_n=1, by="Marta")
    ktok = db.rotate_share_token(conn, project_id=pid)
    conn.close()
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    return c, db, pid, toks, ktok, (ADMIN_COOKIE, admin_cookie_value("letmein"))


def _lanes(c, pid, tok):
    page = c.get(f"/room/{pid}?t={tok}").text
    out = {}
    for m in re.finditer(r'<div class="deliv-row([^"]*)">(.*?)</div>', page, re.S):
        blk = m.group(2)
        asset = re.search(r"<b>(.*?)</b>", blk)
        if not asset:
            continue
        out[asset.group(1)] = {
            "owner": (re.search(r'class="lane-owner[^"]*">(.*?)<', blk) or [None, ""])[1]
            if re.search(r'class="lane-owner[^"]*">(.*?)<', blk) else "",
            "can_upload": 'class="deliv-form"' in blk,
            "waiting": bool(re.search(r'class="lane-wait">', blk)),
        }
    return out


def test_each_craft_is_offered_only_its_own_lanes(crew):
    c, _db, pid, toks, _k, _a = crew
    comp = _lanes(c, pid, toks["composer"])
    assert comp["Mix-ready stem package"]["can_upload"]
    assert not comp["Instrumental / TV mix"]["can_upload"], (
        "the composer is offered the mixer's lane")
    mix = _lanes(c, pid, toks["mixer"])
    assert mix["Instrumental / TV mix"]["can_upload"]
    assert not mix["Mix-ready stem package"]["can_upload"]


def test_everyone_still_sees_the_whole_delivery(crew):
    """Subtracting the box is not subtracting the row — the editor needs to know a mix
    is coming, and the composer needs to see what their stems are for."""
    c, _db, pid, toks, _k, _a = crew
    for who in ("composer", "mixer", "editor"):
        lanes = _lanes(c, pid, toks[who])
        assert len(lanes) == 4, (who, lanes)


def test_a_lane_says_whose_it_is(crew):
    c, _db, pid, toks, _k, _a = crew
    mix = _lanes(c, pid, toks["mixer"])
    assert mix["Instrumental / TV mix"]["owner"] == "yours"
    assert mix["Mix-ready stem package"]["owner"] == "composer"
    assert mix[":30 / :15 / :06 cutdowns"]["owner"] == "editor"


def test_the_editor_is_not_asked_for_cutdowns_of_a_mix_that_does_not_exist(crew):
    c, _db, pid, toks, _k, _a = crew
    ed = _lanes(c, pid, toks["editor"])
    for lane in (":30 / :15 / :06 cutdowns", "9:16 vertical cuts (loudness-prepped)"):
        assert ed[lane]["waiting"], f"{lane} looks startable"
        assert not ed[lane]["can_upload"]


def test_publishing_the_mix_opens_the_editors_lanes(crew):
    c, db, pid, toks, _k, admin = crew
    files = [("file", ("tvmix.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(40)),
                       "audio/wav"))]
    c.post(f"/creator/{toks['mixer']}/project/{pid}/deliverable",
           data={"label": "Instrumental / TV mix"}, files=files,
           headers={"X-Requested-With": "fetch"})
    # still blocked while it is only WITH the studio — unvetted work is not a hand-off
    assert _lanes(c, pid, toks["editor"])[":30 / :15 / :06 cutdowns"]["waiting"]
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/delivery/asset/publish",
           data={"filename": pend[0]["filename"], "action": "publish"},
           follow_redirects=False)
    c.cookies.clear()
    ed = _lanes(c, pid, toks["editor"])
    assert ed[":30 / :15 / :06 cutdowns"]["can_upload"], "the editor is still blocked"
    assert not ed[":30 / :15 / :06 cutdowns"]["waiting"]


def test_the_editor_is_handed_the_mix_not_just_told_about_it(crew):
    c, db, pid, toks, _k, admin = crew
    c.post(f"/creator/{toks['mixer']}/project/{pid}/deliverable",
           data={"label": "Instrumental / TV mix"},
           files=[("file", ("tvmix.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(40)),
                            "audio/wav"))],
           headers={"X-Requested-With": "fetch"})
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/delivery/asset/publish",
           data={"filename": pend[0]["filename"], "action": "publish"},
           follow_redirects=False)
    c.cookies.clear()
    page = c.get(f"/room/{pid}?t={toks['editor']}").text
    assert "Your cutdowns come from the published mix" in page
    assert "tvmix.wav" in page, (
        "the mix downloads under its storage name; the next person opens twelve of "
        "those to find out which is the kick")


def test_the_client_is_handed_none_of_the_working_files(crew):
    c, db, pid, toks, ktok, admin = crew
    c.post(f"/creator/{toks['mixer']}/project/{pid}/deliverable",
           data={"label": "Instrumental / TV mix"},
           files=[("file", ("tvmix.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(40)),
                            "audio/wav"))],
           headers={"X-Requested-With": "fetch"})
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/delivery/asset/publish",
           data={"filename": pend[0]["filename"], "action": "publish"},
           follow_redirects=False)
    c.cookies.clear()
    page = c.get(f"/room/{pid}?k={ktok}").text
    assert "tvmix.wav" not in page and "download the approved master" not in page


def test_the_hand_off_email_goes_to_the_craft_that_is_up():
    """Not to everyone who has ever touched the project — and once per lane, not once
    per file, or twelve stems send twelve emails."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "project_routes.py").read_text(encoding="utf-8")
    body = src[src.index("def delivery_publish_asset"):]
    body = body[:body.index("@router.post", body.index("was_published"))]
    assert "only_craft=craft" in body, "the hand-off emails the whole crew"
    assert "was_published" in body, (
        "no first-file guard — publishing a stem package would send an email per stem")


def test_an_unmapped_room_still_offers_every_lane(crew):
    """A project whose roles are none of the three crafts must not become a room where
    nobody can upload anything. No hats known → every lane, as before."""
    c, db, pid, _t, _k, _a = crew
    conn = db.connect()
    tid = db.insert_talent(conn, Talent(name="Dee", email="dee@x.com",
                                        disciplines=[MusicDiscipline.COMPOSITION]))
    db.add_assignment(conn, pid, "Producer", tid)
    tok = db.ensure_talent_portal_token(conn, tid)
    conn.close()
    lanes = _lanes(c, pid, tok)
    assert lanes["Mix-ready stem package"]["can_upload"]
    assert lanes["Instrumental / TV mix"]["can_upload"]


def test_the_room_guides_and_the_taste_gate_decides(crew):
    """A deliberate looseness, stated so nobody "fixes" it later.

    The ROUTE does not refuse an upload into a lane the caller's craft does not own. One
    person wearing three hats is the normal case in a small studio — it is exactly how
    this was being tested — and a hard refusal would block a composer who also mixes, or
    the studio uploading on someone's behalf. The room GUIDES by offering the boxes that
    are yours; nothing reaches the client either way until the studio publishes it, which
    is where a mislabelled file gets caught. "The machine proposes, Jon disposes."
    """
    c, db, pid, toks, _k, _a = crew
    got = c.post(f"/creator/{toks['mixer']}/project/{pid}/deliverable",
                 data={"label": "Mix-ready stem package"},
                 files=[("file", ("bass.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(40)),
                                  "audio/wav"))],
                 headers={"X-Requested-With": "fetch"}).json()
    assert got["ok"], "the route refuses a hat the room did not offer — see the docstring"
    conn = db.connect()
    d = db.get_delivery(conn, pid)
    conn.close()
    assert len(d.get("pending_assets") or []) == 1
    assert not (d.get("assets") or []), "it reached the client without the studio"
