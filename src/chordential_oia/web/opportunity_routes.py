"""The opportunity surface — the pipeline's own 58 routes.

ADR-0044, slice 5. The largest group in `app.py` and the last one that needed a
prerequisite: until the helper layer moved (slice 4), these routes reached 21 helpers
inside `app.py`. After it, the count of *shared* helpers they still reach is zero — every
one of the twelve below is used by this group and nothing else, so it travels with it.

Like the discovery slice and unlike `/agencies`, these are not one contiguous block:
31 unrelated routes sit inside their span (the client workspace, the creator portal,
the Match Board, the buyer pages, `/uploads`). So the extraction is per route, in source
order, rather than one cut — which is why the relative order of what remains in `app.py`
is undisturbed.
"""

from __future__ import annotations

import hmac
import json
import os
import re
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from .. import mailer, signing
from ..capabilities import (
    DELIVERY_TEMPLATES, SECTION_FAMILY, attach_agreement, build_capabilities_doc,
    build_understanding,
    chips_for, default_toggles, doc_from_json, doc_to_json,
    quote_band as capabilities_quote_band, quote_for as capabilities_quote_for,
)
from ..matching import match_talent
from ..models import BuyerValue, Opportunity
from ..outreach import (
    COMPOSE_BLOCK_KEYS, assemble_email, build_compose_blocks, build_outreach_plan,
    compose_selection, respond_action, _mailto,
)
from ..prepare import build_pursuit_brief
from ..proposals import build_proposal
from ..storage import get_object_store
from ..strategic import assess_strategic_value
from . import (
    actor, campaign_intake, campaign_intelligence, campaigns, commercial, db,
    intake_lanes, meeting_scheduler, next_action, procurement, producer_learning, signals,
)
from .estimate import estimate_for
from .evaluate import evaluate
from .filters import slug
from .opportunity_ops import (
    _KANBAN_STAGES, _brief_ci_context, _buyer_context, _ensure_project_for_opp,
    _estimate_for_row, _load, agreement_doc_for,
    _quote_band_for, _reconcile_opp_status, _to_utc_iso,
)
from .shell import public_base as _public_base, render, safe_local as _safe_local
from .talent_routes import _parse_rate
from .uploads import _AUDIO_EXTS, _persist_upload, upload_dir

router = APIRouter(tags=["opportunity"])


# --------------------------------------------------------------------------- #
# Jinja helpers (filter functions live in .filters — shared with the public site)
# --------------------------------------------------------------------------- #
# One-click pipeline advance for the Overview action bar. Won is intentionally
# omitted — closing a deal goes through the win/loss form so the value is captured.
_NEXT_STATUS = {"New": "Pursuing", "Pursuing": "Submitted"}


# Stepper "expected next step" (Phase 5, ruling #7). Extends the linear flow all the
# way to Won — kept separate from _NEXT_STATUS so the action-bar's "close via the
# win/loss form" behaviour is undisturbed. New → Reaching out → Proposal out → Won.
_STEPPER_NEXT = {"New": "Pursuing", "Pursuing": "Submitted", "Submitted": "Won"}


@router.post("/opportunity/{opp_id}/delete")
def opportunity_delete(opp_id: int, return_to: str = Form("/inbox")):
    """Permanently delete an opportunity and everything anchored to it — the whole account
    (CI, meetings, procurement, project + delivery, commercial, learning). Built for clearing
    demo accounts. Irreversible; the UI double-confirms before POSTing here."""
    conn = db.connect()
    try:
        summary = db.delete_opportunity(conn, opp_id)
    finally:
        conn.close()
    dest = return_to if (return_to or "").startswith("/") else "/inbox"
    if summary.get("deleted"):
        dest += ("&" if "?" in dest else "?") + "deleted=" + quote(summary.get("client", ""))
    return RedirectResponse(dest, status_code=303)


# NOTE: declared BEFORE /opportunity/{opp_id}. FastAPI matches in declaration
# order, and a literal path competing with a typed parameter loses if it comes
# second: "new" is not an int, so /opportunity/new answered 422 rather than the
# form. Static segments go above their parameterised sibling.
@router.get("/opportunity/new", response_class=HTMLResponse)
def opportunity_new_form(request: Request):
    """Add a deal by hand.

    Until this existed there was NO way to create an opportunity directly. Every one had
    to arrive as an inbound lead and then be promoted — correct for something that came
    through the front door, and pure friction for a referral, a phone call, or a test run:
    two pages and four steps to type in a name. Reported live, by an operator who assumed
    the deal he was told about already existed."""
    return render(request, "opportunity_new.html", nav="inbox")


@router.post("/opportunity/new")
def opportunity_new_create(client: str = Form(""), need: str = Form(""),
                           description: str = Form(""), contact_name: str = Form(""),
                           contact_email: str = Form("")):
    """Create it and go straight to it. Client and need are the only required fields —
    everything else the pipeline is built to discover, and demanding it here would just
    invite guesses at the moment you know least."""
    client, need = client.strip(), need.strip()
    if not client or not need:
        return RedirectResponse("/opportunity/new?err=missing", status_code=303)
    conn = db.connect()
    try:
        opp = Opportunity(client=client, need=need, description=description.strip(),
                          source="manual")
        new_id = db.insert_opportunity(conn, opp)
        if not new_id:
            return RedirectResponse("/opportunity/new?err=failed", status_code=303)
        if contact_name.strip() or contact_email.strip():
            db.update_outreach(conn, new_id, contact_name=contact_name.strip(),
                               contact_email=contact_email.strip())
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{new_id}", status_code=303)


@router.get("/opportunity/{opp_id}", response_class=HTMLResponse)
def opportunity_detail(request: Request, opp_id: int, understood: str = "",
                       added: str = "", asked: str = "", fetch: str = ""):
    conn = db.connect()
    ci = ci_view = None
    intake_sync_lanes = None
    meeting = None
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        buyer_rows = db.buyer_opportunities(conn, row["client"])
        project = db.project_for_opp(conn, opp_id)
        # Campaign Intake lives HERE now (ADR-0013): born on and anchored to the
        # opportunity. Lazily create + seed its CI, then render the provenance view.
        # The intake lanes (ADR-0014) come from the ONE registry — no lane is privileged.
        if campaigns.workspace_enabled():
            ci = campaign_intelligence.ensure_for_opportunity(conn, row)
            ci_view = campaign_intelligence.fields_view(conn, ci["id"])
            intake_sync_lanes = intake_lanes.sync_lanes()
        # Discovery lives in the Campaign Brief now; the opp page shows a meeting only
        # CONTEXTUALLY (the "Upcoming Discovery" panel), never a standing widget.
        meeting = db.meeting_for_opp(conn, opp_id)
        # Pending client Discovery Requests to review + schedule (ADR-0016).
        discovery_requests = db.list_discovery_requests(conn, opp_id, status="new")
        # ADR-0020 §6: the ONE obvious next move for this deal.
        # Keep the pipeline stage honest with reality before we read it (self-heal).
        _reconcile_opp_status(conn, opp_id, project)
        row = db.get_opportunity(conn, opp_id)
        next_act = next_action.compute(conn, db, row, project)
        # Kickoff → Production gate: a project created by client approval sits in Kickoff
        # until the operator confirms Start Production (ADR-0018, Phase 4).
        kickoff_pending = (
            project is not None
            and (project["kickoff_completed_at"] if "kickoff_completed_at" in project.keys()
                 else None) is None
            and db.current_commercial_review(conn, opp_id) is not None
            and db.current_commercial_review(conn, opp_id)["status"] == "approved")
        # The deposit gates Start Production — surfaced so the button reads honestly
        # (offer it only once the deposit has cleared).
        deposit_paid = False
        if project is not None:
            _d = next((i for i in db.list_invoices(conn, project["id"])
                       if (i["kind"] or "") == "Deposit"), None)
            deposit_paid = _d is not None and (_d["status"] or "").lower() in ("paid", "settled")
        # Open Meeting Proposals — times offered, awaiting the client's pick (or unsent drafts).
        open_proposals = [p for p in db.list_meeting_proposals(conn, opp_id)
                          if p["status"] in ("draft", "sent")]
        proposal_slots_et = {
            p["id"]: [meeting_scheduler.fmt_et(s)
                      for s in meeting_scheduler.proposal_slots(p)]
            for p in open_proposals}
        # The price, and the verdict on what the client said they had (ADR-0065). The
        # verdict is the half the operator cannot get anywhere else: a budget below our
        # floor used to become the quote silently, and now it becomes a sentence naming
        # both numbers so the decision — reduce the scope, or decline — is a human's.
        _ci_fields = (ci_view or {}).get("fields") or {}
        quote = capabilities_quote_for(
            opp, _estimate_for_row(conn, row, opp, ev[0]), ci_fields=_ci_fields,
            commercial_overrides=db.get_doc_overrides(conn, opp_id).get("commercial"))
        # The signature, on the page where the operator actually works. It was only on
        # the Campaign Brief, so a signed deal looked unsigned on its own detail page and
        # the board went on saying "release the proposal" for a proposal already accepted.
        proposal_signature = db.latest_opportunity_signature(
            conn, opp_id, signing.DOC_PROPOSAL)
        countersignature = db.latest_opportunity_signature(
            conn, opp_id, signing.DOC_PROPOSAL_COUNTERSIGN)
        sig_state = signing.UNKNOWN
        agreement_text = ""
        if proposal_signature is not None:
            _r2, _o2, _e2, _sdoc, _sdep = agreement_doc_for(conn, opp_id)
            _agr = getattr(_sdoc, "agreement", None)
            agreement_text = _agr.signable_text() if _agr is not None else ""
            sig_state = signing.verify(proposal_signature["digest"], agreement_text)
    finally:
        conn.close()
    qual, scored = ev
    sv = assess_strategic_value(opp)
    capture_summary = None
    if understood.isdigit():
        capture_summary = {"understood": int(understood),
                           "added": int(added) if added.isdigit() else 0,
                           "asked": int(asked) if asked.isdigit() else 0}
    # Guided-not-gated stepper: the expected next stage along the working flow
    # (New → Reaching out → Proposal out → Won). Computed separately from the
    # action-bar's _NEXT_STATUS so adding Submitted→Won here doesn't change the
    # Won-via-win/loss-form behaviour elsewhere.
    stepper_next = _STEPPER_NEXT.get(row["status"])
    return render(
        request, "detail.html", fetch_msg=fetch, nav="inbox", row=row, opp=opp, qual=qual, scored=scored,
        sv=sv, buyer_count=len(buyer_rows), buyer_values=list(BuyerValue),
        project_id=(project["id"] if project else None),
        next_status=_NEXT_STATUS.get(row["status"]),
        stepper_next=stepper_next, stepper_stages=_KANBAN_STAGES,
        ci=ci, ci_view=ci_view, intake_sync_lanes=intake_sync_lanes,
        meeting=meeting, notetaker_ready=intake_lanes.get_lane("discovery_call").is_available(),
        # Where this call's confirmations actually went, and what the mailer said. Reported
        # because "I never got a calendar block" has several causes that look identical from
        # the outside — no mail provider, no operator address, a send that errored, or an
        # invitation that arrived and the calendar declined to add.
        confirmations=(db.confirmations(meeting) if meeting is not None else []),
        discovery_requests=discovery_requests, open_proposals=open_proposals,
        proposal_slots_et=proposal_slots_et, capture_summary=capture_summary,
        kickoff_pending=kickoff_pending, deposit_paid=deposit_paid, next_act=next_act,
        quote=quote, proposal_signature=proposal_signature,
        countersignature=countersignature, agreement_text=agreement_text,
        signature_state=sig_state,
        signature_note=signing.verdict_note(
            sig_state, dict(proposal_signature) if proposal_signature is not None else None),
        signature_valid=(sig_state == signing.VALID),
        ai_spend=_ai_spend_status(),
    )


def _delivery_readiness(status: dict) -> dict:
    """Add the two settings that decide whether an invitation reaches the OPERATOR.

    The seam status answers "is Google connected", which is not the question that was
    failing. A calendar invitation rides the confirmation email, so an unsent email is an
    unbooked calendar — and both of the ways that happens are silent: the mailer is a no-op
    until its provider is set, and `_operator_email` falls back to the app's own sending
    address when CHORDENTIAL_OPERATOR_EMAIL is unset, which makes an unconfigured inbox
    look configured. Reported here rather than in `meetings/` because the mail seam and the
    operator address are the web layer's business; `meetings/` must not import upward."""
    from .. import mailer as _mailer
    from . import meeting_scheduler as _ms
    out = dict(status or {})
    out["mail"] = _mailer.mail_configured()
    out["operator_email"] = _ms._operator_email()
    out["operator_email_guessed"] = _ms.operator_email_is_a_guess()
    return out


def _ai_spend_status() -> dict:
    """The AI spend meter for the Analyze panel: whether a click spends API credit, this
    month's estimated spend, the cap, and whether the cap has bitten. Surfaced so cost is
    never a surprise (reported live: a silent per-analyze charge drained the operator)."""
    try:
        from . import extraction_bridge
        conn = db.connect()
        try:
            return extraction_bridge.spend_status(conn)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return {"spent": 0.0, "cap": 0.0, "calls": 0, "over": False, "enabled": False}


# --------------------------------------------------------------------------- #
# Campaign Intake on the Opportunity (ADR-0013) — Update Intelligence + edits.
# --------------------------------------------------------------------------- #
@router.post("/opportunity/{opp_id}/intelligence/analyze")
async def opp_intelligence_analyze(
        opp_id: int, stance: str = Form("objective"), modality: str = Form("notes"),
        lane: str = Form(""), text: str = Form(""),
        file: Optional[UploadFile] = File(None)):
    """The ONE place a paid model run is asked for by a person.

    The button shows the cost and confirms before it posts, so this scope — and only
    this scope — is marked as approved spend. Everything outside it (every scheduler
    tick, every background thread, every webhook) cannot reach the API at all and uses
    the free deterministic pass instead. See web/ai_budget.py for why that is the rule
    rather than a cap."""
    from . import ai_budget
    with ai_budget.approved_by("operator"):
        return await _analyze_with_approval(opp_id, stance, modality, lane, text, file)


async def _analyze_with_approval(opp_id, stance, modality, lane, text, file):
    """Update Intelligence: read ONLY the newly submitted capture, merge it into this
    opportunity's Campaign Intelligence (preserving provenance + the raw-evidence capture,
    never clobbering a human edit — disagreements surface as conflicts), raise follow-up
    questions, and reflect mappable facts back onto the opportunity. The intake LANE
    (ADR-0014) resolves from an explicit key or from stance+modality. Text lanes read
    directly; a binary upload is stored as evidence and marked awaiting transcription."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    text = (text or "").strip()
    the_lane = intake_lanes.resolve_lane(lane_key=lane, stance=stance, modality=modality)
    artifact_ref = upload_name = ""
    artifact_bytes = None
    if file is not None and (file.filename or "").strip():
        ext = os.path.splitext(file.filename)[1].lower()
        safe = f"intake_{opp_id}_{abs(hash(file.filename)) % 10**8}{ext}"
        try:
            # ADR-0043: read here (the text extraction below needs the bytes) but
            # persist through the store once the connection is open — this route
            # used to write straight into upload_dir(), so a voice memo or an RFP had
            # exactly one copy on the disk the cutover removes.
            artifact_bytes = await file.read()
            upload_name, artifact_ref = file.filename, safe
            # a text-like upload (transcript/rfp/email exported as .txt) can be read now
            if not text and ext in (".txt", ".md", ".vtt", ".srt"):
                text = artifact_bytes.decode("utf-8", "ignore").strip()
        except (OSError, ValueError):
            artifact_ref = upload_name = ""
    conn = db.connect()
    if artifact_ref and artifact_bytes is not None:
        _persist_upload(conn, artifact_ref, artifact_bytes)
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        if not text:
            # No readable text (e.g. a voice memo with no transcription seam configured):
            # store the raw evidence honestly — nothing is extracted or invented.
            ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
            db.insert_capture(
                conn, ci_id=ci_row["id"], opp_id=opp_id, lane=the_lane.key,
                stance=the_lane.stance, modality=the_lane.modality,
                provenance_source=the_lane.provenance_source, artifact_ref=artifact_ref,
                raw_text=(f"[{the_lane.label}: {upload_name or 'no text'}, "
                          f"awaiting transcription]"),
                extraction=[], status="received", created_by="operator")
            return RedirectResponse(
                f"/opportunity/{opp_id}?understood=&added=0&asked=0#intelligence",
                status_code=303)
        summary = campaign_intake.ingest_opportunity(
            conn, row, stance, text, lane_key=the_lane.key, artifact_ref=artifact_ref)
    finally:
        conn.close()
    q = summary["questions"]
    return RedirectResponse(
        f"/opportunity/{opp_id}?understood={summary['understanding_pct']}"
        f"&added={summary['added']}&asked={len(q)}#intelligence", status_code=303)


@router.post("/opportunity/{opp_id}/intelligence/field")
def opp_intelligence_field(opp_id: int, value: str = Form(""), field_id: str = Form(""),
                           facet: str = Form(""), key: str = Form(""),
                           kind: str = Form("fact"), label: str = Form("")):
    """Human edit of a CI field — authoritative (ADR-0013). Edits an existing field by id,
    fills an empty canonical slot by (facet,key,kind), or CREATES a field nobody defined.

    The canonical ten are the fields every campaign has. They were never meant to be the
    only fields a campaign can have — a check-in cadence, a legal lead time, a stakeholder
    nobody has a slot for. Storage and the view already carried arbitrary facts; there was
    simply no way for a person to make one. A typed label becomes the key."""
    if label.strip() and not key.strip():
        key = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")[:48]
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    value = (value or "").strip()
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
        if not value:
            pass
        elif str(field_id).strip().isdigit():
            old = db.get_ci_field(conn, int(field_id))
            campaign_intelligence.edit_field(conn, int(field_id), value, actor="operator")
            if old is not None:
                # ADR-0021: the operator edited a proposed value — training data. A
                # consistent enrichment in a facet teaches the extractor to propose richer.
                producer_learning.record_event(
                    conn, ci_id=ci_row["id"], opp_id=opp_id, facet=old["facet"],
                    key=old["key"], kind=old["kind"], action="edited",
                    ai_value=old["value"] or "", final_value=value,
                    confidence_before=old["confidence"], capture_id=old["capture_id"])
        elif facet and key:
            campaign_intelligence.edit_or_create(conn, ci_row["id"], facet, key,
                                                 kind or "fact", value, actor="operator")
            # The operator supplied a field the AI never proposed — the missed-concept signal.
            producer_learning.record_event(
                conn, ci_id=ci_row["id"], opp_id=opp_id, facet=facet, key=key,
                kind=kind or "fact", action="added", ai_value="", final_value=value)
        campaign_intake.sync_ci_to_opportunity(conn, ci_row["id"], opp_id)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#intelligence", status_code=303)


@router.post("/opportunity/{opp_id}/intelligence/answer")
def opp_intelligence_answer(opp_id: int, field_id: str = Form(...), answer: str = Form("")):
    """Answer an open question → a confirmed FACT, and close the question.

    "Mark answered" used to mean only "stop showing me this": it closed the question and
    kept nothing, so a discovery call's answer evaporated at the moment someone actually
    knew it. Answered now means answered — the text lands in Campaign Intelligence as a
    confirmed fact, which is what the Campaign Brief, the estimate and the proposal read,
    and the question drops off the client-facing list because it genuinely has an answer."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    answer = (answer or "").strip()
    conn = db.connect()
    try:
        if answer and str(field_id).strip().isdigit():
            fld = db.get_ci_field(conn, int(field_id))
            if fld is not None:
                campaign_intake.answer_gap(conn, fld, answer, created_by="operator")
                # Answering a follow-up fills a field the AI flagged as unknown — the operator
                # supplying the value is an "added" event on the target field (ADR-0021).
                target_key = (fld["key"] or "")[4:] if (fld["key"] or "").startswith("ask_") \
                    else (fld["key"] or "")
                producer_learning.record_event(
                    conn, ci_id=fld["ci_id"], opp_id=opp_id, facet=fld["facet"],
                    key=target_key, action="added", ai_value="", final_value=answer,
                    capture_id=fld["capture_id"])
                campaign_intake.sync_ci_to_opportunity(conn, fld["ci_id"], opp_id)
    finally:
        conn.close()
    anchor = f"ci-{field_id}" if str(field_id).strip().isdigit() else "intelligence"
    return RedirectResponse(f"/opportunity/{opp_id}#{anchor}", status_code=303)


@router.post("/opportunity/{opp_id}/intelligence/dispose")
def opp_intelligence_dispose(opp_id: int, field_id: str = Form(...)):
    """The human disposition gate — confirm / acknowledge / accept / mark-answered.

    Returns to the ITEM, not to the top of the section. `#intelligence` sent the page back
    to the section heading, which on a long producer's read is a screen or more above the
    line you just pressed — so disposing of ten items in a row meant scrolling back down
    ten times, and losing your place each time."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        if str(field_id).strip().isdigit():
            fld = db.get_ci_field(conn, int(field_id))
            if fld is not None:
                campaign_intelligence.dispose(conn, fld, actor="operator")
                # ADR-0021: confirming a proposal verbatim is the strongest "trust" signal.
                producer_learning.record_event(
                    conn, ci_id=fld["ci_id"], opp_id=opp_id, facet=fld["facet"],
                    key=fld["key"], kind=fld["kind"], action="confirmed",
                    ai_value=fld["value"] or "", final_value=fld["value"] or "",
                    confidence_before=fld["confidence"], capture_id=fld["capture_id"])
                campaign_intake.sync_ci_to_opportunity(conn, fld["ci_id"], opp_id)
    finally:
        conn.close()
    anchor = f"ci-{field_id}" if str(field_id).strip().isdigit() else "intelligence"
    return RedirectResponse(f"/opportunity/{opp_id}#{anchor}", status_code=303)


@router.post("/opportunity/{opp_id}/intelligence/conflict")
def opp_intelligence_conflict(opp_id: int, field_id: str = Form(...),
                              decision: str = Form("keep")):
    """Resolve a surfaced conflict: accept the machine's proposed value, or keep your own."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        if str(field_id).strip().isdigit():
            fld = db.get_ci_field(conn, int(field_id))
            if fld is not None:
                accept = (decision == "accept")
                campaign_intelligence.resolve_conflict(
                    conn, int(field_id), accept=accept, actor="operator")
                # ADR-0021: accepting the machine's disputed value = confirmed; keeping your
                # own = the machine value was rejected. Both train the prior.
                producer_learning.record_event(
                    conn, ci_id=fld["ci_id"], opp_id=opp_id, facet=fld["facet"],
                    key=fld["key"], kind=fld["kind"],
                    action=("confirmed" if accept else "rejected"),
                    ai_value=fld["proposed_value"] or "",
                    final_value=(fld["proposed_value"] or "") if accept else (fld["value"] or ""),
                    confidence_before=fld["confidence"], capture_id=fld["capture_id"])
                campaign_intake.sync_ci_to_opportunity(conn, fld["ci_id"], opp_id)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#intelligence", status_code=303)


# --------------------------------------------------------------------------- #
# Procurement Intelligence (ADR-0022) — capture → adapt → generate → onboard → learn.
# ChordOS prepares clients for procurement; it never integrates with their systems.
# --------------------------------------------------------------------------- #
@router.get("/opportunity/{opp_id}/procurement", response_class=HTMLResponse)
def procurement_workspace(request: Request, opp_id: int):
    """The Procurement Workspace: an adaptive checklist assembled from what THIS client
    actually requires (discovered from Campaign Intelligence), the document generation engine,
    readiness, the portal-onboarding action, and the audit timeline."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        # Discover on load (idempotent) + pre-load from this client's history the first time.
        procurement.seed_from_history(conn, opp_id)
        procurement.discover_from_ci(conn, opp_id)
        view = {
            "row": row, "opp_id": opp_id,
            "readiness": procurement.readiness(conn, opp_id),
            "checklist": procurement.checklist(conn, opp_id),
            "portal": procurement.portal_action(conn, opp_id),
            "timeline": procurement.timeline(conn, opp_id),
            "profile": db.get_company_profile(conn),
            "profile_complete": bool((db.get_company_profile(conn) or {}).get("legal_name")),
            "vocab": procurement.VOCAB, "statuses": procurement.STATUSES,
            "status_label": procurement.STATUS_LABEL,
        }
    finally:
        conn.close()
    return render(request, "procurement.html", nav="pipeline", **view)


@router.post("/opportunity/{opp_id}/procurement/add")
def procurement_add(opp_id: int, req_key: str = Form(...)):
    """Add a requirement the machine didn't discover — from the known vocabulary."""
    conn = db.connect()
    try:
        if req_key in procurement.VOCAB:
            procurement.upsert_requirement(conn, opp_id, req_key, source="Operator",
                                           evidence="Added by the operator")
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/procurement", status_code=303)


@router.post("/opportunity/{opp_id}/procurement/{rid}/generate")
def procurement_generate(opp_id: int, rid: int):
    """Generate the artifact from the Company Profile (or a professional placeholder)."""
    conn = db.connect()
    try:
        r = db.get_procurement_requirement_by_id(conn, rid)
        if r is not None and r["opp_id"] == opp_id:
            procurement.generate_document(conn, opp_id, r["req_key"])
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/procurement", status_code=303)


@router.post("/opportunity/{opp_id}/procurement/{rid}/status")
def procurement_status(opp_id: int, rid: int, status: str = Form(...)):
    """Advance a requirement — Mark Complete / uploaded / not-required, tracked in the audit."""
    conn = db.connect()
    try:
        r = db.get_procurement_requirement_by_id(conn, rid)
        if r is not None and r["opp_id"] == opp_id and status in procurement.STATUSES:
            db.update_procurement_requirement(conn, rid, status=status)
            procurement.add_event(conn, opp_id, status,
                                  f"{r['label']} → {procurement.STATUS_LABEL.get(status, status)}")
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/procurement", status_code=303)


@router.post("/opportunity/{opp_id}/procurement/{rid}/upload")
async def procurement_upload(opp_id: int, rid: int, file: UploadFile = File(...)):
    """Upload a client-supplied or externally-signed document against a requirement."""
    conn = db.connect()
    try:
        r = db.get_procurement_requirement_by_id(conn, rid)
        if r is not None and r["opp_id"] == opp_id and (file.filename or "").strip():
            ext = os.path.splitext(file.filename)[1].lower()
            safe = f"procurement_{opp_id}_{r['req_key']}{ext}"
            try:
                data = await file.read()
                # ADR-0043: a procurement document is a compliance artefact — a W-9,
                # a COI, a signed vendor form. It used to be written straight to disk
                # with no second copy.
                _persist_upload(conn, safe, data)
                db.update_procurement_requirement(conn, rid, artifact_ref=f"upload/{safe}",
                                                  status="uploaded")
                procurement.add_event(conn, opp_id, "uploaded", f"Uploaded {r['label']}")
            except OSError:
                pass
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/procurement", status_code=303)


@router.get("/opportunity/{opp_id}/procurement/{rid}/view", response_class=PlainTextResponse)
def procurement_view(opp_id: int, rid: int):
    """View the generated artifact text (a Download, not a page — the PDF is a rendering)."""
    conn = db.connect()
    try:
        r = db.get_procurement_requirement_by_id(conn, rid)
        text = (r["artifact_text"] if r is not None and r["opp_id"] == opp_id else "") or ""
    finally:
        conn.close()
    if not text:
        return PlainTextResponse("Not generated yet.", status_code=404)
    return PlainTextResponse(text)


@router.post("/opportunity/{opp_id}/procurement/complete")
def procurement_complete(opp_id: int):
    """Mark the whole procurement process complete — and LEARN from it for this client."""
    conn = db.connect()
    try:
        procurement.complete_and_learn(conn, opp_id)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/procurement", status_code=303)


@router.get("/opportunity/{opp_id}/evidence", response_class=HTMLResponse)
def opportunity_evidence(request: Request, opp_id: int):
    """The raw evidence behind Campaign Intelligence — every Capture (transcripts, notes, …)
    with its full text next to what the pipeline extracted from it. Raw evidence is permanent
    and reviewable (ADR-0014): this is where you check whether a missing fact is a transcript
    gap (the words weren't captured) or an extraction gap (they were, but not pulled out)."""
    conn = db.connect()
    items = []
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        ci = db.ci_for_opportunity(conn, opp_id)
        for c in (db.list_captures(conn, ci["id"]) if ci else []):
            try:
                meta = json.loads(c["metadata_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            try:
                extraction = json.loads(c["extraction_json"] or "[]")
            except (json.JSONDecodeError, TypeError):
                extraction = []
            run = meta.get("extraction_run")
            items.append({"c": c, "meta": meta, "extraction": extraction, "run": run,
                          "remedy": _extraction_error_remedy(
                              (run or {}).get("provider_error", ""))})
    finally:
        conn.close()
    from ..extraction import providers as _ext_providers
    return render(request, "evidence.html", nav="inbox", row=row, items=items,
                  engine_enabled=_ext_providers.is_enabled())


def _extraction_error_remedy(err: str) -> str:
    """Map a model-call error to the precise, actionable remedy so the operator isn't sent
    chasing the wrong knob (a billing error is not a model error)."""
    low = (err or "").lower()
    if not low:
        return ""
    if "credit" in low or "billing" in low or "quota" in low or "insufficient" in low:
        return ("The Anthropic API key has no API credit. Note: a Claude Max/Pro plan "
                "(claude.ai) is SEPARATE from API billing and does NOT fund the API — buy "
                "prepaid API credits at console.anthropic.com → Billing (a few dollars is "
                "plenty; each extraction costs cents), and confirm the key belongs to that "
                "same workspace and its spend limit isn't $0. No redeploy — just re-analyze.")
    if "not_found" in low or "not found" in low or "model" in low and "404" in low:
        return ("That model id isn't available to your key — set "
                "CHORDENTIAL_EXTRACTION_MODEL to one it can call, then re-analyze.")
    if "authentication" in low or "401" in low or "api key" in low or "unauthorized" in low:
        return ("The API key was rejected — check ANTHROPIC_API_KEY in the environment, "
                "then re-analyze.")
    if "rate" in low or "429" in low or "overloaded" in low or "529" in low:
        return "The API was rate-limited/overloaded — transient; just re-analyze in a moment."
    return "Re-analyze once the model call above can succeed."


@router.post("/opportunity/{opp_id}/identity")
def opp_identity(opp_id: int, need: str = Form(""), client: str = Form("")):
    """Edit the opportunity's title (need) and/or buyer name (client) — the human-corrected
    values are authoritative and re-evaluate the opportunity (ADR-0013)."""
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        need, client = (need or "").strip(), (client or "").strip()
        db.apply_intelligence_to_opportunity(
            conn, opp_id, need=need or None, client=client or None)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


@router.post("/opportunity/{opp_id}/discovery/reschedule")
def discovery_reschedule(opp_id: int, start_at: str = Form(""), tz_offset: str = Form(""),
                         duration_min: int = Form(0)):
    """Reschedule the opportunity's current discovery call to a new time (local → UTC via
    tz_offset) through the shared engine, so the calendar event moves and confirmations resend."""
    conn = db.connect()
    try:
        m = db.meeting_for_opp(conn, opp_id)
        new_start = _to_utc_iso(start_at, tz_offset)
        if m is not None and new_start:
            meeting_scheduler.reschedule(conn, m, new_start, duration_min=duration_min or None)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#discovery", status_code=303)


@router.post("/opportunity/{opp_id}/capture/{capture_id}/reanalyze")
async def opp_capture_reanalyze(opp_id: int, capture_id: int):
    """Read a capture we already hold, again — with the engine this time.

    The console has told operators to "just re-analyze" whenever the engine could not run
    (no credit, a rejected key, a rate limit) since that message was written, and there
    was no way to. Pasting the text again would have made a SECOND capture of the same
    call. This re-reads the evidence on file.

    A human pressed it, so the scope is approved spend (web/ai_budget.py)."""
    from . import ai_budget, campaign_intake
    conn = db.connect()
    try:
        with ai_budget.approved_by("operator"):
            out = campaign_intake.reanalyze_capture(conn, capture_id)
    except Exception as e:      # noqa: BLE001 — a press never ends in a 500
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()
    if out.get("ok"):
        msg = ("Re-read with the engine — %d fact%s." % (
            out.get("added", 0), "" if out.get("added") == 1 else "s")
            if out.get("engine") else
            "Re-read, but the engine still could not run — keyword baseline again.")
    else:
        msg = out.get("error") or "Could not re-analyze."
    from urllib.parse import quote
    return RedirectResponse(f"/opportunity/{opp_id}?fetch={quote(msg[:300])}",
                            status_code=303)


@router.post("/opportunity/{opp_id}/discovery/{meeting_id}/fetch-transcript")
def discovery_fetch_transcript(opp_id: int, meeting_id: int):
    """Fetch this call's transcript NOW, rather than waiting on the background poller.

    Until this existed, the only route from a recorded call to Campaign Intelligence was
    a loop in the scheduler — invisible, uncheckable, and after ~8 hours it gave up for
    good. A discovery call's notes are too valuable to sit behind a background job the
    operator has no handle on."""
    from urllib.parse import quote

    from . import meetings_service
    try:
        msg = meetings_service.start_fetch(meeting_id)
    except Exception as e:      # noqa: BLE001 — a button press never ends in a 500
        msg = f"Could not start the fetch: {type(e).__name__}: {e}"
    return RedirectResponse(
        f"/opportunity/{opp_id}?fetch={quote(msg[:300])}#discovery", status_code=303)


@router.post("/opportunity/{opp_id}/discovery/{meeting_id}/cancel")
def discovery_cancel(opp_id: int, meeting_id: int):
    """Cancel a scheduled discovery call (drops the calendar event; the record is retained)."""
    conn = db.connect()
    try:
        m = db.get_meeting(conn, meeting_id)
        if m is not None and m["opp_id"] == opp_id:
            meeting_scheduler.cancel(conn, m)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


# ── Client Discovery REQUEST (ADR-0016) — the client asks; it schedules nothing. ──────
def _request_token_ok(conn, opp_id: int, k: str):
    row = db.get_opportunity(conn, opp_id)
    token = row["share_token"] if row is not None and "share_token" in row.keys() else None
    if row is None or not token or not k or not hmac.compare_digest(str(k), str(token)):
        return None
    return row


@router.get("/opportunity/{opp_id}/request", response_class=HTMLResponse)
def discovery_request_form(request: Request, opp_id: int, k: str = "", done: str = ""):
    """The client-facing Request-a-Discovery-Call form (token-gated, from the Brief)."""
    conn = db.connect()
    try:
        row = _request_token_ok(conn, opp_id, k)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
    finally:
        conn.close()
    return render(request, "discovery_request.html", nav="", row=row, k=k,
                  done=bool(done), prefill_email=(row["contact_email"] or ""),
                  prefill_name=(row["contact_name"] or ""))


@router.post("/opportunity/{opp_id}/request")
def discovery_request_submit(opp_id: int, k: str = Form(""), name: str = Form(""),
                             email: str = Form(""), company: str = Form(""),
                             preferred_type: str = Form("zoom"), message: str = Form("")):
    """Create a Discovery Request attached to the opportunity + notify the operator. Schedules
    nothing (ADR-0016)."""
    conn = db.connect()
    try:
        row = _request_token_ok(conn, opp_id, k)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        rid = db.create_discovery_request(
            conn, opp_id=opp_id, name=name.strip(), email=email.strip(),
            company=company.strip(), preferred_type=preferred_type, message=message.strip())
        meeting_scheduler.notify_new_request(db.get_discovery_request(conn, rid), row)
    finally:
        conn.close()
    # Automated acknowledgment to the client (best-effort, off-thread; no-op until
    # SMTP is configured) — same confirmation every inbound intake sends.
    signals.fire_and_forget(mailer.send_intake_ack, email.strip(), name.strip())
    return RedirectResponse(f"/opportunity/{opp_id}/request?k={k}&done=1", status_code=303)


# ── Operator SCHEDULING (ADR-0016) — one engine, from a request or manually. ──────────
@router.get("/opportunity/{opp_id}/prep", response_class=HTMLResponse)
def discovery_prep_sheet(request: Request, opp_id: int):
    """The call prep sheet (Phase 0 of docs/discovery-copilot-plan.md).

    Every question worth asking on a discovery call, with what Campaign Intelligence
    already holds beside it. Printable, no model call, no spend — the machine's whole
    contribution used to arrive after everyone hung up, as a list of things it was by then
    too late to ask. This is the same knowledge, delivered while it can still be used.

    A slot we already hold becomes a READ-BACK rather than disappearing: a value captured
    confidently and wrongly is the failure this product keeps having, and the only cheap
    moment to catch it is while the person who knows is still on the line."""
    from ..call_prep import coverage, prep_sheet
    from ..pricing import licence_from_ci, price_guide
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        fields = {}
        ci_row = db.ci_for_opportunity(conn, opp_id)
        if ci_row is not None:
            fields = dict(
                campaign_intelligence.brief_view(conn, ci_row["id"]).get("fields") or {})
        meeting = db.meeting_for_opp(conn, opp_id)
        _r, opp, ev = _load(conn, opp_id)
    finally:
        conn.close()
    groups = prep_sheet(fields)
    # The price of each answer, computed for THIS deal (ADR-0065). The four licence
    # questions were already on the sheet and already flagged as the ones that get
    # dropped when a call overruns; what the sheet could not say was what dropping them
    # costs. Priced through the same `build_quote` the proposal uses, so the guide cannot
    # quote a number the proposal would not honour.
    qual, _scored = ev
    guide = price_guide(estimate_for(opp, qual=qual), licence_from_ci(fields))
    return render(request, "call_prep.html", nav="inbox", row=row, meeting=meeting,
                  groups=groups, cover=coverage(groups), guide=guide)


@router.get("/opportunity/{opp_id}/schedule", response_class=HTMLResponse)
def discovery_schedule_form(request: Request, opp_id: int, req: str = ""):
    """The operator's Meeting Scheduler — type (Zoom/Phone) + date + time. Prefills from a
    Discovery Request when ``req`` is given, or blank for a manual (referral/inbound) booking."""
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        dr = db.get_discovery_request(conn, int(req)) if req.strip().isdigit() else None
    finally:
        conn.close()
    from .. import meetings as _M
    return render(request, "discovery_schedule.html", nav="inbox", row=row, dr=dr,
                  integrations=_delivery_readiness(_M.integration_status()),
                  prefill_name=((dr["name"] if dr else "") or row["contact_name"] or ""),
                  prefill_email=((dr["email"] if dr else "") or row["contact_email"] or ""),
                  prefill_type=((dr["preferred_type"] if dr else "") or "zoom"))


@router.post("/opportunity/{opp_id}/schedule")
def discovery_schedule_submit(opp_id: int, meeting_type: str = Form("zoom"),
                              mode: str = Form("propose"),
                              date: str = Form(""), time: str = Form(""),
                              date2: str = Form(""), time2: str = Form(""),
                              date3: str = Form(""), time3: str = Form(""),
                              message: str = Form(""),
                              duration_min: int = Form(30), client_name: str = Form(""),
                              client_email: str = Form(""), join_url: str = Form(""),
                              request_id: str = Form("")):
    """One form, two modes (ADR-0016/0017). ``propose`` (default): up to three Eastern-time
    options become a Meeting Proposal + a reviewable client email — the client's pick books
    through the shared engine. ``direct``: the time is already agreed; book it now. All wall
    clocks here are Eastern (the client's zone); storage is UTC."""
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        rid = int(request_id) if request_id.strip().isdigit() else None
        slots = [meeting_scheduler.et_to_utc_iso(d.strip(), (t.strip() or "09:00"))
                 for d, t in ((date, time), (date2, time2), (date3, time3)) if d.strip()]
        slots = [s for s in slots if s]
        if mode == "direct":
            meeting_scheduler.schedule(
                conn, row, meeting_type=meeting_type, start_at=(slots[0] if slots else ""),
                duration_min=duration_min or 30, client_name=client_name.strip(),
                client_email=client_email.strip(), join_url=join_url.strip(),
                initiated_by=("client_request" if rid else "operator"), request_id=rid)
            return RedirectResponse(f"/opportunity/{opp_id}#discovery", status_code=303)
        res = meeting_scheduler.propose(
            conn, row, slots=slots, meeting_type=meeting_type,
            duration_min=duration_min or 30, client_name=client_name.strip(),
            client_email=client_email.strip(), message=message.strip(),
            join_url=join_url.strip(), request_id=rid)
        if not res.get("ok"):
            return RedirectResponse(f"/opportunity/{opp_id}/schedule?err=slots",
                                    status_code=303)
        pid = res["proposal"]["id"]
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/proposal/{pid}", status_code=303)


@router.get("/opportunity/{opp_id}/proposal/{pid}", response_class=HTMLResponse)
def meeting_proposal_preview(request: Request, opp_id: int, pid: int):
    """The machine proposes, the operator disposes: review the exact client email (options in
    Eastern time) before anything is sent."""
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        prop = db.get_meeting_proposal(conn, pid)
        if row is None or prop is None or prop["opp_id"] != opp_id:
            return HTMLResponse("Not found", status_code=404)
        email = meeting_scheduler.resolved_proposal_email(row, prop)
        slots = [meeting_scheduler.fmt_et(s, long=True)
                 for s in meeting_scheduler.proposal_slots(prop)]
    finally:
        conn.close()
    return render(request, "meeting_proposal.html", nav="inbox", row=row, prop=prop,
                  email=email, slots_et=slots,
                  pick_url=f"{_public_base()}/meet/{prop['token']}")


def _save_proposal_edits(conn, pid: int, subject: Optional[str], body: Optional[str],
                         reset: bool) -> None:
    """Persist the operator's edits to the exact client email (or reset to the generated
    draft). Stored as overrides — blank means "use the generated text"."""
    if reset:
        db.update_meeting_proposal(conn, pid, subject_override="", body_override="")
        return
    # Only persist NON-empty edits: a blank field means "not submitted / leave as-is"
    # (Form defaults to "" so we can't see None), never "wipe the saved draft" — that's
    # what Reset is for. In the real UI the box is always prefilled, so Send always
    # carries the full text and this WYSIWYG guarantee holds.
    fields = {}
    if (subject or "").strip():
        fields["subject_override"] = subject.strip()
    if (body or "").strip():
        fields["body_override"] = body.strip()
    if fields:
        db.update_meeting_proposal(conn, pid, **fields)


@router.post("/opportunity/{opp_id}/proposal/{pid}/edit")
def meeting_proposal_edit(opp_id: int, pid: int, subject: str = Form(""),
                          body: str = Form(""), reset: str = Form("")):
    """Save the operator's edits to the times email without sending (Save draft / Reset)."""
    conn = db.connect()
    try:
        prop = db.get_meeting_proposal(conn, pid)
        if prop is None or prop["opp_id"] != opp_id:
            return HTMLResponse("Not found", status_code=404)
        _save_proposal_edits(conn, pid, subject, body, reset == "1")
    finally:
        conn.close()
    saved = "reset" if reset == "1" else "saved"
    return RedirectResponse(
        f"/opportunity/{opp_id}/proposal/{pid}?{saved}=1", status_code=303)


@router.post("/opportunity/{opp_id}/proposal/{pid}/send")
def meeting_proposal_send(opp_id: int, pid: int, subject: str = Form(""),
                          body: str = Form("")):
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        prop = db.get_meeting_proposal(conn, pid)
        if row is None or prop is None or prop["opp_id"] != opp_id:
            return HTMLResponse("Not found", status_code=404)
        # Persist whatever is in the review box FIRST, so we send exactly what's shown.
        _save_proposal_edits(conn, pid, subject, body, reset=False)
        prop = db.get_meeting_proposal(conn, pid)
        res = meeting_scheduler.send_proposal(conn, row, prop)
        if not res.get("ok"):
            return RedirectResponse(
                f"/opportunity/{opp_id}/proposal/{pid}?err=send", status_code=303)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#discovery", status_code=303)


@router.post("/opportunity/{opp_id}/proposal/{pid}/cancel")
def meeting_proposal_cancel(opp_id: int, pid: int):
    conn = db.connect()
    try:
        prop = db.get_meeting_proposal(conn, pid)
        if prop is not None and prop["opp_id"] == opp_id and prop["status"] in ("draft", "sent"):
            db.update_meeting_proposal(conn, pid, status="canceled")
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#discovery", status_code=303)


def _build_review_for_opp(conn, opp_id, version=1):
    """Project a Commercial Review for an opportunity, live from Campaign Intelligence.
    Operator edits (price/deposit) live in the ``commercial`` doc-override blob and win."""
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None, None
    qual, _scored = ev
    # Priced against the ASSIGNED talent's real rates once a project exists — the whole
    # point of `estimate_for`'s project_id (ADR-0033): "the internal number and the
    # client-facing proposal cannot diverge after assignment". This call omitted it, so
    # the Review priced off global role defaults while the project's own proposal priced
    # off the real ones. Nobody noticed because the quote came from the client's stated
    # budget, which made both paths return the same figure whatever estimate fed them;
    # the moment the price started deriving from the work (ADR-0065), the two disagreed
    # on the deposit — the client approving one number and being invoiced from another.
    est = _estimate_for_row(conn, row, opp, qual)
    ci_view, met = _brief_ci_context(conn, row)
    overrides = db.get_doc_overrides(conn, opp_id).get("commercial") or {}
    review = commercial.build_commercial_review(opp, qual, est, ci_view, met=met,
                                                version=version, overrides=overrides)
    return row, review


@router.post("/opportunity/{opp_id}/commercial/edit")
def commercial_edit(opp_id: int, fee_low: str = Form(""), fee_high: str = Form(""),
                    deposit_pct: str = Form(""), scope_summary: str = Form(""),
                    timeline: str = Form(""), revision_rounds: str = Form("")):
    """Operator edits the Commercial Review before releasing it — the whole agreement, not
    just the price: scope summary, delivery deadline (timeline), revision rounds, the price
    band and the deposit %. Stored in the ``commercial`` override blob and consumed on every
    render, so what's on the page is exactly what the client approves. An empty field snaps
    that value back to the Campaign-Intelligence-derived default."""
    conn = db.connect()
    try:
        ov = dict(db.get_doc_overrides(conn, opp_id).get("commercial") or {})
        lo, hi = _parse_rate(fee_low), _parse_rate(fee_high)
        if lo and hi:
            ov["fee_low"], ov["fee_high"] = int(min(lo, hi)), int(max(lo, hi))
        elif not fee_low and not fee_high:
            ov.pop("fee_low", None); ov.pop("fee_high", None)
        pct = _parse_rate(deposit_pct)
        if pct is not None:
            ov["deposit_pct"] = max(0.0, min(100.0, pct)) / 100.0
        # Free-text agreement fields: set when provided, cleared (→ CI default) when blank.
        for key, val in (("scope_summary", scope_summary), ("timeline", timeline),
                         ("revision_rounds", revision_rounds)):
            if val.strip():
                ov[key] = val.strip()
            else:
                ov.pop(key, None)
        db.update_doc_override(conn, opp_id, "commercial", ov)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/commercial", status_code=303)


@router.get("/opportunity/{opp_id}/commercial", response_class=HTMLResponse)
def commercial_preview(request: Request, opp_id: int):
    """Operator preview of the Commercial Review, generated from CI — 'the machine prepares'.
    Review it, then Release to the client ('the human commits')."""
    conn = db.connect()
    try:
        version = db.next_commercial_version(conn, opp_id)
        row, review = _build_review_for_opp(conn, opp_id, version)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        current = db.current_commercial_review(conn, opp_id)
        token = db.ensure_share_token(conn, opp_id)
        rev_ov = (db.get_doc_overrides(conn, opp_id).get("commercial") or {}).get("revision_rounds")
    finally:
        conn.close()
    return render(request, "commercial_preview.html", nav="inbox", row=row, review=review,
                  current=current, token=token, released_badge="Preview",
                  revision_rounds=(rev_ov or ""))


@router.post("/opportunity/{opp_id}/commercial/release")
def commercial_release(opp_id: int):
    """Freeze + release the Commercial Review to the client (opens the Commercial stage in
    their workspace). Once released it's a stable offer; re-release supersedes with a new
    version. Records a CI timeline event."""
    conn = db.connect()
    try:
        version = db.next_commercial_version(conn, opp_id)
        row, review = _build_review_for_opp(conn, opp_id, version)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        db.release_commercial_review(conn, opp_id, review.version,
                                     commercial.review_to_json(review))
        _reconcile_opp_status(conn, opp_id)      # → Proposal out
        # Email is the notification layer (ADR-0020): the proposal is in their workspace.
        token = db.ensure_share_token(conn, opp_id)
        if (row["contact_email"] or "").strip():
            try:
                mailer.send_email(
                    row["contact_email"].strip(),
                    f"Your proposal is ready · {row['client']}",
                    f"Your proposal for {row['need']} is ready in your workspace: scope, "
                    f"timeline, investment and terms, with one approval at the end.\n\n"
                    f"{_public_base()}/workspace/{token}")
            except Exception:  # noqa: BLE001
                pass
        if campaigns.workspace_enabled():
            try:
                ci = campaign_intelligence.ensure_for_opportunity(conn, row)
                db.add_ci_event(conn, ci["id"], actor="operator", verb="commercial_released",
                                facet="commercial", key="review", to_value=f"v{review.version}",
                                source="commercial")
            except Exception:  # noqa: BLE001
                pass
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/commercial", status_code=303)


@router.post("/opportunity/{opp_id}/start-production")
def start_production(opp_id: int):
    """The operator confirms the Sales→Production handoff is complete (ADR-0018, Phase 4):
    stamps the project's kickoff gate, advancing the workspace from Kickoff into Production.
    'The machine prepared readiness; the human commits to starting.'"""
    from datetime import datetime, timezone
    conn = db.connect()
    try:
        project = db.project_for_opp(conn, opp_id)
        if project is None:
            return HTMLResponse("No project yet", status_code=404)
        # Deposit gates production start (reported live: "the deposit needs to be completed
        # to initiate kickoff"). Until the deposit invoice is paid, we don't stamp the gate —
        # the operator is bounced back with a reason so nothing kicks off unpaid.
        dep = next((i for i in db.list_invoices(conn, project["id"])
                    if (i["kind"] or "") == "Deposit"), None)
        if dep is None or (dep["status"] or "").lower() not in ("paid", "settled"):
            return RedirectResponse(f"/opportunity/{opp_id}?err=deposit_unpaid", status_code=303)
        conn.execute("UPDATE projects SET kickoff_completed_at = ? WHERE id = ?",
                     (datetime.now(timezone.utc).isoformat(), project["id"]))
        conn.commit()
        if campaigns.workspace_enabled():
            try:
                opp = db.get_opportunity(conn, opp_id)
                ci = campaign_intelligence.ensure_for_opportunity(conn, opp)
                db.add_ci_event(conn, ci["id"], actor="operator", verb="production_started",
                                facet="commercial", key="kickoff", source="kickoff")
            except Exception:  # noqa: BLE001
                pass
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


@router.post("/opportunity/{opp_id}/request/{req_id}/decline")
def discovery_request_decline(opp_id: int, req_id: int):
    conn = db.connect()
    try:
        db.set_discovery_request_status(conn, req_id, "declined")
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


@router.get("/opportunity/{opp_id}/qualification", response_class=HTMLResponse)
def qualification_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
    finally:
        conn.close()
    qual, scored = ev
    return render(
        request, "qualification.html", nav="inbox", row=row, opp=opp, qual=qual, scored=scored
    )


@router.get("/opportunity/{opp_id}/estimate", response_class=HTMLResponse)
def estimate_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        qual, scored = ev
        # Inside the open connection: the estimate now resolves the deal's project to
        # pick up its assigned rates, so it needs the DB.
        est = _estimate_for_row(conn, row, opp, qual)
    finally:
        conn.close()
    return render(
        request, "estimate.html", nav="inbox", row=row, opp=opp, qual=qual, est=est
    )


def _brief_for(conn, opp_id: int):
    """Load an opportunity and assemble its pursuit brief (None if missing)."""
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None, None, None
    qual, scored = ev
    est = _estimate_for_row(conn, row, opp, qual)
    strategic = assess_strategic_value(opp)
    brief = build_pursuit_brief(opp, qual, scored, est, strategic,
                                quote_band=_quote_band_for(conn, row, opp, est))
    return row, opp, brief


def _brief_checklist(brief, done_keys):
    """Pair each checklist step with a stable key and its done state.

    Key = index + slug so it survives reloads (the list is deterministic per opp)
    and stays unique even if two steps share a prefix."""
    items = []
    for i, text in enumerate(brief.checklist):
        key = f"{i}-{slug(text)[:48]}"
        items.append({"key": key, "text": text, "done": key in done_keys})
    done = sum(1 for it in items if it["done"])
    total = len(items)
    progress = {"done": done, "total": total, "pct": round(done / total * 100) if total else 0}
    return items, progress


@router.get("/opportunity/{opp_id}/brief", response_class=HTMLResponse)
def brief_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, brief = _brief_for(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        done_keys = db.brief_done_keys(conn, opp_id)
    finally:
        conn.close()
    items, progress = _brief_checklist(brief, done_keys)
    return render(
        request, "brief.html", nav="inbox", row=row, opp=opp, brief=brief,
        checklist_items=items, progress=progress,
    )


@router.post("/opportunity/{opp_id}/brief/step")
def toggle_brief_step(opp_id: int, step_key: str = Form(...), done: str = Form("")):
    conn = db.connect()
    try:
        db.set_brief_step(conn, opp_id, step_key, bool(done.strip()))
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/brief", status_code=303)


@router.get("/opportunity/{opp_id}/brief.txt", response_class=PlainTextResponse)
def brief_text(opp_id: int):
    conn = db.connect()
    try:
        row, opp, brief = _brief_for(conn, opp_id)
        if row is None:
            return PlainTextResponse("Opportunity not found", status_code=404)
    finally:
        conn.close()
    return PlainTextResponse(brief.render_text())


def _outreach_for(conn, opp_id: int):
    """Load an opportunity and assemble its outreach plan (None if missing)."""
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None, None, None
    qual, scored = ev
    est = _estimate_for_row(conn, row, opp, qual)
    strategic = assess_strategic_value(opp)
    plan = build_outreach_plan(
        opp, qual, scored, est, strategic, contact_name=row["contact_name"],
        quote_band=_quote_band_for(conn, row, opp, est),
    )
    return row, opp, plan


@router.get("/opportunity/{opp_id}/outreach", response_class=HTMLResponse)
def outreach_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, plan = _outreach_for(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        events = db.list_outreach_events(conn, opp_id)
    finally:
        conn.close()
    return render(
        request, "outreach.html", nav="inbox", row=row, opp=opp, plan=plan, events=events,
        respond=respond_action(row, plan),
    )


@router.get("/opportunity/{opp_id}/outreach.txt", response_class=PlainTextResponse)
def outreach_text(opp_id: int):
    conn = db.connect()
    try:
        row, opp, plan = _outreach_for(conn, opp_id)
        if row is None:
            return PlainTextResponse("Opportunity not found", status_code=404)
    finally:
        conn.close()
    return PlainTextResponse(plan.render_text())


@router.post("/opportunity/{opp_id}/outreach")
def set_outreach(
    opp_id: int,
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    contact_role: str = Form(""),
    next_action: str = Form(""),
    next_action_due: str = Form(""),
    contact_linkedin: str = Form(""),
    contact_phone: str = Form(""),
):
    conn = db.connect()
    try:
        db.update_outreach(
            conn, opp_id, contact_name, contact_email, contact_role,
            next_action, next_action_due, contact_linkedin, contact_phone,
        )
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/outreach", status_code=303)


@router.post("/opportunity/{opp_id}/outreach/event")
def add_outreach_event(
    opp_id: int,
    channel: str = Form("Email"),
    direction: str = Form("Sent"),
    note: str = Form(""),
):
    conn = db.connect()
    try:
        if note.strip():
            db.add_outreach_event(conn, opp_id, channel, direction, note.strip())
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/outreach", status_code=303)


# --------------------------------------------------------------------------- #
# Block composer (Phase 1) — on/off blocks + live preview, choices persisted per
# deal under the `compose` doc-override; the send action builds a personal
# plain-text email into Jon's own mail client (mailto). Mirrors the doc save
# routes' style.
# --------------------------------------------------------------------------- #
def _compose_state(conn, opp_id: int):
    """Load the opp/plan, build the composer blocks, and resolve the saved
    selection + assembled body from the `compose` override. Returns
    ``(row, opp, plan, blocks, selected, body)`` (all None when missing)."""
    row, opp, plan = _outreach_for(conn, opp_id)
    if row is None:
        return None, None, None, None, None, None
    overrides = db.get_doc_overrides(conn, opp_id)
    # Mint (or fetch) the unguessable share token so the page-link block carries the
    # real token-gated URL — the same token the first-touch route validates.
    share_token = db.ensure_share_token(conn, opp_id)
    # ADR-0017: the email inherits from Campaign Intelligence, same as the Brief.
    ci_view, met = _brief_ci_context(conn, row)
    blocks = build_compose_blocks(
        opp, None, plan, overrides=overrides, opp_id=opp_id,
        contact_name=row["contact_name"], share_token=share_token,
        ci_view=ci_view, met=met,
    )
    selected = compose_selection(blocks, overrides)
    body = assemble_email(blocks, selected)
    return row, opp, plan, blocks, selected, body


@router.get("/opportunity/{opp_id}/compose", response_class=HTMLResponse)
def compose_page(request: Request, opp_id: int, sent: str = ""):
    conn = db.connect()
    try:
        row, opp, plan, blocks, selected, body = _compose_state(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        overrides = db.get_doc_overrides(conn, opp_id)
        relevant_uploads = overrides.get("relevant_uploads") or []
        token = db.ensure_share_token(conn, opp_id)
    finally:
        conn.close()
    subject = plan.email_subject
    mailto = _mailto(row["contact_email"] or "", subject, body)
    # The client link the email carries IS the client Workspace — its Discovery Summary is
    # the single brief the client reads (consolidation, ADR-0018). Token-gated so it's
    # shareable but not enumerable, and "Preview the brief" opens exactly what they'll see.
    page_url = f"/workspace/{token}"
    return render(
        request, "compose.html", nav="inbox", row=row, opp=opp, plan=plan,
        blocks=blocks, selected=selected, body=body, subject=subject, mailto=mailto,
        relevant_uploads=relevant_uploads, page_url=page_url,
        mail_configured=mailer.mail_configured(), sent=sent,
    )


@router.post("/opportunity/{opp_id}/compose")
async def set_compose(request: Request, opp_id: int):
    """Persist the composer state: the checked block keys + any edited block texts
    are written into the `compose` doc-override. Mirrors the doc save routes."""
    form = await request.form()
    on = [str(k) for k in form.getlist("on")]
    text = {}
    for key in COMPOSE_BLOCK_KEYS:
        raw = form.get(f"text_{key}")
        if isinstance(raw, str) and raw.strip():
            text[key] = raw
    compose = {"on": on}
    if text:
        compose["text"] = text
    conn = db.connect()
    try:
        db.update_doc_override(conn, opp_id, "compose", compose)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/compose", status_code=303)


@router.post("/opportunity/{opp_id}/compose/send")
def compose_send(opp_id: int):
    """Actually send the composed email via the configured mail provider,
    instead of only opening a mailto: draft in Jon's own mail client (where
    it sits until he separately hits Send there). Falls back to "manual" —
    same as the recruiting invite — when there's no contact email or mail
    isn't configured; the mailto link stays on the page either way, so
    nothing is lost, this just adds a real send on top."""
    conn = db.connect()
    try:
        row, opp, plan, blocks, selected, body = _compose_state(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
    finally:
        conn.close()
    email = (row["contact_email"] or "").strip()
    if not email or not mailer.mail_configured():
        return RedirectResponse(f"/opportunity/{opp_id}/compose?sent=manual", status_code=303)
    # ADR-0018: the emailed link is the client's durable Workspace (built by the page-link
    # block), which renders the LIVE brief inline — the relationship grows, nothing resets.
    # Sending still freezes a brief snapshot, but its role is the audit/PDF record (its Phase-3
    # job), NOT how the client views the brief; legacy ?v= links still render it on the
    # standalone route for backward compatibility.
    conn = db.connect()
    try:
        ci_view, met = _brief_ci_context(conn, row)
        overrides = db.get_doc_overrides(conn, opp_id)
        qual, _scored = evaluate(opp)
        est = _estimate_for_row(conn, row, opp, qual)
        doc = build_capabilities_doc(
            opp, qual, est, toggles=default_toggles(row["status"], met=met),
            overrides=overrides,
            call_url=os.environ.get("CHORDENTIAL_DISCOVERY_CALL_URL", "").strip(),
            ci_view=ci_view, met=met)
        db.create_brief_snapshot(conn, opp_id, doc_to_json(doc))
        # Re-sending a summary the client flagged IS the fix landing. Without this the
        # correction stays unresolved for ever and the board keeps saying "Fix the
        # summary" after it has been fixed and re-shared — the mirror image of the bug
        # where it said "waiting on the client" after they had already replied.
        from datetime import datetime, timezone
        correction = overrides.get("scope_correction") or None
        if isinstance(correction, dict) and not correction.get("resolved"):
            db.update_doc_override(conn, opp_id, "scope_correction",
                                   {**correction, "resolved": True,
                                    "resolved_at": datetime.now(timezone.utc).isoformat()})
    finally:
        conn.close()
    base = _public_base()
    status = mailer.send_email(
        email, plan.email_subject, body, html=mailer.branded_html(base, body),
    )
    return RedirectResponse(f"/opportunity/{opp_id}/compose?sent={status}", status_code=303)


# --------------------------------------------------------------------------- #
# The tailored first-touch page (Phase 2) — a SELF-CONTAINED public page the
# soft email link points at. NOT admin-gated (an external recipient opens it);
# the unguessable per-opp share token in ?k=<token> IS the access control. A
# valid load also stamps the Phase-3 engagement signal (view count / last seen).
#
# Option C (branded HTML send via Gmail) remains DEFERRED — this page + its view
# measurement are the gate that decides whether Option C is ever worth building.
# --------------------------------------------------------------------------- #
def _reply_to_address() -> str:
    """A real recipient for the first-touch 'Reply' CTA. Prefer the configured
    send-from address; otherwise derive hello@<public-domain> so the mailto never
    opens an empty, recipient-less draft."""
    configured = mailer._smtp_from()
    if configured:
        return configured
    domain = os.environ.get(
        "CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com")
    host = domain.split("://", 1)[-1].strip("/").split("/")[0] or "chordential.com"
    return f"hello@{host}"


@router.get("/opportunity/{opp_id}/first-touch", response_class=HTMLResponse)
def first_touch_page(request: Request, opp_id: int, k: str = ""):
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        token = row["share_token"] if row is not None else None
        # Token check is the access control: a missing opp, an unset token, or a
        # mismatch all 404 identically so the page never leaks an opp's existence.
        if row is None or not token or not k or not hmac.compare_digest(str(k), str(token)):
            return HTMLResponse("Not found", status_code=404)
        opp = db.opportunity_from_row(row)
        overrides = db.get_doc_overrides(conn, opp_id)
        # Phase 3: a valid load is the engagement signal surfaced on the outreach view.
        db.record_first_touch_view(conn, opp_id)
    finally:
        conn.close()

    understanding = build_understanding(opp)
    relevant_uploads = overrides.get("relevant_uploads") or []
    relevant_links = overrides.get("relevant_links") or []
    # Never dead-end the highest-intent click with silence: when nothing was
    # hand-picked for this opportunity, fall back to the showcase demo tracks
    # (honest craft demos, invented brands) so there is always music to hear.
    showcase_tracks = []
    if not relevant_uploads and not relevant_links:
        from .showcase import get_showcase
        showcase_tracks = [
            {"label": f"{d.title} · {d.discipline_label}", "url": d.audio_url}
            for d in get_showcase().demos if d.audio_url
        ]
    call_url = os.environ.get("CHORDENTIAL_DISCOVERY_CALL_URL", "").strip()
    return render(
        request, "first_touch.html", nav="", row=row, opp=opp,
        client=row["client"], understanding=understanding,
        relevant_uploads=relevant_uploads, relevant_links=relevant_links,
        showcase_tracks=showcase_tracks, reply_to=_reply_to_address(),
        call_url=call_url,
    )


@router.get("/opportunity/{opp_id}/match", response_class=HTMLResponse)
def talent_match_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        talents = db.load_talent(conn)
    finally:
        conn.close()
    qual, scored = ev
    matches = match_talent(qual.discipline, qual.secondary_disciplines,
                           f"{opp.need} {opp.description}", talents)
    # Detail for the eventual human decision: how many were considered vs gated out.
    matchable = sum(1 for t in talents if t.matchable)
    pending = sum(1 for t in talents if t.review_status.value == "Pending")
    return render(
        request, "match.html", nav="inbox", row=row, opp=opp, qual=qual, scored=scored,
        matches=matches, matchable=matchable, pending=pending, roster=len(talents),
    )


@router.post("/opportunity/{opp_id}/status")
def set_status(
    opp_id: int,
    status: str = Form(...),
    outcome_value: str = Form(""),
    return_to: str = Form(""),
):
    conn = db.connect()
    try:
        value = float(outcome_value) if outcome_value.strip() else None
        db.update_status(conn, opp_id, status, value)
    finally:
        conn.close()
    return RedirectResponse(
        _safe_local(return_to, f"/opportunity/{opp_id}"), status_code=303
    )


@router.post("/opportunity/{opp_id}/create-project")
def opportunity_create_project(opp_id: int):
    """Spin up the project for a deal that is already won.

    Countersigning creates the project itself, so this is the self-heal for the deals
    that were countersigned before it did — and the fallback for any award that reached
    "Won" by a path that skipped project creation. Idempotent: an existing project is
    returned, never duplicated.
    """
    conn = db.connect()
    try:
        if db.get_opportunity(conn, opp_id) is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        pid = _ensure_project_for_opp(conn, opp_id)
        _reconcile_opp_status(conn, opp_id)
    finally:
        conn.close()
    # Straight to the project, because the next decision is WHO — the roles are waiting
    # there and assigning one sends the portal, the scope email and the client's update.
    return RedirectResponse(f"/project/{pid}" if pid else f"/opportunity/{opp_id}",
                            status_code=303)


@router.post("/opportunity/{opp_id}/countersign")
def opportunity_countersign(request: Request, opp_id: int, typed_name: str = Form(""),
                            consent: str = Form("")):
    """Our half of the signed proposal (ADR-0065).

    The acceptance text the client signs says, in as many words, "we countersign, raise
    the deposit invoice, and work begins when that deposit clears". Until now that was a
    promise the product could not keep: nothing anywhere could countersign, so the first
    sentence of the first document we ask a client to sign was one we did not honour.

    Two refusals, both load-bearing:

    * **Nothing to countersign until they have signed.** A countersignature on a document
      the other party has not accepted is not a contract, it is a note to self.
    * **Never countersign a document that has MOVED since they signed it.** If
      `signing.verify` says SUPERSEDED, the text we would be binding ourselves to is not
      the text they agreed to. Refusing is the whole reason the digest exists — the
      alternative is two parties signed to two different documents, which is exactly the
      failure the old typed-name-in-a-blob could not even detect.
    """
    who = actor.identify(request).get("label", "") or ""
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        client_sig = db.latest_opportunity_signature(conn, opp_id, signing.DOC_PROPOSAL)
        if client_sig is None:
            return RedirectResponse(f"/opportunity/{opp_id}?flag=not-signed#agreement",
                                    status_code=303)
        if db.latest_opportunity_signature(
                conn, opp_id, signing.DOC_PROPOSAL_COUNTERSIGN) is not None:
            return RedirectResponse(f"/opportunity/{opp_id}#agreement", status_code=303)
        _r, _o, _e, doc, _dep = agreement_doc_for(conn, opp_id)
        agr = getattr(doc, "agreement", None)
        text = agr.signable_text() if agr is not None else None
        if signing.verify(client_sig["digest"], text) != signing.VALID:
            # The document changed after they signed it. Countersigning now would bind us
            # to terms they never saw.
            return RedirectResponse(f"/opportunity/{opp_id}?flag=superseded#agreement",
                                    status_code=303)
        try:
            sig = signing.build_signature(
                doc_kind=signing.DOC_PROPOSAL_COUNTERSIGN,
                opportunity_id=opp_id,
                document_text=text,
                signer_name=who or "Chordential",
                typed_name=(typed_name.strip() or who or "Chordential"),
                actor=who,
                ip=(request.client.host if request.client else ""),
                user_agent=request.headers.get("user-agent", ""),
                terms_snapshot={"countersigns": client_sig["digest"]},
            )
        except ValueError as exc:
            return HTMLResponse(str(exc), status_code=400)
        db.record_signature(conn, sig)
        db.update_doc_override(conn, opp_id, "proposal_countersigned", {
            "at": sig.signed_at, "by": sig.typed_name, "digest": sig.digest})
        # Countersigning IS the award — both parties are now bound — so it creates the
        # project, exactly as approving a Commercial Review does (ADR-0018). Without this
        # the deal was won and had nowhere to put the work: the board offered "Start
        # production" and there was no project to start, no roles to fill, and nobody to
        # assign. Production does not begin with a button; it begins with a team.
        _ensure_project_for_opp(conn, opp_id)
        _reconcile_opp_status(conn, opp_id)   # → Won
        # The contact lives on the ROW, not on the Opportunity dataclass; falling back to
        # the address the signer actually used means we write to whoever signed.
        _row_mail = row["contact_email"] if "contact_email" in row.keys() else ""
        client_mail = (_row_mail or "").strip() or (client_sig["signer_email"] or "")
        need, client_name = row["need"], row["client"]
        share_token = db.ensure_share_token(conn, opp_id)
    finally:
        conn.close()
    if client_mail:
        try:
            mailer.send_email(
                client_mail, f"Countersigned — {client_name} · {need}",
                f"We have countersigned the agreement for {need}. It is now signed by "
                f"both parties.\n\nNext: we raise the deposit invoice, and work begins "
                f"when it clears.\n\n{_public_base()}/workspace/{share_token}")
        except Exception:  # noqa: BLE001
            pass
    return RedirectResponse(f"/opportunity/{opp_id}#agreement", status_code=303)


@router.post("/opportunity/{opp_id}/delivery-sent")
def mark_delivery_sent(opp_id: int, return_to: str = Form("")):
    """Stamp the 'Delivery doc sent' milestone (the outreach → closing hand-off)."""
    conn = db.connect()
    try:
        db.mark_delivery_doc_sent(conn, opp_id)
    finally:
        conn.close()
    return RedirectResponse(
        _safe_local(return_to, f"/opportunity/{opp_id}"), status_code=303
    )


@router.post("/opportunity/{opp_id}/strategic")
def set_strategic(opp_id: int, buyer_value: str = Form("unknown"), marquee: str = Form("")):
    conn = db.connect()
    try:
        db.update_strategic_inputs(conn, opp_id, buyer_value, bool(marquee.strip()))
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


@router.post("/opportunity/{opp_id}/notes")
def set_notes(opp_id: int, notes: str = Form("")):
    conn = db.connect()
    try:
        db.update_notes(conn, opp_id, notes)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


@router.get("/opportunity/{opp_id}/buyer", response_class=HTMLResponse)
def opportunity_buyer(request: Request, opp_id: int):
    """The buyer profile rendered inside the opportunity's tabbed context, so the
    subnav stays put instead of jumping to the standalone company page."""
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        ctx = _buyer_context(conn, row["client"])
    finally:
        conn.close()
    if ctx is None:
        return HTMLResponse("Buyer not found", status_code=404)
    return render(request, "buyer.html", nav="inbox", opp_row=row, **ctx)


@router.get("/opportunity/{opp_id}/capabilities", response_class=HTMLResponse)
def opportunity_capabilities(request: Request, opp_id: int, k: str = "", v: str = ""):
    """The Campaign Brief — the branded, toggleable client-facing deliverable → preview,
    Save as PDF, and (with a valid ?k=<share_token>) the public client link the outreach
    email points to. One artifact: the emailed link opens this same brief.

    Sections default by deal stage (discovery hides cost; proposal adds the price
    band; contract adds terms + DocuSign). Once the toggle bar is submitted, each
    section follows its checkbox so you can tailor what the buyer sees."""
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        # Client link: a valid share token opens the brief publicly (no admin chrome); a
        # missing/bad token on a ?k request 404s so the brief never leaks. No ?k → the
        # admin edit view (already behind the login gate).
        public = False
        if (k or "").strip():
            token = row["share_token"] if "share_token" in row.keys() else None
            if not token or not hmac.compare_digest(str(k), str(token)):
                return HTMLResponse("Not found", status_code=404)
            # Consolidation (ADR-0018): the client's single brief IS the workspace Discovery
            # Summary. The live standalone client link now redirects into the workspace so
            # there's ONE durable client destination — no divergent second page. Reported
            # live: "uploading audio + Preview takes you to a totally different page." A
            # frozen ?v=<snapshot> send still renders verbatim here (historical record); the
            # operator edit view (no ?k, behind the login gate) still renders here too.
            public = True
        # The deal's project + its Deposit invoice (if either exists yet) — used to
        # surface the Stripe "Pay deposit" button, exactly as the detail page looks
        # the project up. No project/invoice → we fall back to showing the amount.
        project = db.project_for_opp(conn, opp_id)
        deposit_invoice = None
        stored_proposal = None
        if project is not None:
            stored_proposal = db.proposal_for_project(conn, project["id"])
            for inv in db.list_invoices(conn, project["id"]):
                if inv["kind"] == "Deposit":
                    deposit_invoice = inv
                    break
        # Per-deal hand edits (client name, understanding, chips, links, template).
        overrides = db.get_doc_overrides(conn, opp_id)
        custom_chips = db.list_custom_chips(conn)
        # The Brief's "Request a Discovery Call" CTA → the token-gated request form (same
        # share token that opens the brief), so the client requests, Jon schedules (ADR-0016).
        brief_token = db.ensure_share_token(conn, opp_id)
        # ADR-0017: Campaign Intelligence first; and a sent snapshot renders VERBATIM.
        ci_view, met = _brief_ci_context(conn, row)
        snapshot_doc = None
        if (v or "").strip().isdigit():
            snap = db.get_brief_snapshot(conn, int(v))
            if snap is not None and snap["opp_id"] == opp_id:
                snapshot_doc = doc_from_json(snap["doc_json"])
        qual, scored = ev
        est = _estimate_for_row(conn, row, opp, qual)
    finally:
        conn.close()
    request_url = f"/opportunity/{opp_id}/request?k={brief_token}"

    toggles = default_toggles(row["status"], met=met)
    qp = request.query_params
    if qp.get("submitted"):                       # toggle bar was applied
        for key in ("cost", "examples", "call", "terms", "delivery"):
            toggles[key] = qp.get(key) == "1"
    doc = snapshot_doc or build_capabilities_doc(
        opp, qual, est, toggles=toggles, overrides=overrides,
        call_url=os.environ.get("CHORDENTIAL_DISCOVERY_CALL_URL", "").strip(),
        ci_view=ci_view, met=met,
    )

    # Edit-mode payload the (later) editable-template UI consumes: the chip library
    # per editable section (deliverable chips scoped to the chosen template), the
    # available delivery templates for the override dropdown, and saved "My chips".
    edit = qp.get("edit") == "1" and not public   # the client link is never editable
    chip_library = {
        section: chips_for(section, doc.delivery_template)
        for section in SECTION_FAMILY
    }
    delivery_templates = {
        key: tmpl["label"] for key, tmpl in DELIVERY_TEMPLATES.items()
    }

    # Deposit amount for the Pay-deposit element: the stored proposal's deposit if the
    # project's been spun up, otherwise a fraction of the band shown on THIS page
    # (ADR-0034). It used to derive from the estimate, so the button and the "Indicative
    # investment" figure above it disagreed. ci_view/overrides are already loaded — this
    # needs no further DB work, which matters because the connection is closed by here.
    if stored_proposal is not None and stored_proposal["deposit_amount"]:
        deposit_amount = stored_proposal["deposit_amount"]
    else:
        deposit_amount = build_proposal(
            opp, qual, est,
            quote_band=capabilities_quote_band(
                opp, est, ci_fields=(ci_view or {}).get("fields") or {},
                commercial_overrides=(overrides or {}).get("commercial")),
        ).deposit_amount

    # Re-derive the agreement with the deposit figure, exactly as the client's copy does
    # (`_live_brief_ctx`). Both surfaces must build the SAME text or the digest disagrees:
    # without this the operator's copy kept the prose deposit while the client signed one
    # naming the real number, so an untouched document read as SUPERSEDED. One derivation,
    # many reporters — and this is the reporter that had drifted.
    attach_agreement(doc, deposit_amount=deposit_amount)

    # The signature, on the operator's copy too. Without this the person who has to
    # countersign and start production could only learn the client had signed from an
    # email — the document itself, the thing that WAS signed, said nothing. No `sign_url`
    # is passed, so this view renders the record and never a form: the author of a
    # document must not be able to sign it on the client's behalf.
    conn = db.connect()
    try:
        proposal_signature = db.latest_opportunity_signature(
            conn, opp_id, signing.DOC_PROPOSAL)
    finally:
        conn.close()
    sig_state = signing.verify(
        proposal_signature["digest"] if proposal_signature is not None else "",
        doc.agreement.signable_text() if getattr(doc, "agreement", None) else None)

    return render(
        request, "capabilities_doc.html", nav="inbox", row=row, doc=doc,
        proposal_signature=proposal_signature,
        proposal_signature_mark=(
            (proposal_signature["drawn_mark"] if "drawn_mark" in proposal_signature.keys()
             else "") if proposal_signature is not None else ""),
        proposal_signature_note=signing.verdict_note(
            sig_state, dict(proposal_signature) if proposal_signature is not None else None),
        deposit_amount=deposit_amount,
        deposit_invoice_id=(deposit_invoice["id"] if deposit_invoice else None),
        edit=edit, overrides=overrides, chip_library=chip_library,
        custom_chips=custom_chips, delivery_templates=delivery_templates,
        section_family=SECTION_FAMILY, public=public, request_url=request_url,
    )


# --------------------------------------------------------------------------- #
# Editable client document — per-deal save endpoints (the UI pass calls these).
# Each is best-effort, validates inputs minimally, and redirects back into edit
# mode so the toolbar/edit affordances stay visible after a save.
# --------------------------------------------------------------------------- #
_DOC_FIELDS = {"client", "understanding", "delivery_template", "delivery_assumptions"}

# LIST sections of the brief, edited as one line per item. These are the two the operator
# could not touch at all: the client flags a summary, the operator opens it to fix, and the
# only sections they could not change were the two most likely to be wrong — a machine's
# read of what is risky and what is unresolved. Stored as a list override; blank resets to
# the generated set, exactly like the scalar fields.
_DOC_LIST_FIELDS = {"risks", "open_questions"}


def _doc_redirect(opp_id: int):
    return RedirectResponse(
        f"/opportunity/{opp_id}/capabilities?edit=1", status_code=303
    )


def _doc_back(opp_id: int, return_to: str = ""):
    """Redirect back to the caller (e.g. the composer) when a safe local
    ``return_to`` is supplied, else to the capabilities doc editor."""
    rt = (return_to or "").strip()
    if rt.startswith("/opportunity/") and "//" not in rt and " " not in rt:
        return RedirectResponse(rt, status_code=303)
    return _doc_redirect(opp_id)


@router.post("/opportunity/{opp_id}/doc/field")
def doc_field(opp_id: int, name: str = Form(""), value: str = Form("")):
    """Set/reset an override field. A blank value resets it to the generated default.

    Scalars (`client`, `understanding`, …) store the string. LIST sections (`risks`,
    `open_questions`) arrive as a textarea, one item per line, and store a list — so the
    operator can cut a risk that reads wrong, reword one, or add the thing the machine
    missed, on the two sections that previously had no edit at all."""
    if name in _DOC_LIST_FIELDS:
        items = [ln.strip().lstrip("•-–— ").strip()
                 for ln in (value or "").replace("\r", "").split("\n")]
        items = [i for i in items if i]
        conn = db.connect()
        try:
            db.update_doc_override(conn, opp_id, name, items)
        finally:
            conn.close()
        return _doc_redirect(opp_id)
    if name in _DOC_FIELDS:
        conn = db.connect()
        try:
            db.update_doc_override(conn, opp_id, name, value)
        finally:
            conn.close()
    return _doc_redirect(opp_id)


# ADR-0017: brief fields that are Campaign Intelligence slots. Editing one in the brief
# writes CI (the single source of truth); the brief then re-renders from the updated
# intelligence — edits are never page-local and never revert to stock copy.
_BRIEF_CI_FIELDS = {
    "business_objective": ("engagement", "business_objective"),
    "budget_band": ("engagement", "budget_band"),
    "deadline": ("engagement", "deadline"),
    "deliverables": ("engagement", "deliverables"),
    "decision_makers": ("buyer", "decision_makers"),
    "brand_notes": ("buyer", "brand_notes"),
    "agency_notes": ("buyer", "agency_notes"),
    "campaign_objective": ("direction", "campaign_objective"),
    "emotional_arc": ("direction", "emotional_arc"),
    "reference_playlist": ("direction", "reference_playlist"),
}


@router.post("/opportunity/{opp_id}/doc/ci-field")
def doc_ci_field(opp_id: int, name: str = Form(""), value: str = Form("")):
    """Apply a brief edit to Campaign Intelligence itself (ADR-0017)."""
    if name in _BRIEF_CI_FIELDS and campaigns.workspace_enabled():
        conn = db.connect()
        try:
            row = db.get_opportunity(conn, opp_id)
            if row is None:
                return HTMLResponse("Opportunity not found", status_code=404)
            ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
            facet, key = _BRIEF_CI_FIELDS[name]
            campaign_intelligence.edit_or_create(
                conn, ci_row["id"], facet, key, "fact", value, actor="operator")
        finally:
            conn.close()
    return _doc_redirect(opp_id)


@router.post("/opportunity/{opp_id}/doc/chip")
def doc_chip(
    opp_id: int, section: str = Form(""), action: str = Form(""),
    label: str = Form(""), sentence: str = Form(""),
):
    """Add/remove a support chip in one section's ``support_chips`` list."""
    section = (section or "").strip()
    if section and action in ("add", "remove"):
        conn = db.connect()
        try:
            overrides = db.get_doc_overrides(conn, opp_id)
            chips = dict(overrides.get("support_chips") or {})
            current = list(chips.get(section) or [])
            if action == "add" and (label.strip() or sentence.strip()):
                current.append({"label": label.strip(), "sentence": sentence.strip()})
            elif action == "remove":
                current = [
                    c for c in current
                    if not (c.get("label") == label and c.get("sentence") == sentence)
                ]
            if current:
                chips[section] = current
            else:
                chips.pop(section, None)
            db.update_doc_override(conn, opp_id, "support_chips", chips or None)
        finally:
            conn.close()
    return _doc_redirect(opp_id)


@router.post("/opportunity/{opp_id}/doc/link")
def doc_link(
    opp_id: int, action: str = Form(""), label: str = Form(""), url: str = Form(""),
):
    """Add/remove a hand-picked relevant-work link ({label, url})."""
    if action in ("add", "remove"):
        conn = db.connect()
        try:
            overrides = db.get_doc_overrides(conn, opp_id)
            links = list(overrides.get("relevant_links") or [])
            if action == "add" and url.strip():
                links.append({"label": label.strip() or url.strip(), "url": url.strip()})
            elif action == "remove":
                links = [l for l in links if l.get("url") != url]
            db.update_doc_override(conn, opp_id, "relevant_links", links or None)
        finally:
            conn.close()
    return _doc_redirect(opp_id)


@router.post("/opportunity/{opp_id}/doc/pill")
def doc_pill(
    opp_id: int, section: str = Form(""), action: str = Form(""), label: str = Form(""),
):
    """Hide/restore an auto-generated pill (discipline, music need, team role) per
    deal. Hidden labels live in ``overrides['hidden_pills'][section]``; the builder
    leaves the generated pills intact, the template just skips the hidden ones, so a
    'show' fully restores it."""
    section = (section or "").strip()
    label = (label or "").strip()
    if section and label and action in ("hide", "show"):
        conn = db.connect()
        try:
            overrides = db.get_doc_overrides(conn, opp_id)
            hidden = dict(overrides.get("hidden_pills") or {})
            current = list(hidden.get(section) or [])
            if action == "hide" and label not in current:
                current.append(label)
            elif action == "show":
                current = [x for x in current if x != label]
            if current:
                hidden[section] = current
            else:
                hidden.pop(section, None)
            db.update_doc_override(conn, opp_id, "hidden_pills", hidden or None)
        finally:
            conn.close()
    return _doc_redirect(opp_id)


@router.post("/opportunity/{opp_id}/doc/upload")
async def doc_upload(
    opp_id: int,
    request: Request,
    label: str = Form(""),
    action: str = Form("add"),
    filename: str = Form(""),
    return_to: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """Upload (or remove) a founder audio sample for the Relevant-work section.

    Add: validates the file is audio (by extension or content-type), saves it under
    a safe unique name in upload_dir(), and appends {label, url, filename} to
    ``overrides["relevant_uploads"]``. Remove: drops the entry and unlinks the file
    best-effort.

    PERSISTENCE CAVEAT: see the note above — local disk is not durable on Render's
    zero-downtime deploys; durable storage needs S3/R2.
    """
    conn = db.connect()
    try:
        if action == "remove" and filename.strip():
            base = os.path.basename(filename.strip())
            overrides = db.get_doc_overrides(conn, opp_id)
            uploads = [
                u for u in list(overrides.get("relevant_uploads") or [])
                if u.get("filename") != base
            ]
            db.update_doc_override(conn, opp_id, "relevant_uploads", uploads or None)
            try:    # best-effort unlink; never fail the request on a missing file
                os.remove(os.path.join(upload_dir(), base))
            except OSError:
                pass
            return _doc_back(opp_id, return_to)

        if file is None or not (file.filename or "").strip():
            return _doc_back(opp_id, return_to)

        ext = os.path.splitext(file.filename)[1].lower()
        ctype = (file.content_type or "").lower()
        is_audio = ext in _AUDIO_EXTS or ctype.startswith("audio/")
        if not is_audio:
            return PlainTextResponse(
                "Only audio files are accepted (.mp3, .wav, .m4a, .aac, .ogg, .flac).",
                status_code=400,
            )
        if ext not in _AUDIO_EXTS:
            ext = ".mp3"   # audio/* with an odd extension → store under a known one

        data = await file.read()
        # Safe, unique on-disk name: opp-scoped + a counter so re-uploads don't clash.
        existing = {
            u.get("filename")
            for u in (db.get_doc_overrides(conn, opp_id).get("relevant_uploads") or [])
        }
        # ADR-0043: uniqueness is asked of the STORE, not of the local filesystem —
        # with a bucket configured there is no local file to collide with.
        _store = get_object_store(upload_dir())
        n = 1
        while f"opp{opp_id}-{n}{ext}" in existing or _store.exists(f"opp{opp_id}-{n}{ext}"):
            n += 1
        safe_name = f"opp{opp_id}-{n}{ext}"
        # This route wrote straight to disk too; the client-facing brief's audio had
        # exactly one copy.
        _persist_upload(conn, safe_name, data)

        overrides = db.get_doc_overrides(conn, opp_id)
        uploads = list(overrides.get("relevant_uploads") or [])
        uploads.append({
            "label": label.strip() or file.filename,
            "url": f"/uploads/{safe_name}",
            "filename": safe_name,
        })
        db.update_doc_override(conn, opp_id, "relevant_uploads", uploads)
    finally:
        conn.close()
    return _doc_back(opp_id, return_to)


@router.post("/opportunity/{opp_id}/project")
def create_project(opp_id: int):
    conn = db.connect()
    try:
        if db.get_opportunity(conn, opp_id) is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        pid = _ensure_project_for_opp(conn, opp_id)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{pid}", status_code=303)
