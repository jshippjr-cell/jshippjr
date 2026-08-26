"""What the call established, and what the operator corrected, both reach the quote.

Traced live (2026-08-26) after the question *"does a pricing proposal pull from this
pricing intelligence?"*. The chain was real — transcript → capture → Campaign Intelligence
→ `licence_from_ci` → `build_quote` → proposal, one quote authority throughout — and two of
the four priced levers fell out of it on the way.

**The wiring.** The extraction engine's Rights & Licensing worker is instructed to emit
``usage_rights, territory, term, media, …`` (extraction/workers.py). `licence_from_ci`
looked for ``license_term``, ``licence_term``, ``usage_term``, ``rights_term`` — never the
bare ``term`` it was being handed. So the second-largest lever on the sheet arrived under a
name nothing read, and every proposal priced an assumed three-year licence however plainly
the client had answered. Two narrower failures behind it: "twelve months" written in words
matched a digits-only regex, and "North America" matched no territory pattern at all.

**The correction.** These four are PRICED, and until now they were not slots — they landed
in the "extra facts" tail with no labelled, always-editable row. So an operator who heard
the recording and knew the territory was wrong had no way to fix it except to guess an
exact key in "Anything else that matters" and hope pricing happened to read that name. As
canonical slots they are visible when empty, editable when wrong, and a human value wins by
construction — which is the whole point of being able to make one.

Neither failure was a lie: an unread lever lands in ``assumed`` and the quote says
"…were not stated in the brief. Confirm before this becomes an offer." It under-read rather
than invented. But a client who says *"perpetual"* in words the parser missed was priced at
×1.00 instead of ×1.90, with only a caveat line between that and a signature.
"""
import importlib

import pytest

from chordential_oia.pricing import build_quote, licence_from_ci, reference_estimate


# ── the wiring: read what the engine actually emits ─────────────────────────────────
def test_the_rights_worker_speaks_a_language_the_price_understands():
    """The exact key names `extraction/workers.py` tells the rights worker to use, carrying
    the answers a real call gives. Every one has to land."""
    from chordential_oia.extraction.workers import WORKERS
    rights = next(w for w in WORKERS if w.name == "rights")
    for key in ("territory", "term", "media", "exclusivity"):
        assert key in rights.key_guide, f"the worker no longer emits {key}"

    terms = licence_from_ci({
        "territory": "North America to start",
        "term": "Twelve months from first air",
        "media": "Broadcast and social",
        "exclusivity": "Category exclusive for outdoor apparel",
    })
    assert terms.term_stated and terms.term_years == 1
    assert terms.territory_stated and terms.territory == "national"
    assert terms.exclusivity_stated and terms.exclusivity == "category"
    assert terms.media_stated
    assert terms.assumed == [], f"still guessing: {terms.assumed}"


def test_bare_term_is_the_licence_term():
    """The single fix that mattered. A rights analyst saying "term" can only mean the
    licence term — payment terms are their own key — and `term` was the name the whole
    lever kept arriving under while nothing read it."""
    assert licence_from_ci({"term": "2 years"}).term_years == 2
    assert licence_from_ci({"term": "perpetual"}).term_years is None


@pytest.mark.parametrize("said,years", [
    ("Twelve months from first air", 1),
    ("two years", 2),
    ("a year", 1),
    ("18 months", 2),          # rounded UP: 18 months priced as one year gives four away
    ("eighteen months", 2),
    ("3 years", 3),
    ("five-year licence", 5),
])
def test_a_term_said_in_words_is_still_a_term(said, years):
    """Transcripts write numbers out. A digits-only regex reverted "twelve months" to an
    assumed three years — and term is ×0.65 at one year against ×1.90 in perpetuity, so a
    term that fails to parse is not a rounding error, it is the fee."""
    terms = licence_from_ci({"license_term": said})
    assert terms.term_stated, f"{said!r} did not read as a term"
    assert terms.term_years == years


@pytest.mark.parametrize("said,expected", [
    ("North America to start", "national"),
    ("EMEA", "national"),
    ("Europe", "national"),
    ("United States and Canada", "national"),
    ("worldwide", "global"),
    ("all territories", "global"),
    ("US only", "local"),
    ("nationally", "national"),
])
def test_a_region_is_a_territory_answer(said, expected):
    """"North America to start" matched nothing and fell through to an ASSUMED national
    licence — on a transcript where the client had just answered the question."""
    terms = licence_from_ci({"territory": said})
    assert terms.territory_stated, f"{said!r} did not read as a territory"
    assert terms.territory == expected


def test_silence_is_still_silence():
    """The fix must widen what is READ, never what is CLAIMED. Nothing said means nothing
    stated, and the quote goes on saying so."""
    terms = licence_from_ci({"deliverables": "a 60 and two 30s"})
    assert terms.assumed == ["media", "territory", "licence term", "exclusivity"]
    quote = build_quote(reference_estimate(9000), terms)
    assert any("not stated in the brief" in a for a in quote.assumptions)


# ── the correction: four priced levers the operator can actually reach ──────────────
def test_every_priced_lever_is_a_slot_you_can_edit():
    from chordential_oia.web.campaign_intelligence import CANONICAL_FIELDS
    slots = {k for _f, k, _kind, _l, _p, _o in CANONICAL_FIELDS}
    for key in ("media", "territory", "license_term", "exclusivity"):
        assert key in slots, f"{key} is priced but has no editable slot"


def test_the_sheet_and_the_slots_cannot_drift():
    """`call_prep` declares which of its lines fill a CI slot, and it used to say so per
    GROUP — true while the terms were conversation, false the moment four of them became
    slots. A key added in one place and forgotten in the other is a question whose answer
    the sheet never reads back."""
    from chordential_oia.call_prep import _CANON_SLOTS
    from chordential_oia.web.campaign_intelligence import CANONICAL_FIELDS
    assert _CANON_SLOTS == {k for _f, k, _kind, _l, _p, _o in CANONICAL_FIELDS}


def test_the_fourth_lever_is_finally_asked():
    """Media is priced from ×0.55 to ×1.55 and the prep sheet never asked about it — it
    reached the quote only by accident, read out of whatever the deliverables mentioned."""
    from chordential_oia.call_prep import prep_sheet
    asked = {ln.key: ln.ask for g in prep_sheet() for ln in g.lines}
    assert "media" in asked
    assert "run" in asked["media"].lower()


def test_a_deliverable_for_broadcast_does_not_tick_the_media_question():
    """"A 30-second cut down for broadcast" is how a client describes a DELIVERABLE.
    Ticking media off that word would mark the fourth priced lever covered on a call where
    nobody asked."""
    from chordential_oia.call_prep import prep_sheet, score_call
    scored = score_call(prep_sheet({}), "Marco: A 30-second cut down for broadcast.")
    assert [l.label for l in scored.lines if l.covered] == ["Deliverables"]


@pytest.fixture()
def deal(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, campaign_intelligence as ci, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    conn = db.connect()
    try:
        row = db.ci_for_opportunity(conn, 1)
        cid = int(row["id"]) if row is not None else int(
            ci.ensure_for_opportunity(conn, db.get_opportunity(conn, 1))["id"])
    finally:
        conn.close()
    return c, db, ci, 1, cid


def _licence(db, ci, cid):
    conn = db.connect()
    try:
        return licence_from_ci(ci.brief_view(conn, cid)["fields"])
    finally:
        conn.close()


def test_correcting_the_record_by_hand_moves_the_price(deal):
    """THE ASK, end to end. The operator listens back, finds the call was misheard, fixes
    it in Campaign Intelligence — and the quote follows. A correction that does not reach
    the price is a correction that changed nothing."""
    c, db, ci, opp, cid = deal
    conn = db.connect()
    try:
        ci.contribute(conn, cid, "commercial", "term", "Twelve months from first air",
                      kind="fact", source="discovery_call", contributed_by="ai")
        ci.contribute(conn, cid, "commercial", "territory", "North America to start",
                      kind="fact", source="discovery_call", contributed_by="ai")
        conn.commit()
    finally:
        conn.close()
    heard = _licence(db, ci, cid)
    assert (heard.term_years, heard.territory) == (1, "national")

    for key, value in (("license_term", "Perpetual buyout"), ("territory", "Worldwide")):
        r = c.post(f"/opportunity/{opp}/intelligence/field",
                   data={"field_id": "", "facet": "commercial", "key": key,
                         "kind": "fact", "value": value}, follow_redirects=True)
        assert r.status_code == 200

    fixed = _licence(db, ci, cid)
    assert fixed.term_years is None and fixed.territory == "global"
    assert fixed.factor > heard.factor
    before = build_quote(reference_estimate(9000), heard).total
    after = build_quote(reference_estimate(9000), fixed).total
    assert after > before, f"the correction did not move the price ({before} → {after})"


def test_the_correction_is_recorded_as_stated_not_assumed(deal):
    """A value a human typed is the strongest evidence there is. It must not keep reading
    as a guess on the proposal's assumption line."""
    c, db, ci, opp, cid = deal
    c.post(f"/opportunity/{opp}/intelligence/field",
           data={"field_id": "", "facet": "commercial", "key": "exclusivity",
                 "kind": "fact", "value": "Fully exclusive"}, follow_redirects=True)
    terms = _licence(db, ci, cid)
    assert terms.exclusivity == "full" and terms.exclusivity_stated
    assert "exclusivity" not in terms.assumed


def test_the_priced_levers_show_on_the_opportunity_page(deal):
    """Visible when empty, which is the half that makes them correctable at all: a value
    with no row cannot be fixed, only guessed at in the free-text tail."""
    c, _db, _ci, opp, _cid = deal
    page = c.get(f"/opportunity/{opp}").text
    for label in ("Usage · media", "Usage · territory", "Licence term", "Exclusivity"):
        assert label in page, f"{label} has no slot on the page"
