"""A sample source with realistic, hand-built mock opportunities.

This lets the whole pipeline run end-to-end with no credentials, and doubles
as a fixture for tests and a reference for what a real connector should
produce. The records span the source categories from the product brief.
"""

from __future__ import annotations

from datetime import date
from typing import List

from ..models import (
    AgencySize,
    CompetitionLevel,
    MusicRequirement,
    Opportunity,
    Relationship,
)
from .base import OpportunitySource


def _sample_opportunities() -> List[Opportunity]:
    return [
        Opportunity(
            client="Acme Marketing",
            need="Campaign Music Package",
            source="Creative Agency Partner Network",
            url="https://example.com/opps/acme-campaign",
            posted_date=date(2026, 6, 10),
            description=(
                "National brand campaign needs original music with multiple "
                "cutdowns (:06/:15/:30) on a fast turnaround."
            ),
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=5_000,
            budget_max=15_000,
            turnaround_days=14,
            location="USA",
            competition=CompetitionLevel.MEDIUM,
            agency_size=AgencySize.MID,
            relationship=Relationship.WARM_LEAD,
            tags=["original", "cutdowns", "campaign"],
        ),
        Opportunity(
            client="Brightline Films",
            need="Original Score for Documentary Series",
            source="Production Company Vendor Request",
            url="https://example.com/opps/brightline-doc",
            posted_date=date(2026, 6, 8),
            description=(
                "Six-episode documentary needs an original score and music "
                "supervision. Established director, prior collaboration."
            ),
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=20_000,
            budget_max=40_000,
            turnaround_days=30,
            location="Remote",
            competition=CompetitionLevel.LOW,
            agency_size=AgencySize.BOUTIQUE,
            relationship=Relationship.PAST_CLIENT,
            tags=["score", "supervision", "film"],
        ),
        Opportunity(
            client="City of Lakeshore",
            need="RFP: Tourism Video Music Licensing",
            source="Government RFP Database",
            url="https://example.com/opps/lakeshore-rfp",
            posted_date=date(2026, 6, 1),
            description=(
                "Municipal tourism board RFP for licensed background music "
                "for a video series. Formal procurement, many bidders."
            ),
            music_requirement=MusicRequirement.LICENSED,
            budget_min=8_000,
            budget_max=12_000,
            turnaround_days=60,
            location="Canada",
            competition=CompetitionLevel.HIGH,
            agency_size=AgencySize.ENTERPRISE,
            relationship=Relationship.NONE,
            tags=["rfp", "licensed", "government"],
        ),
        Opportunity(
            client="Northwind Events",
            need="Live Brand Activation Sound Design",
            source="Event Production Request",
            url="https://example.com/opps/northwind-activation",
            posted_date=date(2026, 6, 12),
            description=(
                "Experiential brand activation needs custom sound design and "
                "a signature audio identity for a 2-day event."
            ),
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=10_000,
            budget_max=18_000,
            turnaround_days=21,
            location="UK",
            competition=CompetitionLevel.MEDIUM,
            agency_size=AgencySize.MID,
            relationship=Relationship.NONE,
            tags=["sound-design", "event", "experiential"],
        ),
        Opportunity(
            client="Pixel & Co",
            need="Social Video Edits — needs background tracks",
            source="LinkedIn",
            url="https://example.com/opps/pixel-social",
            posted_date=date(2026, 6, 13),
            description=(
                "Small studio posting about ongoing social video work; music "
                "need is implied, budget unstated, tight weekly cadence."
            ),
            music_requirement=MusicRequirement.IMPLIED,
            budget_min=None,
            budget_max=None,
            turnaround_days=5,
            location="Remote",
            competition=CompetitionLevel.HIGH,
            agency_size=AgencySize.BOUTIQUE,
            relationship=Relationship.NONE,
            tags=["social", "implied"],
        ),
        Opportunity(
            client="Meridian Global Brands",
            need="Master Service Agreement — Marketing Production",
            source="Corporate Procurement Portal",
            url="https://example.com/opps/meridian-msa",
            posted_date=date(2026, 5, 28),
            description=(
                "Enterprise MSA covering broad marketing production. Music is "
                "a small slice; heavy procurement and incumbent vendors."
            ),
            music_requirement=MusicRequirement.IMPLIED,
            budget_min=2_000,
            budget_max=4_000,
            turnaround_days=90,
            location="Germany",
            remote_friendly=False,
            competition=CompetitionLevel.HIGH,
            agency_size=AgencySize.ENTERPRISE,
            relationship=Relationship.NONE,
            tags=["msa", "enterprise"],
        ),
        Opportunity(
            client="Solstice Records (Sync Team)",
            need="Music Supervision for Ad Campaign",
            source="Music Supervision Request",
            url="https://example.com/opps/solstice-sync",
            posted_date=date(2026, 6, 11),
            description=(
                "Looking for music supervision and original cues for a brand "
                "ad campaign with quick delivery and a couple of cutdowns."
            ),
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=12_000,
            budget_max=25_000,
            turnaround_days=18,
            location="USA",
            competition=CompetitionLevel.LOW,
            agency_size=AgencySize.MID,
            relationship=Relationship.WARM_LEAD,
            tags=["supervision", "original", "sync", "cutdowns"],
        ),
        Opportunity(
            client="Harbor Marketing Tenders Board",
            need="Marketing Tender — Jingle & Audio Branding",
            source="Marketing Tender",
            url="https://example.com/opps/harbor-tender",
            posted_date=date(2026, 6, 5),
            description=(
                "Open tender for a jingle and audio branding package. Mid "
                "budget, moderate field, standard timeline."
            ),
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=6_000,
            budget_max=9_000,
            turnaround_days=25,
            location="USA",
            competition=CompetitionLevel.MEDIUM,
            agency_size=AgencySize.MID,
            relationship=Relationship.NONE,
            tags=["tender", "jingle", "branding"],
        ),
    ]


class SampleSource(OpportunitySource):
    """In-memory source of representative mock opportunities."""

    key = "sample"
    name = "Sample / Demo Source"
    category = "demo"

    def fetch(self, limit: int = 50) -> List[Opportunity]:
        return _sample_opportunities()[:limit]
