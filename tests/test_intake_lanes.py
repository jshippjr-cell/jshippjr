"""The intake-lane framework (Increment 1, ADR-0014).

Campaign Intake is an extensible framework of lanes, none privileged. Every lane normalizes
to the ONE Capture envelope and funnels through the ONE shared pipeline into the ONE Campaign
Intelligence object — stamping provenance + the raw-evidence capture on every field, so every
value can answer "why did this change?" Raw evidence is permanent.
"""
from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
from chordential_oia.web import campaign_intake as intake
from chordential_oia.web import campaign_intelligence as ci
from chordential_oia.web import intake_lanes


# --------------------------------------------------------------------------- #
# The registry — the single place lanes are enumerated.
# --------------------------------------------------------------------------- #
def test_registry_enumerates_every_lane_none_privileged():
    keys = {ln.key for ln in intake_lanes.LANES}
    assert {"discovery_call", "producer_debrief", "meeting_notes", "meeting_transcript",
            "rfp", "email_thread", "client_brief"} <= keys
    # discovery call is asynchronous; the manual lanes are synchronous
    assert intake_lanes.get_lane("discovery_call").kind == intake_lanes.ASYNC
    assert intake_lanes.get_lane("meeting_notes").kind == intake_lanes.SYNC


def test_meeting_lane_is_unavailable_until_its_seam_is_configured(monkeypatch):
    monkeypatch.delenv("CHORDENTIAL_NOTETAKER_PROVIDER", raising=False)
    monkeypatch.delenv("CHORDENTIAL_MEETING_PROVIDER", raising=False)
    # null-by-default: the discovery-call lane reports unavailable, manual lanes stay usable
    assert intake_lanes.get_lane("discovery_call").is_available() is False
    assert "discovery_call" not in {ln.key for ln in intake_lanes.sync_lanes()}
    assert intake_lanes.get_lane("meeting_notes").is_available() is True
    # once both seams are set, it becomes available (honest gating, no fakery)
    monkeypatch.setenv("CHORDENTIAL_NOTETAKER_PROVIDER", "recall")
    monkeypatch.setenv("CHORDENTIAL_MEETING_PROVIDER", "zoom")
    assert intake_lanes.get_lane("discovery_call").is_available() is True


def test_resolve_lane_maps_stance_and_modality():
    # a debrief is a stance-level decision → always the producer-debrief lane
    assert intake_lanes.resolve_lane(stance="debrief", modality="notes").key == "producer_debrief"
    assert intake_lanes.resolve_lane(stance="debrief").provenance_source == "producer_debrief"
    # objective + modality → the matching lane, with a precise provenance token
    assert intake_lanes.resolve_lane(stance="objective", modality="notes").provenance_source == "notes"
    assert intake_lanes.resolve_lane(stance="objective", modality="transcript").provenance_source == "transcript"
    # an explicit lane key wins for objective captures
    assert intake_lanes.resolve_lane(lane_key="rfp").provenance_source == "rfp"


# --------------------------------------------------------------------------- #
# The envelope + provenance stamps — every field cites its raw-evidence capture.
# --------------------------------------------------------------------------- #
def _opp(dbm, conn):
    o = Opportunity(client="Halcyon Creative", need="Holiday anthem",
                    description="National holiday campaign.", buyer_type=BuyerType.AGENCY,
                    music_requirement=MusicRequirement.ORIGINAL, budget_min=0, budget_max=0)
    return dbm.insert_opportunity(conn, o)


def _db(tmp_path):
    from chordential_oia.web import db as dbm
    conn = dbm.connect(str(tmp_path / "lanes.db"))
    dbm.init_db(conn)
    return dbm, conn


def test_capture_envelope_is_written_and_every_field_cites_it(tmp_path):
    dbm, conn = _db(tmp_path)
    opp = dbm.get_opportunity(conn, _opp(dbm, conn))
    summary = intake.ingest_opportunity(
        conn, opp, intake.OBJECTIVE,
        "Budget is $18,000 to $24,000. Need it by November. :60 anthem plus stems.",
        lane_key="meeting_notes")
    cap = dbm.get_capture(conn, summary["capture_id"])
    # the normalized envelope: lane, provenance source, anchor, modality, permanent raw text
    assert cap["lane"] == "meeting_notes" and cap["provenance_source"] == "notes"
    assert cap["opp_id"] == opp["id"] and cap["modality"] == "notes"
    assert "$18,000" in cap["raw_text"] and cap["status"] == "ingested"
    # every field this capture proposed cites it (raw-evidence provenance)
    fields = dbm.fields_by_capture(conn, cap["id"])
    keys = {f["key"] for f in fields}
    assert "budget_band" in keys and any(k.startswith("ask_") for k in keys)
    for f in fields:
        assert f["capture_id"] == cap["id"]
    # and the enrichment events are stamped with the same capture (the audit trail)
    ev = conn.execute(
        "SELECT COUNT(*) c FROM campaign_intelligence_event WHERE capture_id=?",
        (cap["id"],)).fetchone()["c"]
    assert ev >= 1


def test_review_batch_derives_this_captures_proposed_changes(tmp_path):
    dbm, conn = _db(tmp_path)
    opp = dbm.get_opportunity(conn, _opp(dbm, conn))
    summary = intake.ingest_opportunity(conn, opp, intake.OBJECTIVE,
                                        "Budget is $20k. By December.",
                                        lane_key="meeting_transcript")
    batch = intake.review_batch(conn, summary["capture_id"])
    assert batch["capture"]["lane"] == "meeting_transcript"
    assert batch["counts"]["total"] >= 1
    # freshly-ingested facts await the human (machine proposes; nothing auto-confirmed)
    assert batch["counts"]["open"] == batch["counts"]["total"]
    assert all(not f["human_value"] for f in batch["fields"])


def test_debrief_lane_keeps_interpretation_distinct_from_fact(tmp_path):
    dbm, conn = _db(tmp_path)
    opp = dbm.get_opportunity(conn, _opp(dbm, conn))
    summary = intake.ingest_opportunity(
        conn, opp, intake.DEBRIEF,
        "We should lead with piano. Risk: unclear who signs off.")
    cap = dbm.get_capture(conn, summary["capture_id"])
    assert cap["lane"] == "producer_debrief" and cap["provenance_source"] == "producer_debrief"
    kinds = {f["kind"] for f in dbm.fields_by_capture(conn, cap["id"])
             if f["kind"] != "open_question" or not f["key"].startswith("ask_")}
    # a debrief contributes interpretation, never an objective fact
    assert "recommendation" in kinds and "fact" not in {
        f["kind"] for f in dbm.fields_by_capture(conn, cap["id"])
        if f["contributed_by"] == "operator"}
