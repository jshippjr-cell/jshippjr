"""The standing agreement for everyone who is paid for their work and does not author it.

Reported live (operator, 2026-08-20): *"do i need to build out agreements for the audio
engineers and editors for them to sign?"* — and the honest answer was worse than a gap.
``db.talent_assignment_blockers`` is **role-blind**: it refuses any assignment without
``agreement_executed_at``, and the only thing in the product that sets that is the
Composer Agreement. Measured on a mixer's own row, that meant putting in front of them a
document that names them "the writer" on 45 lines, conveys them a 30% publishing share,
and lands clause 6A — the duty to collect a release from everyone who *played* — on
someone who played nothing. A mixer signing it would be granted a share of a copyright
they have no claim to, under a warranty about a composition they did not write.

So this is the other standing agreement. It covers the roles
:data:`chordential_oia.compensation.WRITER_ROLE_NAMES` deliberately excludes — the policy
already ratified that *"a mixer, an editor and a project manager are paid for their work
and are not authors of it"*, and this is that sentence as a document.

**What changes from the Composer Agreement, and why:**

- **No publishing, and it says so out loud.** Not silence — a positive clause stating
  that this agreement grants no share of the composition, and naming the one thing to do
  if the contractor believes they authored something (say so before delivering; it is
  settled as authorship or it is not used). Silence on publishing is how a mixer with a
  genuine writing contribution ends up unclaimed on a cue sheet.
- **A fee, not a share of net creative revenue.** The share exists because a writer's
  income follows a work that keeps earning. A mix does not earn separately; it is bought
  once. The fee is stated in writing before acceptance, computed from the contractor's
  own rate, and the estimate holds — the same protection the writer has in clause 3A.
- **They assign what they MAKE, which is a derivative.** A mix, a master, a cutdown and a
  vertical are new fixations of someone else's composition. The grant covers those and
  the session files behind them, and it is careful never to purport to grant the
  underlying work, because the contractor does not own it and a grant of something the
  grantor does not hold pollutes a chain of title rather than completing one.
- **The chain is a clause.** ADR-0075 says the mixer works from the composer's approved
  stems and the editor works from the mixer's approved master. That is a promise the
  studio makes to a client about what was delivered, so it belongs in the document the
  person doing it signed — not only in the software that routes the files.
- **The AI warranty is inverted for this role.** A writer warrants they generated no
  audio. A contractor's exposure is the opposite: the tools of their trade are now
  full of separation, de-noising and assistive mastering, all of which are legitimate.
  What is not legitimate is *generating* material — a replacement instrument, an extended
  tail, an invented stem — and that is what clause 6B here forbids, while permitting the
  processing chain explicitly so nobody has to guess.

**Every shared term is imported, not restated.** The acceptance window, the kill fee, the
payment backstop, the liability cap, the governing law and forum all come from
:mod:`composer_agreement`. Two agreements with two copies of a 120-day backstop is one
agreement with a 120-day backstop and another with whatever it drifted to.

Like the Composer Agreement, this is the studio's standing terms in plain language. It is
not legal advice and has not been through retained counsel — that review is the
operator's to commission, and this file is what to hand them alongside
``docs/composer-agreement-review.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .composer_agreement import (
    ACCEPTANCE_WINDOW_DAYS, INVOICE_WITHIN_DAYS, KILL_FEE_BEFORE_DELIVERY,
    LIABILITY_FEE_MULTIPLE, LIABILITY_FLOOR, PAYMENT_BACKSTOP_DAYS,
    forum, governing_law,
)

#: The crafts this agreement covers, as the document names them. Prose, but kept here
#: rather than inline so the roles the routing layer recognises and the roles the
#: contract claims to cover cannot drift apart.
COVERED_CRAFTS = (
    "mixing and mastering",
    "music editing — cutdowns, verticals, conforms and versioning",
    "sound design",
    "music supervision and clearance research",
)

#: Default loudness targets, by medium. Industry standards, not house invention:
#: ATSC A/85 for US broadcast, EBU R128 for European, and the ~-14 LUFS most streaming
#: platforms normalise to. They are DEFAULTS — the engagement names the target, and this
#: table is what applies when it does not. Held as data so a correction is one edit.
LOUDNESS_TARGETS = {
    "US broadcast": "-24 LKFS ±2 (ATSC A/85), true peak -2 dBTP",
    "European broadcast": "-23 LUFS ±1 (EBU R128), true peak -1 dBTP",
    "Streaming and online video": "-14 LUFS integrated, true peak -1 dBTP",
    "Cinema": "as the engagement states; no default is assumed",
}

#: The delivery floor for anything printed under this agreement. Mirrors clause 2A of the
#: Composer Agreement, because a mix delivered at a different sample rate to the stems it
#: came from is a conform problem nobody discovers until the edit.
DELIVERY_FORMAT = "48 kHz / 24-bit WAV"

ACCEPTANCE_TEXT = (
    "I have read this agreement, I intend my signature below to bind me to it, and I "
    "agree to sign it electronically."
)

ACCEPTANCE_LIMITS = (
    "This is a standing agreement, not a booking. It commits you to no work and "
    "guarantees you none. Each engagement is offered and accepted separately, with its "
    "own scope and fee, and this document sets the terms that apply when you accept one."
)


@dataclass
class ServiceAgreement:
    """The standing terms between the studio and one contractor who is not a writer."""
    contractor: str
    studio: str = "Chordential"
    crafts: tuple = COVERED_CRAFTS
    law: str = ""
    court: str = ""
    version: str = "1.0"
    notes: List[str] = field(default_factory=list)

    def signable_text(self) -> str:
        """The agreement as the plain text a signature binds to (ADR-0059).

        The DOCUMENT, not a rendering of it. No date, for the same reason the Composer
        Agreement carries none: it is stamped at signing and stored beside the digest,
        and a document whose text changed because a day passed would report every
        signature as superseded by morning.
        """
        cap = (f"the greater of ${LIABILITY_FLOOR:,.0f} and "
               f"{LIABILITY_FEE_MULTIPLE} times the fees the studio has paid the "
               f"contractor for that engagement")
        loudness = "; ".join(f"{k} — {v}" for k, v in LOUDNESS_TARGETS.items())
        rows: List[str] = [
            "SERVICE AGREEMENT",
            f"Between: {self.studio} (the studio)",
            f"And: {self.contractor} (the contractor)",
            f"Version: {self.version}",
            "",
            "1. WHAT THIS IS",
            "A standing agreement setting the terms that apply whenever the contractor "
            "accepts an engagement from the studio. It commits neither side to any "
            "particular piece of work.",
            "It covers work on music the contractor did not write: "
            + "; ".join(self.crafts) + ".",
            "It is NOT the studio's Composer Agreement. If the contractor is asked to "
            "write, co-write, arrange or orchestrate original music, that work is done "
            "under the Composer Agreement instead, which they sign separately. Nobody "
            "works under both documents on the same contribution.",
            "An engagement is accepted when the contractor accepts it in the studio's "
            "system. That record is the record of what was agreed and when.",
            "",
            "2. THE WORK",
            "For each engagement the studio states the scope, the source material, the "
            "delivery dates and the fee in writing before the contractor accepts.",
            "Revisions within the rounds stated for that engagement are part of the fee. "
            "Work beyond them is scoped and paid separately, never assumed. A change to "
            "the picture, the voice-over or the composition after work has started is a "
            "new scope, not a revision.",
            "",
            "2A. WHERE THE WORK COMES FROM",
            "Each stage of production starts from the APPROVED output of the stage before "
            "it, and from nothing else.",
            "A mix is made from the composer's approved stems. An edit, cutdown, vertical "
            "or conform is made from the mix engineer's approved master — never from the "
            "composer's stems, never from an earlier mix, and never from a bounce taken "
            "off a review link.",
            "The contractor does not re-balance, re-EQ, re-time or otherwise revise the "
            "previous stage's work unless the engagement asks them to. If the material "
            "they were given cannot carry the job, they say so before starting: that is "
            "a scope conversation the studio can have, and a silent fix is one it cannot "
            "explain to a client or to the person whose work was changed.",
            "",
            "2B. DELIVERED, AND ACCEPTED",
            f"Delivery means the files the engagement lists, in the formats it names — by "
            f"default {DELIVERY_FORMAT} — uploaded to the studio's delivery system by the "
            f"date stated, named as the engagement specifies.",
            "Where the engagement names a medium, the contractor delivers to that "
            f"medium's loudness target. Defaults, applied when the engagement is silent: "
            f"{loudness}. The contractor states the measured integrated loudness and true "
            f"peak of what they delivered.",
            "Where an engagement calls for alternate mixes — instrumental, a television "
            "mix carrying music and effects without dialogue, a version ducked under "
            "voice-over, or stems — each is printed from the SAME session and session "
            "state as the approved main mix, so that they conform to it exactly.",
            f"The studio has {ACCEPTANCE_WINDOW_DAYS} working days from delivery to "
            f"accept, or to say in writing what is wrong. If it says what is wrong, the "
            f"contractor has {ACCEPTANCE_WINDOW_DAYS} working days to fix it, within the "
            f"revision rounds the engagement names. Silence for "
            f"{ACCEPTANCE_WINDOW_DAYS} working days is acceptance.",
            "Delivery dates are tied to air dates and cannot slip quietly. If the "
            "contractor cannot make one, they say so as soon as they know: early is a "
            "problem the studio can solve, late is one it cannot.",
            "",
            "2C. IF THE JOB STOPS",
            f"If an accepted engagement is cancelled, shelved or withdrawn before "
            f"delivery, the contractor is paid {KILL_FEE_BEFORE_DELIVERY:.0%} of the fee "
            f"estimated at acceptance. After delivery, 100%. If the studio replaces the "
            f"contractor for any reason other than failure to deliver, the same applies.",
            "If the contractor withdraws or fails to deliver, nothing is due for that "
            "engagement and no rights pass under clause 4.",
            "",
            "3. WHAT THE CONTRACTOR IS PAID",
            "A fee for each engagement, stated in writing before the contractor accepts "
            "it and computed from the contractor's rate then in force — hourly, daily or "
            "per project, as recorded with the studio — against the scope of that "
            "engagement.",
            "The fee is for the work. It is not a share of what the client pays, and this "
            "agreement gives the contractor no interest in the licence fee, in renewals, "
            "or in any later payment the client makes to widen what it may do with the "
            "music. Clause 5 says why, and what to do if the contractor thinks it should "
            "be otherwise on a particular job.",
            "",
            "3A. THE ESTIMATE HOLDS",
            "The estimated fee is stated in writing at acceptance, together with the "
            "scope it was computed from. If the studio expands that scope, the fee rises "
            "with it. The fee is not reduced below the estimate without the contractor's "
            "written agreement — a discount the studio chose to give a client is not a "
            "fact about the contractor's work.",
            "",
            "3B. WHEN, AND HOW TO CHECK IT",
            f"The studio invoices the client within {INVOICE_WITHIN_DAYS} working days of "
            f"the client accepting delivery.",
            f"The studio pays the contractor within 30 days of the client settling that "
            f"invoice, and in any event within {PAYMENT_BACKSTOP_DAYS} days of the client "
            f"accepting delivery, whether or not the client has paid. If the studio has "
            f"not invoiced within 30 days of acceptance, the contractor is paid as though "
            f"it had.",
            "With each payment the studio sends a statement showing the client and "
            "engagement, the scope, the rate applied and the resulting fee. Nothing is "
            "deducted from the contractor's fee — not the studio's time, overhead, "
            "software, insurance, commission or travel.",
            "The contractor invoices the studio, or is paid against the studio's own "
            "statement where they prefer; either way the statement is the record.",
            "",
            "4. RIGHTS IN WHAT THE CONTRACTOR MAKES",
            "The contractor assigns to the studio, absolutely and for the full term of "
            "copyright including all renewals, extensions and reversions, all right, "
            "title and interest in everything they create under an engagement — the "
            "mixes, masters, edits, cutdowns, verticals, conforms, alternates, sound "
            "design elements and stems they deliver, together with the session files, "
            "edit decision lists, plug-in settings and project files behind them — "
            "throughout the world, in all media now known or later invented.",
            "This grant covers the contractor's own contribution and nothing else. It "
            "does not purport to grant the underlying composition or any earlier "
            "recording: those come to the studio from the writer, under the Composer "
            "Agreement. A grant of something the person granting it does not hold is "
            "worth nothing, and putting one in a chain of title makes the chain worse "
            "rather than longer.",
            "Because this is a standing agreement, the assignment takes effect on each "
            "piece of work the moment it is created, without anything further needing to "
            "be signed. The contractor will still sign any confirmatory document the "
            "studio reasonably asks for.",
            "",
            "4A. EDITS",
            "The work will be cut down, re-edited, layered with dialogue and sound "
            "design, and used against pictures the contractor has not seen. The "
            "contractor agrees to that and, so far as the law allows, waives their moral "
            "rights in the work — including the right to be identified and the right to "
            "object to derogatory treatment — in favour of the studio, its clients, and "
            "anyone they license. This waiver is about editing, not about credit: "
            "clause 7 stands.",
            "",
            "4B. THE CONTRACTOR'S REEL",
            "Once the client has released the work publicly, the contractor may use the "
            "finished track and up to 60 seconds of the finished spot in their own "
            "showreel, portfolio site and social accounts, and may say what they did on "
            "it. Not for sale, not for licensing to anyone else, and not before release.",
            "",
            "5. NO PUBLISHING, AND THE ONE EXCEPTION",
            "This agreement conveys no share of the composition: no writer's share, no "
            "publisher's share, and no interest of any kind in the publishing. Mixing, "
            "editing, mastering, conforming and sound design are craft on someone "
            "else's work; they are paid for as work and do not make the person doing "
            "them an author of the music.",
            "Nothing is being taken away here either. The contractor has no writer's "
            "share on this work to keep, because they did not write it — and if that is "
            "not true of a particular job, the next paragraph is the one that matters.",
            "The exception is real and it is the contractor's to raise. If, on a "
            "particular engagement, the contractor is asked for or ends up contributing "
            "original musical material — a written part, a melodic or harmonic idea, a "
            "topline, an arrangement — they say so BEFORE delivering it. The studio then "
            "either settles it as authorship, in writing and on the cue sheet, under the "
            "Composer Agreement, or the material is not used.",
            "Raising this is never a breach of this agreement and never a reason not to "
            "book someone again. An unclaimed writer on a cue sheet is a defect in the "
            "studio's chain of title, and the person best placed to catch it is the one "
            "who made the contribution.",
            "",
            "6. WHAT THE CONTRACTOR WARRANTS",
            "The contractor adds no material of their own that they do not have the "
            "right to add: no sample of anyone else's recording, no loop, construction "
            "kit or pre-composed phrase from any source (including royalty-free ones "
            "such as Splice), and no production-library element.",
            "Licensed plug-ins, virtual instruments, sample libraries and sound-effect "
            "libraries are fine and expected. The contractor confirms they hold a current "
            "licence for every one they used; that the licence permits use in a "
            "commissioned commercial work; and — because these engagements deliver stems "
            "— that it permits delivery of stems in which that element may be heard on "
            "its own. Where a licence does not permit that, the contractor says so before "
            "delivering, and the element is replaced.",
            "The contractor has the right to grant what clause 4 grants, and their "
            "contribution does not knowingly infringe any third party's copyright, trade "
            "mark, moral rights, performers' rights, rights of publicity or other rights.",
            "Where the contractor wants to use anything they did not make, they say so "
            "BEFORE delivering it, and it is cleared in writing or it is not used. "
            "Telling the studio honestly is never itself a breach of this agreement.",
            "This clause is part of what the studio's clearance certificate to the client "
            "stands on. No waiver of it is effective unless in writing and signed by an "
            "officer of the studio.",
            "",
            "6A. ANYONE THE CONTRACTOR BRINGS IN",
            "The contractor does not subcontract an engagement without the studio's "
            "written agreement. Where the studio agrees, the contractor names each "
            "person to the studio before delivery and gets them to sign the studio's "
            "contributor release — an assistant engineer, a second, a stem editor, or "
            "anyone else who touches the files.",
            "If anyone PERFORMS on the work at the contractor's request — a re-sung line, "
            "a replacement part, a played element — the studio is told before delivery "
            "and that person signs the contributor release too. Paid or unpaid, stranger "
            "or friend, in the room or over the internet.",
            "No one is engaged under a union or collective agreement — AFM, SAG-AFTRA, "
            "the Musicians' Union or any other — without the studio's prior written "
            "agreement. The contractor confirms on each delivery that no engagement was "
            "made under one.",
            "",
            "6B. NOTHING IN THE DELIVERY IS GENERATED",
            "The contractor warrants that they have not generated any musical material "
            "with an artificial-intelligence system and placed it in the delivered files "
            "— no generated instrument, part, phrase, extended tail, invented stem, "
            "sound-effect or replacement performance, whether or not it was edited, "
            "processed or re-recorded over afterwards.",
            "The tools of the craft are permitted and expected, and are named here so "
            "nobody has to guess: source separation and stem extraction from the "
            "material the studio supplied, de-noising and de-reverberation, spectral "
            "repair, pitch correction, time alignment and stretching, assistive or "
            "reference-matched mastering, loudness measurement and conform tools. On "
            "delivery the contractor lists which of these were used.",
            "The line is between PROCESSING what a human made and GENERATING what nobody "
            "did. Material generated by an AI system is not owned by anybody under US "
            "copyright law, so it cannot be assigned, cannot be cleared, and cannot be "
            "certified to a client. A breach of this clause is a breach of the whole "
            "agreement.",
            "",
            "6C. NOT TWICE",
            "What the contractor makes under an engagement is made for that engagement "
            "and is not delivered, licensed, re-used or re-released for anyone else. "
            "This includes the session files and any stems or elements created for it.",
            "Beyond that, the contractor is free to work for anyone, in any genre, on "
            "anything else. This agreement claims no exclusivity over the contractor's "
            "time and never will.",
            "",
            "7. CREDIT",
            "The studio credits the contractor by role on the delivery documentation it "
            "produces, every time. That one is in the studio's hands, and it is a "
            "promise.",
            "The studio also asks the client to credit the contractor on any credit list "
            "the client publishes, and puts that request in writing on every engagement. "
            "What a client publishes is the client's decision, so this is a promise to "
            "ask, not a promise that it happens. A client's failure to credit is not a "
            "breach by the studio, and the studio tells the contractor if it is refused.",
            "",
            "8. CONFIDENTIALITY",
            "Briefs, unreleased work, client names, fees and the identity of the other "
            "people on a job stay private until the client makes them public. Clause 4B "
            "says what the contractor may show once it is out.",
            "",
            "9. ENDING IT",
            "Either side may end this standing agreement in writing at any time. "
            "Engagements already accepted are completed and paid under these terms.",
            "Clauses 3, 3A, 3B, 4, 4A, 4B, 5, 6, 6A, 6B, 6C, 8, 10, 11 and 12 survive "
            "for work already delivered.",
            "",
            "10. IF THE WARRANTY TURNS OUT TO BE WRONG",
            "If a claim is made against the studio or its client because clause 6, 6A or "
            "6B was not true, the contractor will cover the studio's reasonable, "
            "documented losses and legal costs arising from it, and will help the studio "
            "deal with the claim — answering questions, producing session files, and "
            "telling the truth about how the work was made — at no charge and for as long "
            "as it takes.",
            f"The contractor's total liability under this clause for any one engagement "
            f"is capped at {cap}. The cap does not apply where the contractor knew the "
            f"warranty was untrue, or gave a dishonest answer to a direct question.",
            "The contractor keeps the session files, edit lists and delivered masters for "
            "each engagement for seven years and produces them on request. They are the "
            "evidence of how the work was made, and in a real dispute they are worth more "
            "than the warranty is.",
            "",
            "11. LAW, AND ARGUMENTS",
            f"This agreement is governed by the law of {self.law}, and both sides submit "
            f"to the courts of {self.court}. Either side may still go to any court to "
            f"stop a breach of clause 6 or to protect the rights granted in clause 4.",
            "Before either side starts proceedings, they will spend 30 days trying to "
            "settle it — in writing first, then on a call.",
            "",
            "12. THE REST",
            "The contractor is an independent contractor, not an employee, and is "
            "responsible for their own taxes. They provide a W-9 or W-8BEN before the "
            "first payment. Nothing here creates employment, partnership or agency.",
            "The contractor uses their own equipment and rooms, sets their own hours "
            "within the delivery dates, and is free to work for others throughout.",
            "Notices are given by email to the addresses on the signature page and take "
            "effect when sent.",
            "If any part of this agreement is unenforceable, the rest still stands.",
            "This agreement, the engagement documents and any agreed variations are the "
            "whole of what is agreed. Where an agreed variation conflicts with a clause "
            "above, the variation wins.",
            "The studio may transfer this agreement to a company that takes over its "
            "business. The contractor may not transfer it.",
            "The version of this agreement the contractor has signed applies to every "
            "engagement accepted while it is in force. A new version applies only to "
            "engagements accepted after the contractor signs it.",
        ]
        if self.notes:
            rows += ["", "AGREED VARIATIONS"] + [f"  - {n}" for n in self.notes]
        rows += ["", "ACCEPTANCE", ACCEPTANCE_TEXT, ACCEPTANCE_LIMITS]
        return "\n".join(rows)


def build_agreement(talent_row=None, *, notes: Optional[List[str]] = None,
                    law: Optional[str] = None,
                    court: Optional[str] = None) -> ServiceAgreement:
    """The standing agreement for one contractor.

    ``talent_row`` is a talent DB row (or anything with a ``name``). The law and forum
    come from the same place the Composer Agreement reads them, so the two documents
    cannot end up naming different courts.
    """
    name = ""
    if talent_row is not None:
        try:
            name = (talent_row["name"] or "").strip()
        except (TypeError, KeyError, IndexError):
            name = (getattr(talent_row, "name", "") or "").strip()
    return ServiceAgreement(
        contractor=name or "the contractor",
        law=(law if law is not None else governing_law()),
        court=(court if court is not None else forum()),
        notes=[str(n).strip() for n in (notes or []) if str(n).strip()],
    )


def is_signable(agreement: Optional[ServiceAgreement] = None) -> bool:
    """May this be put in front of a contractor to sign? Same rule as the Composer
    Agreement: a contract with no stated forum must not collect a signature."""
    law = (agreement.law if agreement is not None else governing_law())
    return bool((law or "").strip())


def blocked_reason(agreement: Optional[ServiceAgreement] = None) -> str:
    """Why it cannot be signed yet, for a surface to render. "" when it can."""
    from .composer_agreement import GOVERNING_LAW_ENV
    if is_signable(agreement):
        return ""
    return (f"No governing law is set, so this agreement is not ready to sign. Set "
            f"{GOVERNING_LAW_ENV} to the law and courts that will settle any dispute.")
