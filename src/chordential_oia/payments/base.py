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

    def verify_return(self, params: Mapping) -> dict:
        """Did the payer who landed on our success URL actually pay?

        ``params`` is the query string of the return. Returns the same normalized
        shape as :meth:`handle_webhook` — ``{"invoice_id", "status", "external_ref"}``
        — and ``{}`` when payment cannot be PROVEN, which includes every error.

        This exists because a success URL is not evidence. ``/pay/return?invoice=7``
        was a plain GET, exempt from the admin gate, that marked invoice 7 Paid,
        unlocked the client's downloads, queued crew payouts and emailed a receipt —
        for anyone who typed it. The browser belongs to the payer, and the payer is
        not a trusted party; only the provider that issued a checkout can say what
        became of it.

        A provider that cannot verify returns ``{}`` rather than assume. The
        signature-verified webhook is the authoritative door and is untouched, so
        "not confirmed here" costs a few seconds, never a payment.
        """
        ...
