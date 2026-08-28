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
    # `house` — this one is OURS, and the only team member a buyer may be named.
    # Every other card is the roster (`room.CAPS` denies a client `see_who`), so the
    # subtraction needs to tell "the producer they email" apart from "the freelancer
    # whose name walks out of the door".
    return {"role": "Producer", "name": name, "email": email, "assigned": True,
            "house": True}


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


def _procurement_line(conn, db, opp, discover: bool = True) -> dict:
    """The procurement checklist line — REAL state from Procurement Intelligence (ADR-0022),
    not a placeholder. Discovers requirements on read, then reports honestly: nothing surfaced
    → 'Nothing required'; some done → progress; all done → done; a portal → the onboarding
    prompt. The checklist adapts to what THIS client actually asked for."""
    try:
        # `discover` WRITES (it materialises requirements from CI). The room reports this
        # line on every render, for every role, and a reporter must not discover — so the
        # room reads what is on file and the operator's Kickoff page is what finds it.
        if discover:
            procurement.discover_from_ci(conn, opp["id"])
        r = procurement.readiness(conn, opp["id"])
    except Exception:  # noqa: BLE001 — the checklist must render even if procurement hiccups
        return {"label": "Procurement complete", "state": "na",
                "na_note": "Nothing required", "lens": "commercial"}
    if r["total"] == 0:
        return {"label": "Procurement complete", "state": "na",
                "na_note": "Nothing required", "lens": "commercial"}
    if r["all_done"]:
        return {"label": "Procurement complete", "state": "done", "lens": "commercial"}
    note = f"{r['complete']}/{r['total']} ready"
    if r["has_portal"]:
        note += " · portal onboarding"
    return {"label": "Procurement", "state": "pending", "na_note": note,
            "lens": "commercial"}


def build_readiness(conn, db, opp, project, review_row, ci_view: Optional[dict] = None,
                    portal_url: str = "", discover: bool = True) -> dict:
    """Assemble the Production Readiness view. Pure reads; no new state written here.

    ``portal_url`` is the client's own token-gated delivery portal, passed in rather than
    minted here so this module stays read-only. Without it the assets action still names
    what is needed; with it, the client can act on it.
    """
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
    _delivery = db.get_delivery(conn, project["id"]) if project else {}
    has_picture = bool((_delivery or {}).get("picture"))
    timeline = (ci_fields.get("deadline") or (review.timeline if review else "") or "").strip()
    kickoff_done = bool(project and (project["kickoff_completed_at"]
                                     if "kickoff_completed_at" in project.keys() else None))
    checklist = [
        {"label": "Creative direction approved", "state": "done"},
        {"label": "Commercial terms approved", "state": "done"},
        # `lens: commercial` — the buyer's money and the buyer's onboarding. The studio
        # and the buyer see these; a creator never does. Tagged on the ROW rather than
        # matched by label in the subtraction, because a label is copy and copy gets
        # rewritten, and the day it does the row would silently start reaching creators.
        {"label": "Deposit received",
         "state": {"received": "done", "awaiting": "pending", "none": "na"}[deposit],
         "na_note": "No deposit required" if deposit == "none" else "",
         "lens": "commercial"},
        _procurement_line(conn, db, opp, discover=discover),
        {"label": "Your picture received",
         "state": "done" if has_picture else "pending"},
        {"label": "Team assigned", "state": "done" if team_assigned else "pending"},
        {"label": "Timeline confirmed", "state": "done" if timeline else "pending"},
        {"label": "Kickoff complete", "state": "done" if kickoff_done else "pending"},
    ]

    # ── Client actions remaining: only items the CLIENT owns and hasn't done ──
    #
    # The picture is one of them, and it was missing. The composer's session room is built
    # around the client's cut — it renders "picture arrives with the client's cut" and
    # waits — and the delivery portal has had the Drop that receives it all along. Nothing
    # ever ASKED for it: Kickoff listed the deposit and nothing else, so a client whose
    # deposit was settled read "Everything is ready" while the room their money had
    # started sat empty, waiting on footage nobody had requested. Reported live.
    #
    # It is not gated on the deposit. Sending us the cut early costs the client nothing
    # and is the single most useful thing they can do while we assign the composer.
    client_actions = []
    if deposit == "awaiting":
        client_actions.append({"label": "Send your deposit to confirm the booking",
                               "kind": "deposit"})
    if project is not None and not has_picture:
        client_actions.append({
            "label": "Send us the cut your music is written to, and any references",
            "kind": "assets", "url": portal_url,
            "cta": "Upload your picture →" if portal_url else ""})
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
        "rights": rights_line(mr),
    }

    return {
        "summary": summary, "checklist": checklist, "team": team,
        "communication": communication, "upcoming": upcoming,
        "client_actions": client_actions, "all_ready": all_ready,
        "kickoff_done": kickoff_done,
    }

def rights_line(music_requirement: str) -> str:
    """What the buyer owns, in one line. ONE derivation of these words.

    It was written inline in the campaign summary above and shown only on the client
    workspace. When the client moved into the room it would have gone with it — a buyer who
    can no longer see what they bought — so it is a function, read by both, rather than a
    sentence retyped into a second template.
    """
    return ("Original, cleared worldwide, yours on final payment"
            if "original" in str(music_requirement or "").lower()
            else "As licensed for this campaign")


def readiness_for_project(conn, db, project_id: int, portal_url: str = "",
                          discover: bool = True) -> Optional[dict]:
    """`build_readiness` for a project, resolved from the project id alone.

    The resolution — project → opportunity → current review — was written inside
    `client_gate` and is now needed by the room's checklist too. One copy, because two
    readiness views built from different rows is exactly the disagreement ADR-0029 keeps
    being written about.
    """
    project = db.get_project(conn, project_id)
    if project is None or not project["opp_id"]:
        return None
    opp = db.get_opportunity(conn, project["opp_id"])
    if opp is None:
        return None
    return build_readiness(conn, db, opp, project,
                           db.current_commercial_review(conn, opp["id"]),
                           portal_url=portal_url, discover=discover)


def client_gate(conn, db, project_id: int, portal_url: str = "",
                ready: Optional[dict] = None) -> Optional[dict]:
    """What the CLIENT still has to do before production really starts — or ``None``.

    THE KICKOFF GATE, MOVED INTO THE ROOM. It lived on the client workspace, which is no
    longer where a client goes after the countersignature: *"the pay the deposit and upload
    assets gate can live inside 'the room' hub where they will interact with the composer
    and studio"* (operator, 2026-08-27).

    Both asks come from `build_readiness` rather than being re-derived, so the room and the
    operator's readiness view cannot reach different conclusions about what a client owes.
    ``ready`` lets a caller that has already built it — the room, which renders the whole
    checklist — hand it over instead of paying for a second one that must agree.
    THE PICTURE IS NOT GATED ON THE DEPOSIT and must not become so here: sending the cut
    early costs the client nothing and is the most useful thing they can do while a composer
    is being assigned. Both stand at once or neither does.
    """
    proposal = db.proposal_for_project(conn, project_id)
    if proposal is None:
        return None
    if ready is None:
        ready = readiness_for_project(conn, db, project_id, portal_url=portal_url)
    if ready is None:
        return None
    actions = list(ready.get("client_actions") or [])
    if not actions:
        return None
    invoices = db.list_invoices(conn, project_id)
    invoice = next((i for i in invoices if (i["kind"] or "") == "Deposit"), None)
    settled = invoice is not None and (invoice["status"] or "").lower() in ("paid", "settled")
    amount = (invoice["amount"] if invoice is not None else proposal["deposit_amount"]) or 0
    deposit = None
    if amount and not settled:
        # The PROJECT share token: `/pay` authorises on that one specifically, and handing
        # it the opportunity's produces a Pay button that bounces.
        deposit = {"amount": amount, "pid": int(project_id),
                   "ptok": db.ensure_project_share_token(conn, int(project_id))}
    return {"actions": actions, "deposit": deposit}
