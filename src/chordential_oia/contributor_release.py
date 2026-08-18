"""The release everyone who is not the composer has to sign.

Clause 6A of the Composer Agreement obliges a writer to get a release signed by anyone
who performs on, sings on, programs, produces, engineers or co-writes a delivered work —
*"paid or unpaid, stranger or friend, in the room or over the internet"*. A council
review then checked whether that release existed anywhere in the codebase and found zero
matches outside the agreement text. So the studio was asking composers to collect a
document nobody had written, which is worse than not asking: it reads as diligence and
delivers none.

**This is the gap most likely to actually void a Clearance Certificate**, and it needs no
bad faith to happen. A composer books a violinist for two hours, or a friend sings a
topline, and a rights-holder now exists that Chordential has never heard of and holds no
grant from. `delivery._contributors` builds the certificate's chain of title from
*assignments in the database* — operator records — not from anything anyone signed.

In the UK this is sharper still: performers' rights under CDPA 1988 Part II are a
**separate property right**, and the composer has no power to assign them on the
performer's behalf however comprehensively they assign their own.

So the release is short, plain, and does exactly four things: assign the performance,
warrant it is theirs and human-made, waive moral rights so the recording can be edited
the way advertising edits things, and confirm no union agreement applies. It is
deliberately not a contract about money — payment is between the composer and the player,
and pretending otherwise would make the studio a party to an engagement it never made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import composer_agreement

# Roles a contributor can hold. Data, not a free-text box: "who else played" is a
# question with a bounded set of answers, and a typed role is what lets the clearance
# certificate report a chain of title rather than a list of names.
ROLES = (
    "Performer", "Vocalist", "Programmer", "Producer", "Engineer", "Co-writer",
    "Arranger", "Orchestrator", "Other",
)

# Roles that AUTHOR the work rather than perform on it. They need the composition
# handled as well as the recording, so the release says so explicitly for them.
WRITER_ROLES = frozenset({"Co-writer", "Arranger", "Orchestrator"})

ACCEPTANCE_TEXT = (
    "I have read this release, I intend my signature below to bind me to it, and I agree "
    "to sign it electronically."
)

ACCEPTANCE_LIMITS = (
    "This release is about the recording, not about your fee. Whatever you agreed to be "
    "paid is between you and the person who booked you, and signing this does not change "
    "it or waive it."
)


@dataclass
class ContributorRelease:
    """One person's release for one piece of work."""
    contributor: str
    role: str
    work: str                      # what they played on, in plain words
    booked_by: str = ""            # the composer who engaged them
    studio: str = "Chordential"
    law: str = ""
    court: str = ""
    version: str = "1.0"
    notes: List[str] = field(default_factory=list)

    @property
    def is_writer(self) -> bool:
        return self.role in WRITER_ROLES

    def signable_text(self) -> str:
        """The release as the plain text a signature binds to (ADR-0059).

        Short on purpose. A session player asked to sign four pages on their phone
        between takes signs without reading, and a release signed without reading is the
        one a dispute unpicks first.
        """
        rows: List[str] = [
            "CONTRIBUTOR RELEASE",
            f"Contributor: {self.contributor}",
            f"Role: {self.role}",
            f"Work: {self.work}",
            f"For: {self.studio}",
        ]
        if self.booked_by:
            rows.append(f"Booked by: {self.booked_by}")
        rows += [
            "",
            "1. WHAT THIS IS",
            f"You performed on, or contributed to, a piece of music {self.studio} is "
            f"delivering to a client. This release confirms that {self.studio} can use "
            f"that recording, and that nothing in it needs anyone else's permission.",
            "",
            "2. THE RECORDING",
            f"You assign to {self.studio}, for the full term of copyright and throughout "
            f"the world, all rights in your performance and in the recording of it, in "
            f"all media now known or later invented. {self.studio} may use, edit, "
            f"licence and sub-licence it as part of the work and any version of it.",
        ]
        if self.is_writer:
            rows += [
                f"Because your role was {self.role.lower()}, this also covers whatever "
                f"you contributed to the composition itself — the writing, not only the "
                f"performance. If you believe you should be credited as a writer with a "
                f"share, say so now rather than signing: that is a conversation to have "
                f"before the work is delivered, and it is a fair one to raise.",
            ]
        rows += [
            "",
            "3. WHAT YOU CONFIRM",
            "The performance is your own. You are free to give what this release gives, "
            "and you have not given it to anyone else.",
            "You did not use, quote or sample anyone else's recording or composition in "
            "it. If you did, say so before signing — telling us is never a problem, and "
            "finding out afterwards is.",
            "Your contribution was performed by you, a human being, and not generated by "
            "an artificial-intelligence music system. Ordinary studio tools that process "
            "a real performance — tuning, timing, noise removal — are fine and expected.",
            "",
            "4. UNION",
            "You were not engaged under a union or collective agreement — AFM, "
            "SAG-AFTRA, the Musicians' Union or any other — and no scale, pension, health "
            "or re-use obligation arises from your work on this recording. If you think "
            "one does, stop and tell us before signing.",
            "",
            "5. EDITS AND CREDIT",
            "Advertising music gets cut down, re-edited, layered under dialogue and used "
            "against pictures nobody showed you. You agree to that and, so far as the law "
            "allows, waive your moral rights in the recording — including the right to be "
            "identified and the right to object to how it is treated.",
            f"{self.studio} will name you on the cue sheet it files for the work.",
            "",
            "6. YOUR FEE",
            ACCEPTANCE_LIMITS,
            "",
            "7. LAW",
            f"This release is governed by the law of {self.law}, and the courts of "
            f"{self.court} deal with any dispute about it.",
        ]
        if self.notes:
            rows += ["", "AGREED VARIATIONS"] + [f"  - {n}" for n in self.notes]
        rows += ["", "ACCEPTANCE", ACCEPTANCE_TEXT]
        return "\n".join(rows)


def build_release(row=None, *, contributor: str = "", role: str = "",
                  work: str = "", booked_by: str = "",
                  notes: Optional[List[str]] = None,
                  law: Optional[str] = None,
                  court: Optional[str] = None) -> ContributorRelease:
    """The release for one contributor.

    ``row`` is a contributors DB row; the keyword arguments are the same fields for
    callers that do not have one yet (the preview an operator reads before sending).
    Law and forum come from the same place the Composer Agreement's do, so the two
    documents cannot end up governed by different states.
    """
    def _get(key, fallback):
        if row is None:
            return fallback
        try:
            return (row[key] or "").strip() or fallback
        except (TypeError, KeyError, IndexError):
            return fallback

    return ContributorRelease(
        contributor=_get("name", contributor) or "the contributor",
        role=_get("role", role) or "Performer",
        work=_get("work", work) or "an original music engagement",
        booked_by=_get("booked_by", booked_by),
        law=(law if law is not None else composer_agreement.governing_law()),
        court=(court if court is not None else composer_agreement.forum()),
        notes=[str(n).strip() for n in (notes or []) if str(n).strip()],
    )
