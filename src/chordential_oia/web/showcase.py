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
    "video": "/static/public/hero-process.mp4?v=2",  # capabilities "Process" reel (compressed)
    "poster": "/static/public/hero-process-poster.jpg?v=2",  # first-frame poster (shown on mobile)
    "loop": "/static/public/hero-loop.webp",  # animated fallback if video is cleared
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
        "A holiday campaign requires music that evokes warmth, nostalgia, and celebration "
        "without relying on predictable seasonal tropes.",
        "This demonstration explores contemporary string writing, layered harmonies, and "
        "dynamic orchestration techniques designed to create emotional connection while "
        "preserving a refined commercial sound.",
        "An approach to arranging and orchestrating music that enhances storytelling and "
        "supports emotionally driven advertising campaigns.",
        audio_url="/static/public/demo-holiday-strings.mp3",
    ),
    CapabilityDemo(
        "Title Sequence Sound Design",
        "Sound design",
        "Explore how sound design can establish tone, atmosphere, and narrative intrigue "
        "before a story unfolds.",
        "A title sequence must capture attention immediately and create anticipation "
        "without relying on dialogue or narrative context.",
        "This demonstration examines the use of evolving textures, cinematic impacts, "
        "transitional elements, and atmospheric layers to create tension, movement, and "
        "immersion.",
        "An approach to building sonic environments that strengthen visual storytelling "
        "and contribute to a distinctive creative identity.",
        audio_url="/static/public/demo-title-sequence.mp3",
    ),
    CapabilityDemo(
        "National Retail Brand — Campaign Anthem",
        "Original composition",
        "Explore how music can support a national retail brand relaunch through emotional "
        "storytelling and broad audience appeal.",
        "A large consumer brand requires a campaign anthem that feels optimistic, "
        "trustworthy, and adaptable across advertising, digital, and social content.",
        "This demonstration explores a momentum-driven musical direction built around a "
        "memorable melodic theme, combining organic instrumentation with modern production "
        "techniques to create energy, optimism, and forward movement.",
        "An approach to developing brand-forward music that reinforces messaging, supports "
        "storytelling, and connects with diverse consumer audiences.",
        audio_url="/static/public/demo-retail-anthem.mp3",
    ),
    CapabilityDemo(
        "Financial Services — Brand Theme",
        "Sonic branding",
        "Explore how music can communicate trust, stability, and long-term confidence "
        "within a financial services context.",
        "A financial brand requires a musical identity that conveys credibility and "
        "sophistication while avoiding generic corporate conventions.",
        "This demonstration examines a restrained piano-led theme supported by subtle "
        "electronic textures and recurring musical motifs intended to communicate clarity, "
        "intelligence, and modern professionalism.",
        "An approach to translating brand attributes into a cohesive musical identity "
        "suitable for advertising, presentations, digital experiences, and branded content.",
        audio_url="/static/public/demo-financial-theme.mp3",
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
