"""The Outreach-to-Win layer — turn a qualified pursuit into a contact plan.

The sixth mission verb (Identify → Rank → Qualify → Estimate → Prepare →
**Outreach**). Like :mod:`prepare`, it is deliberately **deterministic** (no LLM
cost): it assembles what the engines already produced — the qualification
verdict, the estimate, the strategic value, and the inferred decision-maker —
into a concrete, sequenced outreach plan a human can act on, plus a ready
first-touch message.

This is where the product stops preparing and starts *winning the business*: a
recommended contact, an urgency call, and a touch-by-touch cadence tuned to the
buyer. It does **not** send mail — it drafts and structures the outreach so Jon
(or a producer) can run it and log the result, which feeds the win/loss moat.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote, quote_plus

from .estimation import Estimate
from .models import BuyerType, MusicDiscipline, Opportunity, QualificationResult, ScoredOpportunity
from .strategic import StrategicValue

# --------------------------------------------------------------------------- #
# Per-discipline creative content for the outreach message.
#
# IMPORTANT (company strategy): Chordential does NOT synthesize audio. These are
# recommendations for which *existing portfolio* examples to attach and which
# deliverables to anticipate — not generated audio. They complement the brief's
# vision so the human can attach the right reel.
# --------------------------------------------------------------------------- #
# What to attach: example types tuned to the discipline (the "audio examples").
_RECOMMENDED_EXAMPLES = {
    MusicDiscipline.COMPOSITION: [
        "Original score / theme example",
        "Theme-and-variations example",
        "Multi-channel campaign cut example",
    ],
    MusicDiscipline.SONIC_BRANDING: [
        "Sonic logo example",
        "Brand anthem example",
        "Campaign adaptation example",
    ],
    MusicDiscipline.SOUND_DESIGN: [
        "Signature sound-design example",
        "Motion / UI sound example",
        "Trailer / promo sound example",
    ],
    MusicDiscipline.ARRANGEMENT: [
        "Arrangement / orchestration example",
        "Ensemble recording example",
        "Adaptation / re-arrangement example",
    ],
    MusicDiscipline.SUPERVISION: [
        "Curated placement example",
        "Cleared-track shortlist example",
        "Needle-drop reel example",
    ],
    MusicDiscipline.LICENSING: [
        "Licensing / library reel example",
        "Cleared-track example",
    ],
    MusicDiscipline.MIXING: [
        "Mix-engineering before/after example",
        "Multi-format mix + master example",
        "Stem mix / re-version example",
    ],
}

# Deliverables we'd "anticipate supporting" — the unified-system framing.
_DELIVERABLES = {
    MusicDiscipline.COMPOSITION: [
        "Original composition / score", "Theme development and variations",
        "Campaign cutdowns and alternate lengths",
        "Stems and alternate versions for each channel",
        "Final mixes optimized for delivery",
    ],
    MusicDiscipline.SONIC_BRANDING: [
        "Sonic logo development", "Brand anthem composition",
        "Campaign cutdowns and adaptations",
        "Alternate versions for social, digital, and broadcast",
        "Final mixes optimized for advertising delivery",
    ],
    MusicDiscipline.SOUND_DESIGN: [
        "Signature sound-design palette", "Key-moment scoring and effects",
        "Motion / UI / transition sound", "Alternate versions per channel",
        "Final mixes optimized for delivery",
    ],
    MusicDiscipline.ARRANGEMENT: [
        "Arrangement / orchestration", "Ensemble preparation and recording",
        "Alternate arrangements and lengths", "Stems and alternate mixes",
        "Final mixes optimized for delivery",
    ],
    MusicDiscipline.SUPERVISION: [
        "Music supervision and curation", "Track shortlist and creative direction",
        "Clearance and licensing coordination", "Alternate options per channel",
        "Delivery-ready files",
    ],
    MusicDiscipline.LICENSING: [
        "Track curation and licensing", "Clearance coordination",
        "Alternate options per channel", "Delivery-ready files",
    ],
    MusicDiscipline.MIXING: [
        "Full mix and master", "Instrumental / TV / stem mixes",
        "Loudness-compliant deliverables per channel",
        "Revisions to picture", "Delivery-ready master files",
    ],
}

# Relevant-work bullets for the message ([Project] is the human's to fill in).
_EXAMPLE_WORK = {
    MusicDiscipline.COMPOSITION: [
        "[Project] — Original score for a branded film",
        "[Project] — Campaign music package with cutdowns and alternate versions",
        "[Project] — Original composition supporting a multi-channel launch",
    ],
    MusicDiscipline.SONIC_BRANDING: [
        "[Project] — Sonic identity and brand theme development",
        "[Project] — National campaign music package with cutdowns and alternate versions",
        "[Project] — Original composition supporting a multi-channel brand launch",
    ],
    MusicDiscipline.SOUND_DESIGN: [
        "[Project] — Signature sound-design system for a product launch",
        "[Project] — Motion and UI sound for a digital campaign",
        "[Project] — Trailer / promo sound-design package",
    ],
    MusicDiscipline.ARRANGEMENT: [
        "[Project] — Orchestral arrangement for a brand film",
        "[Project] — Ensemble arrangement and recording",
        "[Project] — Multi-version adaptation across channels",
    ],
    MusicDiscipline.SUPERVISION: [
        "[Project] — Music supervision for a branded campaign",
        "[Project] — Curated, cleared placements across channels",
        "[Project] — Needle-drop reel for a product launch",
    ],
    MusicDiscipline.LICENSING: [
        "[Project] — Licensed music package with clearance",
        "[Project] — Curated cleared-track selection for a campaign",
    ],
    MusicDiscipline.MIXING: [
        "[Project] — Mix and master for a branded campaign",
        "[Project] — Multi-format mixes (broadcast, social, cinema)",
        "[Project] — Stem mixing and re-versions across channels",
    ],
}

_SYSTEM_FRAMING = {
    MusicDiscipline.SONIC_BRANDING: (
        "The combination of a sonic logo, brand anthem, and campaign adaptations "
        "immediately suggests a unified music system rather than a collection of "
        "individual deliverables, and that's where we tend to provide the most value."
    ),
}


def _for_discipline(table, disc):
    """Discipline lookup with a Composition fallback (keeps disqualified safe)."""
    return table.get(disc) or table[MusicDiscipline.COMPOSITION]


def _build_first_touch(opp, qual, contact_name):
    """The first-touch message — a relationship-first proposal that adapts the
    examples, deliverables, and framing to the lead's discipline and brand."""
    disc = qual.discipline
    name = (contact_name or "").strip() or "there"
    examples = _for_discipline(_EXAMPLE_WORK, disc)
    ex_lines = "\n".join(f"• {e}" for e in examples)
    return (
        f"Hi {name},\n\n"
        f"Thank you for the chance to be considered for {opp.need}. Having read the "
        "brief, I'm confident this is squarely the kind of work Chordential is built "
        "for.\n\n"
        "I've included a few examples below that I believe speak directly to the "
        "objectives you've outlined:\n\n"
        f"{ex_lines}\n\n"
        "I also know how much outreach reaches your inbox, and that opening links "
        "from an unfamiliar sender isn't always ideal. If you'd prefer, I'm glad to "
        "set up a short call and walk you through the examples myself — the thinking "
        f"behind each one and how we'd approach {opp.client}'s project specifically. "
        "My aim is simply to make evaluating us as easy and comfortable as possible "
        "for your team.\n\n"
        "Whenever suits, I'd welcome a quick conversation about your goals, timeline, "
        "and what success looks like."
    )


# --------------------------------------------------------------------------- #
# Block composer (Phase 1) — an on/off block model over the generated first-touch
# content, assembled into a personal plain-text email body for Jon's mail client.
#
# Each block is ``{key, label, default_on, text}`` where ``text`` is the generated
# plain-text content (overridable per-deal via the ``compose`` override). The
# default selection is the ``default_on`` keys; the email reads hand-typed and
# minimal (Founder's Advocate ruling) with richness opt-in.
# --------------------------------------------------------------------------- #
# Ordered block keys — Phase 2 consumes this contract (the compose override stores
# {"on": [keys], "text": {key: editedText}}).
COMPOSE_BLOCK_KEYS = [
    "opener", "understanding", "track", "call_offer", "page_link", "signoff",
    "example_more", "credibility", "ps",
]

# The soft tailored-page link → the Phase 2 token-gated first-touch page. The
# token is the page's access control: an unguessable per-opp ``share_token`` so the
# URL is shareable but not enumerable. Falls back to a "preview" stub only when no
# id/token is available (e.g. a bare preview render).
def _page_url(opp_id, token=None) -> str:
    ident = opp_id if opp_id is not None else "preview"
    k = token if (token and str(token).strip()) else str(ident)
    # Absolute URL so the link is clickable in the email (a relative path is dead
    # in a mail client). Uses the configured public domain; chordential.com default.
    base = os.environ.get("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com").rstrip("/")
    return f"{base}/opportunity/{ident}/first-touch?k={k}"


def _first_brief_line(opp) -> str:
    """ONE specific line about their brief, drawn from need/description."""
    need = (getattr(opp, "need", "") or "").strip()
    desc = (getattr(opp, "description", "") or "").strip()
    brief = need or desc
    if not brief:
        return "Thanks for putting your music brief out there — it caught my eye."
    # Keep it short and concrete; a single clause referencing their own words.
    snippet = brief.split("\n", 1)[0].strip()
    if len(snippet) > 160:
        snippet = snippet[:157].rstrip() + "…"
    return f"I read your brief for {snippet} and it's squarely the kind of work I love to take on."


def build_compose_blocks(opp, qual, plan, overrides=None, opp_id=None,
                         contact_name=None, share_token=None):
    """Assemble the ordered list of composer blocks for one opportunity.

    Returns a list of ``{key, label, default_on, text}`` dicts. ``overrides`` is
    the per-deal ``doc_overrides`` blob; a ``compose.text`` entry replaces a
    block's generated text (so Jon's hand edits survive). ``opp_id`` is the DB row
    id used to build the soft page-link URL and ``share_token`` is the opp's
    unguessable token threaded into that URL (so the ``page_link`` block carries the
    real token-gated link); ``contact_name`` is the known recipient name for the
    greeting."""
    overrides = overrides or {}
    compose = overrides.get("compose") or {}
    text_over = compose.get("text") or {}

    from .capabilities import build_understanding

    name = (contact_name or "").strip() or "there"

    examples = list(getattr(plan, "recommended_examples", []) or [])
    best = examples[0] if examples else ""
    more = examples[1:]

    opener = f"Hi {name},\n\n{_first_brief_line(opp)}"
    understanding = build_understanding(opp)
    if best:
        track = f"One piece I think speaks directly to your brief: {best}."
    else:
        track = "I can pull a piece from our portfolio that speaks directly to your brief."
    call_offer = (
        "I can attach a few examples, but I also know opening links from a "
        "stranger isn't always ideal — so if it's easier, I'm happy to walk you "
        "through them on a short call."
    )
    page_url = _page_url(opp_id, share_token)
    # Put the URL on its OWN line: a bare, fully-qualified https URL alone on a
    # line is what mail clients (Gmail / Apple Mail / Outlook) reliably auto-link
    # into a clickable hyperlink — inline-after-a-colon often isn't detected.
    page_link = (
        "If useful, here's a short page I put together for your brief:\n"
        f"{page_url}"
    )
    signoff = "— Jon Shipp · Chordential"
    if more:
        example_more = "A couple more, if helpful:\n" + "\n".join(f"• {e}" for e in more)
    else:
        example_more = "Happy to send a couple more references tuned to your brief."
    credibility = (
        "Everything we deliver is original and cleared, with a fixed scope and a "
        "vetted craft team."
    )
    ps = "P.S. Happy to send a couple more references tuned to your brief if that's useful."

    defaults = {
        "opener": opener,
        "understanding": understanding,
        "track": track,
        "call_offer": call_offer,
        "page_link": page_link,
        "signoff": signoff,
        "example_more": example_more,
        "credibility": credibility,
        "ps": ps,
    }
    labels = {
        "opener": "Warm opener",
        "understanding": "What we understand you need",
        "track": "One relevant track",
        "call_offer": "The call offer",
        "page_link": "Soft tailored-page link",
        "signoff": "Personal sign-off",
        "example_more": "A second / third example",
        "credibility": "Credibility line",
        "ps": "P.S.",
    }
    default_on = {"opener", "understanding", "track", "call_offer", "page_link", "signoff"}

    blocks = []
    for key in COMPOSE_BLOCK_KEYS:
        text = text_over.get(key)
        if not (isinstance(text, str) and text.strip()):
            text = defaults[key]
        blocks.append({
            "key": key,
            "label": labels[key],
            "default_on": key in default_on,
            "text": text,
        })
    return blocks


def compose_selection(blocks, overrides=None):
    """The set of currently-selected (ON) block keys.

    Falls back to each block's ``default_on`` when the ``compose`` override has no
    saved ``on`` list (an un-composed deal renders the minimal defaults)."""
    overrides = overrides or {}
    compose = overrides.get("compose") or {}
    on = compose.get("on")
    if isinstance(on, list):
        saved = {str(k) for k in on}
        return [b["key"] for b in blocks if b["key"] in saved]
    return [b["key"] for b in blocks if b["default_on"]]


def assemble_email(blocks, selected) -> str:
    """Join the SELECTED blocks' text in order, separated by blank lines."""
    sel = set(selected or [])
    parts = [b["text"].strip() for b in blocks if b["key"] in sel and b["text"].strip()]
    return "\n\n".join(parts)


# Per-buyer-type opening channel + the channel used to ask for a live conversation.
_CHANNELS = {
    BuyerType.AGENCY: ("Email, then a LinkedIn touch", "Phone / video call"),
    BuyerType.BRAND: ("Email, then a LinkedIn touch", "Phone / video call"),
    BuyerType.PRODUCTION_COMPANY: ("Email to the production contact", "Phone / video call"),
    BuyerType.GOVERNMENT: ("Formal email / procurement portal", "Scheduled call within the process"),
    BuyerType.EDUCATIONAL: ("Email to the department contact", "Phone / video call"),
    BuyerType.UNKNOWN: ("Email", "Phone / video call"),
}


@dataclass
class OutreachStep:
    """One sequenced touch in the outreach cadence."""

    order: int
    action: str
    channel: str
    timing: str
    talking_point: str


@dataclass
class OutreachPlan:
    target_contact: str
    urgency: str
    primary_channel: str
    steps: List[OutreachStep]
    first_touch_message: str
    email_subject: str = ""
    linkedin_search_url: str = ""
    recommended_examples: List[str] = field(default_factory=list)
    qualified: bool = True
    assumptions: List[str] = field(default_factory=list)

    def render_text(self) -> str:
        """Plain-text outreach plan for copy-paste."""
        lines = [
            "OUTREACH PLAN",
            f"Contact: {self.target_contact}",
            f"Urgency: {self.urgency}",
            f"Primary channel: {self.primary_channel}",
            "",
            "First-touch message:",
            self.first_touch_message,
            "",
            "Cadence:",
        ]
        for s in self.steps:
            lines.append(f"  {s.order}. {s.action} — {s.channel} ({s.timing})")
            lines.append(f"     {s.talking_point}")
        if self.assumptions:
            lines.append("")
            lines.append("Notes:")
            lines += [f"  - {a}" for a in self.assumptions]
        return "\n".join(lines)


def _linkedin_research_url(target: str, company: str, contact_name: str = "") -> str:
    """A LinkedIn people-search deep-link. Searches the known **contact name** when
    we have one (the most precise lead), otherwise falls back to the inferred
    decision-maker role — both scoped to the buyer so the search lands on the right
    person. The ``Likely`` qualifier and any parenthetical buyer-type suffix are
    stripped so the search terms stay clean.
    """
    who = (contact_name or "").strip() or target.replace("Likely ", "").strip()
    company_clean = company.split("(")[0].strip()
    keywords = f"{who} {company_clean}".strip()
    return (
        "https://www.linkedin.com/search/results/people/?keywords="
        + quote_plus(keywords)
    )


def _urgency(qual: QualificationResult, scored: ScoredOpportunity,
             strategic: StrategicValue, opp: Opportunity) -> str:
    tight = opp.turnaround_days is not None and opp.turnaround_days <= 7
    if strategic.tier == "Door-opener":
        return "Reach out within 24h — strategic door-opener; speed wins the relationship."
    if tight:
        return f"Reach out within 24h — tight {opp.turnaround_days}-day turnaround."
    if qual.recommended_action.value == "Pursue":
        return "Reach out within 1–2 business days — qualified, high-fit pursuit."
    return "Reach out within 2–3 business days — warm, non-urgent."


def build_outreach_plan(
    opp: Opportunity,
    qual: QualificationResult,
    scored: ScoredOpportunity,
    estimate: Optional[Estimate],
    strategic: StrategicValue,
    contact_name: Optional[str] = None,
) -> OutreachPlan:
    """Assemble a deterministic outreach plan from existing engine outputs."""
    discipline = qual.discipline
    buyer = opp.buyer_type.value.replace("_", " ")
    target = scored.decision_maker  # inferred role/name from the scoring engine
    primary_channel, call_channel = _CHANNELS.get(
        opp.buyer_type, _CHANNELS[BuyerType.UNKNOWN]
    )

    if estimate is not None:
        price = estimate.suggested_price
        price_phrase = f"~${price:,.0f}"
        cost_range = estimate.cost_range
    else:
        price_phrase = "TBD"
        cost_range = "TBD"

    first_touch_message = _build_first_touch(opp, qual, contact_name)
    # Subject line for the one-click mailto draft (kept short and concrete).
    email_subject = f"{opp.need} — Chordential"
    recommended_examples = _for_discipline(_RECOMMENDED_EXAMPLES, discipline) if qual.qualified else []

    steps: List[OutreachStep] = []
    is_gov = opp.buyer_type is BuyerType.GOVERNMENT
    if is_gov:
        steps.append(OutreachStep(
            1, "Confirm submission requirements", primary_channel,
            "Day 0 — before pitching",
            "Pull the deadline, format, and eligibility from the posting/portal; "
            "note any teaming or registration requirement.",
        ))

    base = [
        OutreachStep(
            0, f"Introductory message to {target}", primary_channel,
            "Day 0 (within the urgency window)",
            f"Lead with the fit: {discipline.label} craft for {buyer} work; "
            "attach one relevant reference.",
        ),
        OutreachStep(
            0, "Value follow-up", "Email",
            "Day 3 (if no reply)",
            "Share a 2–3 piece reel tuned to the brief; restate the fast turnaround.",
        ),
        OutreachStep(
            0, "Offer a scoping call", call_channel,
            "Day 5",
            f"Propose a 15-min call to confirm scope, deliverables, and deadline with {target}.",
        ),
        OutreachStep(
            0, "Send indicative quote / proposal", "Email",
            "After the call (or Day 7)",
            f"Provide the indicative quote ({price_phrase}); close with one clear next step.",
        ),
    ]
    steps += base
    # Re-number sequentially so an optional gov step 1 doesn't collide.
    for i, s in enumerate(steps, start=1):
        s.order = i

    return OutreachPlan(
        target_contact=target,
        urgency=_urgency(qual, scored, strategic, opp),
        primary_channel=primary_channel,
        steps=steps,
        first_touch_message=first_touch_message,
        email_subject=email_subject,
        linkedin_search_url=_linkedin_research_url(target, opp.client, contact_name),
        recommended_examples=recommended_examples,
        qualified=qual.qualified,
        assumptions=[
            "Sequenced deterministically from the qualification, estimate, and "
            "strategic-value engines — no AI generation.",
            f"Contact ({target}) is inferred — confirm the real name/email before sending.",
            "Recommended examples are existing portfolio pieces to attach — "
            "Chordential does not synthesize audio (human craft + Jon-reviewed reels).",
            "LinkedIn link is an auto-built people search — for the named contact "
            "when you've entered one, otherwise the inferred decision-maker at this "
            "buyer — open it to find/verify the person, then paste their profile to lock it in.",
            "Log each touch below; the outcome feeds the win/loss moat.",
        ],
    )


# --------------------------------------------------------------------------- #
# Channel-aware Respond — reply in the platform the lead came from, with a draft.
# --------------------------------------------------------------------------- #
# Email-channel sources (a response goes out as email even without a saved address).
_EMAIL_SOURCES = ("productionhub", "mandy", "email", "staffmeup", "hitmarker", "front_of_house")


def _field(row, key):
    """Read a column from a sqlite Row or a plain dict (None when absent)."""
    try:
        val = row[key]
    except (KeyError, IndexError):
        return None
    return val


def _mailto(to: str, subject: str, body: str) -> str:
    return (f"mailto:{quote(to or '', safe='@')}"
            f"?subject={quote(subject or '', safe='')}"
            f"&body={quote(body or '', safe='')}")


def respond_action(row, plan: OutreachPlan) -> dict:
    """Pick how to respond to a lead *in the channel it came from*, with a prepared
    draft to review and send. Deterministic; sends nothing itself. Returns
    ``{channel, label, url, draft, opens_compose, hint}``.

    This is **separate** from viewing the original post — that link just opens the
    posting; this drafts the actual DM/email reply to the person who listed it.
    """
    source = (_field(row, "source") or "").lower()
    url = _field(row, "url") or ""
    email = _field(row, "contact_email") or ""
    handle = _field(row, "contact_handle") or ""
    linkedin = _field(row, "contact_linkedin") or ""
    need = _field(row, "need") or "your project"
    subject = plan.email_subject or f"Re: {need}"
    draft = plan.first_touch_message or ""

    is_reddit = "reddit" in source or "reddit.com" in url or source.startswith("/r/")
    if is_reddit:
        if handle:
            compose = ("https://www.reddit.com/message/compose/?to=" + quote_plus(handle)
                       + "&subject=" + quote_plus(subject[:100])
                       + "&message=" + quote_plus(draft[:9000]))
            return {
                "channel": "Reddit DM",
                "label": f"Message on Reddit ▸ u/{handle}",
                "url": compose, "draft": draft, "opens_compose": True,
                "hint": "Opens Reddit's message composer to the poster with your note "
                        "prefilled — review and send.",
            }
        return {
            "channel": "Reddit",
            "label": "Reply on Reddit ▸ open post",
            "url": url or "https://www.reddit.com", "draft": draft, "opens_compose": False,
            "hint": "We don't have the poster's username, so open the post and reply/DM "
                    "from there — your draft below is ready to paste.",
        }

    if "linkedin" in source and not email:
        target = linkedin or plan.linkedin_search_url
        return {
            "channel": "LinkedIn",
            "label": "Message on LinkedIn ▸ open profile",
            "url": target, "draft": draft, "opens_compose": False,
            "hint": "Opens the LinkedIn profile/search — paste your draft into a message.",
        }

    if email or any(k in source for k in _EMAIL_SOURCES):
        return {
            "channel": "Email",
            "label": ("Email ▸ " + email) if email else "Compose email",
            "url": _mailto(email, subject, draft), "draft": draft, "opens_compose": True,
            "hint": (f"Opens your mail app to {email} with the pitch prefilled." if email
                     else "Opens your mail app with the pitch prefilled — add the recipient."),
        }

    # Fallback: open the source link if we have one, else draft an email.
    if url:
        return {
            "channel": "Open source",
            "label": "Open listing ▸ respond there",
            "url": url, "draft": draft, "opens_compose": False,
            "hint": "Open the listing and respond through its own channel — draft ready below.",
        }
    return {
        "channel": "Email",
        "label": "Compose email",
        "url": _mailto(email, subject, draft), "draft": draft, "opens_compose": True,
        "hint": "Opens your mail app with the pitch prefilled — add the recipient.",
    }
