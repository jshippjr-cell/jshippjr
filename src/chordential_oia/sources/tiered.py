"""Chordential's tiered RFP / opportunity source taxonomy.

Ten named sources across four tiers, each with the realistic *access method*
that a live connector would use (see ``docs/market-research.md`` for the
feasibility analysis):

  Tier 1 — Government / corporate RFP aggregators
      rfpdb        RFPDB                 RSS / saved-search feed   (auto)
      sam_gov      SAM.gov               Official free API        (auto)
      govwin       GovWin IQ             Paid API (license req.)  (manual/licensed)
  Tier 2 — Commercial / agency intelligence
      agency_spotter  Agency Spotter     Login-gated, ToS         (manual)
      adforum         AdForum            Subscription             (manual)
      campaign_us     Campaign US        Headline RSS             (auto, partial)
  Tier 3 — Film / TV / streaming production
      productionhub   ProductionHUB      Email-alert intake       (auto via alerts)
      staffmeup       Staff Me Up        Login-gated, ToS         (manual)
      mandy           Mandy Network      Email-alert intake       (auto via alerts)
  Tier 4 — Gaming / interactive
      hitmarker       Hitmarker          Email-alert intake       (auto via alerts)

Each ``fetch`` returns representative mock opportunities so the engine can be
exercised across A/B/C/Watch tiers. Swap ``fetch`` for the live connector
(API poll, RSS, or parsed email alert) without touching scoring/reporting.
"""

from __future__ import annotations

from datetime import date
from typing import List

from ..models import BuyerType, MusicRequirement, Opportunity
from .base import OpportunitySource


class TieredSource(OpportunitySource):
    """A configurable source carrying tier + access metadata and mock data."""

    def __init__(
        self,
        key: str,
        name: str,
        source_tier: int,
        category: str,
        access: str,
        opportunities: List[Opportunity],
    ) -> None:
        self.key = key
        self.name = name
        self.source_tier = source_tier
        self.category = category
        self.access = access  # "auto" | "auto via alerts" | "manual" | ...
        self._opportunities = opportunities

    def fetch(self, limit: int = 50) -> List[Opportunity]:
        # Stamp provenance the source knows about onto each record.
        for opp in self._opportunities:
            opp.source = self.name
            opp.source_tier = self.source_tier
        return self._opportunities[:limit]


# --------------------------------------------------------------------------- #
# Tier 1 — Government / corporate RFP aggregators (mostly C-tier output)
# --------------------------------------------------------------------------- #
_RFPDB = lambda: TieredSource(
    key="rfpdb",
    name="RFPDB",
    source_tier=1,
    category="government",
    access="auto",
    opportunities=[
        Opportunity(
            client="State University Tourism Board",
            need="RFP: Promotional Video Series with Background Music",
            url="https://example.com/rfpdb/univ-tourism",
            posted_date=date(2026, 6, 9),
            description=(
                "Public RFP for a promotional video series; licensed background "
                "music is one line item inside a larger media scope."
            ),
            buyer_type=BuyerType.GOVERNMENT,
            commercial_campaign=False,
            video_production=True,
            music_requirement=MusicRequirement.LICENSED,
            budget_min=8_000,
            budget_max=12_000,
            location="Tallahassee, FL",
        ),
    ],
)

_SAM_GOV = lambda: TieredSource(
    key="sam_gov",
    name="SAM.gov",
    source_tier=1,
    category="government",
    access="auto",
    opportunities=[
        Opportunity(
            client="Federal Agency (Public Affairs)",
            need="PSA Video Production — Original Music Component",
            url="https://example.com/sam/psa-production",
            posted_date=date(2026, 6, 4),
            description=(
                "Federal public-affairs PSA production. Original music is "
                "buried inside a broader video-production contract; teaming "
                "with a prime likely required."
            ),
            buyer_type=BuyerType.GOVERNMENT,
            commercial_campaign=False,
            video_production=True,
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=40_000,
            budget_max=90_000,
            location="Washington, DC",
        ),
    ],
)

_GOVWIN = lambda: TieredSource(
    key="govwin",
    name="GovWin IQ",
    source_tier=1,
    category="government",
    access="manual",  # paid platform; surfaced by a license holder
    opportunities=[
        Opportunity(
            client="County Communications Office",
            need="Recurring Creative Services IDIQ (incl. audio/music)",
            url="https://example.com/govwin/creative-idiq",
            posted_date=date(2026, 5, 30),
            description=(
                "Multi-year creative-services contract; music/audio is a small "
                "recurring task order within a large scope."
            ),
            buyer_type=BuyerType.GOVERNMENT,
            commercial_campaign=False,
            video_production=True,
            music_requirement=MusicRequirement.IMPLIED,
            location="Atlanta, GA",
        ),
    ],
)


# --------------------------------------------------------------------------- #
# Tier 2 — Commercial / agency intelligence (A/B-tier output)
# --------------------------------------------------------------------------- #
_AGENCY_SPOTTER = lambda: TieredSource(
    key="agency_spotter",
    name="Agency Spotter",
    source_tier=2,
    category="advertising",
    access="manual",
    opportunities=[
        Opportunity(
            client="Halcyon Creative (agency)",
            need="Original Campaign Music + Cutdowns for New CPG Account",
            url="https://example.com/agencyspotter/halcyon-cpg",
            posted_date=date(2026, 6, 14),
            description=(
                "Agency just won a national CPG account; needs original "
                "campaign music with :06/:15/:30 cutdowns and stems, fast."
            ),
            buyer_type=BuyerType.AGENCY,
            commercial_campaign=True,
            video_production=True,
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=6_000,
            budget_max=10_000,
            location="Miami, FL",
            tags=["original", "cutdowns", "campaign"],
        ),
    ],
)

_ADFORUM = lambda: TieredSource(
    key="adforum",
    name="AdForum",
    source_tier=2,
    category="advertising",
    access="manual",
    opportunities=[
        Opportunity(
            client="Brightside & Partners (agency)",
            need="Music for Brand Campaign in Active Pitch",
            url="https://example.com/adforum/brightside-pitch",
            posted_date=date(2026, 6, 11),
            description=(
                "Agency in an active brand-campaign pitch; original music "
                "likely needed if they win. Budget not yet disclosed."
            ),
            buyer_type=BuyerType.AGENCY,
            commercial_campaign=True,
            video_production=True,
            music_requirement=MusicRequirement.ORIGINAL,
            location="New York, NY",
            tags=["pitch", "campaign", "pre-production"],
        ),
    ],
)

_CAMPAIGN_US = lambda: TieredSource(
    key="campaign_us",
    name="Campaign US",
    source_tier=2,
    category="advertising",
    access="auto",  # headline RSS
    opportunities=[
        Opportunity(
            client="Meridian Beverage Co. (brand)",
            need="Sonic Branding + Anthem for National Launch",
            url="https://example.com/campaignus/meridian-launch",
            posted_date=date(2026, 6, 13),
            description=(
                "Brand announces a national launch; wants a sonic logo, brand "
                "anthem, and campaign cutdowns. Disclosed mid-five-figure budget."
            ),
            buyer_type=BuyerType.BRAND,
            commercial_campaign=True,
            sonic_branding=True,
            video_production=True,
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=15_000,
            budget_max=30_000,
            location="Miami, FL",
            tags=["sonic-branding", "anthem", "launch"],
        ),
    ],
)


# --------------------------------------------------------------------------- #
# Tier 3 — Film / TV / streaming production (B-tier output)
# --------------------------------------------------------------------------- #
_PRODUCTIONHUB = lambda: TieredSource(
    key="productionhub",
    name="ProductionHUB",
    source_tier=3,
    category="production",
    access="auto via alerts",
    opportunities=[
        Opportunity(
            client="Two Rivers Productions",
            need="Composer for Branded Content Series",
            url="https://example.com/productionhub/two-rivers",
            posted_date=date(2026, 6, 12),
            description=(
                "Production company seeking a composer for an original-music "
                "branded-content series; ongoing episodic work."
            ),
            buyer_type=BuyerType.PRODUCTION_COMPANY,
            commercial_campaign=True,
            video_production=True,
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=10_000,
            budget_max=18_000,
            location="Orlando, FL",
            tags=["branded-content", "composer", "episodic"],
        ),
    ],
)

_STAFFMEUP = lambda: TieredSource(
    key="staffmeup",
    name="Staff Me Up",
    source_tier=3,
    category="production",
    access="manual",
    opportunities=[
        Opportunity(
            client="Lantern Pictures",
            need="Production Entering Development — Composer Needed Soon",
            url="https://example.com/staffmeup/lantern-dev",
            posted_date=date(2026, 6, 10),
            description=(
                "Doc/branded production entering active development; a music "
                "need will follow shortly. Budget undisclosed."
            ),
            buyer_type=BuyerType.PRODUCTION_COMPANY,
            video_production=True,
            music_requirement=MusicRequirement.IMPLIED,
            location="Los Angeles, CA",
            tags=["development", "early-signal"],
        ),
    ],
)

_MANDY = lambda: TieredSource(
    key="mandy",
    name="Mandy Network",
    source_tier=3,
    category="production",
    access="auto via alerts",
    opportunities=[
        Opportunity(
            client="Indie Commercial Director",
            need="Composer for Original Score — Short Commercial Film",
            url="https://example.com/mandy/indie-commercial",
            posted_date=date(2026, 6, 13),
            description=(
                "Director seeks a composer for an original score on a short "
                "commercial film. Modest disclosed budget."
            ),
            buyer_type=BuyerType.PRODUCTION_COMPANY,
            commercial_campaign=True,
            video_production=True,
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=3_000,
            budget_max=6_000,
            location="Miami, FL",
            tags=["score", "commercial", "short-film"],
        ),
    ],
)


# --------------------------------------------------------------------------- #
# Tier 4 — Gaming / interactive (B-tier output)
# --------------------------------------------------------------------------- #
_HITMARKER = lambda: TieredSource(
    key="hitmarker",
    name="Hitmarker",
    source_tier=4,
    category="games",
    access="auto via alerts",
    opportunities=[
        Opportunity(
            client="Lanternlight Games (studio)",
            need="Composer + Sound Design for Indie Title",
            url="https://example.com/hitmarker/lanternlight",
            posted_date=date(2026, 6, 13),
            description=(
                "Indie studio hiring for original music and sound design with "
                "audio implementation; perpetuity/buyout license."
            ),
            buyer_type=BuyerType.PRODUCTION_COMPANY,
            commercial_campaign=False,
            video_production=False,
            music_requirement=MusicRequirement.ORIGINAL,
            budget_min=8_000,
            budget_max=14_000,
            location="Remote",
            tags=["score", "sound-design", "indie", "implementation"],
        ),
    ],
)


# Factories (zero-arg callables) keyed for the registry.
TIERED_SOURCES = {
    "rfpdb": _RFPDB,
    "sam_gov": _SAM_GOV,
    "govwin": _GOVWIN,
    "agency_spotter": _AGENCY_SPOTTER,
    "adforum": _ADFORUM,
    "campaign_us": _CAMPAIGN_US,
    "productionhub": _PRODUCTIONHUB,
    "staffmeup": _STAFFMEUP,
    "mandy": _MANDY,
    "hitmarker": _HITMARKER,
}
