"""Payment provider selection.

``get_payment_provider`` returns the provider chosen by the
``CHORDENTIAL_PAYMENT_PROVIDER`` env var ("null" | "stripe"), defaulting to the
deterministic Null provider. This is the single seam where Stripe slots in later;
nothing else in the app references a payment SDK.
"""

from __future__ import annotations

import os

from .base import PaymentProvider
from .null import NullPaymentProvider

PROVIDER_ENV = "CHORDENTIAL_PAYMENT_PROVIDER"


def get_payment_provider() -> PaymentProvider:
    choice = os.environ.get(PROVIDER_ENV, "null").strip().lower()
    if choice == "stripe":
        from .stripe import StripePaymentProvider  # lazy import — no SDK needed otherwise
        return StripePaymentProvider()
    return NullPaymentProvider()


__all__ = ["PaymentProvider", "NullPaymentProvider", "get_payment_provider"]
