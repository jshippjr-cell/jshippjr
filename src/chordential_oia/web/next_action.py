"""The operator's Next Action (ADR-0020 §6): decision-oriented, not page-oriented.

Every deal exposes exactly ONE obvious next move. Everything else is supporting context.
This mirrors the client's court-state, pointed inward: at any moment the answer to "what
should I do next?" is computed, never remembered.

Returns a dict:
  {court: 'you'|'client'|'team'|'scheduled'|'done',
   label, detail, url, post (bool — render as a POST form), since (iso, may be '')}
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import production
from ..delivery import delivery_completeness


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute(conn, db, opp, project) -> dict:
    """The one next move for this deal. Pure reads; the ladder mirrors the lifecycle."""
    opp_id = opp["id"]
    status = (opp["status"] or "").strip()
    if status in ("Lost", "Passed"):
        return {"court": "done", "label": "Nothing — this deal is closed",
                "detail": f"Marked {status.lower()}.", "url": "", "post": False, "since": ""}

    # The recorded stage is a FLOOR on this ladder. Every rung below infers where
    # the deal stands from ARTIFACTS — meeting rows, a brief snapshot, a commercial
    # review — which is right when the deal was worked through the system and wrong
    # the moment it was not. A deal marked Won, with a project staffed and in
    # delivery, had no meeting rows, so the ladder offered "Schedule the discovery
    # call" — and the dashboard featured it as the one thing waiting on the operator.
    # Winning is a decision a human recorded; it outranks a missing artifact.
    won = status == "Won" or project is not None

    # ── Discovery ───────────────────────────────────────────────────────────
    now = _now_iso()
    met, upcoming, upcoming_at = False, False, ""
    for m in db.list_meetings(conn, opp_id):
        if m["status"] == "canceled":
            continue
        if m["status"] in ("ingested", "transcript_ready") or (
                (m["start_at"] or "") and m["start_at"] <= now):
            met = True
        elif (m["start_at"] or "") and m["start_at"] > now:
            upcoming, upcoming_at = True, m["start_at"]
    proposals_open = any(p["status"] in ("draft", "sent")
                         for p in db.list_meeting_proposals(conn, opp_id))
    if not met and not won:
        if upcoming:
            return {"court": "scheduled", "label": "Nothing until the discovery call",
                    "detail": "The call is booked; the transcript will land by itself.",
                    "url": "", "post": False, "since": upcoming_at}
        if proposals_open:
            return {"court": "client", "label": "Waiting: client picking a call time",
                    "detail": "Times are offered; the pick books itself.",
                    "url": "", "post": False, "since": ""}
        return {"court": "you", "label": "Schedule the discovery call",
                "detail": "Offer up to three times — the client's pick books everything.",
                "url": f"/opportunity/{opp_id}/schedule", "post": False, "since": ""}

    # ── Summary → confirmation → proposal → approval ────────────────────────
    overrides = db.get_doc_overrides(conn, opp_id)
    confirmed = overrides.get("scope_confirmed") or None
    review = db.current_commercial_review(conn, opp_id)
    approved = bool(review) and review["status"] == "approved"
    if not approved and not won:
        snap = db.latest_brief_snapshot(conn, opp_id)
        if snap is None and not confirmed:
            return {"court": "you", "label": "Send the Discovery Summary",
                    "detail": "One email — “here's what we heard, confirm it's right.”",
                    "url": f"/opportunity/{opp_id}/compose", "post": False, "since": ""}
        # A CORRECTION is our move, not theirs. The client pressing "no, something's off"
        # writes `scope_correction` and emails the operator — and the board went on saying
        # "Waiting: client confirming the summary", so the one surface whose whole job is
        # naming the next move was pointing at the person who had already made it. The ball
        # had changed hands and only the inbox knew.
        correction = overrides.get("scope_correction") or None
        if correction and not correction.get("resolved") and not confirmed:
            note = (correction.get("comment") or "").strip()
            who = (correction.get("by") or "").strip()
            return {"court": "you", "label": "Fix the summary — the client flagged it",
                    "detail": (f"{who or 'They'} said: “{note}”" if note
                               else f"{who or 'They'} say something in it is wrong."),
                    "url": f"/opportunity/{opp_id}/capabilities?edit=1", "post": False,
                    "since": correction.get("at", "")}
        if not confirmed:
            return {"court": "client", "label": "Waiting: client confirming the summary",
                    "detail": "They confirm (or correct) with one click in their workspace.",
                    "url": "", "post": False,
                    "since": snap["created_at"] if snap else ""}
        # A SIGNED proposal is not a proposal waiting to be released (ADR-0065). Reported
        # live: the client signed, and the board still said "Release the proposal" for a
        # proposal she had already accepted — the one surface whose whole job is naming
        # the next move was pointing at a step that had happened. Signing satisfies the
        # release AND the approval, because the summary IS the proposal.
        from .. import signing as _signing
        signed = db.latest_opportunity_signature(conn, opp_id, _signing.DOC_PROPOSAL)
        if signed is not None:
            countersigned = db.latest_opportunity_signature(
                conn, opp_id, _signing.DOC_PROPOSAL_COUNTERSIGN)
            if countersigned is None:
                return {"court": "you", "label": "Countersign the agreement",
                        "detail": (f"{signed['typed_name']} signed it. Countersign to make "
                                   f"it binding on both sides, then start production."),
                        "url": f"/opportunity/{opp_id}#agreement", "post": False,
                        "since": signed["signed_at"] or ""}
            # Countersigned and no project yet — the award happened but nothing was spun
            # up to hold the work. This used to return "Start production" pointing at the
            # page the operator was already on, so the one button on the board did
            # nothing. Production does not start with a button; it starts with a team.
            if project is None:
                return {"court": "you", "label": "Create the project and assign the team",
                        "detail": "Signed by both sides — spin up the project so the work "
                                  "has somewhere to live.",
                        "url": f"/opportunity/{opp_id}/create-project", "post": True,
                        "since": countersigned["signed_at"] or ""}
            # Otherwise fall through to the kickoff ladder below, which already knows the
            # real sequence: assign each role, then the deposit, then Start Production.
        if review is None or review["status"] != "released":
            return {"court": "you", "label": "Release the proposal",
                    "detail": "Scope is confirmed — review the numbers and release.",
                    "url": f"/opportunity/{opp_id}/commercial", "post": False,
                    "since": (confirmed or {}).get("at", "")}
        return {"court": "client", "label": "Waiting: client approving the proposal",
                "detail": "One approval — scope, pricing, timeline, terms — is the award.",
                "url": "", "post": False, "since": review["released_at"] or ""}

    # ── Kickoff → production → invoice ──────────────────────────────────────
    if project is None:
        return {"court": "you", "label": "Create the project",
                "detail": "Approved but no project — the fallback path.",
                "url": f"/opportunity/{opp_id}", "post": False, "since": ""}
    pid = project["id"]
    kick_done = bool(project["kickoff_completed_at"]
                     if "kickoff_completed_at" in project.keys() else None)
    if not kick_done:
        import json as _json
        roles = []
        try:
            roles = list(_json.loads(project["roles"] or "[]"))
        except Exception:  # noqa: BLE001
            pass
        assigned = {a["role"] for a in db.list_assignments(conn, pid)}
        missing = [r for r in roles if r not in assigned]
        if missing:
            return {"court": "you", "label": f"Assign the {missing[0].lower()}",
                    "detail": "One decision — the portal, the scope email and the brief all "
                              "send themselves.",
                    "url": f"/project/{pid}", "post": False, "since": ""}
        # The deposit gates production start — before it lands, the move is the client's
        # (pay the deposit), not the operator's. Once it's in, Start Production unlocks.
        dep = next((i for i in db.list_invoices(conn, pid)
                    if (i["kind"] or "") == "Deposit"), None)
        dep_paid = dep is not None and (dep["status"] or "").lower() in ("paid", "settled")
        if not dep_paid:
            return {"court": "client", "label": "Waiting: client's deposit to start",
                    "detail": "Team's assigned — production begins the moment the deposit clears.",
                    "url": f"/opportunity/{opp_id}", "post": False, "since": ""}
        return {"court": "you", "label": "Start production",
                "detail": "Deposit's in and the team's assigned — open the studio.",
                "url": f"/opportunity/{opp_id}/start-production", "post": True, "since": ""}

    delivery = db.get_delivery(conn, pid)
    court = production.court_state(project, delivery)
    state = (delivery.get("state") or "").strip()
    comp = delivery_completeness(project, delivery)
    roll = db.asset_approval_rollup(delivery)
    # Invoice ONLY once the package has actually shipped. Delivery auto-finalizes to
    # "Delivered" only after every deliverable is uploaded AND signed off by the client
    # (_maybe_finalize_delivery), so "Delivered"/"Released" is the one true "done" signal.
    # A master-only "Approved" — even with every derivative UPLOADED — is not done until
    # the client has signed each one off (see the two branches below).
    if state in ("Delivered", "Released"):
        prop = db.proposal_for_project(conn, pid)
        invoices = db.list_invoices(conn, pid)
        final = next((i for i in invoices if (i["kind"] or "") == "Final"), None)
        if final is None:
            return {"court": "you", "label": "Send the final invoice",
                    "detail": "Delivery is approved — close the loop.",
                    "url": f"/project/{pid}/proposal", "post": False, "since": ""}
        paid = (final["status"] or "").lower() in ("paid", "settled") or (
            "paid_at" in final.keys() and final["paid_at"])
        if not paid:
            return {"court": "client", "label": "Waiting: final invoice payment",
                    "detail": "Full-resolution release unlocks when the balance lands.",
                    "url": f"/project/{pid}/proposal", "post": False,
                    "since": final["created_at"] or ""}
        return {"court": "done", "label": "Nothing — campaign delivered and paid",
                "detail": "The archive and renewal calendar carry it from here.",
                "url": f"/project/{pid}/delivery", "post": False, "since": ""}
    if delivery.get("pending_version"):
        return {"court": "you", "label": "Review & publish the new version",
                "detail": "A submission is waiting at your taste gate.",
                "url": f"/project/{pid}/delivery", "post": False,
                "since": (delivery["pending_version"] or {}).get("at", "")}
    # Master approved (creative locked), but the remaining scoped deliverables are still
    # being produced/uploaded — the next move is FINISHING delivery, not invoicing.
    if production.creative_lock(delivery) and not comp["complete"]:
        return {"court": "team",
                "label": "Waiting: the remaining deliverables",
                "detail": f"Master approved — {comp['text']}. They publish through your taste gate.",
                "url": f"/project/{pid}/delivery", "post": False, "since": ""}
    # Master approved, every deliverable UPLOADED, but the client hasn't signed each off
    # yet — once they all are, delivery auto-finalizes to Delivered and we invoice above.
    if production.creative_lock(delivery) and comp["complete"]:
        signed = f"{roll['approved']} of {roll['total']}" if roll.get("total") else "0"
        return {"court": "client",
                "label": "Waiting: client signing off the deliverables",
                "detail": f"All deliverables uploaded — {signed} signed off. The invoice unlocks when the last one is approved.",
                "url": f"/project/{pid}/delivery", "post": False, "since": ""}
    if court["court"] == "client":
        return {"court": "client", "label": "Waiting: client listening to the version",
                "detail": "They comment or approve in their workspace.",
                "url": "", "post": False, "since": court.get("since", "")}
    return {"court": "team", "label": "Waiting: the studio is composing",
            "detail": "You'll be pinged the moment a version needs your ear.",
            "url": f"/project/{pid}/delivery", "post": False,
            "since": court.get("since", "")}
