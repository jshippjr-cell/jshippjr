"""Signature provider seam.

The signing engine (:mod:`chordential_oia.signing`) never imports a vendor SDK. Signing
goes through a :class:`SignatureProvider` selected at runtime by env, exactly as
payments go through ``payments/`` and mail through ``mailer.py``.

**The default provider is not a stub.** ``InHouseSignatureProvider`` produces a real,
legally-formed electronic signature: intent, consent recorded verbatim, attribution,
association with the document by SHA-256 digest, and retention in an append-only table.
Under ESIGN / UETA that is a valid electronic signature without any third party.

What a vendor (DocuSign and the like) adds is a NEUTRAL WITNESS and a procurement
checkbox — not validity. Some buyers' legal teams require one; that is a real
requirement and this seam is where it plugs in, one file, when a deal needs it.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class SignatureProvider(Protocol):
    """Minimal contract every signature backend implements."""

    #: Stable provider name ("inhouse", "docusign", …).
    name: str

    #: Whether signing happens on OUR page (in-house) or the signer is sent away to
    #: a vendor's. The routes need to know which, because the second cannot return a
    #: completed signature synchronously.
    remote: bool

    def request_signature(self, *, project_id: int, doc_kind: str,
                          document_text: str, signer_name: str,
                          signer_email: str) -> Optional[str]:
        """Start a signing ceremony. In-house returns None (the signer is already
        here); a remote provider returns a URL to send them to."""
        ...

    def completed(self, payload: dict) -> dict:
        """Interpret a provider callback into the fields `signing.build_signature`
        needs. Returns ``{}`` when the callback is not a completed signing."""
        ...
