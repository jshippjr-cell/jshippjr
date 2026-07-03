"""Campaign Intelligence (Creative OS) — the canonical, LIVING per-engagement record.

The stable spine every module inherits from and contributes back to, through one
provenance model. This module is the DOMAIN layer: the field catalog (facets × keys ×
kinds), the kind-aware disposition rules, the provenance API (contribute / dispose /
seed), and the read view. Storage primitives live in db.py; the design is in
docs/architecture/CAMPAIGN_INTELLIGENCE.md.

Every fact carries three orthogonal dimensions:
  • facet — which body of knowledge (engagement/buyer/direction/commercial/…)
  • kind  — what KIND of knowledge (fact / insight / recommendation / open_question)
  • provenance — sources[] (who says so) + status (how disposed) — machine proposes,
    the human disposes (Constitution §4.1).
"""
from __future__ import annotations

from typing import List, Optional

from . import db

FACETS = ["engagement", "buyer", "direction", "commercial", "relationship", "outcome"]
KINDS = ["fact", "insight", "recommendation", "open_question"]

# The disposition lifecycle is KIND-AWARE, but there is always ONE gate: a human moves
# a field from its OPEN state to its DISPOSED state (§4bis). CI-1 wires the single
# primary disposition per kind; richer verbs (deferred/declined/dismissed) come later.
KIND_OPEN_STATUS = {
    "fact": "needs_review", "insight": "noted",
    "recommendation": "open", "open_question": "open",
}
KIND_DISPOSED_STATUS = {
    "fact": "confirmed", "insight": "acknowledged",
    "recommendation": "accepted", "open_question": "answered",
}
KIND_LABEL = {
    "fact": "Fact", "insight": "Insight",
    "recommendation": "Recommendation", "open_question": "Open question",
}
KIND_DISPOSE_VERB = {  # the button label for disposing an open field
    "fact": "Confirm", "insight": "Acknowledge",
    "recommendation": "Accept", "open_question": "Mark answered",
}

DISPOSED_STATUSES = set(KIND_DISPOSED_STATUS.values())


def is_open(status: str) -> bool:
    """True when a field still awaits a human's disposition."""
    return status not in DISPOSED_STATUSES


# --------------------------------------------------------------------------- #
# Provenance API — contribute (any module) + dispose (the human gate).
# --------------------------------------------------------------------------- #
def contribute(conn, ci_id: int, facet: str, key: str, value: str, *,
               kind: str = "fact", source: str, contributed_by: str = "",
               confidence: Optional[int] = None, is_concern: bool = False,
               value_json=None, confirmed: bool = False) -> int:
    """Contribute a fact/insight/recommendation/open_question to Campaign Intelligence
    through the provenance model — the ONE way every module (intake, proposal, workspace,
    production, delivery, client success, retrospective) writes. Lands at the OPEN status
    for its kind (machine/non-owner proposes) unless ``confirmed`` (the operator, or an
    owner writing its own facet, disposing directly). Merges the source; logs the event."""
    if facet not in FACETS or kind not in KINDS:
        raise ValueError(f"bad facet/kind: {facet}/{kind}")
    status = KIND_DISPOSED_STATUS[kind] if confirmed else KIND_OPEN_STATUS[kind]
    fid = db.upsert_ci_field(
        conn, ci_id, facet, key, kind, value=value, value_json=value_json,
        source=source, status=status, origin=source,
        confidence=confidence, is_concern=is_concern, contributed_by=contributed_by or source)
    db.add_ci_event(conn, ci_id, actor=(contributed_by or source),
                    verb=("confirmed" if confirmed else "contributed"),
                    facet=facet, key=key, kind=kind, to_value=value[:200], source=source)
    return fid


def dispose(conn, field_row, actor: str = "operator") -> None:
    """The human disposition gate: move an open field to its disposed state for its kind
    (confirm a fact, acknowledge an insight, accept a recommendation, answer a question).
    Only a human calls this — the machine can only ever leave a field OPEN."""
    kind = field_row["kind"]
    new_status = KIND_DISPOSED_STATUS.get(kind, "confirmed")
    db.set_ci_field_status(conn, field_row["id"], new_status)
    db.add_ci_event(conn, field_row["ci_id"], actor=actor, verb=new_status,
                    facet=field_row["facet"], key=field_row["key"], kind=kind)


# --------------------------------------------------------------------------- #
# Lazy creation + seeding — a CI for every campaign, populated from upstream.
# --------------------------------------------------------------------------- #
def ensure_for_campaign(conn, campaign_row):
    """Get (or lazily create + seed) the Campaign Intelligence for a campaign. Idempotent
    (one CI per campaign). Seeds from the opportunity (engagement facts), the linked
    agency (buyer snapshot — reachable via the Step-1 agency_id), and the increment-1
    creative-direction cards (direction facts). Empty upstream → empty CI (honesty:
    nothing is invented)."""
    existing = db.ci_for_campaign(conn, campaign_row["id"])
    if existing is not None:
        return existing
    ci_id = db.create_campaign_intelligence(
        conn, campaign_id=campaign_row["id"], opp_id=campaign_row["opp_id"],
        agency_id=campaign_row["agency_id"], project_id=campaign_row["project_id"],
        title=campaign_row["title"], brand=campaign_row["brand"],
        agency_client=campaign_row["agency_client"])
    _seed(conn, ci_id, campaign_row)
    db.add_ci_event(conn, ci_id, actor="system", verb="seeded")
    return db.get_campaign_intelligence(conn, ci_id)


def get_for_campaign(conn, campaign_row):
    return db.ci_for_campaign(conn, campaign_row["id"])


def _txt(v) -> str:
    """Best-effort display string from a maybe-structured intel value ({value:…}, list, …)."""
    if v is None:
        return ""
    if isinstance(v, dict):
        v = v.get("value", v.get("summary", ""))
    if isinstance(v, list):
        return ", ".join(_txt(x) for x in v if x)
    return str(v).strip()


def _seed(conn, ci_id: int, campaign) -> None:
    # ── engagement facts (from the opportunity / campaign) ──────────────────
    if campaign["brand"]:
        contribute(conn, ci_id, "engagement", "brand", campaign["brand"],
                   source="opportunity", contributed_by="system")
    bmin, bmax = campaign["budget_min"], campaign["budget_max"]
    if bmin or bmax:
        band = (f"${int(bmin):,}–${int(bmax):,}" if bmin and bmax and bmin != bmax
                else f"${int(bmax or bmin):,}")
        contribute(conn, ci_id, "engagement", "budget_band", band,
                   source="opportunity", contributed_by="system")
    if campaign["deadline"]:
        contribute(conn, ci_id, "engagement", "deadline", campaign["deadline"],
                   source="opportunity", contributed_by="system")

    # ── buyer snapshot (from the linked Agency/Company Intelligence) ─────────
    if campaign["agency_id"]:
        intel = db.get_agency_intel(conn, campaign["agency_id"]) or {}
        for key, ik in (("how_they_work", "executive_summary"),
                        ("production_complexity", "production_complexity"),
                        ("music_characteristics", "music_usage"),
                        ("typical_clients", "typical_clients"),
                        ("campaign_types", "campaign_types")):
            val = _txt(intel.get(ik))
            if val:
                contribute(conn, ci_id, "buyer", key, val,
                           source="agency_intelligence", contributed_by="system")
        state = db.get_agency_enrichment(conn, campaign["agency_id"]) or {}
        profile = (state.get("profile") or {})
        if profile.get("portfolio"):
            contribute(conn, ci_id, "buyer", "previous_campaigns",
                       _txt(profile["portfolio"]), source="agency_intelligence",
                       contributed_by="system", value_json=profile["portfolio"])

    # ── direction facts (from the increment-1 creative-direction cards) ─────
    # The STATED brief is a fact; a section the operator marked complete is disposed.
    for row in conn.execute(
            "SELECT * FROM campaign_direction WHERE campaign_id = ?", (campaign["id"],)):
        body = (row["body"] or "").strip()
        if body:
            contribute(conn, ci_id, "direction", row["section"], body,
                       source="workspace", contributed_by="operator",
                       confirmed=bool(row["complete"]))


# --------------------------------------------------------------------------- #
# Read view for the UI — grouped by facet, with kind/sources/status decorated.
# --------------------------------------------------------------------------- #
def fields_view(conn, ci_id: int) -> dict:
    """Fields grouped by facet, each decorated for the provenance card:
    {facet: [{id, key, kind, kind_label, value, sources[], status, open, is_concern,
    dispose_verb}]}."""
    import json as _json
    grouped: dict = {f: [] for f in FACETS}
    counts = {"total": 0, "open": 0}
    for r in db.list_ci_fields(conn, ci_id):
        try:
            sources = _json.loads(r["sources"]) or []
        except (_json.JSONDecodeError, TypeError):
            sources = []
        item = {
            "id": r["id"], "key": r["key"], "kind": r["kind"],
            "kind_label": KIND_LABEL.get(r["kind"], r["kind"]),
            "label": r["key"].replace("_", " ").title(),
            "value": r["value"], "sources": sources, "status": r["status"],
            "open": is_open(r["status"]), "is_concern": bool(r["is_concern"]),
            "dispose_verb": KIND_DISPOSE_VERB.get(r["kind"], "Confirm"),
        }
        grouped.setdefault(r["facet"], []).append(item)
        counts["total"] += 1
        if item["open"]:
            counts["open"] += 1
    return {"by_facet": grouped, "counts": counts,
            "facets_present": [f for f in FACETS if grouped.get(f)]}
