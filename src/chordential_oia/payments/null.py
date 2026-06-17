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
