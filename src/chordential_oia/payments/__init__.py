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


def payments_status() -> dict:
    """What the money seam is ACTUALLY doing, for the boot line to report.

    Reads env only — no SDK import, no network — so it is safe at startup and in tests.
    Three states are worth distinguishing because they fail in three different places:
    the Null provider fails politely on a page, a missing secret key fails when a buyer
    presses Pay, and a missing webhook secret does not fail at all — it leaves
    ``/webhooks/stripe`` accepting unverified "mark this invoice paid" events.
    """
    live = os.environ.get(PROVIDER_ENV, "null").strip().lower() == "stripe"
    key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    return {
        "provider": "stripe" if live else "null",
        "live": live,
        "key": bool(key),
        # sk_live_… vs sk_test_… — worth saying out loud, because "we were still on the
        # test key" is discovered from a month of payments that never arrived.
        "mode": ("live" if key.startswith("sk_live") else
                 "test" if key.startswith("sk_test") else "unknown"),
        "webhook_verified": bool((os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()),
    }


def boot_line() -> str:
    """The one sentence the app prints at startup about money.

    Composed here rather than in ``app.py`` because ADR-0044 ratchets that file down and
    a paragraph of branching prose is exactly what put 9,133 lines in it. ``app.py``
    prints; this decides what there is to say.
    """
    s = payments_status()
    if not s["live"]:
        return ("Null provider — Pay buttons say online payment is not switched on. Set "
                "CHORDENTIAL_PAYMENT_PROVIDER=stripe + STRIPE_SECRET_KEY to take money.")
    if not s["key"]:
        return ("WARNING: provider=stripe but STRIPE_SECRET_KEY is NOT set — every "
                "checkout will fail at the moment a client presses Pay.")
    if not s["webhook_verified"]:
        return ("WARNING: Stripe is live but STRIPE_WEBHOOK_SECRET is NOT set — "
                "/webhooks/stripe accepts UNVERIFIED events, so anyone who finds the URL "
                "can mark an invoice paid. Set the signing secret.")
    return f"Stripe live ({s['mode']} key), webhook signature verified."


__all__ = ["PaymentProvider", "NullPaymentProvider", "get_payment_provider",
           "payments_status", "boot_line"]
