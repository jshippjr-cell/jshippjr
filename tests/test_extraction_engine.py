"""The Campaign Intelligence Extraction Engine (ADR-0023).

The orchestrated system — ten domain specialists fanning out over every artifact,
deterministic validation, a recall loop that hunts omissions until dry, and a merge that
preserves evidence + ambiguity — all writing into the EXISTING Campaign Intelligence
Board through the intake pipeline's capture envelope and contribute(). Nothing bypasses
the board; with no provider configured the engine steps aside and intake behaves exactly
as before (the null-provider regression tests pin that)."""
import importlib
import json

import pytest

from chordential_oia.extraction import engine as ext_engine
from chordential_oia.extraction import merge as ext_merge
from chordential_oia.extraction import providers as ext_providers
from chordential_oia.extraction import recall as ext_recall
from chordential_oia.extraction import validation as ext_validation
from chordential_oia.extraction.schemas import coerce_fact
from chordential_oia.extraction.workers import (RECALL_SPEC, WORKERS, WORKERS_BY_NAME,
                                                build_worker_prompt)


class FakeProvider:
    """Dispatches canned JSON per worker (worker prompts carry their specialist title),
    records every prompt, and can be told to fail for specific workers."""
    name = "fake"
    model = "fake-1"
    available = True

    def __init__(self, outputs=None, recall_rounds=(), fail=()):
        self.outputs = outputs or {}          # worker name -> list of fact dicts
        self.recall_rounds = list(recall_rounds)  # successive recall replies
        self.fail = set(fail)
        self.prompts = []

    def complete(self, prompt, *, max_tokens=4000):
        self.prompts.append(prompt)
        if "Recall Auditor" in prompt:
            return json.dumps(self.recall_rounds.pop(0)) if self.recall_rounds else "[]"
        for spec in WORKERS:
            if spec.title in prompt:
                if spec.name in self.fail:
                    raise RuntimeError("worker exploded")
                return json.dumps(self.outputs.get(spec.name, []))
        return "[]"


ARTIFACTS = [{"name": "Discovery Transcript", "kind": "transcript",
              "text": "Client wants a sonic logo. Budget twenty thousand."}]


# --------------------------------------------------------------------------- #
# Workers — prompts, fan-out, domain fencing.
# --------------------------------------------------------------------------- #
def test_ten_workers_each_own_one_domain():
    assert len(WORKERS) == 10
    assert set(WORKERS_BY_NAME) == {
        "budget", "timeline", "deliverables", "stakeholder", "creative",
        "campaign", "rights", "technical", "opportunity", "risk"}


def test_worker_prompt_carries_charge_schema_and_every_artifact():
    arts = ARTIFACTS + [{"name": "Uploaded RFP", "kind": "rfp", "text": "RFP body."}]
    for spec in WORKERS:
        p = build_worker_prompt(spec, arts, priors="values brass")
        assert spec.title in p and "responsible ONLY for" in p
        assert "Return ONLY a JSON array" in p
        # every worker receives every artifact, labeled for source attribution
        assert "ARTIFACT: Discovery Transcript" in p and "ARTIFACT: Uploaded RFP" in p
        # the recall posture: keep searching, never stop at the first find
        assert "keep searching" in p
        assert "values brass" in p                       # priors calibrate every worker


def test_engine_fans_out_every_worker_and_survives_a_worker_failure():
    fake = FakeProvider(
        outputs={"budget": [{"key": "budget_band", "value": "$20,000", "confidence": 90}]},
        fail={"timeline"})
    res = ext_engine.run(ARTIFACTS, provider=fake, recall_rounds=0)
    worker_prompts = [p for p in fake.prompts if "Recall Auditor" not in p]
    assert len(worker_prompts) == 10                      # all ten ran
    names = {w["name"]: w for w in res.report["workers"]}
    assert names["timeline"]["error"]                     # failure recorded…
    assert any(c["key"] == "budget_band" for c in res.candidates)  # …others landed


def test_domain_fence_drops_off_facet_and_off_kind_items():
    spec = WORKERS_BY_NAME["budget"]
    assert coerce_fact({"facet": "direction", "key": "mood", "value": "somber"}, spec) is None
    assert coerce_fact({"kind": "recommendation", "key": "x", "value": "y"}, spec) is None
    ok = coerce_fact({"key": "Music Budget!", "value": "$5k", "confidence": "80",
                      "evidence": "five for music", "speaker": "CD"}, spec)
    assert ok and ok["facet"] == "engagement" and ok["key"] == "music_budget"
    assert ok["confidence"] == 80 and ok["speaker"] == "CD"
    # the risk worker flags everything it extracts as a concern by default
    risk = coerce_fact({"key": "approval_risk", "value": "CMO unseen",
                        "kind": "open_question"}, WORKERS_BY_NAME["risk"])
    assert risk and risk["is_concern"] is True


# --------------------------------------------------------------------------- #
# Validation — duplicates, conflicts, impossible values (never reads the transcript).
# --------------------------------------------------------------------------- #
def _fact(key, value, *, facet="engagement", kind="fact", conf=None, worker="budget"):
    return {"worker": worker, "facet": facet, "key": key, "kind": kind, "value": value,
            "confidence": conf, "is_concern": False, "evidence": f"ev:{value}",
            "speaker": "", "timestamp": "", "artifact": "T"}


def test_validation_dedupes_and_keeps_best_confidence():
    rep = ext_validation.validate([
        _fact("budget_band", "$20,000", conf=60, worker="budget"),
        _fact("budget_band", "$20,000", conf=90, worker="campaign"),
    ])
    assert len(rep.facts) == 1 and rep.duplicates_removed == 1
    assert rep.facts[0]["confidence"] == 90              # corroboration lifts, not loses
    assert rep.facts[0]["corroborated_by"]               # both evidence trails survive


def test_validation_raises_a_flagged_question_on_true_conflicts_only():
    rep = ext_validation.validate([
        _fact("budget_band", "$20,000", conf=90),
        _fact("budget_band", "$40,000", conf=55),
        _fact("deliverables", ":30 cutdown"),
        _fact("deliverables", "stems"),                  # list slot: corroboration
    ])
    assert rep.conflicts == 1
    q = rep.questions[0]
    assert q["kind"] == "open_question" and q["is_concern"]
    assert q["key"] == "confirm_budget_band"
    assert "$20,000" in q["value"] and "$40,000" in q["value"]


def test_validation_drops_impossible_money_and_empty_values():
    rep = ext_validation.validate([
        _fact("budget_band", "$0"), _fact("deadline", "  "),
        _fact("budget_band", "$20,000"),
    ])
    assert rep.impossible_dropped == 2
    assert [f["value"] for f in rep.facts] == ["$20,000"]


# --------------------------------------------------------------------------- #
# Merge — evidence + alternates preserved; list slots union.
# --------------------------------------------------------------------------- #
def test_merge_preserves_evidence_and_alternates():
    out = ext_merge.merge([
        _fact("budget_band", "$20,000", conf=90),
        _fact("budget_band", "$40,000", conf=55),
    ])
    assert len(out) == 1
    c = out[0]
    assert c["value"] == "$20,000"                        # highest confidence is primary
    vj = c["value_json"]
    assert [a["value"] for a in vj["alternates"]] == ["$40,000"]   # ambiguity preserved
    assert any(e["quote"] == "ev:$20,000" for e in vj["evidence"])  # evidence preserved


def test_merge_unions_list_slots_instead_of_competing():
    out = ext_merge.merge([
        _fact("deliverables", ":30 cutdown, stems", conf=70),
        _fact("deliverables", ":15 cutdown, stems", conf=80),
    ])
    assert len(out) == 1
    v = out[0]["value"]
    assert ":30 cutdown" in v and ":15 cutdown" in v
    assert v.count("stems") == 1                          # union dedupes items


# --------------------------------------------------------------------------- #
# Recall — hunts omissions until a round comes back dry (bounded).
# --------------------------------------------------------------------------- #
def test_recall_loop_adds_missed_facts_then_stops_when_dry():
    fake = FakeProvider(
        outputs={"budget": [{"key": "budget_band", "value": "$20,000", "confidence": 90}]},
        recall_rounds=[
            [{"facet": "commercial", "key": "territory", "kind": "fact",
              "value": "North America", "confidence": 75, "evidence": "US + Canada"}],
            [],
        ])
    res = ext_engine.run(ARTIFACTS, provider=fake, recall_rounds=5)
    assert res.report["recall_added"] == 1
    assert res.report["recall_rounds"] == 2               # round 2 came back dry → stop
    assert any(c["key"] == "territory" for c in res.candidates)


def test_recall_prompt_shows_the_inventory_and_never_restates_it():
    facts = [_fact("budget_band", "$20,000")]
    p = ext_recall.build_recall_prompt(ARTIFACTS, facts)
    assert "what facts were MISSED" in p.lower() or "MISSED" in p
    assert "engagement.budget_band" in p                  # the inventory it audits against
    assert "ARTIFACT: Discovery Transcript" in p          # …with the original source


# --------------------------------------------------------------------------- #
# The board is the only destination — integration through the intake pipeline.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def webctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "x.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mods = {}
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "extraction_bridge"):
        mods[m] = importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    conn = mods["db"].connect()
    mods["db"].init_db(conn)
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    opp_id = mods["db"].insert_opportunity(conn, Opportunity(
        client="Hoagies", need="Sonic logo", description="Emo launch.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    return mods, conn, opp_id


def test_engine_candidates_land_on_the_board_with_capture_and_evidence(webctx, monkeypatch):
    mods, conn, opp_id = webctx
    intake, dbm = mods["campaign_intake"], mods["db"]
    fake = FakeProvider(outputs={
        "budget": [{"key": "budget_band", "value": "$20,000", "confidence": 90,
                    "evidence": "twenty for the music", "speaker": "Pat",
                    "artifact": "Discovery Transcript"}],
        "risk": [{"key": "approval_risk", "kind": "open_question",
                  "value": "CMO has not seen the direction"}],
    })
    monkeypatch.setattr("chordential_oia.extraction.providers.get_provider", lambda: fake)
    monkeypatch.setattr("chordential_oia.extraction.providers.is_enabled", lambda: True)
    opp = dbm.get_opportunity(conn, opp_id)
    summary = intake.ingest_opportunity(conn, opp, intake.OBJECTIVE,
                                        "Budget is $20,000.", modality="transcript")
    assert summary["added"] >= 2
    rows = {(r["facet"], r["key"]): r
            for r in dbm.list_ci_fields(conn, summary["ci_id"])}
    band = rows[("engagement", "budget_band")]
    assert band["value"] == "$20,000"
    assert band["capture_id"] == summary["capture_id"]    # provenance: the raw evidence
    vj = json.loads(band["value_json"])
    assert vj["evidence"][0]["quote"] == "twenty for the music"   # evidence on the field
    assert vj["evidence"][0]["speaker"] == "Pat"
    risk = rows[("engagement", "approval_risk")]
    assert risk["kind"] == "open_question" and risk["is_concern"]
    assert risk["status"] == "open"                       # lands OPEN — human disposes
    # the run report is preserved on the capture envelope (observability as evidence)
    cap = dbm.get_capture(conn, summary["capture_id"])
    meta = json.loads(cap["metadata_json"])
    assert meta["extraction_run"]["provider"] == "fake"
    assert len(meta["extraction_run"]["workers"]) == 10
    # every worker saw every artifact, incl. Opportunity Intelligence context
    assert any("Opportunity Intelligence" in p for p in fake.prompts)


def test_null_provider_leaves_intake_byte_for_byte_deterministic(webctx):
    mods, conn, opp_id = webctx
    intake, dbm = mods["campaign_intake"], mods["db"]
    assert not ext_providers.is_enabled()                 # no key in this env
    opp = dbm.get_opportunity(conn, opp_id)
    summary = intake.ingest_opportunity(
        conn, opp, intake.OBJECTIVE,
        "Budget is $18,000 - $24,000. Need :30 cutdowns by June 5.")
    rows = {(r["facet"], r["key"]): r["value"]
            for r in dbm.list_ci_fields(conn, summary["ci_id"])}
    assert ("engagement", "budget_band") in rows          # heuristics still extract
    cap = dbm.get_capture(conn, summary["capture_id"])
    assert "extraction_run" not in json.loads(cap["metadata_json"])  # engine stayed out


def test_provider_meltdown_never_blocks_the_capture(webctx, monkeypatch):
    mods, conn, opp_id = webctx
    intake, dbm = mods["campaign_intake"], mods["db"]

    class Meltdown:
        name, model, available = "melt", "m", True
        def complete(self, prompt, *, max_tokens=4000):
            raise RuntimeError("provider on fire")

    monkeypatch.setattr("chordential_oia.extraction.providers.get_provider", Meltdown)
    monkeypatch.setattr("chordential_oia.extraction.providers.is_enabled", lambda: True)
    opp = dbm.get_opportunity(conn, opp_id)
    summary = intake.ingest_opportunity(conn, opp, intake.OBJECTIVE,
                                        "Budget is $18,000 - $24,000.")
    assert summary["capture_id"]                          # capture landed regardless
    rows = {(r["facet"], r["key"]) for r in dbm.list_ci_fields(conn, summary["ci_id"])}
    assert ("engagement", "budget_band") in rows          # heuristic fallback extracted


def test_evidence_page_shows_engine_state_and_per_capture_method(webctx, monkeypatch):
    """The Evidence page must make the extraction METHOD visible — so "the update made no
    improvement" is answerable at a glance: engine off → an honest baseline banner + how to
    enable; engine on → the run report (specialists, recall, conflicts) per capture."""
    from fastapi.testclient import TestClient
    mods, conn, opp_id = webctx
    intake, dbm, app_mod = mods["campaign_intake"], mods["db"], __import__(
        "chordential_oia.web.app", fromlist=["app"])
    # 1) Engine OFF (no key): the baseline banner + per-capture 'baseline' badge show.
    intake.ingest_opportunity(conn, dbm.get_opportunity(conn, opp_id), intake.OBJECTIVE,
                              "Budget is $20,000.", modality="notes")
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}/evidence").text
    assert "AI extraction crew is OFF" in page and "ANTHROPIC_API_KEY" in page
    assert "baseline" in page

    # 2) Engine ON: the same page shows the run report instead.
    fake = FakeProvider(outputs={
        "budget": [{"key": "budget_band", "value": "$20,000", "confidence": 90}]})
    monkeypatch.setattr("chordential_oia.extraction.providers.get_provider", lambda: fake)
    monkeypatch.setattr("chordential_oia.extraction.providers.is_enabled", lambda: True)
    intake.ingest_opportunity(conn, dbm.get_opportunity(conn, opp_id), intake.OBJECTIVE,
                              "The budget is twenty thousand dollars.", modality="transcript")
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}/evidence").text
    assert "10-agent engine" in page and "specialists" in page
    assert "AI extraction crew is OFF" not in page          # crew is on now


def test_model_failure_surfaces_the_reason_not_a_silent_fallback(webctx, monkeypatch):
    """A key IS set but the model call fails (bad model id / auth) → the run report carries
    the real error and the Evidence page shows it, so 'no improvement' is diagnosable — not
    a silent fall-back to the keyword baseline."""
    from fastapi.testclient import TestClient

    class BadModel:
        name, model, available = "anthropic", "claude-sonnet-5", True
        def __init__(self): self.last_error = ""
        def complete(self, prompt, *, max_tokens=4000):
            self.last_error = ("BadRequestError: 400 - Your credit balance is too low to "
                               "access the Anthropic API. Please go to Plans & Billing.")
            return None

    mods, conn, opp_id = webctx
    intake, dbm = mods["campaign_intake"], mods["db"]
    monkeypatch.setattr("chordential_oia.extraction.providers.get_provider", BadModel)
    monkeypatch.setattr("chordential_oia.extraction.providers.is_enabled", lambda: True)
    summary = intake.ingest_opportunity(conn, dbm.get_opportunity(conn, opp_id),
                                        intake.OBJECTIVE, "Budget is $18,000 - $24,000.")
    # the capture still lands (heuristic fallback), AND the failure reason is recorded
    cap = dbm.get_capture(conn, summary["capture_id"])
    run = json.loads(cap["metadata_json"])["extraction_run"]
    assert "credit balance is too low" in run["provider_error"]
    app_mod = __import__("chordential_oia.web.app", fromlist=["app"])
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}/evidence").text
    assert "engine error" in page and "credit balance is too low" in page
    # the REMEDY is the precise one for THIS error — API billing, and it names the
    # Max/Pro-vs-API distinction (the actual confusion), not the model knob
    assert "console.anthropic.com" in page
    assert "SEPARATE from API billing" in page
    assert "CHORDENTIAL_EXTRACTION_MODEL" not in page      # would mislead for a billing error


def test_debrief_stance_keeps_its_dedicated_subjective_path(webctx, monkeypatch):
    mods, conn, opp_id = webctx
    intake, dbm = mods["campaign_intake"], mods["db"]
    fake = FakeProvider()
    monkeypatch.setattr("chordential_oia.extraction.providers.get_provider", lambda: fake)
    monkeypatch.setattr("chordential_oia.extraction.providers.is_enabled", lambda: True)
    opp = dbm.get_opportunity(conn, opp_id)
    intake.ingest_opportunity(conn, opp, intake.DEBRIEF,
                              "I'd recommend leading with the anthem.")
    assert fake.prompts == []                             # fact workers never ran
