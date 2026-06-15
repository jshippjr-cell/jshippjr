"""Opportunity sources.

Every source implements :class:`base.OpportunitySource` and yields normalized
:class:`~chordential_oia.models.Opportunity` records. Real connectors
(SAM.gov, agency portals, LinkedIn, newsletters, etc.) plug in here later;
the engine and scorecards stay unchanged.
"""

from .base import OpportunitySource
from .sample import SampleSource

# Registry of available sources by key. Live connectors get added here as
# they are built; the CLI discovers sources through this map.
AVAILABLE_SOURCES = {
    "sample": SampleSource,
}

__all__ = ["OpportunitySource", "SampleSource", "AVAILABLE_SOURCES"]
