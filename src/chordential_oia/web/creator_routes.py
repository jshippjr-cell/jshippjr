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
from typing import List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..delivery import (
    current_version, deliverable_owner, merge_license, owed_after, revision_status,
    role_key, scoped_deliverables, seed_brief, version_label, versions_list,
)
from .. import composer_agreement, contributor_release, signing
from ..talent import profile_completeness
from . import db, production, room
from .billing import final_invoice_block
from .delivery_ops import (
    scoped_signoff, _campaign_label, _notify_operator_review, _project_estimate,
    _sync_role_milestones,
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
    # Rows written before `author_role` existed carry a blank. Infer those from EVIDENCE
    # — the note's email against this project's assigned creators — never from the shape
    # of a name. Unknown resolves to `client`, which is the reading that keeps a buyer's
    # own words attributed to them; a studio note wrongly shown as the studio's is
    # nothing, and a client's note wrongly shown as ours would be a lie about who spoke.
    crew = {(a["talent_email"] or "").strip().lower()
            for a in db.list_assignments(conn, project_id) if a["talent_email"]}

    def _role_of(row) -> str:
        keys = row.keys()
        stated = (row["author_role"] if "author_role" in keys else "") or ""
        if stated:
            return stated
        mail = ((row["email"] if "email" in keys else "") or "").strip().lower()
        if mail and mail in crew:
            return "talent"
        return "client"
    archive = []
    for c in rows:
        # Only the notes a composer acts on. EVERY version's, not just the current
        # one — a note belongs to the take it was written against, and the room now
        # lets you select a take (operator, 2026-08-19: *"when i click for a version
        # to be loaded it should also come with its notes"*). `notes` stays the
        # current version's list, because the counters, the badge and every existing
        # reader mean "what is waiting on the take under review".
        if c["kind"] not in ("comment", "change_request", "asset_change"):
            continue
        if c["parent_id"]:
            continue                       # replies thread under their parent below
        keys = c.keys()
        disp = (c["disposition"] if "disposition" in keys else "") or ""
        n = {
            "id": c["id"], "t": c["t_seconds"],
            "t_end": (c["t_end"] if "t_end" in keys else None),
            "author": c["author"], "author_role": _role_of(c),
            "body": c["body"], "kind": c["kind"], "resolved": bool(c["resolved"]),
            "addressed": bool(c["composer_addressed"]
                              if "composer_addressed" in keys else 0),
            # Species (EP P1): a conform (re-sync to a new cut) is free — the
            # composer must SEE that per-note, not just in the banner.
            "conform": bool(c["conform"] if "conform" in keys else 0),
            "disposition": disp,
            # The take this note was written against. Blank for a note left before
            # any version existed — it belongs to no take and shows with the first.
            "version": (c["version"] or ""),
            "at": c["created_at"] or "",
            "replies": [],
        }
        (notes if (c["version"] or "") == cur_n else archive).append(n)
        by_id[c["id"]] = n
    for c in rows:                          # thread replies (client, studio, composer)
        if c["parent_id"] and c["parent_id"] in by_id:
            keys = c.keys()
            by_id[c["parent_id"]]["replies"].append({
                "author": c["author"], "author_role": _role_of(c), "body": c["body"],
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
        # Earlier takes' notes, newest version first. Rendered in the room but shown
        # only when that take is selected — so switching to v1 brings v1's
        # conversation with it, and a fresh take opens on a fresh pane.
        "archive": sorted(archive, key=lambda n: (n["version"], n["id"]), reverse=True),
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


def _call_intel(conn, prow) -> dict:
    """The discovery call, as the composer needs to read it. Empty when there is no
    linked opportunity or no intelligence yet — an absent section, never a fake one."""
    from . import campaign_intelligence as ci, campaigns
    if not prow["opp_id"] or not campaigns.workspace_enabled():
        return {"facts": [], "open_questions": []}
    try:
        row = db.get_opportunity(conn, prow["opp_id"])
        if row is None:
            return {"facts": [], "open_questions": []}
        view = ci.brief_view(conn, ci.ensure_for_opportunity(conn, row)["id"])
        # Risks and insights are the STUDIO's read of the buyer — how they behave, what
        # to watch commercially. Open questions are the only debrief item a composer acts
        # on, and even those are capped: a brief is a page you read before you start, not
        # an archive. The full record stays on the operator's page.
        return {"facts": ci.composer_brief(view),
                "open_questions": list(view.get("open_questions") or [])[:4]}
    except Exception:  # noqa: BLE001 — the room must open even if intelligence hiccups
        return {"facts": [], "open_questions": []}


def _room_fields(conn, project_id: int, prow, *, role: str = "") -> dict:
    """Every field the room shows about ONE engagement, for whoever is looking.

    Role-agnostic on purpose: this builds the room in full and `room.room_view` performs
    the SUBTRACTION for the role that asked. One derivation, many reporters — the rule
    the queue, the price and the relationship already follow, applied to the room itself,
    because three renderings of one engagement is how they drift.
    """
    delivery = db.get_delivery(conn, project_id)
    # Once the client approves the master (creative lock), the composer's job shifts
    # from iterating the master to producing the DERIVATIVE deliverables (instrumental,
    # cutdowns, verticals, stems). Surface those so the portal can ask for them —
    # the master is the version ladder, so it's excluded here.
    locked = bool(production.creative_lock(delivery))
    # Scoped deliverables + specs are DAY-ONE knowledge (composer review P1-8:
    # "I bounce to spec from take one if you tell me on day one"), not a
    # post-approval surprise. Pending = submitted, with the studio (EP P0-3).
    # HOW MANY files are in each lane, not merely whether any are. A stem package is a
    # folder; a lane that could only say "something is in here" closed itself after the
    # first file and left no way to add the rest (reported live, 2026-08-19).
    from collections import Counter
    pending_n = Counter((x.get("label") or "").strip().lower()
                        for x in (delivery.get("pending_assets") or []))
    published_n = Counter((a.get("label") or a.get("filename") or "").strip().lower()
                          for a in (delivery.get("assets") or []))
    published_files, pending_files = {}, {}
    for asset in (delivery.get("assets") or []):
        key = (asset.get("label") or asset.get("filename") or "").strip().lower()
        published_files.setdefault(key, []).append(
            {"url": asset.get("url") or "",
             "name": asset.get("orig") or asset.get("filename") or "file"})
    # WHAT IS ACTUALLY IN THE LANE, by name. A count answers "did anything land"; it does
    # not answer "did I send all twelve", which is the question someone bouncing stems at
    # 2am is asking (operator, 2026-08-19).
    for asset in (delivery.get("pending_assets") or []):
        key = (asset.get("label") or "").strip().lower()
        pending_files.setdefault(key, []).append(
            {"url": asset.get("url") or "",
             # the storage name is the KEY the studio's publish/send-back posts
             "filename": asset.get("filename") or "",
             "by": asset.get("by") or "",
             "name": asset.get("orig") or asset.get("filename") or "file"})
    # WHOSE LANE, and what it is made FROM (ADR-0075). The composer writes and bounces
    # the stems; the mixer works from the approved master; the editor cuts down the
    # mixer's finished mix. A lane whose upstream has not been published yet is not work
    # anyone can start, and saying so is better than an empty upload box that looks like
    # a missed deadline.
    signoff_items, signoff_rollup, _assets = scoped_signoff(prow, delivery)
    balance = db.invoice_balance(conn, project_id)
    unlocked = bool(delivery.get("download_unlocked")) or balance["paid_in_full"]
    # Why the balance cannot be asked for, when it cannot. "" = it can.
    invoice_block = final_invoice_block(conn, project_id)
    rows = [d for d in scoped_deliverables(prow, delivery) if not d.get("is_master")]
    published_by_owner = {}
    for d in rows:
        owner = deliverable_owner(d["asset"], d.get("group", ""))
        if published_n.get((d["asset"] or "").strip().lower()):
            published_by_owner[owner] = True
    deliverables = []
    for d in rows:
        key = (d["asset"] or "").strip().lower()
        owner = deliverable_owner(d["asset"], d.get("group", ""))
        waits_on = owed_after(owner)
        deliverables.append({
            "asset": d["asset"], "group": d["group"],
            "spec": d.get("spec", ""), "uploaded": bool(d.get("uploaded")),
            "pending": bool(pending_n.get(key)),
            "pending_n": pending_n.get(key, 0),
            "published_n": published_n.get(key, 0),
            "owner": owner,
            "waits_on": waits_on,
            # The published files themselves. The editor's cutdowns are made FROM the
            # mixer's mix, so knowing it exists is half an answer — they need the file.
            # `room.room_view` strips these for the client, who receives the package.
            "files": published_files.get(key, []),
            "waiting_files": pending_files.get(key, []),
            # Ready = nothing upstream, or the upstream craft has published something.
            "ready": (not waits_on) or bool(published_by_owner.get(waits_on)),
        })
    return {
        "project_id": project_id,
        "role": role,
        # Every hat a creator wears on this engagement, in assignment order.
        "roles": ([role] if role else []),
        # …and the CRAFTS behind those hats, which is what a deliverable lane is keyed
        # by. "Mixer", "Audio Engineer" and "Mix engineer" are one craft; the room has
        # to know that before it can say whose lane a row is.
        "role_keys": [k for k in [role_key(role)] if k],
        "client": prow["client"],
        "need": prow["need"],
        "deadline": prow["deadline"],
        "status": prow["status"],
        "delivery_state": (delivery.get("state") or "Not started"),
        "version_state": (delivery.get("version_state") or ""),
        "versions": versions_list(delivery),
        # The creator's OWN latest submission, even while it's still pending Jon's
        # review — so they can see it landed instead of the empty "upload your first"
        # state (reported live: after submitting, the portal looked like nothing happened).
        # Removed for the client by `room.room_view`: published versions only.
        # It carries the LABEL it will get on publish. "with the studio" told you a take
        # was in the building and not which one it is; a room holding v1 and an unnamed
        # newer thing reads as a room holding v1 (operator, 2026-08-19: *"V2 should be
        # loaded and labelled as v2"*).
        "pending": (dict(delivery["pending_version"],
                         label=version_label(len(versions_list(delivery)) + 1))
                    if delivery.get("pending_version") else None),
        "feedback": _creator_feedback(conn, project_id, delivery),
        "creative_lock": locked,
        # THE APPROVED MASTER, as a file. A mixer or a music editor is invited at exactly
        # this moment and has to work from it — and the room, which knows which version is
        # approved, offered no way to get it. They were being asked to mix something they
        # could only stream (reported live, 2026-08-19). Only for a hand that may have the
        # source (`download_source`); `room.room_view` subtracts it from the client, who
        # gets their files through the delivery package.
        "master": (versions_list(delivery)[-1] if versions_list(delivery) else None),
        "deliverables": deliverables,
        # WHAT THE CLIENT SIGNS OFF, and what stands between them and their files. The
        # studio published four stems and the client's room said nothing — because
        # `deliverables` is the LANE view (specs, uploads, whose craft) and is subtracted
        # from them entirely. This is the other half: the same scoped list with its
        # per-asset approval state, the balance, and the package. One derivation
        # (`delivery_ops.scoped_signoff`), read by the console, the portal and here.
        "signoff": signoff_items,
        "signoff_rollup": signoff_rollup,
        "download_unlocked": unlocked,
        "invoice_balance": balance,
        "invoice_block": invoice_block,
        "delivery_zip": delivery.get("delivery_zip") or None,
        # The room's Brief layer renders the REAL creative brief (the same
        # effective brief the console shows), not a restatement of the title.
        "brief": seed_brief(
            prow,
            db.get_opportunity(conn, prow["opp_id"]) if prow["opp_id"] else None,
            delivery),
        "deadline_rel": _rel_deadline(prow["deadline"]) if prow["deadline"] else "",
        # What the DISCOVERY CALL established, for the person writing the music. The
        # brief sheet was seeded only from the opportunity's `need` and `description`
        # (`delivery.seed_brief`), so a call summarised into Campaign Intelligence — the
        # objective, the arc, the deliverables, the decision makers, the open questions —
        # reached the operator's page and never reached the composer. Reported live.
        "intel": _call_intel(conn, prow),
        # What the client is actually licensing. The EP review was blunt: "I cannot
        # approve music whose usage I cannot see." The FEE stays operator-only
        # (`see_money`); the GRANT is what they are buying and belongs beside the button.
        "license": merge_license(delivery.get("license")),
        # A cut waiting to be conformed (ADR-0069). The room keeps playing the cut the
        # notes were written against until the studio says how far the picture moved.
        "conform_pending": delivery.get("conform_pending") or None,
        # Phase 2 — the picture + references + conform marking
        "picture": delivery.get("picture") or None,
        "references": list(delivery.get("references") or []),
        # Phase 3 — the Cue Layer: cue regions + hit diamonds on the spine.
        # Read-only for the composer (Jon owns the cue list); they score to it.
        "cues": db.get_cues(conn, project_id),
        # Phase 4 §13 — the private Capture shelf (composer + studio only).
        "captures": db.get_captures(conn, project_id),
    }


def _room_for_project(conn, project_id: int) -> Optional[dict]:
    """THE engagement, built once, for whoever is looking. ``None`` if it is gone."""
    prow = db.get_project(conn, project_id)
    return None if prow is None else _room_fields(conn, project_id, prow)


def _creator_assignment_view(conn, talent_id: int) -> list:
    """Per-assignment cards for the composer portal: brief, role, deadline, the
    delivery state, the versions THIS creator can submit/see, and the client's
    review feedback on the current version (read-only)."""
    out = []
    # ONE ROOM PER PROJECT, not per assignment row. A creator wearing three hats on one
    # engagement — composer, editor, mixer — got three identical rooms stacked down the
    # page, the same picture and the same take rendered three times. Reported live. The
    # engagement is the room; the hats are a line in it.
    seen = {}
    for a in db.list_talent_assignments(conn, talent_id):
        if a["project_id"] in seen:
            seen[a["project_id"]]["roles"].append(a["role"])
            continue
        prow = db.get_project(conn, a["project_id"])
        if prow is None:
            continue
        entry = _room_fields(conn, a["project_id"], prow, role=a["role"])
        # The composer's own portal is a TALENT view, so it obeys the same rule the room
        # does: a note is not work until a human has priced it (ADR-0069).
        entry["feedback"] = room.priced_notes_only(entry["feedback"])
        seen[a["project_id"]] = entry
        out.append(entry)
    # Needs-me-first (composer review P1): rooms owing the composer work come
    # before in-motion rooms; delivered rooms sink to the bottom.
    def _urgency(v):
        closed = v["delivery_state"] in ("Released", "Delivered")
        needs_me = (v["feedback"]["open_count"] > 0
                    or (not v["versions"] and not v["pending"] and not closed))
        return 2 if closed else (0 if needs_me else 1)
    out.sort(key=_urgency)
    # "Composer · Editor · Mixer" — one line, order preserved, duplicates dropped.
    for v in out:
        uniq = list(dict.fromkeys(r for r in v["roles"] if (r or "").strip()))
        v["roles"] = uniq
        v["role"] = " · ".join(uniq) or v["role"]
        v["role_keys"] = list(dict.fromkeys(k for k in (role_key(r) for r in uniq) if k))
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
        # Who else played, per room. Clause 6A is the composer's obligation, so the
        # roster lives where the composer is — not on an operator screen they never see.
        contributors = {a["project_id"]: [
            dict(c, signed=db.latest_contributor_signature(
                conn, c["id"], signing.DOC_CONTRIBUTOR_RELEASE) is not None)
            for c in (dict(r) for r in db.list_contributors(conn, a["project_id"]))]
            for a in assignments}
        # The banner below was unconditional: a composer who had signed, and been
        # countersigned, was still told to "Read & sign" the agreement and that signing
        # "is what lets us put you on paid work" — while working. Same class of error as
        # the client being told to release a proposal already released.
        agr_signed = db.latest_talent_signature(
            conn, row["id"], signing.DOC_COMPOSER_AGREEMENT)
        agr_counter = db.latest_talent_signature(
            conn, row["id"], signing.DOC_COMPOSER_COUNTERSIGN)
    finally:
        conn.close()
    all_rooms = assignments
    if p is not None:
        assignments = [a for a in assignments if a["project_id"] == p] or all_rooms
    return render(
        request, "creator_portal.html", nav="", token=token, t=t,
        # THE ROOM'S CREDENTIAL, on the composer's own door too. The template posts
        # every room action with `room_token`, and this page never set it — so the note
        # bar submitted an empty creator token, the route read that as "no credential",
        # and a composer writing a note from their own portal had it dropped with
        # "That note did not send". One name for the credential, set wherever the room
        # renders.
        room_token=token, room_token_kind="t",
        completeness=profile_completeness(t), assignments=assignments,
        all_rooms=all_rooms, focused=p, contributors=contributors,
        contributor_roles=contributor_release.ROLES,
        agr_signed=agr_signed, agr_counter=agr_counter,
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


def _mail_signed_copy(signer_mail: str, sig, doc_text: str, *, row_name: str,
                      doc_title: str = "Composer Agreement",
                      signer_note: str = ("It commits you to no work; each engagement is "
                                          "offered and accepted separately."),
                      operator_note: str = ("They are now assignable (the agreement half "
                                            "of the gate).")) -> None:
    """Their copy, and the operator's. Retention is a requirement of the legal shape this
    claims (ESIGN/UETA), and a writer who signed a rights assignment should not have to
    come back to a link to read what they gave away.

    The drawn signature travels as an ATTACHED PNG. Reported live: "it comes back as
    signed but it comes back as text. I cant see a copy of the digital signature." It was
    plain text with no image at all — and even inline it would not have shown, because
    the mark is stored as a data: URI and Gmail strips those out of <img>. A file arrives
    everywhere and is a thing either party can keep.

    The document is a PARAMETER because the contributor release borrows this function.
    Hard-coded, it told a session cellist she had signed the Composer Agreement, and told
    the operator she was "now assignable" — she is not on the roster, is not assignable,
    and did not sign that document. Naming the wrong instrument in the receipt for a
    signature is the honesty rule broken in the one place it matters most.
    """
    from .. import mailer, signing as _signing
    from . import meeting_scheduler
    from .shell import public_base as _pb
    block = (f"\n\n{'=' * 58}\nSIGNED COPY — the exact text this signature covers\n"
             f"{'=' * 58}\n{doc_text}\n{'=' * 58}\n"
             f"Signed by: {sig.typed_name}"
             + (f" <{sig.signer_email}>" if sig.signer_email else "")
             + f"\nSigned at: {sig.signed_at}\n"
             f"Consent given: {sig.consent_text}\n"
             f"Document digest (SHA-256): {sig.digest}\n")
    png = _signing.drawn_mark_png(getattr(sig, "drawn_mark", "") or "")
    files = [("signature.png", "image/png", png)] if png else []
    if png:
        block += "\nThe drawn signature is attached as signature.png.\n"
    base = _pb()
    if signer_mail:
        text = (f"Thank you. Below is the {doc_title.lower()} exactly as you signed it, "
                f"for your records. {signer_note}" + block)
        try:
            mailer.send_email(signer_mail, f"Your signed {doc_title} — Chordential",
                              text, html=mailer.branded_html(base, text), files=files)
        except Exception:  # noqa: BLE001
            pass
    op_mail = meeting_scheduler._operator_email()
    if op_mail:
        text = (f"{sig.typed_name} signed the {doc_title}.\n"
                f"{operator_note}\n"
                f"{base}/talent" + block)
        try:
            mailer.send_email(op_mail,
                              f"✍ {doc_title} signed — {row_name or sig.typed_name}",
                              text, html=mailer.branded_html(base, text), files=files)
        except Exception:  # noqa: BLE001
            pass


@router.post("/creator/{token}/project/{project_id}/contributor")
def creator_add_contributor(token: str, project_id: int, name: str = Form(""),
                            role: str = Form("Performer"), email: str = Form(""),
                            instrument: str = Form("")):
    """The composer names someone who played on the work, and we email them a release.

    Clause 6A obliges the writer to collect one from anyone who performed, sang,
    programmed, produced, engineered or co-wrote — "paid or unpaid, stranger or friend".
    Naming them here is how that obligation becomes something a person can actually do at
    11pm after a session, which is when they will do it or not at all.
    """
    conn = db.connect()
    try:
        talent = db.get_talent_by_portal_token(conn, token)
        if talent is None:
            return HTMLResponse("Not found", status_code=404)
        project = db.get_project(conn, project_id)
        if project is None:
            return HTMLResponse("Not found", status_code=404)
        if not name.strip():
            return RedirectResponse(f"/creator/{token}?p={project_id}#contributors",
                                    status_code=303)
        work = (instrument.strip()
                or f"{project['client']} · {project['need']}").strip()
        cid = db.add_contributor(
            conn, project_id=project_id, talent_id=talent["id"],
            name=name.strip(), role=role.strip() or "Performer",
            email=email.strip(), work=work,
            booked_by=(talent["name"] or "").strip())
        row = db.get_contributor(conn, cid)
        rel = contributor_release.build_release(row)
        sent = _mail_release(row, rel)
        if sent:
            db.mark_contributor_sent(conn, cid)
    finally:
        conn.close()
    return RedirectResponse(f"/creator/{token}?p={project_id}#contributors",
                            status_code=303)


@router.post("/creator/{token}/project/{project_id}/contributor/{cid}/remind")
def creator_remind_contributor(token: str, project_id: int, cid: int):
    """Send the release again. People lose emails; chasing is the composer's job and it
    should be one button, not a note-to-self."""
    conn = db.connect()
    try:
        if db.get_talent_by_portal_token(conn, token) is None:
            return HTMLResponse("Not found", status_code=404)
        row = db.get_contributor(conn, cid)
        if row is None or row["project_id"] != project_id:
            return HTMLResponse("Not found", status_code=404)
        if db.latest_contributor_signature(
                conn, cid, signing.DOC_CONTRIBUTOR_RELEASE) is None:
            if _mail_release(row, contributor_release.build_release(row)):
                db.mark_contributor_sent(conn, cid)
    finally:
        conn.close()
    return RedirectResponse(f"/creator/{token}?p={project_id}#contributors",
                            status_code=303)


@router.post("/creator/{token}/project/{project_id}/contributor/{cid}/remove")
def creator_remove_contributor(token: str, project_id: int, cid: int):
    """Named the wrong person, or they did not end up playing. Refused once signed — a
    signed release is evidence, and evidence is not deleted because it is inconvenient."""
    conn = db.connect()
    try:
        if db.get_talent_by_portal_token(conn, token) is None:
            return HTMLResponse("Not found", status_code=404)
        row = db.get_contributor(conn, cid)
        if row is not None and row["project_id"] == project_id:
            db.remove_contributor(conn, cid)
    finally:
        conn.close()
    return RedirectResponse(f"/creator/{token}?p={project_id}#contributors",
                            status_code=303)


def _mail_release(row, rel) -> bool:
    """Send one contributor their release. Returns whether it went.

    They are not a user of this system and never will be: no account, no password, one
    link that is the whole credential. A session player should be able to sign on a phone
    in a car park.
    """
    from .. import mailer
    from .shell import public_base as _pb
    email = (row["email"] or "").strip()
    if not email or not mailer.mail_configured():
        return False
    url = f"{_pb()}/contributor/{row['token']}"
    first = (row["name"] or "there").split(" ")[0]
    body = (
        f"Hi {first},\n\n"
        f"{row['booked_by'] or 'A composer'} has named you as having played on "
        f"\"{row['work']}\" for Chordential. Before we can deliver it to the client we "
        f"need a short release from you — it confirms the recording is yours to give and "
        f"that we can use it.\n\n"
        f"Read and sign it here (takes a minute, works on a phone):\n{url}\n\n"
        f"It is about the recording, not your fee — whatever you agreed to be paid is "
        f"between you and {row['booked_by'] or 'whoever booked you'}, and this does not "
        f"change it.\n\n"
        f"— Chordential"
    )
    try:
        return mailer.send_email(
            email, f"Quick release to sign — {row['work'][:60]}", body,
            html=mailer.branded_html(_pb(), body)) == "sent"
    except Exception:  # noqa: BLE001 — chasing a signature never breaks the session
        return False


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
    file: Optional[List[UploadFile]] = File(None),
):
    """A creator uploads scoped DELIVERABLES (instrumental / TV mix, cutdowns, verticals,
    stems) AFTER the master is approved. They land in ``delivery_json['pending_assets']``
    under the lane's label so the studio can vet them, and ping the operator. Guarded by a
    valid portal token AND an assignment to the project.

    MANY FILES PER LANE. A stem package is not a file, it is a folder — and the lane took
    one upload and then closed itself, so the row read "with the studio · under review"
    with a single stem in it and no way to add the other eleven (reported live,
    2026-08-19). Each file lands as its own asset under the same label; a lane stays open
    for as long as the delivery does, so they can arrive together or over three days.

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
        uploads_in = [f for f in (file or []) if f is not None and (f.filename or "").strip()]
        if not uploads_in:
            return _fail("no file", 400)
        who = row["name"]
        from datetime import datetime as _dt, timezone as _tz
        delivery = db.get_delivery(conn, project_id)
        pending = list(delivery.get("pending_assets") or [])
        deliverable = (label.strip() or uploads_in[0].filename)
        names = []
        for up in uploads_in:
            ext = os.path.splitext(up.filename)[1].lower()
            ctype = (up.content_type or "").lower()
            kind = "audio" if (ext in _AUDIO_EXTS or ctype.startswith("audio/")) else "file"
            data = await _read_capped(up, _SUBMISSION_MAX_BYTES)
            if not data:            # empty OR over cap — never buffer unbounded
                continue            # one bad file in twelve must not lose the other eleven
            # Collision-proof on-disk name (random suffix) so nothing can overwrite
            # another upload's file — no counter to race on.
            safe_ext = ext if ext else (".mp3" if kind == "audio" else ".bin")
            safe_name = f"proj{project_id}-{os.urandom(5).hex()}{safe_ext}"
            _persist_upload(conn, safe_name, data,
                            mirror=len(data) <= _CUT_MIRROR_BYTES)   # ADR-0026
            # EP review P0-3: deliverables get the SAME studio gate as the master. The
            # upload lands PENDING — the studio vets and publishes it before the client
            # can ever see it (uniform publish gate, stems included).
            pending.append({"label": deliverable, "url": f"/uploads/{safe_name}",
                            "filename": safe_name, "orig": up.filename,
                            "kind": kind, "by": who,
                            "at": _dt.now(_tz.utc).isoformat()})
            names.append(safe_name)
        if not names:
            return _fail("file missing or too large", 400)
        db.update_delivery(conn, project_id, "pending_assets", pending)
        # CONFIRM they actually persisted before telling the composer they landed. A
        # partial save is reported as a partial save.
        stored = db.get_delivery(conn, project_id).get("pending_assets") or []
        stored_names = {a.get("filename") for a in stored}
        added = sum(1 for n in names if n in stored_names)
        landed = added > 0
        count = sum(1 for a in stored
                    if (a.get("label") or "").strip().lower() == deliverable.strip().lower())
        prow = db.get_project(conn, project_id)
        campaign = (prow["need"] if prow is not None else "") or "Campaign"
        db.add_update(
            conn, project_id,
            f"{who} submitted {added} file{'s' if added != 1 else ''} for "
            f"'{deliverable}' · with the studio for review.")
    finally:
        conn.close()
    if not landed:
        return _fail("not saved. Please try again", 500)
    await run_in_threadpool(
        _notify_operator_review, project_id, None, f"Deliverable submitted · {campaign}",
        f"{who} submitted a deliverable. Vet it in the delivery console, then publish.")
    if xhr:
        # `count` is what is now in THIS LANE, so the row can say "3 files with the
        # studio" rather than a running total of everything ever submitted.
        # `count` is what is now in THIS LANE, and `names` are the files just added —
        # the row lists them so twelve stems can be checked at a glance without a reload.
        return JSONResponse({"ok": True, "label": deliverable,
                             "added": added, "count": count,
                             "names": [f.filename for f in uploads_in][:added]})
    return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)
