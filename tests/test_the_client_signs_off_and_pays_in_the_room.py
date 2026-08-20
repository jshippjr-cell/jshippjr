"""The last stage, in the room: sign off each deliverable, settle, download.

Four reports from one pass (operator, 2026-08-19):

  *"Everytime i approve a stem inside the room within the v Takes window it closes the
  window and i have to open it back up to approve another one."*

  *"The client view of takes has text that is not applicable to them."*

  *"The studio approved deliverables to push to the client but nothing went to the client
  in the room view. also the room view still has an approve v2 button active and the
  client already approved v2 it should grey out and text change."*

  *"We should be at the stage where the client clicks approve on the deliverables and
  they get prompted to pay the remaining deposit to release the full package."*

The third is the substantial one. `deliverables` is the LANE view — specs, whose craft,
upload boxes — and `room_view` subtracts it from the buyer entirely, correctly. What was
missing is the other half: the same scoped list with its per-asset approval state, which
is what the client actually does at this stage. It comes from ONE derivation
(`delivery_ops.scoped_signoff`) that the console, the delivery portal and the room all
read, so they cannot come to disagree about whether a delivery is finished.
"""
import io
import os
import re

import pytest
from fastapi.testclient import TestClient

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent


@pytest.fixture()
def stage(tmp_path, monkeypatch):
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
                            1000, 2000, ["Composer"])
    tid = db.insert_talent(conn, Talent(name="Ada Cheng", email="ada@x.com",
                                        disciplines=[MusicDiscipline.COMPOSITION]))
    db.add_assignment(conn, pid, "Composer", tid)
    ttok = db.ensure_talent_portal_token(conn, tid)
    ktok = db.rotate_share_token(conn, project_id=pid)
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v1 FINAL", "url": "/uploads/v1.wav"}])
    db.update_delivery(conn, pid, "version_state", "v1 FINAL")
    production.set_creative_lock(conn, pid and db, pid, version_n=1, by="Marta Ruiz")
    conn.close()
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    return c, db, pid, ttok, ktok, (ADMIN_COOKIE, admin_cookie_value("letmein"))


def _words(page):
    body = page[page.index("<body>"):]
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", body, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def _deliver_and_publish(c, db, pid, ttok, admin, label="Instrumental / TV mix"):
    c.post(f"/creator/{ttok}/project/{pid}/deliverable", data={"label": label},
           files=[("file", ("tvmix.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(40)),
                            "audio/wav"))],
           headers={"X-Requested-With": "fetch"})
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/delivery/asset/publish",
           data={"filename": pend[0]["filename"], "action": "publish", "origin": "room"},
           follow_redirects=False)
    c.cookies.clear()


# ── 1. vetting a file must not shut the window you are vetting it in ────────────────
def test_approving_a_stem_answers_in_place(stage):
    c, db, pid, ttok, _k, admin = stage
    c.post(f"/creator/{ttok}/project/{pid}/deliverable",
           data={"label": "Mix-ready stem package"},
           files=[("file", ("kick.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(40)),
                            "audio/wav"))],
           headers={"X-Requested-With": "fetch"})
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    c.cookies.set(*admin)
    r = c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": pend[0]["filename"], "action": "publish",
                     "origin": "room"},
               headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200 and r.json()["ok"], (
        "the press still answers with a redirect, which reloads the room and shuts the "
        "Takes sheet")


def test_a_plain_press_still_redirects(stage):
    """No JS is not a broken room."""
    c, db, pid, ttok, _k, admin = stage
    c.post(f"/creator/{ttok}/project/{pid}/deliverable",
           data={"label": "Mix-ready stem package"},
           files=[("file", ("kick.wav", io.BytesIO(b"RIFF0000WAVE" + os.urandom(40)),
                            "audio/wav"))],
           headers={"X-Requested-With": "fetch"})
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    c.cookies.set(*admin)
    r = c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": pend[0]["filename"], "action": "publish",
                     "origin": "room"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/room/{pid}")


def test_the_row_is_updated_rather_than_the_page_reloaded():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
           / "web" / "templates" / "creator_portal.html").read_text(encoding="utf-8")
    fn = src[src.index('document.querySelectorAll("form.lf-gate")'):]
    fn = fn[:fn.index("DROP FILES ON A LANE")]
    assert "e.preventDefault()" in fn and "X-Requested-With" in fn
    assert "closeAllSheets" not in fn, "vetting a file still shuts the sheet"


# ── 2. the client's Takes window is theirs ──────────────────────────────────────────
@pytest.mark.parametrize("line", [
    "yours alone, never the client's",     # the composer's private shelf, labelled
    "Now deliver the remaining assets",    # the loading dock
    "A lane takes as many files",          # how to upload into it
])
def test_the_client_is_not_shown_the_loading_dock(stage, line):
    c, _db, pid, _t, ktok, _a = stage
    assert line.lower() not in _words(c.get(f"/room/{pid}?k={ktok}").text).lower()


def test_the_composer_keeps_all_of_it(stage):
    c, _db, pid, ttok, _k, _a = stage
    words = _words(c.get(f"/room/{pid}?t={ttok}").text)
    assert "yours alone, never the client's" in words
    assert "Now deliver the remaining assets" in words


# ── 3. what the client sees at this stage ───────────────────────────────────────────
def test_a_published_deliverable_reaches_the_clients_room(stage):
    """*"The studio approved deliverables to push to the client but nothing went to the
    client in the room view."*"""
    c, db, pid, ttok, ktok, admin = stage
    # Before anything is published the list is still there — it is what they will
    # RECEIVE — but nothing in it is signable yet.
    before = c.get(f"/room/{pid}?k={ktok}").text
    assert "Sign off your deliverables" in before
    assert 'name="action" value="approve"' not in before
    assert "not delivered yet" in before
    _deliver_and_publish(c, db, pid, ttok, admin)
    page = c.get(f"/room/{pid}?k={ktok}").text
    assert "Sign off your deliverables" in page
    assert "Instrumental / TV mix" in page
    assert page.count('name="action" value="approve"') == 1


def test_the_creator_is_never_offered_the_clients_sign_off(stage):
    c, db, pid, ttok, _k, admin = stage
    _deliver_and_publish(c, db, pid, ttok, admin)
    page = c.get(f"/room/{pid}?t={ttok}").text
    assert "Sign off your deliverables" not in page
    assert '/review/asset' not in page


def test_an_approved_version_is_not_still_a_button(stage):
    """*"the room view still has an approve v2 button active and the client already
    approved v2 it should grey out and text change."*"""
    c, _db, pid, _t, ktok, _a = stage
    page = c.get(f"/room/{pid}?k={ktok}").text
    assert "✓ Approve v1 FINAL" not in page, "a one-tap button for something already done"
    assert "You approved v1 FINAL" in page
    assert "Request changes" in page, (
        "approval is reversible on purpose; taking the way back is worse than the "
        "stale button")


def test_before_approval_the_button_is_there(stage):
    """The other half of the pair — do not fix the stale button by removing the real one."""
    c, db, pid, _t, ktok, _a = stage
    conn = db.connect()
    from chordential_oia.web import production
    production.clear_creative_lock(conn, db, pid)
    conn.close()
    page = c.get(f"/room/{pid}?k={ktok}").text
    assert "✓ Approve v1 FINAL" in page
    assert "You approved" not in page


# ── 4. sign off, settle, download ───────────────────────────────────────────────────
def test_the_client_can_approve_a_deliverable_from_the_room(stage):
    c, db, pid, ttok, ktok, admin = stage
    _deliver_and_publish(c, db, pid, ttok, admin)
    page = c.get(f"/room/{pid}?k={ktok}").text
    key = re.search(r'name="filename" value="([^"]+)"', page).group(1)
    r = c.post(f"/project/{pid}/review/asset",
               data={"k": ktok, "author": "Marta Ruiz", "email": "m@aurora.example",
                     "filename": key, "action": "approve", "origin": "room"},
               follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith(f"/room/{pid}?k={ktok}"), (
        "signing off ejects the client to the old portal")
    page = c.get(f"/room/{pid}?k={ktok}").text
    assert "✓ Approved · Marta Ruiz" in page


def test_the_room_says_what_stands_between_them_and_their_files(stage):
    c, db, pid, ttok, ktok, admin = stage
    _deliver_and_publish(c, db, pid, ttok, admin)
    payoff = re.search(r'class="payoff">(.*?)</div>',
                       c.get(f"/room/{pid}?k={ktok}").text, re.S).group(1)
    assert "Approve every deliverable above" in payoff


def test_the_pay_button_appears_once_everything_is_signed_off(stage):
    """Driven by setting the end state, because getting a real delivery to 100% needs
    every scoped asset uploaded — which the delivery tests already cover."""
    c, db, pid, _t, ktok, _a = stage
    conn = db.connect()
    db.update_delivery(conn, pid, "assets", [])
    conn.close()
    import chordential_oia.web.creator_routes as cr
    real = cr.scoped_signoff
    cr.scoped_signoff = lambda row, delivery: (
        [{"asset": "Final master", "spec": "", "uploaded": True, "asset_key": "",
          "approval": {"status": "Approved", "by": "Marta Ruiz"}}],
        {"approved": 1, "total": 1, "uploaded": 1}, [])
    try:
        from chordential_oia.invoicing import Invoice
        conn = db.connect()
        iid = db.insert_invoice(conn, pid, None,
                                Invoice(client="The Larkspur Trust",
                                        need="Fundraising film",
                                        kind="Final", amount=4200.0))
        # Draft is not owed yet — only an ISSUED invoice is a balance (db.invoice_balance)
        db.update_invoice_status(conn, iid, "Issued")
        conn.close()
        payoff = re.search(r'class="payoff">(.*?)</div>',
                           c.get(f"/room/{pid}?k={ktok}").text, re.S).group(1)
        assert "Pay $4200.00 to unlock your files" in payoff, payoff
        assert "/pay" in payoff
    finally:
        cr.scoped_signoff = real


def test_the_download_replaces_the_paywall_once_paid(stage):
    c, db, pid, _t, ktok, _a = stage
    import chordential_oia.web.creator_routes as cr
    real = cr.scoped_signoff
    cr.scoped_signoff = lambda row, delivery: (
        [{"asset": "Final master", "spec": "", "uploaded": True, "asset_key": "",
          "approval": {"status": "Approved", "by": "Marta Ruiz"}}],
        {"approved": 1, "total": 1, "uploaded": 1}, [])
    try:
        conn = db.connect()
        db.update_delivery(conn, pid, "download_unlocked", True)
        db.update_delivery(conn, pid, "delivery_zip", {"url": "/uploads/pkg.zip"})
        conn.close()
        payoff = re.search(r'class="payoff">(.*?)</div>',
                           c.get(f"/room/{pid}?k={ktok}").text, re.S).group(1)
        assert "Download everything" in payoff and "/uploads/pkg.zip" in payoff
        assert "Pay $" not in payoff
    finally:
        cr.scoped_signoff = real


def test_a_creator_is_shown_neither_the_balance_nor_the_package(stage):
    """`see_invoice` is the client's and the studio's. What the buyer owes is not a
    creator's business, and the package is not theirs to hand out."""
    from chordential_oia.web import room as R
    assert R.can(R.CLIENT, "see_invoice") and R.can(R.OPERATOR, "see_invoice")
    assert not R.can(R.TALENT, "see_invoice")
    c, db, pid, ttok, _k, _a = stage
    conn = db.connect()
    db.update_delivery(conn, pid, "download_unlocked", True)
    db.update_delivery(conn, pid, "delivery_zip", {"url": "/uploads/pkg.zip"})
    conn.close()
    assert "/uploads/pkg.zip" not in c.get(f"/room/{pid}?t={ttok}").text


# ── and "below" has to mean below ───────────────────────────────────────────────────
def test_the_sign_off_is_in_the_room_not_buried_in_a_sheet(stage):
    """*"im in the client view and it still not show the deliverables for review, if it
    does its misleading becasue it say sign off below"* (operator, 2026-08-19).

    It was built inside the Takes sheet, beside the lanes it mirrors — so the verdict
    said "sign each one off below" and below was nothing, two clicks away in a sheet
    called The takes. The buyer's last action in the room is not a drawer.
    """
    c, db, pid, ttok, ktok, admin = stage
    _deliver_and_publish(c, db, pid, ttok, admin)
    page = c.get(f"/room/{pid}?k={ktok}").text
    sign = page.index("Sign off your deliverables")
    for sheet in ("takes", "brief", "notes"):
        assert sign < page.index(f'<div class="sheet sr-sheet" data-sheet="{sheet}"'), (
            f"the sign-off is inside (or after) the {sheet} sheet")
    assert sign > page.index("You approved"), (
        "the verdict says 'below' and points above itself")


def test_the_whisper_counts_the_clients_own_list(stage):
    """It read from `a.deliverables` — the lane view, subtracted from the buyer — so it
    always said "0 of 0 in" at the exact moment they had things to sign off."""
    c, db, pid, ttok, ktok, admin = stage
    _deliver_and_publish(c, db, pid, ttok, admin)
    page = c.get(f"/room/{pid}?k={ktok}").text
    whisper = re.search(r'class="whisper sr-whisper">.*?<span>(.*?)</span>', page, re.S)
    said = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", whisper.group(1))).strip()
    assert "0 of 0" not in said, said
    assert re.search(r"1 of \d+ signed off", said), said


# ── a lane is a folder here too ─────────────────────────────────────────────────────
def _publish_many(c, db, pid, ttok, admin, label, names):
    c.post(f"/creator/{ttok}/project/{pid}/deliverable", data={"label": label},
           files=[("file", (n, io.BytesIO(b"RIFF0000WAVE" + os.urandom(40)), "audio/wav"))
                  for n in names],
           headers={"X-Requested-With": "fetch"})
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    c.cookies.set(*admin)
    for a in pend:
        c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": a["filename"], "action": "publish"},
               follow_redirects=False)
    c.cookies.clear()


def _lane(page, label):
    seg = page[page.index(label):]
    end = seg.find("</form>")
    return seg[:end + 7] if end > 0 else seg[:2000]


def test_a_lane_shows_every_file_it_holds(stage):
    """*"it only showcases 1 file for each lane when in fact there were multiple files
    pushed per lane for approval"* (operator, 2026-08-19). `scoped_signoff` kept the
    FIRST asset under a label — the injective match — so a twelve-stem package was one
    player and one Approve."""
    c, db, pid, ttok, ktok, admin = stage
    stems = ["kick.wav", "snare.wav", "bass.wav", "gtr.wav", "keys.wav", "vox.wav"]
    _publish_many(c, db, pid, ttok, admin, "Mix-ready stem package", stems)
    lane = _lane(c.get(f"/room/{pid}?k={ktok}").text, "Mix-ready stem package")
    assert re.findall(r'class="so-name">([^<]+)<', lane) == stems, lane[:400]
    assert lane.count("<audio") == 6, "not every file can be auditioned"


def test_one_press_signs_off_the_whole_lane(stage):
    """"I approve the stems" is the decision a person is making — not twelve of them."""
    c, db, pid, ttok, ktok, admin = stage
    stems = ["kick.wav", "snare.wav", "bass.wav"]
    _publish_many(c, db, pid, ttok, admin, "Mix-ready stem package", stems)
    lane = _lane(c.get(f"/room/{pid}?k={ktok}").text, "Mix-ready stem package")
    keys = re.findall(r'name="filename" value="([^"]+)"', lane)
    assert len(keys) == 3, keys
    assert "✓ Approve all 3" in lane
    r = c.post(f"/project/{pid}/review/asset",
               data={"k": ktok, "author": "Marta Ruiz", "email": "m@a.com",
                     "origin": "room", "action": "approve", "filename": keys},
               follow_redirects=False)
    assert r.status_code == 303
    conn = db.connect()
    d = db.get_delivery(conn, pid)
    states = [db.get_asset_approval(d, a)["status"] for a in d["assets"]]
    conn.close()
    assert states == ["Approved"] * 3, states


def test_a_partly_approved_lane_says_how_many_are_left(stage):
    c, db, pid, ttok, ktok, admin = stage
    _publish_many(c, db, pid, ttok, admin, "Mix-ready stem package",
                  ["kick.wav", "snare.wav", "bass.wav"])
    lane = _lane(c.get(f"/room/{pid}?k={ktok}").text, "Mix-ready stem package")
    keys = re.findall(r'name="filename" value="([^"]+)"', lane)
    c.post(f"/project/{pid}/review/asset",
           data={"k": ktok, "author": "Marta Ruiz", "email": "m@a.com", "origin": "room",
                 "action": "approve", "filename": keys[:1]}, follow_redirects=False)
    lane = _lane(c.get(f"/room/{pid}?k={ktok}").text, "Mix-ready stem package")
    assert "2 of 3 awaiting your sign-off" in lane, lane[:400]
    assert "✓ Approve all 2" in lane, "the second press re-approves what is already signed"


def test_a_lane_is_only_approved_when_every_file_is(stage):
    """The rollup drives the paywall. One approved stem out of twelve must not read as
    a signed-off deliverable."""
    c, db, pid, ttok, ktok, admin = stage
    _publish_many(c, db, pid, ttok, admin, "Mix-ready stem package",
                  ["kick.wav", "snare.wav"])
    page = c.get(f"/room/{pid}?k={ktok}").text
    lane = _lane(page, "Mix-ready stem package")
    keys = re.findall(r'name="filename" value="([^"]+)"', lane)
    first = re.search(r"(\d+)\s+of\s+(\d+)\s+approved", page).groups()
    c.post(f"/project/{pid}/review/asset",
           data={"k": ktok, "author": "M", "email": "m@a.com", "origin": "room",
                 "action": "approve", "filename": keys[:1]}, follow_redirects=False)
    after = re.search(r"(\d+)\s+of\s+(\d+)\s+approved",
                      c.get(f"/room/{pid}?k={ktok}").text).groups()
    assert after == first, f"half a lane counted as a signed-off deliverable: {first} → {after}"
