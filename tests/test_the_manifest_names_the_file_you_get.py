"""The manifest must describe the package it ships inside.

Reported as *"duplicate labels in the manifest"* (operator, 2026-08-24). Measured, it
was worse than duplication. `build_manifest` invented a name for every uploaded asset
with `version_name(campaign, label, …)` — a function of the LANE — while
`build_delivery_zip` wrote a different name entirely. So:

  * a lane holding four stems produced four IDENTICAL manifest rows
    (`AURORA_Mixreadystempackage_MASTER_v1_MASTER`, ×4), and the client could not tell
    the kick from the vocal or a re-delivery from the one before it;
  * **not one filename on the manifest existed in the ZIP it was describing** — the whole
    of that document's job;
  * and a scoped line read `[ ] Mix-ready stem package · Scoped` directly above four
    Delivered rows of that very lane: one document, both claims.

The fix is the repo's own rule — one derivation, many reporters (ADR-0062). The layout
is decided once in `plan_package_layout`; the packager and the manifest both report it.

Also here: the ZIP's orientation file. `START-HERE.txt` opens "open
Docs/Delivery-Package.html" and was filed two folders deep in `Docs/For-filing/`, under
a name that says it is paperwork for a PRO — so unzipping presented `Docs/ Masters/
Stems/` and nothing at all saying which to open first.
"""
import os
import tempfile
import zipfile

import pytest

from chordential_oia.delivery import (
    build_delivery_zip, build_manifest, plan_package_layout,
)

STEMS = ["kick_01.wav", "snare_02.wav", "vox_lead.wav", "bass_di.wav"]


def _project():
    return {"id": 12, "client": "AURORA", "need": "Aurora Outdoor Launch",
            "discipline": "original_score", "status": "delivered"}


def _assets():
    """One lane holding four files (ADR-0074), plus a single-file lane."""
    out = [{"filename": "stored_" + n, "orig": n, "label": "Mix-ready stem package",
            "kind": "audio", "folder": "Stems"} for n in STEMS]
    out.append({"filename": "stored_master.wav", "orig": "master.wav",
                "label": "Master :60", "kind": "audio", "folder": "Masters"})
    return out


@pytest.fixture()
def built():
    """A real package on disk, with real bytes behind every asset."""
    tmp = tempfile.mkdtemp()
    for a in _assets():
        with open(os.path.join(tmp, a["filename"]), "wb") as fh:
            fh.write(b"RIFF0000WAVEfmt ")
    delivery = {"assets": _assets(), "state": "released", "versions": []}
    desc = build_delivery_zip(_project(), [], delivery, tmp)
    with zipfile.ZipFile(os.path.join(tmp, desc["filename"])) as zf:
        yield desc, zf


def _uploaded_rows(assets):
    return [r for r in build_manifest(_project(), assets=assets)
            if r.group == "Uploaded assets"]


# ── the duplication that was reported ───────────────────────────────────────────────
def test_a_lane_of_four_is_four_distinct_manifest_rows():
    rows = _uploaded_rows(_assets())
    names = [r.asset for r in rows]
    assert len(names) == 5
    assert len(set(names)) == 5, f"the manifest says the same thing twice: {names}"


def test_each_row_carries_the_creators_own_filename():
    """The lane name is what four stems SHARE; it cannot be what tells them apart."""
    names = " ".join(r.asset for r in _uploaded_rows(_assets()))
    for stem in STEMS:
        assert stem in names, f"{stem} is not named anywhere on the manifest"


def test_the_lane_is_still_named():
    """Distinctness must not cost the label — the client needs to know what lane a
    file belongs to as well as which file it is."""
    rows = _uploaded_rows(_assets())
    assert sum("Mix-ready stem package" in r.asset for r in rows) == 4
    assert any("Master :60" in r.asset for r in rows)


# ── the part that matters: the names have to be real ────────────────────────────────
def test_every_filename_on_the_manifest_exists_in_the_package(built):
    """The one assertion this document lives or dies by.

    Before the fix this failed on EVERY row: the manifest named
    `AURORA_Mixreadystempackage_MASTER_v1_MASTER` and the ZIP held `Stems/kick_01.wav`.
    """
    _desc, zf = built
    inside = set(zf.namelist())
    for row in _uploaded_rows(_assets()):
        path = row.asset.split(" · ", 1)[-1]
        assert path in inside, (
            f"the manifest lists {path!r}, which is not in the package. "
            f"The package holds: {sorted(n for n in inside if '/' in n)}")


def test_the_packager_and_the_manifest_read_the_same_plan(built):
    """One derivation, many reporters. Two naming conventions is how they came to
    disagree, so the test is that there is only one."""
    _desc, zf = built
    planned = {e["arc"] for e in plan_package_layout(_project(), _assets())}
    listed = {r.asset.split(" · ", 1)[-1] for r in _uploaded_rows(_assets())}
    assert planned == listed
    assert planned <= set(zf.namelist())


def test_an_asset_with_no_file_is_not_given_an_imaginary_path():
    """Evidence or nothing: a referenced-by-URL asset has no copy in the package, and
    the manifest must not print a path for it."""
    rows = _uploaded_rows([{"filename": "", "url": "https://example.com/a.mp3",
                            "label": "Anthem :60 (demo)", "kind": "audio"}])
    assert len(rows) == 1
    assert "not in this package" in rows[0].asset
    assert rows[0].status == "Pending"


def test_an_asset_whose_bytes_are_nowhere_is_not_claimed_as_delivered():
    """The half of this fix that was nearly missed.

    An asset with a stored filename has a planned home whether or not its bytes exist —
    so listing that home unconditionally would print a path the ZIP does not contain,
    which is the exact lie the row was rewritten to stop telling. The packager passes
    the set it is really writing.
    """
    tmp = tempfile.mkdtemp()
    present, absent = _assets()[0], dict(_assets()[-1])
    absent["filename"] = "vanished.wav"
    with open(os.path.join(tmp, present["filename"]), "wb") as fh:
        fh.write(b"RIFF0000WAVEfmt ")
    desc = build_delivery_zip(_project(), [], {"assets": [present, absent]}, tmp)
    with zipfile.ZipFile(os.path.join(tmp, desc["filename"])) as zf:
        inside = set(zf.namelist())
        text = zf.read("Docs/For-filing/manifest.txt").decode("utf-8")
    assert desc["referenced_count"] == 1
    rows = [l for l in text.splitlines() if "Master :60" in l]
    assert rows and "not in this package" in rows[0], rows
    for line in text.splitlines():
        for tok in line.split():
            if "/" in tok and tok.split("/")[0] in ("Masters", "Stems", "Social",
                                                    "Cutdowns", "Assets"):
                assert tok in inside, f"the manifest promises {tok}, which is absent"


# ── the scoped line that contradicted the delivered ones ────────────────────────────
def test_a_scoped_deliverable_that_arrived_says_so():
    rows = build_manifest(_project(), assets=_assets())
    stem_row = next(r for r in rows
                    if r.asset == "Mix-ready stem package" and r.group != "Uploaded assets")
    assert stem_row.status == "Delivered", (
        "the manifest still says a lane is unfulfilled on the same page it lists four "
        "delivered files from it")


def test_a_scoped_deliverable_that_did_not_arrive_is_not_claimed():
    """The loose matcher (`_deliverable_uploaded`) shares a token with everything: a
    delivery of stems and a :60 master read 'Instrumental / TV mix · Delivered' off the
    word "mix". A manifest claiming a deliverable nobody made is worse than one that
    admits the gap, so the match is INJECTIVE — one asset satisfies one line."""
    rows = build_manifest(_project(), assets=_assets())
    tv = next(r for r in rows if r.asset == "Instrumental / TV mix")
    assert tv.status == "Scoped"


def test_nothing_is_marked_delivered_when_nothing_was_uploaded():
    rows = build_manifest(_project(), assets=[])
    assert all(r.status == "Scoped" for r in rows)


# ── the orientation file ────────────────────────────────────────────────────────────
def test_the_package_says_where_to_start_at_the_top_level(built):
    _desc, zf = built
    assert "START-HERE.txt" in zf.namelist(), (
        "unzipping shows Docs/ Masters/ Stems/ and nothing saying which to open")
    text = zf.read("START-HERE.txt").decode("utf-8")
    assert "START HERE" in text
    assert "Docs/Delivery-Package.html" in text


def test_the_readme_path_is_correct_from_where_it_sits(built):
    """It tells you to open `Docs/Delivery-Package.html`. From inside
    `Docs/For-filing/`, where it used to live, that path pointed at nothing."""
    _desc, zf = built
    inside = set(zf.namelist())
    text = zf.read("START-HERE.txt").decode("utf-8")
    for line in text.splitlines():
        for token in line.split():
            if token.startswith("Docs/") and token.endswith((".html", ".pdf")):
                assert token in inside, f"START-HERE.txt points at {token}, which is absent"


def test_the_raw_filing_records_stay_out_of_the_clients_docs_folder(built):
    """The branded HTML is the deliverable; the CSV/JSON/TXT a coordinator files with
    the PROs is not, and must not sit beside it."""
    _desc, zf = built
    top = {n.split("/", 1)[1] for n in zf.namelist()
           if n.startswith("Docs/") and n.count("/") == 1}
    assert top and all(n.endswith((".html", ".pdf")) for n in top), top
