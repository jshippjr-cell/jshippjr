"""Payment provider seam.

The deterministic proposal/invoice engines never import a payment SDK. Instead,
charging money goes through a :class:`PaymentProvider` selected at runtime by env.
Today that's the deterministic :class:`~chordential_oia.payments.null.NullPaymentProvider`;
the Stripe implementation drops in later touching only ``payments/stripe.py`` and a
webhook route — no change to the engines, routes' shape, or the DB schema (the
``external_ref`` / ``paid_at`` invoice columns already exist).
"""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class PaymentProvider(Protocol):
    """Minimal contract every payment backend implements."""

    #: Stable provider name ("null", "stripe").
    name: str

    def create_checkout(self, invoice: Mapping) -> str:
        """Create a payment intent/checkout for an invoice and return a reference
        (a checkout URL or provider id) to store on the invoice as external_ref."""
        ...

    def handle_webhook(self, payload: Mapping) -> dict:
        """Interpret a provider webhook into a normalized event dict, e.g.
        ``{"invoice_ref": ..., "status": "Paid"}``. Returns ``{}`` if irrelevant."""
        ...
