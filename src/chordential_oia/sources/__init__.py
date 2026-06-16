"""Opportunity sources.

Every source implements :class:`base.OpportunitySource` and yields normalized
:class:`~chordential_oia.models.Opportunity` records. Real connectors
(SAM.gov, agency portals, LinkedIn, newsletters, etc.) plug in here later;
the engine and scorecards stay unchanged.
"""

from .base import OpportunitySource
from .sample import SampleSource
from .strategic import (
    AgencyCampaignSource,
    CreatorStreamerSource,
    IndieGameScoringSource,
)

# Registry of available sources by key. Live connectors get added here as
# they are built; the CLI discovers sources through this map. The strategic
# sources map to Chordential's launch roadmaps (see docs/market-research.md).
AVAILABLE_SOURCES = {
    "sample": SampleSource,
    "agency_campaign": AgencyCampaignSource,  # Roadmap A
    "indie_game": IndieGameScoringSource,  # Roadmap B
    "creator_streamer": CreatorStreamerSource,  # Roadmap C
}

__all__ = [
    "OpportunitySource",
    "SampleSource",
    "AgencyCampaignSource",
    "IndieGameScoringSource",
    "CreatorStreamerSource",
    "AVAILABLE_SOURCES",
]
