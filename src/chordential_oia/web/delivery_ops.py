"""The production-side operations shared by /project, /creator and /workspace.

Approving a version, assembling the package, deciding whether a delivery may finalize,
and telling the people involved. ``approve_version_core`` is the one that forced this
module to exist: /project and /workspace both approve, and the chain underneath it
reaches ten further helpers, so neither route group could move while it sat in
``app.py``.

The engine logic lives in :mod:`chordential_oia.delivery` and :mod:`..web.production`.
What is here is the *orchestration* — the order in which those engines are called and
the side effects (invoice, notification, event log) that follow.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .. import mailer
from ..delivery import (
    build_delivery_zip, current_version, delivery_completeness, role_key,
    scoped_deliverables, state_on_client_approved, version_label, versions_list,
)
from ..storage import get_object_store
from . import db, production, signals, webpush
from .estimate import estimate_for
from .billing import _ensure_final_invoice_issued, _send_invoice_pay_link
from .shell import public_base as _public_base
from .uploads import upload_dir


def _gate_banner(err: str, t: Optional[int]) -> Optional[dict]:
    """The A-3 refusal banner (ADR-0024): who was blocked and what's missing, so
    the operator's next click is the fix, not a mystery. Pure lookup — returns
    None unless this request is the redirect from a refused assign."""
    if err != "agreement" or not t:
        return None
    conn = db.connect()
    try:
        row = db.get_talent(conn, int(t))
    finally:
        conn.close()
    if row is None:
        return None
    blockers = db.talent_assignment_blockers(row)
    missing = " + ".join(
        {"agreement": "an executed Composer Agreement",
         "rate": "a rate"}[b] for b in blockers) or "nothing"
    name = (row["name"] or "This creator") if "name" in row.keys() else "This creator"
    return {"talent_id": row["id"], "name": name, "missing": missing}


def _campaign_label(project) -> str:
    """A short campaign label for the operator push (client / need)."""
    try:
        return (project["need"] or project["client"] or "Campaign").strip()
    except Exception:  # noqa: BLE001
        return "Campaign"


def _current_version_tag(delivery: dict) -> str:
    """The version number a comment/approval is tagged with: the current version's
    ``n`` (anti-chaos — feedback always lands on the version it was made against).
    Falls back to ``"0"`` for a Phase-0 project that never logged a version."""
    cur = current_version(delivery)
    return str(cur["n"]) if cur else "0"


def _delivery_console_url(project_id: int) -> str:
    return f"/project/{project_id}/delivery"


def _notify_assigned_creators(project_id: int, project, *, subject: str,
                              body_text: str, exclude_email: str = "",
                              only_craft: str = "") -> None:
    """Composer-direction notification: email each assigned creator (with an email)
    when the client acts on their work — approved, or changes requested. Also used to
    broadcast a new assignment to the whole project crew. Closes the loop the review
    portal opened: the composer hears the verdict from us instead of Jon relaying it by
    hand. ``exclude_email`` skips one recipient (e.g. the just-assigned creator who has
    already had a tailored email). ``only_craft`` narrows to one craft — the hand-off
    down the chain (ADR-0075) is addressed to the editor, not to everyone who has ever
    touched the project. Best-effort, per creator, never raises. Runs in its
    own DB connection so it's safe to fire-and-forget off the request thread."""
    conn = db.connect()
    try:
        assignments = db.list_assignments(conn, project_id)
    finally:
        conn.close()
    if not mailer.mail_configured():
        return
    base = _public_base()
    seen = set()
    if exclude_email:
        seen.add(exclude_email.strip().lower())
    # Look up each creator's portal token so the email can carry their one link (courtesy:
    # the composer opens straight into their portal to see the notes / submit the next take).
    portal_by_talent = {}
    conn2 = db.connect()
    try:
        for a in assignments:
            tid = a["talent_id"] if "talent_id" in a.keys() else None
            if tid is not None:
                trow = db.get_talent(conn2, tid)
                tok = (trow["portal_token"] if trow is not None and "portal_token" in trow.keys()
                       else "") or ""
                if tok:
                    portal_by_talent[tid] = tok
    finally:
        conn2.close()
    for a in assignments:
        email = (a["talent_email"] or "").strip() if "talent_email" in a.keys() else ""
        if not email or email.lower() in seen:
            continue
        if only_craft and role_key(a["role"] if "role" in a.keys() else "") != only_craft:
            continue
        seen.add(email.lower())
        name = (a["talent_name"] or "there").strip() if "talent_name" in a.keys() else "there"
        tid = a["talent_id"] if "talent_id" in a.keys() else None
        text = f"Hi {name},\n\n{body_text}"
        tok = portal_by_talent.get(tid)
        if tok:
            text += f"\n\nOpen your portal; the feedback and your upload box are here:\n{base}/creator/{tok}"
        text += "\n\nChordential"
        try:
            mailer.send_email(email, subject, text, html=mailer.branded_html(base, text))
        except Exception:  # noqa: BLE001 — best-effort; one creator's failure never stops the rest
            pass


def _notify_operator_review(project_id: int, project, title: str, body: str) -> None:
    """Push the operator (Jon) when the agency comments / requests changes /
    approves — the coordination signal that 'one link, no email' would otherwise
    drop. Best-effort, never blocks the request (mirrors notify_new_gig).

    Operator-direction only. Agency-direction email (notify the reviewer when a new
    version is uploaded) needs the deferred outbound-send infra that doesn't exist
    yet — see the TODO below; we do NOT fake it here.

    TODO(delivery-os): agency-direction notifications. When a new version is
    uploaded or the operator replies, email the reviewer at their captured
    ``review_comments.email``. Requires a transactional send channel (deferred
    outbound email infra) — not wired yet, so left unimplemented rather than faked.
    """
    url = _delivery_console_url(project_id)
    try:
        webpush.send_web_push(title, body=body, url=url)
    except Exception:  # noqa: BLE001 — push is best-effort, never block the action
        pass
    try:
        signals.send_push(title, body=body, click_url=url)
    except Exception:  # noqa: BLE001
        pass


def _ready_to_deliver(delivery: dict, project) -> bool:
    """The gate to the full download (Option 1 model): the master is approved (Creative Lock),
    every scoped deliverable is UPLOADED, AND every uploaded derivative is SIGNED OFF by the
    client. The primary master IS the review version — approving it (the main creative approval)
    delivers + approves it; the derivatives (instrumental, cutdowns, verticals, stems) are the
    composer's uploads, each signed off one at a time. Only when all of that is true does the
    full package assemble and the download unlock — so a client can never download an
    incomplete or unapproved delivery."""
    if not production.creative_lock(delivery):            # master approved?
        return False
    if not delivery_completeness(project, delivery)["complete"]:   # everything uploaded?
        return False
    roll = db.asset_approval_rollup(delivery)             # every derivative signed off?
    return roll["total"] == 0 or roll["approved"] == roll["total"]


def _rehydrate_delivery_media(conn, project_id: int) -> int:
    """Restore a project's delivery media (asset + version files) from the durable DB blob
    mirror back to disk when the ephemeral disk was wiped — so a package (re)build actually
    contains the audio instead of README placeholders. Returns the count restored."""
    delivery = db.get_delivery(conn, project_id)
    names = set()
    for a in (delivery.get("assets") or []):
        if a.get("filename"):
            names.add(os.path.basename(a["filename"]))
    for v in (delivery.get("versions") or []):
        if v.get("filename"):
            names.add(os.path.basename(v["filename"]))
    pv = delivery.get("pending_version") or {}
    if pv.get("filename"):
        names.add(os.path.basename(pv["filename"]))
    restored = 0
    store = get_object_store(upload_dir())
    for base in names:
        # ADR-0043: ask the STORE whether the bytes are there. A durable store needs
        # no rehydration at all — this loop exists to repair a wiped local disk from
        # the SQLite mirror before zipping, and a bucket does not get wiped.
        if not base or store.exists(base):
            continue
        blob = db.get_media_blob(conn, base)
        if blob is None:
            continue
        if store.put(base, blob[0], blob[1] or ""):
            restored += 1
    return restored


def _build_delivery_package(conn, project_id: int) -> Optional[dict]:
    """Delivery automation (Phase 3): assemble the delivery ZIP for a project and
    store its descriptor + checklist on ``delivery_json``. Returns the descriptor
    (or None if the project is gone). Deterministic + best-effort: the stdlib ZIP +
    docs always build; audio conversion is attempted only if ffmpeg is available.

    Durable across ephemeral-disk wipes: rehydrates the source media from the DB mirror
    before zipping, and mirrors the built ZIP itself into the blob store so the download
    survives a redeploy.

    Stored shape::

        delivery_json['delivery_zip']       = {filename, url, built_at}
        delivery_json['delivery_checklist'] = [item, …]   (founder's payoff list)
    """
    row = db.get_project(conn, project_id)
    if row is None:
        return None
    _rehydrate_delivery_media(conn, project_id)      # source audio back on disk before zipping
    assignments = db.list_assignments(conn, project_id)
    delivery = db.get_delivery(conn, project_id)
    pkg = build_delivery_zip(row, assignments, delivery, upload_dir())
    # The built ZIP goes through the write door (ADR-0043), not straight into the DB
    # mirror. It used to call `db.save_media_blob` directly, which meant that with a
    # bucket configured the delivery package — the single artefact the client pays for —
    # was the one piece of client media that never reached the bucket: it sat on the
    # ephemeral disk plus a SQLite blob, which is exactly the bloat the Postgres cutover
    # is meant to end.
    try:
        from .uploads import _persist_upload
        with open(os.path.join(upload_dir(), os.path.basename(pkg["filename"])), "rb") as fh:
            _persist_upload(conn, os.path.basename(pkg["filename"]), fh.read(),
                            "application/zip")
    except (OSError, KeyError):
        pass
    db.update_delivery(conn, project_id, "delivery_zip", {
        "filename": pkg["filename"], "url": pkg["url"], "built_at": pkg["built_at"],
        # Honest partial labelling: the portal card + ZIP descriptor read "Partial
        # delivery — N of M deliverables" (not "everything") when incomplete.
        "partial": pkg.get("partial", False),
        "descriptor": pkg.get("descriptor", ""),
        "completeness": pkg.get("completeness", {}),
    })
    db.update_delivery(conn, project_id, "delivery_checklist", pkg["checklist"])
    return pkg


def _maybe_finalize_delivery(conn, project_id: int) -> bool:
    """Ship the delivery package + mark Delivered ONLY when the creative is approved (Creative
    Lock) AND every deliverable is uploaded + signed off. This is the SINGLE door to the full
    download; approving the master version alone never opens it. Returns True if it finalized."""
    delivery = db.get_delivery(conn, project_id)
    project = db.get_project(conn, project_id)
    if project is None or not production.creative_lock(delivery):
        return False
    if (delivery.get("state") or "") in ("Delivered", "Released"):
        _ensure_final_invoice_issued(conn, project_id)   # self-heal older Delivered deals
        return True
    if not _ready_to_deliver(delivery, project):
        return False
    try:
        _build_delivery_package(conn, project_id)
        db.update_delivery(conn, project_id, "state", "Delivered")
        # The balance is now owed — raise it so the download stays gated behind it, and EMAIL
        # the client their pay link automatically (reported live: the final invoice just sat
        # in the operator's queue). Sent once, here, on the delivery transition.
        _ensure_final_invoice_issued(conn, project_id)
        _fin = next((i for i in db.list_invoices(conn, project_id)
                     if (i["kind"] or "") == "Final"), None)
        if _fin is not None and (_fin["status"] or "").lower() not in ("paid", "settled"):
            try:
                _send_invoice_pay_link(conn, _fin["id"])
            except Exception:  # noqa: BLE001 — the auto-send never blocks delivery
                pass
        db.add_project_event(conn, project_id, "delivered", actor_role="operator",
                             actor_name="ChordOS",
                             body="All deliverables approved. Delivery package assembled.")
        return True
    except Exception:  # noqa: BLE001
        return False


def _approve_version_core(conn, project_id: int, name: str, mail: str) -> str:
    """Record the client's approval of the current master version — this is the CREATIVE
    approval (Creative Lock), NOT final delivery. The full package ships only once every
    deliverable is also uploaded + signed off (``_maybe_finalize_delivery``), so a client can
    never download an incomplete package by approving the master alone. Reversible via
    /review/reopen. Returns the approved version tag."""
    delivery = db.get_delivery(conn, project_id)
    project = db.get_project(conn, project_id)
    approved_n = _current_version_tag(delivery)
    db.add_review_comment(
        conn, project_id, version=approved_n, author=name, email=mail,
        body=f"Approved v{approved_n} · creative locked.", kind="approval", verified=True)
    if not production.creative_lock(delivery):
        production.set_creative_lock(conn, db, project_id, version_n=int(approved_n or 0), by=name)
    versions = versions_list(delivery)
    if versions:
        versions[-1] = dict(versions[-1])
        versions[-1]["label"] = version_label(versions[-1]["n"], final=True)
        db.update_delivery(conn, project_id, "versions", versions)
        db.update_delivery(conn, project_id, "version_state", versions[-1]["label"])
    # Creative approved — but delivery stays LOCKED until every deliverable is signed off.
    db.update_delivery(conn, project_id, "state", state_on_client_approved(delivery))
    finalized = _maybe_finalize_delivery(conn, project_id)   # ships iff complete + all approved
    db.add_project_event(conn, project_id, "approval", actor_role="client", actor_name=name,
                         body=f"Approved v{approved_n} · creative locked.")
    remaining = "" if finalized else " Delivery unlocks once every deliverable is uploaded and signed off."
    _notify_operator_review(
        project_id, project, title=f"{_campaign_label(project)} · creative approved by {name}",
        body=f"v{approved_n} creative approved.{remaining}")
    campaign = _campaign_label(project)
    # THE HAND-OFF. Creative approval is the moment the mixer and the music editor are
    # up: they work FROM the approved master, and until now this email thanked everyone
    # and told them we would handle it. It names the version, names what is owed and to
    # what spec, and `_notify_assigned_creators` appends each person's own room link —
    # where the master is now downloadable.
    owed = [d for d in scoped_deliverables(project, db.get_delivery(conn, project_id))
            if not d.get("is_master") and not d.get("uploaded")]
    lines = "\n".join(
        f"  · {d['asset']}" + (f" — {d['spec']}" if d.get("spec") else "") for d in owed)
    signals.fire_and_forget(
        _notify_assigned_creators, project_id, project, subject=f"Creative approved · {campaign}",
        body_text=(
            f"The client approved the creative on {campaign} — thank you.\n\n"
            f"That locks v{approved_n} as the master, and it is the file everything else "
            "is made from. Your room has it to download.\n\n"
            + (f"Still owed:\n{lines}\n\n" if lines else "")
            + "Upload each into its own lane — a lane takes as many files as it needs, so "
              "a stem package can arrive whole. Everything lands with the studio for "
              "review first; we publish it to the client for sign-off."))
    return approved_n


# --------------------------------------------------------------------------- #
# Delivery OS (Phase 0, Pass A) — the delivery engine + generated package +
# client-facing portal. Deterministic assembly; Jon presses the human buttons
# (license terms, log a revision, approve, release). See chordential_oia.delivery.
# --------------------------------------------------------------------------- #
def scoped_signoff(row, delivery: dict) -> tuple:
    """Every scoped deliverable with its per-asset approval state, and the rollup.

    ONE derivation, three reporters (ADR-0029 applied to sign-off): the delivery console,
    the client's portal and now the ROOM all ask "what is there and has the client signed
    it off", and a second answer is how two pages come to disagree about whether a
    delivery is finished. Extracted verbatim from `_delivery_view`, which now calls it.

    Returns ``(items, rollup)``. Each item is a scoped deliverable plus ``asset_key``
    (the stable handle the Approve button posts), ``approval``, and the uploaded asset's
    ``url``/``kind`` when one satisfies it.
    """
    assets_with_approval = []
    for a in list(delivery.get("assets") or []):
        a2 = dict(a)
        a2["approval"] = db.get_asset_approval(delivery, a)
        a2["asset_key"] = db.asset_key(a)
        assets_with_approval.append(a2)
    by_label = {}
    for a in assets_with_approval:
        lbl = (a.get("label") or a.get("filename") or "").strip()
        if lbl and lbl not in by_label:
            by_label[lbl] = a
    clock = production.creative_lock(delivery)
    items, approved = [], 0
    for d in scoped_deliverables(row, delivery):
        item = dict(d)
        match_asset = by_label.get(d.get("match") or "")
        if match_asset is not None:
            item["asset_key"] = match_asset.get("asset_key")
            item["approval"] = match_asset.get("approval")
            item["url"] = match_asset.get("url")
            item["kind"] = match_asset.get("kind")
            if (match_asset.get("approval") or {}).get("status") == "Approved":
                approved += 1
        elif d.get("from_version"):
            # The primary master is the review version itself — it has no per-row
            # Approve control; the main "Approve the master" button IS its sign-off, so
            # its status simply mirrors the creative lock.
            if clock:
                item["approval"] = {"status": "Approved", "by": (clock.get("by") or ""),
                                    "email": "", "date": "",
                                    "version": str(clock.get("version_n") or "")}
                approved += 1
            else:
                item["approval"] = {"status": "Pending", "by": "", "email": "",
                                    "date": "", "version": ""}
            item["asset_key"] = ""
        else:
            item["asset_key"] = ""
            item["approval"] = None
        items.append(item)
    rollup = {"approved": approved, "total": len(items),
              "uploaded": sum(1 for s in items if s.get("uploaded"))}
    return items, rollup, assets_with_approval


def _project_estimate(conn, row):
    """The estimate behind a project (for scoped revision rounds), or None.

    Rebuilt from the linked opportunity the same way the project view does — used
    only to read the revision multiplier. None when there's no linked opp."""
    opp_id = row["opp_id"] if "opp_id" in row.keys() else None
    if opp_id is None:
        return None
    opp_row = db.get_opportunity(conn, opp_id)
    if opp_row is None:
        return None
    opp = db.opportunity_from_row(opp_row)
    return estimate_for(opp, conn=conn, project_id=row["id"])


def _sync_role_milestones(conn, project_id: int) -> None:
    """Keep the per-role Delivery-progress milestones honest with the actual delivery
    lifecycle (reported live: the Composer milestone stayed 'Pending' after a V1 was
    submitted). Forward-only, and only touches role-tagged (auto-seeded) milestones —
    operator-added milestones stay fully manual. The lead role (first scoped role) owns the
    master; derivative roles begin once the master is locked; everything is Done on ship."""
    prow = db.get_project(conn, project_id)
    if prow is None:
        return
    try:
        roles = list(json.loads(prow["roles"] or "[]"))
    except Exception:  # noqa: BLE001
        roles = []
    lead = roles[0] if roles else None
    delivery = db.get_delivery(conn, project_id)
    has_version = bool(delivery.get("pending_version")) or bool(versions_list(delivery))
    locked = bool(production.creative_lock(delivery))
    shipped = (delivery.get("state") or "") in ("Delivered", "Released")
    rank = {"Pending": 0, "In progress": 1, "Done": 2}
    for m in db.list_milestones(conn, project_id):
        role = (m["role"] or "").strip()
        if not role:
            continue                         # operator-added milestones stay manual
        if shipped:
            target = "Done"
        elif locked:
            target = "Done" if role == lead else "In progress"
        elif has_version and role == lead:
            target = "In progress"
        else:
            target = m["status"]
        if rank.get(target, 0) > rank.get(m["status"], 0):
            db.update_milestone_status(conn, m["id"], target)
