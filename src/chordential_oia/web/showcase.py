"""Front-of-house showcase content — deterministic, code-managed.

The public site's brochure copy (hero, capabilities, sample reel) lives here as
plain data rather than in the database: it is editorial content, not pipeline
state, so it ships with the app and stays version-controlled. Real audio/video
assets are supplied later by Jon; until then the sample entries reference
placeholder posters and are clearly marked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# Disciplines map 1:1 onto the qualification engine's MusicDiscipline craft set,
# so what we advertise is exactly what the engine knows how to qualify and price.
from ..models import MusicDiscipline


@dataclass(frozen=True)
class Capability:
    discipline: MusicDiscipline
    headline: str
    blurb: str


@dataclass(frozen=True)
class SampleReel:
    title: str
    discipline: MusicDiscipline
    client_type: str
    blurb: str
    media_kind: str = "audio"   # "audio" | "video" — drives the player chrome
    poster: str = ""            # static path to a poster image (placeholder for now)
    placeholder: bool = True    # True until a real asset is attached


HERO = {
    "eyebrow": "Original music, sound, and sonic identity",
    "title": "Music that makes the work unforgettable.",
    "lede": (
        "Chordential is a music procurement studio. We compose, design, and "
        "supervise original sound for brands, agencies, and producers — and we "
        "match every commission to exactly the right creators."
    ),
    "primary_cta": {"label": "Start a project", "href": "/site/start"},
    "secondary_cta": {"label": "Book a call", "href": "/site/book"},
}


CAPABILITIES: List[Capability] = [
    Capability(
        MusicDiscipline.COMPOSITION,
        "Original composition",
        "Custom scores and tracks written to picture, brief, or brand — from a "
        "single spot to a full campaign.",
    ),
    Capability(
        MusicDiscipline.SONIC_BRANDING,
        "Sonic branding",
        "Mnemonics, sound logos, and audio identity systems that make a brand "
        "instantly recognizable by ear.",
    ),
    Capability(
        MusicDiscipline.SOUND_DESIGN,
        "Sound design",
        "Textures, transitions, and detail work that give a film or product the "
        "right sonic feel.",
    ),
    Capability(
        MusicDiscipline.ARRANGEMENT,
        "Arrangement & orchestration",
        "Arranging and orchestrating existing themes for ensemble, orchestra, or "
        "hybrid productions.",
    ),
    Capability(
        MusicDiscipline.SUPERVISION,
        "Music supervision",
        "Finding, clearing, and placing the right music — original or licensed — "
        "for your project.",
    ),
]


# Placeholder reel — structure is real, assets arrive later (Jon supplies media).
SAMPLES: List[SampleReel] = [
    SampleReel(
        "Anthem for a national rebrand",
        MusicDiscipline.COMPOSITION,
        "Brand",
        "A :60 orchestral-hybrid anthem written for a brand relaunch.",
        media_kind="video",
    ),
    SampleReel(
        "Three-note sound logo",
        MusicDiscipline.SONIC_BRANDING,
        "Agency",
        "A sonic mnemonic and its variations across touchpoints.",
        media_kind="audio",
    ),
    SampleReel(
        "Title sequence sound design",
        MusicDiscipline.SOUND_DESIGN,
        "Production company",
        "Designed textures and hits for an episodic title sequence.",
        media_kind="video",
    ),
    SampleReel(
        "Strings arrangement for a holiday spot",
        MusicDiscipline.ARRANGEMENT,
        "Agency",
        "A warm string arrangement of a known melody for a :30 spot.",
        media_kind="audio",
    ),
]


@dataclass(frozen=True)
class Showcase:
    hero: dict = field(default_factory=lambda: HERO)
    capabilities: List[Capability] = field(default_factory=lambda: CAPABILITIES)
    samples: List[SampleReel] = field(default_factory=lambda: SAMPLES)


def get_showcase() -> Showcase:
    """The single showcase payload the public templates render from."""
    return Showcase()
