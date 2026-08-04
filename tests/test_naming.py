"""Delivery filenames assert only what the brief actually says.

The stem contract is ``CAMPAIGN_CUE_LEN_ROLE_vN_STATE``. Both production upload paths
called it as ``version_name(campaign, "Master", 60, "Master", n, f"v{n}")``, which on a
seeded project produced::

    SUMMER_Master_60_MASTER_v1_V1

Three fabrications in one filename the client receives:

* **``60``** — hardcoded. Three of the four seeded projects have briefs that never say
  :60; one of them says ":06/:15/:30 cutdowns", i.e. a :30 master.
* **``Master`` twice** — the caller filled the CUE slot with "Master" as well as the
  ROLE slot, and a blank cue fell back to the literal placeholder ``Cue``.
* **``_v1_V1``** — the version number again, because ``f"v{n}"`` was passed into the
  STATE slot, which exists for ``FINAL``.

The manifest independently *recomputed* a stem rather than reading the one the file was
written with, so it could name a file that does not exist.

ADR-0037: every token is optional, a blank one is skipped, and the length comes from
what the brief STATES — never from the pricing engine's assumption.
"""

import importlib
import re

import pytest

from chordential_oia.delivery import build_manifest, version_name
from chordential_oia.estimation import _infer_duration, stated_length

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


# --------------------------------------------------------------------------- #
# What the brief states
# --------------------------------------------------------------------------- #
def test_a_stated_length_is_read():
    assert stated_length("Original :30 brand spot, national") == 30
    assert stated_length("60-second anthem") == 60
    assert stated_length("2-minute brand film") == 120
    assert stated_length(":15 social cutdown") == 15


def test_the_longest_stated_length_wins():
    """Same rule as pricing: a brief listing its cutdown suite is the LONG job. The
    seeded CPG brief says ":06/:15/:30 cutdowns" — its master is a :30, not a :06."""
    assert stated_length(":60 anthem with :30 and :15 cutdowns") == 60
    assert stated_length("original campaign music with :06/:15/:30 cutdowns") == 30


def test_an_unstated_length_is_not_guessed():
    """The whole point. Pricing MUST put a number on an unstated brief — a quote needs
    one — so `_infer_duration` assumes :30. A filename asserting a duration nobody
    measured is a different thing: a claim we cannot back."""
    for brief in ("Summer Launch", "Brand Refresh", "Original music for a campaign"):
        assert stated_length(brief) is None, brief
        assert "assumed" in _infer_duration(brief.lower()).setting, (
            "pricing should still assume — only naming must abstain")


def test_anthem_alone_is_not_a_duration():
    """`_infer_duration` treats "anthem" as :60, which is a fine pricing convention and
    a bad filename. "Holiday Anthem" states no length."""
    assert _infer_duration("holiday anthem").setting == ":60 / anthem"
    assert stated_length("Holiday Anthem") is None


# --------------------------------------------------------------------------- #
# What the stem may contain
# --------------------------------------------------------------------------- #
def test_the_documented_example_still_holds():
    assert version_name("Aurora Outdoor", "Anthem", 60, "Master", 3, "FINAL") == \
        "AURORA_Anthem_60_MASTER_v3_FINAL"


def test_a_blank_token_is_skipped_not_invented():
    """A blank cue used to become the literal string "Cue"."""
    assert version_name("Summer Launch", "", 30, "Master", 1, "") == "SUMMER_30_MASTER_v1"
    assert version_name("Summer Launch", "", "", "Master", 1, "") == "SUMMER_MASTER_v1"
    for stem in (version_name("X", "", "", "", 1, ""), version_name("X", "", "", "M", 2, "")):
        assert "Cue" not in stem
        assert "__" not in stem


def test_the_state_slot_is_not_the_version_number_again():
    assert version_name("Summer", "", "", "Master", 1, "") == "SUMMER_MASTER_v1"
    assert not re.search(r"_v(\d+)_V\1$", version_name("Summer", "", "", "Master", 1, ""))
    # FINAL is what the slot is for, and still works.
    assert version_name("Summer", "", "", "Master", 3, "FINAL").endswith("_v3_FINAL")


# --------------------------------------------------------------------------- #
# What the app actually writes
# --------------------------------------------------------------------------- #
@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "naming.db"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    return mod


def _project_briefs(app_mod):
    """(project row, the full brief text the namer reads) for every seeded project."""
    from chordential_oia.web import db

    conn = db.connect()
    try:
        out = []
        for p in conn.execute("SELECT * FROM projects ORDER BY id").fetchall():
            text = p["need"] or ""
            if p["opp_id"]:
                o = db.get_opportunity(conn, p["opp_id"])
                if o is not None:
                    text = f"{text} {o['need'] or ''} {o['description'] or ''}"
            out.append((dict(p), text, app_mod._master_stem(conn, p["id"], p, 1, "v1 Concept")))
        return out
    finally:
        conn.close()


def test_no_master_claims_a_length_its_brief_never_stated(app_mod):
    """The headline: `_60_` on a :30 spot."""
    rows = _project_briefs(app_mod)
    assert rows, "no seeded projects"
    for proj, text, stem in rows:
        want = stated_length(text)
        found = [int(t) for t in stem.split("_") if t.isdigit()]
        if want is None:
            assert not found, (
                f"project {proj['id']} ({proj['need']!r}) names a length its brief "
                f"never stated: {stem}")
        else:
            assert found == [want], f"project {proj['id']}: {stem} vs a stated :{want}"


def test_a_stated_length_does_reach_the_filename(app_mod):
    """Abstaining must not mean never naming one — the seeded CPG brief states :30."""
    stated = [(p, s) for p, t, s in _project_briefs(app_mod) if stated_length(t)]
    assert stated, "no seeded brief states a length — test proves nothing"
    for proj, stem in stated:
        assert "_30_" in stem or "_60_" in stem or "_15_" in stem or "_120_" in stem


def test_no_master_stem_repeats_itself(app_mod):
    for proj, text, stem in _project_briefs(app_mod):
        assert not re.search(r"_v(\d+)_V\1$", stem), f"project {proj['id']}: {stem}"
        assert stem.upper().count("MASTER") == 1, (
            f"project {proj['id']} says MASTER more than once: {stem}")


def test_both_upload_paths_write_the_same_stem(app_mod):
    """The admin Assets agent and the composer portal share one helper so a version
    cannot be named differently depending on who uploaded it."""
    import inspect

    src = inspect.getsource(app_mod._append_version_from_bytes)
    pub = inspect.getsource(app_mod._publish_pending_submission)
    assert "_master_stem(" in src and "_master_stem(" in pub
    assert "version_name(" not in src and "version_name(" not in pub


# --------------------------------------------------------------------------- #
# The manifest names the file that exists
# --------------------------------------------------------------------------- #
def test_the_manifest_renders_the_stored_stem():
    """It used to recompute one, so the manifest could list a filename the delivery
    package does not contain."""
    project = {"need": "Summer Launch", "client": "Vance Athletic"}
    versions = [{"n": 1, "label": "v1 Concept", "name": "SUMMER_30_MASTER_v1"},
                {"n": 2, "label": "v2 FINAL", "name": "SUMMER_30_MASTER_v2_FINAL"}]
    rows = [r for r in build_manifest(project, versions=versions) if r.group == "Versions"]
    assert [r.asset.split(" — ")[0] for r in rows] == \
        ["SUMMER_30_MASTER_v1", "SUMMER_30_MASTER_v2_FINAL"]


def test_a_legacy_version_without_a_stored_name_still_gets_one():
    """Rows written before names were stored must not crash the manifest — and the
    fallback may not invent a length either."""
    project = {"need": "Summer Launch", "client": "Vance Athletic"}
    rows = [r for r in build_manifest(project, versions=[{"n": 1, "label": "v1 Concept"}])
            if r.group == "Versions"]
    stem = rows[0].asset.split(" — ")[0]
    assert stem == "SUMMER_MASTER_v1"
    assert "60" not in stem
