"""A small demo source with hand-built mock opportunities.

Lets the pipeline run end-to-end with no credentials and doubles as a test
fixture. For the full Chordential source taxonomy see
:mod:`chordential_oia.sources.tiered`.
"""

from __future__ import annotations

from datetime import date
from typing import List

from ..models import BuyerType, MusicRequirement, Opportunity
from .base import OpportunitySource


def _sample_opportunities() -> List[Opportunity]:
    return [
        # A-tier: agency, original, commercial, budget > $5k
        Opportunity(
            client="Acme Marketing (agency)",
            need="Campaign Music Package + Cutdowns",
            source="Sample / Demo",
            url="https://example.com/demo/acme-campaign",
            posted_date=date(2026, 6, 10),
            description="National brand campaign; original music, multiple cutdowns, fast.",
            buyer_type=BuyerType.AGENCY,
            commercial_campaign=True,
            video_production=True,
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=5_000,
            budget_max=15_000,
            location="Miami, FL",
            tags=["original", "cutdowns", "campaign"],
        ),
        # B-tier: production company, original, no budget edge for A
        Opportunity(
            client="Brightline Films",
            need="Original Score for Branded Documentary",
            source="Sample / Demo",
            url="https://example.com/demo/brightline-doc",
            posted_date=date(2026, 6, 8),
            description="Branded documentary needs an original score and supervision.",
            buyer_type=BuyerType.PRODUCTION_COMPANY,
            commercial_campaign=True,
            video_production=True,
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=20_000,
            budget_max=40_000,
            location="Remote",
            tags=["score", "supervision", "branded"],
        ),
        # C-tier: government media contract, music buried
        Opportunity(
            client="City of Lakeshore",
            need="RFP: Tourism Video Music",
            source="Sample / Demo",
            url="https://example.com/demo/lakeshore-rfp",
            posted_date=date(2026, 6, 1),
            description="Municipal tourism video; licensed background music line item.",
            buyer_type=BuyerType.GOVERNMENT,
            commercial_campaign=False,
            video_production=True,
            music_requirement=MusicRequirement.LICENSED,
            budget_min=8_000,
            budget_max=12_000,
            location="Tampa, FL",
            tags=["rfp", "licensed", "government"],
        ),
        # Watch: agency lead but no music component
        Opportunity(
            client="Pixel & Co (agency)",
            need="Social Video Editing Retainer",
            source="Sample / Demo",
            url="https://example.com/demo/pixel-social",
            posted_date=date(2026, 6, 13),
            description="Ongoing social video edits; no clear music need stated.",
            buyer_type=BuyerType.AGENCY,
            commercial_campaign=True,
            video_production=True,
            music_requirement=MusicRequirement.NONE,
            location="Remote",
            tags=["social", "editing"],
        ),
    ]


class SampleSource(OpportunitySource):
    """In-memory source of representative mock opportunities."""

    key = "sample"
    name = "Sample / Demo Source"
    category = "demo"
    source_tier = None

    def fetch(self, limit: int = 50) -> List[Opportunity]:
        return _sample_opportunities()[:limit]
