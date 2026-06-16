"""Strategic lead channels mapped to Chordential's launch roadmaps.

Each source models one of the priority opportunity channels identified in the
June 2026 market research (see ``docs/market-research.md``):

- :class:`AgencyCampaignSource`   -> Roadmap A (Clearance-Certified campaign music)
- :class:`IndieGameScoringSource` -> Roadmap B (indie-game adaptive scoring)
- :class:`CreatorStreamerSource`  -> Roadmap C (brand-safe music for creators)

They ship with representative mock opportunities so the ranking engine can be
exercised against the lead types each roadmap targets. Replace ``fetch`` with a
live connector (job board scrape, agency CRM, itch.io / Discord, creator
outreach) without touching the scoring or reporting code.
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


class AgencyCampaignSource(OpportunitySource):
    """Roadmap A: fast-turnaround original campaign music with cutdowns.

    The beachhead lead type - ad agencies / production companies needing
    clearable, fully-owned music delivered fast with multiple cutdowns.
    """

    key = "agency_campaign"
    name = "Agency & Production Campaign Briefs"
    category = "advertising"

    def fetch(self, limit: int = 50) -> List[Opportunity]:
        opps = [
            Opportunity(
                client="Halcyon Creative (agency)",
                need="Original Music + 4 Cutdowns for Brand Social Campaign",
                source=self.name,
                url="https://example.com/leads/halcyon-social",
                posted_date=date(2026, 6, 14),
                description=(
                    "Agency needs an original hero track with :06/:15/:30 "
                    "cutdowns and stems for a paid-social campaign. Clearance "
                    "for cross-channel + paid spend is a hard requirement."
                ),
                music_requirement=MusicRequirement.ORIGINAL,
                budget_min=4_000,
                budget_max=8_000,
                turnaround_days=4,
                location="USA",
                competition=CompetitionLevel.MEDIUM,
                agency_size=AgencySize.MID,
                relationship=Relationship.WARM_LEAD,
                decision_maker="Producer / Creative Director",
                tags=["original", "cutdowns", "paid-social", "clearance"],
            ),
            Opportunity(
                client="Two Rivers Productions",
                need="Brand Anthem + Sonic Logo",
                source=self.name,
                url="https://example.com/leads/two-rivers-anthem",
                posted_date=date(2026, 6, 12),
                description=(
                    "Production company building a brand anthem and sonic logo "
                    "for a national client. Wants owned music with a clearance "
                    "certificate and indemnification."
                ),
                music_requirement=MusicRequirement.ORIGINAL,
                budget_min=12_000,
                budget_max=18_000,
                turnaround_days=18,
                location="USA",
                competition=CompetitionLevel.LOW,
                agency_size=AgencySize.MID,
                relationship=Relationship.NONE,
                decision_maker="Executive Producer",
                tags=["anthem", "sonic-logo", "clearance", "owned"],
            ),
        ]
        return opps[:limit]


class IndieGameScoringSource(OpportunitySource):
    """Roadmap B: original / adaptive scoring for indie game studios."""

    key = "indie_game"
    name = "Indie Game Scoring Requests"
    category = "games"

    def fetch(self, limit: int = 50) -> List[Opportunity]:
        opps = [
            Opportunity(
                client="Lanternlight Games",
                need="Adaptive Score + Wwise Integration for Cozy RPG",
                source=self.name,
                url="https://example.com/leads/lanternlight-score",
                posted_date=date(2026, 6, 13),
                description=(
                    "Small indie studio needs an original adaptive score with "
                    "Wwise integration and a perpetuity/buyout license they "
                    "can't get from a stock library."
                ),
                music_requirement=MusicRequirement.ORIGINAL,
                budget_min=8_000,
                budget_max=14_000,
                turnaround_days=40,
                location="Remote",
                competition=CompetitionLevel.LOW,
                agency_size=AgencySize.BOUTIQUE,
                relationship=Relationship.NONE,
                decision_maker="Game Director / Studio Lead",
                tags=["score", "adaptive", "wwise", "buyout", "indie"],
            ),
            Opportunity(
                client="Pixelforge (solo dev)",
                need="Theme Pack for Steam Next Fest demo",
                source=self.name,
                url="https://example.com/leads/pixelforge-theme",
                posted_date=date(2026, 6, 15),
                description=(
                    "Solo developer wants a main theme and a few loops before "
                    "Steam Next Fest. Tight budget, fast turnaround."
                ),
                music_requirement=MusicRequirement.ORIGINAL,
                budget_min=1_500,
                budget_max=3_000,
                turnaround_days=10,
                location="Remote",
                competition=CompetitionLevel.MEDIUM,
                agency_size=AgencySize.BOUTIQUE,
                relationship=Relationship.NONE,
                decision_maker="Solo Developer",
                tags=["theme", "loops", "indie", "steam"],
            ),
        ]
        return opps[:limit]


class CreatorStreamerSource(OpportunitySource):
    """Roadmap C: brand-safe music for creators and streamers."""

    key = "creator_streamer"
    name = "Creator & Streamer Brand-Safe Music"
    category = "creator"

    def fetch(self, limit: int = 50) -> List[Opportunity]:
        opps = [
            Opportunity(
                client="MidnightCast Network",
                need="Stream-Safe Music Pack + Content-ID Safelisting",
                source=self.name,
                url="https://example.com/leads/midnightcast-safe",
                posted_date=date(2026, 6, 14),
                description=(
                    "Streamer network wants a curated, human-made, DMCA-safe "
                    "music pack with Content-ID safelisting to avoid Twitch/"
                    "YouTube claims. Recurring need across channels."
                ),
                music_requirement=MusicRequirement.LICENSED,
                budget_min=2_500,
                budget_max=5_000,
                turnaround_days=21,
                location="Remote",
                competition=CompetitionLevel.MEDIUM,
                agency_size=AgencySize.BOUTIQUE,
                relationship=Relationship.WARM_LEAD,
                decision_maker="Network Operations Lead",
                tags=["stream-safe", "content-id", "recurring", "creator"],
            ),
        ]
        return opps[:limit]
