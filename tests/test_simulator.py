"""Discovery Call Simulator: the objection library learns; practice calls are graded.

The library seeds idempotently from the five call simulations, grows from real
transcripts as PROPOSED rows the human confirms (machine proposes, Jon disposes),
and repetition bumps times_seen instead of duplicating. Scripted mode is the
honest null path — no LLM, real library objections in persona order — and the
grader is deterministic against the playbook's measurable rules.
"""
import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for m in ("db", "simulator", "campaign_intelligence", "campaign_intake", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


# --------------------------------------------------------------------------- #
# The library
# --------------------------------------------------------------------------- #
def test_seed_is_idempotent_and_never_inflates_times_seen(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from chordential_oia.web import simulator
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    n1 = simulator.seed_objections(conn)
    n2 = simulator.seed_objections(conn)
    assert n1 == n2 == len(simulator.SEED_OBJECTIONS)
    counts = {r["times_seen"] for r in app_mod.db.list_objections(conn)}
    assert counts == {1}        # re-seeding is not "seeing"
    conn.close()


def test_repeat_objection_bumps_times_seen_instead_of_duplicating(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    a = app_mod.db.upsert_objection(conn, family="money_process",
                                    objection="What's your best price? Don't pad it.")
    b = app_mod.db.upsert_objection(conn, family="money_process",
                                    objection="whats your BEST price -- don't pad it")
    assert a == b               # normalized dedupe
    row = [r for r in app_mod.db.list_objections(conn) if r["id"] == a][0]
    assert row["times_seen"] == 2
    conn.close()


def test_harvest_proposes_objections_with_capture_provenance(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from chordential_oia.web import simulator

    def fake_llm(text):
        return [{"family": "cheap_alternatives",
                 "objection": "Why not just use the free AI tools?",
                 "context": "CMO cost pressure", "response": "ownership reframe",
                 "result": "partial"},
                {"family": "not_a_family", "objection": "dropped"},   # invalid → skipped
                {"family": "delivery_risk", "objection": ""}]         # empty → skipped

    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    added = simulator.harvest_objections(conn, "transcript text", capture_id=77, llm=fake_llm)
    assert added == 1
    rows = app_mod.db.list_objections(conn, status="proposed")
    assert len(rows) == 1
    assert rows[0]["source"] == "transcript" and rows[0]["capture_id"] == 77
    conn.close()


def test_harvest_without_llm_is_honestly_empty(tmp_path, monkeypatch):
    """No key → no extraction. The deterministic fallback never keyword-guesses
    objections into the training data (honesty rule)."""
    app_mod = _app(tmp_path, monkeypatch)
    from chordential_oia.web import simulator
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    added = simulator.harvest_objections(conn, "buyer said stock is cheaper and hung up")
    assert added == 0
    assert app_mod.db.list_objections(conn, status="proposed") == []
    conn.close()


def test_library_page_confirms_a_proposed_objection(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = app_mod.db.upsert_objection(conn, family="trust_incumbency",
                                      objection="Fresh from a real call",
                                      source="transcript", status="proposed")
    conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get("/simulator/library").text
        assert "Fresh from a real call" in page and "proposed" in page
        c.post(f"/simulator/library/{oid}/status", data={"status": "confirmed"})
        conn = app_mod.db.connect()
        row = [r for r in app_mod.db.list_objections(conn) if r["id"] == oid][0]
        assert row["status"] == "confirmed"
        conn.close()


# --------------------------------------------------------------------------- #
# The practice call (scripted mode — the null seam)
# --------------------------------------------------------------------------- #
def test_scripted_session_end_to_end_with_scorecard(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    with TestClient(app_mod.app) as c:
        # home lists personas
        home = c.get("/simulator").text
        assert "Incumbent-Loyal" in home and "Scripted mode" in home
        # start against the deadline producer (scripted — no key set)
        r = c.post("/simulator/start", data={"persona": "deadline_producer"},
                   follow_redirects=False)
        sid = r.headers["location"].rstrip("/").split("/")[-1]
        page = c.get(f"/simulator/{sid}").text
        assert "twelve minutes and a problem" in page          # persona opening line
        # seller speaks; scripted buyer answers with a real library objection
        c.post(f"/simulator/{sid}/say", data={"text":
            "Before anything else — when exactly does it air, and what media is the buy?"})
        page = c.get(f"/simulator/{sid}").text
        assert page.count("turn buyer") >= 2                   # opening + objection
        # end and grade
        c.post(f"/simulator/{sid}/end")
        page = c.get(f"/simulator/{sid}").text
        assert "Scorecard" in page and "%" in page
        conn = app_mod.db.connect()
        s = app_mod.db.get_sim_session(conn, int(sid))
        assert s["status"] == "ended" and s["scorecard_json"]
        conn.close()


def test_scripted_buyer_follows_persona_family_order(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from chordential_oia.web import simulator
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    simulator.seed_objections(conn)
    sid = app_mod.db.create_sim_session(conn, persona="deadline_producer")
    s = app_mod.db.get_sim_session(conn, sid)
    first = simulator.next_scripted_objection(conn, s)
    # deadline producer reaches for delivery_risk first
    assert first["family"] == "delivery_risk"
    conn.close()


# --------------------------------------------------------------------------- #
# The grader — deterministic playbook rules
# --------------------------------------------------------------------------- #
def test_grader_rewards_playbook_behavior(tmp_path, monkeypatch):
    _app(tmp_path, monkeypatch)
    from chordential_oia.web import simulator
    buyer = {"who": "buyer", "text": "buyer answer with a solid paragraph of detail " * 3}
    transcript = [buyer]
    # a disciplined seller: balanced turns, questions spread, price late, dated close
    for i in range(9):
        transcript.append({"who": "seller",
                           "text": f"A focused seller turn number {i} with real substance "
                                   f"behind it — and one good question to move us along?"})
        transcript.append(dict(buyer))
    transcript.append({"who": "seller",
                       "text": "Engagements like this land between $6,500 and $9,500 — "
                               "does that fit the budget you had in mind?"})
    transcript.append(dict(buyer))
    transcript.append({"who": "seller",
                       "text": "Let's lock Thursday at 2pm for the review — I'll send the invite now. Fair?"})
    card = simulator.grade(transcript, [1, 2, 3])
    assert card["talk_share"] <= 50
    assert card["questions"] >= 11
    assert card["price_mentioned"] and card["price_late"]
    assert card["next_step"]
    assert card["score"] == 100
    assert card["objections_faced"] == 3


def test_grader_flags_monologues_early_price_and_missing_next_step(tmp_path, monkeypatch):
    _app(tmp_path, monkeypatch)
    from chordential_oia.web import simulator
    transcript = [
        {"who": "buyer", "text": "hi"},
        {"who": "seller", "text": "our price is $50,000 and " + "we are amazing " * 80},
        {"who": "buyer", "text": "ok"},
        {"who": "seller", "text": "I'll send some stuff over sometime."},
    ]
    card = simulator.grade(transcript, [])
    by_rule = {c["rule"]: c["ok"] for c in card["checks"]}
    assert not by_rule["Price raised in the back third"]
    assert not by_rule["Specific next step (day + time)"]
    assert not by_rule["No monologues (longest turn ≤ 120 words)"]
    assert card["score"] < 60


# --------------------------------------------------------------------------- #
# The learning loop rides the intake pipeline
# --------------------------------------------------------------------------- #
def test_transcript_ingest_harvests_into_the_library(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    from chordential_oia.web import campaign_intake, simulator

    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = app_mod.db.insert_opportunity(conn, Opportunity(
        client="Halcyon", need="Anthem", description="d", buyer_type=BuyerType.AGENCY,
        music_requirement=MusicRequirement.ORIGINAL, budget_min=0, budget_max=0))
    mid = app_mod.db.create_meeting(conn, opp_id=oid, meeting_type="zoom",
                                    start_at="2026-07-10T10:00:00+00:00")
    meeting = app_mod.db.get_meeting(conn, mid)

    class _T:
        external_ref = "bot-1"
        def full_text(self):
            return "BUYER: honestly why wouldn't we just use stock music, it's fifty bucks."
        def metadata(self):
            return {"provider": "test"}

    def fake_harvest_llm(text):
        return [{"family": "cheap_alternatives",
                 "objection": "Why wouldn't we just use stock music at $50?",
                 "context": "price-first buyer", "response": "", "result": "no"}]

    monkeypatch.setattr(simulator, "_default_harvest_llm", fake_harvest_llm)
    campaign_intake.ingest_transcript(conn, meeting, _T())
    proposed = app_mod.db.list_objections(conn, status="proposed")
    assert len(proposed) == 1
    assert proposed[0]["source"] == "transcript"
    assert proposed[0]["capture_id"] is not None    # provenance to the real call
    conn.close()


# --------------------------------------------------------------------------- #
# Coaching — the "suggested answer" next to each buyer turn after a call ends
# --------------------------------------------------------------------------- #
def test_coach_uses_library_approach_for_a_scripted_objection(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from chordential_oia.web import simulator
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    simulator.seed_objections(conn)
    oid = app_mod.db.list_objections(conn, status="confirmed")[0]["id"]
    row = app_mod.db.get_objection(conn, oid)
    transcript = [
        {"who": "buyer", "text": row["objection"], "objection_id": oid},
        {"who": "seller", "text": "my answer"},
    ]
    coaching = simulator.coach_turns(conn, transcript)      # no LLM (no key)
    assert len(coaching) == 1
    assert coaching[0]["idx"] == 0
    assert coaching[0]["approach"] == row["response_pattern"]   # the proven approach
    assert coaching[0]["family"]                               # a readable family label
    assert coaching[0]["example"] == ""                       # no model line offline
    conn.close()


def test_coach_matches_free_ai_text_by_keyword(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from chordential_oia.web import simulator
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    simulator.seed_objections(conn)
    # an AI-mode buyer line (no objection_id) that echoes the stock-price objection
    transcript = [{"who": "buyer",
                   "text": "honestly stock music is basically free, why would we pay you thousands"}]
    coaching = simulator.coach_turns(conn, transcript)
    assert coaching[0]["approach"] != simulator._GENERIC_APPROACH   # matched a real one
    assert "exclusivity" in coaching[0]["approach"].lower() or coaching[0]["family"]
    conn.close()


def test_coach_falls_back_to_generic_when_nothing_matches(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from chordential_oia.web import simulator
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    simulator.seed_objections(conn)
    transcript = [{"who": "buyer", "text": "the weather is lovely today isn't it"}]
    coaching = simulator.coach_turns(conn, transcript)
    assert coaching[0]["approach"] == simulator._GENERIC_APPROACH
    conn.close()


def test_coach_example_line_uses_the_llm_seam_when_provided(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from chordential_oia.web import simulator
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    simulator.seed_objections(conn)
    oid = app_mod.db.list_objections(conn, status="confirmed")[0]["id"]
    transcript = [{"who": "buyer", "text": "pushback", "objection_id": oid}]

    def fake_examples(pairs):
        assert len(pairs) == 1                     # one batched call
        return ["Totally fair — here's the specific paperwork that answers it."]

    coaching = simulator.coach_turns(conn, transcript, llm=fake_examples)
    assert coaching[0]["example"].startswith("Totally fair")
    conn.close()


def test_end_call_renders_suggested_answers(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    with TestClient(app_mod.app) as c:
        r = c.post("/simulator/start", data={"persona": "incumbent_ep"},
                   follow_redirects=False)
        sid = r.headers["location"].rstrip("/").split("/")[-1]
        c.post(f"/simulator/{sid}/say", data={"text": "How do you make music today?"})
        # before ending: no suggested answers yet
        assert "Suggested answer" not in c.get(f"/simulator/{sid}").text
        c.post(f"/simulator/{sid}/end")
        page = c.get(f"/simulator/{sid}").text
        assert "Suggested answer" in page          # coaching now shown
        assert "Approach:" in page
        conn = app_mod.db.connect()
        card = app_mod.db.get_sim_session(conn, int(sid))["scorecard_json"]
        import json as _j
        assert _j.loads(card).get("coaching")       # persisted with the scorecard
        conn.close()
