"""Opportunity sources.

Every source implements :class:`base.OpportunitySource` and yields normalized
:class:`~chordential_oia.models.Opportunity` records. Real connectors plug in
here later; the engine and scorecards stay unchanged.

``AVAILABLE_SOURCES`` maps a source key to a zero-arg factory returning a
source instance. It includes a demo source plus Chordential's ten-source,
four-tier taxonomy (see :mod:`chordential_oia.sources.tiered`).
"""

from .base import OpportunitySource
from .sample import SampleSource
from .tiered import TIERED_SOURCES, TieredSource

# Demo source + the tiered taxonomy. Values are zero-arg callables.
AVAILABLE_SOURCES = {
    "sample": SampleSource,
    **TIERED_SOURCES,
}

__all__ = [
    "OpportunitySource",
    "SampleSource",
    "TieredSource",
    "TIERED_SOURCES",
    "AVAILABLE_SOURCES",
]
