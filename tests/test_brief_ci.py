"""ADR-0017 — Campaign Intelligence is the single source of truth for the Campaign Brief.

Covers: every brief section inheriting from CI (never stock templates once CI exists),
the meeting-summary tone after discovery, brief edits writing back to CI, blank-override
reverting to CI-derived (never stock) copy, the commercial close, and Email This freezing
a snapshot the client link renders verbatim.
"""
import importlib

import pytest

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "campaigns", "meeting_scheduler", "meetings_service", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _opp(dbm, conn):
    oid = dbm.insert_opportunity(conn, Opportunity(
        client="Halcyon Creative", need="Holiday anthem", description="Campaign.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    conn.execute("UPDATE opportunities SET contact_email=?, contact_name=? WHERE id=?",
                 ("sarah@halcyon.com", "Sarah Chen", oid))
    conn.commit()
    return oid


def _seed_ci(app_mod, conn, opp_id):
    """Confirmed intelligence, as a discovery call would leave it."""
    ci = app_mod.campaign_intelligence
    row = app_mod.db.get_opportunity(conn, opp_id)
    ci_id = ci.ensure_for_opportunity(conn, row)["id"]
    facts = [("direction", "campaign_objective", "A holiday anthem that owns Q4 retail"),
             ("direction", "emotional_arc", "Wonder building into confident joy"),
             ("engagement", "deliverables", ":60 anthem, :30/:15 cutdowns, full stems"),
             ("engagement", "deadline", "Final masters by November 10"),
             ("engagement", "budget_band", "$18,000–$24,000"),
             ("buyer", "decision_makers", "CMO signs off; agency CD steers creative")]
    for facet, key, value in facts:
        ci.edit_or_create(conn, ci_id, facet, key, "fact", value, actor="operator")
    ci.contribute(conn, ci_id, "direction", "risk_vo", "VO may extend to :37",
                  kind="insight", source="debrief", is_concern=True)
    ci.contribute(conn, ci_id, "engagement", "ask_stems", "Confirm stem count for social",
                  kind="open_question", source="debrief")
    return ci_id


# --------------------------------------------------------------------------- #
# The brief renders CI — never the stock template — once intelligence exists.
# --------------------------------------------------------------------------- #
def test_brief_sections_inherit_from_ci(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    _seed_ci(app_mod, conn, opp_id); conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}/capabilities").text
    # every seeded fact appears — objective, arc, deliverables, timeline, budget, DMs
    assert "A holiday anthem that owns Q4 retail" in page
    assert "Wonder building into confident joy" in page
    assert ":60 anthem, :30/:15 cutdowns, full stems" in page
    assert "Final masters by November 10" in page
    assert "CMO signs off" in page
    # risks + open questions from the debrief
    assert "VO may extend to :37" in page
    assert "Confirm stem count for social" in page
    # the understanding is CI-derived, not the stock template sentence
    assert "music partner to shape its sound end-to-end" not in page


def test_brief_reads_as_meeting_summary_after_discovery(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    _seed_ci(app_mod, conn, opp_id)
    # a discovery call that already happened
    app_mod.db.create_meeting(conn, opp_id=opp_id, start_at="2026-07-01T14:00:00+00:00",
                              status="ingested")
    conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}/capabilities").text
    assert "After meeting with your team" in page
    assert "What we heard" in page
    # the marketing self-intro steps back when the doc is a meeting summary
    assert "Who we are" not in page


def test_brief_without_ci_still_renders_conservative_default(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn); conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}/capabilities").text
    assert "current understanding" in page      # honest not-met intro
    assert "Campaign Brief" in page


# --------------------------------------------------------------------------- #
# Editing the brief edits CI — the single source of truth.
# --------------------------------------------------------------------------- #
def test_brief_edit_writes_campaign_intelligence(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    ci_id = _seed_ci(app_mod, conn, opp_id); conn.close()
    with TestClient(app_mod.app) as c:
        c.post(f"/opportunity/{opp_id}/doc/ci-field",
               data={"name": "emotional_arc", "value": "Restraint opening into triumph"})
        page = c.get(f"/opportunity/{opp_id}/capabilities").text
    assert "Restraint opening into triumph" in page
    conn = app_mod.db.connect()
    vals = {r["key"]: r["value"] for r in app_mod.db.list_ci_fields(conn, ci_id)}
    conn.close()
    assert vals["emotional_arc"] == "Restraint opening into triumph"   # CI updated, not a copy


def test_blank_understanding_override_reverts_to_ci_not_stock(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    _seed_ci(app_mod, conn, opp_id); conn.close()
    with TestClient(app_mod.app) as c:
        c.post(f"/opportunity/{opp_id}/doc/field",
               data={"name": "understanding", "value": "Hand-written understanding."})
        assert "Hand-written understanding." in c.get(f"/opportunity/{opp_id}/capabilities").text
        # blanking the override reverts to INTELLIGENCE-derived copy, never stock template
        c.post(f"/opportunity/{opp_id}/doc/field", data={"name": "understanding", "value": ""})
        page = c.get(f"/opportunity/{opp_id}/capabilities").text
    assert "Deliverables as discussed" in page
    assert "music partner to shape its sound end-to-end" not in page


# --------------------------------------------------------------------------- #
# The commercial close.
# --------------------------------------------------------------------------- #
def test_commercial_close_renders_from_ci(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    _seed_ci(app_mod, conn, opp_id); conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}/capabilities").text
    assert "The commercial picture" in page
    assert "$18,000–$24,000" in page                       # CI budget band
    assert "Final masters by November 10" in page          # CI timeline in the close
    assert "revision rounds" in page and "50% to begin" in page


# --------------------------------------------------------------------------- #
# Email This freezes a snapshot — the client opens what the operator approved.
# --------------------------------------------------------------------------- #
def test_send_freezes_snapshot_and_link_renders_it_verbatim(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    ci_id = _seed_ci(app_mod, conn, opp_id); conn.close()
    sent = []
    monkeypatch.setattr(app_mod.mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(app_mod.mailer, "send_email",
                        lambda to, sub, body, html=None: sent.append(body) or "sent")
    with TestClient(app_mod.app) as c:
        c.post(f"/opportunity/{opp_id}/compose/send")
        assert sent
        conn = app_mod.db.connect()
        snap = app_mod.db.latest_brief_snapshot(conn, opp_id)
        token = app_mod.db.ensure_share_token(conn, opp_id); conn.close()
        assert snap is not None
        assert f"capabilities?k={token}&v={snap['id']}" in sent[0]   # the mailed link
        # intelligence changes AFTER the send…
        conn = app_mod.db.connect()
        app_mod.campaign_intelligence.edit_or_create(
            conn, ci_id, "direction", "emotional_arc", "fact", "Something new entirely")
        conn.close()
        # …the live brief moves, the snapshot does not
        live = c.get(f"/opportunity/{opp_id}/capabilities?k={token}").text
        frozen = c.get(f"/opportunity/{opp_id}/capabilities?k={token}&v={snap['id']}").text
    assert "Something new entirely" in live
    assert "Something new entirely" not in frozen
    assert "Wonder building into confident joy" in frozen   # what was approved at send


def test_email_this_composer_inherits_ci(tmp_path, monkeypatch):
    """'Email this' → the composer; its understanding block must carry the SAME
    intelligence the brief renders, never the stock restatement (ADR-0017)."""
    app_mod = _app(tmp_path, monkeypatch)
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    _seed_ci(app_mod, conn, opp_id)
    app_mod.db.create_meeting(conn, opp_id=opp_id, start_at="2026-07-01T14:00:00+00:00",
                              status="ingested")
    conn.close()
    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{opp_id}/compose").text
    # the CI-derived understanding appears in the composed email…
    assert "Deliverables as discussed" in page
    assert ":60 anthem, :30/:15 cutdowns, full stems" in page
    # …and the stock restatement does not
    assert "shape its sound end-to-end" not in page


def test_snapshot_survives_roundtrip(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from chordential_oia import capabilities as cap
    from chordential_oia.web.estimate import build_estimate
    from chordential_oia.web.evaluate import evaluate
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    opp_id = _opp(app_mod.db, conn)
    row = app_mod.db.get_opportunity(conn, opp_id)
    opp = app_mod.db.opportunity_from_row(row); conn.close()
    qual, _ = evaluate(opp)
    est = build_estimate(opp, qual.team_shape or qual.discipline.team_shape, qual.discipline)
    doc = cap.build_capabilities_doc(
        opp, qual, est, toggles=cap.default_toggles("New"),
        ci_view={"fields": {"emotional_arc": "Quiet wonder"}, "risks": ["r1"],
                 "open_questions": ["q1"]}, met=True)
    doc2 = cap.doc_from_json(cap.doc_to_json(doc))
    assert doc2 is not None
    assert doc2.ci["emotional_arc"] == "Quiet wonder"
    assert doc2.risks == ["r1"] and doc2.open_questions == ["q1"]
    assert doc2.met is True and doc2.intro == doc.intro
    assert [d.asset for d in doc2.deliverables] == [d.asset for d in doc.deliverables]
