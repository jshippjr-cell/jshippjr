"""The project surface — delivery, review and the client portal.

ADR-0044, slice 6: the last of the large route groups. 57 routes covering the operator's
delivery console, the client's review portal, the session room and the payment door.

What made this one different from `/opportunity` is that measuring "which helpers does
this group share?" by *direct* callers was already known to be wrong (slice 5's
`_quote_band_for`), so it was measured as a transitive closure from both sides at once:
everything reachable from a `/project` route, minus everything reachable from any other
route. That left 25 names exclusive to this group — they are below — and three shared
only with `/creator`, which went into the helper layer instead
(`uploads._read_capped`, `delivery_ops._project_estimate`,
`delivery_ops._sync_role_milestones`).

The closure had to exclude LOCAL bindings to be right. `_delivery_view` assigns a local
`manifest = build_manifest(...)`, and a naive walk read that as a reference to the
module-level `/manifest.webmanifest` handler — which would have moved that route out of
`app.py` by accident.
"""

from __future__ import annotations

import hmac
import json
import math
import os
from typing import Optional
from urllib.parse import quote, unquote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (
    HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response)

from .. import mailer, recruiting
from ..estimation import ROLE_RATES, stated_length
from ..delivery import (
    brief_rollup, build_clearance_certificate, build_cue_sheet, build_manifest,
    build_timeline, current_version, delivery_completeness, license_confirmation,
    merge_signatory, reconcile_brief, revision_status,
    scoped_deliverables, seed_brief, version_label, version_name, versions_list,
    ASSIGNABLE_FOLDERS, BRIEF_FIELDS, CONTENT_ID_HONEST, DELIVERY_STATES, VERSION_STATES,
    can_release, state_on_approval_reopened, state_on_changes_requested,
    state_on_client_approved, state_on_version_published,
)
from ..matching import match_talent
from ..models import MusicDiscipline
from ..payments import get_payment_provider
from ..proposals import build_proposal
from ..storage import get_object_store
from . import campaigns, db, production, signals
from .billing import (
    _client_portal_url, _ensure_final_invoice_issued, _invoice_from_proposal_row,
    _proposal_from_row,
)
from .delivery_ops import (
    _approve_version_core, _build_delivery_package, _campaign_label, _current_version_tag,
    _gate_banner, _maybe_finalize_delivery, _notify_assigned_creators,
    _notify_operator_review, _project_estimate, _sync_role_milestones,
)
from .estimate import estimate_for
from .evaluate import evaluate
from .opportunity_ops import _load, _quote_band_for
from .shell import (
    admin_authed as _admin_authed, public_base as _public_base, render,
)
from .uploads import (
    _AUDIO_EXTS, _CUT_MIRROR_BYTES, _persist_upload, _read_capped,
    _store_pending_submission, upload_dir,
)

router = APIRouter(tags=["project"])


# --------------------------------------------------------------------------- #
# Session Room (Living OS P5) — the live layer over the delivery surfaces.
# One event bus (project_events), role-filtered SERVER-SIDE; presence is
# name + role only (council: never activity surveillance). Increment 1 covers
# the operator console + client portal; talent joins in increment 2. Polling
# transport for now — the endpoint shape (after=cursor) is SSE-compatible.
# --------------------------------------------------------------------------- #
_PRESENCE: dict = {}          # {project_id: {key: (name, role, ts)}} — in-process


# Phase 2 (The Picture): the client's cut. Range streaming is served by the
# existing /uploads route (FileResponse handles Range — Safari requires it).
# Size policy is ADR-0026: hard cap per cut; DB-mirror only under the threshold.
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}


_CUT_MAX_BYTES = int(os.environ.get("CHORDENTIAL_CUT_MAX_MB", "512")) * 1024 * 1024


@router.get("/project/{project_id}/dl/{name}")
def delivery_download(request: Request, project_id: int, name: str, k: str = "", r: str = ""):
    """Payment-gated deliverable download (ZIP + per-asset masters/docs).

    Two access modes, distinguished by whether a share/reviewer TOKEN is presented:

    * **Client** (a valid ``?k=``/``?r=`` token) — the payment gate applies: the file
      is served only when deliverables are UNLOCKED (paid in full, or Jon manually
      unlocked this delivery), else **402 Payment Required**. We key on token presence
      (not admin status) deliberately: when the admin gate is disabled, ``_admin_authed``
      is True for everyone, so an admin-status check would silently bypass the paywall.
    * **Operator** (no token) — must be the admin; Jon downloads freely to inspect the
      package. 404 if not authorized.

    Streaming previews are unaffected (they stay on /uploads); this gate is only on the
    downloadable deliverables."""
    from fastapi.responses import FileResponse
    conn = db.connect()
    try:
        row = db.get_project(conn, project_id)
        if row is None:
            return PlainTextResponse("not found", status_code=404)
        token = db.ensure_project_share_token(conn, project_id)
        delivery = db.get_delivery(conn, project_id)
        verified = reviewer_from_token(delivery, r)
        k_ok = bool(token and k and hmac.compare_digest(str(k), str(token)))
        has_client_token = k_ok or verified is not None
        if has_client_token:
            unlocked = (bool(delivery.get("download_unlocked"))
                        or db.invoice_balance(conn, project_id)["paid_in_full"])
            if not unlocked:
                return PlainTextResponse(
                    "Payment required: your deliverables unlock once your invoice is "
                    "paid in full. You can still stream and review the work.",
                    status_code=402)
        elif not _admin_authed(request):
            # No client token and not the operator → no access.
            return PlainTextResponse("not found", status_code=404)
    finally:
        conn.close()
    # ADR-0043: the gate above has already passed, so it is safe to hand the client
    # a direct URL. Local keeps serving the file itself.
    _store = get_object_store(upload_dir())
    _key = os.path.basename(name or "")
    path = _store.local_path(_key) if _key and _key == name else None
    if path is not None:
        return FileResponse(path, filename=os.path.basename(path))
    if _key and _key == name and getattr(_store, "durable", False):
        signed = _store.url(_key)
        if signed:
            return RedirectResponse(signed, status_code=307)
    # Ephemeral disk wiped: rehydrate from the durable DB mirror (ZIPs are mirrored at build,
    # assets via _persist_upload). A ZIP built BEFORE the mirror existed isn't stored — rebuild
    # it from the durable source media (which _build_delivery_package rehydrates first).
    base = os.path.basename(name or "")
    if base and base == name:
        conn2 = db.connect()
        try:
            blob = db.get_media_blob(conn2, base)
            if blob is None and base.lower().endswith(".zip"):
                pkg = _build_delivery_package(conn2, project_id)
                blob = db.get_media_blob(conn2, base)
                if blob is None and pkg is not None:
                    blob = db.get_media_blob(conn2, os.path.basename(pkg["filename"]))
        finally:
            conn2.close()
        if blob is not None:
            data, ctype = blob
            # ADR-0043: put it back through the STORE. On local this restores the
            # disk copy so the next read hits FileResponse and Range works; with a
            # bucket configured it repairs the missing object instead of writing a
            # local file nothing would serve.
            get_object_store(upload_dir()).put(base, data, ctype)
            return Response(content=data, media_type=ctype or "application/zip",
                            headers={"Content-Disposition": f'attachment; filename="{base}"'})
    return PlainTextResponse("not found", status_code=404)


@router.post("/project/{project_id}/delivery/unlock")
def delivery_unlock(project_id: int, unlock: str = Form("1")):
    """Operator override (admin-only via the gate): manually unlock/relock the
    client's deliverable downloads independent of payment. Machine proposes (pay in
    full → unlock); Jon disposes (release anyway, or hold)."""
    conn = db.connect()
    try:
        db.update_delivery(conn, project_id, "download_unlocked",
                           True if unlock == "1" else None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#delivery", status_code=303)


# Scoped role name → the craft (MusicDiscipline) that qualifies a creator for it.
# Drives per-role candidate lists so the Composer slot lists composers, the Mixer
# slot lists mixers, etc. — instead of one opp-discipline list shown under every role.
_ROLE_DISCIPLINE = {
    "composer": MusicDiscipline.COMPOSITION,
    "music editor": MusicDiscipline.COMPOSITION,
    "arranger": MusicDiscipline.ARRANGEMENT,
    "orchestrator": MusicDiscipline.ARRANGEMENT,
    "sound designer": MusicDiscipline.SOUND_DESIGN,
    "mixer": MusicDiscipline.MIXING,
    "mix engineer": MusicDiscipline.MIXING,
    "mastering": MusicDiscipline.MIXING,
    "music supervisor": MusicDiscipline.SUPERVISION,
}


def _project_view(conn, project_id: int):
    """Assemble a project with its roles, current assignments, and ranked candidates."""
    row = db.get_project(conn, project_id)
    if row is None:
        return None
    _sync_role_milestones(conn, project_id)  # reflect delivery reality before we read them
    roles = json.loads(row["roles"]) if row["roles"] else []
    assignments = db.list_assignments(conn, project_id)
    by_role = {role: [] for role in roles}
    for a in assignments:
        by_role.setdefault(a["role"], []).append(a)

    # Ranked candidates come from the linked opportunity's discipline (the matcher).
    talent_pool = db.load_talent(conn)
    matches = []
    need_text = ""
    if row["opp_id"] is not None:
        opp_row = db.get_opportunity(conn, row["opp_id"])
        if opp_row is not None:
            opp = db.opportunity_from_row(opp_row)
            qual, scored = evaluate(opp)
            need_text = f"{opp.need} {opp.description}"
            matches = match_talent(
                qual.discipline, qual.secondary_disciplines, need_text, talent_pool,
            )
    # Per-role candidates: each scoped role lists the approved creators whose craft fits
    # THAT role (Composer→composition, Mixer→mixing, …), ranked by fit — not the single
    # opp-discipline list shown identically under every role. Reported live: "I'm not
    # getting a full list of matchable composers to match to a project."
    matches_by_role = {}
    for role in roles:
        disc = _ROLE_DISCIPLINE.get((role or "").strip().lower())
        matches_by_role[role] = (
            match_talent(disc, [], need_text, talent_pool) if disc is not None else matches
        )
    milestones = db.list_milestones(conn, project_id)
    progress = db.milestone_progress(conn, project_id)
    return {
        "row": row, "roles": roles, "by_role": by_role, "matches": matches,
        "matches_by_role": matches_by_role,
        "milestones": milestones, "progress": progress,
        "updates": db.list_updates(conn, project_id),
        "crew": db.project_crew(conn, project_id),
        # Per-role pay priors so Jon sees the cost of each scoped role.
        "role_rates": {role: ROLE_RATES.get(role) for role in roles},
        # When an assigned talent has their own rate it overrides the role
        # default in the proposal — surface it so the cost source is clear.
        "rate_overrides": db.assigned_rate_overrides(conn, project_id),
    }


@router.get("/project/{project_id}", response_class=HTMLResponse)
def project_detail(request: Request, project_id: int,
                   err: str = "", t: Optional[int] = None):
    conn = db.connect()
    try:
        view = _project_view(conn, project_id)
        if view is None:
            return HTMLResponse("Project not found", status_code=404)
    finally:
        conn.close()
    return render(
        request, "project_detail.html", nav="projects",
        project_states=db.PROJECT_STATES, milestone_states=db.MILESTONE_STATES,
        gate_banner=_gate_banner(err, t), **view,
    )


@router.post("/project/{project_id}/assign")
def project_assign(project_id: int, role: str = Form(...), talent_id: int = Form(...)):
    """The decision action — Jon assigns a creator to a role. The only assign
    path. Reported live: signing a creator should email them the project
    scope — this is the one place that decision is made, so it's the one
    place the email fires from."""
    conn = db.connect()
    try:
        row = db.get_talent(conn, talent_id)
        # ADR-0024 (the A-3 floor): no assignment without an executed agreement +
        # rate — refused server-side before any side effect, mirroring the
        # payment gate on release.
        if db.talent_assignment_blockers(row):
            return RedirectResponse(
                f"/project/{project_id}?err=agreement&t={talent_id}",
                status_code=303)
        db.add_assignment(conn, project_id, role, talent_id)
        t = db.talent_from_row(row) if row is not None else None
        name = t.name if t else "a creator"
        # The assignment IS the broadcast — post a roster line to the crew feed
        # automatically (no manual "post an update" step). Names the whole team so
        # everyone on the project sees who they're now working with.
        crew = db.project_crew(conn, project_id)
        names = ", ".join(c["name"] for c in crew) or name
        db.add_update(
            conn, project_id,
            f"{name} joined the crew as {role}. Current team: {names}.",
            "assignment",
        )
        project = db.get_project(conn, project_id)
        # ADR-0020: one decision, many quiet operations — the portal exists the moment the
        # composer does. Mint their portal token now so the scope email carries their one
        # link (brief, feedback, uploads); no separate "issue portal link" step.
        portal_token = db.ensure_talent_portal_token(conn, talent_id) if hasattr(
            db, "ensure_talent_portal_token") else None
        if portal_token is None:
            trow = db.get_talent(conn, talent_id)
            portal_token = trow["portal_token"] if trow is not None and "portal_token" in trow.keys() else None
            if not portal_token:
                import secrets as _sec
                portal_token = _sec.token_urlsafe(12)
                conn.execute("UPDATE talent SET portal_token=? WHERE id=?",
                             (portal_token, talent_id))
                conn.commit()
    finally:
        conn.close()
    if t is not None and t.email and mailer.mail_configured() and project is not None:
        base = _public_base()
        scope = recruiting.compose_project_assignment(
            t, role=role, client=project["client"], need=project["need"],
            deadline=project["deadline"] or "",
        )
        body = scope["body"]
        if portal_token:
            body += (f"\n\nYour portal — the brief, deliverables, timeline, client feedback "
                     f"and your uploads all live here:\n{base}/creator/{portal_token}")
        mailer.send_email(
            t.email, scope["subject"], body,
            html=mailer.branded_html(base, body),
        )
    # Update the CLIENT too — their team is coming together (reported live: assigning a
    # creator should alert the client). Warm status note via the opportunity's contact;
    # never the creator's rate. Best-effort, off the assign decision.
    if project is not None and mailer.mail_configured() and project["opp_id"]:
        conn2 = db.connect()
        try:
            opp = db.get_opportunity(conn2, project["opp_id"])
            contact_email = (opp["contact_email"] if opp is not None
                             and "contact_email" in opp.keys() else "") or ""
            token = db.ensure_share_token(conn2, project["opp_id"]) if opp is not None else ""
        finally:
            conn2.close()
        if contact_email:
            base = _public_base()
            upd = recruiting.compose_client_assignment_update(
                role=role, creator_name=name, need=project["need"],
                contact_name=(opp["contact_name"] if opp is not None
                              and "contact_name" in opp.keys() else "") or "",
                workspace_url=f"{base}/workspace/{token}" if token else "",
            )
            try:
                mailer.send_email(contact_email, upd["subject"], upd["body"],
                                  html=mailer.branded_html(base, upd["body"]))
            except Exception:  # noqa: BLE001 — a client update never blocks the assign
                pass
    # Broadcast the new assignment to the rest of the project crew (the new hire
    # already got the tailored scope email above, so they're excluded here).
    if project is not None:
        _notify_assigned_creators(
            project_id, project,
            subject=f"New teammate on {project['client']} — {project['need']}",
            body_text=(f"{name} just joined the crew as {role}. "
                       f"The full team is now: {names}."),
            exclude_email=(t.email if t is not None else ""),
        )
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@router.post("/project/{project_id}/unassign")
def project_unassign(project_id: int, assignment_id: int = Form(...)):
    conn = db.connect()
    try:
        a = db.get_assignment(conn, assignment_id)
        db.remove_assignment(conn, assignment_id)
        if a is not None:
            db.add_update(
                conn, project_id,
                f"{a['talent_name'] or 'A creator'} removed from {a['role']}.",
                "assignment",
            )
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@router.post("/project/{project_id}/status")
def project_status(project_id: int, status: str = Form(...)):
    conn = db.connect()
    try:
        db.update_project_status(conn, project_id, status)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@router.post("/project/{project_id}/milestone")
def project_add_milestone(project_id: int, title: str = Form(...), role: str = Form("")):
    conn = db.connect()
    try:
        if title.strip():
            db.add_milestone(conn, project_id, title.strip(), role.strip() or None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@router.post("/project/{project_id}/milestone/status")
def project_milestone_status(
    project_id: int, milestone_id: int = Form(...), status: str = Form(...)
):
    conn = db.connect()
    try:
        db.update_milestone_status(conn, milestone_id, status)
        m = db.get_milestone(conn, milestone_id)
        if m is not None:
            db.add_update(conn, project_id, f"“{m['title']}” → {status}.", "milestone")
        # Delivery folds into the money flow: once every milestone is Done and a
        # proposal exists, draft the final invoice (once) so closing the work and
        # billing for it are one motion. Jon still issues + marks it paid.
        if status == "Done":
            progress = db.milestone_progress(conn, project_id)
            prop = db.proposal_for_project(conn, project_id)
            if (
                progress["total"] > 0 and progress["done"] == progress["total"]
                and prop is not None and not db.has_invoice(conn, project_id, "Final")
            ):
                prow = db.get_project(conn, project_id)
                inv = _invoice_from_proposal_row(prow, prop, "Final")
                db.insert_invoice(conn, project_id, prop["id"], inv)
                db.add_update(
                    conn, project_id,
                    "Final invoice drafted (all milestones delivered).", "invoice",
                )
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@router.post("/project/{project_id}/update")
def project_post_update(project_id: int, body: str = Form("")):
    """Jon posts a note that broadcasts to everyone assigned to the project."""
    conn = db.connect()
    try:
        if body.strip():
            db.add_update(conn, project_id, body.strip(), "update")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@router.post("/project/{project_id}/milestone/delete")
def project_milestone_delete(project_id: int, milestone_id: int = Form(...)):
    conn = db.connect()
    try:
        db.remove_milestone(conn, milestone_id)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


def _delivery_view(conn, project_id: int, selected_v=None, client_view: bool = False):
    """Assemble the Delivery OS data for a project (engine docs + state), or None.

    ``selected_v`` (IP2) picks which version the review surface opens — its track
    loads in the player and its comments filter to that version's number. Defaults
    to the current (latest) version so the existing behaviour is unchanged."""
    row = db.get_project(conn, project_id)
    if row is None:
        return None
    assignments = db.list_assignments(conn, project_id)
    delivery = db.get_delivery(conn, project_id)
    license = delivery.get("license") or {}
    estimate = _project_estimate(conn, row)

    versions = versions_list(delivery)
    current = current_version(delivery)

    # IP3 (defensible rights): the certificate carries a signatory block, the
    # version it certifies, the date, and reads the license grant as a draft until
    # the operator explicitly confirms the terms (no silent buyout-by-default).
    from datetime import date as _date
    license_conf = license_confirmation(delivery)
    certified_version = (current.get("label") if current else "") or ""
    cert = build_clearance_certificate(
        row, assignments, license,
        signatory=delivery.get("signatory"),
        license_confirmed=license_conf,
        certified_version=certified_version,
        certified_date=_date.today().isoformat(),
    )
    cues = build_cue_sheet(row, assignments, delivery=delivery)
    manifest = build_manifest(
        row, assets=delivery.get("assets") or [], versions=versions
    )
    revisions = revision_status(row, estimate, delivery)
    token = db.ensure_project_share_token(conn, project_id)

    # The creative brief (Phase 4): the logged brief, or defaults seeded from the
    # opportunity behind the project (need → objective, description → references/tone).
    opp_row = db.get_opportunity(conn, row["opp_id"]) if row["opp_id"] is not None else None
    brief = seed_brief(row, opp_row, delivery)
    # Brief-as-contract: reconcile the brief's deliverables against the delivered
    # assets so both portal + console show what was promised vs delivered.
    brief_recon = reconcile_brief(brief, delivery.get("assets") or [])
    brief_roll = brief_rollup(brief_recon)
    # Delivery-completeness gate: which scoped, upload-required deliverables have a
    # real uploaded asset vs which are silently missing — drives the portal/console
    # warnings + the honest partial labelling so we never ship "everything" when the
    # cutdowns/stems were never uploaded.
    completeness = delivery_completeness(row, delivery)
    # The client portal never sees composer↔studio internal notes (publish-gate
    # principle applied to words); the console sees everything.
    comments = db.list_review_comments(conn, project_id,
                                       include_internal=not client_view)
    timeline = build_timeline(row, delivery, comments)
    # Tie conform classification to the cue that changed (EP P0): map each
    # timecoded change request to the cue its timecode falls under, and name the
    # cues the current cut touches. Both read the live cue list — the once-dead
    # cue_for_time/cues_touched_by_cut helpers now drive the console's conform copy.
    _cues_now = db.get_cues(conn, project_id)
    note_cue = {}
    for _c in comments:
        # Any timecoded note (a client's pinned comment or a timed change request)
        # gets tagged with the cue(s) it falls under — a RANGE note names every cue
        # its span overlaps ('m01–m02') so the operator weighing conform-vs-revision
        # sees a section note touches a section, not just its first frame (EP P0).
        if _c["t_seconds"] is not None:
            _te = _c["t_end"] if "t_end" in _c.keys() else None
            _code = db.cues_for_note(_cues_now, _c["t_seconds"], _te)
            if _code:
                note_cue[_c["id"]] = _code
    conform_cut_cues = db.cues_touched_by_cut(conn, project_id) if delivery.get("picture") else []

    # Per-asset approval (granular sign-off): attach each deliverable asset's
    # current per-asset status + stable key so the portal/console can render a
    # badge and the reviewer can Approve / Request changes one asset at a time.
    assets_for_approval = list(delivery.get("assets") or [])
    assets_with_approval = []
    for a in assets_for_approval:
        a2 = dict(a)
        a2["approval"] = db.get_asset_approval(delivery, a)
        a2["asset_key"] = db.asset_key(a)
        assets_with_approval.append(a2)

    # Make per-asset approval discoverable on the client portal: surface EVERY
    # scoped deliverable with a clear status — ✓ uploaded (carrying the matching
    # asset's per-asset-approval row + stable key, so verified reviewers get the
    # Approve / Request-changes controls) vs ⧗ not uploaded yet ("waiting on
    # Chordential"). Most demo deliverables are referenced-only, so showing only
    # uploaded assets hid the per-deliverable controls; this surfaces the full list.
    _by_label = {}
    for a in assets_with_approval:
        lbl = (a.get("label") or a.get("filename") or "").strip()
        if lbl and lbl not in _by_label:
            _by_label[lbl] = a
    _clock = production.creative_lock(delivery)
    scoped_list = []
    n_scoped_approved = 0
    for d in scoped_deliverables(row, delivery):
        item = dict(d)
        match_asset = _by_label.get(d.get("match") or "")
        if match_asset is not None:
            item["asset_key"] = match_asset.get("asset_key")
            item["approval"] = match_asset.get("approval")
            item["url"] = match_asset.get("url")
            item["kind"] = match_asset.get("kind")
            if (match_asset.get("approval") or {}).get("status") == "Approved":
                n_scoped_approved += 1
        elif d.get("from_version"):
            # The primary master is the review version itself — it has no per-row
            # Approve control; the main "Approve the master" button IS its sign-off,
            # so its status simply mirrors the creative lock.
            if _clock:
                item["approval"] = {"status": "Approved", "by": (_clock.get("by") or ""),
                                    "email": "", "date": "", "version": str(_clock.get("version_n") or "")}
                n_scoped_approved += 1
            else:
                item["approval"] = {"status": "Pending", "by": "", "email": "", "date": "", "version": ""}
            item["asset_key"] = ""              # approved via the main button, not a row button
        else:
            item["asset_key"] = ""
            item["approval"] = None
        scoped_list.append(item)
    scoped_rollup = {
        "approved": n_scoped_approved,
        "total": len(scoped_list),
        "uploaded": sum(1 for s in scoped_list if s.get("uploaded")),
    }

    current_n = int(current["n"]) if current else 0

    # IP2: the reviewer can open ANY version, not just current. Resolve the
    # selected version (default = current); its track drives the player and its
    # comments filter to that version's number, so v1 ↔ v2 is navigable/playable.
    selected = current
    if selected_v not in (None, ""):
        try:
            want = int(selected_v)
        except (TypeError, ValueError):
            want = None
        if want is not None:
            match = next((v for v in versions if int(v.get("n") or 0) == want), None)
            if match is not None:
                selected = match
    selected_n = int(selected["n"]) if selected else 0

    # The version under review (anti-chaos): the SELECTED version's audio drives
    # the review player; fall back to the first uploaded audio asset for Phase-0
    # projects that never logged a version.
    review_track = selected
    if review_track is None:
        assets = delivery.get("assets") or []
        review_track = next((a for a in assets if a.get("kind") == "audio"), None)

    # IP2: per-version open/resolved counts for the SELECTED version (kind='comment'
    # top-level notes only — replies inherit their parent's thread, approvals/change
    # requests aren't resolvable).
    sel_open = sel_resolved = 0
    for c in comments:
        if (c["kind"] or "comment") != "comment" or c["parent_id"] is not None:
            continue
        if selected_n != 0 and str(c["version"]) != str(selected_n):
            continue
        if c["resolved"]:
            sel_resolved += 1
        else:
            sel_open += 1

    # Payment gate on DOWNLOADS (not on streaming/preview — the client must be able
    # to review before paying). Deliverables unlock when the client is paid in full
    # OR Jon has manually unlocked this delivery. Streaming src stays on /uploads;
    # only the ZIP + per-asset DOWNLOAD links route through the gated _can-download_ path.
    # Self-heal: once delivered, the balance must be a real Issued invoice so the download
    # stays gated behind it — otherwise a paid DEPOSIT reads as "paid in full" (nothing else
    # outstanding) and the files unlock without the balance (reported live).
    if (delivery.get("state") or "") in ("Delivered", "Released"):
        _ensure_final_invoice_issued(conn, project_id)
    balance = db.invoice_balance(conn, project_id)
    download_unlocked = bool(delivery.get("download_unlocked")) or balance["paid_in_full"]
    # Build gated download URLs (carry the share token so the route can authorize).
    def _dl(name: str) -> str:
        base = os.path.basename(name or "")
        return f"/project/{project_id}/dl/{base}?k={token}" if base else ""
    zip_obj = delivery.get("delivery_zip")
    if zip_obj:
        zip_obj = dict(zip_obj)
        zip_obj["dl_url"] = _dl(zip_obj.get("filename") or "")
    for a in assets_with_approval:
        fn = a.get("filename") or os.path.basename(a.get("url") or "")
        a["dl_url"] = _dl(fn)

    return {
        "row": row,
        "project": row,
        "assignments": assignments,
        "delivery": delivery,
        # ADR-0019: the production spine on the console — directions + the lock.
        "prod_directions": production.directions(delivery),
        "creative_lock": production.creative_lock(delivery),
        "download_unlocked": download_unlocked,
        "invoice_balance": balance,
        "state": delivery.get("state") or DELIVERY_STATES[0],
        "version_state": revisions["state"],
        # ADR-0019/0036: the client-facing production experience answers the court
        # question FIRST. Computed, never stored — one engine, and the portal and the
        # workspace render the same sentence.
        "court": production.court_state(row, delivery),
        "cert": cert,
        # The honest Content-ID sentence — the ONE source of truth (delivery.py),
        # so the browser doc and the ZIP doc can't drift on legally-material copy.
        "content_id_honest": CONTENT_ID_HONEST,
        "cues": cues,
        # The Cue Layer (Phase 3): the scoring cue list + hits + per-cue state.
        # Distinct from ``cues`` (the licensing cue SHEET above) — this is the
        # timed, scoreable spine the composer works against.
        "scoring_cues": _cues_now,
        "cue_states": db.CUE_STATES,
        # Conform↔cue tie (EP P0): which cue each timecoded change request lands
        # under, and which cues the current cut touches — surfaced where the
        # operator actually classifies conform vs revision.
        "note_cue": note_cue,
        "conform_cut_cues": conform_cut_cues,
        "manifest": manifest,
        "revisions": revisions,
        "license": cert.license,
        # IP3 — defensible rights: signatory block + explicit license confirmation.
        "signatory": merge_signatory(delivery.get("signatory")),
        "license_confirmed": license_conf,
        "assignable_folders": ASSIGNABLE_FOLDERS,
        "cue_meta": delivery.get("cue_meta") or {},
        "approvals": delivery.get("approvals") or [],
        # Verified-identity approval: the operator-invited reviewer roster — each has
        # a personal ?r= invite link (the only way to approve).
        "reviewers": delivery.get("reviewers") or [],
        # Outbound-email status: honest indicator on the reviewers card — whether
        # invites / new-version notices go out automatically or links are copied
        # by hand (mailer is null/unconfigured until SMTP env is set).
        "mail_configured": mailer.mail_configured(),
        # A creator's submission awaiting Jon's publish decision (console-only; the
        # client portal never reads this — pending work stays off the client's page).
        "pending_version": delivery.get("pending_version") or None,
        "assets": assets_with_approval,
        # Per-asset approval rollup ("N of M deliverables approved") — surfaced
        # next to the whole-version Approve so the gap is visible.
        "asset_rollup": db.asset_approval_rollup(delivery, assets_for_approval),
        "asset_approval_states": db.ASSET_APPROVAL_STATES,
        # Delivery-completeness gate: {expected, uploaded, missing, complete, text}
        # — drives the warnings + honest partial labelling on portal + console.
        "completeness": completeness,
        # The FULL scoped deliverable list with per-item upload status (✓/⧗) +
        # per-asset approval controls on the uploaded ones, + an N-of-M rollup.
        "scoped_deliverables": scoped_list,
        "scoped_rollup": scoped_rollup,
        "versions": versions,
        "current_version": current,
        "current_n": current_n,
        # IP2: which version the review surface is showing (default = current).
        "selected_version": selected,
        "selected_n": selected_n,
        "open_count": sel_open,
        "resolved_count": sel_resolved,
        "review_track": review_track,
        "released_at": delivery.get("released_at"),
        "share_token": token,
        "comments": comments,
        # Delivery automation (Phase 3): the assembled ZIP + the payoff checklist.
        "delivery_zip": zip_obj,
        "delivery_checklist": delivery.get("delivery_checklist") or [],
        # Creative brief + campaign timeline (Phase 4) — the dashboard's spine.
        "brief": brief,
        "brief_fields": BRIEF_FIELDS,
        # Brief-as-contract: the reconciliation list + the "N of M" rollup.
        "brief_items": brief_recon,
        "brief_rollup": brief_roll,
        "timeline": timeline,
        "version_states": VERSION_STATES,
    }


@router.post("/project/{project_id}/campaign/open")
def campaign_open(project_id: int):
    """Open (or create) the campaign workspace that wraps a project — the bridge from
    the project record into the Creative OS. Idempotent (lazy-creates once)."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, project_id)
        camp = db.ensure_campaign_for_project(
            conn, project_id, phase=campaigns.hydrate_phase_from_delivery(delivery))
        if camp is None:
            return HTMLResponse("Project not found", status_code=404)
        cid = camp["id"]
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{cid}", status_code=303)


@router.get("/project/{project_id}/delivery", response_class=HTMLResponse)
def delivery_console(request: Request, project_id: int, release: str = ""):
    """The Campaign Dashboard / Delivery Console (Phase 4) — the operator's command
    center for one campaign. One screen tying the creative brief, the five-agent
    status row, the version rail, the review activity feed, the campaign timeline,
    the deliverable assets + upload controls, and the action toolbar (client review
    link, delivery package, build, release) together. The delivery mutation routes
    all redirect here, so it renders the console (no longer a bounce to the package).

    ``release=needs_license`` (IP3) flags that a release was refused because the
    license has not been explicitly confirmed yet."""
    conn = db.connect()
    try:
        view = _delivery_view(conn, project_id)
        if view is None:
            return HTMLResponse("Project not found", status_code=404)
    finally:
        conn.close()
    view["release_flag"] = release
    return render(request, "delivery_console.html", nav="projects", **view)


@router.post("/project/{project_id}/delivery/brief")
def delivery_set_brief(
    project_id: int,
    objective: str = Form(""),
    references: str = Form(""),
    tone: str = Form(""),
    deliverables_needed: str = Form(""),
    deadline: str = Form(""),
):
    """Creative brief (Phase 4): log/edit the brief that opens the campaign record.

    Stored raw on ``delivery_json['brief']`` (blank fields dropped so the engine
    falls back to the opportunity-seeded default for that field)."""
    conn = db.connect()
    try:
        brief = {
            "objective": objective.strip(),
            "references": references.strip(),
            "tone": tone.strip(),
            "deliverables_needed": deliverables_needed.strip(),
            "deadline": deadline.strip(),
        }
        brief = {k: v for k, v in brief.items() if v}
        db.update_delivery(conn, project_id, "brief", brief or None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#brief", status_code=303)


@router.get("/project/{project_id}/delivery-package", response_class=HTMLResponse)
def delivery_package(request: Request, project_id: int):
    """THE artifact — the generated, on-brand Clearance-Certified delivery package
    (print-to-PDF). Admin-gated; this is the proof-of-concept."""
    conn = db.connect()
    try:
        view = _delivery_view(conn, project_id)
        if view is None:
            return HTMLResponse("Project not found", status_code=404)
    finally:
        conn.close()
    return render(request, "delivery_package.html", nav="projects", **view)


@router.post("/project/{project_id}/delivery/license")
def delivery_set_license(
    project_id: int,
    type: str = Form(""),
    territory: str = Form(""),
    term: str = Form(""),
    exclusivity: str = Form(""),
    content_id: str = Form(""),
):
    """Log the license grant (Rights agent). Stored raw; the engine merges defaults."""
    conn = db.connect()
    try:
        license = {
            "type": type.strip(),
            "territory": territory.strip(),
            "term": term.strip(),
            "exclusivity": exclusivity.strip(),
            "content_id": content_id.strip(),
        }
        # Drop blank fields so the engine falls back to the standard term.
        license = {k: v for k, v in license.items() if v}
        db.update_delivery(conn, project_id, "license", license or None)
        # IP3: editing the license terms invalidates a prior confirmation — the
        # operator must re-confirm the new terms before the cert asserts them.
        db.update_delivery(conn, project_id, "license_confirmed", None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#license", status_code=303)


@router.post("/project/{project_id}/delivery/signatory")
def delivery_set_signatory(
    project_id: int,
    entity: str = Form(""),
    signer: str = Form(""),
    title: str = Form(""),
):
    """IP3 (Rights agent): set the Clearance Certificate's signatory block —
    entity, authorized signer, and title. Stored raw on
    ``delivery_json['signatory']`` (blank fields drop to the Chordential default)."""
    conn = db.connect()
    try:
        signatory = {
            "entity": entity.strip(),
            "signer": signer.strip(),
            "title": title.strip(),
        }
        signatory = {k: v for k, v in signatory.items() if v}
        db.update_delivery(conn, project_id, "signatory", signatory or None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#license", status_code=303)


@router.post("/project/{project_id}/delivery/rotate-link")
def delivery_rotate_link(project_id: int):
    """Cut a leaked client link and mint a fresh one (ADR-0039).

    The share token is the ONLY credential on the delivery portal: whoever holds the
    URL can stream the unreleased masters, read the brief, and post a change request
    — which spends a contractual revision round. Until now it could never be changed,
    so a forwarded email or an exported Slack channel was permanent access.

    Destructive by design (the client's existing link stops working the moment this
    runs), so the button carries a confirm and this is an operator press — the
    machine never rotates on its own.
    """
    conn = db.connect()
    try:
        if db.get_project(conn, project_id) is None:
            return HTMLResponse("Project not found", status_code=404)
        token = db.rotate_share_token(conn, project_id=project_id)
        if token:
            db.add_update(
                conn, project_id,
                "Client link rotated — the previous link no longer opens this project.",
                "rights")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#reviewers", status_code=303)


@router.post("/project/{project_id}/delivery/reviewer")
def delivery_reviewer(
    project_id: int, action: str = Form("add"), name: str = Form(""),
    email: str = Form(""), role: str = Form(""), token: str = Form(""),
):
    """Verified-identity approval (operator side): manage the reviewer roster.

    ``action=add`` invites a named reviewer and mints their unique personal token
    (their ``?r=`` invite link is how the agency approves — a generic share link
    cannot). ``action=remove`` drops a reviewer by their token (their link stops
    working). Stored on ``delivery_json['reviewers']``."""
    conn = db.connect()
    invited = None
    campaign = "Campaign"
    try:
        project = db.get_project(conn, project_id)
        if project is None:
            return HTMLResponse("Project not found", status_code=404)
        if action == "remove":
            db.remove_delivery_reviewer(conn, project_id, token)
        elif name.strip():
            invited = db.add_delivery_reviewer(
                conn, project_id, name=name, email=email, role=role
            )
            campaign = _campaign_label(project)
    finally:
        conn.close()
    # Cheap win: if the mailer is configured, send the new reviewer their personal
    # link automatically. If it isn't, behavior is unchanged — the operator copies
    # the link by hand (nothing breaks today). Best-effort, never blocks the route.
    if invited and mailer.mail_configured():
        _email_reviewer_link(
            project_id, invited, campaign,
            subject=f"Your review link — {campaign}",
            lead="You've been invited to review the work.",
        )
    return RedirectResponse(f"/project/{project_id}/delivery#reviewers", status_code=303)


@router.post("/project/{project_id}/delivery/license/confirm")
def delivery_confirm_license(project_id: int, by: str = Form("")):
    """IP3 (Rights agent): the operator explicitly confirms the license terms —
    records who + when on ``delivery_json['license_confirmed']``. Until this is
    pressed the certificate shows the grant as "DRAFT — pending confirmation"
    (no silent buyout-by-default), and release is refused."""
    from datetime import date as _date
    conn = db.connect()
    try:
        signer = by.strip() or merge_signatory(
            db.get_delivery(conn, project_id).get("signatory")).get("signer", "")
        db.update_delivery(conn, project_id, "license_confirmed", {
            "by": signer or "Operator",
            "date": _date.today().isoformat(),
        })
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#license", status_code=303)


@router.post("/project/{project_id}/delivery/asset/folder")
def delivery_set_asset_folder(
    project_id: int,
    filename: str = Form(""),
    folder: str = Form(""),
):
    """IP3 (Assets agent): assign an uploaded asset's delivery folder so the ZIP
    files it where the operator says, not by keyword guess. Stored on the asset's
    ``folder`` key; a value outside ``ASSIGNABLE_FOLDERS`` clears it (back to the
    heuristic)."""
    conn = db.connect()
    try:
        base = os.path.basename((filename or "").strip())
        if base:
            delivery = db.get_delivery(conn, project_id)
            assets = list(delivery.get("assets") or [])
            chosen = folder.strip() if folder.strip() in ASSIGNABLE_FOLDERS else ""
            for a in assets:
                if a.get("filename") == base:
                    if chosen:
                        a["folder"] = chosen
                    else:
                        a.pop("folder", None)
            db.update_delivery(conn, project_id, "assets", assets or None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)


@router.post("/project/{project_id}/delivery/cue")
def delivery_set_cue_meta(
    project_id: int,
    cue: str = Form(""),
    duration: str = Form(""),
    isrc: str = Form(""),
    iswc: str = Form(""),
):
    """IP3 (Metadata agent): set a cue's Duration / ISRC / ISWC so the cue sheet is
    fileable. Stored on ``delivery_json['cue_meta']`` keyed by the cue name (blank
    fields drop, so an all-blank submit clears that cue's meta)."""
    conn = db.connect()
    try:
        key = (cue or "").strip()
        if key:
            delivery = db.get_delivery(conn, project_id)
            cue_meta = dict(delivery.get("cue_meta") or {})
            row = {
                "duration": duration.strip(),
                "isrc": isrc.strip(),
                "iswc": iswc.strip(),
            }
            row = {k: v for k, v in row.items() if v}
            if row:
                cue_meta[key] = row
            else:
                cue_meta.pop(key, None)
            db.update_delivery(conn, project_id, "cue_meta", cue_meta or None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#license", status_code=303)


# ── The Cue Layer (Phase 3) — operator doors. "The machine proposes, Jon ──────
# disposes": Jon builds the cue list + hits; the composer scores against it; per-cue
# approval maps onto the same human-pressed sign-off as deliverables. Namespaced
# under /delivery/cues/… to stay clear of the legacy /delivery/cue metadata route.
@router.post("/project/{project_id}/delivery/cues/add")
def delivery_cue_add(project_id: int, code: str = Form(""), name: str = Form(""),
                     t_in: str = Form(""), t_out: str = Form(""),
                     direction: str = Form("")):
    """Add a scoring cue (a named, timed span the composer scores)."""
    conn = db.connect()
    try:
        if db.get_project(conn, project_id) is None:
            return HTMLResponse("Project not found", status_code=404)
        db.add_cue(conn, project_id, code=code, name=name, t_in=t_in, t_out=t_out,
                   direction=direction)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@router.post("/project/{project_id}/delivery/cues/{cue_id}/state")
def delivery_cue_state(project_id: int, cue_id: int, state: str = Form("")):
    """Advance/reset a cue's state (open|take|published|approved). Approving a cue
    is a human decision (Constitution §4.1) — the machine never self-approves."""
    conn = db.connect()
    try:
        db.set_cue_state(conn, project_id, cue_id, (state or "").strip())
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@router.post("/project/{project_id}/delivery/cues/{cue_id}/edit")
def delivery_cue_edit(project_id: int, cue_id: int, code: str = Form(""),
                      name: str = Form(""), t_in: str = Form(""),
                      t_out: str = Form(""), direction: str = Form("")):
    """Edit a cue's label/timing/direction in place."""
    conn = db.connect()
    try:
        db.update_cue(conn, project_id, cue_id, code=(code or "").strip(),
                      name=(name or "").strip(), t_in=t_in, t_out=t_out,
                      direction=(direction or "").strip())
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@router.post("/project/{project_id}/delivery/cues/{cue_id}/delete")
def delivery_cue_delete(project_id: int, cue_id: int):
    """Remove a cue."""
    conn = db.connect()
    try:
        db.delete_cue(conn, project_id, cue_id)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@router.post("/project/{project_id}/delivery/cues/{cue_id}/hit")
def delivery_cue_hit_add(project_id: int, cue_id: int, t: str = Form(""),
                         name: str = Form("")):
    """Add a hit (a moment the music must honor) inside a cue."""
    conn = db.connect()
    try:
        db.add_hit(conn, project_id, cue_id, t=t, name=name)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@router.post("/project/{project_id}/delivery/cues/{cue_id}/hit/{hit_id}/delete")
def delivery_cue_hit_delete(project_id: int, cue_id: int, hit_id: int):
    """Remove a hit from a cue."""
    conn = db.connect()
    try:
        db.delete_hit(conn, project_id, cue_id, hit_id)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@router.post("/project/{project_id}/delivery/revision")
def delivery_revision(
    project_id: int,
    action: str = Form("log"),
    version_state: str = Form(""),
):
    """Revisions agent: log a round (increment used) or set the version state."""
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, project_id)
        if action == "version" and version_state in VERSION_STATES:
            db.update_delivery(conn, project_id, "version_state", version_state)
        else:  # log a revision round
            used = int(delivery.get("revisions_used") or 0) + 1
            db.update_delivery(conn, project_id, "revisions_used", used)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery", status_code=303)


# ── Production spine (ADR-0019): Directions + Creative Lock (operator actions). ───────
@router.post("/project/{project_id}/direction")
def project_direction(project_id: int, action: str = Form("add"), name: str = Form(""),
                      thesis: str = Form(""), direction_id: str = Form(""),
                      status: str = Form(""), reason: str = Form("")):
    """Directions — the creative territories. Add one (name + thesis: the hero element), or
    decide its fate (selected / rejected — a rejection carries its WHY, which is what
    Relationship Intelligence learns from)."""
    conn = db.connect()
    try:
        if db.get_project(conn, project_id) is None:
            return HTMLResponse("Project not found", status_code=404)
        if action == "add":
            production.add_direction(conn, db, project_id, name=name, thesis=thesis)
        elif action == "decide":
            production.decide_direction(conn, db, project_id, direction_id,
                                        status=status, reason=reason)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#directions", status_code=303)


@router.post("/project/{project_id}/creative-lock")
def project_creative_lock(project_id: int, action: str = Form("set")):
    """Creative Lock — the hinge of the lifecycle (ADR-0019). Ends the revision economy:
    changes after lock are scope/conform conversations; production spend is authorized."""
    conn = db.connect()
    try:
        if db.get_project(conn, project_id) is None:
            return HTMLResponse("Project not found", status_code=404)
        delivery = db.get_delivery(conn, project_id)
        if action == "clear":
            production.clear_creative_lock(conn, db, project_id)
        else:
            cur = current_version(delivery) or {}
            production.set_creative_lock(conn, db, project_id,
                                         version_n=cur.get("n") or 0)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#directions", status_code=303)


@router.post("/project/{project_id}/delivery/asset")
async def delivery_asset(
    project_id: int,
    request: Request,
    label: str = Form(""),
    action: str = Form("add"),
    filename: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """Assets agent: upload (or remove) a deliverable file into the project's
    ``delivery_json['assets']`` list. Reuses the doc_upload audio/file handling and
    the local upload_dir() + /uploads/{name} mechanism (no S3/R2)."""
    conn = db.connect()
    try:
        if action == "remove" and filename.strip():
            base = os.path.basename(filename.strip())
            delivery = db.get_delivery(conn, project_id)
            assets = [
                a for a in list(delivery.get("assets") or [])
                if a.get("filename") != base
            ]
            db.update_delivery(conn, project_id, "assets", assets or None)
            try:
                os.remove(os.path.join(upload_dir(), base))
            except OSError:
                pass
            return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)

        if file is None or not (file.filename or "").strip():
            return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)

        ext = os.path.splitext(file.filename)[1].lower()
        ctype = (file.content_type or "").lower()
        kind = "audio" if (ext in _AUDIO_EXTS or ctype.startswith("audio/")) else "file"
        data = await file.read()

        # Safe, unique on-disk name: project-scoped + a counter so re-uploads don't clash.
        existing = {
            a.get("filename")
            for a in (db.get_delivery(conn, project_id).get("assets") or [])
        }
        safe_ext = ext if ext else (".mp3" if kind == "audio" else ".bin")
        n = 1
        while f"proj{project_id}-{n}{safe_ext}" in existing or os.path.exists(
            os.path.join(upload_dir(), f"proj{project_id}-{n}{safe_ext}")
        ):
            n += 1
        safe_name = f"proj{project_id}-{n}{safe_ext}"
        _persist_upload(conn, safe_name, data)

        delivery = db.get_delivery(conn, project_id)
        assets = list(delivery.get("assets") or [])
        assets.append({
            "label": label.strip() or file.filename,
            "url": f"/uploads/{safe_name}",
            "filename": safe_name,
            "kind": kind,
        })
        db.update_delivery(conn, project_id, "assets", assets)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)


def _next_version_label(delivery: dict, *, final: bool = False) -> tuple:
    """The next version's ``(n, label)`` for a logged version upload.

    n is one past the latest logged version (1 for the first). The label follows
    the v1 Concept → v2 Direction-lock → v3 FINAL ladder, forced to FINAL when the
    delivery is being released/approved (``final=True``)."""
    n = len(versions_list(delivery)) + 1
    return n, version_label(n, final=final)


def _master_stem(conn, project_id: int, row, n: int, label: str) -> str:
    """The deterministic filename stem for a project's master version (ADR-0037).

    THE one place a version is named. Both upload doors — the operator's console and
    the composer's portal — park a file as a pending submission, and
    ``_publish_pending_submission`` names it here on publish, so a version cannot be
    named differently depending on who uploaded it. (This docstring used to say the two
    paths "go through here", which was aspirational: the second path was
    ``_append_version_from_bytes``, a function with no callers since the first commit,
    deleted 2026-08-05.) Previously the namer called
    ``version_name(campaign, "Master", 60, "Master", n, f"v{n}")``, which produced
    e.g. ``SUMMER_Master_60_MASTER_v1_V1``: a hardcoded :60 on a brief that never said
    :60, the word Master twice (once filling the CUE slot), and the version number
    twice (``f"v{n}"`` landing in the STATE slot, which is for FINAL).

    Length comes from what the brief STATES — the project's need plus the linked
    opportunity's need/description — and is omitted when nothing states one. A master
    spans the whole piece, so there is no cue to name; that slot stays empty.
    """
    campaign = (row["need"] if row is not None else "") or "Campaign"
    text = campaign
    opp_id = row["opp_id"] if row is not None and "opp_id" in row.keys() else None
    if opp_id:
        opp_row = db.get_opportunity(conn, opp_id)
        if opp_row is not None:
            text = f"{campaign} {opp_row['need'] or ''} {opp_row['description'] or ''}"
    return version_name(
        campaign, "", stated_length(text) or "", "Master", n,
        "FINAL" if "FINAL" in label.upper() else "",
    )


def _publish_pending_submission(conn, project_id: int):
    """Move the pending creator submission into the live version ladder (Jon's
    'Publish to client' press). Returns ``(label, campaign)`` for the client-direction
    notification, or ``None`` if there was nothing pending."""
    from datetime import datetime as _dt, timezone as _tz
    delivery = db.get_delivery(conn, project_id)
    pv = delivery.get("pending_version")
    if not pv:
        return None
    versions = versions_list(delivery)
    n, label = _next_version_label(delivery)
    row = db.get_project(conn, project_id)
    campaign = (row["need"] if row is not None else "") or "Campaign"
    stem = _master_stem(conn, project_id, row, n, label)
    versions.append({
        "n": n, "label": label, "url": pv.get("url"),
        "filename": pv.get("filename"), "name": stem,
        "created_at": _dt.now(_tz.utc).isoformat(),
        "from_creator": pv.get("by") or "",
    })
    db.update_delivery(conn, project_id, "versions", versions)
    db.update_delivery(conn, project_id, "version_state", label)
    db.update_delivery(conn, project_id, "pending_version", "")   # consumed
    # Publishing a version ALWAYS moves the ball to the client — the court is theirs now,
    # whatever it was before (fresh v1 from "In production", or a re-open after approval).
    db.update_delivery(conn, project_id, "state",
                       state_on_version_published(delivery))
    return label, campaign


@router.post("/project/{project_id}/delivery/version")
async def delivery_version(
    project_id: int,
    request: Request,
    action: str = Form("add"),
    filename: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """Revisions + Assets agents: log a new **version** of the master.

    Uploads an audio file into the project's ``delivery_json['versions']`` ladder
    (reusing the local upload_dir() + /uploads/{name} mechanism), names it
    deterministically, advances ``version_state`` to the new label, and — if the
    delivery had been Approved — reopens it to "In review" (a new version means the
    prior approval no longer stands). ``action=remove`` drops the newest version."""
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, project_id)
        versions = versions_list(delivery)

        # Remove the newest version (optional housekeeping).
        if action == "remove" and versions:
            dropped = versions[-1]
            db.update_delivery(conn, project_id, "versions", versions[:-1] or None)
            remaining = versions_list(db.get_delivery(conn, project_id))
            new_state = (remaining[-1]["label"] if remaining
                         else VERSION_STATES[0])
            db.update_delivery(conn, project_id, "version_state", new_state)
            try:
                os.remove(os.path.join(upload_dir(), os.path.basename(
                    dropped.get("filename") or "")))
            except OSError:
                pass
            return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)

        if file is None or not (file.filename or "").strip():
            return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)

        data = await file.read()
        # The taste gate is UNIVERSAL (operator feedback): every upload — even the operator's
        # own — lands as a pending submission FIRST, so nothing reaches the client until an
        # explicit "Publish to client" press. The operator reviews it on the console, then
        # publishes. "The machine proposes, Jon disposes" — for every version, no exceptions.
        _store_pending_submission(conn, project_id, data, file.filename, "Studio")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)


@router.post("/project/{project_id}/delivery/approve")
def delivery_approve(
    project_id: int,
    asset: str = Form(...),
    approver: str = Form(...),
):
    """Approvals agent: log a sign-off (approved_by + today's date) per asset."""
    from datetime import date as _date
    conn = db.connect()
    try:
        if asset.strip() and approver.strip():
            delivery = db.get_delivery(conn, project_id)
            approvals = list(delivery.get("approvals") or [])
            approvals.append({
                "asset": asset.strip(),
                "approver": approver.strip(),
                "date": _date.today().isoformat(),
            })
            db.update_delivery(conn, project_id, "approvals", approvals)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery", status_code=303)


@router.post("/project/{project_id}/delivery/release")
def delivery_release(project_id: int):
    """Approvals agent: mark the delivery Released (state + released_at stamp).

    IP3: REFUSES to release until the license has been explicitly confirmed (the
    "Confirm license terms" console action). Without confirmation the certificate
    would assert a silent perpetual/worldwide/exclusive buyout — so we bounce back
    to the console with a flag instead of releasing."""
    from datetime import date as _date
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, project_id)
        allowed, _why = can_release(delivery)      # the rule lives in the engine
        if not allowed:
            return RedirectResponse(
                f"/project/{project_id}/delivery?release=needs_license#delivery",
                status_code=303,
            )
        db.update_delivery(conn, project_id, "state", "Released")
        db.update_delivery(conn, project_id, "released_at", _date.today().isoformat())
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#delivery", status_code=303)


@router.post("/project/{project_id}/delivery/ship")
def delivery_ship(project_id: int):
    """Operator action: finalize + ship the delivery when it's READY (master approved,
    every deliverable uploaded + signed off) but hasn't shipped — e.g. after a reopen/
    un-ship, where nothing re-triggers the automatic finalize. Assembles the package and
    flips to Delivered (idempotent; ships only if genuinely ready)."""
    conn = db.connect()
    shipped = False
    try:
        shipped = _maybe_finalize_delivery(conn, project_id)
    finally:
        conn.close()
    flag = "" if shipped else "?ship=not_ready"
    return RedirectResponse(f"/project/{project_id}/delivery{flag}#delivery", status_code=303)


@router.get("/project/{project_id}/delivery-portal", response_class=HTMLResponse)
def delivery_portal(request: Request, project_id: int, k: str = "", v: str = "",
                    r: str = ""):
    """The client-facing, token-gated delivery page. NOT admin-gated — access is by
    one of two tokens:

    * ``?k=<share_token>`` — the generic share link: view + comment as a **guest**
      (still name + email), but the Approve control is disabled.
    * ``?r=<reviewer_token>`` — a **verified** reviewer's personal invite link:
      their name + email are taken (locked) from the roster and they may approve.

    ``r`` is itself an access token (it grants the same view as ``k``), so a valid
    ``r`` works on its own — no ``k`` required.

    ``?v=<n>`` (IP2) selects which logged version the review surface opens — its
    track plays and its comments show — so the reviewer can A/B any round."""
    conn = db.connect()
    try:
        row = db.get_project(conn, project_id)
        token = db.ensure_project_share_token(conn, project_id) if row is not None else None
        delivery = db.get_delivery(conn, project_id) if row is not None else {}
        verified = reviewer_from_token(delivery, r)
        k_ok = bool(token and k and hmac.compare_digest(str(k), str(token)))
        # A verified reviewer token grants access on its own; otherwise the share
        # token must match. A missing project / no valid token 404s identically.
        if row is None or not (k_ok or verified is not None):
            return HTMLResponse("Not found", status_code=404)
        view = _delivery_view(conn, project_id, selected_v=v, client_view=True)
    finally:
        conn.close()
    # The share token is what the page's generic forms carry. If the reviewer
    # arrived only via ?r= (no k), surface the project share token so guest forms
    # still work; verified actions carry ?r= instead.
    view["share_token"] = view.get("share_token") or token
    if verified is not None:
        # Verified reviewer: identity is LOCKED to the roster (not editable, not
        # spoofable by typing a different name) and Approve is enabled.
        view["reviewer_token"] = verified["token"]
        view["verified"] = True
        view["reviewer"] = {
            "name": verified.get("name") or "", "email": verified.get("email") or "",
            "role": verified.get("role") or "", "known": True, "verified": True,
        }
    else:
        # Guest (share-link) mode: free-entry identity for commenting, no approve.
        view["reviewer_token"] = ""
        view["verified"] = False
        r_name, r_email = _reviewer_identity(request)
        view["reviewer"] = {"name": r_name, "email": r_email,
                            "known": bool(r_name and r_email), "verified": False}
    return render(request, "delivery_portal.html", nav="", **view)


def _review_token_ok(conn, project_id: int, k: str) -> bool:
    """The per-project share token is the access control for client review actions."""
    row = db.get_project(conn, project_id)
    if row is None:
        return False
    token = db.ensure_project_share_token(conn, project_id)
    return bool(token and k and hmac.compare_digest(str(k), str(token)))


def reviewer_from_token(delivery: dict, r: str):
    """Resolve a verified reviewer from their personal token (``?r=``), or None.

    The roster (``delivery_json['reviewers']``) is the set of named, operator-invited
    reviewers; a matching token means the reviewer is *verified* — their name + email
    come from the roster (not free-typed) and they may approve. Constant-time match."""
    r = (r or "").strip()
    if not r:
        return None
    for rv in (delivery.get("reviewers") or []):
        tok = (rv.get("token") or "") if isinstance(rv, dict) else ""
        if tok and hmac.compare_digest(str(r), str(tok)):
            return rv
    return None


def _access_ok(conn, project_id: int, k: str, r: str):
    """Resolve portal-action access: either a valid share token (``k``, guest) or a
    verified reviewer token (``r``). Returns ``(ok, reviewer_or_None)`` — ``reviewer``
    is the roster dict when the request came in on a verified ``?r=`` link."""
    delivery = db.get_delivery(conn, project_id)
    reviewer = reviewer_from_token(delivery, r)
    if reviewer is not None:
        return True, reviewer
    return _review_token_ok(conn, project_id, k), None


# Delivery OS IP1 (trust & coordination): the reviewer sets their identity (name +
# email) once; we remember it in a cookie so they never retype it, and every
# comment/approve/change-request is attributed to a real email, not free text.
REVIEWER_COOKIE = "cdl_reviewer"


def _reviewer_identity(request: Request, author: str = "", email: str = ""):
    """Resolve the reviewer's (name, email): a freshly-posted identity wins, else
    fall back to the remembered cookie. Returns ``(name, email)`` (either blank)."""
    name = (author or "").strip()
    mail = (email or "").strip()
    if not name or not mail:
        cookie = request.cookies.get(REVIEWER_COOKIE) or ""
        if cookie:
            try:
                saved = json.loads(unquote(cookie))
                name = name or (saved.get("name") or "").strip()
                mail = mail or (saved.get("email") or "").strip()
            except Exception:  # noqa: BLE001 — a malformed cookie just means "ask again"
                pass
    return name, mail


def _set_reviewer_cookie(resp, name: str, email: str) -> None:
    """Remember the reviewer's identity so they set it once, not per action."""
    if not (name and email):
        return
    value = quote(json.dumps({"name": name, "email": email}))
    resp.set_cookie(
        REVIEWER_COOKIE, value, samesite="lax", max_age=60 * 60 * 24 * 180,
    )


def _reviewer_review_url(project_id: int, token: str) -> str:
    """A reviewer's PERSONAL review link as an absolute URL (the ``?r=`` invite)."""
    return f"{_public_base()}/project/{project_id}/delivery-portal?r={token}"


def _email_reviewer_link(project_id: int, reviewer: dict, campaign: str,
                         *, subject: str, lead: str) -> str:
    """Best-effort: email one roster reviewer their personal review link.

    Skips reviewers without an email and never raises (the mailer itself is
    best-effort). Returns the mailer status for the caller's bookkeeping."""
    email = (reviewer.get("email") or "").strip()
    token = (reviewer.get("token") or "").strip()
    if not email or not token:
        return "skipped"
    url = _reviewer_review_url(project_id, token)
    name = (reviewer.get("name") or "there").strip() or "there"
    text = (
        f"Hi {name},\n\n{lead}\n\n"
        f"Campaign: {campaign}\n\n"
        f"Open your personal review link to listen, comment, and approve:\n{url}\n\n"
        "This link is yours — it's how you sign off on the work.\n\n"
        "— Chordential"
    )
    try:
        return mailer.send_email(email, subject, text)
    except Exception:  # noqa: BLE001 — mail is additive + best-effort, never block
        return "error"


def _notify_reviewers_new_version(project_id: int, campaign: str, label: str,
                                  reviewers: list) -> None:
    """Agency-direction notification: when a new version is uploaded, email each
    roster reviewer (who has an email) their personal review link. Best-effort,
    per reviewer — never blocks the upload (this was the documented TODO)."""
    subject = f"New version ready — {campaign}"
    lead = (
        f"A new version ({label}) is ready for your review."
    )
    for rv in (reviewers or []):
        try:
            _email_reviewer_link(project_id, rv, campaign, subject=subject, lead=lead)
        except Exception:  # noqa: BLE001 — one reviewer's failure must not stop the rest
            pass


def _review_redirect(project_id: int, k: str, *, name: str = "", email: str = "",
                     r: str = "", flag: str = ""):
    """Bounce back to the portal after an action. A verified reviewer link (``r``)
    is preserved so the reviewer stays verified; otherwise the share token (``k``).

    ``flag`` (e.g. ``incomplete``) surfaces a portal notice — used by the
    delivery-completeness gate to explain why an approve did NOT deliver."""
    extra = f"&gate={flag}" if (flag or "").strip() else ""
    if (r or "").strip():
        url = f"/project/{project_id}/delivery-portal?r={r}{extra}#review"
    else:
        url = f"/project/{project_id}/delivery-portal?k={k}{extra}#review"
    resp = RedirectResponse(url, status_code=303)
    # Only remember a *guest's* self-typed identity in the cookie — a verified
    # reviewer's identity lives on the roster, not the device.
    if not (r or "").strip():
        _set_reviewer_cookie(resp, name, email)
    return resp


@router.post("/project/{project_id}/review/comment")
def review_comment(
    request: Request, project_id: int, k: str = Form(""), author: str = Form(""),
    email: str = Form(""), t: str = Form(""), body: str = Form(""),
    parent_id: str = Form(""), r: str = Form(""), t_end: str = Form(""),
):
    """A timecoded comment pinned to the version under review (Frame.io-style).

    Accepts either a share token (``k``, guest) or a verified reviewer token
    (``r``). When verified, the comment is attributed to the roster identity and
    marked verified (not free-typed).

    ``parent_id`` (IP2) makes this a reply threaded one level under that comment —
    a reply answers its parent so it carries no timecode of its own."""
    conn = db.connect()
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        if reviewer is not None:
            name, mail = (reviewer.get("name") or ""), (reviewer.get("email") or "")
        else:
            name, mail = _reviewer_identity(request, author, email)
        # Identity is required so events attribute to a real person, not free text.
        if body.strip() and name and mail:
            # A reply nests under its parent (no timecode); a top-level note carries
            # the live playhead's timecode.
            parent = None
            if str(parent_id).strip():
                p = db.get_review_comment(conn, int(parent_id)) \
                    if str(parent_id).strip().isdigit() else None
                if p is not None and p["project_id"] == project_id:
                    parent = int(parent_id)
            if parent is not None:
                t_seconds = None
            else:
                try:
                    t_seconds = float(t) if str(t).strip() != "" else None
                except ValueError:
                    t_seconds = None
                # A non-finite timecode (inf/nan — anyone with the share token can
                # POST one) round-trips SQLite REAL and then 500s every template
                # that formats it (creator portal, delivery portal, console).
                # Guard once at the write site; negatives are equally meaningless.
                # …and the same 24h sanity cap cues use, so a guest can't plant a
                # garbled "1666666666666:40" label in the client feed (eng P2).
                if t_seconds is not None and (
                        not math.isfinite(t_seconds) or t_seconds < 0
                        or t_seconds > db._MAX_TIMECODE_SECONDS):
                    t_seconds = None
            project = db.get_project(conn, project_id)
            delivery = db.get_delivery(conn, project_id)
            # Phase 4: an optional end timecode makes this a RANGE note (a span of
            # the picture), guarded the same way as the start. Ignored on replies.
            t_end_val = None
            if parent is None and str(t_end).strip() != "":
                try:
                    _te = float(t_end)
                    if math.isfinite(_te) and _te >= 0:
                        t_end_val = _te
                except ValueError:
                    t_end_val = None
            db.add_review_comment(
                conn, project_id, version=_current_version_tag(delivery),
                t_seconds=t_seconds, t_end=t_end_val, author=name, email=mail,
                body=body.strip(), kind="comment", parent_id=parent,
                verified=reviewer is not None,
            )
            verb = "replied" if parent is not None else "commented"
            # Session Room bus: the comment becomes an event everyone in the
            # room may see (client-side act; audience = all roles).
            db.add_project_event(
                conn, project_id, "comment", actor_role="client",
                actor_name=name, body=body.strip()[:200],
            )
            _notify_operator_review(
                project_id, project,
                title=f"{_campaign_label(project)} — new note",
                body=f"{name} {verb}: {body.strip()[:120]}",
            )
    finally:
        conn.close()
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


_PRESENCE_TTL = 90            # seconds; single-worker deployment, honest scope


def _session_role(conn, project_id: int, k: str, r: str):
    """Resolve the caller's room role. A valid share/reviewer token → client;
    no token → operator (the login gate already protected the path)."""
    if k or r:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return None, ""
        return "client", ((reviewer or {}).get("name") or "Client")
    return "operator", "Studio"


@router.get("/project/{project_id}/session.json")
def session_room_poll(project_id: int, after: int = 0, k: str = "", r: str = ""):
    conn = db.connect()
    try:
        role, _name = _session_role(conn, project_id, k, r)
        if role is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        events = [
            {"id": e["id"], "kind": e["kind"], "role": e["actor_role"],
             "name": e["actor_name"], "body": e["body"], "at": e["created_at"]}
            for e in db.list_project_events(conn, project_id, role=role,
                                            after_id=after)
        ]
    finally:
        conn.close()
    import time as _t
    now = _t.time()
    room = _PRESENCE.get(project_id, {})
    alive = {kk: v for kk, v in room.items() if now - v[2] < _PRESENCE_TTL}
    _PRESENCE[project_id] = alive
    return {"events": events,
            "last": events[-1]["id"] if events else after,
            "presence": [{"name": v[0], "role": v[1]} for v in alive.values()]}


@router.post("/project/{project_id}/presence")
def session_room_presence(project_id: int, k: str = Form(""), r: str = Form(""),
                          name: str = Form("")):
    conn = db.connect()
    try:
        role, fallback = _session_role(conn, project_id, k, r)
    finally:
        conn.close()
    if role is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    import time as _t
    who = (name.strip() or fallback)[:40]
    _PRESENCE.setdefault(project_id, {})[f"{role}:{who}"] = (who, role, _t.time())
    return {"ok": True}


async def _store_picture(conn, project_id: int, file: UploadFile, by: str) -> Optional[dict]:
    """Store the client's cut as the room's PICTURE (Phase 2). The current cut is
    archived to ``picture_history`` and the cut number bumps — a new cut is a
    CONFORM event, never a revision (production model): notes from the prior cut
    get marked by the room. Returns the new picture dict, or None on a bad file."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _VIDEO_EXTS:
        return None
    data = await _read_capped(file, _CUT_MAX_BYTES)
    if not data:
        return None
    safe_name = f"proj{project_id}-cut-{os.urandom(5).hex()}{ext}"
    # ADR-0026: cuts mirror into the DB only under the threshold; larger cuts are
    # disk-only until the object-storage seam ships.
    _persist_upload(conn, safe_name, data, content_type=file.content_type or "",
                    mirror=len(data) <= _CUT_MIRROR_BYTES)
    delivery = db.get_delivery(conn, project_id)
    prior = delivery.get("picture") or None
    from datetime import datetime as _dt, timezone as _tz
    if len((by or "").strip()) < 2:
        by = "The client"                       # attribution fallback (EP P2-3)
    pic = {"url": f"/uploads/{safe_name}", "filename": safe_name,
           "orig": file.filename, "by": by,
           "at": _dt.now(_tz.utc).isoformat(),
           "n": (int(prior.get("n") or 0) + 1) if prior else 1}
    if prior:
        hist = list(delivery.get("picture_history") or [])
        hist.append(prior)
        db.update_delivery(conn, project_id, "picture_history", hist)
    db.update_delivery(conn, project_id, "picture", pic)
    db.add_update(conn, project_id,
                  f"{by} uploaded cut {pic['n']} of the picture ({file.filename})."
                  + (" Notes from the prior cut are marked — changes it causes are"
                     " conforms, not revisions." if prior else ""))
    return pic


_REF_BLOCKED_EXTS = {".html", ".htm", ".svg", ".xml", ".xhtml", ".js", ".mjs"}


_REF_MAX_BYTES = int(os.environ.get("CHORDENTIAL_REF_MAX_MB", "128")) * 1024 * 1024


async def _store_reference(conn, project_id: int, file: UploadFile, by: str,
                           label: str = "") -> Optional[dict]:
    """Store an audible/visual REFERENCE for the composer (Phase 2 pull-forward:
    'Bonobo' is a career, not a reference — give them the actual track).

    Markup/script extensions are rejected outright (stored-XSS lane — review P0)
    and the serving layer additionally forces attachment on anything non-media."""
    # Normalize before the blocklist check: os.path.splitext("evil.html.") yields
    # ".", sneaking markup past a raw ext test (eng P2). Strip trailing dots/space.
    ext = os.path.splitext((file.filename or "").rstrip(". ").strip())[1].lower()
    if ext in _REF_BLOCKED_EXTS:
        return None
    data = await _read_capped(file, _REF_MAX_BYTES)
    if not data:
        return None
    kind = ("audio" if ext in _AUDIO_EXTS else
            "video" if ext in _VIDEO_EXTS else "file")
    safe_name = f"proj{project_id}-ref-{os.urandom(5).hex()}{ext or '.bin'}"
    # ADR-0026 mirror cap applies to references too — a 128MB video reference must
    # not blob into SQLite (eng P0: this path defaulted mirror=True, defeating the
    # ADR). Disk always; DB mirror only under the same threshold as a cut.
    _persist_upload(conn, safe_name, data, content_type=file.content_type or "",
                    mirror=len(data) <= _CUT_MIRROR_BYTES)
    delivery = db.get_delivery(conn, project_id)
    refs = list(delivery.get("references") or [])
    from datetime import datetime as _dt, timezone as _tz
    ref = {"label": (label or "").strip() or (file.filename or "Reference"),
           "url": f"/uploads/{safe_name}", "filename": safe_name, "kind": kind,
           "by": by, "at": _dt.now(_tz.utc).isoformat()}
    refs.append(ref)
    db.update_delivery(conn, project_id, "references", refs)
    db.add_update(conn, project_id, f"{by} added a reference: {ref['label']}.")
    return ref


@router.post("/project/{project_id}/review/picture")
async def review_upload_picture(
    request: Request, project_id: int, k: str = Form(""), r: str = Form(""),
    author: str = Form(""), email: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """The client door's Drop: upload the cut the music is written to. Token-gated
    like every review action; the room dresses itself around the picture."""
    conn = db.connect()
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        who = (reviewer.get("name") if reviewer else "") or author.strip() or "The client"
        pic = None
        if file is not None and (file.filename or "").strip():
            pic = await _store_picture(conn, project_id, file, who)
        project = db.get_project(conn, project_id)
    finally:
        conn.close()
    if pic is not None:
        await run_in_threadpool(
            _notify_operator_review, project_id, project,
            f"Picture uploaded — {_campaign_label(project) if project else 'campaign'}",
            f"{pic['by']} uploaded cut {pic['n']}. The composer's room now carries it.")
        await run_in_threadpool(
            _notify_assigned_creators, project_id, project,
            subject=f"The picture is in — cut {pic['n']}",
            body_text=("The client's cut just landed in your session room — the picture "
                       "is waiting for your music."))
    return _review_redirect(project_id, k, name=author, email=email, r=r)


@router.post("/project/{project_id}/review/reference")
async def review_upload_reference(
    request: Request, project_id: int, k: str = Form(""), r: str = Form(""),
    author: str = Form(""), email: str = Form(""), label: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """The client adds a hearable/viewable reference for the composer."""
    conn = db.connect()
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        who = (reviewer.get("name") if reviewer else "") or author.strip() or "The client"
        ref = None
        if file is not None and (file.filename or "").strip():
            ref = await _store_reference(conn, project_id, file, who, label=label)
        project = db.get_project(conn, project_id)
    finally:
        conn.close()
    if ref is not None:
        # the studio hears about every client reference (temp-love / rights lane —
        # EP review): the operator can veto before the composer leans on it
        await run_in_threadpool(
            _notify_operator_review, project_id, project,
            f"Client reference — {_campaign_label(project) if project else 'campaign'}",
            f"{ref['by']} added '{ref['label']}'. Listen before the composer leans on it.")
    return _review_redirect(project_id, k, name=author, email=email, r=r)


@router.post("/project/{project_id}/delivery/picture")
async def delivery_upload_picture(project_id: int,
                                  file: Optional[UploadFile] = File(None)):
    """Operator door: log the client's cut from the console (email handoffs
    happen; the room should still get the picture)."""
    conn = db.connect()
    try:
        pic = None
        if file is not None and (file.filename or "").strip():
            pic = await _store_picture(conn, project_id, file, "The studio")
        project = db.get_project(conn, project_id)
    finally:
        conn.close()
    if pic is not None:
        await run_in_threadpool(
            _notify_assigned_creators, project_id, project,
            subject=f"The picture is in — cut {pic['n']}",
            body_text=("The cut just landed in your session room — the picture is "
                       "waiting for your music."))
    return RedirectResponse(f"/project/{project_id}/delivery#picture", status_code=303)


@router.post("/project/{project_id}/delivery/reference")
async def delivery_upload_reference(project_id: int, label: str = Form(""),
                                    file: Optional[UploadFile] = File(None)):
    """Operator door: add a reference for the composer."""
    conn = db.connect()
    try:
        if file is not None and (file.filename or "").strip():
            await _store_reference(conn, project_id, file, "The studio", label=label)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#picture", status_code=303)


@router.post("/project/{project_id}/review/resolve")
def review_resolve(
    request: Request, project_id: int, k: str = Form(""),
    author: str = Form(""), email: str = Form(""), comment_id: str = Form(""),
    r: str = Form(""),
):
    """Toggle a comment's resolved flag (IP2 — Frame.io's resolve checkbox).

    Token-gated like the other review actions (share token ``k`` guest OR verified
    reviewer ``r``), and (like approve/changes) requires a complete reviewer
    identity so a resolve is attributable, not anonymous."""
    conn = db.connect()
    name, mail = "", ""
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        if reviewer is not None:
            name, mail = (reviewer.get("name") or ""), (reviewer.get("email") or "")
        else:
            name, mail = _reviewer_identity(request, author, email)
        if name and mail and str(comment_id).strip().isdigit():
            db.toggle_comment_resolved(conn, project_id, int(comment_id))
    finally:
        conn.close()
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


@router.post("/project/{project_id}/review/approve")
def review_approve(
    request: Request, project_id: int, k: str = Form(""),
    author: str = Form(""), email: str = Form(""), r: str = Form(""),
    deliver_partial: str = Form(""),
):
    """The agency approves the current version — the trigger for Delivery
    Automation (Phase 3). Records the sign-off, locks the FINAL version, then
    **assembles the delivery package** (organise → document → convert → ZIP) and
    flips state to Delivered with the founder's payoff checklist + ZIP url stored.

    Identity, two strengths (ADR-0020 — the client's single approval IS the award, so
    it must not be gated behind a link they may not have): a **verified reviewer link**
    (``?r=<reviewer_token>``) signs with the roster's LOCKED name + email, unspoofable;
    the workspace share link (``?k=``) may also approve, signing with a captured name +
    email, which is intent enough under ESIGN/UETA. Both paths record who and when.

    Note what that means operationally: the share link is forwardable, so anyone holding
    it can approve under any typed name. That is accepted, not overlooked — the mitigation
    is reviewer links for consequential sign-off and treating ``?k=`` as a bearer token.
    """
    conn = db.connect()
    name, mail = "", ""
    try:
        # Access still resolves on either token (so a stale ?k= form 404s vs no-ops
        # consistently with the other actions); the *approve gate* is stricter below.
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        # Identity gate (ADR-0020): the client can approve from their OWN share link —
        # a captured name + email is intent enough (ESIGN/UETA-sufficient), and it's their
        # durable token. A verified reviewer link is the STRONGER path (locked roster
        # identity), not the only one. Either way the sign-off records who + when.
        if reviewer is not None:
            name = (reviewer.get("name") or "").strip()
            mail = (reviewer.get("email") or "").strip()
        else:
            name, mail = _reviewer_identity(request, author, email)
        if not (name and mail):
            return _review_redirect(project_id, k, r=r, flag="identify")
        # Approving the master version records the CREATIVE approval (Creative Lock). It no
        # longer ships an incomplete package — the full download unlocks only when every
        # deliverable is uploaded + signed off (_maybe_finalize_delivery). So there's no
        # partial-opt-in to gate here; the client can always approve the creative.
        _approve_version_core(conn, project_id, name, mail)   # notifies creators + operator
    finally:
        conn.close()
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


@router.post("/project/{project_id}/review/reopen")
def review_reopen(request: Request, project_id: int, k: str = Form(""), r: str = Form("")):
    """Un-approve / reopen — approval is NOT a one-way door (operator feedback). Clears the
    Creative Lock, drops the FINAL label back to its round label, and returns the project to
    'In review'. Available to the operator (console, no token) or the client (their link)."""
    conn = db.connect()
    try:
        if k or r:                                    # a client action — validate the token
            ok, _rev = _access_ok(conn, project_id, k, r)
            if not ok:
                return HTMLResponse("Not found", status_code=404)
        row = db.get_project(conn, project_id)
        if row is None:
            return HTMLResponse("Project not found", status_code=404)
        delivery = db.get_delivery(conn, project_id)
        state = (delivery.get("state") or "").strip()
        if state in ("Delivered", "Released"):
            # UN-SHIP: the package went out, but pull it back to the DELIVERABLE SIGN-OFF
            # stage — the master stays approved and every prior per-deliverable sign-off is
            # preserved; only the shipped package + the client download are undone. So the
            # operator (or client) can revisit a single deliverable without redoing the master.
            db.update_delivery(conn, project_id, "state",
                               state_on_client_approved(delivery))
            db.update_delivery(conn, project_id, "download_unlocked", False)
            db.update_delivery(conn, project_id, "delivery_zip", None)
            db.add_project_event(conn, project_id, "reopened", actor_role="operator",
                                 actor_name="Studio",
                                 body="Delivery reopened — back to deliverable sign-off.")
        else:
            # Reopen the CREATIVE (master): back to review, master un-approved.
            production.clear_creative_lock(conn, db, project_id)
            versions = versions_list(delivery)
            if versions:
                versions[-1] = dict(versions[-1])
                versions[-1]["label"] = version_label(versions[-1]["n"], final=False)
                db.update_delivery(conn, project_id, "versions", versions)
                db.update_delivery(conn, project_id, "version_state", versions[-1]["label"])
            db.update_delivery(conn, project_id, "state",
                               state_on_approval_reopened(delivery))
            db.update_delivery(conn, project_id, "download_unlocked", False)
            db.add_project_event(conn, project_id, "reopened", actor_role="operator",
                                 actor_name="Studio", body="Approval reopened — back in review.")
    finally:
        conn.close()
    if k or r:
        return _review_redirect(project_id, k, r=r)
    return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)


@router.post("/project/{project_id}/delivery/build")
def delivery_build(project_id: int):
    """Admin: (re)build the delivery package by hand — same automation as APPROVE
    triggers, for when assets/versions changed after delivery (idempotent rebuild)."""
    conn = db.connect()
    try:
        pkg = _build_delivery_package(conn, project_id)
        if pkg is None:
            return HTMLResponse("Project not found", status_code=404)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#delivery", status_code=303)


@router.post("/project/{project_id}/review/note/{comment_id}/species")
def review_note_species(project_id: int, comment_id: int):
    """Operator door: classify a note as conform (picture-caused, free) or
    revision (counts against rounds) — the round ledger's species record.

    Classifying a change request as a conform RETURNS its round to the budget
    (and flipping back consumes one again, floored at zero). Without this the
    'conform · free' label was cosmetic — the round was already spent at
    request time and nothing gave it back (EP review P0). This keeps the one
    ``revisions_used`` counter — read identically by console, portal, and the
    composer room — actually honest."""
    conn = db.connect()
    try:
        new_val = db.toggle_comment_conform(conn, project_id, comment_id)
        if new_val is not None:
            crow = conn.execute(
                "SELECT kind FROM review_comments WHERE id = ? AND project_id = ?",
                (comment_id, project_id)).fetchone()
            # Only change requests consume rounds; praise/comments never did.
            if crow is not None and crow["kind"] == "change_request":
                delivery = db.get_delivery(conn, project_id)
                used = int(delivery.get("revisions_used") or 0)
                used = max(0, used - 1) if new_val == 1 else used + 1
                db.update_delivery(conn, project_id, "revisions_used", used)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)


@router.post("/project/{project_id}/delivery/asset/publish")
def delivery_publish_asset(project_id: int, filename: str = Form(""),
                           action: str = Form("publish")):
    """Jon's disposition of a creator's pending DELIVERABLE (stems, cutdowns,
    verticals): publish it into the client-visible assets, or discard it. The same
    gate the master gets — uniform, per the EP review (unvetted stems on delivery
    night were the hole)."""
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, project_id)
        pending = list(delivery.get("pending_assets") or [])
        hit = next((a for a in pending if a.get("filename") == filename), None)
        if hit is None:
            return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)
        pending = [a for a in pending if a.get("filename") != filename]
        db.update_delivery(conn, project_id, "pending_assets", pending)
        if action == "discard":
            # A rejected deliverable must not stay downloadable: remove the blob
            # (best-effort, path-guarded inside upload_dir() — engineering P2).
            try:
                blob = os.path.realpath(os.path.join(upload_dir(), hit.get("filename") or ""))
                if blob.startswith(os.path.realpath(upload_dir()) + os.sep) and os.path.isfile(blob):
                    os.remove(blob)
            except OSError:
                pass
            db.add_update(conn, project_id,
                          f"Sent back the pending deliverable '{hit.get('label')}'.")
        else:
            assets = list(delivery.get("assets") or [])
            assets.append({"label": hit.get("label"), "url": hit.get("url"),
                           "filename": hit.get("filename"), "kind": hit.get("kind")})
            db.update_delivery(conn, project_id, "assets", assets)
            db.add_update(conn, project_id,
                          f"Published '{hit.get('label')}' — ready for client sign-off.")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)


@router.post("/project/{project_id}/delivery/publish")
def delivery_publish(project_id: int, action: str = Form("publish")):
    """Jon's disposition of a creator's pending submission: publish it to the client
    (moves it into the version ladder and notifies the reviewers) or discard it. The
    gate that keeps unvetted creator work off the client's portal."""
    conn = db.connect()
    result = None
    reviewers = []
    try:
        project = db.get_project(conn, project_id)
        if project is None:
            return HTMLResponse("Project not found", status_code=404)
        delivery = db.get_delivery(conn, project_id)
        if not delivery.get("pending_version"):
            return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)
        if action == "discard":
            db.update_delivery(conn, project_id, "pending_version", "")
            db.add_update(conn, project_id, "Discarded the pending creator submission.")
        else:
            result = _publish_pending_submission(conn, project_id)
            if result is not None:
                db.add_update(conn, project_id, f"Published {result[0]} to the client.")
                reviewers = db.list_delivery_reviewers(conn, project_id)
                # The client's own workspace contact — the person the version is FOR — is
                # notified with their durable link, not just the reviewer roster.
                client_email = client_name = client_token = ""
                opp = db.get_opportunity(conn, project["opp_id"]) if project["opp_id"] else None
                if opp is not None:
                    client_email = (opp["contact_email"] or "").strip()
                    client_name = (opp["contact_name"] or "").strip()
                    client_token = db.ensure_share_token(conn, opp["id"])
    finally:
        conn.close()
    # Client-direction notification only on a real publish — off the request thread.
    if result is not None:
        label, campaign = result
        signals.fire_and_forget(
            _notify_reviewers_new_version, project_id, campaign, label, reviewers)
        if client_email:
            portal_url = f"{_public_base()}/project/{project_id}/delivery-portal?k={client_token}"
            signals.fire_and_forget(
                _notify_client_new_version, client_email, client_name, campaign, label,
                client_token, portal_url)
    return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)


def _notify_client_new_version(email: str, name: str, campaign: str, label: str, token: str,
                               portal_url: str = ""):
    """Email the client that a new version is waiting — pointing straight at the listening
    room (the delivery portal) where they play it, comment, and approve. The review IS the
    action, so the link goes to the review surface, not the workspace shell."""
    if not (mailer.mail_configured() and email):
        return
    base = _public_base()
    who = (name or "there").strip()
    link = portal_url or f"{base}/workspace/{token}"
    text = (f"Hi {who},\n\n{label} of {campaign} is ready for you to hear. Open the listening "
            f"room to play it, leave timecoded notes, or approve it:\n\n"
            f"{link}\n\n— Chordential")
    try:
        mailer.send_email(email, f"A new version is ready — {campaign}", text,
                          html=mailer.branded_html(base, text))
    except Exception:  # noqa: BLE001 — best-effort
        pass


@router.post("/project/{project_id}/review/changes")
def review_changes(
    request: Request, project_id: int, k: str = Form(""),
    author: str = Form(""), email: str = Form(""), note: str = Form(""),
    r: str = Form(""),
):
    """The agency requests changes — logs the request and bumps the revision count.
    Accepts a share token (``k``, guest) or a verified reviewer token (``r``);
    requires a complete identity (name + email) so the request is attributable."""
    conn = db.connect()
    name, mail = "", ""
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        if reviewer is not None:
            name, mail = (reviewer.get("name") or ""), (reviewer.get("email") or "")
        else:
            name, mail = _reviewer_identity(request, author, email)
        if not (name and mail):
            return _review_redirect(project_id, k, name=name, email=mail, r=r)
        delivery = db.get_delivery(conn, project_id)
        project = db.get_project(conn, project_id)
        note_text = note.strip() or "Requested changes."
        db.add_review_comment(
            conn, project_id, version=_current_version_tag(delivery),
            author=name, email=mail, body=note_text, kind="change_request",
            verified=reviewer is not None,
        )
        db.update_delivery(conn, project_id, "revisions_used",
                           int(delivery.get("revisions_used") or 0) + 1)
        # ADR-0019: the round LEDGER behind the counter — which version, who, what they said
        # (post-lock rounds are stamped so scope conversations have a record to stand on).
        production.log_round(conn, db, project_id,
                             version=_current_version_tag(delivery), by=name, note=note_text)
        db.update_delivery(conn, project_id, "state",
                           state_on_changes_requested(delivery))
        _notify_operator_review(
            project_id, project,
            title=f"{_campaign_label(project)} — changes requested by {name}",
            body=note_text[:160],
        )
    finally:
        conn.close()
    # Tell the assigned creator(s) directly, off the request thread — the composer
    # portal now shows the notes, and this is the nudge to go look.
    campaign = _campaign_label(project)
    signals.fire_and_forget(
        _notify_assigned_creators, project_id, project,
        subject=f"Changes requested — {campaign}",
        body_text=(f"The client requested changes on {campaign}:\n\n\"{note_text}\"\n\n"
                   "Open your creator portal to see the full timecoded feedback and "
                   "submit your next version."))
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


@router.post("/project/{project_id}/review/asset")
def review_asset(
    request: Request, project_id: int, k: str = Form(""),
    filename: str = Form(""), action: str = Form(""), note: str = Form(""),
    r: str = Form(""), author: str = Form(""), email: str = Form(""),
):
    """Per-asset approval: a VERIFIED reviewer signs off (or requests changes on) a
    single deliverable — the :60 master Approved while the :30 cutdown still awaits.

    Gated exactly like the version-level Approve: a valid verified reviewer link
    (``?r=``) is required. A share-link guest (``?k=`` only) sees per-asset status
    read-only — this route no-ops for them, so they cannot change a per-asset state.

    ``filename`` is the asset's stable key (its filename, or ``label:<slug>`` for a
    referenced-only asset). ``action`` is ``approve`` or ``changes``. The status is
    recorded with the roster identity + current version + date, logged into the
    review tape (kind ``asset_approval`` / ``asset_change``, body naming the asset),
    and the operator push fires."""
    conn = db.connect()
    name, mail = "", ""
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        # Per-deliverable sign-off is open to the identified client on their own share link
        # (operator feedback: the client approves each itemized deliverable before the full
        # download unlocks) — same captured-intent rule as the whole-version Approve. A
        # verified reviewer keeps their locked roster identity.
        if reviewer is not None:
            name = (reviewer.get("name") or "").strip()
            mail = (reviewer.get("email") or "").strip()
        else:
            name, mail = _reviewer_identity(request, author, email)
        key = (filename or "").strip()
        if not name or not key:
            return _review_redirect(project_id, k, r=r)
        delivery = db.get_delivery(conn, project_id)
        # Resolve the asset's display label for the tape (fall back to the key).
        label = key
        for a in (delivery.get("assets") or []):
            if db.asset_key(a) == key:
                label = (a.get("label") or a.get("filename") or key)
                break
        version = _current_version_tag(delivery)
        if action == "changes":
            status, kind = "Changes requested", "asset_change"
            note_text = note.strip() or "Requested changes."
            body = f"Changes requested on {label}: {note_text}"
        else:
            status, kind = "Approved", "asset_approval"
            body = f"Approved {label}."
        rec = db.set_asset_approval(
            conn, project_id, key, status=status, by=name, email=mail,
            version=version,
        )
        if rec is not None:
            project = db.get_project(conn, project_id)
            db.add_review_comment(
                conn, project_id, version=version, author=name, email=mail,
                body=body, kind=kind, verified=True,
            )
            verb = "requested changes on" if action == "changes" else "approved"
            _notify_operator_review(
                project_id, project,
                title=f"{_campaign_label(project)} — {label} {status.lower()}",
                body=f"{name} {verb} {label}.",
            )
            db.add_project_event(conn, project_id, kind.replace("asset_", "asset-"),
                                 actor_role="client", actor_name=name, body=body[:200])
            # When this sign-off was the LAST one needed (creative locked + every deliverable
            # uploaded + approved), the full package assembles + download unlocks. Approving
            # one deliverable never ships early — only the last approval opens the door.
            if action != "changes":
                _maybe_finalize_delivery(conn, project_id)
    finally:
        conn.close()
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


@router.post("/project/{project_id}/proposal")
def project_generate_proposal(project_id: int):
    """Generate a deterministic proposal for a project from the estimator."""
    conn = db.connect()
    try:
        prow = db.get_project(conn, project_id)
        if prow is None:
            return HTMLResponse("Project not found", status_code=404)
        opp_id = prow["opp_id"]
        if opp_id is None:
            return RedirectResponse(f"/project/{project_id}", status_code=303)
        row, opp, ev = _load(conn, opp_id)
        qual, scored = ev
        # ``project_id`` pulls in the assigned talent's own rates, so the
        # client-facing proposal reflects real assigned cost — not role defaults.
        est = estimate_for(opp, conn=conn, project_id=project_id, qual=qual)
        proposal = build_proposal(
            opp, qual, est, quote_band=_quote_band_for(conn, row, opp, est))
        db.insert_proposal(conn, project_id, opp_id, proposal)
        db.add_update(conn, project_id, "Proposal generated.", "proposal")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/proposal", status_code=303)


@router.get("/project/{project_id}/proposal", response_class=HTMLResponse)
def project_proposal_view(request: Request, project_id: int):
    conn = db.connect()
    try:
        prow = db.get_project(conn, project_id)
        if prow is None:
            return HTMLResponse("Project not found", status_code=404)
        proposal = db.proposal_for_project(conn, project_id)
        line_items = json.loads(proposal["line_items"]) if proposal and proposal["line_items"] else []
        terms = json.loads(proposal["terms"]) if proposal and proposal["terms"] else []
        invoices = db.list_invoices(conn, project_id)
    finally:
        conn.close()
    return render(
        request, "proposal_detail.html", nav="projects", project=prow,
        proposal=proposal, line_items=line_items, terms=terms, invoices=invoices,
        proposal_states=db.PROPOSAL_STATES, invoice_states=db.INVOICE_STATES,
    )


@router.get("/project/{project_id}/proposal.txt", response_class=PlainTextResponse)
def project_proposal_text(project_id: int):
    conn = db.connect()
    try:
        prow = db.get_project(conn, project_id)
        proposal = db.proposal_for_project(conn, project_id) if prow else None
    finally:
        conn.close()
    if proposal is None:
        return PlainTextResponse("No proposal yet", status_code=404)
    obj = _proposal_from_row(proposal)
    obj.client = prow["client"]
    obj.need = prow["need"]
    return PlainTextResponse(obj.render_text())


@router.post("/project/{project_id}/invoice")
def project_create_invoice(project_id: int, kind: str = Form(...)):
    """Issue a deposit or final invoice from the project's proposal."""
    conn = db.connect()
    try:
        prow = db.get_project(conn, project_id)
        prop = db.proposal_for_project(conn, project_id)
        if prow is None or prop is None:
            return RedirectResponse(f"/project/{project_id}/proposal", status_code=303)
        if not db.has_invoice(conn, project_id, kind):
            inv = _invoice_from_proposal_row(prow, prop, kind)
            db.insert_invoice(conn, project_id, prop["id"], inv)
            db.add_update(conn, project_id, f"{kind} invoice created.", "invoice")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/proposal", status_code=303)


@router.post("/project/{project_id}/pay")
def client_pay(project_id: int, k: str = Form(""), r: str = Form(""), kind: str = Form("final")):
    """Client-facing, token-gated: begin payment for the deposit or final invoice. Ensures the
    invoice exists, opens a provider checkout, and — with Stripe configured — redirects the
    client to the HOSTED checkout page. With the unconfigured Null provider it bounces back
    with an honest 'online payment isn't enabled yet' note (the studio can still collect and
    mark it paid). No admin gate: access is by the client's own share token."""
    conn = db.connect()
    kind = "Deposit" if kind.lower().startswith("dep") else "Final"
    # Where to bounce back on the honest null-provider fallback / errors: the deposit is
    # paid from the workspace, the final from the delivery portal.
    def _back(flag):
        if kind == "Deposit":
            prow0 = db.get_project(conn, project_id)
            if prow0 is not None and prow0["opp_id"]:
                return f"/workspace/{db.ensure_share_token(conn, prow0['opp_id'])}?{flag}"
        return _client_portal_url(project_id, k, flag)
    try:
        ok, _rev = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        prow = db.get_project(conn, project_id)
        prop = db.proposal_for_project(conn, project_id)
        if prow is None or prop is None:
            return RedirectResponse(_back("pay=error"), status_code=303)
        if not db.has_invoice(conn, project_id, kind):
            db.insert_invoice(conn, project_id, prop["id"], _invoice_from_proposal_row(prow, prop, kind))
        invoice = next((i for i in db.list_invoices(conn, project_id)
                        if (i["kind"] or "") == kind), None)
        if invoice is None:
            return RedirectResponse(_back("pay=error"), status_code=303)
        if (invoice["status"] or "").lower() in ("paid", "settled"):
            return RedirectResponse(_back("pay=already"), status_code=303)
        try:
            ref = get_payment_provider().create_checkout(invoice) or ""
        except Exception:  # noqa: BLE001 — never 500 the payer
            ref = ""
        if ref.startswith("http"):                     # Stripe hosted checkout
            db.update_invoice_status(conn, invoice["id"], "Issued", external_ref=ref)
            db.add_update(conn, project_id, f"{kind} checkout opened by the client.", "invoice")
            return RedirectResponse(ref, status_code=303)
        # Null / unconfigured provider — be honest, don't fake a charge.
        return RedirectResponse(_back("pay=unavailable"), status_code=303)
    finally:
        conn.close()
