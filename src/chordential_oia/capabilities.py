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
    # editable-document additions (the UI pass consumes these)
    support_chips: dict = field(default_factory=dict)   # section name → [{label, sentence}]
    relevant_links: List[dict] = field(default_factory=list)  # [{label, url}]
    delivery_template: str = "campaign"        # the chosen engagement-template key
    delivery_template_label: str = ""          # human label for the chosen template
    delivery_assumptions: str = ""             # the mandatory assumptions banner text


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


# --------------------------------------------------------------------------- #
# Support-descriptor library (the cabinet's content deliverable — §4 + Appendix)
#
# Each chip = a short ``label`` Jon sees in the rail + the ``sentence`` the client
# reads when it's inserted. ``family`` is one of craft / aesthetic / deliverable /
# assurance. ``templates`` is None for *universal* chips (always available) or a
# list of delivery-template keys for the *deliverable* family (template-scoped, so
# a film brief never surfaces ad-cutdown language). Populated verbatim from the
# council doc's Appendix.
# --------------------------------------------------------------------------- #
SUPPORT_CHIPS = [
    # Craft — "what we'll make" (universal)
    {"id": "craft-original", "family": "craft", "label": "Original composition",
     "sentence": "Original composition — written for your project from a blank page, not licensed stock.",
     "templates": None},
    {"id": "craft-score", "family": "craft", "label": "Score to picture",
     "sentence": "Scored to your edit — music written to hit the story's beats, cue by cue.",
     "templates": None},
    {"id": "craft-production", "family": "craft", "label": "Production & arrangement",
     "sentence": "Full production and arrangement — from first sketch to a finished, mix-ready record.",
     "templates": None},
    {"id": "craft-topline", "family": "craft", "label": "Topline / song writing",
     "sentence": "Topline and song writing — memorable melody and lyric built around your message.",
     "templates": None},
    {"id": "craft-sonic", "family": "craft", "label": "Sonic identity",
     "sentence": "A sonic identity — a short, ownable musical signature that travels across everything you make.",
     "templates": None},
    {"id": "craft-multicut", "family": "craft", "label": "Arrangement for multiple cuts",
     "sentence": "Arranged so one piece flexes into every length and format you need.",
     "templates": None},
    # Aesthetic — "how it should feel" (universal)
    {"id": "aes-brand", "family": "aesthetic", "label": "Brand aesthetic",
     "sentence": "Tuned to your brand's aesthetic — the sound matches the look and the voice.",
     "templates": None},
    {"id": "aes-cinematic", "family": "aesthetic", "label": "Cinematic / orchestral",
     "sentence": "A cinematic, orchestral palette — scale and emotion without the stock-music sheen.",
     "templates": None},
    {"id": "aes-warm", "family": "aesthetic", "label": "Warm & hopeful",
     "sentence": "Warm, hopeful, human — music that leaves the audience feeling something.",
     "templates": None},
    {"id": "aes-modern", "family": "aesthetic", "label": "Modern & current",
     "sentence": "Contemporary production that sounds current, not dated on arrival.",
     "templates": None},
    {"id": "aes-gritty", "family": "aesthetic", "label": "Gritty / textural",
     "sentence": "Gritty, textural, real — character over polish where the story calls for it.",
     "templates": None},
    {"id": "aes-minimal", "family": "aesthetic", "label": "Minimal & restrained",
     "sentence": "Restrained and minimal — space and intention, never wall-to-wall.",
     "templates": None},
    # Deliverable — "what you'll get" (template-scoped)
    {"id": "del-cues", "family": "deliverable", "label": "Cues to picture",
     "sentence": "Every cue delivered to picture, conformed to your locked edit.",
     "templates": ["film_tv"]},
    {"id": "del-stems-me", "family": "deliverable", "label": "Score stems + M&E",
     "sentence": "Full score stems and an M&E mix for dub-stage flexibility and international versions.",
     "templates": ["film_tv"]},
    {"id": "del-spotting", "family": "deliverable", "label": "Spotting session",
     "sentence": "A spotting session up front so we agree where music lives before a note is written.",
     "templates": ["film_tv"]},
    {"id": "del-broadcast", "family": "deliverable", "label": "Broadcast masters",
     "sentence": "Broadcast-ready masters plus an instrumental/TV mix.",
     "templates": ["campaign"]},
    {"id": "del-cutdowns", "family": "deliverable", "label": "Multi-format cutdowns",
     "sentence": "All the cutdowns you need — :30, :15, :06 — and 9:16 social verticals.",
     "templates": ["campaign"]},
    {"id": "del-logo", "family": "deliverable", "label": "Logo + variations",
     "sentence": "A primary sonic logo plus short/long variations for every placement.",
     "templates": ["sonic"]},
    {"id": "del-master-stems", "family": "deliverable", "label": "Produced master + stems",
     "sentence": "A produced master, instrumental, TV track, and the stems.",
     "templates": ["artist"]},
    {"id": "del-stems-flex", "family": "deliverable", "label": "Stems for flexibility",
     "sentence": "Delivered with stems, so the music can be re-versioned as your campaign grows.",
     "templates": None},
    # Assurance — "why it's safe to hire us" (universal)
    {"id": "ass-cleared", "family": "assurance", "label": "Original & cleared",
     "sentence": "100% original and cleared — no samples, no third-party masters, no PRO surprises.",
     "templates": None},
    {"id": "ass-buyout", "family": "assurance", "label": "Full buyout",
     "sentence": "Delivered as a full buyout — you own it, worldwide, in perpetuity.",
     "templates": None},
    {"id": "ass-fixed", "family": "assurance", "label": "Fixed scope & timeline",
     "sentence": "A fixed scope and a dependable timeline — no open-ended creative drift.",
     "templates": None},
    {"id": "ass-vetted", "family": "assurance", "label": "Vetted craft team",
     "sentence": "Made by a vetted craft team matched to your brief, not a faceless library.",
     "templates": None},
    {"id": "ass-revisions", "family": "assurance", "label": "Revisions included",
     "sentence": "Revision rounds built into the scope — we land it, together.",
     "templates": None},
    {"id": "ass-onepartner", "family": "assurance", "label": "One accountable partner",
     "sentence": "One accountable partner from brief to final delivery.",
     "templates": None},
]

# Which descriptor family an editable section pulls from. The section names are
# the keys the template + save routes use for ``support_chips``.
SECTION_FAMILY = {
    "understanding": "craft",
    "aesthetic": "aesthetic",
    "deliverables": "deliverable",
    "assurance": "assurance",
}


def chips_for(section: str, template_key: str = "campaign", conn=None) -> List[dict]:
    """The chips available for an editable section.

    Resolves the section to its descriptor family; for the *deliverable* family the
    list is filtered to the active delivery template (universal deliverable chips —
    ``templates is None`` — always pass). Craft/aesthetic/assurance are universal.
    Any saved "My chips" of the same family are appended so reused phrases show up
    in the rail."""
    family = SECTION_FAMILY.get(section, section)
    out: List[dict] = []
    for chip in SUPPORT_CHIPS:
        if chip["family"] != family:
            continue
        if chip["templates"] is not None and template_key not in chip["templates"]:
            continue
        out.append(dict(chip))
    if conn is not None:
        try:
            from .web import db as _db
            for row in _db.list_custom_chips(conn):
                if (row["family"] or "") == family:
                    out.append({
                        "id": f"custom-{row['id']}", "family": family,
                        "label": row["label"], "sentence": row["sentence"],
                        "templates": None, "custom": True,
                    })
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- #
# Delivery templates (engagement-shaped deliverables/rollout/rights — §6)
#
# Four hand-authored templates. The builder picks one from the lead, Jon can
# override. Each opens with a mandatory assumptions banner ("just want to know the
# assumptions"). No fabricated specifics — types of assets, never fake files.
# --------------------------------------------------------------------------- #
DELIVERY_TEMPLATES = {
    "film_tv": {
        "label": "Film / TV score",
        "deliverables": [
            Deliverable("Score", "Score cues to picture", "WAV 24-bit / 48 kHz"),
            Deliverable("Score", "Spotting session", "Working session"),
            Deliverable("Production assets", "Full score stems", "WAV 24-bit / 48 kHz"),
            Deliverable("Mixes", "M&E (music & effects) mix", "WAV 24-bit / 48 kHz"),
            Deliverable("Documentation", "Cue sheet", "PDF"),
        ],
        "rollout": [],   # a film doesn't get an ad rollout map
        "rights": list(_RIGHTS_SUMMARY),
        "assumptions": (
            "Assumed engagement: feature-film score (~20–30 cues, delivered to "
            "picture). Not right? Switch template or edit below."
        ),
    },
    "campaign": {
        "label": "Brand / advertising campaign",
        "deliverables": list(_BASE_DELIVERABLES),
        "rollout": None,   # filled per-deal by _rollout_for (sonic-aware)
        "rights": list(_RIGHTS_SUMMARY),
        "assumptions": (
            "Assumed engagement: brand/advertising campaign (anthem + cutdowns + "
            "social). Not right? Switch template or edit below."
        ),
    },
    "sonic": {
        "label": "Sonic identity / branding",
        "deliverables": [
            Deliverable("Sonic identity", "Sonic logo / mnemonic", "WAV 24-bit / 48 kHz"),
            Deliverable("Sonic identity", "Short / long variations", "WAV 24-bit / 48 kHz"),
            Deliverable("Application", "App / UI cues", "WAV 24-bit / 48 kHz"),
            Deliverable("Documentation", "Sonic usage guide", "PDF"),
        ],
        "rollout": [
            RolloutItem(":03", "Mnemonic", ["All endcards", "OOH / in-store"]),
            RolloutItem("UI", "App cues", ["Product / app", "On-hold / IVR"]),
        ],
        "rights": list(_RIGHTS_SUMMARY),
        "assumptions": (
            "Assumed engagement: sonic identity / audio branding (logo + variations "
            "+ application cues). Not right? Switch template or edit below."
        ),
    },
    "artist": {
        "label": "Artist / song production",
        "deliverables": [
            Deliverable("Masters", "Produced master", "WAV 24-bit / 48 kHz"),
            Deliverable("Masters", "Instrumental", "WAV 24-bit / 48 kHz"),
            Deliverable("Masters", "TV track", "WAV 24-bit / 48 kHz"),
            Deliverable("Production assets", "Stem package", "WAV 24-bit / 48 kHz"),
        ],
        "rollout": [],
        "rights": list(_RIGHTS_SUMMARY),
        "assumptions": (
            "Assumed engagement: song / artist production (produced master + "
            "instrumental + TV track + stems). Not right? Switch template or edit below."
        ),
    },
}

# Keyword → template, longest-intent-first. Matched across the lead's own words.
_TEMPLATE_KEYWORDS = [
    ("film_tv", ("film", "score", "feature", "cinema", "cinematic", "movie", "tv series", "documentary", "trailer")),
    ("sonic", ("sonic", "logo", "mnemonic", "identity", "audio brand", "sound logo")),
    ("artist", ("song", "artist", "single", "track", "album", "topline", "ep ", "record ")),
    ("campaign", ("campaign", "spot", "brand", "advert", "advertising", "commercial", "anthem")),
]


def pick_delivery_template(opp: Opportunity) -> str:
    """Best-guess engagement template from the lead's own words.

    Reads ``project_type`` (if the row carries one), ``need`` and ``description``.
    Defaults to ``campaign`` (the historical behaviour) when nothing matches."""
    text = " ".join(
        str(getattr(opp, attr, "") or "")
        for attr in ("project_type", "need", "description")
    ).lower()
    for key, words in _TEMPLATE_KEYWORDS:
        if any(w in text for w in words):
            return key
    return "campaign"


def build_understanding(opp: Opportunity) -> str:
    """A conservative, client-facing restatement of the lead's OWN request (§3).

    Deliberately templated and safe: it draws only from ``need`` / ``project_type``
    / ``description`` and invents no specifics and no scoring language. Better a
    plain true sentence than a confident wrong one (Founder's Advocate). Jon edits
    it and drops in support chips to enrich."""
    need = (getattr(opp, "need", "") or "").strip()
    project_type = (getattr(opp, "project_type", "") or "").strip()
    brief = (need or project_type).strip()
    if not brief:
        return (
            "You're bringing us a music brief, and you need a partner to shape its "
            "sound end-to-end — from first sketch to final, polished delivery."
        )
    # Lowercase the lead-in only when it reads as a common-noun phrase (keep proper
    # nouns/acronyms as-is) so "Original :30 brand spot" → "original :30 brand spot".
    lead_in = brief
    if lead_in[:1].isupper() and not lead_in.isupper():
        lead_in = lead_in[0].lower() + lead_in[1:]
    return (
        f"You're looking for {lead_in}, and you need a music partner to shape its "
        f"sound end-to-end — from first idea to finished, ready-to-use delivery."
    )


def build_capabilities_doc(
    opp: Opportunity, qual: QualificationResult, estimate: Estimate, *,
    toggles: dict, call_url: str = "", overrides: Optional[dict] = None,
) -> CapabilitiesDoc:
    """Assemble the document for one opportunity under the given section toggles.

    ``overrides`` is the per-deal ``doc_overrides`` blob (``db.get_doc_overrides``):
    Jon's hand edits applied *on top of* the generated defaults. An un-touched deal
    (``overrides`` empty) renders exactly as before — just with the conservative
    client-facing synopsis instead of the scoring jargon, and an auto-picked
    delivery template instead of the always-campaign one."""
    overrides = overrides or {}
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

    # Client name + understanding — overridable; understanding is NEVER the scoring
    # summary anymore (§3) — a conservative client-facing restatement is the default.
    client = overrides.get("client") or opp.client
    understanding = overrides.get("understanding") or build_understanding(opp)

    # Delivery template — auto-picked from the lead, override wins. The chosen
    # template supplies the deliverables/rollout/rights/assumptions.
    template_key = overrides.get("delivery_template") or pick_delivery_template(opp)
    if template_key not in DELIVERY_TEMPLATES:
        template_key = "campaign"
    template = DELIVERY_TEMPLATES[template_key]

    # Delivery-package outline — only assembled (and only shown) once the deal is
    # qualified, so we never present a delivery standard for an off-craft lead.
    show_delivery = bool(toggles.get("delivery")) and qual.qualified
    deliverables: List[Deliverable] = []
    rights_summary: List[str] = []
    rollout: List[RolloutItem] = []
    if show_delivery:
        override_dels = overrides.get("deliverable_overrides")
        if override_dels:
            deliverables = [
                d if isinstance(d, Deliverable)
                else Deliverable(d.get("group", ""), d.get("asset", ""), d.get("spec", ""))
                for d in override_dels
            ]
        else:
            deliverables = list(template["deliverables"])
        rights_summary = list(template["rights"])
        # campaign's rollout is the legacy sonic-aware map; others are fixed lists.
        tmpl_rollout = template["rollout"]
        rollout = _rollout_for(qual) if tmpl_rollout is None else list(tmpl_rollout)

    delivery_assumptions = overrides.get("delivery_assumptions") or template["assumptions"]
    support_chips = overrides.get("support_chips") or {}
    relevant_links = overrides.get("relevant_links") or []

    return CapabilitiesDoc(
        client=client,
        need=opp.need,
        stage=stage,
        discipline_label=qual.discipline.label,
        value_prop=VALUE_PROP,
        understanding=understanding,
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
        support_chips=support_chips,
        relevant_links=relevant_links,
        delivery_template=template_key,
        delivery_template_label=template["label"],
        delivery_assumptions=delivery_assumptions,
    )
