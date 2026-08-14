"""A perfect read filed one drawer over is worth nothing.

Second live discovery call, 2026-08-14. The operator stated the budget as plainly as it
can be stated:

    "Speaking of budget, I want to be straight up with you. The number that I've been
     given is roughly 25. No, no, 30,000. And that's, that's all in including any
     licensing."

The ten-agent engine read it correctly, spoken correction and all, and returned:

    FACT  Music budget is roughly $30,000, all-in including any licensing.
          · commercial/budget_band

And the Budget field on the page was **empty**, showing its placeholder, while that
sentence sat in the evidence column beside it.

The canonical slot is keyed ``(engagement, budget_band, fact)``. The engine's key was
already canonical; its FACET was not. `_canonicalise` snapped keys and left facets alone,
so the lookup missed by one column. Deliverables went the same way.

This is the same defect as the first comprehension call — where the answers landed under
"Production Budget" and "Seasonality" — fixed then for the key only. A canonical key
belongs to exactly one facet; that is what makes it canonical. So the facet is DERIVED,
never accepted, and the estimate/brief/proposal that read those slots get the number.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "ci.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    from chordential_oia.web import db as dbm
    dbm = importlib.reload(dbm)
    from chordential_oia.web import campaign_intelligence as ci
    ci = importlib.reload(ci)
    from chordential_oia.web import campaign_intake as intake
    intake = importlib.reload(intake)
    conn = dbm.connect()
    dbm.init_db(conn)
    oid = dbm.insert_opportunity(conn, Opportunity(
        client="Champ Atlantic", need="Fall product launch", description="",
        buyer_type=BuyerType.BRAND, music_requirement=MusicRequirement.ORIGINAL))
    try:
        yield dbm, ci, intake, conn, dbm.get_opportunity(conn, oid)
    finally:
        conn.close()


# ── the slot itself ──────────────────────────────────────────────────────────────
def test_the_facet_is_derived_from_the_key_not_taken_from_the_model(env):
    """THE bug, in one line. `commercial/budget_band` is the exact pair the live engine
    returned for a budget it had read perfectly."""
    _dbm, ci, _intake, _conn, _opp = env
    assert ci.canonical_slot("commercial", "budget_band", "fact") == (
        "engagement", "budget_band", "fact")


@pytest.mark.parametrize("facet,key", [
    ("commercial", "budget_band"),      # what the live call actually produced
    ("commercial", "music_budget"),     # key alias AND wrong facet, together
    ("delivery", "deliverables"),
    ("creative", "deliverables_list"),
    ("timeline", "seasonality"),
    ("scheduling", "deadline"),
    ("people", "final_approver"),
])
def test_a_canonical_answer_lands_in_its_slot_from_wherever_it_was_filed(env, facet, key):
    _dbm, ci, _intake, _conn, _opp = env
    got_facet, got_key, _kind = ci.canonical_slot(facet, key, "fact")
    assert (got_facet, got_key, "fact") in ci.CANONICAL_BY_KEY, (
        f"{facet}/{key} did not reach a canonical slot; it landed at {got_facet}/{got_key}")


def test_an_open_question_about_the_budget_stays_an_open_question(env):
    """Only FACTS are moved into a slot. The live call raised "confirm the currency for
    the ~$30,000" — a question, not a value, and filing it as the budget would be worse
    than losing it."""
    _dbm, ci, _intake, _conn, _opp = env
    facet, key, kind = ci.canonical_slot("observed", "currency", "open_question")
    assert kind == "open_question"
    assert (facet, key, kind) not in ci.CANONICAL_BY_KEY


def test_a_field_with_no_canonical_meaning_is_left_exactly_where_it_was(env):
    """The dynamic field — the thing that let "weekly check-ins" be captured at all. It
    must survive a change whose whole purpose is to move things."""
    _dbm, ci, _intake, _conn, _opp = env
    assert ci.canonical_slot("commercial", "payment_terms", "fact") == (
        "commercial", "payment_terms", "fact")
    assert ci.canonical_slot("observed", "meeting_cadence", "fact") == (
        "observed", "meeting_cadence", "fact")


# ── end to end, through the intake the transcript really travels ─────────────────
def test_the_budget_from_the_call_reaches_the_budget_field(env, monkeypatch):
    _dbm, ci, intake, conn, opp = env
    ci_row = ci.ensure_for_opportunity(conn, opp)

    # exactly what the ten-agent engine returned for this call, facets included
    engine_output = [
        {"facet": "commercial", "key": "budget_band", "kind": "fact", "confidence": 90,
         "value": "Music budget is roughly $30,000, all-in including any licensing."},
        {"facet": "delivery", "key": "deliverables", "kind": "fact", "confidence": 85,
         "value": "Original master for the ~4-minute launch film, stems on all "
                  "deliverables, instrumental only (no vocals)."},
        {"facet": "commercial", "key": "payment_terms", "kind": "open_question",
         "confidence": 60, "value": "No payment terms were mentioned — confirm."},
    ]
    monkeypatch.setattr(intake, "extract", lambda *a, **k: list(engine_output))

    lane = intake.intake_lanes.LANES_BY_KEY["discovery_call"]
    intake._apply_capture(conn, ci_row["id"], lane,
                          "…the number I've been given is roughly 25. No, no, 30,000…",
                          opp_id=opp["id"])

    fields = {(f["facet"], f["key"], f["kind"]): f
              for f in _dbm.list_ci_fields(conn, ci_row["id"])}
    budget = fields.get(("engagement", "budget_band", "fact"))
    assert budget is not None, (
        "the budget was read correctly and still did not reach the Budget field")
    assert "30,000" in budget["value"]

    assert ("engagement", "deliverables", "fact") in fields, "same for Deliverables"
    # …and the question stayed a question, where a human still has to answer it
    assert ("commercial", "payment_terms", "open_question") in fields


# ── the calls already captured under the old behaviour ───────────────────────────
def test_the_repair_moves_a_call_that_was_already_misfiled(env):
    """Fixing the intake only helps the NEXT call. The operator's real one is already in
    the database with the right answer in the wrong drawer, so the boot repair puts it
    where the Budget field looks."""
    dbm, ci, _intake, conn, opp = env
    ci_row = ci.ensure_for_opportunity(conn, opp)
    dbm.upsert_ci_field(conn, ci_row["id"], "commercial", "budget_band", "fact",
                        value="Music budget is roughly $30,000, all-in including any "
                              "licensing.", source="discovery call")
    dbm.upsert_ci_field(conn, ci_row["id"], "commercial", "payment_terms", "fact",
                        value="Net 30 discussed.", source="discovery call")

    assert dbm.refile_ci_fields_to_canonical_slots(conn) == 1

    fields = {(f["facet"], f["key"], f["kind"]): f
              for f in dbm.list_ci_fields(conn, ci_row["id"])}
    assert "30,000" in fields[("engagement", "budget_band", "fact")]["value"]
    assert ("commercial", "payment_terms", "fact") in fields, "a dynamic field must not move"
    assert dbm.refile_ci_fields_to_canonical_slots(conn) == 0, "must be idempotent"


def test_the_repair_never_overwrites_a_value_a_human_already_put_there(env):
    """A repair that loses the operator's own answer is worse than the bug it fixes."""
    dbm, ci, _intake, conn, opp = env
    ci_row = ci.ensure_for_opportunity(conn, opp)
    dbm.upsert_ci_field(conn, ci_row["id"], "engagement", "budget_band", "fact",
                        value="$30,000 confirmed with Maria", source="operator",
                        status="confirmed")
    dbm.upsert_ci_field(conn, ci_row["id"], "commercial", "budget_band", "fact",
                        value="machine guess", source="discovery call")

    assert dbm.refile_ci_fields_to_canonical_slots(conn) == 0
    fields = {(f["facet"], f["key"], f["kind"]): f
              for f in dbm.list_ci_fields(conn, ci_row["id"])}
    assert fields[("engagement", "budget_band", "fact")]["value"] == "$30,000 confirmed with Maria"
    assert ("commercial", "budget_band", "fact") in fields, (
        "the loser stays visible rather than being deleted; a person decides")


# ── one slot, one occupant ───────────────────────────────────────────────────────
def test_the_distractor_never_takes_the_budget_slot_from_the_real_figure(env):
    """Live call two, verbatim from the page: Budget read

        "Total production budget for the overall film (not the music) is approximately
         $900,000"

    while the engine's own open question referred to "the $55k-$65k budget". Both facts
    reached the slot and the LAST WRITE WON. Last write winning is not a tie-break, it is a
    coin toss with a client-facing number on it — and the loser here even carried "(not the
    music)" in its own text."""
    _dbm, _ci, intake, _conn, _opp = env
    out = {c["key"]: c["value"] for c in intake._canonicalise([
        {"facet": "commercial", "key": "budget_band", "kind": "fact", "confidence": 90,
         "value": "Music budget is $55,000-$65,000, hard ceiling, USD, license included."},
        {"facet": "commercial", "key": "production_budget", "kind": "fact", "confidence": 95,
         "value": "Total production budget for the overall film (not the music) is ~$900,000"},
    ])}
    assert "55,000" in out["budget_band"]
    assert "900,000" not in out["budget_band"]
    assert "900,000" in out["production_budget"], "the loser keeps its own name, not the bin"


def test_an_exact_key_outranks_an_alias_even_at_lower_confidence(env):
    """An exact key is the EXTRACTOR naming the slot. An alias is us asserting two words
    mean the same thing — the weaker claim, and the one that has been wrong twice."""
    _dbm, _ci, intake, _conn, _opp = env
    out = {c["key"]: c["value"] for c in intake._canonicalise([
        {"facet": "commercial", "key": "fee", "kind": "fact", "confidence": 99,
         "value": "via an alias"},
        {"facet": "commercial", "key": "budget_band", "kind": "fact", "confidence": 10,
         "value": "under its own name"},
    ])}
    assert out["budget_band"] == "under its own name"
    assert out["fee"] == "via an alias"


def test_two_aliases_are_settled_by_confidence_not_by_arrival_order(env):
    _dbm, _ci, intake, _conn, _opp = env
    out = {c["key"]: c["value"] for c in intake._canonicalise([
        {"facet": "x", "key": "fee", "kind": "fact", "confidence": 40, "value": "weaker"},
        {"facet": "x", "key": "budget_range", "kind": "fact", "confidence": 95,
         "value": "stronger"},
    ])}
    assert out["budget_band"] == "stronger"
    assert out["fee"] == "weaker"


def test_nothing_is_ever_dropped_by_the_contest(env):
    _dbm, _ci, intake, _conn, _opp = env
    src = [
        {"facet": "a", "key": "budget_band", "kind": "fact", "confidence": 90, "value": "1"},
        {"facet": "b", "key": "music_budget", "kind": "fact", "confidence": 80, "value": "2"},
        {"facet": "c", "key": "fee", "kind": "fact", "confidence": 70, "value": "3"},
        {"facet": "d", "key": "weekly_cadence", "kind": "fact", "confidence": 60, "value": "4"},
    ]
    out = intake._canonicalise(src)
    assert len(out) == 4
    assert {c["value"] for c in out} == {"1", "2", "3", "4"}
    assert sum(1 for c in out if (c["facet"], c["key"], c["kind"])
               == ("engagement", "budget_band", "fact")) == 1, "exactly one occupant"
    assert src[1]["key"] == "music_budget", "the caller's list must not be mutated"
