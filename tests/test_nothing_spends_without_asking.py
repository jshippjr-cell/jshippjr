"""Nothing spends money unless a human asked for it.

On 2026-08-13 the operator's Anthropic organisation ran out of credit and the API was
switched off — while the console meter read "This month: $0.00 of $10 cap". Both were
true: the cap only ever saw ONE caller. Campaign Intake recorded what it spent; the
decision-maker engine, outreach drafting, inbox triage and the call simulator each called
the API and recorded nothing. A ceiling cannot hold up money it cannot see.

And production ran six of those engines on a timer (render.yaml set
CHORDENTIAL_AUTONOMOUS=1, against the code's own documented default of OFF), so the
unmetered calls were being made unattended until the balance hit zero.

A cap alone would not have been enough: stopping at $10 still spends $10 nobody approved.
So the rule is approval, with the cap as a second floor underneath it — and the default
for anything unattended is no.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("CHORDENTIAL_EXTRACTION_ENGINE", raising=False)
    monkeypatch.setenv("CHORDENTIAL_EXTRACTION_MONTHLY_CAP", "10")


def _budget():
    from chordential_oia.web import ai_budget
    return ai_budget


def test_unapproved_work_cannot_spend(monkeypatch):
    """The rule. A scheduler tick has no approver, so it gets the free path."""
    ab = _budget()
    ok, why = ab.may_spend("decision-maker discovery")
    assert ok is False
    assert "nobody approved" in why


def test_an_approved_scope_can_spend(monkeypatch):
    ab = _budget()
    monkeypatch.setattr(ab, "spent_this_month", lambda: 0.0)
    with ab.approved_by("operator"):
        ok, why = ab.may_spend("intake extraction")
    assert ok is True, why


def test_approval_does_not_leak_out_of_its_scope(monkeypatch):
    """If it did, one Analyze press would licence every later background call."""
    ab = _budget()
    monkeypatch.setattr(ab, "spent_this_month", lambda: 0.0)
    with ab.approved_by("operator"):
        assert ab.may_spend("x")[0] is True
    assert ab.may_spend("x")[0] is False


def test_the_cap_is_a_second_floor_under_an_approved_run(monkeypatch):
    ab = _budget()
    monkeypatch.setattr(ab, "spent_this_month", lambda: 10.50)
    with ab.approved_by("operator"):
        ok, why = ab.may_spend("intake extraction")
    assert ok is False and "cap" in why


def test_a_missing_key_or_a_dead_switch_stops_it(monkeypatch):
    ab = _budget()
    with ab.approved_by("operator"):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert ab.may_spend("x")[0] is False
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("CHORDENTIAL_EXTRACTION_ENGINE", "0")
        assert ab.may_spend("x")[0] is False


def test_an_unreadable_ledger_is_not_a_licence_to_spend(monkeypatch):
    """If the ledger cannot be read we must not silently treat spend as zero forever —
    the gate still requires approval, which is what actually holds the line."""
    ab = _budget()
    monkeypatch.setattr(ab, "spent_this_month",
                        lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert ab.may_spend("x")[0] is False        # unapproved: no


@pytest.mark.parametrize("module,func", [
    ("decision_makers", "_default_llm"),
    ("outreach_engine", "_default_llm"),
    ("simulator", "_default_buyer_llm"),
])
def test_every_paid_caller_goes_through_the_gate(module, func):
    """Each of these called the API with nothing recorded. If one loses its gate, the
    meter goes back to under-counting and the cap goes back to being decorative."""
    import importlib
    import inspect
    m = importlib.import_module(f"chordential_oia.web.{module}")
    src = inspect.getsource(getattr(m, func))
    assert "ai_budget.may_spend" in src, f"{module}.{func} can spend unmetered"
    assert 'os.environ.get("ANTHROPIC_API_KEY")' not in src, (
        f"{module}.{func} still decides for itself whether it may spend")


def test_intake_and_triage_are_gated_too():
    """The other two paid callers, by the same rule."""
    import inspect
    from chordential_oia.web import campaign_intake, triage
    assert "_may_spend()" in inspect.getsource(triage._llm_extract)
    intake = inspect.getsource(campaign_intake)
    assert "ai_budget.may_spend" in intake, "intake's paid seam is ungated"


def test_a_booked_calls_transcript_still_gets_the_full_read():
    """The line is asked-for versus speculative, NOT interactive versus background.

    A discovery call is scheduled by a person, attended by a person, and recorded because
    they asked for it to be — so the ten-agent read of its transcript is the machine
    finishing the job it was given, and it stays automatic (ADR-0023). Gating it behind
    "a request thread triggered this" broke the product for one commit; this is the test
    that keeps it broken-proof."""
    import inspect
    from chordential_oia.web import campaign_intake
    src = inspect.getsource(campaign_intake.ingest_transcript)
    assert "ai_budget.approved_by" in src, (
        "a transcript from a call the operator booked must get the full read")


def test_the_speculative_sweeps_are_the_ones_held_back(monkeypatch):
    """And the ones that emptied the balance stay held back."""
    ab = _budget()
    for sweep in ("decision-maker discovery", "outreach drafting", "inbox triage"):
        ok, why = ab.may_spend(sweep)
        assert ok is False and "nobody approved" in why, sweep


def test_the_analyze_button_is_the_approved_scope():
    """The one handler a person triggers, which already shows the cost and confirms."""
    import inspect
    from chordential_oia.web import opportunity_routes
    src = inspect.getsource(opportunity_routes.opp_intelligence_analyze)
    assert "ai_budget.approved_by" in src


def test_production_no_longer_runs_the_engines_unattended():
    """render.yaml set "1" against the code's documented default of OFF. That override
    is what turned unmetered calls into unmetered calls ON A TIMER."""
    from pathlib import Path
    y = Path(__file__).resolve().parents[1] / "render.yaml"
    text = y.read_text(encoding="utf-8")
    block = text.split("CHORDENTIAL_AUTONOMOUS", 1)[1].split("- key:", 1)[0]
    assert '"0"' in block, "the autonomous engines must not default to on"


def test_recording_a_spend_reaches_the_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "s.sqlite"))
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)
    conn.close()

    ab = _budget()
    importlib.reload(ab)
    ab.record("decision-maker discovery", cost=0.42, calls=3,
              in_tokens=1000, out_tokens=500)
    assert ab.spent_this_month() == pytest.approx(0.42)


def test_the_estimate_rounds_against_us():
    """Under-counting is how a ledger lets a balance reach zero."""
    ab = _budget()
    assert ab.estimate_cost(1_000_000, 0) >= 3.0
    assert ab.estimate_cost(0, 1_000_000) >= 15.0
