"""A client paid thousands and downloaded a package with no audio in it.

Reported live (operator, 2026-08-20): *"I downloaded everything and it doesnt have the
audio files in there."*

The packager is not the fault — it bundles every asset whose file is on disk and marks
the rest "referenced (not bundled)". The fault is that it only ever RUNS ONCE.
``_maybe_finalize_delivery`` returns early when the state is already Delivered, so the
ZIP is assembled at whatever moment the delivery first reached that state and every
asset published afterwards stays outside it — listed in the manifest as delivered, and
absent from the file.

Two more from the same download:

* the closing seal read **IN PROGRESS** on a finished, paid-for delivery, and spelled the
  studio's name in 9px caps where the wordmark belongs;
* the Clearance Certificate read **DRAFT · pending confirmation** — *"Dont i need to have
  an actual clearance signature on the certificate? i was never asked for that in the
  whole process."* Confirming the licence gated *Release*, which is a state after the
  client already has the package.
"""
import io
import os
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import Talent


@pytest.fixture()
def shipped(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "letmein")
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    import importlib
    importlib.reload(importlib.import_module("chordential_oia.web.db"))
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import db, production
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    c = TestClient(app_mod.app)
    conn = db.connect()
    db.init_db(conn)
    pid = db.insert_project(conn, None, "The Larkspur Trust", "Sand Castle",
                            1000, 2000, ["Composer"])
    tid = db.insert_talent(conn, Talent(name="Jon Shipp", email="j@x.com",
                                        disciplines=[MusicDiscipline.COMPOSITION]))
    db.add_assignment(conn, pid, "Composer", tid)
    ttok = db.ensure_talent_portal_token(conn, tid)
    up = str(tmp_path / "up")
    os.makedirs(up, exist_ok=True)
    with open(os.path.join(up, "v.wav"), "wb") as fh:
        fh.write(b"RIFF0000WAVE" + os.urandom(300))
    db.update_delivery(conn, pid, "versions",
                       [{"n": 1, "label": "v2 FINAL", "url": "/uploads/v.wav",
                         "filename": "v.wav"}])
    production.set_creative_lock(conn, db, pid, version_n=2, by="Marta Ruiz")
    conn.close()
    return (c, db, pid, ttok, up,
            (ADMIN_COOKIE, admin_cookie_value("letmein")))


def _publish(c, db, pid, ttok, admin, label, names):
    c.post(f"/creator/{ttok}/project/{pid}/deliverable", data={"label": label},
           files=[("file", (n, io.BytesIO(b"RIFF0000WAVE" + os.urandom(300)), "audio/wav"))
                  for n in names], headers={"X-Requested-With": "fetch"})
    conn = db.connect()
    pend = db.get_delivery(conn, pid)["pending_assets"]
    conn.close()
    c.cookies.set(*admin)
    for a in pend:
        c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": a["filename"], "action": "publish"},
               follow_redirects=False)
    c.cookies.clear()


def _satisfy_uploads(db, conn, pid):
    """Give every scoped deliverable an uploaded, approved asset, so the only thing
    left holding the delivery is the licence."""
    from chordential_oia.delivery import scoped_deliverables
    prow = db.get_project(conn, pid)
    assets = []
    for d in scoped_deliverables(prow, db.get_delivery(conn, pid)):
        if d.get("is_master"):
            continue
        assets.append({"label": d["asset"], "filename": "v.wav",
                       "url": "/uploads/v.wav", "kind": "audio"})
    db.update_delivery(conn, pid, "assets", assets)
    for a in assets:
        db.set_asset_approval(conn, pid, db.asset_key(a), status="Approved",
                              by="Marta Ruiz", email="m@a.com", version="2")


def _zip_of(db, pid, up):
    conn = db.connect()
    z = db.get_delivery(conn, pid).get("delivery_zip") or {}
    conn.close()
    assert z, "no package was built"
    return zipfile.ZipFile(os.path.join(up, z["filename"])), z


# ── the audio has to be in it ───────────────────────────────────────────────────────
def test_the_package_contains_the_audio(shipped):
    c, db, pid, ttok, up, admin = shipped
    _publish(c, db, pid, ttok, admin, "Mix-ready stem package", ["kick.wav", "snare.wav"])
    from chordential_oia.web.delivery_ops import _build_delivery_package
    conn = db.connect()
    _build_delivery_package(conn, pid)
    conn.close()
    z, _d = _zip_of(db, pid, up)
    audio = [n for n in z.namelist() if n.lower().endswith((".wav", ".mp3"))]
    assert len(audio) >= 3, z.namelist()      # two stems + the master
    assert any(n.startswith("Stems/") for n in audio), z.namelist()
    assert any(n.startswith("Masters/") for n in audio), z.namelist()


def test_a_package_built_before_the_work_is_rebuilt(shipped):
    """THE reported bug. The ZIP was assembled once, at whatever moment the delivery
    first reached Delivered, and everything published afterwards stayed outside it."""
    c, db, pid, ttok, up, admin = shipped
    from chordential_oia.web.delivery_ops import _build_delivery_package, _package_is_stale
    conn = db.connect()
    db.update_delivery(conn, pid, "state", "Delivered")
    _build_delivery_package(conn, pid)        # built EARLY — before the stems land
    conn.close()
    z, _d = _zip_of(db, pid, up)
    assert not [n for n in z.namelist() if n.startswith("Stems/")], (
        "the fixture is wrong — the early package already has stems")

    _publish(c, db, pid, ttok, admin, "Mix-ready stem package", ["kick.wav", "snare.wav"])
    conn = db.connect()
    delivery = db.get_delivery(conn, pid)
    assert _package_is_stale(delivery), "a package older than its own contents reads fresh"
    from chordential_oia.web.delivery_ops import _maybe_finalize_delivery
    _maybe_finalize_delivery(conn, pid)       # the shortcut that used to just return True
    conn.close()
    z, _d = _zip_of(db, pid, up)
    assert [n for n in z.namelist() if n.startswith("Stems/")], (
        "the package still has no audio in it — the client pays for this file")


def test_the_descriptor_records_what_it_could_not_bundle(shipped):
    """`referenced_count` is the number of files the client will NOT find in the ZIP.
    Non-zero means a package with holes, which nothing was counting."""
    c, db, pid, ttok, up, admin = shipped
    conn = db.connect()
    db.update_delivery(conn, pid, "assets", [
        {"label": "Ghost", "filename": "not-on-disk.wav", "url": "/uploads/x.wav",
         "kind": "audio"}])
    from chordential_oia.web.delivery_ops import _build_delivery_package
    pkg = _build_delivery_package(conn, pid)
    conn.close()
    assert pkg["referenced_count"] == 1, pkg
    assert pkg["asset_count"] == 1


# ── the seal ────────────────────────────────────────────────────────────────────────
def _package_html(db, pid, up):
    z, _d = _zip_of(db, pid, up)
    return z.read("Docs/Delivery-Package.html").decode()


def test_a_delivered_package_is_not_stamped_in_progress(shipped):
    c, db, pid, _t, up, _a = shipped
    conn = db.connect()
    db.update_delivery(conn, pid, "state", "Delivered")
    from chordential_oia.web.delivery_ops import _build_delivery_package
    _build_delivery_package(conn, pid)
    conn.close()
    html = _package_html(db, pid, up)
    seals = re.findall(r'<div class="seal"[^>]*>(.*?)</div>', html, re.S)
    closing = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", seals[-1])).strip()
    assert "DELIVERED" in closing, closing
    assert "IN PROGRESS" not in closing


def test_every_seal_carries_the_mark(shipped):
    """It spelled "Chordential" in 9px caps where the wordmark belongs."""
    c, db, pid, _t, up, _a = shipped
    conn = db.connect()
    db.update_delivery(conn, pid, "state", "Delivered")
    from chordential_oia.web.delivery_ops import _build_delivery_package
    _build_delivery_package(conn, pid)
    conn.close()
    z, _d = _zip_of(db, pid, up)
    for doc in ("Docs/Delivery-Package.html", "Docs/Clearance-Certificate.html"):
        html = z.read(doc).decode()
        for seal in re.findall(r'<div class="seal"[^>]*>(.*?)</div>', html, re.S):
            assert "seal-mark" in seal, f"{doc}: a seal without the wordmark"
            assert "data:image/png;base64," in seal, f"{doc}: the mark did not embed"


# ── and the certificate that certifies nothing ──────────────────────────────────────
def test_an_unconfirmed_licence_is_reported_as_a_hold(shipped):
    """*"i was never asked for that in the whole process."* Confirming the licence gates
    RELEASE — a state after the client already has the package — so a Delivered package
    can carry a DRAFT grant. It is not hard-gated here (that would strand every delivery
    already in flight); it is NAMED, on the console and in the queue."""
    c, db, pid, _t, _up, admin = shipped
    from chordential_oia.web.delivery_ops import DELIVERY_HELD, delivery_held_by
    conn = db.connect()
    _satisfy_uploads(db, conn, pid)
    db.update_delivery(conn, pid, "state", "Delivered")
    delivery, prow = db.get_delivery(conn, pid), db.get_project(conn, pid)
    # the licence is reported LAST — everything else about this delivery is done
    assert delivery_held_by(delivery, prow) == "licence"
    from chordential_oia.web.queue import compute_queue
    cards = compute_queue(conn, db)
    conn.close()
    hit = [x for x in cards if "DRAFT" in (x["title"] or "")]
    assert hit, "nothing tells the operator the certificate certifies nothing"
    assert DELIVERY_HELD["licence"] in hit[0]["detail"]
    c.cookies.set(*admin)
    console = c.get(f"/project/{pid}/delivery").text
    assert "Held:" in console and "Clearance Certificate" in console


def test_confirming_the_licence_moves_the_hold_to_the_signature(shipped):
    """The chain, in the order it has to happen (ADR-0080): confirm the licence — which
    CHANGES the document — then sign it. Signing first would guarantee a superseded
    signature, so the holds are reported in that order."""
    c, db, pid, _t, _up, admin = shipped
    from chordential_oia.web.delivery_ops import delivery_held_by
    conn = db.connect()
    _satisfy_uploads(db, conn, pid)
    db.update_delivery(conn, pid, "state", "Delivered")
    conn.close()
    c.cookies.set(*admin)
    c.post(f"/project/{pid}/delivery/license/confirm", data={"by": "Jon Shipp"},
           follow_redirects=False)
    conn = db.connect()
    held = delivery_held_by(db.get_delivery(conn, pid), db.get_project(conn, pid))
    conn.close()
    assert held == "unsigned", held
    c.post(f"/project/{pid}/delivery/certificate/execute",
           data={"typed_name": "Jon Shipp", "consent": "1"}, follow_redirects=False)
    conn = db.connect()
    held = delivery_held_by(db.get_delivery(conn, pid), db.get_project(conn, pid))
    conn.close()
    assert held == "", held


# ── the download itself is the last chance to get it right ──────────────────────────
def test_downloading_a_stale_package_rebuilds_it_first(shipped):
    """*"i unzip the file, and i see this... no audio files just docs"* — again, after
    the rebuild-on-finalize fix, because an already-Delivered project has no NEXT
    approval to trigger it. The client could download the same hollow ZIP forever."""
    c, db, pid, ttok, up, admin = shipped
    from chordential_oia.web.delivery_ops import _build_delivery_package
    conn = db.connect()
    db.update_delivery(conn, pid, "state", "Delivered")
    db.update_delivery(conn, pid, "download_unlocked", True)
    _build_delivery_package(conn, pid)               # built before the stems land
    ktok = db.ensure_project_share_token(conn, pid)
    conn.close()
    z, _d = _zip_of(db, pid, up)
    assert not [n for n in z.namelist() if n.startswith("Stems/")]

    _publish(c, db, pid, ttok, admin, "Mix-ready stem package", ["kick.wav", "snare.wav"])
    conn = db.connect()
    zip_name = (db.get_delivery(conn, pid)["delivery_zip"] or {})["filename"]
    conn.close()
    c.cookies.clear()
    r = c.get(f"/project/{pid}/dl/{zip_name}", params={"k": ktok},
              follow_redirects=False)
    assert r.status_code == 200, r.status_code
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert [n for n in z.namelist() if n.startswith("Stems/")], (
        "the client downloaded the stale package again")


def test_a_hollow_package_is_not_offered_as_a_download(shipped):
    """A ZIP of documents handed over as "Download everything" is worse than offering
    nothing — it looks like the delivery."""
    c, db, pid, _t, _up, _a = shipped
    conn = db.connect()
    db.update_delivery(conn, pid, "assets", [
        {"label": "Ghost", "filename": "gone.wav", "url": "/uploads/gone.wav",
         "kind": "audio"}])
    db.update_delivery(conn, pid, "state", "Delivered")
    db.update_delivery(conn, pid, "download_unlocked", True)
    from chordential_oia.web.delivery_ops import _build_delivery_package
    _build_delivery_package(conn, pid)
    from chordential_oia.web import production
    ktok = db.ensure_project_share_token(conn, pid)
    conn.close()
    page = c.get(f"/room/{pid}?k={ktok}").text
    payoff = re.search(r'class="payoff">(.*?)</div>', page, re.S)
    if payoff:
        assert "Download everything" not in payoff.group(1), (
            "a package with no audio is offered as the finished delivery")
        assert "being re-assembled" in payoff.group(1)


def test_the_operator_is_told_the_package_is_hollow(shipped):
    c, db, pid, _t, _up, admin = shipped
    conn = db.connect()
    db.update_delivery(conn, pid, "assets", [
        {"label": "Ghost", "filename": "gone.wav", "url": "/uploads/gone.wav",
         "kind": "audio"}])
    from chordential_oia.web.delivery_ops import _build_delivery_package
    _build_delivery_package(conn, pid)
    from chordential_oia.web.queue import compute_queue
    cards = compute_queue(conn, db)
    conn.close()
    hit = [x for x in cards if "no audio in it" in (x["title"] or "")]
    assert hit, "the queue never mentions a package with nothing in it"
    c.cookies.set(*admin)
    console = c.get(f"/project/{pid}/delivery").text
    assert "could not be put in the package" in console


# ── and a way to put the missing files BACK ─────────────────────────────────────────
def _gone(db, pid, pairs):
    """Assets that were published and approved, whose files are no longer on the server."""
    conn = db.connect()
    assets = [{"label": label, "filename": f"gone-{orig}", "orig": orig,
               "url": f"/uploads/gone-{orig}", "kind": "audio"}
              for label, orig in pairs]
    db.update_delivery(conn, pid, "assets", assets)
    for a in assets:
        db.set_asset_approval(conn, pid, db.asset_key(a), status="Approved",
                              by="Marta Ruiz", email="m@a.com", version="2")
    db.update_delivery(conn, pid, "state", "Delivered")
    from chordential_oia.web.delivery_ops import _build_delivery_package
    _build_delivery_package(conn, pid)
    conn.close()


def _restore(c, pid, names):
    return c.post(f"/project/{pid}/delivery/asset/restore",
                  files=[("file", (n, io.BytesIO(b"RIFF" + os.urandom(400)), "audio/wav"))
                         for n in names], follow_redirects=False)


def test_the_console_names_the_missing_files_and_offers_to_take_them(shipped):
    """*"im clicking rebuild package and nothing comes up for me to input the assets"*
    (operator, 2026-08-20). Rebuild re-zips what we still have; when the files are gone
    it cannot help, and the only upload was a single-file form eight screens down."""
    c, db, pid, _t, _up, admin = shipped
    _gone(db, pid, [("Mix-ready stem package", "kick.wav"),
                    ("Mix-ready stem package", "snare.wav")])
    c.cookies.set(*admin)
    page = c.get(f"/project/{pid}/delivery").text
    assert "Missing from the server" in page
    assert "kick.wav" in page and "snare.wav" in page, "it does not say WHICH"
    assert "/delivery/asset/restore" in page
    assert 'name="file" multiple' in page, "one file at a time for a twelve-stem package"


def test_restoring_puts_them_back_in_place(shipped):
    c, db, pid, _t, up, admin = shipped
    _gone(db, pid, [("Mix-ready stem package", "kick.wav"),
                    ("Mix-ready stem package", "snare.wav")])
    c.cookies.set(*admin)
    r = _restore(c, pid, ["kick.wav", "snare.wav"])
    assert r.status_code == 303 and "restore=2" in r.headers["location"]
    conn = db.connect()
    d = db.get_delivery(conn, pid)
    conn.close()
    assert len(d["assets"]) == 2, "restoring APPENDED instead of replacing"
    assert all(os.path.isfile(os.path.join(up, a["filename"])) for a in d["assets"])
    assert [a["orig"] for a in d["assets"]] == ["kick.wav", "snare.wav"]


def test_the_clients_sign_off_survives_the_restore(shipped):
    """`db.asset_key` IS the filename, so a naive replace silently un-approves a
    deliverable the client already signed."""
    c, db, pid, _t, _up, admin = shipped
    _gone(db, pid, [("Mix-ready stem package", "kick.wav")])
    c.cookies.set(*admin)
    _restore(c, pid, ["kick.wav"])
    conn = db.connect()
    d = db.get_delivery(conn, pid)
    conn.close()
    states = [db.get_asset_approval(d, a)["status"] for a in d["assets"]]
    assert states == ["Approved"], states


def test_restoring_rebuilds_the_package_with_the_audio_in_it(shipped):
    """The point of the whole exercise."""
    c, db, pid, _t, up, admin = shipped
    _gone(db, pid, [("Mix-ready stem package", "kick.wav"),
                    ("Mix-ready stem package", "snare.wav")])
    conn = db.connect()
    before = db.get_delivery(conn, pid)["delivery_zip"]
    conn.close()
    assert before["referenced_count"] == 2
    c.cookies.set(*admin)
    _restore(c, pid, ["kick.wav", "snare.wav"])
    z, after = _zip_of(db, pid, up)
    assert after["referenced_count"] == 0, after
    assert len([n for n in z.namelist() if n.startswith("Stems/")]) == 2, z.namelist()


def test_files_are_matched_to_the_deliverable_they_belong_to(shipped):
    """By original name where it matches — not by upload order, which would put the
    cutdown in the stem package."""
    c, db, pid, _t, _up, admin = shipped
    _gone(db, pid, [("Mix-ready stem package", "kick.wav"),
                    (":30 / :15 / :06 cutdowns", "cut30.wav")])
    c.cookies.set(*admin)
    _restore(c, pid, ["cut30.wav", "kick.wav"])          # deliberately reversed
    conn = db.connect()
    d = db.get_delivery(conn, pid)
    conn.close()
    by_label = {a["label"]: a["orig"] for a in d["assets"]}
    assert by_label["Mix-ready stem package"] == "kick.wav"
    assert by_label[":30 / :15 / :06 cutdowns"] == "cut30.wav"


def test_restoring_nothing_says_so(shipped):
    c, db, pid, _t, _up, admin = shipped
    _gone(db, pid, [("Mix-ready stem package", "kick.wav")])
    c.cookies.set(*admin)
    r = c.post(f"/project/{pid}/delivery/asset/restore", files=[], follow_redirects=False)
    assert "restore=none" in r.headers["location"]
