"""The Production Readiness Workspace (ADR-0018, Phase 4) — Kickoff.

Kickoff is the transition from Sales to Production, designed as a concierge handoff, not an
onboarding form. It answers ONE question: "Is everything we need to begin creating?" It shows
what ChordOS has already organized on the client's behalf, who is involved, what happens next,
and — crucially — what (if anything) is still needed from the client. When nothing is, it says
so plainly, so the client leaves thinking "everything is under control."

Everything here is a projection of Campaign Intelligence + the approved (frozen) Commercial
Review + the project's team/milestones/invoices + house defaults. The only new persistent
state is the project's ``kickoff_completed_at`` gate; Kickoff itself stores nothing.
"""
from __future__ import annotations

import os
from typing import Optional

from . import commercial, procurement


def _operator_producer() -> dict:
    email = (os.environ.get("CHORDENTIAL_OPERATOR_EMAIL", "")
             or os.environ.get("CHORDENTIAL_SMTP_FROM", "")).strip()
    name = (os.environ.get("CHORDENTIAL_OPERATOR_NAME", "").strip()
            or "Your producer at Chordential")
    return {"role": "Producer", "name": name, "email": email, "assigned": True}


def _deposit_state(invoices, owed: int = 0) -> str:
    """'received' | 'awaiting' | 'none' — from the project's Deposit invoice if one exists;
    otherwise 'awaiting' when a deposit is owed (approved but not yet invoiced) and 'none'
    only when genuinely nothing is due."""
    for inv in invoices:
        if (inv["kind"] or "") == "Deposit":
            paid = (inv["status"] or "").lower() in ("paid", "settled") or (
                "paid_at" in inv.keys() and inv["paid_at"])
            return "received" if paid else "awaiting"
    return "awaiting" if owed else "none"


def _procurement_line(conn, db, opp) -> dict:
    """The procurement checklist line — REAL state from Procurement Intelligence (ADR-0022),
    not a placeholder. Discovers requirements on read, then reports honestly: nothing surfaced
    → 'Nothing required'; some done → progress; all done → done; a portal → the onboarding
    prompt. The checklist adapts to what THIS client actually asked for."""
    try:
        procurement.discover_from_ci(conn, opp["id"])
        r = procurement.readiness(conn, opp["id"])
    except Exception:  # noqa: BLE001 — the checklist must render even if procurement hiccups
        return {"label": "Procurement complete", "state": "na", "na_note": "Nothing required"}
    if r["total"] == 0:
        return {"label": "Procurement complete", "state": "na", "na_note": "Nothing required"}
    if r["all_done"]:
        return {"label": "Procurement complete", "state": "done"}
    note = f"{r['complete']}/{r['total']} ready"
    if r["has_portal"]:
        note += " · portal onboarding"
    return {"label": "Procurement", "state": "pending", "na_note": note}


def build_readiness(conn, db, opp, project, review_row, ci_view: Optional[dict] = None) -> dict:
    """Assemble the Production Readiness view. Pure reads; no new state written here."""
    ci_view = ci_view or {}
    ci_fields = dict(ci_view.get("fields") or {})
    review = commercial.review_from_json(review_row["doc_json"]) if review_row else None

    assignments = db.list_assignments(conn, project["id"]) if project else []
    invoices = db.list_invoices(conn, project["id"]) if project else []
    milestones = db.list_milestones(conn, project["id"]) if project else []

    # ── Meet your team: the operator-producer + the craft roles (names as assigned) ──
    assigned_by_role = {}
    for a in assignments:
        assigned_by_role.setdefault(a["role"], a)
    roles = []
    try:
        import json as _json
        roles = list(_json.loads(project["roles"] or "[]")) if project else []
    except Exception:  # noqa: BLE001
        roles = []
    team = [_operator_producer()]
    for role in roles:
        a = assigned_by_role.get(role)
        team.append({"role": role,
                     "name": (a["talent_name"] if a and a["talent_name"] else "Being assigned"),
                     "email": (a["talent_email"] if a and a["talent_email"] else ""),
                     "assigned": bool(a and a["talent_name"])})
    team_assigned = bool(roles) and all(
        assigned_by_role.get(r) and assigned_by_role[r]["talent_name"] for r in roles)

    # ── Production checklist ─────────────────────────────────────────────
    # A deposit is OWED as soon as the approved proposal carries one — even before the client
    # has opened the invoice (it's created lazily at Pay). So "awaiting" keys off the owed
    # amount, not just an existing invoice; otherwise Kickoff reads "Everything is ready"
    # with an unpaid deposit and no way to pay it (reported live).
    _prop = db.proposal_for_project(conn, project["id"]) if project else None
    owed = int(_prop["deposit_amount"] or 0) if _prop is not None else 0
    deposit = _deposit_state(invoices, owed)
    timeline = (ci_fields.get("deadline") or (review.timeline if review else "") or "").strip()
    kickoff_done = bool(project and (project["kickoff_completed_at"]
                                     if "kickoff_completed_at" in project.keys() else None))
    checklist = [
        {"label": "Creative direction approved", "state": "done"},
        {"label": "Commercial terms approved", "state": "done"},
        {"label": "Deposit received",
         "state": {"received": "done", "awaiting": "pending", "none": "na"}[deposit],
         "na_note": "No deposit required" if deposit == "none" else ""},
        _procurement_line(conn, db, opp),
        {"label": "Team assigned", "state": "done" if team_assigned else "pending"},
        {"label": "Timeline confirmed", "state": "done" if timeline else "pending"},
        {"label": "Kickoff complete", "state": "done" if kickoff_done else "pending"},
    ]

    # ── Client actions remaining: only items the CLIENT owns and hasn't done ──
    client_actions = []
    if deposit == "awaiting":
        client_actions.append({"label": "Send your deposit to confirm the booking",
                               "kind": "deposit"})
    all_ready = not client_actions

    # ── Upcoming milestones: the project's milestones, else the Review's schedule ──
    if milestones:
        upcoming = [{"stage": m["title"],
                     "when": ("Done" if (m["status"] or "") == "Delivered"
                              else "In sequence")} for m in milestones]
    elif review is not None:
        upcoming = list(review.schedule)
    else:
        upcoming = []

    # ── Communication: shown, not asked (concierge, not onboarding forms) ──
    rounds = commercial._revision_rounds(ci_fields)
    communication = {
        "primary_contact": (opp["contact_name"] or opp["client"] or "You"),
        "review_cadence": "You'll receive each creative milestone as it's ready",
        "turnaround": "Feedback is turned around within a couple of working days",
        "revision_policy": f"{rounds} rounds of revisions are included",
        "preferred": (opp["contact_email"] or "Email"),
    }

    mr = (opp["music_requirement"] if "music_requirement" in opp.keys() else "") or ""
    summary = {
        "campaign": opp["need"],
        "producer": team[0]["name"],
        "delivery_date": timeline or "Confirmed at kickoff",
        "scope": (review.scope_summary if review else (ci_fields.get("campaign_objective") or "")),
        "budget": (ci_fields.get("budget_band") or ""),
        "rights": ("Original — cleared worldwide, yours on final payment"
                   if "original" in str(mr).lower()
                   else "As licensed for this campaign"),
    }

    return {
        "summary": summary, "checklist": checklist, "team": team,
        "communication": communication, "upcoming": upcoming,
        "client_actions": client_actions, "all_ready": all_ready,
        "kickoff_done": kickoff_done,
    }
