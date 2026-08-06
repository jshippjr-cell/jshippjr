"""Signature provider selection.

``get_signature_provider`` returns the provider chosen by
``CHORDENTIAL_SIGNATURE_PROVIDER``, defaulting to the in-house one — which is a REAL
electronic signature (see ``base.py``), not a placeholder waiting for a vendor.

**There is deliberately no DocuSign module here.** Writing an OAuth + envelope client
that nobody has ever run against a DocuSign account would be a file that looks like an
integration and is not one — the exact thing the honesty rule forbids, and worse than an
empty seam because it would read as done. When a buyer's procurement actually requires
a third-party witness, that is the moment to add ``docusign.py``, with credentials to
test it against. The seam is here so that day costs one file and no schema change:
`signature.token_fingerprint` and `certified_version` already carry what an envelope
callback would need to reconcile.
"""

from __future__ import annotations

import os

from .base import SignatureProvider
from .inhouse import InHouseSignatureProvider

PROVIDER_ENV = "CHORDENTIAL_SIGNATURE_PROVIDER"


def get_signature_provider() -> SignatureProvider:
    choice = os.environ.get(PROVIDER_ENV, "inhouse").strip().lower()
    if choice in ("", "inhouse", "null"):
        return InHouseSignatureProvider()
    # An unknown name must not silently fall back to signing things ourselves under a
    # configuration that asked for someone else. Failing loudly at boot is the only
    # safe direction for a signature.
    raise RuntimeError(
        f"{PROVIDER_ENV}={choice!r} is not an available signature provider. "
        "Only 'inhouse' is implemented; see signing_providers/__init__.py for why."
    )


__all__ = ["SignatureProvider", "InHouseSignatureProvider", "get_signature_provider"]
