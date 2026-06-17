"""Base interface every talent source implements (supply-side mirror of
:class:`chordential_oia.sources.base.OpportunitySource`).

Adding a new way to discover creators — a public applicant form, a portfolio
directory, an approved web-crawl target — means writing one ``fetch`` method that
returns normalized :class:`~chordential_oia.talent.Talent` objects. Matching,
the review gate, and the roster never need to change.

Every creator a source yields enters at ``ReviewStatus.PENDING`` /
``InviteStatus.PROSPECT`` so it lands in Jon's reel-review queue and is **not**
matchable until he approves it — the same human gate that governs manual talent.
"""

from __future__ import annotations

import abc
from typing import List

from ..talent import InviteStatus, ReviewStatus, Talent


class TalentSource(abc.ABC):
    """Abstract base class for a talent (supply-side) source.

    Implementations talk to their backend (an applicant form, an HTTP API, an
    approved crawl target) and map raw results onto :class:`Talent`. They must
    fail soft: skip an individual malformed record rather than raising, so one
    bad row doesn't sink a run.
    """

    #: Short, stable key used in config and the registry (e.g. "applicants").
    key: str = "base"

    #: Human-readable name shown in the roster / reports.
    name: str = "Base Talent Source"

    #: Grouping label for reporting (e.g. "inbound", "crawl", "demo").
    category: str = "general"

    @abc.abstractmethod
    def fetch(self, limit: int = 50) -> List[Talent]:
        """Return up to ``limit`` candidate creators as Pending/Prospect Talent."""
        raise NotImplementedError

    @staticmethod
    def _pending(**kwargs) -> Talent:
        """Build a Talent fixed at the review/invite gate entry state.

        Centralizes the contract so no source can accidentally yield a creator
        that is already approved/matchable — review is always Jon's call.
        """
        kwargs.pop("review_status", None)
        kwargs.pop("invite_status", None)
        return Talent(
            review_status=ReviewStatus.PENDING,
            invite_status=InviteStatus.PROSPECT,
            **kwargs,
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} key={self.key!r} category={self.category!r}>"
