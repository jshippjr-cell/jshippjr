"""The composer's half of the chain of title, as a document they can sign.

Reported live: *"Where do I find the composer agreement in the talent section?"* — and
the answer was that there wasn't one. `talent.agreement_executed_at` recorded that an
agreement existed *somewhere else*, and `agreement_ref` was free text for where the paper
lived. The assignment gate (ADR-0024) turned on a checkbox an operator ticked about a
document the system had never seen.

That is a weak spot in the one thing this business sells. The Clearance Certificate
warrants to a buyer that the work is *"100% original & cleared: no samples, no
third-party masters, nothing to clear but ours"* — and the only thing that can make that
true is the composer having warranted it first. A certificate whose backing is a tickbox
is a certificate backed by a memory of a conversation.

So the composer signs the same way the client does (ADR-0059/0065): one deterministic
text, a SHA-256 of exactly what they read, a drawn mark if they want one, and a
countersignature from the studio. Signing IS the gate — `agreement_executed_at` is
stamped by the signature rather than by a human asserting it happened.

**Every term here is existing policy, not invention.** The fee shares, the demo fee and
the publishing split come from :mod:`chordential_oia.compensation` (ADR-0061); the rights
grant is the mirror image of what `capabilities` already promises a client; the cue-sheet
undertaking is what `delivery` already files. If a term in this document and a number in
the engine ever disagree, the engine is right and this file is a bug — which is why the
figures are read from `compensation` rather than typed out here.

This is the studio's standing terms in plain language. It is not legal advice, and it has
not been through counsel; that review is the operator's to commission, and nothing here
pretends otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import compensation

# The consent shown above the signature line, and part of the signed text. It lives here
# rather than in a template for the same reason the client's does: it enters the digest,
# so a change to it is a change every existing signature can detect.
ACCEPTANCE_TEXT = (
    "I have read this agreement, I intend my signature below to bind me to it, and I "
    "agree to sign it electronically."
)

# What signing does NOT do. A composer reading "agreement" reasonably assumes it commits
# them to a job; it does not, and saying so is cheaper than the conversation where they
# find out.
ACCEPTANCE_LIMITS = (
    "This is a standing agreement, not a booking. It commits you to no work and "
    "guarantees you none. Each engagement is offered and accepted separately, with its "
    "own scope and fee, and this document sets the terms that apply when you accept one."
)


@dataclass
class ComposerAgreement:
    """The standing terms between the studio and one writer."""
    composer: str
    studio: str = "Chordential"
    house_publisher: str = compensation.HOUSE_PUBLISHER
    # Read from policy, never typed twice — see the module docstring.
    share_pct: float = compensation.COMPOSER_SHARE * 100.0
    share_with_session_pct: float = compensation.COMPOSER_SHARE_WITH_SESSION * 100.0
    demo_fee: float = compensation.DEMO_FEE
    publisher_to_writers_pct: float = compensation.PUBLISHER_SPLIT_TO_WRITERS * 100.0
    version: str = "1.0"
    notes: List[str] = field(default_factory=list)

    def signable_text(self) -> str:
        """The agreement as the plain text a signature binds to (ADR-0059).

        The DOCUMENT, not a rendering of it. No date is included: it is stamped at signing
        and stored beside the digest, and a document whose text changed because a day
        passed would report every signature as superseded by morning.
        """
        rows: List[str] = [
            "COMPOSER AGREEMENT",
            f"Between: {self.studio} (the studio)",
            f"And: {self.composer} (the writer)",
            f"Version: {self.version}",
            "",
            "1. WHAT THIS IS",
            "A standing agreement setting the terms that apply whenever the writer "
            "accepts an engagement from the studio. It commits neither side to any "
            "particular piece of work.",
            "",
            "2. THE WORK",
            "For each engagement the studio states the scope, the delivery dates and the "
            "fee in writing before the writer accepts. The writer composes and delivers "
            "original music to that scope, including the stems and versions the "
            "engagement names.",
            "Revisions within the rounds stated for that engagement are part of the fee. "
            "Work beyond them is scoped and paid separately, never assumed.",
            "",
            "3. WHAT THE WRITER IS PAID",
            f"A share of NET CREATIVE REVENUE for the engagement: {self.share_pct:.0f}%, "
            f"rising to {self.share_with_session_pct:.0f}% where the writer also "
            f"orchestrates or produces the recording session.",
            "Net creative revenue is the fee the client pays for the engagement, less "
            "money that passes through the studio to third parties — players, studio "
            "hire and per-engagement licences. It is not a share of gross: booking an "
            "orchestra is not a fact about the writer's work.",
            f"A demo submitted at the studio's request that does not win the work is paid "
            f"a flat ${self.demo_fee:,.0f}.",
            "The studio pays the writer within 30 days of the client settling the "
            "invoice the work belongs to, and tells the writer when that happens.",
            "",
            "4. RIGHTS IN THE RECORDING",
            "The writer assigns the master recording of the delivered work to the studio, "
            "which licenses or assigns it onward to the client under the engagement's "
            "terms. This is what lets the studio warrant a clean chain of title to a "
            "buyer, and it is the reason clause 6 matters.",
            "",
            "5. PUBLISHING",
            "The writer keeps 100% of the writer's share of the composition. Nothing in "
            "this agreement takes any part of it.",
            f"The publisher's share is held by {self.house_publisher} and split "
            f"{self.publisher_to_writers_pct:.0f}/"
            f"{100.0 - self.publisher_to_writers_pct:.0f} with the writers of the work.",
            "The studio registers the work and files the cue sheet, and the writer's "
            "splits appear on it. A share is only ever filed to an entity that can "
            "actually collect it — a name in a publisher column that is not registered "
            "at a PRO is an unclaimed royalty, not a favour.",
            "",
            "6. WHAT THE WRITER WARRANTS",
            "The work is the writer's own and original. It contains no samples, no "
            "third-party recordings, no interpolations and no library material — nothing "
            "requiring anyone else's clearance.",
            "The writer has the right to grant what this agreement grants, and the work "
            "does not knowingly infringe anyone.",
            "Where the writer wants to use anything they did not write, they say so "
            "BEFORE delivering it, and it is cleared in writing or it is not used.",
            "This clause is what the studio's clearance certificate to the client stands "
            "on. It is the one term here that cannot be waived quietly.",
            "",
            "7. CREDIT",
            "The writer is credited as composer on cue sheets and on any credit list the "
            "client publishes, and the studio asks for that credit as a matter of course.",
            "",
            "8. CONFIDENTIALITY",
            "Briefs, unreleased work, client names and fees stay private until the client "
            "makes them public. The writer may describe the work privately to secure "
            "other engagements once it has been released.",
            "",
            "9. ENDING IT",
            "Either side may end this standing agreement in writing at any time. "
            "Engagements already accepted are completed and paid under these terms, and "
            "clauses 4, 5, 6 and 8 survive for work already delivered.",
            "",
            "ACCEPTANCE",
            ACCEPTANCE_TEXT,
            ACCEPTANCE_LIMITS,
        ]
        if self.notes:
            rows += ["", "AGREED VARIATIONS"] + [f"  - {n}" for n in self.notes]
        return "\n".join(rows)


def build_agreement(talent_row=None, *, notes: Optional[List[str]] = None
                    ) -> ComposerAgreement:
    """The standing agreement for one writer.

    ``talent_row`` is a talent DB row (or anything with a ``name``). Everything else comes
    from :mod:`compensation`, so the document and the payout ledger cannot drift.
    """
    name = ""
    if talent_row is not None:
        try:
            name = (talent_row["name"] or "").strip()
        except (TypeError, KeyError, IndexError):
            name = (getattr(talent_row, "name", "") or "").strip()
    return ComposerAgreement(composer=name or "the writer",
                             notes=[str(n).strip() for n in (notes or []) if str(n).strip()])
