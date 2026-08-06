"""Relationship Management Platform — not a CRM (these aren't customers; they're
prospects, partners, relationships). It consumes the outputs of the other engines
(Intelligence, Decision Makers, Signals, Opportunity) and manages the LIFECYCLE of
each agency relationship. Everything belongs to the relationship, not the agency.

It never duplicates the engines. It answers one question for every agency: "Given
everything we know, where are we in this relationship and what should Jon do next?"

The auto-agents (all deterministic, derived from the living Agency Profile):
  * Relationship Agent — derives the stage (Cold / Warm Prospect / Active /
    Client / Dormant) from the score + interactions, unless a human overrides it.
  * Reminder Agent — after an outreach, ensures a follow-up task exists.
  * Timeline Agent — merges interactions + signals + score history + tasks into one
    chronological relationship timeline.
  * Relationship Memory Agent — institutional memory; seeds a few facts from what
    the platform already knows, and stores whatever Jon captures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import buyer_intel, db

# ONE vocabulary (ADR-0057). This module used to declare its own — Cold / Warm Prospect
# / Active / Client / Dormant — over the same companies the Buyer Graph staged as
# Cold / Warming / Engaged / Client. `buyer_intel.STAGES` is now the only one, and
# dormancy is a flag beside it rather than a stage that erases "Client".
STAGES = buyer_intel.STAGES
_PROBABILITY = {"A": "High", "B": "Medium", "C": "Low", "D": "Low"}


# --------------------------------------------------------------------------- #
# Relationship Agent — ONE stage, over ALL of the evidence.
# --------------------------------------------------------------------------- #
# This used to be a rule of its own, and it could not return "Client" — the value was
# in its STAGES tuple and unreachable from its code, so a company that had commissioned
# and paid for work read "Active", or after a quiet quarter "Dormant". Meanwhile
# /buyers, looking at the same company through `opportunities`, said "Client". Both
# pages were right about their half and neither could see the other's. The derivation
# now lives in `buyer_intel`; this module's job is to hand it the evidence it holds.
def _assess(*, interactions: List, responded: bool, score: Optional[int],
            deal: Optional[dict]) -> buyer_intel.BuyerRelationship:
    # MAX, not min: the most RECENT touch decides recency, and an ISO string sorts
    # the same way the timestamp does.
    last_touch = max((i["occurred_at"] for i in interactions), default=None)
    return buyer_intel.relationship_for(
        deal=deal, fit_score=score,
        outreach={"count": len(interactions), "last_touch": last_touch,
                  "responded": responded})


def _deal_for_agency(conn, agency_id: Optional[int]) -> Optional[dict]:
    """The deals hanging off the same canonical organisation (ADR-0056) — invisible
    from this side until organisations had an id."""
    if not agency_id:
        return None
    org = db.orgs_for_agencies(conn, [agency_id]).get(agency_id)
    if org is None:
        return None
    return db.org_deal_rollup(conn, [org["id"]]).get(org["id"])


def derive_stage(*, score: Optional[int], interactions: List, responded: bool,
                 deal: Optional[dict] = None) -> str:
    """The lifecycle stage, deterministically. A human can override it (stored on the
    relationship); this is the automatic default.

    ``deal`` is the organisation's opportunity rollup. Without it this answers from the
    outreach log alone — which is what it did before, and is still the whole truth for
    an agency no opportunity has ever named.
    """
    return _assess(interactions=interactions, responded=responded, score=score,
                   deal=deal).stage


def pipeline_stages(conn, rows: List) -> List[dict]:
    """Stage each scored agency in ``rows`` with O(1) queries: ONE outreach aggregate,
    ONE org lookup, ONE deal rollup and ONE relationships fetch for the whole set,
    deriving stages in memory and persisting only the changed (non-overridden) ones in
    a SINGLE transaction.

    Replaces the per-row loop that ran list_agency_outreach + get_relationship for
    every row and committed the cached stage per changed row (~150 queries + up to 50
    fsync commits on the /relationships read path). The stage is now the unified one,
    so this table and /buyers cannot disagree; an overridden stage is still honored."""
    ids = [r["id"] for r in rows]
    agg = db.outreach_aggregate(conn, ids)
    rels = db.relationships_by_ids(conn, ids)
    orgs = db.orgs_for_agencies(conn, ids)
    deals = db.org_deal_rollup(conn, [o["id"] for o in orgs.values()])
    out: List[dict] = []
    changed = False
    for r in rows:
        aid = r["id"]
        org = orgs.get(aid)
        rel = buyer_intel.relationship_for(
            deal=deals.get(org["id"]) if org is not None else None,
            outreach=agg.get(aid), fit_score=r["opportunity_score"])
        stored = rels.get(aid)
        if stored is not None and stored["stage_overridden"] and stored["stage"]:
            rel = buyer_intel.apply_override(rel, stored["stage"])
        elif stored is None or stored["stage"] != rel.stage:
            # `exists` comes from the batch we already fetched — upsert_relationship
            # would SELECT per agency to learn what `rels` already told us.
            db.cache_relationship_stage(conn, aid, rel.stage,
                                        exists=stored is not None)  # no commit yet
            changed = True
        out.append({"id": aid, "company": r["company"],
                    "score": r["opportunity_score"], "tier": r["opportunity_tier"],
                    "stage": rel.stage, "dormant": rel.dormant, "label": rel.label,
                    "movement": r["score_movement"]})
    if changed:
        conn.commit()                                            # ONE commit for the batch
    return out


def current_stage(conn, agency_id: int, *, score: Optional[int],
                  interactions: List, responded: bool) -> str:
    return current_relationship(conn, agency_id, score=score,
                                interactions=interactions, responded=responded).stage


def current_relationship(conn, agency_id: int, *, score: Optional[int],
                         interactions: List, responded: bool
                         ) -> buyer_intel.BuyerRelationship:
    """The whole relationship, not just its name — the caller needs the dormancy flag
    and the next action too, and deriving those separately is how there came to be two
    engines in the first place."""
    rel = _assess(interactions=interactions, responded=responded, score=score,
                  deal=_deal_for_agency(conn, agency_id))
    stored = db.get_relationship(conn, agency_id)
    if stored and stored["stage_overridden"] and stored["stage"]:
        return buyer_intel.apply_override(rel, stored["stage"])
    # cache the derived stage (without marking it overridden)
    if not stored or stored["stage"] != rel.stage:
        db.upsert_relationship(conn, agency_id, stage=rel.stage)
        conn.commit()
    return rel


# --------------------------------------------------------------------------- #
# Reminder Agent — ensure a follow-up after an outreach.
# --------------------------------------------------------------------------- #
def ensure_followup(conn, agency_id: int, *, days: int = 14, contact: str = "") -> bool:
    """Create a follow-up task ``days`` out if none is open. Returns True if created."""
    if db.has_open_followup(conn, agency_id):
        return False
    due = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    who = f" with {contact}" if contact else ""
    db.add_agency_task(conn, agency_id, title=f"Follow up{who}", kind="followup",
                       due_at=due, source="auto")
    conn.commit()
    return True


# --------------------------------------------------------------------------- #
# Relationship Memory Agent — seed institutional memory from what we know.
# --------------------------------------------------------------------------- #
def seed_memory(conn, agency_id: int) -> int:
    """Seed a few memory facts from the collected profile (deduped). Captures the
    'what we know' so the workspace starts with institutional context, not blank."""
    intel = db.get_agency_intel(conn, agency_id) or {}
    dms = [dict(d) for d in db.list_decision_makers(conn, agency_id)]
    added = 0
    top = next((d for d in dms if d["priority"] in ("Very High", "High")), None)
    if top:
        added += db.add_agency_memory(
            conn, agency_id, contact=top["name"], source="auto",
            fact=f"{top['name']} is {top['title']} — {top.get('relevance_reason','key contact')}")
    usage = (intel.get("music_usage") or {}).get("value") or []
    if usage:
        added += db.add_agency_memory(
            conn, agency_id, source="auto",
            fact="Observed music usage: " + ", ".join(v.replace("Uses ", "") for v in usage))
    inds = (intel.get("primary_industries") or {}).get("value") or []
    if inds:
        added += db.add_agency_memory(conn, agency_id, source="auto",
                                      fact="Serves: " + ", ".join(inds[:4]))
    if added:
        conn.commit()
    return added


# --------------------------------------------------------------------------- #
# Timeline Agent — one chronological view across every source.
# --------------------------------------------------------------------------- #
def relationship_timeline(conn, agency_id: int) -> List[Dict]:
    events: List[Dict] = []
    for o in db.list_agency_outreach(conn, agency_id):
        label = f"{o['kind'].title()}" + (f" → {o['contact']}" if o["contact"] else "")
        if o["responded"]:
            label += " (responded)"
        events.append({"date": o["occurred_at"], "kind": "Interaction",
                       "label": label, "detail": o["note"] or ""})
    for s in db.list_opportunity_signals(conn, agency_id, active_only=False):
        events.append({"date": s["detected_at"], "kind": "Signal",
                       "label": f"{s['event_type']} · music {s['music_relevance']}",
                       "detail": s["summary"]})
    for t in db.list_agency_tasks(conn, agency_id):
        when = t["done_at"] or t["created_at"]
        events.append({"date": when, "kind": "Task",
                       "label": f"{t['title']} ({t['status']})",
                       "detail": ("due " + t["due_at"][:10]) if t["due_at"] else ""})
    for h in (db.get_agency_score(conn, agency_id) or {}).get("history", []):
        events.append({"date": h["date"], "kind": "Score",
                       "label": f"Score {h['score']} (tier {h['tier']})", "detail": ""})
    events.sort(key=lambda e: e["date"], reverse=True)
    return events


# --------------------------------------------------------------------------- #
# The workspace view + the priorities dashboard.
# --------------------------------------------------------------------------- #
def relationship_view(conn, agency_id: int) -> Dict:
    """Everything the relationship workspace shows for one agency — assembled from
    the engines' outputs (consumed, not recomputed) + the relationship layer."""
    row = db.get_agency(conn, agency_id)
    if row is None:
        return {}
    score_blob = db.get_agency_score(conn, agency_id) or {}
    interactions = list(db.list_agency_outreach(conn, agency_id))
    responded = any(o["responded"] for o in interactions)
    score = score_blob.get("score")
    rel = current_relationship(conn, agency_id, score=score, interactions=interactions,
                               responded=responded)
    tasks = [dict(t) for t in db.list_agency_tasks(conn, agency_id, status="open")]
    last = interactions[0] if interactions else None
    return {
        "agency_id": agency_id, "company": row["company"],
        "score": score, "tier": score_blob.get("tier"),
        "confidence": score_blob.get("confidence"),
        "stage": rel.stage, "dormant": rel.dormant, "stage_label": rel.label,
        "next_best_action": rel.next_best_action, "relationship_signals": rel.signals,
        "probability": _PROBABILITY.get(score_blob.get("tier") or "", "—"),
        "primary_contact": score_blob.get("recommended_contact"),
        "recommended_action": score_blob.get("recommended_action") or "Score the agency to get a recommendation",
        "best_timing": score_blob.get("best_timing"),
        "talking_points": score_blob.get("talking_points", []),
        "last_interaction": (last["occurred_at"][:10] if last else None),
        "interaction_count": len(interactions),
        "signal_count": db.count_opportunity_signals(conn, agency_id, active_only=True),
        "next_task": (tasks[0] if tasks else None),
        "open_tasks": tasks,
        "memory": [dict(m) for m in db.list_agency_memory(conn, agency_id)],
        "documents": [dict(d) for d in db.list_agency_documents(conn, agency_id)],
        "timeline": relationship_timeline(conn, agency_id),
    }


def daily_priorities(conn) -> Dict:
    """Today's Priorities — what Jon should act on, derived from the engines. Not
    'accounts' and 'contacts' — movements, follow-ups, and recommended outreach."""
    movers = [dict(r) for r in db.top_movers(conn, limit=50)]
    moved_to_a = [m for m in movers if (m["opportunity_tier"] == "A" and (m["score_movement"] or 0) > 0)]

    recent = db.recent_opportunity_signals(conn, limit=200, active_only=True)
    ep_hires = [r for r in recent if r["event_type"] == "Hiring"
                and r["music_relevance"] in ("Very High", "High")]
    campaigns = [r for r in recent if r["event_type"] in ("Campaign launch", "New work")]

    overdue = [dict(t) for t in db.overdue_tasks(conn, limit=50)]
    top = [dict(r) for r in db.top_opportunities(conn, limit=50)]
    # recommended outreach: high-tier agencies whose recommendation says reach out
    recommended = []
    for r in top:
        blob = db.get_agency_score(conn, r["id"]) or {}
        action = (blob.get("recommended_action") or "").lower()
        if r["opportunity_tier"] in ("A", "B") and "reach out" in action:
            recommended.append({"id": r["id"], "company": r["company"],
                                "score": r["opportunity_score"], "tier": r["opportunity_tier"],
                                "action": blob.get("recommended_action"),
                                "contact": blob.get("recommended_contact")})

    return {
        "moved_to_a": moved_to_a[:10], "moved_to_a_count": len(moved_to_a),
        "ep_hires": ep_hires[:10], "ep_hires_count": len(ep_hires),
        "campaigns": campaigns[:10], "campaigns_count": len(campaigns),
        "overdue": overdue, "overdue_count": len(overdue),
        "follow_ups_due_count": len(overdue),
        "recommended": recommended[:25], "recommended_count": len(recommended),
        "top_movers": movers[:10], "top_opportunities": top[:10],
    }
