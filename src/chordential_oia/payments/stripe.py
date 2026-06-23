"""Stripe payment provider — Phase 1 wire-up (Checkout + webhook).

The ``stripe`` SDK is imported lazily *inside* methods, so merely importing this
module never requires the package — the app runs fine on the Null provider with no
Stripe installed. Selected only when ``CHORDENTIAL_PAYMENT_PROVIDER=stripe``.

Config (env): ``STRIPE_SECRET_KEY`` (required), ``STRIPE_WEBHOOK_SECRET`` (for
signature verification), ``CHORDENTIAL_PUBLIC_DOMAIN`` (absolute https base for the
success/cancel redirects). The DB stays the source of truth: ``create_checkout``
stamps the invoice id onto the session (``client_reference_id`` + ``metadata``), and
``handle_webhook`` maps a paid session back to that invoice id.
"""

from __future__ import annotations

import json
import os
from typing import Mapping

# Stripe events that mean "the customer's money has been captured".
_PAID_EVENTS = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
_PAID_STATUSES = {"paid", "no_payment_required"}


class StripePaymentProvider:
    name = "stripe"

    def __init__(self) -> None:
        # Read config from env at construction; never hard-codes secrets.
        self.secret_key = os.environ.get("STRIPE_SECRET_KEY")
        self.webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
        self.domain = os.environ.get("CHORDENTIAL_PUBLIC_DOMAIN")

    def _client(self):
        try:
            import stripe  # lazy: absence never breaks app import
        except ImportError as exc:  # pragma: no cover - exercised only without SDK
            raise RuntimeError(
                "The 'stripe' package is not installed. Add the 'stripe' extra "
                "and set STRIPE_SECRET_KEY to enable live payments."
            ) from exc
        if not self.secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not set.")
        stripe.api_key = self.secret_key
        return stripe

    def create_checkout(self, invoice: Mapping) -> str:
        """Create a hosted Stripe Checkout Session for an invoice and return its
        URL (stored as the invoice ``external_ref`` and where the customer pays).
        Wallets (Apple/Google Pay) are automatic for card Checkout. The invoice id
        rides on the session so the webhook can reconcile against our DB."""
        stripe = self._client()
        inv_id = invoice["id"]
        kind = invoice["kind"]
        amount_cents = int(round(float(invoice["amount"]) * 100))
        note = (invoice["note"] or "") if "note" in invoice.keys() else ""
        # Redirect to a PUBLIC page — the payer isn't the admin, so never land
        # them on an admin-gated route. (Phase 2 adds a branded receipt page.)
        domain = (self.domain or "https://chordential.com").rstrip("/")

        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=f"{domain}/?paid={inv_id}",
            cancel_url=f"{domain}/?canceled={inv_id}",
            client_reference_id=str(inv_id),
            metadata={"invoice_id": str(inv_id), "kind": str(kind)},
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount_cents,
                    "product_data": {
                        "name": f"Chordential — {kind} invoice",
                        "description": note[:300] or f"{kind} payment",
                    },
                },
            }],
        )
        return session.url

    def handle_webhook(self, payload: Mapping) -> dict:
        """Verify + interpret a Stripe webhook. ``payload`` carries the raw
        ``body`` (bytes/str) and ``signature`` header. Returns
        ``{"invoice_id", "status": "Paid", "external_ref"}`` for a captured
        payment, else ``{}`` (ignored). Verification uses STRIPE_WEBHOOK_SECRET;
        if it's unset we parse without verifying (dev only)."""
        stripe = self._client()
        body = payload.get("body")
        signature = payload.get("signature")
        if self.webhook_secret:
            # Raises on a bad signature — the route turns that into a 400.
            event = stripe.Webhook.construct_event(body, signature, self.webhook_secret)
        else:
            raw = body.decode() if isinstance(body, (bytes, bytearray)) else (body or "{}")
            event = json.loads(raw)

        if event.get("type") not in _PAID_EVENTS:
            return {}
        obj = event.get("data", {}).get("object", {})
        if obj.get("payment_status") not in _PAID_STATUSES:
            return {}
        ref = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("invoice_id")
        if ref is None:
            return {}
        return {
            "invoice_id": int(ref),
            "status": "Paid",
            "external_ref": obj.get("payment_intent") or obj.get("id"),
        }
