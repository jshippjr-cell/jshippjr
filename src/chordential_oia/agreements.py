"""Which standing agreement governs a creator — decided once, read everywhere.

The studio has two of them now: the Composer Agreement for people who author music, and
the Service Agreement for people who are paid for craft on music somebody else wrote
(:mod:`service_agreement` says why the second one had to exist). The moment there are
two, something has to choose, and if the portal chooses one way and the roster another
then a creator reads one document and signs the digest of a different one.

So the choice lives here and nowhere else — the same rule as the queue count
(ADR-0029), the price (ADR-0033) and the relationship stage (ADR-0057).

**The evidence is the creator's disciplines**, because a standing agreement is signed
before any engagement exists and there is no role to read yet. The split follows
:data:`chordential_oia.compensation.WRITER_ROLE_NAMES`, which already ratified that a
mixer, an editor and a project manager are paid for their work and are not authors of it.

**Any writing discipline wins.** Someone who both writes and mixes signs the Composer
Agreement: it is the broader instrument, it is the one that has to be true for the
Clearance Certificate, and it does not stop them being booked to mix. The reverse is not
true — a Service Agreement cannot carry a writer's publishing.

**No disciplines recorded is not a default, it is a gap.** The honesty rule (evidence or
nothing) applies to a contract as much as to a buyer's name: putting the wrong standing
agreement in front of someone because their profile was blank is exactly the defect this
module exists to fix. :func:`kind_for` returns ``UNKNOWN`` and the surfaces say so.
"""

from __future__ import annotations

from typing import Optional

from . import composer_agreement, service_agreement, signing
from .models import MusicDiscipline

#: The creator authors music. The Composer Agreement governs.
COMPOSER = "composer"
#: The creator works on music somebody else wrote. The Service Agreement governs.
SERVICE = "service"
#: Nothing on the record says which. Reported, never guessed.
UNKNOWN = "unknown"

#: Disciplines whose practitioners AUTHOR the work. Sonic branding is here because a
#: mnemonic is a composition — the shortest one the studio sells, but a composition.
WRITER_DISCIPLINES = frozenset({
    MusicDiscipline.COMPOSITION,
    MusicDiscipline.SONIC_BRANDING,
    MusicDiscipline.ARRANGEMENT,
})

#: Disciplines whose practitioners are paid for craft on someone else's work.
#:
#: SOUND_DESIGN sits here on the ratified policy in `compensation.WRITER_ROLE_NAMES`,
#: and it is the one with a real edge: a sound designer who invents original musical
#: material has authored something. Clause 5 of the Service Agreement is that edge,
#: handled the honest way — they raise it before delivering and it is settled as
#: authorship under the Composer Agreement or it is not used.
SERVICE_DISCIPLINES = frozenset({
    MusicDiscipline.MIXING,
    MusicDiscipline.SOUND_DESIGN,
    MusicDiscipline.SUPERVISION,
    MusicDiscipline.LICENSING,
})


def _disciplines(talent_row) -> list:
    """The disciplines on a talent row or Talent object, as enum members.

    Reads both shapes deliberately. The column holds a JSON list (``db`` writes it with
    ``json.dumps``), a ``Talent`` holds enum members, and a hand-built dict in a test may
    hold a plain name. Getting this wrong is invisible rather than loud: an unparsed
    column yields no disciplines, which reads as "no craft recorded" and quietly routes
    a real mixer into the no-agreement branch.
    """
    import json
    raw = None
    if talent_row is None:
        return []
    try:
        raw = talent_row["disciplines"]
    except (TypeError, KeyError, IndexError):
        raw = getattr(talent_row, "disciplines", None)
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            parts = list(decoded) if isinstance(decoded, list) else [decoded]
        except (ValueError, TypeError):
            parts = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        parts = list(raw)
    out = []
    for p in parts:
        if isinstance(p, MusicDiscipline):
            out.append(p)
            continue
        try:
            out.append(MusicDiscipline(str(p).strip()))
        except ValueError:
            continue                    # an unknown value is not evidence of anything
    return out


def kind_for(talent_row) -> str:
    """Which standing agreement governs this creator: COMPOSER, SERVICE or UNKNOWN."""
    ds = [d for d in _disciplines(talent_row) if d is not MusicDiscipline.NON_CRAFT]
    if any(d in WRITER_DISCIPLINES for d in ds):
        return COMPOSER
    if any(d in SERVICE_DISCIPLINES for d in ds):
        return SERVICE
    return UNKNOWN


def build_for(talent_row):
    """The right agreement object for this creator, or None when nothing says which."""
    kind = kind_for(talent_row)
    if kind == COMPOSER:
        return composer_agreement.build_agreement(talent_row)
    if kind == SERVICE:
        return service_agreement.build_agreement(talent_row)
    return None


def module_for(kind: str):
    """The module that owns a kind — so a caller reaches ACCEPTANCE_TEXT, is_signable
    and blocked_reason without a second branch of its own."""
    if kind == COMPOSER:
        return composer_agreement
    if kind == SERVICE:
        return service_agreement
    return None


#: What each kind is called, and what signature kind records it.
LABELS = {COMPOSER: "Composer Agreement", SERVICE: "Service Agreement"}
DOC_KINDS = {
    COMPOSER: signing.DOC_COMPOSER_AGREEMENT,
    SERVICE: signing.DOC_SERVICE_AGREEMENT,
}
COUNTERSIGN_KINDS = {
    COMPOSER: signing.DOC_COMPOSER_COUNTERSIGN,
    SERVICE: signing.DOC_SERVICE_COUNTERSIGN,
}

UNKNOWN_REASON = (
    "No craft is recorded for this creator, so the studio cannot tell which standing "
    "agreement applies — the Composer Agreement conveys a publishing share and is the "
    "wrong document for a mixer or an editor, and the Service Agreement carries no "
    "publishing and is the wrong document for a writer. Add at least one discipline to "
    "their profile and the right one appears here."
)


def doc_kind_for(talent_row) -> Optional[str]:
    """The ``signing.DOC_*`` kind this creator's standing agreement is recorded under."""
    return DOC_KINDS.get(kind_for(talent_row))


def label_for(talent_row) -> str:
    """What to call this creator's standing agreement on a surface."""
    return LABELS.get(kind_for(talent_row), "Standing agreement")
