"""The money doors — proposal price, invoice status, checkout, and the payment webhook.

ADR-0044, slice 11. Seven routes with **no helpers of their own**: the chain they drive
(`proposal -> invoice -> payment -> receipt`) already lives in :mod:`billing`, moved there
in slice 4. What is here is only the HTTP surface over it.

``/webhooks/stripe`` and ``/pay/return`` are the two doors a payment can arrive through,
and both call the same idempotent `billing.apply_invoice_payment` — the first to arrive
takes effect and the second is a no-op. That is deliberate: neither door can be trusted to
fire exactly once.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..payments import get_payment_provider
from . import db
from .billing import _apply_invoice_payment, _client_portal_url, _send_invoice_pay_link
from .talent_routes import _parse_rate

router = APIRouter(tags=["billing"])


@router.post("/proposal/{proposal_id}/price")
def proposal_set_price(
    proposal_id: int, total_price: str = Form(...), deposit_pct: str = Form("50"),
):
    """Override a proposal's price with a custom, hand-agreed number — for deals
    quoted per-contract rather than off the estimator (e.g. a flat productized
    offer). Deposit/balance recompute from the new total; the existing invoice +
    Stripe-checkout + payment-gate + revenue-dashboard pipeline is unchanged."""
    conn = db.connect()
    try:
        p = db.get_proposal(conn, proposal_id)
        if p is None:
            return RedirectResponse("/projects", status_code=303)
        total = _parse_rate(total_price)
        if total is not None:
            pct = _parse_rate(deposit_pct) or 50.0
            pct = max(0.0, min(100.0, pct)) / 100.0
            db.update_proposal_price(conn, proposal_id, total, pct)
            if p["project_id"]:
                db.add_update(conn, p["project_id"],
                              f"Proposal price set to {total:,.0f} (custom).", "proposal")
    finally:
        conn.close()
    if p is not None and p["project_id"]:
        return RedirectResponse(f"/project/{p['project_id']}/proposal", status_code=303)
    return RedirectResponse("/projects", status_code=303)


@router.post("/proposal/{proposal_id}/status")
def proposal_set_status(proposal_id: int, status: str = Form(...)):
    conn = db.connect()
    try:
        db.update_proposal_status(conn, proposal_id, status)
        p = db.get_proposal(conn, proposal_id)
        if p is not None and p["project_id"]:
            db.add_update(conn, p["project_id"], f"Proposal {status}.", "proposal")
            return RedirectResponse(
                f"/project/{p['project_id']}/proposal", status_code=303
            )
    finally:
        conn.close()
    return RedirectResponse("/projects", status_code=303)


@router.post("/invoice/{invoice_id}/checkout")
def invoice_checkout(invoice_id: int):
    """Create a checkout for an invoice through the selected payment provider.

    Today the Null provider returns a deterministic reference and the invoice is
    marked Issued; later, selecting the Stripe provider makes this create a real
    checkout — this route and the engines do not change.
    """
    conn = db.connect()
    try:
        inv = db.get_invoice(conn, invoice_id)
        if inv is None:
            return RedirectResponse("/projects", status_code=303)
        ref = get_payment_provider().create_checkout(inv)
        db.update_invoice_status(conn, invoice_id, "Issued", external_ref=ref)
        if inv["project_id"]:
            db.add_update(
                conn, inv["project_id"],
                f"{inv['kind']} invoice issued for payment.", "invoice",
            )
            return RedirectResponse(
                f"/project/{inv['project_id']}/proposal", status_code=303
            )
    finally:
        conn.close()
    return RedirectResponse("/projects", status_code=303)


@router.post("/invoice/{invoice_id}/send-pay-link")
def invoice_send_pay_link(invoice_id: int):
    """Operator action: email the client a secure pay link for this invoice — so the balance
    actually reaches them instead of sitting in the queue (reported live). Best-effort;
    bounces back with a flash on the proposal page."""
    conn = db.connect()
    try:
        inv = db.get_invoice(conn, invoice_id)
        if inv is None or not inv["project_id"]:
            return RedirectResponse("/projects", status_code=303)
        pid = inv["project_id"]
        flag = _send_invoice_pay_link(conn, invoice_id)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{pid}/proposal?pay={flag}", status_code=303)


@router.get("/pay/return", response_class=HTMLResponse)
def pay_return(request: Request, invoice: int = 0):
    """Stripe ``success_url`` target — the payer lands here after a COMPLETED checkout. Applies
    the payment (idempotent — the signature-verified webhook may have beaten the browser here)
    and returns to the workspace/portal with a thank-you."""
    conn = db.connect()
    dest = "/"
    try:
        inv = db.get_invoice(conn, invoice) if invoice else None
        if inv is not None and inv["project_id"]:
            _apply_invoice_payment(conn, invoice)
            pid = inv["project_id"]
            prow = db.get_project(conn, pid)
            if inv["kind"] == "Final":
                dest = _client_portal_url(pid, db.ensure_project_share_token(conn, pid) or "", "paid=1")
            elif prow is not None and prow["opp_id"]:
                dest = f"/workspace/{db.ensure_share_token(conn, prow['opp_id'])}?paid=1"
    finally:
        conn.close()
    return RedirectResponse(dest, status_code=303)


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Stripe payment webhook — the AUTHORITATIVE, signature-verified confirmation of a
    completed payment, independent of whether the payer's browser ever returns. Verifies the
    ``Stripe-Signature`` via the provider (``STRIPE_WEBHOOK_SECRET``), and on a captured
    payment marks the invoice Paid + unlocks downloads + queues payouts, idempotently.
    Bypasses the admin gate (Stripe posts server-to-server) — the signature IS the auth."""
    body = await request.body()
    sig = (request.headers.get("stripe-signature")
           or request.headers.get("Stripe-Signature") or "")
    try:
        event = get_payment_provider().handle_webhook({"body": body, "signature": sig}) or {}
    except Exception:  # noqa: BLE001 — bad signature / malformed body → 400, never 500
        return JSONResponse({"ok": False, "error": "invalid"}, status_code=400)
    inv_id = event.get("invoice_id")
    applied = False
    if inv_id and (event.get("status") or "").lower() == "paid":
        conn = db.connect()
        try:
            applied = _apply_invoice_payment(conn, int(inv_id), event.get("external_ref") or "")
        finally:
            conn.close()
    return JSONResponse({"ok": True, "applied": applied})


@router.post("/invoice/{invoice_id}/status")
def invoice_set_status(invoice_id: int, status: str = Form(...)):
    conn = db.connect()
    try:
        inv = db.get_invoice(conn, invoice_id)
        if inv is None:
            return RedirectResponse("/projects", status_code=303)
        db.update_invoice_status(conn, invoice_id, status)
        if inv["project_id"]:
            db.add_update(
                conn, inv["project_id"],
                f"{inv['kind']} invoice {status.lower()}.", "invoice",
            )
            # Client payment in → generate the crew payout ledger (Owed). Idempotent.
            if status == "Paid":
                n = db.ensure_project_payouts(conn, inv["project_id"])
                if n:
                    db.add_update(conn, inv["project_id"],
                                  f"{n} crew payout(s) queued (Owed).", "invoice")
            return RedirectResponse(
                f"/project/{inv['project_id']}/proposal", status_code=303
            )
    finally:
        conn.close()
    return RedirectResponse("/projects", status_code=303)
