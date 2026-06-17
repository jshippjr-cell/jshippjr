"""Stripe payment provider — the later wire-up seam (stub).

Intentionally not implemented yet: Jon provides the Stripe account, secret key,
and a real domain, and this is the ONLY file (plus a webhook route) that changes.
The ``stripe`` SDK is imported lazily *inside* methods so that merely importing
this module never requires the package — the app runs fine with the Null provider
and no Stripe installed.
"""

from __future__ import annotations

import os
from typing import Mapping


class StripePaymentProvider:
    name = "stripe"

    def __init__(self) -> None:
        # Read config from env at construction; never hard-codes secrets.
        self.secret_key = os.environ.get("STRIPE_SECRET_KEY")
        self.domain = os.environ.get("CHORDENTIAL_PUBLIC_DOMAIN")

    def _client(self):  # pragma: no cover - exercised only once Stripe is wired
        try:
            import stripe  # lazy: absence never breaks app import
        except ImportError as exc:
            raise RuntimeError(
                "The 'stripe' package is not installed. Add the 'stripe' extra "
                "and set STRIPE_SECRET_KEY to enable live payments."
            ) from exc
        if not self.secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not set.")
        stripe.api_key = self.secret_key
        return stripe

    def create_checkout(self, invoice: Mapping) -> str:  # pragma: no cover - not wired yet
        raise NotImplementedError(
            "Stripe checkout is not wired yet — provide STRIPE_SECRET_KEY and a "
            "domain, then implement this method (the only change needed here)."
        )

    def handle_webhook(self, payload: Mapping) -> dict:  # pragma: no cover - not wired yet
        raise NotImplementedError(
            "Stripe webhook handling is not wired yet."
        )
