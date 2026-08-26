"""The specialist extraction workers (ADR-0023) — ten domains, one owner each.

Each worker is a WorkerSpec: a charge (what it is responsible for, and NOTHING else), a
facet/kind fence enforced at coercion, and a key guide steering facts into the Board's
EXISTING canonical slots (budget_band, deadline, deliverables, decision_makers, …) so
downstream modules find them where they already look. Workers read every artifact
independently, never talk to each other, never summarize — they only extract facts in
their specialty and return structured JSON (schemas.FACT_SCHEMA).

Adding a domain later = appending one WorkerSpec. Nothing else changes (the engine fans
out over WORKERS; validation/merge are shape-generic).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class WorkerSpec:
    name: str                      # machine name (appears in provenance + logs)
    title: str                     # the specialist's role, spoken in the prompt
    charge: str                    # "responsible ONLY for" — the domain contract
    facets: Tuple[str, ...]        # facet fence (coercion drops anything else)
    default_facet: str
    key_guide: str                 # canonical keys FIRST, then domain vocabulary
    kinds: Tuple[str, ...] = ("fact", "insight", "open_question")
    default_kind: str = "fact"
    concern_default: bool = False  # risk worker: everything lands flagged


WORKERS: List[WorkerSpec] = [
    WorkerSpec(
        name="budget", title="Budget Analyst",
        charge=("campaign budget, music budget, production budget, budget ranges, budget "
                "flexibility, cost concerns, procurement constraints, financial risks, "
                "and currency. Nothing else."),
        facets=("engagement", "commercial", "observed"), default_facet="engagement",
        key_guide=("budget_band (the canonical budget slot — the range/figure quoted for the "
                   "music), music_budget, production_budget, budget_flexibility, "
                   "cost_concerns, procurement_constraints, payment_terms, currency"),
    ),
    WorkerSpec(
        name="timeline", title="Timeline Analyst",
        charge=("launch dates, delivery dates, internal reviews, client reviews, broadcast "
                "dates, production schedule, dependencies, rush indicators, and milestones. "
                "Nothing else."),
        facets=("engagement", "observed"), default_facet="engagement",
        key_guide=("deadline (the canonical timeline slot — the governing air/delivery date), "
                   "launch_date, delivery_dates, "
                   "review_dates (WHEN reviews happen — dates and cadence only. WHO "
                   "approves is never yours: that is decision_makers, and filing an "
                   "approver here hides them inside a schedule), "
                   "broadcast_dates, "
                   "production_schedule, dependencies, milestones, rush_indicators"),
    ),
    WorkerSpec(
        name="deliverables", title="Deliverables Specialist",
        charge=("every deliverable asset: master, instrumental, TV, radio, social, "
                "Instagram, TikTok, YouTube, stems, VO mix, music-only, :30 / :15 / :06 "
                "cutdowns, alternate mixes, language versions, versioning. Search the ENTIRE "
                "transcript; never stop after the first deliverable. Nothing else."),
        facets=("engagement", "observed"), default_facet="engagement",
        key_guide=("deliverables (the canonical slot — one merged list of every asset "
                   "mentioned), plus one deliverable_<slug> fact per distinct asset with its "
                   "spec (length, platform, mix, language)"),
    ),
    WorkerSpec(
        name="stakeholder", title="Stakeholder Analyst",
        charge=("client, brand, agency, decision makers, creative director, producer, music "
                "supervisor, procurement, legal, approvers, roles, hierarchy, and influence. "
                "Nothing else."),
        facets=("buyer", "relationship", "observed"), default_facet="buyer",
        key_guide=(
            "decision_makers (the canonical slot — the PEOPLE who approve the music, by "
            "name and role, and how many times they see it. The person on the call is "
            "often NOT the approver; say who actually signs off), "
            "brand_notes (the canonical slot — what the BRAND is and how it behaves: who "
            "they are, what they make, how long they have done it, what they are careful "
            "about, whether music has let them down before. NOT the brand's name, and "
            "never the agency — a name on its own is not a note), "
            "agency_notes (the canonical slot — how the AGENCY works: who moves paper, "
            "how slow legal is, what to plan around), "
            "stakeholders, approval_chain, procurement_contacts, legal_contacts, "
            "influence_map"),
    ),
    WorkerSpec(
        name="creative", title="Creative Direction Analyst",
        charge=("mood, genre, instrumentation, tempo, artist references, commercial "
                "references, creative adjectives, emotional language, brand voice, desired "
                "feeling, and creative intent. Nothing else."),
        facets=("direction", "observed"), default_facet="direction",
        # THESE THREE ARE THE COMPOSER'S BRIEF. Everything else this worker finds is
        # context; these are what a person has to write music from, and an empty one is a
        # brief with a hole in it that nobody downstream can fill.
        key_guide=("campaign_objective (canonical — what this music is FOR: its job inside "
                   "the film, whether it carries the whole thing or sits under a "
                   "voiceover), emotional_arc "
                   "(canonical — how it should feel across the piece, start to end, "
                   "INCLUDING what it must not become: \"not triumphant\" is direction), "
                   "reference_playlist (canonical — every track/artist/commercial cited, "
                   "and any named as the WRONG direction, which matters more), "
                   "mood, genre, instrumentation, tempo, "
                   "brand_voice, creative_intent, creative_adjectives"),
    ),
    WorkerSpec(
        name="campaign", title="Campaign Analyst",
        charge=("business objective, campaign objective, campaign type, industry, audience, "
                "markets, store count, territories, languages, seasonality, and products. "
                "Nothing else."),
        facets=("engagement", "buyer", "observed"), default_facet="engagement",
        key_guide=("business_objective (canonical — what the brand is trying to achieve), "
                   "campaign_type, industry, audience, markets, store_count, territories, "
                   "languages, seasonality, products"),
    ),
    WorkerSpec(
        name="rights", title="Rights & Licensing Analyst",
        charge=("usage, territory, duration/term, media, licensing, publishing, PRO, union, "
                "buyout, renewals, and exclusivity. Nothing else."),
        facets=("commercial", "observed"), default_facet="commercial",
        key_guide=("usage_rights, territory, term, media, licensing, publishing, pro, "
                   "union_status, buyout, renewals, exclusivity"),
    ),
    WorkerSpec(
        name="technical", title="Technical Specifications Analyst",
        charge=("runtime, frame rate, sample rate, file formats, technical specifications, "
                "loudness, delivery specs, codec, and platform requirements. Nothing else."),
        facets=("engagement", "observed"), default_facet="engagement",
        key_guide=("runtime, frame_rate, sample_rate, file_formats, loudness, "
                   "delivery_specs, codec, platform_requirements, mix_requirements"),
    ),
    WorkerSpec(
        name="opportunity", title="Opportunity Analyst",
        charge=("upsell opportunities, cross-sell opportunities, additional deliverables we "
                "could offer, expansion opportunities, relationship opportunities, and "
                "competitive advantages. Nothing else."),
        facets=("relationship", "outcome", "observed"), default_facet="relationship",
        key_guide=("upsell_<slug>, cross_sell_<slug>, expansion_<slug>, "
                   "relationship_<slug>, competitive_advantage_<slug>"),
        kinds=("recommendation", "insight"), default_kind="recommendation",
    ),
    WorkerSpec(
        name="risk", title="Risk Analyst",
        charge=("contradictions, unknowns, assumptions, missing information, open questions, "
                "production risks, approval risks, scheduling risks, and budget risks. "
                "Nothing else."),
        facets=("engagement", "commercial", "direction", "observed"),
        default_facet="engagement",
        key_guide=("risk_<slug> / assumption_<slug> / contradiction_<slug> / "
                   "unknown_<slug> — one item per distinct risk or unknown"),
        kinds=("open_question", "insight"), default_kind="open_question",
        concern_default=True,
    ),
]

WORKERS_BY_NAME: Dict[str, WorkerSpec] = {w.name: w for w in WORKERS}

# The recall pass reuses the same wire contract with the fences OPEN — its whole job is
# to catch what fell between the specialists' fences.
RECALL_SPEC = WorkerSpec(
    name="recall", title="Recall Auditor",
    charge="every fact of ANY domain that the specialist crew missed.",
    facets=("engagement", "buyer", "direction", "commercial", "relationship", "outcome",
            "observed"),
    default_facet="observed",
    key_guide="any snake_case key; prefer the Board's canonical keys when one fits",
    kinds=("fact", "insight", "recommendation", "open_question"),
)


def _artifact_blocks(artifacts: List[Dict]) -> str:
    """Every worker receives EVERY available artifact, clearly labeled so extracted
    facts can cite their Source Artifact by name."""
    blocks = []
    for a in artifacts:
        name = (a.get("name") or a.get("kind") or "Artifact").strip()
        text = (a.get("text") or "").strip()
        if text:
            blocks.append(f"===== ARTIFACT: {name} =====\n{text}")
    return "\n\n".join(blocks) if blocks else "(no artifacts)"


def build_worker_prompt(spec: WorkerSpec, artifacts: List[Dict], *, priors: str = "") -> str:
    """One specialist's complete instruction: the domain contract, the recall posture
    (search everything, never stop at the first match, return candidates when unsure),
    the Board-aligned key guide, the wire schema, and every artifact."""
    prior_block = f"\nPRODUCER PRIORS (what this operator consistently values):\n{priors.strip()}\n" \
        if priors and priors.strip() else ""
    return (
        f"You are the {spec.title} — one specialist on Chordential's Campaign Intelligence "
        "extraction crew. Chordential is a procurement-grade studio for clearance-certified, "
        "human-composed campaign music; the Campaign Intelligence Board is the canonical "
        "record every downstream module (brief, proposal, estimate, cue sheet, rights, "
        "timeline, CRM) reads. Your pass is the only chance your domain's facts have of "
        "reaching the board — a missed fact is a downstream failure.\n\n"
        f"YOUR DOMAIN — you are responsible ONLY for: {spec.charge}\n"
        "Everything outside this domain belongs to another specialist: ignore it.\n\n"
        "HOW TO WORK:\n"
        "- Read EVERY artifact below, start to finish. Your domain may surface twenty "
        "times, in passing, out of order — keep searching after each find.\n"
        "- Extract every fact in your domain. Never summarize. Never infer what the text "
        "does not support.\n"
        "- If a statement is ambiguous, return MULTIPLE candidate facts at lower "
        "confidence rather than silently choosing one.\n"
        "- If something in your domain is implied but uncertain, emit an 'open_question' "
        "naming the exact follow-up to ask.\n"
        f"{prior_block}\n"
        f"TARGET FIELDS (prefer these snake_case keys so facts land in the board's "
        f"labeled slots): {spec.key_guide}\n\n"
        "Return ONLY a JSON array; each element:\n"
        '{"facet": one of ' + str(list(spec.facets)) + ', "key": "snake_case_field", '
        '"kind": one of ' + str(list(spec.kinds)) + ', "value": "the faithful extracted '
        'content", "confidence": 0-100, "evidence": "shortest verbatim supporting quote", '
        '"speaker": "who said it (or empty)", "timestamp": "position in the source (or '
        'empty)", "artifact": "the artifact name it came from", "is_concern": true only '
        "for a risk/red-flag}\n\n"
        + _artifact_blocks(artifacts)
    )
