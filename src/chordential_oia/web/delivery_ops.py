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
    build_delivery_zip, current_version, delivery_completeness, license_confirmation,
    role_key,
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


def notify_operator(title: str, body: str, url: str) -> None:
    """Push the operator, on every channel that is configured. ONE place.

    Both channels or neither: Web Push reaches a desktop that has the console open, ntfy
    reaches a phone that does not, and which one the operator is near is not something the
    caller can know. Best-effort by construction — a notification that raises would cost
    the action it was announcing, which is the wrong way round.

    Split out of `_notify_operator_review` when it turned out that eleven delivery events
    pushed here — a composer submitting a take, a reviewer leaving a comment — and the
    client SIGNING THE PROPOSAL did not. The one event that closes a deal was the one that
    went out by email alone (operator, 2026-08-27: "when the client signs the discovery
    summary I don't get a notification"). It was never a missing channel; it was a caller
    that reached for the delivery-console helper and found the URL was wrong for it, so
    reached for nothing.
    """
    try:
        webpush.send_web_push(title, body=body, url=url)
    except Exception:  # noqa: BLE001 — push is best-effort, never block the action
        pass
    try:
        signals.send_push(title, body=body, click_url=url)
    except Exception:  # noqa: BLE001
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
    notify_operator(title, body, _delivery_console_url(project_id))


def delivery_held_by(delivery: dict, project) -> str:
    """What is stopping this delivery from shipping ("" when nothing is).

    `_ready_to_deliver` is a boolean, and a boolean cannot tell the operator that the
    thing they are waiting on is a button they have not pressed. Same shape as
    `billing.final_invoice_block`: name it once, report it everywhere.
    """
    if not production.creative_lock(delivery):
        return "master"
    if not delivery_completeness(project, delivery)["complete"]:
        return "uploads"
    roll = db.asset_approval_rollup(delivery)
    if roll["total"] and roll["approved"] != roll["total"]:
        return "signoff"
    # The licence is reported LAST and does not block: confirming it gates Release
    # (tested contract), and hard-gating Delivered on it would strand every delivery
    # already in flight the moment this shipped. So the operator is TOLD — on the
    # console and in the queue — while the certificate goes on saying DRAFT honestly.
    if not license_confirmation(delivery):
        return "licence"
    # …and the certificate itself. Reported after the licence because confirming the
    # licence CHANGES the document, so asking for the signature first would guarantee a
    # superseded one (ADR-0080).
    ex = delivery.get("certificate_executed") or {}
    if not ex.get("digest"):
        return "unsigned"
    return ""


#: What each hold means to the operator — the client never sees these.
DELIVERY_HELD = {
    "master": "The client has not approved the master yet.",
    "uploads": "Not every scoped deliverable has been uploaded.",
    "licence": ("Confirm the licence terms. Until you do, the Clearance Certificate "
                "reads DRAFT — it certifies nothing, and the package will not ship."),
    "unsigned": ("Sign the Clearance Certificate. It is Chordential warranting the chain "
                 "of title, and it ships with a blank signature line until you do."),
    "signoff": "The client has not signed off every delivered file yet.",
}


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
    # THE BYTES, from wherever they actually are. The rehydrate above puts what it can
    # back on disk; this is what happens when it CANNOT — a full ephemeral allowance makes
    # every `store.put` return False, silently, and the packager then declares files lost
    # that the database is holding. Handing it a reader removes the disk from the question
    # entirely (ADR-0079, amended 2026-08-22).
    def _bytes_for(name: str):
        """The bytes, from WHEREVER they are — the object store first, then the database
        mirror. Exactly the two places `media_present` looks, which is the whole point: a
        file the console calls present must be a file the packager can bundle.

        Asking only the database was delivery-stopping on any instance with a bucket
        configured. `_persist_upload` deliberately SKIPS the mirror when the store is
        durable — mirroring to a bucket would double every master into the database for
        no benefit — so with S3/R2 on, every file lives in exactly one place the packager
        never read, and every package shipped documents only. Measured on the operator's
        own instance, 2026-08-22: `21 assets · 0 read from the durable mirror · 21 not
        found (21 mirror empty)`, while the same page reported all 21 present.
        """
        key = os.path.basename(name or "")
        if not key:
            return None
        try:
            data = get_object_store(upload_dir()).get(key)
            if data:
                return data
        except Exception:      # noqa: BLE001 — a store that errors is not a broken package
            pass
        try:
            blob = db.get_media_blob(conn, key)
        except Exception:      # noqa: BLE001 — a missing byte is not a broken package
            return None
        return blob[0] if blob else None

    def _has(name: str) -> bool:
        """Does this file exist anywhere — WITHOUT pulling it. The planning pass asks
        this; only the write pass asks for bytes. Fetching during planning held every
        stem in memory at once and took the service down."""
        key = os.path.basename(name or "")
        if not key:
            return False
        try:
            if get_object_store(upload_dir()).exists(key):
                return True
        except Exception:      # noqa: BLE001
            pass
        try:
            return db.media_blob_exists(conn, key)
        except Exception:      # noqa: BLE001
            return False

    pkg = build_delivery_zip(row, assignments, delivery, upload_dir(),
                             fetch=_bytes_for, has=_has)
    # The built ZIP goes through the write door (ADR-0043), not straight into the DB
    # mirror. It used to call `db.save_media_blob` directly, which meant that with a
    # bucket configured the delivery package — the single artefact the client pays for —
    # was the one piece of client media that never reached the bucket: it sat on the
    # ephemeral disk plus a SQLite blob, which is exactly the bloat the Postgres cutover
    # is meant to end.
    try:
        from .uploads import persist_file
        # ONE WRITE DOOR (ADR-0043) — the streaming one, because this is the artefact
        # that can be a gigabyte. Reaching for the store directly here bypassed the door
        # and, with it, the seam every test and every future backend depends on.
        persist_file(conn, os.path.basename(pkg["filename"]),
                     os.path.join(upload_dir(), os.path.basename(pkg["filename"])),
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
        # How many assets this build saw, and how many it could NOT bundle. Both were
        # computed and then dropped on the floor here, which is why a ZIP holding only
        # documents looked identical to a finished delivery on every screen.
        "asset_count": pkg.get("asset_count", 0),
        "referenced_count": pkg.get("referenced_count", 0),
        # …and WHICH ones. Dropped here exactly as `at` was dropped when publishing
        # copied an asset into a narrower dict — the same shape of bug twice in one
        # delivery. A count cannot be checked against anything; the names can.
        "referenced_names": pkg.get("referenced_names", []),
        # How the build actually went, so the console can stop guessing (ADR-0088).
        "from_mirror": pkg.get("from_mirror", 0),
        "why": pkg.get("why", {}),
    })
    db.update_delivery(conn, project_id, "delivery_checklist", pkg["checklist"])
    return pkg


def _package_is_stale(delivery: dict, conn=None) -> bool:
    """Does the built ZIP predate — or fail to contain — the work it is supposed to hold?

    Compares the newest delivered thing — an asset, a version — against the package's
    own ``built_at``. Anything landing after the build is simply not in the file the
    client downloads, and nothing said so: the manifest cheerfully listed it as
    "Delivered · referenced (not bundled)".

    **A package with HOLES is stale too, the moment its missing bytes are back.** A build
    made while the ephemeral disk had eaten the audio produces a docs-only ZIP with
    ``referenced_count > 0`` — and it is not "old", so nothing rebuilt it, while the
    client's room said *"Chordential has been told, and you'll have it shortly."* That
    promise had nothing behind it: *"the 1st test i was able to download, it had the text
    files but no audio.. we are re testing to see if the audio gets packaged correctly"*
    (operator, 2026-08-22). Now that the files survive a deploy (ADR-0084), the rebuild
    that makes the sentence true can actually fire.

    Checked against the bytes, and only with a ``conn`` to check with: if the audio is
    STILL missing a rebuild changes nothing, and saying stale would loop forever.
    """
    zip_obj = delivery.get("delivery_zip") or {}
    built = (zip_obj.get("built_at") or "").strip()
    if not zip_obj:
        return True                       # never built at all
    if not built:
        return True                       # unknown age → assume stale
    if conn is not None and int(zip_obj.get("referenced_count") or 0) > 0:
        from .uploads import media_present
        names = [(a.get("filename") or "") for a in (delivery.get("assets") or [])
                 if (a.get("filename") or "")]
        if names and all(media_present(conn, n) for n in names):
            return True                   # holes, and the bytes to fill them are here
    # THE COUNT, FIRST AND ALWAYS. This was only consulted when NO asset carried a
    # timestamp, so a package that had seen 2 assets and a delivery now holding 4 read as
    # fresh the moment any one of them had a date. Publishing dropped `at`, which put
    # exactly that mix on the board and shipped the previous ZIP to the client. A
    # different number of files is stale on its own — no dates required.
    if len(delivery.get("assets") or []) != int(zip_obj.get("asset_count") or -1):
        return True
    newest = ""
    for a in (delivery.get("assets") or []):
        newest = max(newest, (a.get("at") or a.get("created_at") or ""))
    for v in (delivery.get("versions") or []):
        newest = max(newest, (v.get("created_at") or v.get("at") or ""))
    # An asset with no timestamp cannot be compared; count the set instead, which is
    # the case that matters (a file was added after the build).
    if not newest:
        return len(delivery.get("assets") or []) != int(zip_obj.get("asset_count") or -1)
    return newest > built


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
        # …AND REBUILD THE PACKAGE IF IT IS STALE. This returned here unconditionally, so
        # the ZIP was assembled exactly ONCE — at whatever moment the delivery first
        # reached Delivered — and every asset published afterwards stayed outside it. A
        # client paid and downloaded a package with no audio in it (reported live,
        # 2026-08-20). Cheap to check, and the rebuild is idempotent.
        if _package_is_stale(delivery, conn):
            _build_delivery_package(conn, project_id)
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
def client_visibility(row, delivery: dict) -> dict:
    """Which stored files actually REACH the client, and which quietly do not.

    Reported live four times running: *"im in the client room and there is no new
    deliverables, i pushed it from the studio side. the client should be seeing it and i
    dont"* (operator, 2026-08-21). Every reproduction of that flow on a clean instance put
    the file in front of the client, which is exactly why it needed a measurement instead
    of another guess: the failure is in one project's DATA, and nothing on any screen
    compared what is STORED against what is SHOWN.

    The comparison is deliberately dumb and therefore trustworthy: take the filenames the
    client's own sign-off list would render, and subtract them from the filenames in
    ``assets``. Anything left over is stored, published, and invisible — which is the
    shape of the bug and cannot be argued with. It makes no assumption about WHY the
    lane matching missed, so it keeps working when the matching rules change.
    """
    from .uploads import media_present
    lanes, _rollup, _awa = scoped_signoff(row, delivery)
    shown = set()
    for lane in lanes:
        for fobj in (lane.get("files") or []):
            nm = (fobj.get("name") or "").strip()
            if nm:
                shown.add(nm)
    conn = _conn_for_presence()
    try:
        def _rec(a):
            fn = a.get("filename") or ""
            return {"name": (a.get("orig") or fn or "").strip(), "filename": fn,
                    "label": (a.get("label") or "").strip(),
                    # Bytes, not a row. A lane entry whose file is gone cannot be
                    # published (the gate refuses it) and cannot be heard — and looked
                    # identical to a healthy one until this said so.
                    "here": bool(conn is None or not fn or media_present(conn, fn))}
        published, hidden = [], []
        for a in (delivery.get("assets") or []):
            rec = _rec(a)
            (published if rec["name"] in shown else hidden).append(rec)
        waiting = [_rec(a) for a in (delivery.get("pending_assets") or [])]
    finally:
        if conn is not None:
            conn.close()
    return {
        "published": published,      # stored AND on the client's screen
        "hidden": hidden,            # stored, published, and not reaching them
        "waiting": waiting,          # still at the taste gate — correctly unseen
        "lane_labels": sorted({(x.get("asset") or "") for x in lanes}),
        "lost": [r for r in published + hidden + waiting if not r["here"]],
        "ok": not hidden,
    }


def _conn_for_presence():
    """Its own connection: this is a read-only diagnostic and must never depend on, or
    interfere with, whatever transaction the caller is in."""
    try:
        return db.connect()
    except Exception:      # noqa: BLE001 — a diagnostic may never break the page
        return None


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
    # EVERY asset under a label, not just the first. A stem package is twelve files in
    # one lane (ADR-0074) and this kept one of them, so the buyer was shown one player
    # and one Approve for a folder they had been sent whole — *"it only showcases 1 file
    # for each lane when in fact there were multiple files pushed per lane"* (operator,
    # 2026-08-19). The FIRST still drives `match`/`url` (the injective matching upstream
    # is per-label), and `all` carries the rest.
    by_label, all_by_label = {}, {}
    for a in assets_with_approval:
        lbl = (a.get("label") or a.get("filename") or "").strip()
        if not lbl:
            continue
        all_by_label.setdefault(lbl, []).append(a)
        if lbl not in by_label:
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
            # The whole lane, each file with its own key so one press can sign off all
            # of them and a partly-approved lane can say which are still outstanding.
            item["files"] = [
                {"name": (f.get("orig") or f.get("filename") or "file"),
                 "url": f.get("url") or "", "kind": f.get("kind") or "",
                 "asset_key": f.get("asset_key") or "",
                 "status": (f.get("approval") or {}).get("status") or "Pending"}
                for f in all_by_label.get(d.get("match") or "", [])
            ]
            # A lane counts as approved only when EVERY file in it is.
            if item["files"] and all(f["status"] == "Approved" for f in item["files"]):
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
        item.setdefault("files", [])
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
