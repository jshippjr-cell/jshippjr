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
        # Read config from env at construction; never hard-codes secrets. .strip()
        # guards the common copy-paste gotcha — a trailing space/newline in the env
        # var breaks Stripe's exact-match signature verification.
        self.secret_key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip() or None
        self.webhook_secret = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip() or None
        self.domain = (os.environ.get("CHORDENTIAL_PUBLIC_DOMAIN") or "").strip() or None

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

        # `{CHECKOUT_SESSION_ID}` is substituted by Stripe on the redirect, and it is
        # what makes the return VERIFIABLE: `verify_return` hands it back to Stripe and
        # asks what actually happened. Without it the success URL was a bare invoice id
        # that anyone could type — see `verify_return` and ADR-0085. The invoice id
        # stays on the URL for navigation only; it decides nothing about money.
        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=(f"{domain}/pay/return?invoice={inv_id}"
                         f"&session_id={{CHECKOUT_SESSION_ID}}"),
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

    def verify_return(self, params: Mapping) -> dict:
        """Ask Stripe what became of the checkout the payer just came back from.

        The ``session_id`` on the success URL is written by Stripe, not by the payer,
        and is unguessable — but it is not treated as a secret here either. It is a
        LOOKUP KEY: the session is retrieved server-side and the answer comes from
        Stripe's copy, so a forged or stale id proves nothing and yields ``{}``.

        The invoice id is taken from the SESSION (``client_reference_id`` /
        ``metadata``), never from the query string. That is the difference between
        "this payer paid for this invoice" and "this payer paid for something, and
        also typed an invoice number".
        """
        session_id = str((params or {}).get("session_id") or "").strip()
        if not session_id:
            return {}
        try:
            session = self._client().checkout.Session.retrieve(session_id)
        except Exception:      # noqa: BLE001 — unknown id, network, bad key: unproven
            return {}
        get = session.get if hasattr(session, "get") else (lambda k, d=None: getattr(session, k, d))
        if get("payment_status") not in _PAID_STATUSES:
            return {}
        ref = get("client_reference_id") or (get("metadata") or {}).get("invoice_id")
        if ref is None:
            return {}
        try:
            invoice_id = int(ref)
        except (TypeError, ValueError):
            return {}
        return {
            "invoice_id": invoice_id,
            "status": "Paid",
            "external_ref": get("payment_intent") or get("id") or session_id,
        }

    def handle_webhook(self, payload: Mapping) -> dict:
        """Verify + interpret a Stripe webhook. ``payload`` carries the raw
        ``body`` (bytes/str) and ``signature`` header. Returns
        ``{"invoice_id", "status": "Paid", "external_ref"}`` for a captured
        payment, else ``{}`` (ignored). Verification uses STRIPE_WEBHOOK_SECRET;
        if it's unset we parse without verifying (dev only)."""
        body = payload.get("body")
        signature = payload.get("signature")
        # Verify authenticity (raises on a bad signature → the route returns 400).
        # We discard the returned object and parse the raw JSON ourselves below,
        # because the SDK's typed event objects don't all support dict .get().
        if self.webhook_secret:
            self._client().Webhook.construct_event(body, signature, self.webhook_secret)
        raw = body.decode() if isinstance(body, (bytes, bytearray)) else (body or "{}")
        event = json.loads(raw)

        if event.get("type") not in _PAID_EVENTS:
            return {}
        obj = (event.get("data") or {}).get("object") or {}
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
