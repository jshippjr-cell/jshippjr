"""Deterministic no-op payment provider — the default.

Runs now and in tests. ``create_checkout`` returns a stable, deterministic
reference (no network), so the invoice flow works end-to-end without any payment
account. Swapping in Stripe later changes only which provider is selected.
"""

from __future__ import annotations

from typing import Mapping


class NullPaymentProvider:
    name = "null"

    def create_checkout(self, invoice: Mapping) -> str:
        # Deterministic, reproducible reference — no external call.
        return f"null-checkout-{str(invoice['kind']).lower()}-{invoice['id']}"

    def handle_webhook(self, payload: Mapping) -> dict:
        # No real webhooks in deterministic mode.
        return {}

    def verify_return(self, params: Mapping) -> dict:
        """Never vouches for a payment, because it never took one.

        The reference this provider hands back is not a URL, so ``client_pay``
        bounces with "online payment isn't switched on" and no payer is ever sent to
        a success URL. Anything arriving at ``/pay/return`` under this provider was
        typed by hand — which is exactly the request that used to mark an invoice
        Paid. Returning ``{}`` is the honest answer AND the safe one.
        """
        return {}
