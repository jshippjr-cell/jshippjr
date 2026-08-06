"""One relationship stage, over both halves of the evidence.

The defect this closes, stated as the two engines actually behaved:

* the Buyer Graph (`/buyers`) staged a company from `opportunities` + `outreach_events`
  as Cold / Warming / Engaged / Client — so it knew we had been PAID, and could not say
  a relationship had gone quiet;
* Relationship Management (`/relationships`) staged the SAME company from
  `agency_outreach` as Cold / Warm Prospect / Active / Dormant — so it knew about
  dormancy, and **could not return "Client" at any input**. The value sat in its STAGES
  tuple with no code path to it; only a human override could ever set it.

So a company that had commissioned, paid for and received delivered work read "Client"
on one page and "Active" — or after a quiet quarter, "Dormant" — on the other, on the
same day, from the same database. Until ADR-0056 gave organisations a canonical id there
was not even a join to notice it with.

`test_the_old_split_could_not_say_this` is the regression that matters: it asserts the
pair neither engine could express.
"""

import importlib

import pytest

from chordential_oia.web import buyer_intel
from chordential_oia.web import db as db_mod
from chordential_oia.web import relationships as rel_mod


def _days_ago(n: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "r.db"))
    importlib.reload(db_mod)
    c = db_mod.connect()
    db_mod.init_db(c)
    yield c
    c.close()


# --------------------------------------------------------------------------- #
# One vocabulary
# --------------------------------------------------------------------------- #
def test_there_is_exactly_one_stage_vocabulary():
    """Two tuples over the same companies is the disjointness, in the part Jon reads."""
    assert rel_mod.STAGES is buyer_intel.STAGES
    assert buyer_intel.STAGES == ("Cold", "Warm", "Engaged", "Client")


def test_dormant_is_a_flag_and_not_a_stage():
    """Making it a stage is what erased "Client": a paying customer who went quiet
    stopped being recorded as a customer at all."""
    assert "Dormant" not in buyer_intel.STAGES


# --------------------------------------------------------------------------- #
# The evidence each engine was missing
# --------------------------------------------------------------------------- #
def test_the_old_split_could_not_say_this():
    """A client we have been paid by, who has not spoken to us in eight months.

    The Buyer Graph said "Client" and could not say quiet. Relationship Management said
    "Dormant" and could not say client. It is the PAIR that tells Jon to pick up the
    phone, and it is the pair that no single old engine could produce.
    """
    rel = buyer_intel.relationship_for(
        deal={"opps": 3, "qualified": 3, "won": 2, "lost": 0, "open_pursuits": 0,
              "touches": 4, "last_contacted": _days_ago(240)},
        outreach={"count": 6, "last_touch": _days_ago(240), "responded": True})
    assert rel.stage == "Client"
    assert rel.dormant is True
    assert rel.label == "Client · dormant"
    assert "won" in " ".join(rel.signals)


def test_a_won_deal_makes_a_client_even_with_no_outreach_logged():
    """Relationship Management could not reach "Client" from any input. This is the
    input it could not reach it from."""
    rel = buyer_intel.relationship_for(
        deal={"opps": 1, "qualified": 1, "won": 1, "open_pursuits": 0},
        outreach=None)
    assert rel.stage == "Client"


def test_a_quiet_quarter_is_visible_to_the_deal_side_too():
    """The Buyer Graph had no concept of dormancy at all — 240 days since contact and
    40 days since contact staged identically."""
    quiet = buyer_intel.relationship_for(
        deal={"opps": 1, "touches": 2, "last_contacted": _days_ago(240)})
    warm = buyer_intel.relationship_for(
        deal={"opps": 1, "touches": 2, "last_contacted": _days_ago(40)})
    assert quiet.dormant is True and warm.dormant is False
    assert quiet.score < warm.score


def test_a_reply_buys_the_relationship_more_time():
    """Relationship Management's rule, kept: someone who has ever replied is given a
    third of a year rather than a quarter before we call it quiet."""
    silent = buyer_intel.relationship_for(
        deal={"opps": 1}, outreach={"count": 2, "last_touch": _days_ago(100),
                                    "responded": False})
    replied = buyer_intel.relationship_for(
        deal={"opps": 1}, outreach={"count": 2, "last_touch": _days_ago(100),
                                    "responded": True})
    assert silent.dormant is True
    assert replied.dormant is False


def test_a_cold_organisation_cannot_be_dormant():
    """Nothing has happened, so nothing has gone quiet. Reporting dormancy here would
    put every buyer we have never contacted on a re-engagement list."""
    rel = buyer_intel.relationship_for(deal={"opps": 1, "touches": 0})
    assert rel.stage == "Cold" and rel.dormant is False


def test_the_two_logs_are_one_conversation():
    """`outreach_events` hangs off an opportunity and `agency_outreach` off an agency
    record. They are the same act, recorded in whichever surface the operator happened
    to be standing in, and the count and the recency must both merge."""
    rel = buyer_intel.relationship_for(
        deal={"opps": 1, "touches": 2, "last_contacted": _days_ago(60)},
        outreach={"count": 3, "last_touch": _days_ago(3), "responded": False})
    assert rel.stage == "Engaged", "the more recent of the two logs did not win"
    assert "5 outreach touches" in " ".join(rel.signals)


def test_a_well_scored_agency_with_no_contact_is_warm_not_cold():
    """Relationship Management's "Warm Prospect": Agency Intelligence has scored them
    highly, nobody has reached out yet. The Buyer Graph had no way to express it."""
    assert buyer_intel.relationship_for(deal={"opps": 0}, fit_score=91).stage == "Warm"
    assert buyer_intel.relationship_for(deal={"opps": 0}, fit_score=30).stage == "Cold"


# --------------------------------------------------------------------------- #
# Both surfaces, one answer
# --------------------------------------------------------------------------- #
def _company(conn, name, *, won=0, touch_days=None):
    cur = conn.execute(
        "INSERT INTO agencies (source, dedup_key, company, created_at) VALUES (?,?,?,?)",
        ("test", name, name, _days_ago(400)))
    aid = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO opportunities (client, need, status, created_at) VALUES (?,?,?,?)",
        (name, "A spot", "Won" if won else "Pursuing", _days_ago(300)))
    if touch_days is not None:
        conn.execute(
            "INSERT INTO agency_outreach (agency_id, kind, occurred_at, responded) "
            "VALUES (?,?,?,?)", (aid, "email", _days_ago(touch_days), 0))
    conn.commit()
    db_mod.link_orgs(conn)
    return aid


def test_both_pages_stage_the_same_company_the_same_way(conn):
    """The whole item. `/relationships` derives through `pipeline_stages`; `/buyers`
    derives through `relationship_for` over `all_buyers`. One company, one answer."""
    aid = _company(conn, "Northwind Agency", won=1, touch_days=200)

    rm = rel_mod.pipeline_stages(conn, [{
        "id": aid, "company": "Northwind Agency", "opportunity_score": 70,
        "opportunity_tier": "A", "score_movement": 0}])[0]

    row = next(r for r in db_mod.all_buyers(conn) if r["client"] == "Northwind Agency")
    orgs = db_mod.orgs_by_ids(conn, [row["org_id"]])
    agg = db_mod.outreach_aggregate(conn, [aid])
    bg = buyer_intel.relationship_for(deal=dict(row), outreach=agg.get(aid))

    assert rm["stage"] == bg.stage == "Client"
    assert rm["dormant"] == bg.dormant is True
    assert orgs[row["org_id"]]["agency_id"] == aid


def test_relationship_management_can_now_reach_client(conn):
    """`derive_stage` could not return "Client" at any input before this. Asserted
    through the agency workspace, which is where the wrong answer was displayed."""
    aid = _company(conn, "Northwind Agency", won=1, touch_days=3)
    view = rel_mod.relationship_view(conn, aid)
    assert view["stage"] == "Client"
    assert view["dormant"] is False
    assert view["next_best_action"]


def test_a_human_override_still_wins(conn):
    """"The machine proposes, Jon disposes" applies to this too — the derivation must
    not quietly overwrite a stage he set by hand."""
    aid = _company(conn, "Northwind Agency", won=1, touch_days=3)
    db_mod.upsert_relationship(conn, aid, stage="Cold", stage_overridden=1)
    conn.commit()
    assert rel_mod.relationship_view(conn, aid)["stage"] == "Cold"


def test_a_stored_legacy_stage_is_translated_not_dropped(conn):
    """Overrides Jon typed under the old vocabulary are still his decision. They are
    mapped on read rather than migrated — rewriting his rows to tidy a refactor is not
    a trade worth making."""
    assert buyer_intel.apply_override(
        buyer_intel.relationship_for(deal={"opps": 1}), "Warm Prospect").stage == "Warm"
    assert buyer_intel.apply_override(
        buyer_intel.relationship_for(deal={"opps": 1}), "Active").stage == "Engaged"


def test_a_stored_dormant_sets_the_flag_rather_than_a_missing_stage(conn):
    """"Dormant" is no longer a stage. An override of it must mean what Jon meant —
    "this has gone quiet" — not a stage no filter can select."""
    rel = buyer_intel.relationship_for(
        deal={"opps": 1, "won": 1, "touches": 1, "last_contacted": _days_ago(2)})
    out = buyer_intel.apply_override(rel, "Dormant")
    assert out.stage == "Client" and out.dormant is True


def test_the_override_form_cannot_pin_a_stage_that_does_not_exist(tmp_path, monkeypatch):
    """The override is read back as the answer on two pages now. A value outside the
    vocabulary would pin one company to a stage nothing can select or clear."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "v.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app) as c:
        conn = db_mod.connect()
        aid = _company(conn, "Northwind Agency")
        conn.close()
        assert c.post(f"/agencies/{aid}/relationship/stage",
                      data={"stage": "Dormant"},
                      follow_redirects=False).status_code == 400
        assert c.post(f"/agencies/{aid}/relationship/stage",
                      data={"stage": "Client"},
                      follow_redirects=False).status_code == 303


# --------------------------------------------------------------------------- #
# The read path
# --------------------------------------------------------------------------- #
def test_the_pipeline_stays_at_a_constant_number_of_queries(conn):
    """Reaching the other half of the evidence must not reintroduce the per-row loop
    that ADR-0029's batching removed — it is a read path on a page Jon opens daily."""
    rows = []
    for i in range(12):
        aid = _company(conn, f"Agency {i}", won=(i % 2), touch_days=i)
        rows.append({"id": aid, "company": f"Agency {i}", "opportunity_score": 70,
                     "opportunity_tier": "A", "score_movement": 0})

    reads = {"n": 0}
    real = conn.execute

    class Counting:
        def __getattr__(self, k): return getattr(conn, k)
        def execute(self, sql, *a, **kw):
            if sql.lstrip().upper().startswith("SELECT"):
                reads["n"] += 1
            return real(sql, *a, **kw)
        def commit(self): return conn.commit()

    out = rel_mod.pipeline_stages(Counting(), rows)
    assert len(out) == 12
    # Reads only. The writes are one cached-stage upsert per row whose stage moved,
    # which is the pre-existing behaviour; what must not come back is a SELECT per row.
    # Four batched reads: outreach aggregate, relationships, orgs, deal rollup — and
    # the rollup is two statements, so five is the ceiling, not twelve.
    assert reads["n"] <= 5, (
        f"{reads['n']} reads for 12 agencies — the batching regressed")
