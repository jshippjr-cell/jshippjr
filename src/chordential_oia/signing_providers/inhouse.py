"""The default signature provider: we witness it ourselves.

Not a null object standing in for a real one. This IS the real one for every deal that
does not have a procurement rule demanding a third-party witness — the signer is already
authenticated to the document by the share token that got them to the page, the consent
is shown and recorded verbatim, the mark is their typed name, and the binding to the
document is a SHA-256 of its exact text.

The remote flag is False because nothing leaves the building: no redirect, no envelope,
no vendor outage between a client and the certificate they came to sign.
"""

from __future__ import annotations

from typing import Optional


class InHouseSignatureProvider:
    name = "inhouse"
    remote = False

    def request_signature(self, *, project_id: int, doc_kind: str,
                          document_text: str, signer_name: str,
                          signer_email: str) -> Optional[str]:
        """No ceremony to start — the signer is on the page with the document."""
        return None

    def completed(self, payload: dict) -> dict:
        """There is no callback: the POST that signs is the completion."""
        return dict(payload or {})
