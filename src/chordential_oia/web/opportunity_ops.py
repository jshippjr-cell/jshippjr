"""The opportunity-side helpers shared across route groups.

``_load`` is the smallest and the most load-bearing: /opportunity and /project both open
a record through it, and it is 58 + 57 routes' worth of blocker for seven lines of code.
The rest are here for the same reason and no other — each is called from more than one
group (/buyer, /matchboard, /meeting, /workspace, /opportunity, /project).

Nothing in this module renders. Nothing in it decides — ``reconcile_opp_status`` only
moves a deal *forward* to the stage the record already implies, and never past a stage a
human chose.
"""

from __future__ import annotations

from typing import Optional

from ..capabilities import quote_band as capabilities_quote_band
from ..models import BuyerValue, MusicDiscipline
from . import campaign_intelligence, campaigns, db, production
from .buyer_intel import relationship_for
from .estimate import estimate_for
from .evaluate import evaluate


# The linear stage vocabulary, rendered as the detail page's stepper rail and used
# to order the pipeline. (It named the /lanes kanban's columns too, until ADR-0035
# deleted that board.) Friendly labels are applied at the view layer via stage_label.
_KANBAN_STAGES = ["New", "Pursuing", "Submitted", "Won"]


def _load(conn, opp_id: int):
    row = db.get_opportunity(conn, opp_id)
    if row is None:
        return None, None, None
    opp = db.opportunity_from_row(row)
    qual, scored = evaluate(opp)
    return row, opp, (qual, scored)


def _to_utc_iso(local_iso: str, tz_offset_min: str) -> str:
    """Convert a naive LOCAL wall-clock datetime (what the user typed) to a UTC ISO string,
    using the browser's ``getTimezoneOffset()`` minutes (positive when local is behind UTC —
    e.g. US Eastern = 240). No offset → treated as UTC. So the operator never does the math."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    s = (local_iso or "").strip().replace(" ", "T")
    if not s:
        return ""
    try:
        naive = _dt.fromisoformat(s)
    except ValueError:
        return ""
    try:
        off = int(str(tz_offset_min).strip())
    except (ValueError, TypeError):
        off = 0
    return (naive + _td(minutes=off)).replace(tzinfo=_tz.utc).isoformat()


def _reconcile_opp_status(conn, opp_id, project=None) -> None:
    """Keep the pipeline stage honest with where the deal actually is (ADR-0020 §6): the
    New → Reaching out → Proposal out → Won buttons follow the lifecycle automatically.
    FORWARD-only — a manual override or a later stage is never rolled back; a closed deal
    (Won/Lost/Passed) is left alone. Called at each transition and as a self-heal on view."""
    row = db.get_opportunity(conn, opp_id)
    if row is None:
        return
    cur = row["status"]
    if cur in ("Won", "Lost", "Passed"):
        return
    order = _KANBAN_STAGES                       # New, Pursuing, Submitted, Won
    review = db.current_commercial_review(conn, opp_id)
    proj = project if project is not None else db.project_for_opp(conn, opp_id)
    approved = bool(review) and review["status"] == "approved"
    if approved or proj is not None:
        implied = "Won"
    elif review is not None and review["status"] == "released":
        implied = "Submitted"                    # "Proposal out"
    else:
        met = any((m["status"] in ("ingested", "transcript_ready"))
                  for m in db.list_meetings(conn, opp_id))
        confirmed = bool(db.get_doc_overrides(conn, opp_id).get("scope_confirmed"))
        snap = db.latest_brief_snapshot(conn, opp_id) if hasattr(db, "latest_brief_snapshot") else None
        implied = "Pursuing" if (met or confirmed or snap) else "New"   # "Reaching out"
    if cur in order and implied in order and order.index(implied) > order.index(cur):
        try:
            db.update_status(conn, opp_id, implied, row["outcome_value"])
        except Exception:  # noqa: BLE001 — status honesty never blocks the request
            pass


def _buyer_context(conn, client: str) -> Optional[dict]:
    """Assemble the full buyer-profile context (None when the buyer is unknown).
    Shared by the standalone /buyer/{client} page and the opp-scoped tab."""
    rows = db.buyer_opportunities(conn, client)
    if not rows:
        return None
    touch = db.buyer_touch_summary(conn, client)
    contacts = db.buyer_contacts(conn, client)
    website = db.company_website(conn, client)

    won = [r for r in rows if r["status"] == "Won"]
    lost = [r for r in rows if r["status"] == "Lost"]
    pursuing = [r for r in rows if r["status"] in ("Pursuing", "Submitted")]
    decided = len(won) + len(lost)

    # Strategic standing is a buyer-level attribute — resolve the strongest seen.
    bv_rank = {"enterprise": 3, "repeat": 2, "one_time": 1, "unknown": 0}
    best_bv = max((r["buyer_value"] or "unknown" for r in rows), key=lambda v: bv_rank.get(v, 0))
    tier_rank = {"Door-opener": 3, "High": 2, "Medium": 1, "Low": 0}
    best_tier = max(
        (r["strategic_tier"] for r in rows if r["strategic_tier"]),
        key=lambda t: tier_rank.get(t, 0), default=None,
    )
    strat_vals = [r["strategic_value"] for r in rows if r["strategic_value"] is not None]

    summary = {
        "client": client,
        "buyer_type": rows[0]["buyer_type"],
        "total": len(rows),
        "qualified": sum(1 for r in rows if r["qualified"]),
        "won": len(won),
        "lost": len(lost),
        "pursuing": len(pursuing),
        "win_rate": (len(won) / decided * 100.0) if decided else None,
        "won_value": sum((r["outcome_value"] or 0) for r in won),
        "avg_alignment": (sum(r["alignment"] or 0 for r in rows) / len(rows)),
        "disciplines": sorted({r["discipline"] for r in rows if r["qualified"]}),
        # CMO buyer-value standing
        "buyer_value": BuyerValue(best_bv).label,
        "marquee": any(r["marquee"] for r in rows),
        "strategic_tier": best_tier,
        "avg_strategic": (sum(strat_vals) / len(strat_vals)) if strat_vals else None,
    }
    # The same company's Agency Intelligence record and its outreach log — the half of
    # the evidence this page could not see, and the reason it and /relationships used to
    # disagree about one buyer (ADR-0057).
    org = db.find_org(conn, client)
    agency_id = org["agency_id"] if org is not None else None
    rel = relationship_for(
        deal={"opps": len(rows), "qualified": summary["qualified"],
              "won": len(won), "lost": len(lost), "open_pursuits": len(pursuing),
              "touches": int(touch["touches"] or 0),
              "last_contacted": touch["last_contacted"]},
        outreach=db.outreach_aggregate(conn, [agency_id]).get(agency_id)
                 if agency_id else None,
        strategic_tier=best_tier,
    )
    return {
        "summary": summary, "rows": rows, "rel": rel, "contacts": contacts,
        "last_contacted": touch["last_contacted"], "company_website": website,
        "agency_id": agency_id,
    }


def _brief_ci_context(conn, row):
    """ADR-0017: the brief renders Campaign Intelligence first. Returns (ci_view, met) —
    the canonical CI values + whether a discovery meeting has actually happened (tone)."""
    from datetime import datetime, timezone
    ci_view, met = {}, False
    if campaigns.workspace_enabled():
        try:
            ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
            ci_view = campaign_intelligence.brief_view(conn, ci_row["id"])
        except Exception:  # noqa: BLE001 — the brief must render even if CI hiccups
            ci_view = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    for m in db.list_meetings(conn, row["id"]):
        if m["status"] in ("ingested", "transcript_ready") or (
                m["status"] not in ("canceled",) and (m["start_at"] or "") and
                m["start_at"] <= now_iso):
            met = True
            break
    return ci_view, met


def _ensure_project_for_opp(conn, opp_id: int) -> Optional[int]:
    """Return the opportunity's project id, creating the project (with scoped
    roles + default milestones) if it doesn't exist yet. Shared by the project
    button and the Match Board so both stay in sync."""
    existing = db.project_for_opp(conn, opp_id)
    if existing is not None:
        return existing["id"]
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None
    qual, scored = ev
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    roles = qual.team_shape or discipline.team_shape
    # Thread the buyer link: resolve (and record on the opp) the Agency Intelligence
    # record this opportunity is for, so the project — and the campaign it becomes —
    # can reach the agency's intelligence, not just a client name. Best-effort: an
    # exact name match or nothing (DISCOVERY_INTELLIGENCE_LINEAGE.md, step 1).
    agency_id = db.resolve_opportunity_agency(conn, row)
    # ADR-0018: the project inherits the opportunity's workspace token so the client's
    # single URL never changes across the award boundary.
    workspace_token = db.ensure_share_token(conn, opp_id)
    pid = db.insert_project(
        conn, opp_id, opp.client, opp.need, opp.budget_min, opp.budget_max, roles,
        agency_id=agency_id, share_token=workspace_token,
    )
    db.seed_default_milestones(conn, pid, roles)
    # ADR-0020: Direction is born in Discovery — production inherits it. Seed the approved
    # creative territory from Campaign Intelligence; nobody creates directions later.
    if campaigns.workspace_enabled():
        try:
            ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
            fields = campaign_intelligence.brief_view(conn, ci_row["id"]).get("fields") or {}
            name_ = (fields.get("campaign_objective") or "").strip()
            thesis = (fields.get("emotional_arc") or "").strip()
            if name_ or thesis:
                d = production.add_direction(conn, db, pid,
                                             name=(name_ or "The approved direction")[:80],
                                             thesis=thesis[:160])
                if d:
                    production.decide_direction(conn, db, pid, d["id"], status="selected")
        except Exception:  # noqa: BLE001 — seeding never blocks the award
            pass
    return pid


def _estimate_for_row(conn, row, opp, qual=None):
    """THE estimate behind a client-facing quote for this opportunity.

    `estimate_for` is already the one path that turns a row into an estimate (ADR-0033),
    but it leaves each caller to decide whether to pass ``project_id`` — and that choice
    changes the client's price, because passing it swaps global role defaults for the
    assigned creators' real rates. So the app had two conventions for "the estimate for
    this opp", and the Commercial Review used one while the project's own proposal used
    the other. That divergence was invisible while the quote came from the client's
    stated budget, since the budget won whatever estimate fed it; when the price started
    deriving from the work (ADR-0065) the two documents disagreed on the deposit.

    One rule, stated once: if the deal has a project, its assigned rates are the truth.
    Reach for this from anywhere a BUYER will see the number.
    """
    proj = db.project_for_opp(conn, row["id"])
    return estimate_for(opp, conn=conn, qual=qual,
                        project_id=(proj["id"] if proj is not None else None))


def agreement_doc_for(conn, opp_id):
    """THE signable document for a deal — the one the client reads and signs, rebuilt.

    Every surface that touches the signature must produce byte-identical text or the
    digest is worthless: the client's workspace, the operator's copy of the brief, and
    the countersign route all hash `doc.agreement.signable_text()`. Three places built
    it independently and two of them had already drifted — once on the deposit line, once
    on the estimate — so it is derived here, once, and reported everywhere else.

    Returns ``(row, opp, ev, doc, deposit_amount)``, or ``(None, …)`` if the deal is gone.
    """
    from ..capabilities import (
        attach_agreement, build_capabilities_doc, default_toggles,
        quote_band as _qb,
    )
    from ..proposals import build_proposal
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None, None, None, None, 0
    qual, _scored = ev
    est = _estimate_for_row(conn, row, opp, qual)
    overrides = db.get_doc_overrides(conn, opp_id)
    ci_view, met = _brief_ci_context(conn, row)
    toggles = default_toggles(row["status"], met=met)
    # Before the call there is no scoping, so no honest number, so no priced summary and
    # nothing to sign (ADR-0065's `met` gate — the half of ADR-0020 that was right).
    if not met:
        toggles.update({"cost": False, "terms": False})
    doc = build_capabilities_doc(
        opp, qual, est, toggles=toggles, overrides=overrides,
        call_url="", ci_view=ci_view, met=met)
    ci_fields = (ci_view or {}).get("fields") or {}
    deposit_amount = build_proposal(
        opp, qual, est,
        quote_band=_qb(opp, est, ci_fields=ci_fields,
                       commercial_overrides=(overrides or {}).get("commercial")),
    ).deposit_amount
    project = db.project_for_opp(conn, opp_id)
    if project is not None:
        stored = db.proposal_for_project(conn, project["id"])
        if stored is not None and stored["deposit_amount"]:
            deposit_amount = stored["deposit_amount"]
    attach_agreement(doc, deposit_amount=deposit_amount)
    return row, opp, ev, doc, deposit_amount


def _quote_band_for(conn, row, opp, est):
    """THE number we'd put in front of this buyer (ADR-0034) — the same call the
    client's Campaign Brief and Commercial Review render. Resolving it needs the DB
    (Campaign Intelligence + the operator's commercial overrides), which is why the
    engines take it as a parameter rather than deriving one each."""
    ci_view, _met = _brief_ci_context(conn, row)
    overrides = db.get_doc_overrides(conn, row["id"]).get("commercial") or {}
    return capabilities_quote_band(
        opp, est, ci_fields=(ci_view or {}).get("fields") or {},
        commercial_overrides=overrides,
    )
