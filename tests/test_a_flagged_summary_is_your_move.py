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
