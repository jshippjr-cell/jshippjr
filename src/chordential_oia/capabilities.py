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
from .models import Opportunity, QualificationResult
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
    }


@dataclass
class WorkExample:
    title: str
    blurb: str
    client_type: str
    placeholder: bool = True


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
    )
