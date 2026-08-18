"""The client workspace — one token-gated URL that never changes.

ADR-0044, slice 10. Five routes behind the deal's ``share_token`` (ADR-0018): the
workspace itself, the client's scope confirmation, the court-state poll, and the two
approval doors. No admin session is involved; `_WORKSPACE_RE` exempts these paths from
the gate, because the whole point of the durable link is that the client opens it without
an account.

One contiguous span, no interleaved routes, three helpers used by nothing else.

This is the surface where the client's own action drives state: approving the Commercial
Review is the **award trigger** that creates the project. The operator's buttons elsewhere
are the fallback, not the primary path — so the writes here are the ones that most need to
behave identically after a move, which is what the equivalence run checks.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import mailer, signing
from ..capabilities import (
    attach_agreement, build_capabilities_doc, default_toggles,
    quote_band as capabilities_quote_band,
)
from ..proposals import build_proposal
from . import (
    campaign_intelligence, campaigns, commercial, db, kickoff, meeting_scheduler,
    production, workspace,
)
from .delivery_ops import _approve_version_core
from .estimate import estimate_for
from .opportunity_ops import (
    _brief_ci_context, _ensure_project_for_opp, _estimate_for_row, _load,
    _reconcile_opp_status,
)
from .shell import public_base as _public_base, render

router = APIRouter(tags=["workspace"])


# ── The Client Workspace (ADR-0018) — the ONE durable client destination. ─────────────
def _workspace_signals(conn, opp, project):
    """Gather the phase signals for one deal (ADR-0018). Pure DB reads; the mapping to a
    phase lives in ``workspace.compute_phase`` so it stays trivially testable. Signals for
    phases not yet built (commercial/kickoff) are simply absent."""
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    opp_id = opp["id"]
    met = False
    upcoming = False
    for m in db.list_meetings(conn, opp_id):
        if m["status"] == "canceled":
            continue
        if m["status"] in ("ingested", "transcript_ready") or (
                (m["start_at"] or "") and m["start_at"] <= now_iso):
            met = True
        elif (m["start_at"] or "") and m["start_at"] > now_iso:
            upcoming = True
    if any(p["status"] in ("draft", "sent")
           for p in db.list_meeting_proposals(conn, opp_id)):
        upcoming = True
    # Brief-ready means a client-facing brief moment has actually occurred — discovery
    # happened, or the brief was sent. NOT merely "CI has content": CI is auto-seeded
    # from the opportunity's own fields at creation, so that would flip every new deal to
    # the Brief phase before any discovery (ADR-0018 — honest phase signals).
    brief_ready = met or db.latest_brief_snapshot(conn, opp_id) is not None
    delivered = bool(project) and (project["status"] or "").lower() in ("delivered", "complete")
    # Commercial: released (operator opened the offer) → COMMERCIAL; approved → KICKOFF.
    review = db.current_commercial_review(conn, opp_id)
    kickoff_complete = bool(project) and bool(
        project["kickoff_completed_at"] if "kickoff_completed_at" in project.keys() else None)
    # ADR-0020: the client's scope confirmation ("yes, this reflects our project") advances
    # the workspace into the commercial phase — shown as "preparing your proposal" until the
    # operator releases it.
    scope_confirmed = bool(db.get_doc_overrides(conn, opp_id).get("scope_confirmed"))
    return {
        "has_project": project is not None,
        "delivered": delivered,
        "kickoff_complete": kickoff_complete,
        "commercial_approved": bool(review) and review["status"] == "approved",
        "commercial_ready": (bool(review) and review["status"] == "released")
                            or scope_confirmed,
        "brief_ready": brief_ready,
        "in_discovery": upcoming and not brief_ready,
    }


@router.get("/workspace/{token}", response_class=HTMLResponse)
def client_workspace(request: Request, token: str):
    """The Client Workspace: one durable, token-gated URL that never changes; its contents
    are the current lifecycle phase (ADR-0018). The token resolves the opportunity (its
    project inherits the same token), we compute the phase, and render the shell with the
    active stage's continuation. Existing token-gated surfaces (brief, delivery portal) are
    linked from here today; later phases fold them inline under this same URL."""
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            proj = db.project_by_share_token(conn, token)
            opp = db.get_opportunity(conn, proj["opp_id"]) if proj and proj["opp_id"] else None
        if opp is None:
            return HTMLResponse("Not found", status_code=404)
        project = db.project_for_opp(conn, opp["id"])
        # Self-heal: an awarded deal with no stored proposal (approved before the deposit
        # was wired, or via a path that skipped it) gets one now from the approved review,
        # so the deposit reliably surfaces — Pay button + Kickoff readiness.
        if project is not None and db.proposal_for_project(conn, project["id"]) is None:
            _ensure_proposal_from_review(
                conn, opp, project["id"], db.current_commercial_review(conn, opp["id"]))
        phase = workspace.compute_phase(_workspace_signals(conn, opp, project))
        # Deposit status, computed once up front. The deposit is due the moment the client
        # approves the Commercial Review (that's when the project + its Deposit invoice exist),
        # and it GATES Kickoff: production readiness stays locked until the deposit is in
        # (reported live: "as they approve, that should be the time to pay the deposit … the
        # deposit needs to be completed to initiate kickoff").
        _dep_prop = db.proposal_for_project(conn, project["id"]) if project is not None else None
        _dep_inv = (next((i for i in db.list_invoices(conn, project["id"])
                          if (i["kind"] or "") == "Deposit"), None)
                    if project is not None else None)
        deposit_paid = (_dep_inv is not None
                        and (_dep_inv["status"] or "").lower() in ("paid", "settled"))
        # The Campaign Brief folds INLINE into the workspace (ADR-0018) — one URL, no jump.
        # Other phases still link to their existing surface until they're folded in turn
        # (intro/discovery → scheduling; production/delivery → the portal, folded in P5).
        brief_ctx = None
        review = None
        readiness = None
        approved_note = ""
        preparing = False
        scope_confirm_url = ""
        proposal_signed = db.latest_opportunity_signature(
            conn, opp["id"], signing.DOC_PROPOSAL) is not None
        if phase == workspace.BRIEF:
            brief_ctx = _live_brief_ctx(conn, opp["id"])
            # ADR-0020: the Summary's one action — "yes, this reflects our project".
            if not db.get_doc_overrides(conn, opp["id"]).get("scope_confirmed"):
                scope_confirm_url = f"/workspace/{token}/confirm-scope"
        elif phase == workspace.COMMERCIAL:
            # The frozen Commercial Review — the agreement the client approves; before the
            # operator releases it, the phase reads "we're preparing your proposal".
            cr = db.current_commercial_review(conn, opp["id"])
            if cr is not None and cr["status"] in ("released", "approved"):
                review = commercial.review_from_json(cr["doc_json"])
            elif proposal_signed:
                # They signed the summary-as-proposal (ADR-0065). Signing sets
                # `scope_confirmed`, which advances the phase out of BRIEF — so without
                # this the client pressed "Sign and accept" and watched the document they
                # had just signed disappear, replaced by "we're preparing your proposal"
                # for a proposal they had already accepted. The signed document stays on
                # screen, and its own Agreement block now shows the signature.
                brief_ctx = _live_brief_ctx(conn, opp["id"])
            else:
                preparing = True
        elif phase == workspace.KICKOFF:
            # The Production Readiness Workspace — the concierge handoff. The deposit is the
            # first readiness gate here ("Send your deposit"); production doesn't start until
            # it's in (enforced on the operator's Start Production action).
            cr = db.current_commercial_review(conn, opp["id"])
            ci_view, _met = _brief_ci_context(conn, opp)
            readiness = kickoff.build_readiness(conn, db, opp, project, cr, ci_view=ci_view)
        prod = None
        if phase in (workspace.PRODUCTION, workspace.DELIVERY) and project is not None:
            # ADR-0019: production answers the court question first — whose move is it —
            # then shows the creative journey. The portal stays the listening room.
            delivery_blob = db.get_delivery(conn, project["id"])
            prod = {
                "court": production.court_state(project, delivery_blob),
                "journey": production.creative_journey(delivery_blob),
                "portal_url": f"/project/{project['id']}/delivery-portal?k={token}",
                "approve_url": f"/workspace/{token}/approve-version",
            }
        stage_url = ""
        if (brief_ctx is None and review is None and readiness is None and prod is None
                and not preparing):
            stage_url = {
                workspace.INTRO: f"/opportunity/{opp['id']}/request?k={token}",
                workspace.DISCOVERY: f"/opportunity/{opp['id']}/request?k={token}",
            }.get(phase, "")
            if not stage_url and project is not None:
                stage_url = f"/project/{project['id']}/delivery-portal?k={token}"
        # Client-facing DEPOSIT payment: once there's a project (awarded), surface the
        # deposit due + a Pay button until it's paid. Uses the project share token so the
        # token-gated /pay route authorizes it.
        deposit_pay = None
        if project is not None:
            dep_amount = (_dep_inv["amount"] if _dep_inv is not None
                          else (_dep_prop["deposit_amount"] if _dep_prop is not None else 0)) or 0
            if _dep_prop is not None and dep_amount and not deposit_paid:
                deposit_pay = {"amount": dep_amount, "pid": project["id"],
                               "ptok": db.ensure_project_share_token(conn, project["id"])}
    finally:
        conn.close()
    # The client can approve only a released (not-yet-approved) review.
    approve_url = (f"/workspace/{token}/approve"
                   if review is not None and not approved_note else "")
    return render(request, "workspace.html", nav="", token=token, opp=opp,
                  project=project, phase=phase, phase_label=workspace.PHASE_LABEL[phase],
                  phase_blurb=workspace.PHASE_BLURB[phase], rail=workspace.rail(phase),
                  stage_url=stage_url, review=review, approve_url=approve_url,
                  approved_note=approved_note, k=readiness, prod=prod,
                  preparing=preparing, scope_confirm_url=scope_confirm_url,
                  proposal_signed=proposal_signed,
                  back_url=f"/opportunity/{opp['id']}/capabilities?k={token}",
                  deposit_pay=deposit_pay,
                  **(brief_ctx or {}))


@router.post("/workspace/{token}/confirm-scope")
def workspace_confirm_scope(request: Request, token: str, confirmed_by: str = Form(""),
                            comment: str = Form(""), decision: str = Form("yes")):
    """ADR-0020: the Discovery Summary has two answers — "yes, this reflects our project"
    (alignment, not commitment: advances to "preparing your proposal" and notifies the
    operator to release it) or "no, something's off" (captures the client's corrections,
    notifies the operator, and does NOT advance — the operator edits the summary and
    re-shares). Reported live: the box only offered "Yes"."""
    from datetime import datetime, timezone
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            return HTMLResponse("Not found", status_code=404)
        if decision.strip().lower() == "no":
            # Something's off — record the correction, ping the operator, don't advance.
            note = comment.strip()[:500]
            db.update_doc_override(conn, opp["id"], "scope_correction", {
                "at": datetime.now(timezone.utc).isoformat(),
                "by": confirmed_by.strip(), "comment": note, "resolved": False})
            if campaigns.workspace_enabled():
                try:
                    ci = campaign_intelligence.ensure_for_opportunity(conn, opp)
                    db.add_ci_event(conn, ci["id"], actor="client", verb="scope_correction",
                                    facet="engagement", key="discovery_summary",
                                    to_value=(note[:200] or "flagged for correction"),
                                    source="workspace")
                except Exception:  # noqa: BLE001
                    pass
            op_mail = meeting_scheduler._operator_email()
            if op_mail:
                try:
                    mailer.send_email(
                        op_mail, f"⚠ Client flagged the summary — {opp['client']}",
                        f"{confirmed_by.strip() or 'The client'} says the Discovery Summary "
                        f"for {opp['need']} needs a fix."
                        + (f"\nTheir note: “{note}”" if note else "")
                        + f"\n\nEdit the summary, then re-share:\n"
                          f"{_public_base()}/opportunity/{opp['id']}/capabilities?edit=1")
                except Exception:  # noqa: BLE001
                    pass
            return RedirectResponse(f"/workspace/{token}?flag=corrections", status_code=303)
        if not db.get_doc_overrides(conn, opp["id"]).get("scope_confirmed"):
            db.update_doc_override(conn, opp["id"], "scope_confirmed", {
                "at": datetime.now(timezone.utc).isoformat(),
                "by": confirmed_by.strip(), "comment": comment.strip()[:500]})
            _reconcile_opp_status(conn, opp["id"])   # → Reaching out
            if campaigns.workspace_enabled():
                try:
                    ci = campaign_intelligence.ensure_for_opportunity(conn, opp)
                    db.add_ci_event(conn, ci["id"], actor="client", verb="scope_confirmed",
                                    facet="engagement", key="discovery_summary",
                                    to_value=(comment.strip()[:200] or "confirmed"),
                                    source="workspace")
                except Exception:  # noqa: BLE001
                    pass
            op_mail = meeting_scheduler._operator_email()
            if op_mail:
                try:
                    mailer.send_email(
                        op_mail, f"✓ Scope confirmed — {opp['client']}",
                        f"The client confirmed the Discovery Summary for {opp['need']}."
                        + (f"\nTheir note: \u201c{comment.strip()}\u201d" if comment.strip() else "")
                        + f"\n\nNext: review and release the proposal.\n"
                          f"{_public_base()}/opportunity/{opp['id']}/commercial")
                except Exception:  # noqa: BLE001
                    pass
    finally:
        conn.close()
    return RedirectResponse(f"/workspace/{token}", status_code=303)


@router.post("/workspace/{token}/sign")
def workspace_sign_proposal(request: Request, token: str, typed_name: str = Form(""),
                            signer_email: str = Form(""), consent: str = Form(""),
                            drawn_signature: str = Form("")):
    """The client accepts the Discovery Summary & Proposal (ADR-0065).

    This is the deal's ONE commercial commitment (ADR-0020's rule, kept), and it is a real
    signature rather than a typed name in a JSON blob: the digest is taken over
    ``agreement.signable_text()`` rebuilt HERE, from the live document, so what is stored
    is provably what the page showed. If a term moves afterwards, `signing.verify` reports
    SUPERSEDED instead of showing a signature that no longer covers anything.

    It does not award the deal. A client signature is the client's half; "the machine
    proposes, Jon disposes" means the project is still spun up by a human, so this records
    the commitment, tells the operator, and puts countersigning in their court.
    """
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            return HTMLResponse("Not found", status_code=404)
        opp_id = opp["id"]
        # Consent is required by the form and re-checked here: a POST that skipped the
        # browser has skipped the one element that makes an electronic signature valid.
        if not consent.strip() or not typed_name.strip():
            return RedirectResponse(f"/workspace/{token}?flag=sign-incomplete#agreement",
                                    status_code=303)
        ctx = _live_brief_ctx(conn, opp_id)
        doc = (ctx or {}).get("doc")
        agr = getattr(doc, "agreement", None) if doc is not None else None
        # A signature already covering THIS text → nothing to do. A double submit or a
        # refresh must not stack a duplicate onto an append-only table.
        #
        # But a signature covering an OLDER text must not block the new one. The whole
        # correction flow ends here: the client flags something, the summary is fixed,
        # and they come back to accept the fix. Refusing on "already signed" left them
        # looking at a superseded signature with no way forward, and the deal stuck.
        # The old row stays — the record is that they signed v1 and then v2.
        prior = db.latest_opportunity_signature(conn, opp_id, signing.DOC_PROPOSAL)
        if prior is not None and agr is not None and signing.verify(
                prior["digest"], agr.signable_text()) == signing.VALID:
            return RedirectResponse(f"/workspace/{token}#agreement", status_code=303)
        if agr is None:
            # No price, no terms → nothing to agree to. Refusing is the point: a
            # signature collected here would look like a commitment to a number that
            # was never named.
            return RedirectResponse(f"/workspace/{token}?flag=not-signable", status_code=303)
        sig = signing.build_signature(
            doc_kind=signing.DOC_PROPOSAL,
            opportunity_id=opp_id,
            document_text=agr.signable_text(),
            signer_name=typed_name.strip(),
            signer_email=signer_email.strip(),
            typed_name=typed_name.strip(),
            ip=(request.client.host if request.client else ""),
            user_agent=request.headers.get("user-agent", ""),
            token=token,
            # Validated, never trusted: `clean_drawn_mark` drops anything that is not a
            # real base64 PNG rather than storing it, because this value is rendered back
            # into an <img src> for every later reader of the document.
            drawn_mark=drawn_signature,
            terms_snapshot={"fee": agr.fee_line, "scope": agr.scope,
                            "timeline": agr.timeline, "deposit": agr.deposit,
                            "terms": list(agr.terms)},
        )
        db.record_signature(conn, sig)
        # The existing scope-confirmation state, so every surface that already reads it
        # (the workspace phase, the next action, the operator's board) keeps working. A
        # signature is a STRONGER confirmation, not a different one — and writing only the
        # new record would have quietly regressed all of them to "waiting on the client".
        if not db.get_doc_overrides(conn, opp_id).get("scope_confirmed"):
            db.update_doc_override(conn, opp_id, "scope_confirmed", {
                "at": sig.signed_at, "by": sig.typed_name, "comment": "",
                "signed": True})
        db.update_doc_override(conn, opp_id, "proposal_signed", {
            "at": sig.signed_at, "by": sig.typed_name, "email": sig.signer_email,
            "digest": sig.digest})
        _reconcile_opp_status(conn, opp_id)
        if campaigns.workspace_enabled():
            try:
                ci = campaign_intelligence.ensure_for_opportunity(conn, opp)
                db.add_ci_event(conn, ci["id"], actor="client", verb="proposal_signed",
                                facet="engagement", key="discovery_summary",
                                to_value=f"signed by {sig.typed_name}", source="workspace")
            except Exception:  # noqa: BLE001
                pass
        # Both notifications carry THE DOCUMENT, not a summary of it. A mail saying only
        # "signed, fee $12,500" is a receipt for a contract nobody attached: the operator
        # asked "where is the signed document" the first time this fired, and the client
        # is entitled under ESIGN/UETA to retain what she agreed to rather than have to
        # go back to a link for it.
        document = agr.signable_text()
        signed_block = (
            f"\n\n{'=' * 58}\nSIGNED COPY — the exact text this signature covers\n"
            f"{'=' * 58}\n{document}\n{'=' * 58}\n"
            f"Signed by: {sig.typed_name}"
            + (f" <{sig.signer_email}>" if sig.signer_email else "")
            + f"\nSigned at: {sig.signed_at}\n"
            f"Consent given: {sig.consent_text}\n"
            f"Document digest (SHA-256): {sig.digest}\n")
        op_mail = meeting_scheduler._operator_email()
        if op_mail:
            try:
                mailer.send_email(
                    op_mail, f"✍ Proposal SIGNED — {opp['client']}",
                    f"{sig.typed_name} signed the Discovery Summary & Proposal for "
                    f"{opp['need']}.\n"
                    f"Fee: {agr.fee_line or '—'}\n\n"
                    f"Next: countersign, then start production.\n"
                    f"{_public_base()}/opportunity/{opp_id}#agreement"
                    + signed_block)
            except Exception:  # noqa: BLE001
                pass
        # The signer's own copy. Retention is a requirement of the legal shape this
        # module claims (ESIGN/UETA), and "it is on the web page" is a weaker answer than
        # a copy in their inbox on the day they signed.
        if sig.signer_email:
            try:
                mailer.send_email(
                    sig.signer_email,
                    f"Your signed copy — {opp['client']} · {opp['need']}",
                    f"Thank you. Below is the agreement exactly as you signed it, for "
                    f"your records.\n\nWe countersign and raise the deposit invoice; work "
                    f"begins when the deposit clears. Your workspace stays at "
                    f"{_public_base()}/workspace/{token}"
                    + signed_block)
            except Exception:  # noqa: BLE001
                pass
    finally:
        conn.close()
    return RedirectResponse(f"/workspace/{token}#agreement", status_code=303)


@router.get("/workspace/{token}/court.json")
def workspace_court_signature(token: str):
    """A cheap signature of the deal's current state so the client's Workspace can quietly
    refresh itself the moment something changes (a version lands, an approval fires) — no more
    manual reload. Motion communicates state; nothing reloads unless the state actually moved."""
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        project = db.project_for_opp(conn, opp["id"])
        # A cheap signature: award state + delivery state + version count + pending flag +
        # scope-confirm + review status. Any client-visible transition changes it.
        parts = [opp["status"] or "", "proj" if project else "noproj"]
        review = db.current_commercial_review(conn, opp["id"])
        parts.append((review["status"] if review else "") or "")
        parts.append("sc" if db.get_doc_overrides(conn, opp["id"]).get("scope_confirmed") else "")
        if project is not None:
            d = db.get_delivery(conn, project["id"])
            parts += [d.get("state", "") or "", str(len(d.get("versions") or [])),
                      "p" if d.get("pending_version") else ""]
        sig = ":".join(parts)
    finally:
        conn.close()
    return {"sig": sig}


@router.post("/workspace/{token}/approve-version")
def workspace_approve_version(request: Request, token: str, approver_name: str = Form("")):
    """The client approves the current version straight from their Workspace — the "it's
    perfect, no changes" path (operator feedback). The durable workspace token IS the client's
    identity + access; a typed name captures intent (ESIGN/UETA-sufficient). Records the
    sign-off, locks the creative, and drives delivery — the same core the reviewer route uses."""
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            return HTMLResponse("Not found", status_code=404)
        project = db.project_for_opp(conn, opp["id"])
        if project is None:
            return RedirectResponse(f"/workspace/{token}", status_code=303)
        delivery = db.get_delivery(conn, project["id"])
        # Only meaningful when a version is actually waiting on the client.
        if delivery.get("state") == "In review" and production.court_state(project, delivery)["court"] == "client":
            name = (approver_name.strip() or opp["contact_name"] or "The client").strip()
            mail = (opp["contact_email"] or "").strip()
            _approve_version_core(conn, project["id"], name, mail)
    finally:
        conn.close()
    return RedirectResponse(f"/workspace/{token}", status_code=303)


@router.post("/workspace/{token}/approve")
def workspace_approve(request: Request, token: str, approver_name: str = Form(""),
                      approver_email: str = Form(""), scope_ok: str = Form(""),
                      pricing_ok: str = Form(""), terms_ok: str = Form(""),
                      timeline_ok: str = Form("")):
    """The client approves the released Commercial Review — the primary award trigger
    (ADR-0018). Captures the electronic-approval audit record bound to the FROZEN version,
    marks the review approved, and advances the workspace into Kickoff. Phase 3 enriches
    the audit + adds the optional DocuSign path."""
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            proj = db.project_by_share_token(conn, token)
            opp = db.get_opportunity(conn, proj["opp_id"]) if proj and proj["opp_id"] else None
        if opp is None:
            return HTMLResponse("Not found", status_code=404)
        review = db.current_commercial_review(conn, opp["id"])
        if review is not None and review["status"] == "released":
            db.create_commercial_approval(
                conn, opp_id=opp["id"], review_id=review["id"],
                approver_name=approver_name.strip(), approver_email=approver_email.strip(),
                ip=(request.client.host if request.client else ""),
                user_agent=request.headers.get("user-agent", ""),
                scope_ok=bool(scope_ok), pricing_ok=bool(pricing_ok), terms_ok=bool(terms_ok),
                timeline_ok=bool(timeline_ok))
            # Email is the notification layer (ADR-0020): tell the operator the award landed.
            op_mail = meeting_scheduler._operator_email()
            if op_mail:
                try:
                    mailer.send_email(
                        op_mail, f"✓ Proposal approved — {opp['client']}",
                        f"{approver_name.strip() or 'The client'} approved the proposal for "
                        f"{opp['need']}. The workspace has advanced to Kickoff.\n"
                        f"{_public_base()}/opportunity/{opp['id']}")
                except Exception:  # noqa: BLE001
                    pass
            db.set_commercial_review_status(conn, review["id"], "approved")
            # ADR-0018: the client's approval is the primary AWARD TRIGGER — it creates the
            # project (in Kickoff), so the Sales→Production handoff has something real to
            # organize (team, milestones, invoices). The machine prepares; the client
            # committed; the operator confirms Start Production to enter Production.
            pid = _ensure_project_for_opp(conn, opp["id"])
            # Persist a proposal carrying the APPROVED deposit/balance so the deposit is real
            # everywhere downstream — the workspace Pay button, the /pay invoice, and the
            # Kickoff readiness (reported live: Kickoff showed "Everything is ready" with no
            # way to pay the deposit, because no proposal → no deposit amount existed).
            if pid is not None:
                _ensure_proposal_from_review(
                    conn, opp, pid, db.current_commercial_review(conn, opp["id"]))
            _reconcile_opp_status(conn, opp["id"])   # → Won (approval is the award)
            if campaigns.workspace_enabled():
                try:
                    ci = campaign_intelligence.ensure_for_opportunity(conn, opp)
                    db.add_ci_event(conn, ci["id"], actor="client", verb="commercial_approved",
                                    facet="commercial", key="review",
                                    to_value=f"v{review['version']} · {approver_name.strip()}",
                                    source="commercial")
                except Exception:  # noqa: BLE001
                    pass
    finally:
        conn.close()
    return RedirectResponse(f"/workspace/{token}", status_code=303)


def _live_brief_ctx(conn, opp_id):
    """The Campaign Brief render context, live from Campaign Intelligence, ready to embed in
    the Client Workspace (ADR-0018). Builds the SAME ``doc`` the standalone brief route builds
    (single source), in read-only/public/embedded mode — the workspace is the frame, so the
    brief's own threshold cover is suppressed and no operator edit affordances render."""
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None
    qual, _scored = ev
    # The SAME estimate the operator's surfaces resolve (ADR-0033/0065): with the deal's
    # project, so assigned rates are in play. This built its own without one, so the
    # document the CLIENT signed could quote a different fee from the deal page the
    # operator was reading — the divergence being signed rather than merely displayed.
    est = _estimate_for_row(conn, row, opp, qual)
    overrides = db.get_doc_overrides(conn, opp_id)
    ci_view, met = _brief_ci_context(conn, row)
    toggles = default_toggles(row["status"], met=met)
    # ADR-0065 supersedes ADR-0020 on THIS point only. ADR-0020 held that the Discovery
    # Summary carries no pricing and no terms, and that the commercial conversation
    # happens later at a released proposal. Its underlying rule — the deal has exactly ONE
    # commercial commitment — is untouched and in fact better served: the client used to
    # be asked twice (confirm the summary, then approve a proposal), and now commits once,
    # by signing. What changes is only WHICH document carries the close.
    #
    # The half of ADR-0020 that was right survives as the `met` gate: before the call
    # there is no scoping, so there is no honest number, so the summary still shows none.
    if not met:
        toggles.update({"cost": False, "terms": False})
    # The "book a discovery call" CTA belongs BEFORE discovery. Once it's happened (met),
    # this IS the summary of that call — re-inviting them to book one is contradictory.
    # Reported live: "it's still auto attaching the discovery call CTA when that already
    # happened." Suppress the CTA post-discovery; the summary's only action is the confirm box.
    call_url = "" if met else os.environ.get("CHORDENTIAL_DISCOVERY_CALL_URL", "").strip()
    doc = build_capabilities_doc(
        opp, qual, est, toggles=toggles, overrides=overrides,
        call_url=call_url, ci_view=ci_view, met=met)
    project = db.project_for_opp(conn, opp_id)
    # ADR-0034: a fraction of the band the client is shown, not of the estimate.
    # ci_view/overrides are already loaded here — no extra query on a client page.
    deposit_amount = build_proposal(
        opp, qual, est,
        quote_band=capabilities_quote_band(
            opp, est, ci_fields=(ci_view or {}).get("fields") or {},
            commercial_overrides=(overrides or {}).get("commercial")),
    ).deposit_amount
    deposit_invoice_id = None
    if project is not None:
        sp = db.proposal_for_project(conn, project["id"])
        if sp is not None and sp["deposit_amount"]:
            deposit_amount = sp["deposit_amount"]
        for inv in db.list_invoices(conn, project["id"]):
            if inv["kind"] == "Deposit":
                deposit_invoice_id = inv["id"]
                break
    token = db.ensure_share_token(conn, opp_id)
    # Re-derive the agreement now that the real deposit figure is known, so the text the
    # client signs names the actual number instead of the prose fallback. Deterministic —
    # `deposit_amount` comes from the same quote band the page shows — which is what lets
    # the sign route rebuild this identically and get the same digest.
    attach_agreement(doc, deposit_amount=deposit_amount)
    sig = db.latest_opportunity_signature(conn, opp_id, signing.DOC_PROPOSAL)
    sig_state = signing.verify(
        sig["digest"] if sig is not None else "",
        doc.agreement.signable_text() if doc.agreement else None)
    return {
        "row": row, "doc": doc, "overrides": overrides,
        "request_url": f"/opportunity/{opp_id}/request?k={token}",
        "deposit_amount": deposit_amount, "deposit_invoice_id": deposit_invoice_id,
        "edit": False, "public": True, "embedded": True,
        # The client's own copy is the ONE place the signature block is live. It stays
        # live when the existing signature is SUPERSEDED: a corrected document is a
        # different document, and the client must be able to sign the new one. Without
        # this a client who signed, was sent a fix, and came back to accept it found her
        # old signature marked superseded and NO WAY TO SIGN — the one path the
        # correction flow exists to reach.
        "sign_url": (f"/workspace/{token}/sign"
                     if doc.show_agreement and sig_state != signing.VALID else ""),
        "proposal_signature": sig,
        "proposal_signature_mark": (
            (sig["drawn_mark"] if "drawn_mark" in sig.keys() else "") if sig is not None
            else ""),
        "proposal_signature_superseded": (sig is not None
                                          and sig_state == signing.SUPERSEDED),
        "proposal_signature_note": signing.verdict_note(
            sig_state, dict(sig) if sig is not None else None),
        "chip_library": {}, "section_family": {}, "custom_chips": [], "delivery_templates": {},
    }


def _ensure_proposal_from_review(conn, opp_row, project_id, review_row) -> None:
    """After the client approves the Commercial Review, persist a Proposal for the project
    carrying the APPROVED money (deposit, balance, total — operator edits included) so the
    deposit is real everywhere downstream: the workspace Pay button, the /pay invoice, and
    the Kickoff readiness. Idempotent — a no-op if the project already has a proposal."""
    if review_row is None or db.proposal_for_project(conn, project_id) is not None:
        return
    review = commercial.review_from_json(review_row["doc_json"])
    if review is None:
        return
    row, opp, ev = _load(conn, opp_row["id"])
    if row is None:
        return
    qual, _scored = ev
    est = estimate_for(opp, qual=qual)
    proposal = build_proposal(opp, qual, est)
    # Override the estimator's numbers with exactly what the client approved.
    total_mid = int(round(((review.fee_low or 0) + (review.fee_high or 0)) / 2))
    if review.deposit_pct:
        proposal.deposit_pct = review.deposit_pct
    if review.deposit_amount:
        proposal.deposit_amount = review.deposit_amount
    if total_mid:
        proposal.total_price = total_mid
    proposal.balance_due = (review.balance_amount
                            or max(0, (total_mid or proposal.total_price) - proposal.deposit_amount))
    db.insert_proposal(conn, project_id, opp_row["id"], proposal)
