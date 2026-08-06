"""What a writer is paid, and what they keep.

Before this the estimate carried a flat `Composer` line of 20h × $150 = $3,000 whatever
the job — 26.9% of an $11,133 :30 spot and **3.9% of a $76,191 orchestral anthem**, the
same money for the harder brief. Nothing in the system said what a writer should be paid,
so the quote, the payout and the sentence said out loud to a composer had no reason to
agree with each other.

Two properties carry the weight:

* `test_the_fee_excludes_money_that_passes_through_to_players` — the fee is a share of
  NET creative revenue, because a writer's fee must not rise because an orchestra was
  hired.
* `test_a_writer_with_no_publishing_entity_is_not_written_onto_the_cue_sheet` — the
  ADR-0050 rule applied to money. A share assigned to an entity that does not exist at
  a PRO is not generosity; it is an unclaimed royalty and a wrong line on a filed
  legal document.
"""

import importlib

import pytest

from chordential_oia import compensation
from chordential_oia.estimation import EstimationEngine
from chordential_oia.models import MusicDiscipline, Opportunity
from chordential_oia.models import MusicDiscipline as _MD
from chordential_oia.talent import Talent
from chordential_oia.web import db as db_mod


def _mk_talent(conn, name, disciplines=("composition",), rate=None, rate_unit="hourly"):
    return db_mod.insert_talent(conn, Talent(
        name=name, email="", disciplines=[_MD(d) for d in disciplines],
        rate=rate, rate_unit=rate_unit))

E = EstimationEngine()


def _est(need, desc=""):
    return E.estimate(Opportunity(client="X", need=need, description=desc),
                      discipline=MusicDiscipline.COMPOSITION)


# --------------------------------------------------------------------------- #
# The fee
# --------------------------------------------------------------------------- #
def test_the_fee_excludes_money_that_passes_through_to_players():
    """On the orchestral anthem, $32,125 of $76,191 is players and a room. A share of
    GROSS would pay a writer more because an orchestra was booked, which is not a fact
    about their work."""
    gross = compensation.writer_fee(76191.0, 0.0).total
    net = compensation.writer_fee(76191.0, 32125.0).total
    assert net < gross
    assert net == pytest.approx(44066.0 * compensation.COMPOSER_SHARE, rel=1e-6)


def test_the_policy_agrees_with_the_price_the_engine_already_quoted():
    """Calibration, not invention: 30% of net on a :30 national spot lands within $20
    of the $3,000 the estimator already modelled for that job. If these drift apart,
    the number quoted to a client and the number promised to a composer have stopped
    being the same arithmetic."""
    est = _est(":30 spot", "National broadcast :30 spot.")
    assert est.writer_fee.total == pytest.approx(2980.0, abs=1.0)
    assert abs(est.writer_fee.total - 3000.0) < 25.0


def test_the_flat_line_was_the_bug_and_the_share_now_scales():
    """The same writer got $3,000 on an $11k spot and $3,000 on a $76k anthem."""
    spot = _est(":30 spot", "National broadcast :30 spot.")
    anthem = _est(":60 anthem with :30 and :15 cutdowns",
                  "National :60 anthem with :30 and :15 cutdowns, full orchestra.")
    assert anthem.writer_fee.total > spot.writer_fee.total * 4


def test_a_writer_who_also_orchestrates_is_paid_for_two_jobs():
    one = compensation.writer_fee(100_000.0, 0.0)
    two = compensation.writer_fee(100_000.0, 0.0, orchestrates=True)
    assert one.share == compensation.COMPOSER_SHARE
    assert two.share == compensation.COMPOSER_SHARE_WITH_SESSION
    assert two.total > one.total


def test_the_uplift_never_claims_a_session_that_did_not_happen():
    """The first wiring of this told a composer they were paid extra to "produce the
    session" on a SAMPLED score with no session. The rate was arguable; the reason was
    false, and a fee whose stated basis is untrue is worse than a lower one."""
    sampled = compensation.writer_fee(100_000.0, 0.0, orchestrates=True,
                                      live_session=False)
    live = compensation.writer_fee(100_000.0, 0.0, orchestrates=True,
                                   live_session=True)
    assert "no live session" in sampled.basis
    assert "recording session" in live.basis
    assert sampled.total == live.total, "the RATE was never the thing that was wrong"


def test_a_sampled_feature_is_not_billed_as_producing_a_session():
    """End to end, through the estimator that got it wrong."""
    est = _est("Original score for a feature film",
               "Feature film score. 45 minutes across 28 cues, orchestral, sampled, "
               "no live players. National.")
    assert est.session_cost == 0
    assert "no live session" in est.writer_fee.basis


def test_the_fee_splits_across_co_writers():
    fee = compensation.writer_fee(10_000.0, 0.0, writers=2)
    assert fee.per_writer == pytest.approx(fee.total / 2)
    assert "split 2 ways" in fee.explanation


def test_the_fee_can_be_explained_without_re_deriving_it():
    """A number you cannot explain in one sentence is a number you will not say out
    loud to a composer."""
    fee = compensation.writer_fee(11133.0, 1200.0)
    assert "30% of $9,933 net creative revenue" in fee.explanation
    assert "$2,980" in fee.explanation


def test_the_fee_never_goes_negative():
    """A session that costs more than the job is a bad job, not a debt owed by the
    writer."""
    assert compensation.writer_fee(1_000.0, 9_000.0).total == 0.0


# --------------------------------------------------------------------------- #
# The publishing split
# --------------------------------------------------------------------------- #
def test_publishing_is_split_fifty_fifty_with_a_registered_writer():
    rows = compensation.publisher_rows(
        [{"name": "Dana", "publisher": "Whitfield Music", "pro": "BMI"}])
    assert {r.name: r.share for r in rows} == {
        compensation.HOUSE_PUBLISHER: 0.5, "Whitfield Music": 0.5}


def test_a_writer_with_no_publishing_entity_is_not_written_onto_the_cue_sheet():
    """The ADR-0050 rule, applied to money. A composer who has never registered as a
    publisher cannot collect on a publisher line — writing their personal name there
    pays them nothing and tells them, falsely, that they are covered."""
    rows = compensation.publisher_rows([{"name": "Dana", "publisher": ""}])
    payable = [r for r in rows if r.share > 0]
    assert len(payable) == 1 and payable[0].name == compensation.HOUSE_PUBLISHER
    assert payable[0].share == 1.0
    held = [r for r in rows if r.held_for]
    assert held and held[0].held_for == "Dana", "the debt was not named"


def test_the_unpaid_half_is_reported_as_a_task():
    """So "publishing 50/50" turns into "get Dana's publishing entity" rather than
    quietly not happening."""
    assert compensation.unassigned_publishing(
        [{"name": "Dana", "publisher": ""},
         {"name": "Sam", "publisher": "Reyes Music"}]) == ["Dana"]


def test_shares_always_total_one_hundred_percent():
    for writers in ([], [{"name": "A", "publisher": "AP"}],
                    [{"name": "A", "publisher": "AP"}, {"name": "B", "publisher": ""}],
                    [{"name": "A", "publisher": "AP"}, {"name": "B", "publisher": "BP"}]):
        rows = compensation.publisher_rows(writers)
        assert sum(r.share for r in rows) == pytest.approx(1.0), writers


def test_the_cue_sheet_carries_the_split():
    from chordential_oia.delivery import build_cue_sheet
    row = build_cue_sheet(
        {"client": "AURORA", "need": "Winter anthem"},
        [{"role": "Composer", "talent_name": "Dana Whitfield", "talent_pro": "BMI",
          "talent_publisher": "Whitfield Music"},
         {"role": "Mixer", "talent_name": "Sam Reyes"}])[0]
    assert row.publisher == "Chordential Music, Whitfield Music"
    assert row.publisher_share == "50%, 50%"
    # The mixer is paid, and is not an author — they take no writer or publisher share.
    assert "Sam Reyes" not in row.composers and "Sam Reyes" not in row.publisher


def test_the_cue_sheet_holds_the_share_when_there_is_no_entity():
    from chordential_oia.delivery import build_cue_sheet
    row = build_cue_sheet(
        {"client": "AURORA", "need": "Winter anthem"},
        [{"role": "Composer", "talent_name": "Dana Whitfield", "talent_pro": "BMI"}])[0]
    assert row.publisher == "Chordential Music"
    assert row.publisher_share == "100%"
    assert row.composers == "Dana Whitfield", "the writer credit was lost too"


# --------------------------------------------------------------------------- #
# The payout ledger
# --------------------------------------------------------------------------- #
@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "c.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    importlib.reload(db_mod)
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    return mod


def test_a_writer_with_no_rate_is_owed_the_policy_fee_not_zero(app_mod):
    """The number a composer was promised used to live only in the conversation where
    it was said — the ledger seeded them at $0.00."""
    conn = db_mod.connect()
    proj = conn.execute(
        "SELECT id, opp_id FROM projects WHERE opp_id IS NOT NULL LIMIT 1").fetchone()
    pid = proj["id"]
    tid = _mk_talent(conn, "Dana Whitfield")
    db_mod.add_assignment(conn, pid, "Composer", tid)
    db_mod.ensure_project_payouts(conn, pid)
    rows = [r for r in db_mod.list_payouts(conn) if r["talent_id"] == tid]
    conn.close()
    assert rows, "no payout was created for the writer"
    assert rows[0]["amount"] > 0, "the writer was seeded at zero"
    assert rows[0]["rate_unit"] == "project"


def test_a_negotiated_rate_still_beats_the_policy(app_mod):
    """The policy is the DEFAULT, not an override. A rate agreed with a specific
    person is the deal that was actually struck."""
    conn = db_mod.connect()
    pid = conn.execute(
        "SELECT id FROM projects WHERE opp_id IS NOT NULL LIMIT 1").fetchone()["id"]
    tid = _mk_talent(conn, "Dana Whitfield", rate=7500.0, rate_unit="project")
    db_mod.add_assignment(conn, pid, "Composer", tid)
    db_mod.ensure_project_payouts(conn, pid)
    rows = [r for r in db_mod.list_payouts(conn) if r["talent_id"] == tid]
    conn.close()
    assert rows[0]["amount"] == 7500.0


def test_a_mixer_is_not_paid_a_writers_fee(app_mod):
    """Only authors share the writer fee. A mixer is paid for mixing."""
    conn = db_mod.connect()
    pid = conn.execute(
        "SELECT id FROM projects WHERE opp_id IS NOT NULL LIMIT 1").fetchone()["id"]
    tid = _mk_talent(conn, "Sam Reyes", disciplines=("mixing",))
    db_mod.add_assignment(conn, pid, "Mixer", tid)
    db_mod.ensure_project_payouts(conn, pid)
    rows = [r for r in db_mod.list_payouts(conn) if r["talent_id"] == tid]
    conn.close()
    assert rows[0]["amount"] == 0.0, "a mixer was seeded with a writer's fee"


def test_a_publishing_entity_round_trips(app_mod):
    conn = db_mod.connect()
    tid = _mk_talent(conn, "Dana Whitfield")
    db_mod.update_talent_profile(conn, tid, "Dana Whitfield", "", ["composition"],
                                 "", "", "", "", pro="BMI",
                                 publisher="Whitfield Music")
    row = db_mod.get_talent(conn, tid)
    conn.close()
    assert row["publisher"] == "Whitfield Music"
    assert row["pro"] == "BMI"
