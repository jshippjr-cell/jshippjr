"""The Producer Learning System (ADR-0021): EP-completeness extraction, the Observed Facts
scratchpad, and the learning ledger whose priors tune the next extraction.
"""
import importlib

from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
# Reached directly, not through `app_mod`: ADR-0044 moved the /opportunity routes
# out of app.py and with them app.py's need to import this engine.
from chordential_oia.web import producer_learning
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia.web import campaign_intelligence  # noqa: E402


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_CAMPAIGN_WORKSPACE", "1")
    monkeypatch.setenv("CHORDENTIAL_INTAKE_LLM", "0")   # deterministic; no network
    for m in ("db", "campaign_intelligence", "campaign_intake", "intake_lanes",
              "producer_learning", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as app_mod
    return app_mod


def _opp(dbm, conn):
    oid = dbm.insert_opportunity(conn, Opportunity(
        client="Aurora Films", need="Indie feature score", description="Feature film.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0))
    return oid


# --------------------------------------------------------------------------- #
# edit_distance + field_prior stances.
# --------------------------------------------------------------------------- #
def test_edit_distance_and_prior_stances(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    pl = producer_learning
    assert pl.edit_distance("stems", "stems") == 0.0
    assert pl.edit_distance("", "anything") == 1.0
    assert 0.0 < pl.edit_distance("warm", "warm cinematic with restrained brass") < 1.0

    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    # trusted: confirmed repeatedly
    for _ in range(3):
        pl.record_event(conn, ci_id=1, opp_id=1, facet="engagement", key="deliverables",
                        action="confirmed", ai_value="stems", final_value="stems")
    assert pl.field_prior(conn, "engagement", "deliverables")["stance"] == "trusted"
    # expand: consistently enriched
    for _ in range(3):
        pl.record_event(conn, ci_id=1, opp_id=1, facet="direction", key="emotional_arc",
                        action="edited", ai_value="warm",
                        final_value="warm, cinematic, restrained brass")
    p = pl.field_prior(conn, "direction", "emotional_arc")
    assert p["stance"] == "expand" and p["expands"] >= 0.4
    # learn (missed concept): added-from-nothing repeatedly
    for _ in range(2):
        pl.record_event(conn, ci_id=1, opp_id=1, facet="engagement", key="campaign_type",
                        action="added", ai_value="", final_value="Feature film")
    lp = pl.field_prior(conn, "engagement", "campaign_type")
    assert lp["stance"] == "learn" and lp["missed"] == 2
    # contested: rejected repeatedly
    for _ in range(2):
        pl.record_event(conn, ci_id=1, opp_id=1, facet="buyer", key="brand_notes",
                        action="rejected", ai_value="guessy note", final_value="")
    assert pl.field_prior(conn, "buyer", "brand_notes")["stance"] == "contested"

    summary = pl.priors_summary(conn)
    assert "engagement.deliverables" in summary and "confidently" in summary
    assert "direction.emotional_arc" in summary and "EXPAND" in summary
    assert "engagement.campaign_type" in summary and "ADDED" in summary
    conn.close()


# --------------------------------------------------------------------------- #
# The full loop through the real routes: confirm/edit/add → events → priors → prompt.
# --------------------------------------------------------------------------- #
def test_dispositions_record_events_and_feed_the_prompt(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = _opp(app_mod.db, conn)
    row = app_mod.db.get_opportunity(conn, oid)
    ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
    ci_id = ci_row["id"]
    # a machine-proposed fact needing review (as extraction would land it)
    fid = campaign_intelligence.contribute(
        conn, ci_id, "engagement", "deliverables", "stems", kind="fact",
        source="discovery_call", confidence=60)
    conn.close()

    with TestClient(app_mod.app) as c:
        # CONFIRM the proposal verbatim
        c.post(f"/opportunity/{oid}/intelligence/dispose", data={"field_id": str(fid)})
        # ADD a field the AI missed (empty-slot fill)
        c.post(f"/opportunity/{oid}/intelligence/field",
               data={"facet": "engagement", "key": "campaign_type", "kind": "fact",
                     "value": "Feature film"})

    conn = app_mod.db.connect()
    rows = conn.execute("SELECT * FROM producer_learning_event ORDER BY id").fetchall()
    assert [r["action"] for r in rows] == ["confirmed", "added"]
    assert rows[0]["facet"] == "engagement" and rows[0]["key"] == "deliverables"
    assert rows[0]["edit_distance"] == 0.0 and rows[0]["ai_value"] == "stems"
    assert rows[1]["action"] == "added" and rows[1]["ai_value"] == ""
    assert rows[1]["final_value"] == "Feature film"
    # the prompt now carries the learned priors (once each field crosses 2 events it shows;
    # a single event won't — assert the plumbing: priors_summary is injected into the prompt)
    producer_learning.record_event(
        conn, ci_id=ci_id, opp_id=oid, facet="engagement", key="campaign_type",
        action="added", ai_value="", final_value="Feature film")
    priors = producer_learning.priors_summary(conn)
    conn.close()
    assert "campaign_type" in priors
    # Reached directly: ADR-0044 moved the /campaign routes out of app.py and with
    # them app.py's need to import this engine.
    from chordential_oia.web import campaign_intake
    prompt = campaign_intake._build_extraction_prompt(
        "some transcript", "objective", priors=priors)
    assert "WHAT THIS PRODUCER CONSISTENTLY VALUES" in prompt
    assert "campaign_type" in prompt
    # EP-completeness voice is in the base prompt
    assert "EXECUTIVE PRODUCER" in prompt and "OVER-capturing" in prompt
    assert "observed" in prompt


# --------------------------------------------------------------------------- #
# Observed facts flow into their own bucket in the view + render in the panel.
# --------------------------------------------------------------------------- #
def test_observed_facts_bucket_and_render(tmp_path, monkeypatch):
    app_mod = _app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    conn = app_mod.db.connect(); app_mod.db.init_db(conn)
    oid = _opp(app_mod.db, conn)
    row = app_mod.db.get_opportunity(conn, oid)
    ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
    campaign_intelligence.contribute(
        conn, ci_row["id"], "observed", "festival_premiere",
        "Plans a film-festival premiere", kind="fact", source="discovery_call", confidence=70)
    view = campaign_intelligence.fields_view(conn, ci_row["id"])
    conn.close()
    assert any(it["value"] == "Plans a film-festival premiere" for it in view["observed"])
    # observed facts must NOT leak into the canonical sections or producer_read
    for sec in view["sections"]:
        assert all(it["facet"] != "observed" for it in sec["items"])

    with TestClient(app_mod.app) as c:
        page = c.get(f"/opportunity/{oid}").text
    assert "Observed facts" in page and "Plans a film-festival premiere" in page


# --------------------------------------------------------------------------- #
# Discovery Summary email — rendered FROM Campaign Intelligence, introduces the Workspace.
# --------------------------------------------------------------------------- #
def test_discovery_summary_renders_from_ci_and_introduces_workspace(tmp_path, monkeypatch):
    from chordential_oia import outreach
    from chordential_oia.models import Opportunity, BuyerType, MusicRequirement
    opp = Opportunity(
        client="Aurora Films", need="Indie feature score", description="Feature film.",
        buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
        budget_min=0, budget_max=0)
    ci_view = {"fields": {
        "business_objective": "Original score for an indie feature film",
        "campaign_type": "Feature film", "distribution": "Film festival debut",
        "deliverables": "Original score, stems, alt mixes, :15 and :30 cutdowns",
        "critical_deadline": "Festival delivery"}}

    # POST-DISCOVERY (met=True): the Discovery Summary introduces the Workspace, from CI.
    blocks = outreach.build_compose_blocks(
        opp, None, None, opp_id=7, contact_name="Sarah", share_token="TOK123",
        ci_view=ci_view, met=True)
    by = {b["key"]: b for b in blocks}
    on = {b["key"] for b in blocks if b["default_on"]}
    # the understanding is rendered FROM CI — not the template default
    assert "indie feature film" in by["understanding"]["text"].lower()
    # …but it is the SHORT version, not the record. It used to carry every CI value it
    # could reach ("Distribution: Film festival debut. Deliverables as discussed: … :15 and
    # :30 cutdowns. Timeline: Festival delivery."), which is the same content the workspace
    # shows in a table — so the client read it in the email and again on the page it links
    # to. The email now names the areas and hands off (client_voice); a value belongs on the
    # surface that has an edit box beside it.
    assert "the deliverables" in by["understanding"]["text"]
    assert "the timeline" in by["understanding"]["text"]
    assert "your workspace" in by["understanding"]["text"]
    for reprinted in ("Film festival debut", ":15 and :30 cutdowns", "Festival delivery"):
        assert reprinted not in by["understanding"]["text"], (
            f"the email restated a workspace value: {reprinted}")
    # the workspace-introduction copy + the durable workspace link
    assert "private Chordential Workspace" in by["page_link"]["text"]
    assert "correct anything we've misunderstood" in by["page_link"]["text"]
    assert "/workspace/TOK123" in by["page_link"]["text"]
    assert by["opener"]["text"].startswith("Hi Sarah")
    assert "Thank you again for your time today" in by["opener"]["text"]
    # cold-prospecting blocks are OFF post-discovery
    assert "track" not in on and "call_offer" not in on
    assert on == {"opener", "understanding", "page_link", "signoff"}

    # PRE-DISCOVERY (met=False): still the prospecting email, understanding still from CI.
    cold = {b["key"]: b for b in outreach.build_compose_blocks(
        opp, None, None, opp_id=7, contact_name="Sarah", share_token="TOK123",
        ci_view=ci_view, met=False)}
    assert "indie feature film" in cold["understanding"]["text"].lower()  # CI, not template
    assert "private Chordential Workspace" not in cold["page_link"]["text"]
