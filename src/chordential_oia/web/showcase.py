"""Front-of-house showcase content — deterministic, code-managed.

Editorial content for the public magazine site, structured to the council-ratified
framework (see ``docs/front-of-house-design-council.md``, derived from the landing
-page brief). All "proof" is honest: sample work is labeled Sample, there are no
fabricated client logos or testimonials. Cinematic stills are placeholders from the
brief's reference deck, to be replaced with licensed/own photography.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

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
    media_kind: str = "audio"
    poster: str = ""
    placeholder: bool = True


@dataclass(frozen=True)
class Case:
    title: str
    objective: str
    challenge: str
    solved: str
    outcome: str
    media_kind: str = "audio"    # 'audio' | 'video' — which player to slot in
    media_url: str = ""          # empty => placeholder player until the asset lands
    poster: str = ""             # optional video poster
    sample: bool = True          # honest until real campaigns exist


@dataclass(frozen=True)
class Step:
    n: int
    title: str
    outcome: str
    timeline: str


@dataclass(frozen=True)
class CapabilityDemo:
    """A capability demonstration for the public 'Capability demos' page.

    Honest framing: Chordential hasn't won client engagements yet, so these are
    NOT case studies of real commissions — they demonstrate how we'd approach a
    brief and the craft we bring. ``audio_url`` empty => 'audio coming soon'.
    """
    title: str
    discipline_label: str
    objective: str
    brief: str
    approach: str
    demonstrates: str
    audio_url: str = ""


# Hero — copy ratified from the brief. The background is a placeholder for a
# looping behind-the-scenes video (asset TBD); no still image behind the text.
HERO = {
    "eyebrow": "Original composition for agencies",
    "title": "Music that moves campaigns forward — and gets approved.",
    "lede": (
        "Original composition for agencies who need clarity, control, and "
        "confidence in delivery."
    ),
    "primary_cta": {"label": "Hear the demos", "href": "/samples"},
    "secondary_cta": {"label": "Start a conversation", "href": "/start"},
    # Hero background: spliced clip (Engineers/string ensemble + Composer/MIDI) on
    # Cloudinary. f_auto,q_auto = optimal codec + visually-lossless quality, so it's
    # a smaller, faster-starting file with NO visible quality loss.
    # ac_none strips the audio track entirely at delivery (no re-upload) — a truly
    # silent video is the most reliable to autoplay on mobile and loads a touch
    # lighter. The hero is decorative; it never needs sound.
    "video": "https://res.cloudinary.com/dwzzf6vvd/video/upload/f_auto,q_auto,ac_none/v1782271309/herospliced_lbtrdp.mp4",
    "poster": "/static/public/hero-spliced-poster.jpg?v=1",
    "loop": "/static/public/hero-loop.webp",  # fallback if video is cleared
}

# Honest market reach — NOT fabricated client logos, NOT narrow verticals. These
# are the markets the deep research validates (docs/market-research.md), led by the
# brand/agency beachhead. See the council addendum in front-of-house-design-council.md.
TRUST_CATEGORIES = ["Brands & agencies", "Film & TV", "Games", "Creators"]

# The thesis.
PROBLEM = {
    "before": ["7 versions in the timeline", "“Can we try lighter?”",
               "“Legal wants safer”", "Feedback piling up"],
    "after": ["One locked cue", "3 controlled variations", "Approval sent",
              "Delivery complete"],
    "headline": "Music rarely fails creatively. It fails operationally.",
    "image_before": "/static/public/img/problem-a.jpg",
    "image_after": "/static/public/img/problem-b.jpg",
}

# The 4-step approach.
STEPS: List[Step] = [
    Step(1, "Direction Lock",
         "We agree the creative direction before a note is written.",
         "Day 1–2"),
    Step(2, "Structural Composition",
         "The cue is built to picture and brief — structure first, not noodling.",
         "Day 3–6"),
    Step(3, "Controlled Variation",
         "A bounded set of variations — not an open-ended revision spiral.",
         "Day 7–9"),
    Step(4, "Bounded Delivery",
         "Stems, versions, cue sheet, and rights — packaged for sign-off.",
         "Day 10"),
]

# What delivery actually looks like (true today — operational clarity).
DELIVERY_ITEMS = [
    "WAV deliverables", "Version naming system", "Cue sheet",
    "Rights clarity", "Stems breakdown", "Campaign rollout versions",
]

# Featured work — SAMPLE until real campaigns exist (honest). Each card carries a
# media player slot; drop in media_url when the audio/video asset is ready.
CASES: List[Case] = [
    Case(
        "National retail brand — campaign anthem",
        "A :60 anthem for a national relaunch, plus cutdowns.",
        "Five stakeholders, two rounds of legal, a moving deadline.",
        "Direction locked up front; three controlled variations; one approval pass.",
        "Approved without reopening the creative conversation.",
        media_kind="video",
    ),
    Case(
        "Financial services — sonic identity",
        "A short sonic logo and its variations across touchpoints.",
        "Needed to feel trustworthy and pass brand + compliance review.",
        "A single mnemonic with bounded variants; rights cleared on delivery.",
        "Signed off by brand and compliance without friction.",
        media_kind="audio",
    ),
]

# Field Notes — editorial presence, honestly stubbed.
FIELD_NOTES = [
    {"title": "Why most music fails in the approval phase", "status": "Coming soon"},
    {"title": "The last mile of campaign music", "status": "Coming soon"},
    {"title": "How to avoid a creative reset in post", "status": "Coming soon"},
]

ABOUT = (
    "Chordential is a music procurement studio. We compose, design, and supervise "
    "original music for agencies and producers — and we run the process so it stays "
    "contained: clear direction, bounded revisions, and approval-ready delivery."
)

CLOSE = {
    "headline": "See how your next campaign could sound.",
    "sub": "Tell us about the project — we’ll come back with an approach and a price range.",
    "cta": {"label": "Start a conversation", "href": "/start"},
}


CAPABILITIES: List[Capability] = [
    Capability(MusicDiscipline.COMPOSITION, "Original composition",
               "Custom scores and tracks written to picture, brief, or brand."),
    Capability(MusicDiscipline.SONIC_BRANDING, "Sonic branding",
               "Mnemonics, sound logos, and audio identity systems."),
    Capability(MusicDiscipline.SOUND_DESIGN, "Sound design",
               "Textures, transitions, and detail that give the work its feel."),
    Capability(MusicDiscipline.ARRANGEMENT, "Arrangement & orchestration",
               "Arranging and orchestrating for ensemble, orchestra, or hybrid."),
    Capability(MusicDiscipline.SUPERVISION, "Music supervision",
               "Finding, clearing, and placing the right music — original or licensed."),
]

SAMPLES: List[SampleReel] = [
    SampleReel("Anthem for a national rebrand", MusicDiscipline.COMPOSITION, "Brand",
               "A :60 orchestral-hybrid anthem written for a brand relaunch.", "video"),
    SampleReel("Three-note sound logo", MusicDiscipline.SONIC_BRANDING, "Agency",
               "A sonic mnemonic and its variations across touchpoints.", "audio"),
    SampleReel("Title sequence sound design", MusicDiscipline.SOUND_DESIGN,
               "Production company", "Designed textures and hits for a title sequence.",
               "video"),
    SampleReel("Strings arrangement for a holiday spot", MusicDiscipline.ARRANGEMENT,
               "Agency", "A warm string arrangement of a known melody for a :30.",
               "audio"),
]


# Demos intro — CMO-led copy (docs/capability-demos-council.md). Leads with the
# brief and the buyer, never with "new studio" / "no clients": a demonstration is
# the purest proof for a craft house, and saying so is both confident and true.
DEMOS_INTRO = {
    "eyebrow": "Capability Demonstrations",
    "title": "Built to brief.",
    "lede": (
        "Every track here answers a campaign brief — an objective, a creative "
        "challenge, and our response in music. Press play for the sound; open the "
        "brief to see how we'd score yours."
    ),
    # Home featured-section heading (same vocabulary, one continuous story).
    "home_title": "Hear how we'd score your brief.",
    "home_cta": "Open the full briefs →",
}

# Capability demos — the public "Capability demos" page. Truthful: demonstrations
# of approach/craft, not client commissions. All four tracks attached.
DEMOS: List[CapabilityDemo] = [
    CapabilityDemo(
        "Strings Arrangement for a Holiday Spot",
        "Arrangement & orchestration",
        "Explore how orchestral string arrangements can support seasonal advertising "
        "while maintaining a premium brand aesthetic.",
        "A holiday campaign requiring music that evokes warmth, nostalgia, and celebration "
        "— without leaning on predictable seasonal tropes.",
        "Contemporary string writing, layered harmonies, and dynamic orchestration designed "
        "to create emotional connection while preserving a refined commercial sound.",
        "Storytelling-first arranging and orchestration that makes emotionally driven "
        "advertising land.",
        audio_url="https://res.cloudinary.com/dwzzf6vvd/video/upload/v1782269017/STRING_ARRANGEMENT_HOLIDAY_SPOT_3_Evergreen_Window_nlifit.mp3",
    ),
    CapabilityDemo(
        "Title Sequence Sound Design",
        "Sound design",
        "Explore how sound design can establish tone, atmosphere, and narrative intrigue "
        "before a story unfolds.",
        "A title sequence capturing attention instantly and building anticipation — with no "
        "dialogue or narrative to lean on.",
        "Evolving textures, cinematic impacts, transitional elements, and atmospheric layers "
        "that build tension, movement, and immersion.",
        "Sonic worlds that strengthen visual storytelling and sharpen a brand's creative "
        "identity.",
        audio_url="https://res.cloudinary.com/dwzzf6vvd/video/upload/v1782269007/Title_sequence_sound_design_4_Black_Thread_zhtdsg.mp3",
    ),
    CapabilityDemo(
        "National Retail Brand — Campaign Anthem",
        "Original composition",
        "Explore how music can support a national retail brand relaunch through emotional "
        "storytelling and broad audience appeal.",
        "A national relaunch demanding an anthem that feels optimistic and trustworthy — and "
        "adapts across broadcast, digital, and social.",
        "A momentum-driven direction built around a memorable melodic theme — organic "
        "instrumentation meeting modern production to create energy, optimism, and forward "
        "movement.",
        "Brand-forward music that reinforces the message and connects across diverse "
        "audiences.",
        audio_url="https://res.cloudinary.com/dwzzf6vvd/video/upload/v1782269033/ANTHEM_FOR_A_NATIONAL_REBRAND_3_5_Crestline_Motif_scjbhs.mp3",
    ),
    CapabilityDemo(
        "Financial Services — Brand Theme",
        "Sonic branding",
        "Explore how music can communicate trust, stability, and long-term confidence "
        "within a financial services context.",
        "A financial brand needing an identity that signals credibility and sophistication "
        "— without the generic corporate clichés.",
        "A restrained, piano-led theme supported by subtle electronic textures and recurring "
        "motifs — communicating clarity, intelligence, and modern professionalism.",
        "Brand attributes translated into one cohesive identity that carries across every "
        "touchpoint.",
        audio_url="https://res.cloudinary.com/dwzzf6vvd/video/upload/v1782269023/FIVE_NOTE_SOUND_LOGO_2_Five_Note_Signal_udyk8p.mp3",
    ),
]


@dataclass(frozen=True)
class Showcase:
    hero: dict = field(default_factory=lambda: HERO)
    trust_categories: List[str] = field(default_factory=lambda: TRUST_CATEGORIES)
    problem: dict = field(default_factory=lambda: PROBLEM)
    steps: List[Step] = field(default_factory=lambda: STEPS)
    delivery_items: List[str] = field(default_factory=lambda: DELIVERY_ITEMS)
    cases: List[Case] = field(default_factory=lambda: CASES)
    field_notes: List[dict] = field(default_factory=lambda: FIELD_NOTES)
    about: str = ABOUT
    close: dict = field(default_factory=lambda: CLOSE)
    capabilities: List[Capability] = field(default_factory=lambda: CAPABILITIES)
    samples: List[SampleReel] = field(default_factory=lambda: SAMPLES)
    demos: List[CapabilityDemo] = field(default_factory=lambda: DEMOS)
    demos_intro: dict = field(default_factory=lambda: DEMOS_INTRO)


def get_showcase() -> Showcase:
    return Showcase()
