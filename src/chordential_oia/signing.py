"""Signatures that are bound to what was signed.

The Clearance Certificate is the single thing the market is asked to pay a premium
for, and until now nothing signed it. What the product called a sign-off was this::

    {"asset": "Master v3 FINAL", "approver": "Dana Whitfield, Aurora",
     "date": "2026-08-06"}

A free-text name and a date, appended to a JSON list. Reproduced on seeded data: a
client signs off, the operator then changes the licence from perpetual / worldwide /
exclusive to **one year, US only, non-exclusive**, and the approval record is
byte-for-byte identical. It survives a change to the very terms it was a sign-off on,
because it never referred to them. Nothing said WHAT was signed, and nothing but a
typed string said WHO signed it.

**A signature is a binding between a person, an intent, and an exact document.** That
is what this module makes. The legal shape is ESIGN / UETA, which is satisfied without
any third party: intent to sign, consent to transact electronically, attribution to a
person, association with the record, and retention. What a DocuSign buys on top is a
NEUTRAL witness and a procurement checkbox — not validity — so the seam for it is in
``signing_providers/`` and this module stands on its own.

The load-bearing idea is the DIGEST. The certificate is deterministic — the same
project data rebuilds the same document — so a signature stores the SHA-256 of the
exact rendered text, and verification rebuilds the document and compares. If a term
moved after signing, the system says so instead of showing a signature that no longer
means anything. A signature that cannot detect that is decoration.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# What can be signed. Kept as data so a new signable document is one line here rather
# than a new branch in the routes.
DOC_CLEARANCE = "clearance_certificate"
DOC_DELIVERY_ACCEPTANCE = "delivery_acceptance"
# The discovery summary, once it carries the commercial close. It is the FIRST thing a
# client signs and the only signable document that hangs off an opportunity rather than
# a project — a project does not exist yet when the proposal is accepted, and inventing
# one so the foreign key had somewhere to point would have made a deal look won on the
# strength of a document nobody had answered.
DOC_PROPOSAL = "discovery_proposal"
DOC_KINDS = (DOC_CLEARANCE, DOC_DELIVERY_ACCEPTANCE, DOC_PROPOSAL)

DOC_LABELS = {
    DOC_CLEARANCE: "Clearance Certificate",
    DOC_DELIVERY_ACCEPTANCE: "Delivery acceptance",
    DOC_PROPOSAL: "Discovery Summary & Proposal",
}

# The consent a signer is shown and agrees to. Recorded VERBATIM on the signature, not
# referenced by version: a consent you have to look up elsewhere to interpret is a
# consent you cannot produce in a dispute two years later.
CONSENT_TEXT = (
    "I agree to sign this document electronically. I have read it, I intend my typed "
    "name to be my signature, and I understand this electronic signature is legally "
    "binding to the same extent as a handwritten one."
)

# Verification outcomes.
VALID = "valid"                 # digest matches the document as it stands now
SUPERSEDED = "superseded"       # the document changed after it was signed
UNKNOWN = "unknown"             # nothing to compare against


def document_digest(text: str) -> str:
    """The SHA-256 of the exact document text, hex.

    Normalised only for line endings and trailing whitespace per line — a document
    that round-trips through a browser textarea must not read as tampered because a
    CRLF appeared. Nothing else is normalised: a changed word is a changed document.
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    canonical = "\n".join(line.rstrip() for line in lines).strip()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint(value: str) -> str:
    """A short, non-reversible marker for something we must not store in the clear.

    Used for the signer's IP: enough to show two signatures came from the same place,
    or to answer "was this signed from the same address as the approval", without the
    delivery database becoming a log of clients' home addresses.
    """
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


@dataclass
class Signature:
    """One signature, with everything needed to stand behind it.

    ``typed_name`` is the mark the signer made. ``signer_name`` / ``signer_email`` are
    who they said they were. They are kept apart on purpose: a mismatch between the
    two is a fact a dispute would care about, and collapsing them destroys it.
    """
    doc_kind: str
    doc_label: str
    project_id: int
    digest: str
    signer_name: str
    signer_email: str
    typed_name: str
    consent_text: str
    signed_at: str
    # Attribution. `actor` is the authenticated identity when there is one (an operator
    # signing in the console); a client signing through a token-gated portal has none,
    # which is why the token is fingerprinted instead.
    actor: str = ""
    # The subject, when it is not a project. A proposal is signed BEFORE any project
    # exists — that is the point of signing it — so it is stamped with the opportunity
    # instead and `project_id` stays 0. Exactly one of the two is set; `build_signature`
    # refuses a signature attached to neither, because a signature nothing can be found
    # by is a record that will never be produced in the dispute it was kept for.
    opportunity_id: int = 0
    ip_fingerprint: str = ""
    user_agent: str = ""
    token_fingerprint: str = ""
    # What the document was ABOUT at signing time — the version and a compact copy of
    # the terms. The digest proves the text; this makes a superseded signature legible
    # without having to reconstruct history.
    certified_version: str = ""
    terms_snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_signature(
    *,
    doc_kind: str,
    project_id: int = 0,
    opportunity_id: int = 0,
    document_text: str,
    signer_name: str,
    signer_email: str = "",
    typed_name: str,
    actor: str = "",
    ip: str = "",
    user_agent: str = "",
    token: str = "",
    certified_version: str = "",
    terms_snapshot: Optional[Dict[str, Any]] = None,
) -> Signature:
    """Make a signature record for a document as it stands right now.

    Raises on the two things that would produce a signature meaning nothing: an empty
    document (there is nothing to bind to) and an empty typed name (nobody signed).
    Refusing is the point — a signature row that quietly recorded neither would be
    worse than no signature at all, because it would LOOK like one.
    """
    if doc_kind not in DOC_KINDS:
        raise ValueError(f"not a signable document: {doc_kind}")
    if not (document_text or "").strip():
        raise ValueError("refusing to sign an empty document")
    if not (typed_name or "").strip():
        raise ValueError("refusing to record a signature with no typed name")
    if not int(project_id or 0) and not int(opportunity_id or 0):
        raise ValueError("refusing to sign a document attached to nothing")
    return Signature(
        doc_kind=doc_kind,
        doc_label=DOC_LABELS[doc_kind],
        project_id=int(project_id or 0),
        opportunity_id=int(opportunity_id or 0),
        digest=document_digest(document_text),
        signer_name=(signer_name or "").strip(),
        signer_email=(signer_email or "").strip().lower(),
        typed_name=(typed_name or "").strip(),
        consent_text=CONSENT_TEXT,
        signed_at=now_iso(),
        actor=(actor or "").strip(),
        ip_fingerprint=fingerprint(ip),
        user_agent=(user_agent or "")[:300],
        token_fingerprint=fingerprint(token),
        certified_version=(certified_version or "").strip(),
        terms_snapshot=dict(terms_snapshot or {}),
    )


def verify(stored_digest: str, current_text: Optional[str]) -> str:
    """Does this signature still describe the document?

    ``SUPERSEDED`` is not a failure to hide — it is the answer the old model could not
    give, and the one that matters. A client whose signed licence was edited afterwards
    is entitled to see that it was.
    """
    if not stored_digest:
        return UNKNOWN
    if current_text is None or not str(current_text).strip():
        return UNKNOWN
    return VALID if document_digest(current_text) == stored_digest else SUPERSEDED


def verdict_note(state: str, sig: Optional[dict] = None) -> str:
    """One honest sentence for a surface to render. No hedging in either direction."""
    who = (sig or {}).get("signer_name") or (sig or {}).get("typed_name") or "the signer"
    when = ((sig or {}).get("signed_at") or "")[:10]
    if state == VALID:
        return f"Signed by {who} on {when}. The document is unchanged since signing."
    if state == SUPERSEDED:
        return (f"Signed by {who} on {when}, but the document HAS CHANGED since. "
                f"This signature covers the earlier version, not the one shown.")
    return "Not signed."
