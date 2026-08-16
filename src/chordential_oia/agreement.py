"""The discovery summary, as something a client can actually agree to.

Until now the summary and the proposal were two documents and two moments. The
client read "here is what we heard", typed their name into a box, and the system
recorded this::

    {"at": "2026-08-16T…", "by": "Nadia Okonjo", "comment": ""}

Then they waited, and a proposal arrived separately. Two problems, one of them
serious.

The small one is the wait. The summary is written at the exact moment the client
is most engaged — they have just spent half an hour telling us about the work —
and it asked them to confirm a paragraph and come back later for the number. The
number is the thing they need to take to whoever holds the budget.

The serious one is that the typed name meant nothing. It is the same free-text
name-and-date that :mod:`chordential_oia.signing` was written to replace on the
Clearance Certificate: it did not say WHAT was agreed, so the scope, the price and
the terms could all move afterwards and the record would be byte-for-byte
identical. A confirmation that survives a change to the thing it confirmed is not
a confirmation.

So the summary carries the commercial close, and the agreement to it is a real
signature bound to a digest (ADR-0059). This module builds the text that digest is
taken over. That text is **the document**: every operative term in a fixed order,
nothing that changes on its own, and — the part that matters most here — a section
naming what the numbers REST ON. An estimate is built on inferred scope
(ADR-0058); a client signing a band derived from an assumed runtime is entitled to
read the assumption next to the figure rather than discover it at invoice. A
proposal that hides what it assumed is the honesty rule broken in the one place it
is most expensive to break.

Nothing here decides anything. It assembles what the brief already shows into the
form a signature can bind to, and it refuses to offer a signature on a document
that has no price and no terms — because there is nothing there to agree to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# The sentence the client is agreeing to, shown immediately above the signature
# block. Kept here rather than in a template because it is part of the DOCUMENT:
# it goes into the signable text, so a change to it is a change a signature can
# detect. Copy that lives only in a template can be edited without any signature
# noticing, which is the whole failure mode this module exists to close.
ACCEPTANCE_TEXT = (
    "By signing below I confirm that this summary reflects our project accurately, "
    "and I accept the scope, fee and terms set out above as the basis for the work."
)

# What a signature on this document does NOT do. Stated on the document because a
# client who signs a proposal reasonably assumes the money moves; here it does not
# until an invoice is issued, and a surprise in that direction is the kind a buyer
# remembers.
ACCEPTANCE_LIMITS = (
    "Signing does not start a payment. We countersign, raise the deposit invoice, "
    "and work begins when that deposit clears."
)


@dataclass
class Agreement:
    """The operative content of the summary-as-proposal, in one place.

    Assembled from the document the client is already reading — not re-derived —
    so the text that is signed and the text that is displayed cannot drift apart.
    """
    client: str
    campaign: str
    understanding: str = ""
    scope: str = ""
    deliverables: List[str] = field(default_factory=list)
    timeline: str = ""
    revisions: str = ""
    price_low: Optional[int] = None
    price_high: Optional[int] = None
    deposit: str = ""
    completion: str = ""
    terms: List[str] = field(default_factory=list)
    rights: List[str] = field(default_factory=list)
    # ADR-0058: what the figures above rest on that the brief did not state.
    assumptions: List[str] = field(default_factory=list)

    @property
    def fee_line(self) -> str:
        """The fee as one sentence. A client who disclosed a single figure is not
        shown "$6,000 to $6,000", which reads as a band that happens to be flat."""
        if self.price_low is None:
            return ""
        if self.price_high is None or self.price_high == self.price_low:
            return f"${self.price_low:,}"
        return f"${self.price_low:,} to ${self.price_high:,}"

    def signable_text(self) -> str:
        """The agreement as the plain text a signature binds to (ADR-0059).

        This is the DOCUMENT, not a rendering of it. Two deliberate exclusions: the
        date (stamped at render, so a document whose digest changed overnight would
        report every signature as superseded by morning) and the client's own name
        for the signature block (the signer supplies that, and it is stored beside
        the digest rather than inside it). Everything a dispute could turn on is in
        here, so changing any of it after signing is exactly what ``signing.verify``
        must catch.
        """
        rows: List[str] = [
            "DISCOVERY SUMMARY & PROPOSAL",
            f"Client: {self.client}",
            f"Campaign: {self.campaign}",
        ]
        if self.understanding:
            rows += ["", "WHAT WE HEARD", self.understanding.strip()]
        rows += ["", "SCOPE"]
        rows.append(f"Scope: {self.scope or '·'}")
        rows.append(f"Timeline: {self.timeline or 'set at kickoff'}")
        rows.append(f"Revisions: {self.revisions or '·'}")
        if self.deliverables:
            rows.append(f"Deliverables ({len(self.deliverables)}):")
            rows += [f"  - {d}" for d in self.deliverables]
        rows += ["", "INVESTMENT",
                 f"Fee: {self.fee_line or '·'}",
                 f"Deposit: {self.deposit or '·'}",
                 f"Completion: {self.completion or '·'}"]
        if self.terms:
            rows += ["", "TERMS"] + [f"  - {t}" for t in self.terms]
        if self.rights:
            rows += ["", "RIGHTS"] + [f"  - {r}" for r in self.rights]
        # Always emitted, even when empty, and empty says so out loud. A silently
        # absent section reads as "nothing was assumed", which is a claim, and one
        # we are usually not entitled to make.
        rows += ["", "WHAT THIS RESTS ON"]
        rows += ([f"  - {a}" for a in self.assumptions]
                 or ["  - Nothing beyond what is written above."])
        rows += ["", "ACCEPTANCE", ACCEPTANCE_TEXT, ACCEPTANCE_LIMITS]
        return "\n".join(rows)


def _clean(items) -> List[str]:
    out: List[str] = []
    for raw in items or []:
        text = str(raw).strip()
        if text and text not in out:
            out.append(text)
    return out


def build_agreement(doc, opp=None, *, deposit_amount: Optional[float] = None) -> Agreement:
    """Assemble the agreement from the capabilities document the client is reading.

    ``doc`` is a :class:`~chordential_oia.capabilities.CapabilitiesDoc`. It is taken
    duck-typed on purpose: this module must not import ``capabilities``, because
    ``capabilities`` imports THIS one. The dependency runs one way — the document
    reaches for the agreement, never the reverse.
    """
    commercial = dict(getattr(doc, "commercial", None) or {})
    deliverables = [
        f"{d.asset} — {d.spec}" if getattr(d, "spec", "") else str(getattr(d, "asset", d))
        for d in (getattr(doc, "deliverables", None) or [])
    ]
    deposit = commercial.get("deposit") or ""
    # The stored proposal's deposit figure, when the project has been spun up and
    # there IS one, beats the prose sentence — the same rule the brief's Pay-deposit
    # button follows (ADR-0034). Two surfaces quoting different deposits on one page
    # is how a client stops believing either.
    if deposit_amount:
        deposit = f"${deposit_amount:,.0f} to begin, the balance on final approval."
    return Agreement(
        client=getattr(doc, "client", "") or (getattr(opp, "client", "") if opp else ""),
        campaign=getattr(doc, "need", "") or (getattr(opp, "need", "") if opp else ""),
        understanding=(getattr(doc, "understanding", "") or "").strip(),
        scope=commercial.get("scope") or "",
        deliverables=deliverables,
        timeline=commercial.get("timeline") or "",
        revisions=commercial.get("revisions") or "",
        price_low=getattr(doc, "price_low", None),
        price_high=getattr(doc, "price_high", None),
        deposit=deposit,
        completion=commercial.get("completion") or "",
        terms=_clean(getattr(doc, "terms", None)),
        rights=_clean(getattr(doc, "rights_summary", None)),
        assumptions=_clean(getattr(doc, "assumptions", None)),
    )


def is_signable(doc) -> bool:
    """May this document carry a signature block at all?

    A price and terms, or there is nothing to agree to. Offering a signature on a
    summary that quotes nothing would collect a commitment to an unnamed number —
    which is worth less than nothing, because it LOOKS like a commitment. This is
    the same refusal ``signing.build_signature`` makes about an empty document, made
    earlier, where it can be a missing button rather than an exception.
    """
    return bool(getattr(doc, "price_low", None)) and bool(getattr(doc, "terms", None))
