"""Capabilities / proposal document — a branded, toggleable, stage-evolving brief
you can preview and "Save as PDF" to send a buyer.

Like the other document layers (``prepare``, ``outreach``, ``proposals``) this is
**deterministic**: it assembles what the engines already produced — the
qualification verdict, the estimate's price band, the showcase reel, and the
proposal terms — into a client-facing one-pager. No new pricing math; no AI.

The document **evolves with the deal stage**:
  - discovery (New/Pursuing): capabilities + understanding + work + a call invite;
    **cost hidden** (you don't talk price before scoping).
  - proposal (Submitted): adds the **price band** + deposit terms.
  - contract (Won): adds **Terms & Conditions** + a DocuSign hand-off.
Any section can also be toggled by hand before exporting.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from .estimation import TARGET_MARGIN, Estimate
from .models import MusicDiscipline, Opportunity, QualificationResult
from .proposals import build_proposal
from .web import showcase

VALUE_PROP = (
    "Chordential is a procurement-grade music partner. We turn a brief into "
    "broadcast-ready original music with a vetted craft team, a fixed scope, and "
    "dependable delivery — so brands and agencies get distinctive sound without "
    "the risk of an open-ended creative process."
)


# Deal stage → which sections show by default.
def default_toggles(status: str) -> dict:
    s = (status or "New").strip()
    if s == "Submitted":
        stage = "proposal"
    elif s == "Won":
        stage = "contract"
    else:
        stage = "discovery"
    return {
        "stage": stage,
        "examples": True,
        "call": True,
        "cost": stage in ("proposal", "contract"),       # hidden in discovery
        "terms": stage in ("proposal", "contract"),       # deposit terms at proposal+
        "delivery": stage in ("proposal", "contract"),    # delivery-package outline
    }


@dataclass
class WorkExample:
    title: str
    blurb: str
    client_type: str
    placeholder: bool = True


@dataclass
class Deliverable:
    group: str       # manifest section header (Masters / Cutdowns / …)
    asset: str       # what they receive
    spec: str        # format / spec


@dataclass
class RolloutItem:
    version: str     # e.g. ":60 Anthem"
    label: str       # the cut's role
    channels: List[str]   # where it runs


@dataclass
class CapabilitiesDoc:
    client: str
    need: str
    stage: str
    discipline_label: str
    value_prop: str
    understanding: str
    music_requirement: str
    team: List[str]
    secondary: List[str] = field(default_factory=list)
    # toggled sections
    show_examples: bool = True
    examples: List[WorkExample] = field(default_factory=list)
    show_call: bool = True
    call_url: str = ""
    show_cost: bool = False
    price_low: Optional[int] = None
    price_high: Optional[int] = None
    show_terms: bool = False
    terms: List[str] = field(default_factory=list)
    show_docusign: bool = False
    # delivery-package outline (what their package will include) — progressive
    # disclosure: rendered only when there's real backing data to personalize it.
    show_delivery: bool = False
    campaign_label: str = ""
    deliverables: List[Deliverable] = field(default_factory=list)
    rights_summary: List[str] = field(default_factory=list)
    rollout: List[RolloutItem] = field(default_factory=list)


def _round100(value: float, up: bool) -> int:
    fn = math.ceil if up else math.floor
    return int(fn(value / 100.0)) * 100


def _price_band(est: Estimate) -> tuple:
    """Client-facing price band from the estimate's cost band, using the same
    margin conversion the public site shows. Rounded to tidy $100s."""
    margin = (est.expected_margin_pct or TARGET_MARGIN * 100) / 100.0
    denom = max(0.1, 1.0 - margin)
    return _round100(est.cost_low / denom, up=False), _round100(est.cost_high / denom, up=True)


def _relevant_examples(qual: QualificationResult) -> List[WorkExample]:
    """Showcase reels in scope of the lead — matched on discipline, with a
    fallback to the full reel so the section is never empty."""
    wanted = {qual.discipline, *getattr(qual, "secondary_disciplines", [])}
    matched = [s for s in showcase.SAMPLES if s.discipline in wanted]
    chosen = matched or list(showcase.SAMPLES)
    return [WorkExample(s.title, s.blurb, s.client_type, s.placeholder) for s in chosen]


# The standard delivery outline by discipline — the *types* of assets this craft
# produces, not specific files. Personalized with the client/campaign name in the
# template; never fabricated specifics (no fake filenames/dates/cue sheets).
_BASE_DELIVERABLES = [
    Deliverable("Masters", "Final master", "WAV 24-bit / 48 kHz"),
    Deliverable("Masters", "Instrumental / TV mix", "WAV 24-bit / 48 kHz"),
    Deliverable("Cutdowns", ":30 / :15 / :06 cutdowns", "WAV + MP3 320"),
    Deliverable("Social verticals", "9:16 vertical cuts (loudness-prepped)", "WAV + MP3 320"),
    Deliverable("Production assets", "Mix-ready stem package", "WAV 24-bit / 48 kHz"),
    Deliverable("Documentation", "Cue sheet & rights certificate", "PDF"),
]
_SONIC_LOGO = Deliverable("Sonic identity", "Sonic logo / mnemonic", "WAV 24-bit / 48 kHz")


def _deliverables_for(qual: QualificationResult) -> List[Deliverable]:
    """The asset types the deal's discipline produces (an outline / standard).

    Composition-shaped work gets the full manifest; a sonic-branding lead also
    surfaces the mnemonic. Returns the *kinds* of assets, never invented files."""
    items = list(_BASE_DELIVERABLES)
    wanted = {qual.discipline, *getattr(qual, "secondary_disciplines", [])}
    if MusicDiscipline.SONIC_BRANDING in wanted:
        items.insert(4, _SONIC_LOGO)
    return items


# Standard grant of rights — these are Chordential's own terms, fine to state.
_RIGHTS_SUMMARY = [
    "Original work — full buyout / work-made-for-hire",
    "Territory: worldwide",
    "Term: perpetuity",
    "Media: all campaign media (broadcast, digital, social, OOH, in-store)",
    "100% original & cleared — no samples, no third-party masters, no PRO surprises",
]


def _rollout_for(qual: QualificationResult) -> List[RolloutItem]:
    """A generic-but-personalized version→channel map (the rollout standard)."""
    rollout = [
        RolloutItem(":60", "Anthem", ["Brand film — site hero / YouTube", "Cinema pre-show"]),
        RolloutItem(":30", "Cutdown", ["TV / CTV", "Radio spot"]),
        RolloutItem(":15", "Cutdown", ["Pre-roll — YouTube / OTT", "Vertical — IG / TikTok"]),
        RolloutItem(":06", "Bumper", ["Bumper — YouTube", "Stories / Reels"]),
    ]
    wanted = {qual.discipline, *getattr(qual, "secondary_disciplines", [])}
    if MusicDiscipline.SONIC_BRANDING in wanted:
        rollout.append(
            RolloutItem(":03", "Mnemonic", ["All endcards", "OOH / in-store"])
        )
    return rollout


def build_capabilities_doc(
    opp: Opportunity, qual: QualificationResult, estimate: Estimate, *,
    toggles: dict, call_url: str = "",
) -> CapabilitiesDoc:
    """Assemble the document for one opportunity under the given section toggles."""
    stage = toggles.get("stage", "discovery")
    show_cost = bool(toggles.get("cost"))
    show_terms = bool(toggles.get("terms"))

    price_low = price_high = None
    if show_cost:
        price_low, price_high = _price_band(estimate)

    terms: List[str] = []
    if show_terms:
        terms = build_proposal(opp, qual, estimate).terms

    secondary = [d.label for d in getattr(qual, "secondary_disciplines", [])]

    # Delivery-package outline — only assembled (and only shown) once the deal is
    # qualified, so we never present a delivery standard for an off-craft lead.
    show_delivery = bool(toggles.get("delivery")) and qual.qualified
    deliverables: List[Deliverable] = []
    rights_summary: List[str] = []
    rollout: List[RolloutItem] = []
    if show_delivery:
        deliverables = _deliverables_for(qual)
        rights_summary = list(_RIGHTS_SUMMARY)
        rollout = _rollout_for(qual)

    return CapabilitiesDoc(
        client=opp.client,
        need=opp.need,
        stage=stage,
        discipline_label=qual.discipline.label,
        value_prop=VALUE_PROP,
        understanding=qual.fit_summary,
        music_requirement=opp.music_requirement.label,
        team=list(qual.team_shape or qual.discipline.team_shape),
        secondary=secondary,
        show_examples=bool(toggles.get("examples")),
        examples=_relevant_examples(qual),
        show_call=bool(toggles.get("call")),
        call_url=call_url,
        show_cost=show_cost,
        price_low=price_low,
        price_high=price_high,
        show_terms=show_terms,
        terms=terms,
        show_docusign=(stage == "contract"),
        show_delivery=show_delivery,
        campaign_label=opp.need,
        deliverables=deliverables,
        rights_summary=rights_summary,
        rollout=rollout,
    )
