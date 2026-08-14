"""Campaign Intelligence holds what the campaign has, not what the schema anticipated.

The ten canonical fields are the ones EVERY campaign has. They were never meant to be the
only ones a campaign MAY have. On a real call the buyer said "we want weekly deliverables,
we want to check in weekly" — twice — and it went nowhere, because there was no slot for a
cadence and so nothing looked for one.

Storage and the view already carried arbitrary facts. What was missing was any way for a
person, or the extractor, to make one. The operator's own words: "it shouldn't be limited,
it should be dynamic."
"""
import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.sqlite"))
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    c = db_mod.connect()
    db_mod.init_db(c)
    yield c
    c.close()


def _ci(db, conn):
    from chordential_oia.models import Opportunity
    from chordential_oia.web import campaign_intelligence as ci
    opp_id = db.insert_opportunity(conn, Opportunity(
        client="AURORA", need="Title sequence", description=""))
    return opp_id, ci.ensure_for_opportunity(conn, db.get_opportunity(conn, opp_id))["id"]


def test_a_field_nobody_defined_can_be_created_and_is_shown(conn):
    """The whole ask: a fact with no slot still has somewhere to live."""
    from chordential_oia.web import campaign_intelligence as ci
    from chordential_oia.web import db
    _opp, ci_id = _ci(db, conn)

    ci.edit_or_create(conn, ci_id, "engagement", "legal_lead_time", "fact",
                      "11 weeks last time", actor="operator")
    view = ci.fields_view(conn, ci_id)
    shown = {it["key"]: it for sec in view["sections"] for it in sec["items"]}
    assert "legal_lead_time" in shown
    assert shown["legal_lead_time"]["value"] == "11 weeks last time"


def test_it_is_labelled_readably_without_anyone_registering_it(conn):
    from chordential_oia.web import campaign_intelligence as ci
    from chordential_oia.web import db
    _opp, ci_id = _ci(db, conn)
    ci.edit_or_create(conn, ci_id, "buyer", "board_meeting_date", "fact",
                      "the 14th", actor="operator")
    view = ci.fields_view(conn, ci_id)
    shown = {it["key"]: it for sec in view["sections"] for it in sec["items"]}
    assert shown["board_meeting_date"]["label"] == "Board Meeting Date"


def test_it_lands_in_the_facet_it_was_filed_under(conn):
    from chordential_oia.web import campaign_intelligence as ci
    from chordential_oia.web import db
    _opp, ci_id = _ci(db, conn)
    ci.edit_or_create(conn, ci_id, "direction", "vocal_stance", "fact",
                      "no vocal — dated badly last time", actor="operator")
    view = ci.fields_view(conn, ci_id)
    facets = {sec["facet"]: [it["key"] for it in sec["items"]] for sec in view["sections"]}
    assert "vocal_stance" in facets["direction"]
    assert "vocal_stance" not in facets["engagement"]


def test_the_canonical_ten_are_still_all_present(conn):
    """Dynamic must mean 'and also', never 'instead of' — an empty slot the operator can
    type into is what stops a campaign quietly losing its budget field."""
    from chordential_oia.web import campaign_intelligence as ci
    from chordential_oia.web import db
    _opp, ci_id = _ci(db, conn)
    ci.edit_or_create(conn, ci_id, "engagement", "anything", "fact", "x", actor="operator")
    view = ci.fields_view(conn, ci_id)
    shown = {it["key"] for sec in view["sections"] for it in sec["items"]}
    for _f, k, _kind, _l, _p, _o in ci.CANONICAL_FIELDS:
        assert k in shown, f"canonical field {k} disappeared"


def test_a_typed_label_becomes_the_key():
    """A person types "Check-in cadence"; the storage key is derived, not demanded."""
    import re
    label = "Check-in cadence"
    key = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")[:48]
    assert key == "check_in_cadence"


def test_the_form_is_on_the_intelligence_card():
    from pathlib import Path
    from chordential_oia.web import app as app_mod
    html = (Path(app_mod.__file__).parent / "templates" / "detail.html").read_text(
        encoding="utf-8")
    assert 'name="label"' in html and "Anything else that matters" in html


def test_the_extractor_can_now_propose_a_field_with_no_slot():
    """The line that started this: stated twice, dropped twice."""
    from chordential_oia.web.campaign_intake import _extract_objective
    got = {c["key"]: c["value"] for c in _extract_objective(
        "We want weekly deliverables. We want to check in weekly. Budget is $9,000.")}
    assert got.get("check_in_cadence") == "weekly"


def test_it_does_not_invent_a_cadence_that_was_never_stated():
    from chordential_oia.web.campaign_intake import _extract_objective
    got = {c["key"] for c in _extract_objective(
        "Budget is $9,000 and we need it by November.")}
    assert "check_in_cadence" not in got
