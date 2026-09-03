"""Proposal -> invoice -> payment -> receipt.

The money chain, lifted out of ``app.py`` whole. Its entry points are called from three
route groups that do not otherwise share code — /project (raise and send an invoice),
/pay and /webhooks (a payment settles), /invoice (the operator's send button) — which is
why it could not stay in the route layer of any one of them.

``apply_invoice_payment`` is the idempotent door: the Stripe success-return and the
webhook both call it and only the first one takes effect.
"""

from __future__ import annotations

import json

from .. import mailer
from ..estimation import RoleLine
from ..invoicing import build_invoice
from ..payments import get_payment_provider
from ..proposals import Proposal
from . import db, room, signals
from .shell import public_base as _public_base


def _proposal_from_row(row) -> Proposal:
    """Reconstruct a Proposal object from a stored row (for render/export)."""
    items = json.loads(row["line_items"]) if row["line_items"] else []
    lines = []
    for i in items:
        line = RoleLine(i["role"], i["hours"], i["rate"], unit=i.get("unit", "hourly"))
        # Preserve a day/flat line cost that isn't simply hours × rate (e.g. an
        # assigned talent's day or per-project rate) so the stored doc renders as
        # generated.
        stored_cost = i.get("cost")
        if stored_cost is not None and abs(stored_cost - line.hours * line.rate) > 1e-9:
            line.cost_override = stored_cost
        lines.append(line)
    return Proposal(
        client="", need="", discipline="", lines=lines,
        total_price=row["total_price"], deposit_pct=row["deposit_pct"],
        deposit_amount=row["deposit_amount"], balance_due=row["balance_due"],
        terms=json.loads(row["terms"]) if row["terms"] else [],
    )


def _invoice_from_proposal_row(prow, prop_row, kind: str):
    """Build an Invoice from the stored proposal (client/need from the project)."""
    obj = _proposal_from_row(prop_row)
    obj.client = prow["client"]
    obj.need = prow["need"]
    return build_invoice(obj, kind)


def _heal_proposal(conn, project_id: int, heal=None):
    """Write the missing ``proposals`` row from the SIGNED agreement, and return it.

    Countersigning writes this row (ADR-0067) — but only since the day that code landed.
    A deal countersigned before it has a signature, a countersignature and a document
    stating the fee, the deposit and "balance due on delivery", and no row anywhere for
    the money surfaces to read. The operator's reaction was the right one: *"i thought
    that was already agreed upon when i got the signature."* It was. Nothing here decides
    a price — `_ensure_proposal_for_project` reads the band out of the document the
    client actually signed, and refuses if it is not priced.

    ``heal`` is ``opportunity_ops._ensure_proposal_for_project``, PASSED IN rather than
    imported: this module sits below that one in the helper DAG (ADR-0044), and reaching
    up for it would make the load order load-bearing again. Same arrangement as
    ``room.room_view(build=…)``. Without one, nothing is healed and the block is reported
    as it stands — the callers that can supply it are the route modules.

    Idempotent, best-effort, and silent on failure: a heal that could 500 the delivery it
    is trying to unblock would be worse than the gap.
    """
    if heal is None:
        return None
    prow = db.get_project(conn, project_id)
    opp_id = prow["opp_id"] if prow is not None and "opp_id" in prow.keys() else None
    if not opp_id:
        return None
    try:
        heal(conn, opp_id, project_id)
    except Exception:  # noqa: BLE001 — see docstring
        return None
    return db.proposal_for_project(conn, project_id)


def _ensure_final_invoice_issued(conn, project_id: int, heal=None) -> None:
    """When the package is finalized, raise the balance (Final) invoice as *Issued* so it is a
    real outstanding amount. Without this, the download gate treats a paid DEPOSIT as
    "paid in full" (the balance invoice is created lazily, so nothing shows outstanding) and
    the files unlock without the balance ever being paid — reported live. Idempotent; needs a
    stored proposal and a non-zero balance."""
    prow = db.get_project(conn, project_id)
    prop = (db.proposal_for_project(conn, project_id)
            or _heal_proposal(conn, project_id, heal))
    if prow is None or prop is None:
        return
    inv = next((i for i in db.list_invoices(conn, project_id)
                if (i["kind"] or "") == "Final"), None)
    if inv is None:
        new_id = db.insert_invoice(
            conn, project_id, prop["id"], _invoice_from_proposal_row(prow, prop, "Final"))
        inv = db.get_invoice(conn, new_id)
    if inv is None:
        return
    status = (inv["status"] or "").lower()
    if (inv["amount"] or 0) and status in ("", "draft"):
        db.update_invoice_status(conn, inv["id"], "Issued")


def _payment_request_email(kind: str, amount: float, client: str, need: str,
                           contact_name: str, pay_url: str) -> dict:
    """A branded 'here's your invoice — pay securely' email for the client."""
    first = (contact_name or "").strip().split()[0] if contact_name.strip() else ""
    greeting = f"Hi {first}," if first else "Hi there,"
    amt = f"${amount:,.0f}" if amount else "your balance"
    label = (kind or "Payment").strip()
    is_final = label.lower().startswith("fin")
    lead = ("Your project is delivered and the final balance is due to release your files."
            if is_final else
            "Here's your deposit invoice to get production underway.")
    tail = ("The moment it's in, your full delivery package unlocks for download."
            if is_final else "Your deposit reserves the team and starts the work.")
    body = (
        f"{greeting}\n\n"
        f"{lead}\n\n"
        f"  {label} due:  {amt}\n"
        f"  Project:      {need or 'your campaign'}\n\n"
        f"Pay securely here:\n{pay_url}\n\n"
        f"{tail}\n\n"
        "Jon, Chordential")
    subject = f"{label} due ({amt}) · {need or 'your campaign'}"
    return {"subject": subject, "body": body}


def final_invoice_block(conn, project_id: int, heal=None) -> str:
    """Why this delivery cannot be paid for yet — "" when it can.

    A delivery reaches the paywall by being Delivered with an outstanding Final invoice.
    Every path that RAISES that invoice needs a stored proposal, and returns silently
    when there is none — so a project without one sails through the whole delivery,
    assembles its package, locks the download behind a balance that does not exist, and
    tells the client their files are "being assembled". Reported live (2026-08-19):
    everything signed off, and no way to pay.

    Money is never invented here. This only NAMES the block, so the client sees something
    true and the operator sees an action.
    """
    inv = next((i for i in db.list_invoices(conn, project_id)
                if (i["kind"] or "") == "Final"), None)
    if inv is not None:
        if (inv["status"] or "").lower() in ("", "draft"):
            return "draft"          # raised but never issued — not owed yet
        if not (inv["amount"] or 0):
            return "zero"           # issued for nothing
        return ""
    if db.proposal_for_project(conn, project_id) is not None:
        return ""
    # A deal countersigned before ADR-0067 has the money in its SIGNED document and no
    # row for it. Heal from the signature before calling it unbillable.
    return "" if _heal_proposal(conn, project_id, heal) is not None else "noproposal"


#: What each ``final_invoice_block`` reason means to each side. The client is told the
#: truth without our plumbing; the operator is told what to press.
INVOICE_BLOCK_CLIENT = {
    "noproposal": ("Chordential is preparing your invoice for the balance — you'll get it "
                   "by email, and your files unlock the moment it's settled."),
    "draft": ("Chordential is finalising your invoice for the balance — you'll get it by "
              "email, and your files unlock the moment it's settled."),
    "zero": "Nothing further is due. Chordential is releasing your files.",
}
INVOICE_BLOCK_OPERATOR = {
    "noproposal": ("This delivery is signed off and the client CANNOT PAY: there is no "
                   "proposal on the project, so no balance invoice can be raised from "
                   "one. Raise it by hand below."),
    "draft": "The balance invoice is still a draft — issue it so the client is asked for it.",
    "zero": "The balance invoice is for zero, so nothing gates the download.",
}


#: What each ``?pay=`` bounce means, in the client's language. Every failure path off
#: ``/project/<id>/pay`` used to redirect with a flag and only ONE of them was rendered
#: anywhere — so a client pressed Pay, the page reloaded, and nothing said why: *"i click
#: it and it does nothing"* (operator, 2026-08-19). A payment that cannot start must say
#: so; silence reads as a broken button, and on a payment button that is the worst thing
#: it can read as.
PAY_NOTICES = {
    "unavailable": ("Online card payment isn't switched on yet. Chordential will send you "
                    "a secure payment link — nothing is owed twice."),
    "already": "That invoice is already settled. Nothing further is due.",
    "noinvoice": ("We couldn't raise this invoice automatically. Chordential has been "
                  "told and will send it to you directly."),
    "error": ("Something went wrong starting that payment, and nothing was charged. "
              "Chordential has been told."),
}


def pay_notice(flag: str) -> str:
    """The sentence for a ``?pay=`` flag, or "" when there is nothing to say."""
    return PAY_NOTICES.get((flag or "").strip().lower(), "")


# `_client_portal_url` USED TO LIVE HERE and has no callers left (2026-08-30). Every
# buyer-facing money link — the pay-link email, the Stripe return, the payment bounce —
# now mints `_client_room_url`. What still reaches the portal are the REVIEWER paths
# (`?r=`): the clearance signature and the delegate invite, which are a different
# credential doing a different job, and they build their own URLs where they are used.


def _client_room_url(project_id: int, k: str, extra: str = "") -> str:
    """Where the buyer goes, on the project's own share token.

    *"the client is sent an email to pay the final invoice and the link in that email goes
    to the old project delivery portal… it needs to go to the room… keep the client in the
    room"* (operator, 2026-08-30). ADR-0093 moved the client into the room at the
    countersignature and ADR-0096 pointed the operator's alerts there; these are the last
    links that still carried a buyer somewhere else — the pay-link email, the Stripe
    return, the "new version is ready" note and the payment bounce.

    `room.client_url` mints from an OPPORTUNITY token; this takes the PROJECT share token,
    which is what the money paths already hold. Both open the same door.
    """
    q = f"?k={k}" if k else ""
    if extra:
        q = (q + "&" if q else "?") + extra
    return f"/room/{project_id}{q}#p{project_id}"


def _send_invoice_pay_link(conn, invoice_id: int) -> str:
    """Email the CLIENT a secure pay link for one invoice. Issues the invoice if it's still a
    draft, then sends a branded payment request to the opportunity's contact with a link to
    their token-gated portal (where the Pay button opens a fresh checkout — a hosted-checkout
    URL can expire, the portal never does). Returns a status: 'sent' | 'no_email' | 'no_mail'
    | 'error'. Shared by the operator button AND the automatic send on delivery."""
    inv = db.get_invoice(conn, invoice_id)
    if inv is None or not inv["project_id"]:
        return "error"
    pid = inv["project_id"]
    if (inv["status"] or "").lower() in ("", "draft"):
        ref = get_payment_provider().create_checkout(inv)
        db.update_invoice_status(conn, invoice_id, "Issued", external_ref=ref)
        inv = db.get_invoice(conn, invoice_id)
    prow = db.get_project(conn, pid)
    opp = db.get_opportunity(conn, prow["opp_id"]) if prow and prow["opp_id"] else None
    contact_email = (opp["contact_email"] if opp is not None
                     and "contact_email" in opp.keys() else "") or ""
    if not contact_email:
        return "no_email"
    if not mailer.mail_configured():
        return "no_mail"
    base = _public_base()
    token = db.ensure_project_share_token(conn, pid)
    pay_url = f"{base}{_client_room_url(pid, token)}"
    contact_name = (opp["contact_name"] if opp is not None
                    and "contact_name" in opp.keys() else "") or ""
    msg = _payment_request_email(inv["kind"], inv["amount"] or 0,
                                 (prow["client"] if prow else "") or "",
                                 (prow["need"] if prow else "") or "", contact_name, pay_url)
    try:
        mailer.send_email(contact_email, msg["subject"], msg["body"],
                          html=mailer.branded_html(base, msg["body"]))
        db.add_update(conn, pid, f"{inv['kind']} pay link emailed to {contact_email}.",
                      "invoice")
        return "sent"
    except Exception:  # noqa: BLE001
        return "error"


def _payment_receipt_email(kind: str, amount: float, client: str, need: str,
                           contact_name: str, workspace_url: str, paid_at: str) -> dict:
    """A clean, branded receipt for the client when their payment settles."""
    first = (contact_name or "").strip().split()[0] if contact_name.strip() else ""
    greeting = f"Hi {first}," if first else "Hi there,"
    amt = f"${amount:,.0f}" if amount else "your payment"
    label = (kind or "Payment").strip()
    date = (paid_at or "")[:10]
    tail = ("Your deposit is in and we're getting production underway. You'll hear from us "
            "at your first creative milestone."
            if label.lower().startswith("dep") else
            "Your balance is settled and your final files are unlocked in your room.")
    body = (
        f"{greeting}\n\n"
        f"Thank you. We've received your {label.lower()} payment. This is your receipt.\n\n"
        f"  Payment:  {label}\n"
        f"  Amount:   {amt}\n"
        f"  Project:  {need or 'your campaign'}\n"
        + (f"  Date:     {date}\n" if date else "")
        + f"\n{tail}\n\n"
        + (f"Everything for your campaign lives in your room:\n{workspace_url}\n\n"
           if workspace_url else "")
        + "Jon, Chordential"
    )
    subject = f"Receipt · {label} payment received ({amt})"
    return {"subject": subject, "body": body}


def _notify_payment_settled(conn, inv, pid: int) -> None:
    """Best-effort notifications when a payment settles: a receipt to the client and a phone
    alert to the operator. Never raises — a notification failure must not undo the payment."""
    try:
        project = db.get_project(conn, pid)
        opp = (db.get_opportunity(conn, project["opp_id"])
               if project is not None and project["opp_id"] else None)
        kind = inv["kind"] or "Payment"
        amount = inv["amount"] or 0
        client = (project["client"] if project is not None else "") or (
            opp["client"] if opp is not None else "a client")
        need = project["need"] if project is not None else ""
        # Operator phone push — the immediate "you got paid" alert.
        signals.fire_and_forget(signals.notify_payment_received, client, kind,
                                f"${amount:,.0f}" if amount else "")
        # Client receipt email.
        contact_email = (opp["contact_email"] if opp is not None
                         and "contact_email" in opp.keys() else "") or ""
        if contact_email and mailer.mail_configured():
            base = _public_base()
            # The receipt is post-award by definition — an invoice needs a project — so
            # its link is the room (`room.client_url`).
            link = room.client_url(conn, db, opp["id"], base=base) if opp is not None else ""
            contact_name = (opp["contact_name"] if opp is not None
                            and "contact_name" in opp.keys() else "") or ""
            receipt = _payment_receipt_email(
                kind, amount, client, need, contact_name, link, inv["paid_at"] or "")
            mailer.send_email(contact_email, receipt["subject"], receipt["body"],
                              html=mailer.branded_html(base, receipt["body"]))
    except Exception:  # noqa: BLE001 — notifications are best-effort
        pass


def _apply_invoice_payment(conn, invoice_id: int, external_ref: str = "") -> bool:
    """Mark an invoice Paid and apply its side effects — unlock the client's downloads
    (Final) + queue crew payouts + notify (client receipt, operator alert) — exactly once.
    Idempotent: a no-op if already paid, so the Stripe success-return and the webhook can
    BOTH fire without double-applying."""
    inv = db.get_invoice(conn, invoice_id)
    if inv is None or not inv["project_id"]:
        return False
    if (inv["status"] or "").lower() in ("paid", "settled"):
        return False
    pid = inv["project_id"]
    db.update_invoice_status(conn, inv["id"], "Paid", external_ref=external_ref or None)
    if (inv["kind"] or "") == "Final":
        db.update_delivery(conn, pid, "download_unlocked", True)
    db.ensure_project_payouts(conn, pid)
    db.add_update(conn, pid, f"{inv['kind']} invoice paid. Thank you.", "invoice")
    # Re-read so the receipt carries the stamped paid_at.
    _notify_payment_settled(conn, db.get_invoice(conn, inv["id"]) or inv, pid)
    return True
