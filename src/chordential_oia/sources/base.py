"""Base interface every opportunity source implements.

The design goal is that adding a new source (a government RFP API, an agency
portal scraper, a LinkedIn search, a newsletter parser) means writing one
``fetch`` method that returns normalized :class:`Opportunity` objects. The
scoring engine and scorecard rendering never need to change.
"""

from __future__ import annotations

import abc
from typing import List

from ..models import Opportunity


class OpportunitySource(abc.ABC):
    """Abstract base class for an opportunity source.

    Implementations are responsible for talking to their backend (HTTP API,
    RSS feed, scraped HTML, CSV export, ...), handling auth, and mapping raw
    results onto :class:`Opportunity`. Mapping helpers like translating a
    free-text brief into a :class:`~chordential_oia.models.MusicRequirement`
    or estimating ``competition`` belong in the source so the rest of the
    pipeline stays source-agnostic.
    """

    #: Short, stable key used in config and the CLI (e.g. "sam_gov").
    key: str = "base"

    #: Human-readable name shown in reports.
    name: str = "Base Source"

    #: One of the categories from the product brief, for grouping/reporting.
    category: str = "general"

    @abc.abstractmethod
    def fetch(self, limit: int = 50) -> List[Opportunity]:
        """Return up to ``limit`` normalized opportunities from this source.

        Implementations should fail soft: log and skip individual malformed
        records rather than raising, so one bad row doesn't sink a run.
        """
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} key={self.key!r} category={self.category!r}>"
