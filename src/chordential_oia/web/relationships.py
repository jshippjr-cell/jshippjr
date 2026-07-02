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

from . import db

STAGES = ("Cold", "Warm Prospect", "Active", "Client", "Dormant")
_PROBABILITY = {"A": "High", "B": "Medium", "C": "Low", "D": "Low"}


def _days_since(iso: str) -> int:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, TypeError):
        return 99999


# --------------------------------------------------------------------------- #
# Relationship Agent — derive the stage from what we know.
# --------------------------------------------------------------------------- #
def derive_stage(*, score: Optional[int], interactions: List, responded: bool) -> str:
    """The lifecycle stage, deterministically. A human can override it (stored on
    the relationship); this is the automatic default."""
    if interactions:
        last_days = min(_days_since(i["occurred_at"]) for i in interactions)
        if responded:
            return "Active" if last_days <= 120 else "Dormant"
        return "Active" if last_days <= 90 else "Dormant"
    # never interacted: it's a prospect we know about, warm if it scores well
    if score is not None and score >= 60:
        return "Warm Prospect"
    return "Cold"


def _stage_from_rollup(score: Optional[int], agg: Optional[dict]) -> str:
    """derive_stage, computed from the batched outreach rollup ({last_touch,
    responded, count}) instead of the full interactions list — identical logic, so
    the pipeline view derives the same stage without loading every touch per row."""
    if agg and agg.get("count"):
        last_days = _days_since(agg["last_touch"])
        if agg.get("responded"):
            return "Active" if last_days <= 120 else "Dormant"
        return "Active" if last_days <= 90 else "Dormant"
    if score is not None and score >= 60:
        return "Warm Prospect"
    return "Cold"


def pipeline_stages(conn, rows: List) -> List[dict]:
    """Stage each scored agency in ``rows`` with O(1) queries: ONE outreach aggregate
    + ONE relationships fetch for the whole set, deriving stages in memory and
    persisting only the changed (non-overridden) ones in a SINGLE transaction.

    Replaces the per-row loop that ran list_agency_outreach + get_relationship for
    every row and committed the cached stage per changed row (~150 queries + up to 50
    fsync commits on the /relationships read path). Behaviour is unchanged: an
    overridden stage is honored; otherwise the same deterministic stage is derived
    and cached."""
    ids = [r["id"] for r in rows]
    agg = db.outreach_aggregate(conn, ids)
    rels = db.relationships_by_ids(conn, ids)
    out: List[dict] = []
    changed = False
    for r in rows:
        aid = r["id"]
        rel = rels.get(aid)
        if rel is not None and rel["stage_overridden"] and rel["stage"]:
            stage = rel["stage"]
        else:
            stage = _stage_from_rollup(r["opportunity_score"], agg.get(aid))
            if rel is None or rel["stage"] != stage:
                db.upsert_relationship(conn, aid, stage=stage)   # no commit yet
                changed = True
        out.append({"id": aid, "company": r["company"],
                    "score": r["opportunity_score"], "tier": r["opportunity_tier"],
                    "stage": stage, "movement": r["score_movement"]})
    if changed:
        conn.commit()                                            # ONE commit for the batch
    return out


def current_stage(conn, agency_id: int, *, score: Optional[int],
                  interactions: List, responded: bool) -> str:
    rel = db.get_relationship(conn, agency_id)
    if rel and rel["stage_overridden"] and rel["stage"]:
        return rel["stage"]
    stage = derive_stage(score=score, interactions=interactions, responded=responded)
    # cache the derived stage (without marking it overridden)
    if not rel or rel["stage"] != stage:
        db.upsert_relationship(conn, agency_id, stage=stage)
        conn.commit()
    return stage


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
    stage = current_stage(conn, agency_id, score=score, interactions=interactions,
                          responded=responded)
    tasks = [dict(t) for t in db.list_agency_tasks(conn, agency_id, status="open")]
    last = interactions[0] if interactions else None
    return {
        "agency_id": agency_id, "company": row["company"],
        "score": score, "tier": score_blob.get("tier"),
        "confidence": score_blob.get("confidence"),
        "stage": stage,
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
