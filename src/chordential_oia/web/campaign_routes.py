"""Campaign Home — the Creative OS command view.

ADR-0044, slice 8. Seven routes behind `campaigns.workspace_enabled()`: with the flag
off every one of them answers 404, which is why they can move as a block without
touching any other surface. One contiguous span, no interleaved routes, and a single
helper (`_campaign_view`) used by nothing else.

The campaign is where a won deal becomes work: the creative timeline, the structured
creative direction the composer briefs from, the agency link, and the phase. What the
routes do NOT do is decide — `phase` and `agency` are recorded because a human pressed
the button, and the intelligence endpoints answer or dispose a question rather than
resolving it themselves.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import campaign_intake, campaign_intelligence, campaigns, db
from .shell import render

router = APIRouter(tags=["campaign"])


# --------------------------------------------------------------------------- #
# Campaign Workspace (Creative OS) — the campaign is the workspace root. Flagged
# behind CHORDENTIAL_CAMPAIGN_WORKSPACE (OFF by default); routes 404 when the module
# is disabled, so the existing product is untouched. See docs/campaign-workspace-prd.md.
# --------------------------------------------------------------------------- #
def _campaign_view(conn, campaign_id: int):
    """Assemble the Campaign Home view (or None if not found)."""
    camp = db.get_campaign(conn, campaign_id)
    if camp is None:
        return None
    direction = db.get_campaign_direction(conn, campaign_id)
    sections = [{
        "key": key, "label": label, "hint": hint,
        "body": (direction[key]["body"] if key in direction else ""),
        "complete": bool(direction[key]["complete"]) if key in direction else False,
    } for key, label, hint in campaigns.DIRECTION_SECTIONS]
    # The buyer link (step 1 of the Discovery Intelligence lineage): the campaign now
    # reaches the Agency/Company Intelligence record, not just a client name. Surface
    # whether it's linked and whether intelligence exists to inherit (the next step).
    agency = db.get_agency(conn, camp["agency_id"]) if camp["agency_id"] else None
    agency_has_intel = bool(
        db.get_agency_intel(conn, camp["agency_id"])) if camp["agency_id"] else False
    # Campaign Intelligence — the living canonical record. Lazy-create + seed it (from the
    # opportunity, the linked agency, and the direction cards), then surface it: the
    # provenance panel showing every fact/insight/recommendation/open-question with its
    # kind, sources, and disposition. This is the object every module inherits from.
    ci = campaign_intelligence.ensure_for_campaign(conn, camp)
    ci_view = campaign_intelligence.fields_view(conn, ci["id"])
    return {
        "campaign": camp,
        "phases": campaigns.PHASES,
        "phase_index": campaigns.phase_index(camp["phase"]),
        "next_phase": campaigns.next_phase(camp["phase"]),
        "sections": sections,
        "completeness": campaigns.direction_completeness(direction),
        "agency": agency,
        "agency_has_intel": agency_has_intel,
        "ci": ci,
        "ci_view": ci_view,
    }


@router.get("/campaign/{campaign_id}", response_class=HTMLResponse)
def campaign_home(request: Request, campaign_id: int):
    """Campaign Home — one screen, one campaign: the creative timeline, the structured
    creative direction, and the link into delivery. The Creative OS command view."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        view = _campaign_view(conn, campaign_id)
        if view is None:
            return HTMLResponse("Campaign not found", status_code=404)
    finally:
        conn.close()
    qp = request.query_params
    view["capture_summary"] = ({
        "understood": qp.get("understood"), "added": qp.get("added"),
        "asked": qp.get("asked"),
    } if qp.get("understood") is not None else None)
    return render(request, "campaign_home.html", nav="projects", **view)


@router.post("/campaign/{campaign_id}/direction")
def campaign_set_direction(campaign_id: int, section: str = Form(...),
                           body: str = Form(""), complete: str = Form("")):
    """Edit one structured creative-direction section (the composer's brief)."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    if section not in campaigns.DIRECTION_KEYS:
        return HTMLResponse("Unknown section", status_code=400)
    done = str(complete).strip() in ("1", "true", "on", "yes")
    conn = db.connect()
    try:
        db.update_campaign_direction(conn, campaign_id, section, body=body, complete=done)
        # Contribute the edit back to Campaign Intelligence so the canonical record stays
        # LIVE — the workspace doesn't keep a private copy, it writes through CI (the
        # stated brief is a `fact`; marking it complete disposes it).
        camp = db.get_campaign(conn, campaign_id)
        if camp is not None and body.strip():
            ci = campaign_intelligence.ensure_for_campaign(conn, camp)
            campaign_intelligence.contribute(
                conn, ci["id"], "direction", section, body.strip(),
                kind="fact", source="workspace", contributed_by="operator",
                confirmed=done)
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{campaign_id}#direction", status_code=303)


@router.post("/campaign/{campaign_id}/capture")
def campaign_capture(campaign_id: int, stance: str = Form("objective"),
                     text: str = Form("")):
    """Campaign Intake: the user tells ChordOS what happened (objective) or what's their
    read (Producer Debrief). The pipeline extracts, classifies by kind, and writes to
    Campaign Intelligence — the user never touches the object. Redirects with a summary
    (understood %, added, gaps)."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    text = (text or "").strip()
    if not text:
        return RedirectResponse(f"/campaign/{campaign_id}#capture", status_code=303)
    conn = db.connect()
    try:
        camp = db.get_campaign(conn, campaign_id)
        if camp is None:
            return HTMLResponse("Campaign not found", status_code=404)
        summary = campaign_intake.ingest(conn, camp, stance, text)
    finally:
        conn.close()
    q = summary["questions"]
    return RedirectResponse(
        f"/campaign/{campaign_id}?understood={summary['understanding_pct']}"
        f"&added={summary['added']}&asked={len(q)}#intelligence", status_code=303)


@router.post("/campaign/{campaign_id}/intelligence/answer")
def campaign_ci_answer(campaign_id: int, field_id: str = Form(...), answer: str = Form("")):
    """Answer a follow-up open_question — the conversational gap-fill. The answer becomes
    a confirmed fact on the target field and the question is marked answered."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    answer = (answer or "").strip()
    conn = db.connect()
    try:
        if answer and str(field_id).strip().isdigit():
            row = db.get_ci_field(conn, int(field_id))
            if row is not None:
                campaign_intake.answer_gap(conn, row, answer, created_by="operator")
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{campaign_id}#intelligence", status_code=303)


@router.post("/campaign/{campaign_id}/intelligence/dispose")
def campaign_ci_dispose(campaign_id: int, field_id: str = Form(...)):
    """The human disposition gate on a Campaign Intelligence field — confirm a fact,
    acknowledge an insight, accept a recommendation, answer a question (machine proposes,
    human disposes, §4.1)."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        if str(field_id).strip().isdigit():
            row = db.get_ci_field(conn, int(field_id))
            if row is not None:
                campaign_intelligence.dispose(conn, row, actor="operator")
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{campaign_id}#intelligence", status_code=303)


@router.post("/campaign/{campaign_id}/agency")
def campaign_link_agency(campaign_id: int, action: str = Form("match"),
                         agency_id: str = Form("")):
    """Link the campaign to an Agency Intelligence record — the buyer thread. Three
    actions: 'match' re-runs the name match against the agencies DB (useful once an
    agency has been enriched after the campaign opened); 'set' links a specific
    agency_id; 'unlink' clears it. Best-effort, honest (an exact match or nothing)."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        camp = db.get_campaign(conn, campaign_id)
        if camp is None:
            return HTMLResponse("Campaign not found", status_code=404)
        if action == "unlink":
            db.set_campaign_agency(conn, campaign_id, None)
        elif action == "set" and str(agency_id).strip().isdigit():
            db.set_campaign_agency(conn, campaign_id, int(agency_id))
        else:  # match by the campaign's agency/client name
            m = db.match_agency_by_name(conn, camp["agency_client"] or camp["brand"])
            db.set_campaign_agency(conn, campaign_id, m["id"] if m else None)
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{campaign_id}", status_code=303)


@router.post("/campaign/{campaign_id}/phase")
def campaign_set_phase(campaign_id: int, phase: str = Form(...)):
    """Advance/set the campaign phase — a human-driven transition (the machine only
    proposes the next phase). Rejects a phase outside the creative timeline."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    if phase not in campaigns.PHASES:
        return HTMLResponse("Unknown phase", status_code=400)
    conn = db.connect()
    try:
        db.set_campaign_phase(conn, campaign_id, phase)
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{campaign_id}", status_code=303)
