"""Nobody was checking the half of the record a composer actually needs.

Reported live (2026-08-26) from a real discovery call: *"the bot failed to capture creative
direction which is hyper important to pass over to the composer and talent team. Is there
an agent review pertinent information specifically tied to what information is important to
deliver to the talent team/composer?"*

There was not. Traced, the hole is exact:

* `campaign_intake.REQUIRED` — the ONLY gap engine, and what drives `understanding_pct` —
  guards ``budget_band``, ``deadline``, ``deliverables``, ``decision_makers``. The money,
  the dates, the assets, the approver. Every one of them is OUR side of the table.
* `campaign_intelligence.BRIEF_KEYS` — what the composer actually receives — is six fields,
  and FOUR of them are guarded by nothing at all.
* `composer_brief` skips an empty field silently, so the brief simply arrives shorter and
  the composer reads an absent section as nothing to say.

So an intelligence record could read "100% understood" while producing a brief with no
objective, no feeling and no references in it — and no surface anywhere said so.

The same call surfaced two mis-filings, both of the class already documented in
`_canonicalise`: a slot the workers were never told the meaning of.
"""
import importlib

import pytest

from chordential_oia.web.campaign_intelligence import (BRIEF_KEYS, brief_readiness,
                                                       canonical_slot, composer_brief)


def _view(**fields):
    return {"fields": dict(fields)}


# ── the check that did not exist ────────────────────────────────────────────────────
def test_the_gap_engine_never_looked_at_the_composers_half():
    """The evidence for why this module exists, kept as a test so it cannot quietly become
    untrue in either direction — if these ever DO overlap fully, this check is redundant
    and should be deleted rather than left asserting a fixed hole."""
    from chordential_oia.web.campaign_intake import REQUIRED
    required = {k for _f, k, _q in REQUIRED}
    composer = {k for k, _l in BRIEF_KEYS}
    unguarded = composer - required
    assert unguarded, "REQUIRED now covers the brief; brief_readiness may be redundant"
    assert {"campaign_objective", "emotional_arc", "reference_playlist"} <= unguarded


def test_an_empty_creative_direction_is_reported_not_skipped():
    """The exact failure: a call that captured the money and the dates and none of the
    direction. The brief renders three lines and says nothing about the three it dropped."""
    view = _view(deliverables="a 60 and two 30s", deadline="Oct 3",
                 business_objective="launch into a younger demographic")
    assert len(composer_brief(view)) == 3, "the brief silently shortened"
    ready = brief_readiness(view)
    assert not ready["ready"]
    assert {m["key"] for m in ready["missing"]} == {
        "campaign_objective", "emotional_arc", "reference_playlist"}
    assert "feeling it carries" in ready["text"]


def test_a_complete_brief_says_so():
    ready = brief_readiness(_view(**{k: "something" for k, _l in BRIEF_KEYS}))
    assert ready["ready"] and not ready["missing"]
    assert ready["have"] == ready["total"] == len(BRIEF_KEYS)


def test_whitespace_is_not_a_captured_field():
    """A field holding a space is an empty field wearing a value. The composer gets
    nothing from it and the check must not be reassured by it."""
    ready = brief_readiness(_view(emotional_arc="   ", campaign_objective="\n\t "))
    assert {m["key"] for m in ready["missing"]} >= {"emotional_arc", "campaign_objective"}


def test_the_check_and_the_hand_over_read_the_same_list():
    """One derivation. A second list here would go stale the first time the brief changed
    shape, and the check would then be reassuring about the wrong fields."""
    view = _view(**{k: "x" for k, _l in BRIEF_KEYS})
    assert {b["key"] for b in composer_brief(view)} == {k for k, _l in BRIEF_KEYS}
    assert {p["key"] for p in brief_readiness(view)["present"]} == {k for k, _l in BRIEF_KEYS}


def test_it_reports_and_does_not_block():
    """The machine proposes, Jon disposes. A brief may be handed over with a hole in it
    deliberately — that is a decision. What it must never be is a surprise."""
    view = _view(deadline="Oct 3")
    assert composer_brief(view), "readiness must not empty the brief it describes"
    assert brief_readiness(view)["missing"]


# ── the two mis-filings from the same call ──────────────────────────────────────────
def test_an_approval_chain_can_only_mean_who_approves():
    """The call read the approvers correctly and filed them under `review_dates`, a
    TIMELINE key — so the canonical slot kept a name scraped off the opportunity, and the
    real approver sat in a schedule field. Same class as the documented `production_budget`
    failure: a slot nobody told the workers the meaning of."""
    for key in ("approval_chain", "approvers", "final_approval", "sign_off"):
        assert canonical_slot("buyer", key, "fact")[1] == "decision_makers", key


def test_the_workers_are_told_what_the_ambiguous_slots_mean():
    """`brand_notes` captured the AGENCY'S NAME, because the key guide listed the slot and
    never said what belonged in it — while `decision_makers` next to it carried an inline
    description and was filed correctly. A model steered on one slot and left to guess on
    the next will guess."""
    from chordential_oia.extraction.workers import WORKERS
    stakeholder = next(w for w in WORKERS if w.name == "stakeholder").key_guide.lower()
    assert "brand_notes (" in stakeholder, "brand_notes is still undescribed"
    assert "not the brand's name" in stakeholder
    assert "never the agency" in stakeholder
    assert "agency_notes (" in stakeholder

    timeline = next(w for w in WORKERS if w.name == "timeline").key_guide.lower()
    assert "review_dates (" in timeline
    assert "decision_makers" in timeline, "nothing sends the approver to the right slot"

    creative = next(w for w in WORKERS if w.name == "creative").key_guide.lower()
    for key, _label in BRIEF_KEYS:
        if key in ("campaign_objective", "emotional_arc", "reference_playlist"):
            assert f"{key} (canonical" in creative


# ── on the page ─────────────────────────────────────────────────────────────────────
@pytest.fixture()
def page(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    return c


def test_the_operator_sees_the_hole_before_they_assign_anyone(page):
    body = page.get("/opportunity/1").text
    assert "For the composer" in body
    assert "A composer reads an absent section as nothing to say" in body


def test_a_complete_record_shows_no_warning(page):
    from chordential_oia.web import campaign_intelligence as ci, db
    conn = db.connect()
    try:
        row = db.ci_for_opportunity(conn, 1)
        cid = int(row["id"]) if row is not None else int(
            ci.ensure_for_opportunity(conn, db.get_opportunity(conn, 1))["id"])
        for key, _label in BRIEF_KEYS:
            facet = ci.CANONICAL_FACET_FOR_KEY.get(key, "engagement")
            ci.contribute(conn, cid, facet, key, "captured on the call", kind="fact",
                          source="discovery_call", contributed_by="t")
        conn.commit()
    finally:
        conn.close()
    assert "For the composer" not in page.get("/opportunity/1").text
