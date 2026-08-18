"""The creator portal — the composer's side of a project.

ADR-0044, slice 7. Six routes behind a per-creator ``portal_token``: the portal itself,
addressing and replying to a client note, a capture, a version submission and a scoped
deliverable. No admin session is involved, which is why `_CREATOR_PORTAL_RE` exempts
these paths from the gate; a composer who bounced to `/admin/login` on their own link
would simply be locked out of the work.

The cleanest extraction of the series, and only because the earlier ones did their job:
one contiguous block, **zero** interleaved routes, **zero** helpers shared with any other
group. Everything it still reached that another group also uses had already moved into
the helper layer in slices 4 and 6 (`uploads._read_capped`, `uploads._store_pending_submission`,
`delivery_ops._project_estimate`, `delivery_ops._sync_role_milestones`).

What the composer may do here is deliberately narrow. A submission lands in
``delivery_json['pending_version']`` and waits — Jon publishes it. The portal never
approves, never releases, never sets a price.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..delivery import (
    current_version, revision_status, scoped_deliverables, seed_brief, versions_list,
)
from .. import composer_agreement, signing
from ..talent import profile_completeness
from . import db, production
from .delivery_ops import (
    _campaign_label, _notify_operator_review, _project_estimate, _sync_role_milestones,
)
from .shell import render
from .uploads import (
    _AUDIO_EXTS, _CUT_MIRROR_BYTES, _persist_upload, _read_capped,
    _store_pending_submission,
)

router = APIRouter(tags=["creator"])


# A composer's submitted take / deliverable (audio-weight, occasionally a video mix)
# rides the same chunked cap — token-gated routes must never buffer an unbounded body.
_SUBMISSION_MAX_BYTES = int(os.environ.get("CHORDENTIAL_SUBMISSION_MAX_MB", "512")) * 1024 * 1024


# --------------------------------------------------------------------------- #
def _creator_feedback(conn, project_id: int, delivery: dict) -> dict:
    """The client's review feedback on the current version, shaped read-only for the
    composer's portal — so they see the timecoded notes and change requests directly
    instead of Jon hand-relaying them (the whole point of the timecode feature).
    Returns the actionable notes for the current version + the revision budget."""
    cur = current_version(delivery)
    cur_n = str(cur["n"]) if cur else "0"
    notes, by_id = [], {}
    rows = db.list_review_comments(conn, project_id)
    for c in rows:
        # Only the notes a composer acts on, and only for the version they're on now.
        if c["kind"] not in ("comment", "change_request", "asset_change"):
            continue
        if c["parent_id"]:
            continue                       # replies thread under their parent below
        if (c["version"] or "") != cur_n:
            continue
        keys = c.keys()
        n = {
            "id": c["id"], "t": c["t_seconds"],
            "t_end": (c["t_end"] if "t_end" in keys else None),
            "author": c["author"],
            "body": c["body"], "kind": c["kind"], "resolved": bool(c["resolved"]),
            "addressed": bool(c["composer_addressed"]
                              if "composer_addressed" in keys else 0),
            # Species (EP P1): a conform (re-sync to a new cut) is free — the
            # composer must SEE that per-note, not just in the banner.
            "conform": bool(c["conform"] if "conform" in keys else 0),
            "at": c["created_at"] or "",
            "replies": [],
        }
        notes.append(n); by_id[c["id"]] = n
    for c in rows:                          # thread replies (client, studio, composer)
        if c["parent_id"] and c["parent_id"] in by_id:
            keys = c.keys()
            by_id[c["parent_id"]]["replies"].append({
                "author": c["author"], "body": c["body"],
                "internal": bool(c["internal"] if "internal" in keys else 0),
            })
    # Scoped rounds come from the SAME source the console/portal read — the
    # estimate's revision multiplier via revision_status — not a phantom
    # ``revisions_included`` field that was never written (so the composer's
    # round sentence was always blank; EP review P0). One source, three doors.
    row = db.get_project(conn, project_id)
    est = _project_estimate(conn, row) if row is not None else None
    rs = revision_status(row, est, delivery) if row is not None else {}
    used = int(rs.get("used", delivery.get("revisions_used") or 0))
    scoped = int(rs.get("scoped") or 0) or None
    return {
        "notes": notes,
        # What's WAITING: every open human note the composer hasn't handled —
        # timeline comments AND formal change requests (asset_change is system
        # bookkeeping, excluded). The client-side recompute after "Mark addressed"
        # uses the identical rule, so the number is consistent from first paint
        # through every click (composer review P0: it read 0 on load with notes
        # waiting, then jumped once JS took over).
        "open_count": sum(1 for n in notes
                          if n["kind"] in ("comment", "change_request")
                          and not (n["resolved"] or n["addressed"])),
        "revisions_used": used,
        "revisions_included": scoped,
        # ONE round sentence across all three doors (EP P0-2) — identical formula
        # to the delivery portal/console chips.
        "round_phrase": (f"Round {min(used + 1, scoped)} of {scoped}"
                         if scoped else ""),
    }


def _rel_deadline(iso: str) -> str:
    """A deadline as the room speaks it — 'due in 11 days', not raw ISO."""
    try:
        from datetime import date as _d
        days = (_d.fromisoformat(str(iso).strip()[:10]) - _d.today()).days
    except (ValueError, TypeError):
        return str(iso or "")
    if days > 1:
        return f"due in {days} days"
    if days == 1:
        return "due tomorrow"
    if days == 0:
        return "due today"
    return f"{-days} day{'s' if days != -1 else ''} past due"


def _creator_assignment_view(conn, talent_id: int) -> list:
    """Per-assignment cards for the composer portal: brief, role, deadline, the
    delivery state, the versions THIS creator can submit/see, and the client's
    review feedback on the current version (read-only)."""
    out = []
    for a in db.list_talent_assignments(conn, talent_id):
        delivery = db.get_delivery(conn, a["project_id"])
        prow = db.get_project(conn, a["project_id"])
        # Once the client approves the master (creative lock), the composer's job shifts
        # from iterating the master to producing the DERIVATIVE deliverables (instrumental,
        # cutdowns, verticals, stems). Surface those so the portal can ask for them —
        # the master is the version ladder, so it's excluded here.
        locked = bool(production.creative_lock(delivery))
        # Scoped deliverables + specs are DAY-ONE knowledge (composer review P1-8:
        # "I bounce to spec from take one if you tell me on day one"), not a
        # post-approval surprise. Pending = submitted, with the studio (EP P0-3).
        pending_labels = {(a.get("label") or "").strip().lower()
                          for a in (delivery.get("pending_assets") or [])}
        deliverables = []
        if prow is not None:
            for d in scoped_deliverables(prow, delivery):
                if d.get("is_master"):
                    continue
                deliverables.append({
                    "asset": d["asset"], "group": d["group"],
                    "spec": d.get("spec", ""), "uploaded": bool(d.get("uploaded")),
                    "pending": (d["asset"] or "").strip().lower() in pending_labels,
                })
        out.append({
            "project_id": a["project_id"],
            "role": a["role"],
            "client": a["client"],
            "need": a["need"],
            "deadline": a["deadline"],
            "status": a["status"],
            "delivery_state": (delivery.get("state") or "Not started"),
            "version_state": (delivery.get("version_state") or ""),
            "versions": versions_list(delivery),
            # The creator's OWN latest submission, even while it's still pending Jon's
            # review — so they can see it landed instead of the empty "upload your first"
            # state (reported live: after submitting, the portal looked like nothing happened).
            "pending": delivery.get("pending_version") or None,
            "feedback": _creator_feedback(conn, a["project_id"], delivery),
            "creative_lock": locked,
            "deliverables": deliverables,
            # The room's Brief layer renders the REAL creative brief (the same
            # effective brief the console shows), not a restatement of the title.
            "brief": seed_brief(
                prow,
                db.get_opportunity(conn, prow["opp_id"])
                if prow is not None and prow["opp_id"] else None,
                delivery),
            "deadline_rel": _rel_deadline(a["deadline"]) if a["deadline"] else "",
            # Phase 2 — the picture + references + conform marking
            "picture": delivery.get("picture") or None,
            "references": list(delivery.get("references") or []),
            # Phase 3 — the Cue Layer: cue regions + hit diamonds on the spine.
            # Read-only for the composer (Jon owns the cue list); they score to it.
            "cues": db.get_cues(conn, a["project_id"]),
            # Phase 4 §13 — the private Capture shelf (composer + studio only).
            "captures": db.get_captures(conn, a["project_id"]),
        })
    # Needs-me-first (composer review P1): rooms owing the composer work come
    # before in-motion rooms; delivered rooms sink to the bottom.
    def _urgency(v):
        closed = v["delivery_state"] in ("Released", "Delivered")
        needs_me = (v["feedback"]["open_count"] > 0
                    or (not v["versions"] and not v["pending"] and not closed))
        return 2 if closed else (0 if needs_me else 1)
    out.sort(key=_urgency)
    return out


@router.get("/creator/{token}", response_class=HTMLResponse)
def creator_portal(request: Request, token: str, p: Optional[int] = None):
    """The composer's Session Room(s). ``?p=<project_id>`` is a room's own door
    (ADR-0025): one token, each engagement individually addressable; without it,
    every room stacks needs-first."""
    conn = db.connect()
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        t = db.talent_from_row(row)
        assignments = _creator_assignment_view(conn, row["id"])
    finally:
        conn.close()
    all_rooms = assignments
    if p is not None:
        assignments = [a for a in assignments if a["project_id"] == p] or all_rooms
    return render(
        request, "creator_portal.html", nav="", token=token, t=t,
        completeness=profile_completeness(t), assignments=assignments,
        all_rooms=all_rooms, focused=p,
    )


@router.get("/creator/{token}/agreement", response_class=HTMLResponse)
def creator_agreement(request: Request, token: str):
    """The Composer Agreement, for the writer to read and sign.

    On the composer's own token-gated portal, because that is where they already are and
    because the per-creator token IS the credential (same model as the client workspace).
    Nothing here is admin-gated; the route validates the token itself.
    """
    conn = db.connect()
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        agr = composer_agreement.build_agreement(row)
        sig = db.latest_talent_signature(conn, row["id"], signing.DOC_COMPOSER_AGREEMENT)
        counter = db.latest_talent_signature(
            conn, row["id"], signing.DOC_COMPOSER_COUNTERSIGN)
        composer_name = row["name"]
    finally:
        conn.close()
    text = agr.signable_text()
    state = signing.verify(sig["digest"] if sig is not None else "", text)
    return render(
        request, "composer_agreement.html", nav="", token=token,
        composer_name=composer_name,
        agreement=agr, agreement_text=text, signature=sig, countersignature=counter,
        signature_note=signing.verdict_note(state, dict(sig) if sig is not None else None),
        signature_valid=(state == signing.VALID),
        # Not signable without a governing law — the document says so rather than
        # collecting a signature on a cross-border assignment with no stated forum.
        sign_url=(f"/creator/{token}/agreement/sign"
                  if sig is None and composer_agreement.is_signable(agr) else ""),
        blocked_reason=composer_agreement.blocked_reason(agr),
        acceptance_text=composer_agreement.ACCEPTANCE_TEXT,
        acceptance_limits=composer_agreement.ACCEPTANCE_LIMITS,
        consent_text=signing.CONSENT_TEXT,
    )


@router.post("/creator/{token}/agreement/sign")
def creator_sign_agreement(request: Request, token: str, typed_name: str = Form(""),
                           signer_email: str = Form(""), consent: str = Form(""),
                           drawn_signature: str = Form("")):
    """The writer signs. This IS the assignment gate (ADR-0024).

    The gate used to turn on `agreement_executed_at`, a date an operator typed to say a
    document existed somewhere the system had never seen. Signing now stamps it — so the
    thing that unblocks assigning someone to paid work is the writer's own signature over
    a text we can still produce, not a memory of a conversation.
    """
    conn = db.connect()
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        talent_id = row["id"]
        if not consent.strip() or not typed_name.strip():
            return RedirectResponse(f"/creator/{token}/agreement?flag=incomplete",
                                    status_code=303)
        # Already signed → the existing one stands. Signing again is not an edit, and the
        # append-only table would otherwise grow a row per refresh.
        if db.latest_talent_signature(
                conn, talent_id, signing.DOC_COMPOSER_AGREEMENT) is not None:
            return RedirectResponse(f"/creator/{token}/agreement", status_code=303)
        agr = composer_agreement.build_agreement(row)
        if not composer_agreement.is_signable(agr):
            return RedirectResponse(f"/creator/{token}/agreement", status_code=303)
        try:
            sig = signing.build_signature(
                doc_kind=signing.DOC_COMPOSER_AGREEMENT,
                talent_id=talent_id,
                document_text=agr.signable_text(),
                signer_name=(row["name"] or "").strip(),
                signer_email=(signer_email.strip()
                              or (row["email"] if "email" in row.keys() else "") or ""),
                typed_name=typed_name.strip(),
                ip=(request.client.host if request.client else ""),
                user_agent=request.headers.get("user-agent", ""),
                token=token,
                drawn_mark=drawn_signature,
                certified_version=agr.version,
                terms_snapshot={"share_pct": agr.share_pct,
                                "share_with_session_pct": agr.share_with_session_pct,
                                "publisher_to_writers_pct": agr.publisher_to_writers_pct},
            )
        except ValueError as exc:
            return HTMLResponse(str(exc), status_code=400)
        db.record_signature(conn, sig)
        # The gate, satisfied by the signature rather than by an assertion about one.
        db.set_talent_agreement(conn, talent_id, sig.signed_at[:10],
                                f"Signed in portal · {sig.digest[:12]}")
        signer_mail = sig.signer_email
        doc_text = agr.signable_text()
    finally:
        conn.close()
    _mail_signed_copy(signer_mail, sig, doc_text, row_name=sig.signer_name)
    return RedirectResponse(f"/creator/{token}/agreement", status_code=303)


def _mail_signed_copy(signer_mail: str, sig, doc_text: str, *, row_name: str) -> None:
    """Their copy, and the operator's. Retention is a requirement of the legal shape this
    claims (ESIGN/UETA), and a writer who signed a rights assignment should not have to
    come back to a link to read what they gave away."""
    from .. import mailer
    from . import meeting_scheduler
    from .shell import public_base as _pb
    block = (f"\n\n{'=' * 58}\nSIGNED COPY — the exact text this signature covers\n"
             f"{'=' * 58}\n{doc_text}\n{'=' * 58}\n"
             f"Signed by: {sig.typed_name}"
             + (f" <{sig.signer_email}>" if sig.signer_email else "")
             + f"\nSigned at: {sig.signed_at}\n"
             f"Consent given: {sig.consent_text}\n"
             f"Document digest (SHA-256): {sig.digest}\n")
    if signer_mail:
        try:
            mailer.send_email(
                signer_mail, "Your signed Composer Agreement — Chordential",
                "Thank you. Below is the agreement exactly as you signed it, for your "
                "records. It commits you to no work; each engagement is offered and "
                "accepted separately." + block)
        except Exception:  # noqa: BLE001
            pass
    op_mail = meeting_scheduler._operator_email()
    if op_mail:
        try:
            mailer.send_email(
                op_mail, f"✍ Composer Agreement signed — {row_name or sig.typed_name}",
                f"{sig.typed_name} signed the Composer Agreement.\n"
                f"They are now assignable (the agreement half of the gate).\n"
                f"{_pb()}/talent" + block)
        except Exception:  # noqa: BLE001
            pass


@router.post("/creator/{token}/project/{project_id}/note/{comment_id}/address")
def creator_address_note(token: str, project_id: int, comment_id: int):
    """The composer marks a client note addressed (or reopens it) — COMPOSER-side
    working state only (EP P0-1): the client's resolved flag is untouched, so the
    client never sees a note flip "resolved" without the studio publishing a take.

    Same double guard as every creator action: valid portal token AND an actual
    assignment to this project."""
    conn = db.connect()
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        if not db.talent_is_assigned(conn, row["id"], project_id):
            return HTMLResponse("Not assigned to this project", status_code=403)
        db.toggle_comment_addressed(conn, project_id, comment_id)
    finally:
        conn.close()
    return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)


@router.post("/creator/{token}/project/{project_id}/note/{comment_id}/reply")
async def creator_reply_note(request: Request, token: str, project_id: int,
                             comment_id: int, body: str = Form("")):
    """The composer asks the studio about a note — the talk-back channel both
    persona reviews named as the #1 reason the phone stays primary.

    The reply is INTERNAL (composer↔studio): it threads under the client's note in
    the composer room and the studio console, and never renders on the client
    portal — the studio mediates what reaches the client (production model:
    feedback→interpretation is the house's craft)."""
    conn = db.connect()
    who = ""
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        if not db.talent_is_assigned(conn, row["id"], project_id):
            return HTMLResponse("Not assigned to this project", status_code=403)
        text = (body or "").strip()[:600]     # server-side cap; maxlength is advisory
        if text:
            parent = conn.execute(
                "SELECT id FROM review_comments WHERE id = ? AND project_id = ?",
                (comment_id, project_id)).fetchone()
            # Only mark success + notify when the reply ACTUALLY threaded onto a real
            # note — a stale/cross-project/guessed comment_id must not fabricate a
            # reply bubble or ping the operator about work that was never recorded
            # (eng P0). ``who`` is the signal the insert happened.
            if parent is not None:
                who = row["name"]
                db.add_review_comment(
                    conn, project_id, author=who,
                    email=(row["email"] or "") if "email" in row.keys() else "",
                    body=text, kind="comment", parent_id=comment_id, internal=True)
        project = db.get_project(conn, project_id)
    finally:
        conn.close()
    if who:
        await run_in_threadpool(
            _notify_operator_review, project_id, project,
            f"Composer question · {_campaign_label(project) if project else 'campaign'}",
            f"{who} replied to a client note. Review it in the delivery console.")
    # XHR (Phase 4): thread the reply in place — no full reload, so the composer
    # keeps their playhead + open sheet (the flow the composer review flagged).
    if (request.headers.get("x-requested-with") or "").lower() in ("fetch", "xmlhttprequest"):
        return JSONResponse({"ok": bool(who), "author": who, "body": text if who else ""})
    return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)


@router.post("/creator/{token}/project/{project_id}/capture")
def creator_capture(request: Request, token: str, project_id: int,
                    text: str = Form("")):
    """Capture (Phase 4 §13): the composer jots an idea/motif to the room's private
    shelf — timestamped, composer + studio only, NEVER shown to the client."""
    conn = db.connect()
    entry = None
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        if not db.talent_is_assigned(conn, row["id"], project_id):
            return HTMLResponse("Not assigned to this project", status_code=403)
        entry = db.add_capture(conn, project_id, text, by=row["name"])
    finally:
        conn.close()
    if (request.headers.get("x-requested-with") or "").lower() in ("fetch", "xmlhttprequest"):
        return JSONResponse({"ok": bool(entry),
                             "text": entry["text"] if entry else "",
                             "at": entry["at"] if entry else ""})
    return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)


@router.post("/creator/{token}/project/{project_id}/version")
async def creator_submit_version(
    token: str, project_id: int, file: Optional[UploadFile] = File(None),
):
    """A creator submits a work version for a project they're assigned to.

    Reuses the exact version-ladder mechanism the admin Assets agent uses, so a
    creator-submitted master is a first-class version. Guarded twice: a valid
    portal token AND an actual assignment to this project."""
    conn = db.connect()
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        if not db.talent_is_assigned(conn, row["id"], project_id):
            return HTMLResponse("Not assigned to this project", status_code=403)
        if file is None or not (file.filename or "").strip():
            return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)
        data = await _read_capped(file, _SUBMISSION_MAX_BYTES)
        if not data:                              # over cap or empty — never buffer unbounded
            return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)
        who = row["name"]
        # A creator's submission does NOT go straight to the client — it waits as a
        # pending submission for Jon to vet, then publish. This is the "machine
        # proposes, Jon disposes" gate the old code claimed but never enforced (it
        # appended directly to the client-visible ladder).
        _store_pending_submission(conn, project_id, data, file.filename, who)
        prow = db.get_project(conn, project_id)
        campaign = (prow["need"] if prow is not None else "") or "Campaign"
        db.add_update(conn, project_id, f"{who} submitted a new version. Pending your review.")
        _sync_role_milestones(conn, project_id)   # Composer deliverable → In progress
    finally:
        conn.close()
    # Composer-direction notification: ping Jon (the operator) that new work landed
    # — NOT the client. Offloaded to a thread: the push/SMTP calls do blocking network
    # I/O, and this is an async handler on uvicorn's single event loop — inline they'd
    # freeze the whole site (every page, every portal, /healthz) for the send.
    await run_in_threadpool(
        _notify_operator_review,
        project_id, None, f"New work submitted · {campaign}",
        f"{who} submitted a new version. Review and publish it in the delivery console.")
    return RedirectResponse(f"/creator/{token}?submitted={project_id}#p{project_id}",
                            status_code=303)


@router.post("/creator/{token}/project/{project_id}/deliverable")
async def creator_submit_deliverable(
    request: Request, token: str, project_id: int, label: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """A creator uploads a scoped DELIVERABLE (instrumental / TV mix, cutdowns, verticals,
    stems) AFTER the master is approved. Lands in ``delivery_json['assets']`` under its
    label so the client can sign it off, and pings the operator. Mirrors the operator
    Assets-agent storage; guarded by a valid portal token AND an assignment to the project.

    Returns an HONEST result: for an AJAX upload (``X-Requested-With`` header) it returns
    JSON ``{ok, count}`` reflecting what actually persisted, so the portal only marks a row
    "Delivered" when the asset truly landed (never on a redirect that stored nothing)."""
    xhr = (request.headers.get("x-requested-with") or "").lower() in ("fetch", "xmlhttprequest")
    def _fail(msg, code=400):
        if xhr:
            return JSONResponse({"ok": False, "error": msg}, status_code=code)
        # No-JS form post: a soft "no file" bounces back to the portal; hard errors
        # (auth, save failure) return their real status code.
        if code == 400:
            return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)
        return HTMLResponse(msg, status_code=code)
    conn = db.connect()
    campaign = "Campaign"
    who = ""
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return _fail("not found", 404)
        if not db.talent_is_assigned(conn, row["id"], project_id):
            return _fail("not assigned", 403)
        if file is None or not (file.filename or "").strip():
            return _fail("no file", 400)
        who = row["name"]
        ext = os.path.splitext(file.filename)[1].lower()
        ctype = (file.content_type or "").lower()
        kind = "audio" if (ext in _AUDIO_EXTS or ctype.startswith("audio/")) else "file"
        data = await _read_capped(file, _SUBMISSION_MAX_BYTES)
        if not data:                              # empty OR over cap — never buffer unbounded
            return _fail("file missing or too large", 400)
        # Collision-proof on-disk name (random suffix) so nothing can overwrite another
        # upload's file — no counter to race on.
        safe_ext = ext if ext else (".mp3" if kind == "audio" else ".bin")
        safe_name = f"proj{project_id}-{os.urandom(5).hex()}{safe_ext}"
        _persist_upload(conn, safe_name, data, mirror=len(data) <= _CUT_MIRROR_BYTES)  # ADR-0026
        delivery = db.get_delivery(conn, project_id)
        # EP review P0-3: deliverables get the SAME studio gate as the master.
        # The upload lands PENDING — the studio vets and publishes it before the
        # client can ever see it (uniform publish gate, stems included).
        from datetime import datetime as _dt, timezone as _tz
        pending = list(delivery.get("pending_assets") or [])
        deliverable = (label.strip() or file.filename)
        pending.append({"label": deliverable, "url": f"/uploads/{safe_name}",
                        "filename": safe_name, "orig": file.filename,
                        "kind": kind, "by": who,
                        "at": _dt.now(_tz.utc).isoformat()})
        db.update_delivery(conn, project_id, "pending_assets", pending)
        # CONFIRM it actually persisted before telling the composer it landed.
        stored = db.get_delivery(conn, project_id).get("pending_assets") or []
        landed = any(a.get("filename") == safe_name for a in stored)
        count = len(stored)
        prow = db.get_project(conn, project_id)
        campaign = (prow["need"] if prow is not None else "") or "Campaign"
        db.add_update(conn, project_id,
                      f"{who} submitted '{deliverable}' · with the studio for review.")
    finally:
        conn.close()
    if not landed:
        return _fail("not saved. Please try again", 500)
    await run_in_threadpool(
        _notify_operator_review, project_id, None, f"Deliverable submitted · {campaign}",
        f"{who} submitted a deliverable. Vet it in the delivery console, then publish.")
    if xhr:
        return JSONResponse({"ok": True, "label": deliverable, "count": count})
    return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)
