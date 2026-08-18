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

import base64
import binascii
import hashlib
import json
import re
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
# Our half of the same document. The acceptance text the client signs says in as many
# words "we countersign, raise the deposit invoice, and work begins when that deposit
# clears" — so a countersignature has to be a real thing that exists, or the first
# sentence of our first binding document is one we cannot keep. It is a SEPARATE kind
# rather than a second row of the client's, so `latest_opportunity_signature` keeps
# answering "did the client sign?" without having to guess which row is whose.
DOC_PROPOSAL_COUNTERSIGN = "discovery_proposal_countersign"
# The supply side of the same business. The Clearance Certificate warrants to a BUYER
# that nothing in the work needs anyone else's clearance; the only thing that can make
# that true is the writer having warranted it first, in something they signed. Until
# this existed the certificate's backing was a checkbox an operator ticked about a
# document the system had never seen.
DOC_COMPOSER_AGREEMENT = "composer_agreement"
DOC_COMPOSER_COUNTERSIGN = "composer_agreement_countersign"
# Everyone who is not the composer. Clause 6A of the Composer Agreement obliges the
# writer to collect this, and for a while it obliged them to collect a document that did
# not exist anywhere — which reads as diligence and delivers none.
DOC_CONTRIBUTOR_RELEASE = "contributor_release"
DOC_KINDS = (DOC_CLEARANCE, DOC_DELIVERY_ACCEPTANCE, DOC_PROPOSAL,
             DOC_PROPOSAL_COUNTERSIGN, DOC_COMPOSER_AGREEMENT,
             DOC_COMPOSER_COUNTERSIGN, DOC_CONTRIBUTOR_RELEASE)

DOC_LABELS = {
    DOC_CLEARANCE: "Clearance Certificate",
    DOC_DELIVERY_ACCEPTANCE: "Delivery acceptance",
    DOC_PROPOSAL: "Discovery Summary & Proposal",
    DOC_PROPOSAL_COUNTERSIGN: "Discovery Summary & Proposal (countersigned)",
    DOC_COMPOSER_AGREEMENT: "Composer Agreement",
    DOC_COMPOSER_COUNTERSIGN: "Composer Agreement (countersigned)",
    DOC_CONTRIBUTOR_RELEASE: "Contributor Release",
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
    # …or a writer, for the supply-side agreement. Exactly one of the three subjects is
    # set; `build_signature` refuses a signature attached to none of them.
    talent_id: int = 0
    #: …or one session player, vocalist or co-writer, for their release.
    contributor_id: int = 0
    ip_fingerprint: str = ""
    user_agent: str = ""
    token_fingerprint: str = ""
    # What the document was ABOUT at signing time — the version and a compact copy of
    # the terms. The digest proves the text; this makes a superseded signature legible
    # without having to reconstruct history.
    certified_version: str = ""
    terms_snapshot: Dict[str, Any] = field(default_factory=dict)
    # The drawn mark, as a PNG data URL, when the signer made one. Deliberately NOT part
    # of the digest and never required: what makes an electronic signature binding is
    # intent, consent and attribution, all carried by the typed name and the recorded
    # consent. A drawing is a courtesy to the signer's expectations, so a browser where
    # the canvas fails must still be able to sign — and a mark treated as the evidence
    # would mean a signature that a rendering bug could erase.
    drawn_mark: str = ""

    def to_json(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_signature(
    *,
    doc_kind: str,
    project_id: int = 0,
    opportunity_id: int = 0,
    talent_id: int = 0,
    contributor_id: int = 0,
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
    drawn_mark: str = "",
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
    if not any((int(project_id or 0), int(opportunity_id or 0), int(talent_id or 0),
                int(contributor_id or 0))):
        raise ValueError("refusing to sign a document attached to nothing")
    return Signature(
        doc_kind=doc_kind,
        doc_label=DOC_LABELS[doc_kind],
        project_id=int(project_id or 0),
        opportunity_id=int(opportunity_id or 0),
        talent_id=int(talent_id or 0),
        contributor_id=int(contributor_id or 0),
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
        drawn_mark=clean_drawn_mark(drawn_mark),
    )


# A drawn signature big enough to be a signature and small enough not to be a payload.
# The pad emits roughly 8-40KB; the ceiling is generous for a slow hand on a big screen
# and still far below anything that could be smuggled through this field.
MAX_DRAWN_MARK = 400_000


def clean_drawn_mark(value: str) -> str:
    """Accept a PNG data URL from our own signature pad, or nothing.

    This value arrives from a token-gated public form and is rendered back into an
    ``<img src>``, so it is validated rather than trusted: anything that is not a plain
    base64 PNG data URL is DROPPED, not sanitised and not stored. A rejected mark costs
    the signer a drawing; an accepted `data:text/html` or `javascript:` would cost every
    later reader of the document. The signature itself never depends on this field, which
    is what makes dropping it the safe direction to fail.
    """
    mark = (value or "").strip()
    if not mark:
        return ""
    if len(mark) > MAX_DRAWN_MARK:
        return ""
    if not mark.startswith("data:image/png;base64,"):
        return ""
    payload = mark[len("data:image/png;base64,"):]
    if not payload or len(payload) % 4:
        return ""
    # Base64 only. A single character outside the alphabet means this was not produced by
    # `canvas.toDataURL`, and guessing at what it was instead is not our job.
    if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", payload):
        return ""
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        return ""
    # It must actually be a PNG, not a base64 blob wearing a PNG label.
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return ""
    return mark


def drawn_mark_png(mark: str) -> Optional[bytes]:
    """The stored drawn signature as real PNG bytes, or None.

    Re-validated on the way out, not trusted on the way in: `clean_drawn_mark` guards
    what is stored, and this guards what is handed to a mail client or written to a
    file. A row that predates the validator, or one edited in the database by hand, must
    not become an attachment nobody checked.
    """
    if not clean_drawn_mark(mark or ""):
        return None
    try:
        return base64.b64decode(mark.split(",", 1)[1], validate=True)
    except (ValueError, IndexError, binascii.Error):
        return None


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
