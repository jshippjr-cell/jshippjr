"""Campaign Intake — the capture pipeline (Intake-1: paste-notes + Producer Debrief).

The user tells ChordOS what happened (objective → facts) or what's their read (a
Producer Debrief → insight/recommendation/open_question/risk); the pipeline extracts,
classifies by kind, and writes to Campaign Intelligence through the provenance API. The
user never touches the object. See docs/campaign-intake-prd.md.
"""

import importlib

import pytest

from chordential_oia.web import campaign_intake as intake

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


# --------------------------------------------------------------------------- #
# Extraction — deterministic heuristic (no web, no deps).
# --------------------------------------------------------------------------- #
def test_objective_extraction_pulls_the_required_facts():
    notes = ("Met Halcyon about the Nike holiday spot. They want a :60 anthem plus :30 "
             "and :15 cutdowns and stems. Budget is $18,000 to $24,000. Need it by "
             "November. Sarah Chen, the creative director, is the final approver.")
    by = {(c["facet"], c["key"]): c for c in intake.extract(notes, intake.OBJECTIVE)}
    assert by[("engagement", "budget_band")]["value"] == "$18,000 to $24,000"
    assert "november" in by[("engagement", "deadline")]["value"].lower()
    assert "anthem" in by[("engagement", "deliverables")]["value"]
    assert "Sarah Chen" in by[("buyer", "decision_makers")]["value"]
    # everything objective is a fact
    assert all(c["kind"] == "fact" for c in intake.extract(notes, intake.OBJECTIVE))


def test_debrief_classifies_into_insight_recommendation_and_open_question():
    debrief = ("My read is they say warm but they mean nostalgic, not saccharine. "
               "We should lead with the piano direction and not show the orchestral option. "
               "Risk: unclear if the brand team has actually signed off.")
    kinds = {c["kind"] for c in intake.extract(debrief, intake.DEBRIEF)}
    assert {"insight", "recommendation", "open_question"} <= kinds
    # nothing in a debrief becomes an objective fact
    assert "fact" not in kinds
    # the risk sentence is flagged a concern
    risk = [c for c in intake.extract(debrief, intake.DEBRIEF) if c["is_concern"]]
    assert risk and risk[0]["kind"] == "open_question"


def test_llm_seam_is_used_when_present_else_heuristic():
    calls = []

    def fake_llm(text, stance):
        calls.append(stance)
        return [{"facet": "direction", "key": "tone", "kind": "fact", "value": "cinematic"}]

    got = intake.extract("whatever", intake.OBJECTIVE, llm=fake_llm)
    assert got[0]["value"] == "cinematic" and calls == ["objective"]
    # a failing/empty LLM falls back to the deterministic heuristic
    assert intake.extract("Budget is $9,000.", intake.OBJECTIVE,
                          llm=lambda t, s: None)[0]["key"] == "budget_band"


def test_llm_extractor_is_the_default_seam_and_falls_back(monkeypatch):
    # With no llm arg, extract() uses the built-in _default_llm seam — the LLM extractor.
    def fake_default(text, stance):
        return [{"facet": "engagement", "key": "budget_band", "kind": "fact",
                 "value": "$20,000", "confidence": 90}]
    monkeypatch.setattr(intake, "_default_llm", fake_default)
    # "about twenty grand" — the deterministic regex can't catch this; the LLM does.
    got = intake.extract("Our budget is about twenty grand.", intake.OBJECTIVE)
    assert got[0]["value"] == "$20,000" and got[0]["confidence"] == 90
    # when the seam returns None (no key / disabled), it falls back to deterministic
    monkeypatch.setattr(intake, "_default_llm", lambda t, s: None)
    assert intake.extract("Budget is $9,000.", intake.OBJECTIVE)[0]["key"] == "budget_band"


def test_llm_default_seam_off_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert intake._default_llm("Budget is about twenty grand.", intake.OBJECTIVE) is None


def test_llm_coerce_validates_normalizes_and_guards_debrief():
    raw = [
        {"facet": "engagement", "key": "budget_band", "kind": "fact", "value": "$20,000",
         "confidence": 90},
        {"facet": "direction", "key": "Emotional Arc!", "kind": "insight",
         "value": "nostalgic, warm", "confidence": "high"},          # key normalized, conf→None
        {"facet": "engagement", "kind": "open_question", "value": "unclear who signs off",
         "is_concern": True},                                        # key derived from value
        {"facet": "bogus", "kind": "fact", "value": "x"},            # dropped: bad facet
        {"facet": "engagement", "kind": "nope", "value": "y"},       # dropped: bad kind
        {"facet": "engagement", "kind": "fact", "value": ""},        # dropped: empty
    ]
    obj = intake._coerce_candidates(raw, intake.OBJECTIVE)
    by = {c["key"]: c for c in obj}
    assert len(obj) == 3
    assert by["budget_band"]["confidence"] == 90
    assert by["emotional_arc"]["kind"] == "insight" and by["emotional_arc"]["confidence"] is None
    assert by["unclear_who_signs_off"]["is_concern"] is True
    # a debrief must never yield an objective fact — the fact is dropped, interpretation kept
    deb = intake._coerce_candidates(raw, intake.DEBRIEF)
    assert "fact" not in {c["kind"] for c in deb} and deb


# --------------------------------------------------------------------------- #
# Ingest + gap-fill — writes to Campaign Intelligence, raises material gaps.
# --------------------------------------------------------------------------- #
def _campaign(tmp_path):
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "i.db"))
    dbm.init_db(conn)
    pid = dbm.insert_project(conn, None, "Halcyon", "Holiday spot", 0, 0, ["Composer"], None)
    camp = dbm.get_campaign(conn, dbm.ensure_campaign_for_project(conn, pid)["id"])
    return dbm, conn, camp


def test_ingest_writes_facts_stores_the_capture_and_raises_gaps(tmp_path):
    from chordential_oia.web import campaign_intelligence as ci
    dbm, conn, camp = _campaign(tmp_path)
    # partial notes: budget + deadline present, deliverables + decision-maker missing
    summary = intake.ingest(conn, camp, intake.OBJECTIVE,
                            "Budget is $18,000 to $24,000. Need it by November.")
    # 2 of 8. The denominator was 4 — the budget, the dates, the deliverables and the
    # approver, every one of them OUR side of the table — until the four fields a COMPOSER
    # is handed joined it (see `campaign_intake.REQUIRED`). The score fell on every deal at
    # once and nothing got worse: those deals were always missing the creative half, and
    # the number was flattering them.
    assert summary["understanding_pct"] == 25
    assert summary["added"] == 2 and len(summary["questions"]) == 6
    # the facts landed on CI, sourced to the capture, awaiting review (machine proposes)
    fields = {(r["facet"], r["key"], r["kind"]): r
              for r in dbm.list_ci_fields(conn, summary["ci_id"])}
    bud = fields[("engagement", "budget_band", "fact")]
    assert bud["status"] == "needs_review" and "notes" in bud["sources"]
    # the gaps became open_question fields (source ai)
    assert ("engagement", "ask_deliverables", "open_question") in fields
    assert ("buyer", "ask_decision_makers", "open_question") in fields
    # the capture is stored as immutable evidence (raw text + extraction)
    caps = dbm.list_captures(conn, summary["ci_id"])
    assert len(caps) == 1 and "$18,000" in caps[0]["raw_text"]
    assert caps[0]["stance"] == "objective"


def test_answering_a_gap_becomes_a_confirmed_fact_and_raises_understanding(tmp_path):
    dbm, conn, camp = _campaign(tmp_path)
    summary = intake.ingest(conn, camp, intake.OBJECTIVE, "Budget is $20k. By December.")
    ci_id = summary["ci_id"]
    assert intake.understanding_pct(conn, ci_id) == 25          # 2 of 8
    # answer the deliverables gap → a confirmed fact, question closed, score rises
    q = [r for r in dbm.list_ci_fields(conn, ci_id) if r["key"] == "ask_deliverables"][0]
    intake.answer_gap(conn, q, ":60 anthem + :30 cutdown + stems")
    fields = {(r["facet"], r["key"], r["kind"]): r for r in dbm.list_ci_fields(conn, ci_id)}
    ans = fields[("engagement", "deliverables", "fact")]
    assert ans["status"] == "confirmed" and "operator" in ans["sources"]
    assert fields[("engagement", "ask_deliverables", "open_question")]["status"] == "answered"
    assert intake.understanding_pct(conn, ci_id) == 38          # 3 of 8


def test_debrief_contributions_are_interpretation_never_fact(tmp_path):
    import json as _json
    dbm, conn, camp = _campaign(tmp_path)
    summary = intake.ingest(conn, camp, intake.DEBRIEF,
                            "We should lead with piano. Risk: unclear who signs off.")
    # scope to what the DEBRIEF itself contributed (source producer_debrief) — its items
    # are interpretation (insight/recommendation/open_question), never objective fact.
    debrief_fields = [r for r in dbm.list_ci_fields(conn, summary["ci_id"])
                      if "producer_debrief" in (_json.loads(r["sources"]) or [])]
    kinds = {r["kind"] for r in debrief_fields}
    assert "recommendation" in kinds and "open_question" in kinds
    assert "fact" not in kinds


# --------------------------------------------------------------------------- #
# Web — the capture routes + the summary banner + inline gap answer.
# --------------------------------------------------------------------------- #
def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    for m in ("db", "campaign_intelligence", "campaign_intake", "campaigns", "app"):
        mod = importlib.import_module(f"chordential_oia.web.{m}")
        importlib.reload(mod)
    from chordential_oia.web import app as app_mod
    return app_mod


def test_capture_route_populates_intelligence_and_answers_a_gap(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    pid = app_mod.db.insert_project(conn, None, "Halcyon", "Spot", 0, 0, ["Composer"], None)
    cid = app_mod.db.ensure_campaign_for_project(conn, pid)["id"]
    conn.close()
    with TestClient(app_mod.app) as c:
        r = c.post(f"/campaign/{cid}/capture", follow_redirects=False,
                   data={"stance": "objective",
                         "text": "Budget is $18,000 to $24,000. Need it by November."})
        assert "understood=25" in r.headers["location"] and "asked=6" in r.headers["location"]
        # the summary banner renders on the redirect target (with the query params)
        home = c.get(f"/campaign/{cid}?understood=25&added=2&asked=6").text
        assert "Understood <b>25%</b>" in home
        assert "What deliverables are needed" in home        # a gap question surfaced
        # answer it inline → becomes a fact.
        #
        # BY KEY, not by position. This used to take the FIRST field_id on the page and
        # assume it was the deliverables gap, which held while there were two gaps and
        # broke the day there were six: it answered whichever question happened to render
        # first and then looked for a deliverables fact that was never written. The page
        # carrying the question is asserted above; which id belongs to it is not a fact
        # about the markup.
        conn = app_mod.db.connect()
        try:
            gap_row = app_mod.db.ci_for_campaign(conn, cid)
            fid = [r["id"] for r in app_mod.db.list_ci_fields(conn, gap_row["id"])
                   if r["key"] == "ask_deliverables"][0]
        finally:
            conn.close()
        c.post(f"/campaign/{cid}/intelligence/answer",
               data={"field_id": fid, "answer": ":60 anthem + stems"})
        conn = app_mod.db.connect()
        try:
            ci_row = app_mod.db.ci_for_campaign(conn, cid)
            deliv = [r for r in app_mod.db.list_ci_fields(conn, ci_row["id"])
                     if r["key"] == "deliverables" and r["kind"] == "fact"][0]
        finally:
            conn.close()
        assert deliv["value"] == ":60 anthem + stems" and deliv["status"] == "confirmed"


def test_debrief_capture_adds_read_with_kind_badges(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    pid = app_mod.db.insert_project(conn, None, "Halcyon", "Spot", 0, 0, ["Composer"], None)
    cid = app_mod.db.ensure_campaign_for_project(conn, pid)["id"]
    conn.close()
    with TestClient(app_mod.app) as c:
        c.post(f"/campaign/{cid}/capture", data={"stance": "debrief",
               "text": "My read is they mean nostalgic not saccharine. We should lead "
                       "with piano. Risk: brand team hasn't signed off."})
        home = c.get(f"/campaign/{cid}").text
        assert ">Insight<" in home and ">Recommendation<" in home and "⚠ risk" in home
