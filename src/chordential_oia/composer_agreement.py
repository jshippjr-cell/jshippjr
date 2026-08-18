"""The composer's half of the chain of title, as a document they can sign.

Reported live: *"Where do I find the composer agreement in the talent section?"* — and
the answer was that there wasn't one. `talent.agreement_executed_at` recorded that an
agreement existed *somewhere else*. The assignment gate (ADR-0024) turned on a checkbox
about a document the system had never seen.

That is a weak spot in the one thing this business sells. The Clearance Certificate
warrants to a buyer that the work is *"100% original & cleared"* — and the only thing
that can make that true is the writer having warranted it first.

**v1.0 was reviewed by an entertainment-lawyer pass and it did not survive.** The
headline finding is worth keeping at the top of this file, because it is the kind of
mistake that reads as fine until it is expensive: *the agreement never granted the
composition.* Clause 4 assigned "the master recording"; clause 5 said the publisher's
share "is held by Chordential Music" — indicative mood, no verb of grant, nothing
transferred. Meanwhile `delivery.DEFAULT_LICENSE` sells every client a **perpetual sync
licence**, which is a licence of the *composition*. We were licensing a copyright we did
not own, under a certificate warranting clean title, while the writer stayed free to
license the same cue to a competitor. Four other clauses were missing entirely: no AI
warranty (against marketing that says "never AI-generated"), nothing capturing session
players and vocalists, no indemnity, no governing law.

**Every term is still existing policy, not invention.** The fee shares, the demo fee and
the publishing split come from :mod:`chordential_oia.compensation` (ADR-0061); the rights
grant is the mirror of what `capabilities` promises a client. Figures are READ from the
policy so the contract and the payout ledger cannot drift.

Three commercial choices were the operator's and are recorded here as theirs: the fee
base is the **creative fee** with a separate share of licence and renewal income (the
better houses' standard); payment has a **120-day backstop** whether or not the client
has paid; and the writer's indemnity is **capped** at the greater of $25,000 and 3× fees,
uncapped only for a knowing breach.

This is the studio's standing terms in plain language, and it is now structurally sound.
It is still not legal advice and has not been through retained counsel — that review is
the operator's to commission, and `docs/composer-agreement-review.md` is what to hand
them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from . import compensation

#: Where arguments get settled. There is no honest default — inventing a jurisdiction
#: for a contract someone signs is the same class of error as inventing a price. Unset,
#: the agreement is NOT SIGNABLE (see :func:`is_signable`), because a cross-border
#: perpetual copyright assignment with no stated law is a fight about which court before
#: it is a fight about anything else.
GOVERNING_LAW_ENV = "CHORDENTIAL_GOVERNING_LAW"

# Capped so a freelancer can actually bear it. An uncapped warranty against a few
# thousand dollars of fee is one an experienced composer strikes and a naive one signs
# without reading — neither is worth having. Uncapped only where they knew it was untrue.
LIABILITY_FLOOR = 25_000.0
LIABILITY_FEE_MULTIPLE = 3

# Paid whether or not the client has. Pay-when-paid with no backstop was the clearest
# below-market term in v1.0 and the one most likely to lose a good composer.
PAYMENT_BACKSTOP_DAYS = 120
INVOICE_WITHIN_DAYS = 10
ACCEPTANCE_WINDOW_DAYS = 5
KILL_FEE_BEFORE_DELIVERY = 0.50

ACCEPTANCE_TEXT = (
    "I have read this agreement, I intend my signature below to bind me to it, and I "
    "agree to sign it electronically."
)

ACCEPTANCE_LIMITS = (
    "This is a standing agreement, not a booking. It commits you to no work and "
    "guarantees you none. Each engagement is offered and accepted separately, with its "
    "own scope and fee, and this document sets the terms that apply when you accept one."
)


def governing_law() -> str:
    """The stated law and forum, or "" when the operator has not set one."""
    return (os.environ.get(GOVERNING_LAW_ENV) or "").strip()


@dataclass
class ComposerAgreement:
    """The standing terms between the studio and one writer."""
    composer: str
    studio: str = "Chordential"
    house_publisher: str = compensation.HOUSE_PUBLISHER
    share_pct: float = compensation.COMPOSER_SHARE * 100.0
    share_with_session_pct: float = compensation.COMPOSER_SHARE_WITH_SESSION * 100.0
    demo_fee: float = compensation.DEMO_FEE
    publisher_to_writers_pct: float = compensation.PUBLISHER_SPLIT_TO_WRITERS * 100.0
    law: str = ""
    version: str = "2.0"
    notes: List[str] = field(default_factory=list)

    def signable_text(self) -> str:
        """The agreement as the plain text a signature binds to (ADR-0059).

        The DOCUMENT, not a rendering of it. No date: it is stamped at signing and stored
        beside the digest, and a document whose text changed because a day passed would
        report every signature as superseded by morning.
        """
        share = f"{self.share_pct:.0f}%"
        share_session = f"{self.share_with_session_pct:.0f}%"
        writers_half = f"{self.publisher_to_writers_pct:.0f}"
        house_half = f"{100.0 - self.publisher_to_writers_pct:.0f}"
        cap = (f"the greater of ${LIABILITY_FLOOR:,.0f} and "
               f"{LIABILITY_FEE_MULTIPLE} times the fees the studio has paid the writer "
               f"for that engagement")
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
            "An engagement is accepted when the writer accepts it in the studio's "
            "system. That record is the record of what was agreed and when.",
            "",
            "2. THE WORK",
            "For each engagement the studio states the scope, the delivery dates and the "
            "fee in writing before the writer accepts. The writer composes and delivers "
            "original music to that scope, including the stems and versions the "
            "engagement names.",
            "Revisions within the rounds stated for that engagement are part of the fee. "
            "Work beyond them is scoped and paid separately, never assumed.",
            "",
            "2A. DELIVERED, AND ACCEPTED",
            "Delivery means the files the engagement lists, in the formats it names — by "
            "default 48 kHz / 24-bit WAV, a stereo master, the named stems printed from "
            "the same session and time-aligned to it, and a note of tempo and key — "
            "uploaded to the studio's delivery system by the date stated.",
            f"The studio has {ACCEPTANCE_WINDOW_DAYS} working days from delivery to "
            f"accept, or to say in writing what is wrong. If it says what is wrong, the "
            f"writer has {ACCEPTANCE_WINDOW_DAYS} working days to fix it, within the "
            f"revision rounds the engagement names. Silence for "
            f"{ACCEPTANCE_WINDOW_DAYS} working days is acceptance.",
            "Delivery dates are tied to air dates and cannot slip quietly. If the writer "
            "cannot make one, they say so as soon as they know: early is a problem the "
            "studio can solve, late is one it cannot.",
            "",
            "2B. IF THE JOB STOPS",
            f"If an accepted engagement is cancelled, shelved or withdrawn before "
            f"delivery, the writer is paid {KILL_FEE_BEFORE_DELIVERY:.0%} of the fee "
            f"estimated at acceptance. After delivery, 100%. If the studio replaces the "
            f"writer for any reason other than failure to deliver, the same applies.",
            "If the writer withdraws or fails to deliver, nothing is due for that "
            "engagement and no rights pass under clauses 4 or 5.",
            "",
            "3. WHAT THE WRITER IS PAID",
            f"A share of NET CREATIVE REVENUE for the engagement: {share}, rising to "
            f"{share_session} where the writer also orchestrates or produces the "
            f"recording session.",
            "Net creative revenue is the CREATIVE FEE the client pays for the engagement "
            "— the fee for writing, producing and delivering the music, as itemised on "
            "the client's proposal — less money that passes through the studio to "
            "unconnected third parties for that engagement. It does not include the "
            "licence fee the client pays for the right to use the music; that is dealt "
            "with in clause 3C.",
            "It is not a share of gross: booking an orchestra is not a fact about the "
            "writer's work.",
            f"A demo submitted at the studio's request that does not win the work is paid "
            f"a flat ${self.demo_fee:,.0f}.",
            "",
            "3A. THE ESTIMATE HOLDS",
            "The estimated fee is stated in writing at acceptance, together with the "
            "price and session cost it was computed from. If the price the client "
            "finally pays is higher, the writer's fee rises with it. If it is lower, the "
            "writer's fee is not reduced below the estimate without the writer's written "
            "agreement. A discount the studio chose to give is not a fact about the "
            "writer's work either.",
            "",
            "3B. WHEN, AND HOW TO CHECK IT",
            f"The studio invoices the client within {INVOICE_WITHIN_DAYS} working days of "
            f"the client accepting delivery, and tells the writer the invoice number and "
            f"the amount invoiced.",
            f"The studio pays the writer within 30 days of the client settling that "
            f"invoice, and in any event within {PAYMENT_BACKSTOP_DAYS} days of the client "
            f"accepting delivery, whether or not the client has paid. If the studio has "
            f"not invoiced within 30 days of acceptance, the writer is paid as though it "
            f"had.",
            "With each payment the studio sends a statement showing: the client and "
            "engagement; the creative fee invoiced; each amount deducted to reach net "
            "creative revenue and who it was paid to; the share applied; and the "
            "resulting fee.",
            "Deductions are limited to money actually paid to unconnected third parties "
            "for that engagement: session players and their pension and health "
            "contributions, studio and equipment hire, engineers engaged for the "
            "session, and licences bought for that engagement alone. Nothing else is "
            "deducted — not the studio's own time, overhead, software, insurance, "
            "commission, travel, or any payment to a person or company connected with "
            "the studio.",
            "Once in any 12 months, on 30 days' notice, the writer may have an accountant "
            "inspect the studio's records for the engagements they worked on. The writer "
            "pays for it, unless it shows the writer was underpaid by more than 5%, in "
            "which case the studio pays for it and for the shortfall. A statement is "
            "final 24 months after it is sent unless queried in writing before then.",
            "",
            "3C. IF THE CLIENT COMES BACK",
            "If the client later pays to extend the term, widen the territory, add "
            "media, take exclusivity, upgrade to a buyout, or otherwise expand what it "
            f"may do with the work, the writer is paid the same {share} share of the net "
            f"of that payment, on the same terms, for as long as the work earns. This "
            f"does not stop when this agreement ends.",
            "",
            "4. RIGHTS IN THE RECORDING",
            "The writer assigns to the studio, absolutely and for the full term of "
            "copyright including all renewals, extensions and reversions, all right, "
            "title and interest in the master recording of each delivered work, "
            "throughout the world, in all media now known or later invented — together "
            "with the stems, alternates, cutdowns, session files, MIDI and project files "
            "delivered or created for it.",
            "Because this is a standing agreement, the assignment takes effect on each "
            "work the moment it is created, without anything further needing to be "
            "signed. The writer will still sign any confirmatory document the studio "
            "reasonably asks for.",
            "This is what lets the studio warrant a clean chain of title to a buyer, and "
            "it is the reason clauses 6 to 6C matter.",
            "",
            "4A. EDITS",
            "The music will be cut down, re-edited, layered with dialogue and sound "
            "design, and used against pictures the writer has not seen. The writer "
            "agrees to that and, so far as the law allows, waives their moral rights in "
            "the work — including the right to be identified and the right to object to "
            "derogatory treatment — in favour of the studio, its clients, and anyone they "
            "license. This waiver is about editing, not about credit: clause 7 stands.",
            "The studio tells the writer the brand and the product category before they "
            "accept an engagement, so the decision about what the music is used for is "
            "made before the work, not after.",
            "",
            "4B. THE WRITER'S REEL",
            "Once the client has released the work publicly, the writer may use the "
            "finished track and up to 60 seconds of the finished spot in their own "
            "showreel, portfolio site and social accounts, and may say they wrote it. "
            "Not for sale, not for licensing to anyone else, and not before release.",
            "",
            "5. PUBLISHING",
            f"The writer assigns to {self.house_publisher} the whole of the copyright in "
            f"the composition — the publishing — for the life of copyright, throughout "
            f"the world, including the sole right to license it for synchronisation with "
            f"the client's advertising and for everything else the engagement grants.",
            "The writer keeps the writer's share of public performance income. That is "
            "the writer's half of performance royalties, which the PRO pays the writer "
            "direct. It is not the studio's to take, and this agreement does not take it.",
            f"{writers_half}% of the publisher's share belongs to the writers of the "
            f"work, and {house_half}% to the studio. Where the writer has a publishing "
            f"entity registered at a PRO, the writers' half is filed to it on the cue "
            f"sheet. Where the writer does not yet have one, the studio holds that half "
            f"FOR the writer, tells the writer in writing that it is doing so, and "
            f"either files it to the writer's entity or pays over what it has collected "
            f"on it within 30 days of the writer naming that entity. The studio does not "
            f"keep it by default and does not keep it by silence.",
            "A share is only ever filed to an entity that can actually collect it — a "
            "name in a publisher column that is not registered at a PRO is an unclaimed "
            "royalty, not a favour.",
            "The studio registers the work and files the cue sheet within 30 days of "
            "first broadcast, and sends the writer a copy of both.",
            "",
            "6. WHAT THE WRITER WARRANTS",
            "The work contains no sample of anyone else's recording, no interpolation of "
            "anyone else's composition, no loop, construction kit or pre-composed phrase "
            "from any source (including royalty-free ones such as Splice), and no "
            "production-library cue.",
            "Licensed virtual instruments and sample libraries are fine and expected. The "
            "writer confirms they hold a current licence for every one they used; that "
            "the licence permits use in a commissioned commercial work; and — because "
            "every engagement here delivers stems — that it permits delivery of stems in "
            "which that instrument may be heard on its own. Where a licence does not "
            "permit that, the writer says so before delivering, and the part is "
            "re-recorded or replaced.",
            "The writer has the right to grant what this agreement grants, and the work "
            "does not knowingly infringe any third party's copyright, trade mark, moral "
            "rights, performers' rights, rights of publicity or other rights.",
            "Where the writer wants to use anything they did not write, they say so "
            "BEFORE delivering it, and it is cleared in writing or it is not used. "
            "Telling the studio honestly is never itself a breach of this agreement.",
            "This clause is what the studio's clearance certificate to the client stands "
            "on. No waiver of it is effective unless in writing and signed by an officer "
            "of the studio.",
            "",
            "6A. EVERYONE ELSE WHO PLAYED",
            "If anyone other than the writer performs on, sings on, programs, produces, "
            "engineers or co-writes the work, the writer names them to the studio before "
            "delivery and gets each of them to sign the studio's contributor release "
            "before the recording is delivered. This applies to singers, session players, "
            "remote players, programmers and co-writers — paid or unpaid, stranger or "
            "friend, in the room or over the internet.",
            "No one is engaged under a union or collective agreement — AFM, SAG-AFTRA, "
            "the Musicians' Union or any other — without the studio's prior written "
            "agreement. The writer confirms on each delivery that no engagement was made "
            "under one.",
            "",
            "6B. THE MUSIC IS HUMAN-MADE",
            "The writer warrants that every note, part and recorded performance in the "
            "work was created by a human being. No part of the work was generated by an "
            "artificial-intelligence music system — including prompt-to-music services "
            "such as Suno, Udio and their successors — and no AI-generated audio, "
            "melody, chord progression, arrangement or stem is contained in the "
            "delivered files, whether or not it was edited, re-recorded over, or "
            "processed afterwards.",
            "Ordinary studio tools that process a human performance are permitted and "
            "expected: pitch correction, time alignment, de-noising, separation of the "
            "writer's own recording, AI-assisted mastering. On delivery the writer lists "
            "which of these were used.",
            "This is not a matter of taste. Music generated by an AI system is not owned "
            "by anybody under US copyright law, so it cannot be assigned, cannot be "
            "cleared, and cannot be certified to a client. A breach of this clause is a "
            "breach of the whole agreement.",
            "",
            "6C. NOT TWICE",
            "The work is written for this engagement and is not delivered, licensed, "
            "re-recorded or re-released for anyone else. For 12 months from first "
            "broadcast, the writer will not knowingly write a materially similar cue for "
            "a competing brand in the same product category.",
            "Beyond that, the writer is free to work for anyone, in any genre, on "
            "anything else. This agreement claims no exclusivity over the writer's time "
            "and never will.",
            "",
            "7. CREDIT",
            "The studio credits the writer as composer on the cue sheet it files, every "
            "time. That one is in the studio's hands, and it is a promise.",
            "The studio also asks the client to credit the writer on any credit list the "
            "client publishes, and puts that request in writing on every engagement. "
            "What a client publishes is the client's decision, so this is a promise to "
            "ask, not a promise that it happens. A client's failure to credit is not a "
            "breach by the studio, and the studio tells the writer if it is refused.",
            "",
            "8. CONFIDENTIALITY",
            "Briefs, unreleased work, client names and fees stay private until the client "
            "makes them public. Clause 4B says what the writer may show once it is out.",
            "",
            "9. ENDING IT",
            "Either side may end this standing agreement in writing at any time. "
            "Engagements already accepted are completed and paid under these terms.",
            "Clauses 3, 3A, 3B, 3C, 4, 4A, 4B, 6, 6A, 6B, 6C, 8, 10, 11 and 12 survive "
            "for work already delivered. Clause 5 survives for the life of copyright.",
            "",
            "10. IF THE WARRANTY TURNS OUT TO BE WRONG",
            "If a claim is made against the studio or its client because clause 6, 6A or "
            "6B was not true, the writer will cover the studio's reasonable, documented "
            "losses and legal costs arising from it, and will help the studio deal with "
            "the claim — answering questions, producing session files, and telling the "
            "truth about how the work was made — at no charge and for as long as it "
            "takes.",
            f"The writer's total liability under this clause for any one engagement is "
            f"capped at {cap}. The cap does not apply where the writer knew the warranty "
            f"was untrue, or gave a dishonest answer to a direct question.",
            "The writer keeps the project files, sketches and source stems for each "
            "engagement for seven years and produces them on request. They are the "
            "evidence that the work is original, and in a real dispute they are worth "
            "more than the warranty is.",
            "",
            "11. LAW, AND ARGUMENTS",
            f"This agreement is governed by the law of {self.law}, and both sides submit "
            f"to the courts of {self.law}. Either side may still go to any court to stop "
            f"a breach of clause 6 or to protect the rights granted in clauses 4 and 5.",
            "Before either side starts proceedings, they will spend 30 days trying to "
            "settle it — in writing first, then on a call.",
            "",
            "12. THE REST",
            "The writer is an independent contractor, not an employee, and is "
            "responsible for their own taxes. They provide a W-9 or W-8BEN before the "
            "first payment. Nothing here creates employment, partnership or agency.",
            "Notices are given by email to the addresses on the signature page and take "
            "effect when sent.",
            "If any part of this agreement is unenforceable, the rest still stands.",
            "This agreement, the engagement documents and any agreed variations are the "
            "whole of what is agreed. Where an agreed variation conflicts with a clause "
            "above, the variation wins.",
            "The studio may transfer this agreement to a company that takes over its "
            "business. The writer may not transfer it, and may not subcontract an "
            "engagement without the studio's written agreement.",
            "The version of this agreement the writer has signed applies to every "
            "engagement accepted while it is in force. A new version applies only to "
            "engagements accepted after the writer signs it.",
        ]
        if self.notes:
            rows += ["", "AGREED VARIATIONS"] + [f"  - {n}" for n in self.notes]
        rows += ["", "ACCEPTANCE", ACCEPTANCE_TEXT, ACCEPTANCE_LIMITS]
        return "\n".join(rows)


def build_agreement(talent_row=None, *, notes: Optional[List[str]] = None,
                    law: Optional[str] = None) -> ComposerAgreement:
    """The standing agreement for one writer.

    ``talent_row`` is a talent DB row (or anything with a ``name``). Everything else comes
    from :mod:`compensation` and the environment, so the document and the payout ledger
    cannot drift.
    """
    name = ""
    if talent_row is not None:
        try:
            name = (talent_row["name"] or "").strip()
        except (TypeError, KeyError, IndexError):
            name = (getattr(talent_row, "name", "") or "").strip()
    return ComposerAgreement(
        composer=name or "the writer",
        law=(law if law is not None else governing_law()),
        notes=[str(n).strip() for n in (notes or []) if str(n).strip()],
    )


def is_signable(agreement: Optional[ComposerAgreement] = None) -> bool:
    """May this be put in front of a writer to sign?

    Only with a governing law set. A cross-border perpetual copyright assignment with no
    stated law is a fight about which court before it is a fight about anything else, and
    there is no honest default to fall back on — inventing a jurisdiction for a document
    someone signs is the same class of error as inventing a price. So the document
    refuses rather than degrading, which is the rule `signing_providers` already follows.
    """
    law = (agreement.law if agreement is not None else governing_law())
    return bool((law or "").strip())


def blocked_reason(agreement: Optional[ComposerAgreement] = None) -> str:
    """Why it cannot be signed yet, for a surface to render. "" when it can."""
    if is_signable(agreement):
        return ""
    return (f"No governing law is set, so this agreement is not ready to sign. Set "
            f"{GOVERNING_LAW_ENV} (for example \"the State of Tennessee\" or \"England "
            f"and Wales\") to the law and courts that will settle any dispute.")
