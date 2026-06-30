"""Talent domain model — the supply side's foundation.

A ``Talent`` is a music creator Chordential can staff onto won work. Talent are
matched on **profile and credits** (per the CEO's directive), and every creator
submits a **demo reel that Jon personally reviews** before they become matchable —
a deliberate human-in-the-loop quality gate, not audio AI.

Disciplines reuse :class:`MusicDiscipline` so supply and demand speak the same
language: an opportunity that needs ``COMPOSITION`` matches a composer directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .models import MusicDiscipline


class ReviewStatus(Enum):
    """Jon's demo-reel review state — the quality gate before matching."""

    PENDING = "Pending"   # reel submitted (or awaited), not yet reviewed
    APPROVED = "Approved"  # Jon reviewed the reel and approved the creator
    DECLINED = "Declined"  # reviewed and not a fit


class InviteStatus(Enum):
    """Recruiting funnel state for a creator."""

    PROSPECT = "Prospect"  # sourced, not yet invited into the app
    INVITED = "Invited"    # invitation sent
    JOINED = "Joined"      # accepted — active in the network


@dataclass
class Talent:
    name: str
    email: Optional[str] = None
    disciplines: List[MusicDiscipline] = field(default_factory=list)
    credits: str = ""
    location: Optional[str] = None
    demo_reel_url: Optional[str] = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    invite_status: InviteStatus = InviteStatus.PROSPECT
    notes: str = ""
    id: Optional[int] = None
    # Provenance: where this creator came from ("manual", "applicant", a source
    # key) and a link back to the profile/portfolio the record was built from.
    source: Optional[str] = None
    source_url: Optional[str] = None
    # Pay rate the founder sets per creator. When this talent is assigned to a
    # role on a project, this rate overrides the global role default in the
    # project proposal. ``rate_unit`` ∈ {hourly, day, project}.
    rate: Optional[float] = None
    rate_unit: str = "hourly"

    @property
    def discipline_labels(self) -> List[str]:
        return [d.label for d in self.disciplines]

    @property
    def source_label(self) -> str:
        """Human-readable origin badge ("Manual" when unset)."""
        return {
            "applicant": "Applied",
            "manual": "Manual",
            "sample": "Sourced",
            "demo": "Sourced",
            "crawl": "Sourced",
            "sourced": "Sourced",
            "paste": "Sourced",
            "referral": "Referral",
        }.get((self.source or "").lower(), (self.source or "Manual").title())

    #: Which roster channel a source value belongs to (for filtering/counts).
    _SOURCE_CHANNELS = {
        "applicant": "applied",
        "referral": "referral",
        "sample": "sourced", "demo": "sourced", "crawl": "sourced",
        "sourced": "sourced", "paste": "sourced",
        "manual": "manual", "": "manual",
    }

    @property
    def source_channel(self) -> str:
        """Coarse origin channel: applied | sourced | referral | manual.

        Groups the fine-grained ``source`` keys so the roster can filter/count by
        the way a creator entered the funnel (your #1 question: "where's my
        sourced channel?")."""
        return self._SOURCE_CHANNELS.get((self.source or "").lower(), "manual")

    @property
    def is_approved(self) -> bool:
        return self.review_status is ReviewStatus.APPROVED

    @property
    def matchable(self) -> bool:
        """Approved by Jon and has at least one discipline — ready to be matched."""
        return self.is_approved and bool(self.disciplines)


def profile_completeness(t: Talent) -> int:
    """0-100 signal of how complete a profile is (matching readiness)."""
    checks = [
        bool(t.name),
        bool(t.email),
        bool(t.disciplines),
        bool(t.credits.strip()),
        bool(t.demo_reel_url),
        bool(t.location),
    ]
    return round(sum(checks) / len(checks) * 100)
