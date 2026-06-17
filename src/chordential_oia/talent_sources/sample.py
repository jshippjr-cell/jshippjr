"""A small demo talent source with hand-built mock creators.

Lets the supply side run end-to-end with no network and doubles as a test
fixture — the analog of :mod:`chordential_oia.sources.sample`. This is the safe
default that runs in CI and on Render; live discovery (the approved web crawl)
plugs in alongside it behind a flag.
"""

from __future__ import annotations

from typing import List

from ..models import MusicDiscipline
from ..talent import Talent
from .base import TalentSource


def _sample_talent() -> List[Talent]:
    mk = TalentSource._pending
    return [
        mk(
            name="Priya Nair",
            email="priya@example.com",
            disciplines=[MusicDiscipline.COMPOSITION, MusicDiscipline.ARRANGEMENT],
            credits="Scored 2 national spots; orchestral + hybrid.",
            location="Los Angeles, CA",
            demo_reel_url="https://example.com/reels/priya",
            notes="Demo source — sample candidate.",
        ),
        mk(
            name="Marcus Bell",
            email="marcus@example.com",
            disciplines=[MusicDiscipline.SOUND_DESIGN],
            credits="Sound design for episodic titles + product films.",
            location="Remote",
            demo_reel_url="https://example.com/reels/marcus",
            notes="Demo source — sample candidate.",
        ),
        mk(
            name="Sofia Ramos",
            email="sofia@example.com",
            disciplines=[MusicDiscipline.SONIC_BRANDING, MusicDiscipline.COMPOSITION],
            credits="Built sonic logos for two DTC brands.",
            location="Austin, TX",
            demo_reel_url="https://example.com/reels/sofia",
            notes="Demo source — sample candidate.",
        ),
    ]


class SampleTalentSource(TalentSource):
    """Deterministic demo source — no network, stable output for tests/seed."""

    key = "sample"
    name = "Sample / Demo Talent"
    category = "demo"

    def fetch(self, limit: int = 50) -> List[Talent]:
        return _sample_talent()[:limit]
