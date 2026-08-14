"""When a client says "no, you didn't get it right", the board must say so.

Reported live, 2026-08-14. The client pressed "no, something's off" in their workspace. An
email went out. And the opportunity went on showing:

    THEIR MOVE — Waiting: client confirming the summary
    They confirm (or correct) with one click in their workspace.

The ball had changed hands and only the inbox knew. The one surface whose entire job is
naming the next move was pointing at the person who had already made theirs.

Two more from the same report, both about the fix being reachable:

  • the operator found the editor by following a link in the email sent AFTER the client
    flagged it. There was no obvious way in beforehand, which is the moment it matters.
  • the two sections they could NOT edit were "Risks we're tracking" and "A couple of
    things to confirm" — the machine's read of what is risky and what is unresolved, and
    therefore the likeliest reasons a client flags a summary in the first place.
"""
import importlib
from datetime import datetime, timezone

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity

pytest.importorskip("fastapi")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "flag.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    for m in ("db", "campaign_intelligence", "campaigns", "next_action", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c


def _opp(*, met=True):
    """An opportunity past its discovery call, because the next-action ladder answers
    "schedule the call" until one has happened — the summary branch is below it."""
    from chordential_oia.web import db
    conn = db.connect()
    try:
        oid = db.insert_opportunity(conn, Opportunity(
            client="Fen & Foundry", need="Brand launch film", description="",
            buyer_type=BuyerType.BRAND, music_requirement=MusicRequirement.ORIGINAL))
        if met:
            db.create_meeting(conn, opp_id=oid, start_at="2026-08-01T15:00:00+00:00",
                              meeting_type="zoom", status="ingested")
        # the client's durable link is minted on demand, not at insert
        return oid, db.ensure_share_token(conn, oid)
    finally:
        conn.close()


def _next(oid):
    from chordential_oia.web import db, next_action
    conn = db.connect()
    try:
        opp = db.get_opportunity(conn, oid)
        return next_action.compute(conn, db, opp, db.project_for_opp(conn, oid))
    finally:
        conn.close()


# ── the state ────────────────────────────────────────────────────────────────────
def test_a_flagged_summary_moves_the_ball_to_you(client):
    """THE bug. The client answered; the board kept waiting for them."""
    from chordential_oia.web import db
    oid, token = _opp()
    conn = db.connect()
    try:
        db.create_brief_snapshot(conn, oid, "{}")
    finally:
        conn.close()

    assert _next(oid)["court"] == "client", "before they answer, it is genuinely their move"

    client.post(f"/workspace/{token}/confirm-scope",
                data={"decision": "no", "confirmed_by": "Marta Vance",
                      "comment": "The budget line is wrong, it's 38 not 110."},
                follow_redirects=False)

    act = _next(oid)
    assert act["court"] == "you", "they replied; the next move is ours"
    assert "flagged" in act["label"].lower()
    assert "38 not 110" in act["detail"], "and their actual words, not a generic nudge"
    assert act["url"].endswith("/capabilities?edit=1"), "pointing straight at the fix"


def test_the_client_still_owns_it_while_they_have_not_answered(client):
    from chordential_oia.web import db
    oid, _token = _opp()
    conn = db.connect()
    try:
        db.create_brief_snapshot(conn, oid, "{}")
    finally:
        conn.close()
    act = _next(oid)
    assert act["court"] == "client" and "Waiting" in act["label"]


def test_a_resolved_correction_stops_claiming_your_attention(client):
    """The mirror image of the bug: once the summary is fixed and re-shared, the board
    must stop saying "fix the summary" — otherwise it is wrong in the other direction."""
    from chordential_oia.web import db
    oid, token = _opp()
    conn = db.connect()
    try:
        db.create_brief_snapshot(conn, oid, "{}")
    finally:
        conn.close()
    client.post(f"/workspace/{token}/confirm-scope",
                data={"decision": "no", "confirmed_by": "Marta", "comment": "wrong"},
                follow_redirects=False)
    assert _next(oid)["court"] == "you"

    conn = db.connect()
    try:
        cur = db.get_doc_overrides(conn, oid)["scope_correction"]
        db.update_doc_override(conn, oid, "scope_correction",
                               {**cur, "resolved": True,
                                "resolved_at": datetime.now(timezone.utc).isoformat()})
    finally:
        conn.close()
    assert _next(oid)["court"] == "client", "fixed and re-shared: back to waiting on them"


def test_a_flag_with_no_note_still_moves_the_ball(client):
    from chordential_oia.web import db
    oid, token = _opp()
    conn = db.connect()
    try:
        db.create_brief_snapshot(conn, oid, "{}")
    finally:
        conn.close()
    client.post(f"/workspace/{token}/confirm-scope",
                data={"decision": "no", "confirmed_by": ""}, follow_redirects=False)
    act = _next(oid)
    assert act["court"] == "you" and act["detail"]


# ── the two sections that could not be edited ────────────────────────────────────
def test_risks_and_questions_are_editable_like_every_other_section(client):
    """They were the only locked ones, and they are the machine's opinion — the part most
    likely to be wrong, on the page a client just told you is wrong."""
    from chordential_oia.web import db
    oid, _token = _opp()

    client.post(f"/opportunity/{oid}/doc/field",
                data={"name": "risks",
                      "value": "The colour grade may slip again.\n"
                               "• Legal is slow on this account."},
                follow_redirects=False)
    client.post(f"/opportunity/{oid}/doc/field",
                data={"name": "open_questions", "value": "Is $38k a ceiling or a target?"},
                follow_redirects=False)

    conn = db.connect()
    try:
        ov = db.get_doc_overrides(conn, oid)
    finally:
        conn.close()
    assert ov["risks"] == ["The colour grade may slip again.",
                           "Legal is slow on this account."], "bullets are stripped"
    assert ov["open_questions"] == ["Is $38k a ceiling or a target?"]

    page = client.get(f"/opportunity/{oid}/capabilities?edit=1").text
    assert "The colour grade may slip again." in page
    assert "Is $38k a ceiling or a target?" in page


def test_the_operators_list_beats_the_machines_selection(client):
    from chordential_oia import capabilities as cap
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    from chordential_oia.qualification import QualificationEngine
    opp = Opportunity(client="Fen & Foundry", need="Brand launch film", description="",
                      buyer_type=BuyerType.BRAND,
                      music_requirement=MusicRequirement.ORIGINAL)
    doc = cap.build_capabilities_doc(
        opp, QualificationEngine().qualify(opp), None, toggles=cap.default_toggles("New"),
        overrides={"risks": ["Only this one."]},
        ci_view={"fields": {"campaign_objective": "Carry the film."},
                 "risks": ["A machine risk.", "Another machine risk."]},
        met=True)
    assert doc.risks == ["Only this one."], "a human who edited has decided"


def test_blanking_the_override_reverts_to_the_generated_set(client):
    from chordential_oia.web import db
    oid, _token = _opp()
    client.post(f"/opportunity/{oid}/doc/field",
                data={"name": "risks", "value": "Mine."}, follow_redirects=False)
    client.post(f"/opportunity/{oid}/doc/field",
                data={"name": "risks", "value": ""}, follow_redirects=False)
    conn = db.connect()
    try:
        assert db.get_doc_overrides(conn, oid)["risks"] == []
    finally:
        conn.close()


# ── and the editor is findable before the client ever sees it ────────────────────
def test_the_edit_control_reads_as_an_action_not_a_toggle(client):
    oid, _token = _opp()
    page = client.get(f"/opportunity/{oid}/capabilities").text
    assert "Edit this summary" in page


def test_the_send_screen_points_at_the_summary_first(client):
    """The operator only found the editor via a link in the email sent AFTER a client
    flagged it. The moment it matters is before Send is pressed."""
    oid, _token = _opp()
    page = client.get(f"/opportunity/{oid}/compose").text
    assert f"/opportunity/{oid}/capabilities?edit=1" in page
    assert "edit the summary" in page.lower()


# ── answered means answered ──────────────────────────────────────────────────────
def _question(oid, facet, key, text):
    from chordential_oia.web import campaign_intelligence as ci
    from chordential_oia.web import db
    conn = db.connect()
    try:
        # the CI record is created on demand, not when the opportunity is inserted
        ci_id = ci.ensure_for_opportunity(conn, db.get_opportunity(conn, oid))["id"]
        return ci_id, ci.contribute(conn, ci_id, facet, key, text,
                                    kind="open_question", source="discovery_call")
    finally:
        conn.close()


def test_answering_a_question_keeps_the_answer_as_a_fact(client):
    """The whole complaint. "Mark answered" closed the question and kept nothing, so the
    answer evaporated at the exact moment somebody knew it."""
    from chordential_oia.web import db
    oid, _token = _opp()
    ci_id, fid = _question(oid, "commercial", "territory", "Where does this run?")

    client.post(f"/opportunity/{oid}/intelligence/answer",
                data={"field_id": str(fid), "answer": "US and Canada, from first air."},
                follow_redirects=False)

    conn = db.connect()
    try:
        rows = {(f["facet"], f["key"], f["kind"]): f for f in db.list_ci_fields(conn, ci_id)}
    finally:
        conn.close()
    fact = rows.get(("commercial", "territory", "fact"))
    assert fact is not None, "the answer must be kept, not just the question closed"
    assert fact["value"] == "US and Canada, from first air."
    assert fact["status"] == "confirmed", "a human said it; it is not a proposal"
    assert rows[("commercial", "territory", "open_question")]["status"] == "answered"


def test_an_answer_lands_in_the_canonical_slot_the_brief_reads(client):
    """A question filed under `commercial/budget_band` is still the budget. Its answer
    belongs in the slot the estimate and the brief read, not one column away because of
    where the QUESTION happened to be filed (ADR-0064)."""
    from chordential_oia.web import db
    oid, _token = _opp()
    ci_id, fid = _question(oid, "commercial", "budget_band",
                           "Is the $38k a ceiling or a target?")

    client.post(f"/opportunity/{oid}/intelligence/answer",
                data={"field_id": str(fid), "answer": "$38,000 is a hard ceiling."},
                follow_redirects=False)

    conn = db.connect()
    try:
        rows = {(f["facet"], f["key"], f["kind"]): f for f in db.list_ci_fields(conn, ci_id)}
    finally:
        conn.close()
    assert ("engagement", "budget_band", "fact") in rows, (
        "the answer landed outside the Budget slot everything downstream reads")
    assert "hard ceiling" in rows[("engagement", "budget_band", "fact")]["value"]


def test_an_answered_question_stops_being_asked_on_the_brief(client):
    oid, _token = _opp()
    _ci_id, fid = _question(oid, "commercial", "territory", "Where does this run?")

    before = client.get(f"/opportunity/{oid}/capabilities").text
    assert "Where does this run?" in before, "it starts life as an open question"

    client.post(f"/opportunity/{oid}/intelligence/answer",
                data={"field_id": str(fid), "answer": "US and Canada."},
                follow_redirects=False)

    after = client.get(f"/opportunity/{oid}/capabilities").text
    assert "Where does this run?" not in after, "an answered question is not still asked"


def test_a_canonical_answer_shows_up_on_the_brief_itself(client):
    """The brief's table is curated to the canonical slots — that is the whole "way too
    much information" fix — so an answer appears there when it fills one of them. A
    non-canonical answer (territory, PRO registration) still lands in intelligence and on
    the opportunity page; it just does not enlarge the client document."""
    oid, _token = _opp()
    _ci_id, fid = _question(oid, "commercial", "budget_band", "Ceiling or target?")
    client.post(f"/opportunity/{oid}/intelligence/answer",
                data={"field_id": str(fid), "answer": "$38,000 is a hard ceiling."},
                follow_redirects=False)
    assert "$38,000 is a hard ceiling." in client.get(
        f"/opportunity/{oid}/capabilities").text


def test_a_non_canonical_answer_still_reaches_the_operators_record(client):
    oid, _token = _opp()
    _ci_id, fid = _question(oid, "commercial", "territory", "Where does this run?")
    client.post(f"/opportunity/{oid}/intelligence/answer",
                data={"field_id": str(fid), "answer": "US and Canada."},
                follow_redirects=False)
    assert "US and Canada." in client.get(f"/opportunity/{oid}").text


def test_answering_returns_to_the_line_you_were_on(client):
    oid, _token = _opp()
    _ci_id, fid = _question(oid, "commercial", "territory", "Where does this run?")
    r = client.post(f"/opportunity/{oid}/intelligence/answer",
                    data={"field_id": str(fid), "answer": "US."}, follow_redirects=False)
    assert r.headers["location"].endswith(f"#ci-{fid}")


def test_dismiss_still_exists_for_a_question_that_will_never_have_one(client):
    """Not every question deserves an answer, and forcing one would invent facts."""
    from chordential_oia.web import db
    oid, _token = _opp()
    ci_id, fid = _question(oid, "commercial", "union", "Union or non-union?")
    client.post(f"/opportunity/{oid}/intelligence/dispose",
                data={"field_id": str(fid)}, follow_redirects=False)
    conn = db.connect()
    try:
        rows = {(f["facet"], f["key"], f["kind"]): f for f in db.list_ci_fields(conn, ci_id)}
    finally:
        conn.close()
    assert rows[("commercial", "union", "open_question")]["status"] == "answered"
    assert ("commercial", "union", "fact") not in rows, (
        "dismissing must NOT invent a fact — it records nothing, which is the honest half")


def test_an_empty_answer_changes_nothing(client):
    from chordential_oia.web import db
    oid, _token = _opp()
    ci_id, fid = _question(oid, "commercial", "territory", "Where does this run?")
    client.post(f"/opportunity/{oid}/intelligence/answer",
                data={"field_id": str(fid), "answer": "   "}, follow_redirects=False)
    conn = db.connect()
    try:
        rows = {(f["facet"], f["key"], f["kind"]): f for f in db.list_ci_fields(conn, ci_id)}
    finally:
        conn.close()
    assert ("commercial", "territory", "fact") not in rows
    assert rows[("commercial", "territory", "open_question")]["status"] == "open"


def test_facts_outside_the_three_canonical_facets_are_rendered_at_all(client):
    """A hole the answer box walked straight into. `fields_view` built sections from
    CANONICAL_FACET_ORDER only — engagement, buyer, direction — so a fact on the
    `commercial` facet was written, confirmed, and displayed NOWHERE. That is exactly
    where the engine files payment terms, cost concerns and usage rights, and where an
    answered question lands when the question was filed there."""
    from chordential_oia.web import campaign_intelligence as ci
    from chordential_oia.web import db
    oid, _token = _opp()
    conn = db.connect()
    try:
        ci_id = ci.ensure_for_opportunity(conn, db.get_opportunity(conn, oid))["id"]
        ci.contribute(conn, ci_id, "commercial", "payment_terms", "Net 30, half up front.",
                      kind="fact", source="discovery_call")
        view = ci.fields_view(conn, ci_id)
    finally:
        conn.close()
    shown = [it["value"] for s in view["sections"] for it in s["items"]]
    assert "Net 30, half up front." in shown
    assert "Net 30, half up front." in client.get(f"/opportunity/{oid}").text
