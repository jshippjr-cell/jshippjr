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
import re
from dataclasses import dataclass, field, fields
from typing import List, Optional

from .estimation import TARGET_MARGIN, Estimate
from .models import MusicDiscipline, Opportunity, QualificationResult
from .proposals import build_proposal
from .web import showcase

VALUE_PROP = (
    "Chordential is a procurement-grade music partner. We turn a brief into "
    "broadcast-ready original music with a vetted craft team, a fixed scope, and "
    "dependable delivery, so brands and agencies get distinctive sound without "
    "the risk of an open-ended creative process."
)


# Deal stage → which sections show by default.
def default_toggles(status: str, *, met: bool = False) -> dict:
    """Which sections a document of this stage opens with.

    ``met`` — a discovery call has happened — is the second axis, and it is the one that
    turns the summary into a proposal (ADR-0065). "You don't talk price before scoping"
    is the rule the stage axis encodes, and it is right; but after the call the scoping
    HAS happened, and a summary that still withheld the number sent the client away to
    wait for a second document. That second document is the one they needed to take to
    whoever holds the budget, and it arrived days after the conversation that earned it.

    A met deal therefore opens with cost, terms and the delivery outline on — the
    commercial close, in the same artifact as what we heard. Every one of them is still
    a checkbox: the machine proposes, and the operator can uncheck any of it before
    anyone sees it.
    """
    s = (status or "New").strip()
    if s == "Submitted":
        stage = "proposal"
    elif s == "Won":
        stage = "contract"
    else:
        stage = "discovery"
    priced = met or stage in ("proposal", "contract")
    return {
        "stage": stage,
        "examples": True,
        "call": True,
        "cost": priced,          # hidden before scoping; after the call, scoping is done
        "terms": priced,         # deposit terms travel with the number, never apart
        "delivery": priced,      # delivery-package outline
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
    # The licence the band was built on, so the operator can SEE the four levers that
    # produced it and correct one without leaving the document. Internal: rendered only in
    # edit mode. What the client reads is the band and, where a lever was assumed rather
    # than stated, the "What this rests on" note — never the factor table.
    licence: Optional[object] = None
    show_terms: bool = False
    terms: List[str] = field(default_factory=list)
    show_docusign: bool = False
    # What the fee rests on that the brief did not state (ADR-0058), in the client's
    # hearing — `client_voice.client_assumptions` holds back the margin and the
    # calibration notes, which are true, internal, and would price the next negotiation
    # for the buyer if printed on a document they sign.
    assumptions: List[str] = field(default_factory=list)
    # The summary as something that can be AGREED to (ADR-0065). Present only when the
    # document carries a price and terms; `agreement.is_signable` is the gate, so a
    # summary that quotes nothing offers no signature rather than collecting a
    # commitment to an unnamed number.
    show_agreement: bool = False
    agreement: Optional["object"] = None
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
    relevant_uploads: List[dict] = field(default_factory=list)  # [{label, url, filename}]
    delivery_template: str = "campaign"        # the chosen engagement-template key
    delivery_template_label: str = ""          # human label for the chosen template
    delivery_assumptions: str = ""             # the mandatory assumptions banner text
    # ADR-0017 — every section inherits from Campaign Intelligence when it exists.
    ci: dict = field(default_factory=dict)     # canonical CI values by key (brief_view fields)
    risks: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)   # the FEW a client can answer
    deferred_terms_note: str = ""              # the commercial points the proposal will state
    met: bool = False                          # a discovery meeting happened (tone switch)
    intro: str = ""                            # the meeting-summary opening line
    commercial: dict = field(default_factory=dict)  # the commercial close (see build)


def doc_to_json(doc: CapabilitiesDoc) -> str:
    """Serialize the rendered brief for a send-time snapshot (ADR-0017): what the operator
    approved is what the client opens, forever."""
    import dataclasses
    import json as _json
    return _json.dumps(dataclasses.asdict(doc))


def doc_from_json(payload: str) -> Optional[CapabilitiesDoc]:
    """Rehydrate a snapshot back into the doc the template renders. Unknown keys from
    older/newer snapshots are dropped; nested rows regain their dataclass types."""
    import json as _json
    try:
        data = dict(_json.loads(payload))
    except (ValueError, TypeError):
        return None
    known = {f.name for f in fields(CapabilitiesDoc)}
    data = {k: v for k, v in data.items() if k in known}
    try:
        data["examples"] = [WorkExample(**e) for e in data.get("examples") or []]
        data["deliverables"] = [Deliverable(**d) for d in data.get("deliverables") or []]
        data["rollout"] = [RolloutItem(**r) for r in data.get("rollout") or []]
        # The agreement is DERIVED, so it is rebuilt rather than rehydrated: a snapshot
        # stores it as a plain dict, and a dict that reached the template would have no
        # `signable_text` — a signature block rendered over nothing. Everything it is
        # built from is snapshotted, so rebuilding reproduces it exactly, which is also
        # what makes the digest of a frozen send still verify.
        data.pop("agreement", None)
        return attach_agreement(CapabilitiesDoc(**data))
    except TypeError:
        return None


def attach_agreement(doc: CapabilitiesDoc,
                     deposit_amount: Optional[float] = None) -> CapabilitiesDoc:
    """Give the document its agreement, when there is something to agree to.

    One derivation, one place (ADR-0062's rule applied to a contract): the agreement is
    assembled from the document the client is reading, so the text that is displayed and
    the text a signature binds to cannot drift apart. Called on both paths — a freshly
    built document and a rehydrated snapshot — because a frozen send is exactly the case
    where the two drifting apart would be invisible.
    """
    from .agreement import build_agreement, is_signable
    doc.show_agreement = is_signable(doc)
    doc.agreement = (build_agreement(doc, deposit_amount=deposit_amount)
                     if doc.show_agreement else None)
    return doc


def _round100(value: float, up: bool) -> int:
    fn = math.ceil if up else math.floor
    return int(fn(value / 100.0)) * 100


def _price_band(est: Estimate) -> tuple:
    """The estimator's own price band — its cost band converted at target margin,
    the same conversion the public site shows. Rounded to tidy $100s.

    This is the LAST leg of ``quote_band``'s precedence, not a quote in itself.
    Call ``quote_band``; a surface that reaches straight for this one ignores both
    the client's disclosed budget and the operator's decision."""
    margin = (est.expected_margin_pct or TARGET_MARGIN * 100) / 100.0
    denom = max(0.1, 1.0 - margin)
    return _round100(est.cost_low / denom, up=False), _round100(est.cost_high / denom, up=True)


def _money_ints(text: str) -> list:
    """Every dollar figure in a string → ints. '$18,000–$24,000' → [18000, 24000]."""
    return [int(m.replace(",", "")) for m in re.findall(r"\$?\s*([\d][\d,]{2,})", text or "")]


def quote_band(
    opp: Opportunity, estimate: Optional[Estimate], *,
    ci_fields: Optional[dict] = None, commercial_overrides: Optional[dict] = None,
) -> tuple:
    """**THE** number we put in front of a buyer (ADR-0034). One authority, every
    renderer: the client Campaign Brief, the client Commercial Review, the pursuit
    checklist, and the outreach cadence all quote this and nothing else.

    Precedence (ADR-0065 supersedes ADR-0034 tier 2):

    1. an explicit operator override (``fee_low``/``fee_high``) — a human decided;
    2. **what the work is worth** — :func:`chordential_oia.pricing.build_quote`: the
       creative fee at target margin plus the licence fee for the media, territory, term
       and exclusivity discovery actually captured, floored at cost.

    Tier 2 used to be *the client's disclosed budget*, and that fired on essentially
    every deal that had had a discovery call, because discovering the budget is what a
    discovery call does. It made the product a name-your-price: the same charity film was
    quoted $6,000 to a client who said $6,000 and $90,000 to one who said $90,000,
    against a cost to deliver of $4,062–$8,435. The budget is still read — it decides
    ``Quote.budget_verdict`` — but it no longer sets the number, and a figure below our
    floor now produces a flag for the operator instead of a quote we lose money on.

    Returns ``(low, high)``, or ``(None, None)`` with no estimate to price from — never a
    fabricated number, and never the estimate's *cost* range.
    """
    quote = quote_for(opp, estimate, ci_fields=ci_fields,
                      commercial_overrides=commercial_overrides)
    return (quote.low, quote.high) if quote is not None else (None, None)


def stated_budget_text(opp, ci_fields: Optional[dict] = None) -> str:
    """What the client said their budget was, wherever they said it.

    CI first (a meeting outranks a posting — ADR-0017), then the opportunity's own
    columns. Used ONLY to judge the quote, never to set it.
    """
    band = str((ci_fields or {}).get("budget_band") or "").strip()
    if band:
        return band
    lo = int(getattr(opp, "budget_min", 0) or 0)
    hi = int(getattr(opp, "budget_max", 0) or 0)
    nums = [n for n in (lo, hi) if n]
    return " to ".join(f"${n:,}" for n in sorted(set(nums))) if nums else ""


def quote_for(
    opp: Opportunity, estimate: Optional[Estimate], *,
    ci_fields: Optional[dict] = None, commercial_overrides: Optional[dict] = None,
):
    """THE quote — the whole of it, not just the two numbers (ADR-0065).

    ``quote_band`` is this function's tuple view. Surfaces that need more than a band —
    the itemised derivation a buyer can check, the floor, the verdict on what the client
    said — reach for this, so the price on the proposal and the warning on the deal page
    can never come from two different calculations.
    """
    from .pricing import build_quote, licence_from_ci
    if estimate is None:
        return None
    quote = build_quote(
        estimate, licence_from_ci(ci_fields),
        budget_band=stated_budget_text(opp, ci_fields),
    )
    ov = commercial_overrides or {}
    olo, ohi = ov.get("fee_low"), ov.get("fee_high")
    if olo and ohi:
        return quote.rescaled_to(int(olo), int(ohi))
    return quote


def quote_phrase(band: Optional[tuple]) -> str:
    """Render a ``quote_band`` result for an internal action list ("Provide an
    indicative quote: …"). An unresolved band says so — the surfaces that used to
    fill this slot reached for the estimate's *cost* range or its point suggested
    price, which is how they ended up quoting numbers the client documents never
    showed."""
    lo, hi = band or (None, None)
    if not lo or not hi:
        return "TBD · no budget discovered and no operator price set"
    if lo == hi:
        return f"${lo:,.0f}"
    return f"${lo:,.0f} to ${hi:,.0f}"


def _relevant_examples(qual: QualificationResult) -> List[WorkExample]:
    """The client-facing Campaign Brief no longer auto-injects placeholder
    "sample reels" (e.g. the anthem-for-a-national-brand demo card) as if they
    were relevant work — that read as fabricated. "Relevant work" now carries
    only the tracks the operator hand-picks for the lead (relevant_links /
    relevant_uploads). The marketing showcase (showcase.SAMPLES) is unaffected."""
    return []


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
# ADR-0032: the recording is bought out, the composition's publishing is retained.
# This used to promise "full buyout / work-made-for-hire" — under which the client
# would own the publishing too, contradicting the cue sheet we file.
_RIGHTS_SUMMARY = [
    "Original work: you own the master outright",
    "Perpetual sync licence across every campaign medium",
    "Territory: worldwide",
    "Term: perpetuity",
    "Media: all campaign media (broadcast, digital, social, OOH, in-store)",
    "Composition publishing retained by Chordential; we file the cue sheet",
    "100% original & cleared: no samples, no third-party masters, nothing to clear but ours",
]


def _rollout_for(qual: QualificationResult) -> List[RolloutItem]:
    """A generic-but-personalized version→channel map (the rollout standard)."""
    rollout = [
        RolloutItem(":60", "Anthem", ["Brand film · site hero / YouTube", "Cinema pre-show"]),
        RolloutItem(":30", "Cutdown", ["TV / CTV", "Radio spot"]),
        RolloutItem(":15", "Cutdown", ["Pre-roll · YouTube / OTT", "Vertical · IG / TikTok"]),
        RolloutItem(":06", "Bumper", ["Bumper · YouTube", "Stories / Reels"]),
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
     "sentence": "Original composition, written for your project from a blank page, not licensed stock.",
     "templates": None},
    {"id": "craft-score", "family": "craft", "label": "Score to picture",
     "sentence": "Scored to your edit: music written to hit the story's beats, cue by cue.",
     "templates": None},
    {"id": "craft-production", "family": "craft", "label": "Production & arrangement",
     "sentence": "Full production and arrangement, from first sketch to a finished, mix-ready record.",
     "templates": None},
    {"id": "craft-topline", "family": "craft", "label": "Topline / song writing",
     "sentence": "Topline and song writing: memorable melody and lyric built around your message.",
     "templates": None},
    {"id": "craft-sonic", "family": "craft", "label": "Sonic identity",
     "sentence": "A sonic identity: a short, ownable musical signature that travels across everything you make.",
     "templates": None},
    {"id": "craft-multicut", "family": "craft", "label": "Arrangement for multiple cuts",
     "sentence": "Arranged so one piece flexes into every length and format you need.",
     "templates": None},
    # Aesthetic — "how it should feel" (universal)
    {"id": "aes-brand", "family": "aesthetic", "label": "Brand aesthetic",
     "sentence": "Tuned to your brand's aesthetic, so the sound matches the look and the voice.",
     "templates": None},
    {"id": "aes-cinematic", "family": "aesthetic", "label": "Cinematic / orchestral",
     "sentence": "A cinematic, orchestral palette: scale and emotion without the stock-music sheen.",
     "templates": None},
    {"id": "aes-warm", "family": "aesthetic", "label": "Warm & hopeful",
     "sentence": "Warm, hopeful, human: music that leaves the audience feeling something.",
     "templates": None},
    {"id": "aes-modern", "family": "aesthetic", "label": "Modern & current",
     "sentence": "Contemporary production that sounds current, not dated on arrival.",
     "templates": None},
    {"id": "aes-gritty", "family": "aesthetic", "label": "Gritty / textural",
     "sentence": "Gritty, textural, real: character over polish where the story calls for it.",
     "templates": None},
    {"id": "aes-minimal", "family": "aesthetic", "label": "Minimal & restrained",
     "sentence": "Restrained and minimal: space and intention, never wall-to-wall.",
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
     "sentence": "All the cutdowns you need: :30, :15, :06, and 9:16 social verticals.",
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
     "sentence": "100% original and cleared: no samples, no third-party masters, no PRO surprises.",
     "templates": None},
    {"id": "ass-buyout", "family": "assurance", "label": "Yours in perpetuity",
     "sentence": "You own the recording and the right to use it forever, worldwide, "
                 "in every campaign medium.",
     "templates": None},
    {"id": "ass-fixed", "family": "assurance", "label": "Fixed scope & timeline",
     "sentence": "A fixed scope and a dependable timeline, with no open-ended creative drift.",
     "templates": None},
    {"id": "ass-vetted", "family": "assurance", "label": "Vetted craft team",
     "sentence": "Made by a vetted craft team matched to your brief, not a faceless library.",
     "templates": None},
    {"id": "ass-revisions", "family": "assurance", "label": "Revisions included",
     "sentence": "Revision rounds built into the scope, so we land it together.",
     "templates": None},
    {"id": "ass-onepartner", "family": "assurance", "label": "One accountable partner",
     "sentence": "One accountable partner from brief to final delivery.",
     "templates": None},
    # Team / talent descriptors — "who we'd put on it" (universal)
    {"id": "team-composer", "family": "team", "label": "Composer matched to your genre",
     "sentence": "A composer whose catalog already lives in your world, not a generalist reaching for it.",
     "templates": None},
    {"id": "team-producer", "family": "team", "label": "Hands-on producer",
     "sentence": "A producer who shapes the record end to end, not just a beat-maker.",
     "templates": None},
    {"id": "team-live", "family": "team", "label": "Live instrumentalists",
     "sentence": "Real players where it counts: live strings, horns, guitars, not just samples.",
     "templates": None},
    {"id": "team-mix", "family": "team", "label": "Dedicated mix engineer",
     "sentence": "A dedicated mix engineer so the master translates everywhere, from cinema to phone.",
     "templates": None},
    {"id": "team-editor", "family": "team", "label": "Music editor (to picture)",
     "sentence": "A music editor to conform every cue to your locked edit.",
     "templates": None},
    {"id": "team-vocalist", "family": "team", "label": "Vocalist / topliner",
     "sentence": "A vocalist and topline writer for a memorable, ownable hook.",
     "templates": None},
    {"id": "team-orchestrator", "family": "team", "label": "Orchestrator",
     "sentence": "An orchestrator to give the score real ensemble depth.",
     "templates": None},
    {"id": "team-sounddesign", "family": "team", "label": "Sound designer",
     "sentence": "A sound designer to weave score and texture into one sonic world.",
     "templates": None},
    {"id": "team-lead", "family": "team", "label": "Senior creative lead",
     "sentence": "A senior creative lead steering taste and consistency across every deliverable.",
     "templates": None},
]

# Which descriptor family an editable section pulls from. The section names are
# the keys the template + save routes use for ``support_chips``.
SECTION_FAMILY = {
    "understanding": "craft",
    "aesthetic": "aesthetic",
    "deliverables": "deliverable",
    "assurance": "assurance",
    "team": "team",
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
            "Assumed engagement: feature-film score (~20 to 30 cues, delivered to "
            "picture)."
        ),
    },
    "campaign": {
        "label": "Brand / advertising campaign",
        "deliverables": list(_BASE_DELIVERABLES),
        "rollout": None,   # filled per-deal by _rollout_for (sonic-aware)
        "rights": list(_RIGHTS_SUMMARY),
        "assumptions": (
            "Assumed engagement: brand/advertising campaign (anthem + cutdowns + "
            "social)."
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
            "+ application cues)."
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
            "instrumental + TV track + stems)."
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
            "sound end-to-end, from first sketch to final, polished delivery."
        )
    # Lowercase the lead-in only when it reads as a common-noun phrase (keep proper
    # nouns/acronyms as-is) so "Original :30 brand spot" → "original :30 brand spot".
    lead_in = brief
    if lead_in[:1].isupper() and not lead_in.isupper():
        lead_in = lead_in[0].lower() + lead_in[1:]
    return (
        f"You're looking for {lead_in}, and you need a music partner to shape its "
        f"sound end-to-end, from first idea to finished, ready-to-use delivery."
    )


def _understanding_from_ci(opp: Opportunity, ci_fields: dict, met: bool,
                           *, lede: bool = True, closing: bool = True,
                           open_question_count: int = 0) -> str:
    """The short version, for a client. Delegates to `client_voice.summary_prose`.

    What this used to do was walk the canonical fields and join them with full stops —
    "Instrumentation: … Deliverables as discussed: … Timeline: … Budget: … Approvals: …" —
    which is the field table serialized, printed directly above the field table. The client
    read it twice on the page and a third time in the email. A summary that restates its
    own source is not a summary; it is a second copy with worse formatting.
    """
    from .client_voice import summary_prose
    return summary_prose(ci_fields or {}, met=met, lede=lede, closing=closing,
                         open_question_count=open_question_count)


def _intro_line(met: bool) -> str:
    if met:
        return ("After meeting with your team, we've summarized our understanding of the "
                "campaign below: the creative direction, deliverables, timeline, and "
                "commercial assumptions discussed during discovery. If anything reads wrong, "
                "one reply fixes it.")
    return ("The following reflects our current understanding of your campaign, assembled "
            "from what you've shared so far. If anything reads wrong, one reply fixes it.")


def _build_commercial(opp: Opportunity, estimate: Estimate, terms: List[str],
                      ci_fields: dict, price_low, price_high,
                      deliverables: List[Deliverable]) -> dict:
    """The commercial close — the last section of the brief, not a separate document.
    Pricing from the estimation engine (or the CI budget band), scope/timeline from CI."""
    # Cleaned for a document someone SIGNS: the extractor's own narration
    # ("Deliverables mentioned:") and its hedges ("(needs clarified)") are not contract
    # terms. An uncertainty leaves the term and returns as a caveat — never silently
    # dropped, because that turns a guess into a fact (ADR-0058).
    from .client_voice import contract_phrase, joined_sentence
    scope, scope_caveats = contract_phrase(ci_fields.get("deliverables") or "")
    timeline, timeline_caveats = contract_phrase(ci_fields.get("deadline") or "")
    budget_band = (ci_fields.get("budget_band") or "").strip()
    return {
        "price_low": price_low, "price_high": price_high,
        "budget_band": budget_band,
        "scope": scope or (opp.need or ""),
        "deliverable_count": len(deliverables),
        "timeline": timeline,
        "terms": list(terms),
        "revisions": "Two structured revision rounds are included; more are scoped, never surprised.",
        "deposit": "50% to begin, the balance on final approval, invoiced and never chased.",
        "completion": (joined_sentence("Working back from", timeline) if timeline
                       else "Estimated completion is set at kickoff, working back from your air date."),
        # Surfaced on the document beside the number, not buried in the term itself.
        "caveats": scope_caveats + timeline_caveats,
    }


def build_capabilities_doc(
    opp: Opportunity, qual: QualificationResult, estimate: Estimate, *,
    toggles: dict, call_url: str = "", overrides: Optional[dict] = None,
    ci_view: Optional[dict] = None, met: bool = False,
) -> CapabilitiesDoc:
    """Assemble the document for one opportunity under the given section toggles.

    ``overrides`` is the per-deal ``doc_overrides`` blob (``db.get_doc_overrides``):
    Jon's hand edits applied *on top of* the generated defaults — presentation concerns
    only. ``ci_view`` is ``campaign_intelligence.brief_view(...)``: once Campaign
    Intelligence exists, EVERY section prefers it (ADR-0017); templates fill only the
    slots CI has not. ``met`` switches the document into meeting-summary tone."""
    overrides = overrides or {}
    ci_view = ci_view or {}
    ci_fields: dict = dict(ci_view.get("fields") or {})
    stage = toggles.get("stage", "discovery")
    show_cost = bool(toggles.get("cost"))
    show_terms = bool(toggles.get("terms"))

    price_low = price_high = None
    licence = None
    if show_cost:
        # ADR-0034: the client brief and the Commercial Review are two documents the
        # SAME buyer reads. They quoted different bands — this one reached straight for
        # the estimator while the Review quoted to the disclosed budget, so a client who
        # told us $20–40k was shown $7.2–15.1k here and $20–40k there.
        price_low, price_high = quote_band(
            opp, estimate, ci_fields=ci_fields,
            commercial_overrides=overrides.get("commercial"),
        )
        # The same read the band was built from — one derivation, shown rather than
        # re-derived, so the rail cannot display a licence the price did not use.
        from .pricing import licence_from_ci as _licence_from_ci
        licence = _licence_from_ci(ci_fields)

    terms: List[str] = []
    assumptions: List[str] = []
    if show_terms:
        terms = build_proposal(opp, qual, estimate).terms
    if show_cost:
        # Named beside the figure, not discovered at invoice (ADR-0058). Through
        # `client_voice` because the estimator's own list states our target margin and
        # that the priors are uncalibrated — both true, both internal, and printing
        # either on a document the buyer signs would price the next negotiation for them.
        from .client_voice import client_assumptions
        assumptions = client_assumptions(list(estimate.assumptions or []))

    secondary = [d.label for d in getattr(qual, "secondary_disciplines", [])]

    # Client name + understanding — overridable; understanding is NEVER the scoring
    # summary anymore (§3) — a conservative client-facing restatement is the default.
    client = overrides.get("client") or opp.client
    # Understanding — override wins (a human wrote it); else CI-derived (what the meeting
    # said); else the conservative template restatement. Blanking an override therefore
    # reverts to intelligence, never to stock copy (ADR-0017).
    # The questions a CLIENT should actually be asked, which is not the same list as the
    # engine's open questions (client_voice): our conflict records, our identity
    # reconciliations and truncated fragments are for the operator, and nine separate
    # "no X was mentioned" rights lines are a form nobody agreed to fill in.
    from .client_voice import client_questions, client_risks
    client_asks, deferred_terms_note = client_questions(
        list(ci_view.get("open_questions") or []))
    # An operator override REPLACES the machine's selection for these two lists — the
    # client flagged the summary, and the sections most likely to be the reason are the
    # machine's read of what is risky and what is unresolved. A human who edits one has
    # decided; blanking it reverts to the generated set (same contract as `understanding`).
    if isinstance(overrides.get("open_questions"), list):
        client_asks = [str(q).strip() for q in overrides["open_questions"] if str(q).strip()]
    # Understanding — override wins (a human wrote it); else CI-derived (what the meeting
    # said); else the conservative template restatement. Blanking an override therefore
    # reverts to intelligence, never to stock copy (ADR-0017). No lede and no closing here:
    # this page already carries a "What we heard" heading above it and an intro that ends
    # "one reply fixes it" — printed again, one thought was stated three times before a
    # single fact appeared.
    understanding = (overrides.get("understanding")
                     or _understanding_from_ci(opp, ci_fields, met, lede=False, closing=False,
                                               open_question_count=len(client_asks))
                     or build_understanding(opp))

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
    relevant_uploads = overrides.get("relevant_uploads") or []

    commercial = {}
    if show_cost or show_terms or ci_fields.get("budget_band"):
        commercial = _build_commercial(opp, estimate, terms, ci_fields,
                                       price_low, price_high, deliverables)

    return attach_agreement(CapabilitiesDoc(
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
        # Never ask for the call you have already had. This brief IS the summary of that
        # meeting — closing it with "Request a discovery call · Let's spend 20 minutes
        # discussing your creative direction, timeline, campaign goals" invites a client
        # who just spent that time to book it again, and reads as a form letter that did
        # not notice the conversation. Pre-discovery the CTA is the whole point, so the
        # toggle still governs there.
        show_call=bool(toggles.get("call")) and not met,
        call_url=call_url,
        show_cost=show_cost,
        price_low=price_low,
        price_high=price_high,
        licence=licence,
        show_terms=show_terms,
        terms=terms,
        # Plus anything the CONTRACT TERMS had to set aside — a scope item the call
        # described but did not settle belongs here, named, rather than inside the term
        # wearing a "(needs clarified)" nobody agreed to sign.
        assumptions=assumptions + [c for c in (commercial or {}).get("caveats") or []
                                   if c not in assumptions],
        show_docusign=(stage == "contract"),
        show_delivery=show_delivery,
        campaign_label=opp.need,
        deliverables=deliverables,
        rights_summary=rights_summary,
        rollout=rollout,
        support_chips=support_chips,
        relevant_links=relevant_links,
        relevant_uploads=relevant_uploads,
        delivery_template=template_key,
        delivery_template_label=template["label"],
        delivery_assumptions=delivery_assumptions,
        ci=ci_fields,
        # Through the same filter as the questions. Leaving this one unfiltered meant
        # everything removed from `open_questions` simply came out of `risks` instead
        # (client_voice.client_risks).
        risks=([str(r).strip() for r in overrides["risks"] if str(r).strip()]
               if isinstance(overrides.get("risks"), list)
               else client_risks(list(ci_view.get("risks") or []))),
        open_questions=client_asks,
        deferred_terms_note=deferred_terms_note,
        met=met,
        intro=_intro_line(met),
        commercial=commercial,
    ))
