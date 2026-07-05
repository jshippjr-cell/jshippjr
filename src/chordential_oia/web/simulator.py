"""Discovery Call Simulator — practice calls against buyer personas, backed by an
objection library that learns from real calls.

The loop (mirrors the product's spine):
  seed  — the library ships with the 22 objections mined from the five call
          simulations (docs/sales-simulations), status='confirmed'.
  play  — a seller practices against a persona. With ANTHROPIC_API_KEY the buyer
          is an LLM held in character (mode='ai'); without it the simulator runs
          an honest SCRIPTED mode that replays library objections in persona
          voice — no fake AI, per the honesty rule.
  grade — deterministic scorecard at end-of-call, measuring the same playbook
          metrics real calls are held to (talk share, question count, price
          timing, next-step specificity, objection coverage).
  learn — harvest_objections() reads real call transcripts (wired into the
          intake pipeline, best-effort) and proposes NEW objections into the
          library with capture provenance; the human confirms or retires them.
          Machine proposes, Jon disposes — the library gets sharper where real
          buyers actually push.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from . import db

LLM = Callable[..., Optional[object]]

FAMILIES = {
    "trust_incumbency": "Trust & incumbency",
    "cheap_alternatives": "Cheap alternatives",
    "guarantee_skepticism": "Product & guarantee skepticism",
    "delivery_risk": "Delivery & revision risk",
    "money_process": "Money, politics & process",
}

# ---------------------------------------------------------------------------- #
# Personas — the five buyer archetypes from the simulations. `families` orders
# which objection families this buyer reaches for first; `voice` shapes the
# scripted-mode phrasing; `system` seeds the AI-mode character.
# ---------------------------------------------------------------------------- #
PERSONAS: Dict[str, Dict] = {
    "incumbent_ep": {
        "label": "The Incumbent-Loyal EP",
        "who": "Dana Merrick · Executive Producer, mid-size independent agency",
        "situation": ("Delivery week, 20-minute hard stop. Two music houses she's used for "
                      "six years, an Epidemic subscription, CDs experimenting with Suno."),
        "difficulty": "hard",
        "families": ["trust_incumbency", "delivery_risk", "guarantee_skepticism",
                     "cheap_alternatives", "money_process"],
        "voice": "brisk, dry, interrupts jargon, names sales techniques out loud",
        "opening": ("Okay — you've got twenty minutes, and I'll be straight: we have two "
                    "music houses we've trusted for six years and a library subscription "
                    "for the small stuff. So make this count. What do you do that my "
                    "current setup doesn't?"),
        "win_condition": "a small paper-first test, not a sale",
    },
    "burned_brand": {
        "label": "The Clearance-Burned Brand",
        "who": "Marcus Webb · Head of Brand Marketing, DTC fitness apparel",
        "situation": ("A label demand letter over music in influencer posts three weeks ago. "
                      "Legal reviews every post now; the content engine is frozen; Q4 at risk."),
        "difficulty": "medium",
        "families": ["guarantee_skepticism", "cheap_alternatives", "money_process",
                     "delivery_risk", "trust_incumbency"],
        "voice": "stressed, guarded about the incident on a recorded call, allergic to FUD",
        "opening": ("I'll be straight with you — I took this call because the words "
                    "'clearance-certified' were in the subject line. We're... reassessing "
                    "how music gets used across our content. I'm not going into specifics. "
                    "What do you actually sell?"),
        "win_condition": "a scoped meeting including their counsel",
    },
    "ai_curious_vp": {
        "label": "The AI-Curious Cost-Cutter",
        "who": "Priya Sharma · VP Marketing, regional QSR chain",
        "situation": ("Her CMO saw a Suno demo and asked why they pay for music at all. "
                      "She's arbitrating between his cost mandate and her brand instincts."),
        "difficulty": "medium",
        "families": ["cheap_alternatives", "money_process", "guarantee_skepticism",
                     "trust_incumbency", "delivery_risk"],
        "voice": "smart, direct, open-minded but demands numbers; 'give me the real answer'",
        "opening": ("I'll tell you why you got this meeting. My CMO watched an AI generate "
                    "a usable jingle in forty seconds and walked into my office asking why "
                    "we pay for music at all. So I'm doing diligence in both directions. "
                    "You're one direction. Go."),
        "win_condition": "arming her with an honest memo + a lean-tier next step",
    },
    "deadline_producer": {
        "label": "The Brutal-Timeline Producer",
        "who": "Sam Okafor · Senior Producer, production company",
        "situation": ("A licensed track failed clearance ten days before air; client review "
                      "is Friday. Found you through a referral an hour ago. Twelve minutes."),
        "difficulty": "fast",
        "families": ["delivery_risk", "money_process", "guarantee_skepticism"],
        "voice": "transactional, interrupts anything that sounds like marketing, wants clocks",
        "opening": ("I have twelve minutes and a problem. Licensed track died in clearance "
                    "on an insurance spot — publisher refused the category. Airs in ten "
                    "days, client review Friday. Convince me you're not another vendor "
                    "who says 'we hit deadlines.' Go."),
        "win_condition": "a same-day close with the company protected",
    },
    "stonewall_supervisor": {
        "label": "The Polite Stonewall",
        "who": "Elena Ruiz · Music Supervisor, holding-company agency",
        "situation": ("No live brief. 200+ pitches a month, a deep trusted bench, "
                      "procurement that takes 6–8 weeks. Deploys 'send me your reel' early."),
        "difficulty": "expert",
        "families": ["trust_incumbency", "guarantee_skepticism", "cheap_alternatives",
                     "money_process", "delivery_risk"],
        "voice": "friendly, experienced, utterly non-committal; rewards honesty only",
        "opening": ("You get twenty minutes because your email did its homework. But I'll "
                    "save you some discovery: I get two hundred pitches a month and my "
                    "bench is deep and earned. So — what's your differentiator in one "
                    "sentence, and it can't contain 'quality' or 'clearance'?"),
        "win_condition": "a graceful disqualification that earns shortlist position",
    },
}

# ---------------------------------------------------------------------------- #
# Seed library — objection library v1, mined from the five simulations.
# (family, objection, context, response_pattern, result)
# ---------------------------------------------------------------------------- #
SEED_OBJECTIONS = [
    ("trust_incumbency", "Why would I risk a client relationship on an unknown vendor?",
     "Incumbent-loyal buyer with years of music-house trust",
     "Agree they shouldn't — propose the smallest low-blast-radius test; offer a risk-bearing term",
     "partial"),
    ("trust_incumbency", "My music houses answer the phone on Friday night. Will you?",
     "Reliability stress-test from a buyer with deep vendor relationships",
     "Contractual SLA in writing + honest concession of no shared history: 'contractual, not cultural'",
     "partial"),
    ("trust_incumbency", "Who have you actually scored for? Why should I be your guinea pig?",
     "Credentials probe against an early-stage vendor",
     "Full honesty (early-stage, fictional demo brands) + contained-entry framing",
     "yes"),
    ("trust_incumbency", "Send me your reel and I'll keep you in mind.",
     "The polite exit line — usually means never",
     "Do NOT push a meeting. Name the disqualification; ask for two tiny non-meeting things",
     "yes"),
    ("cheap_alternatives", "Stock is $49 a month — why would I pay you thousands?",
     "Pricing the file, not the rights or distinctiveness",
     "Exclusivity (same track scores competitors) + license-scope risk + campaign-spend reframe",
     "partial"),
    ("cheap_alternatives", "We'll just use AI — it's basically free.",
     "Cost pressure plus curiosity; risk not yet priced",
     "Concede output quality on short listens; differentiate on enforceable ownership + audience data; honest memo, never FUD",
     "partial"),
    ("cheap_alternatives", "If I played your track and an AI track blind, would anyone hear the difference?",
     "The blind-test challenge",
     "'On one listen, maybe not.' Shift criterion: compounding sonic identity + disclosure norms",
     "partial"),
    ("cheap_alternatives", "Custom music can't scale to our posting volume.",
     "Volume-model brand assuming custom means one-track-per-post",
     "Clarify real usage (sounds in rotation) then the music-SYSTEM reframe: owned stems = hundreds of cues",
     "partial"),
    ("cheap_alternatives", "Why not just buy a bigger library license? Their enterprise tier exists.",
     "Comparing against a stock-library upgrade",
     "Honest comparison: rental vs owned, aggregation risk ('allegedly' on live suits), exclusivity; concede where libraries win",
     "partial"),
    ("guarantee_skepticism", "Your no-AI guarantee is unenforceable — you can't audit a composer's laptop.",
     "Enforceability challenge on the human-made warranty",
     "Three layers honestly ranked: personal warranties + insured E&O; session-file archive (inspectable, not asserted); concede the limit",
     "yes"),
    ("guarantee_skepticism", "Music-house buyouts are already one-stop — what does 'clearance-certified' actually add?",
     "A knowledgeable supervisor calling the clearance bluff",
     "Never pretend houses can't clear. Differentiate: human-authorship attestation, built-in indemnification, procurement-formatted package",
     "partial"),
    ("guarantee_skepticism", "What is your indemnification actually worth? I've seen Swiss-cheese clauses.",
     "A burned buyer who has read carve-outs before",
     "State coverage AND carve-outs unprompted; admit it can't fix the past; send verbatim language for counsel",
     "yes"),
    ("guarantee_skepticism", "You don't do spec? My houses give me three demos in 48 hours, free.",
     "Spec-work expectation from music-house norms",
     "Hold the no-free-spec line with the reason; offer a matched sampler as alternate proof",
     "partial"),
    ("guarantee_skepticism", "How do I KNOW your certification protects us? The last paperwork was decorative too.",
     "Post-incident distrust of any vendor's paper",
     "Documents over adjectives: no aggregation chain, reviewable chain-of-title, warranty + indemnification + E&O",
     "yes"),
    ("delivery_risk", "What happens when the client hates V1?",
     "Where music vendors die: the revision spiral",
     "Named rounds in the SOW; V1 direction-miss doesn't burn a round; shared revision log. Keep the answer SHORT",
     "yes"),
    ("delivery_risk", "Everyone says they hit deadlines. Walk me through it hour by hour.",
     "Deadline buyer stress-testing reliability",
     "A real clock with times, owners, dependencies, and a NAMED buffer",
     "yes"),
    ("delivery_risk", "A third revision round shouldn't be on me if you missed the brief.",
     "Fair-split negotiation on revision overage",
     "Split by cause with the signed brief as referee: contradicts brief = billed; consistent = free",
     "yes"),
    ("delivery_risk", "What am I out if the whole campaign dies before delivery?",
     "Kill-risk exposure on an expedited job",
     "Kill fee capped at deposit, conditioned on verified campaign death, rights reverting",
     "yes"),
    ("money_process", "What's your best price? Don't pad it.",
     "Anchor-extraction attempt / rush-premium suspicion",
     "Never answer with a number first — explore the comparison; itemize any surcharge against real costs",
     "yes"),
    ("money_process", "What does the cheapest viable engagement look like — the floor, not the pitch?",
     "Budget-constrained buyer who distrusts tier theater",
     "Give the floor first, precisely, and recommend it if it fits",
     "yes"),
    ("money_process", "Our agency handles our creative — why am I talking to you and not them?",
     "Vendor-sprawl worry plus agency politics",
     "Label the politics; position as supply-chain upgrade THROUGH the agency; invite their agency contact",
     "yes"),
    ("money_process", "Procurement requires vendor onboarding and we pay net-90. Non-negotiable.",
     "Paper-process gate at brands/holdcos",
     "Start onboarding in parallel (costs nothing if no); deposit at signature net-30, balance net-90 from delivery",
     "partial"),
]


def seed_objections(conn: sqlite3.Connection) -> int:
    """Idempotently seed the v1 library: insert only what's missing. Seeding never
    bumps times_seen — repetition counts are earned from real calls, not restarts.
    Returns how many rows exist after."""
    existing = {db._norm_objection(r["objection"])
                for r in conn.execute("SELECT objection FROM objections")}
    for family, objection, context, pattern, result in SEED_OBJECTIONS:
        if db._norm_objection(objection) in existing:
            continue
        db.upsert_objection(conn, family=family, objection=objection, context=context,
                            response_pattern=pattern, result=result,
                            source="simulation", status="confirmed")
    return int(conn.execute("SELECT COUNT(*) AS n FROM objections").fetchone()["n"])


# ---------------------------------------------------------------------------- #
# The buyer — scripted mode (deterministic, always available) and AI mode
# (Anthropic seam, ADR-0005: null-by-default, never raises).
# ---------------------------------------------------------------------------- #
def _transcript(row) -> List[Dict]:
    try:
        return json.loads(row["transcript_json"] or "[]")
    except Exception:
        return []


def _used(row) -> List[int]:
    try:
        return json.loads(row["objections_used"] or "[]")
    except Exception:
        return []


def next_scripted_objection(conn: sqlite3.Connection, session) -> Optional[sqlite3.Row]:
    """The next confirmed library objection this persona would raise, weighted by
    the persona's family order then by how often real buyers raise it."""
    persona = PERSONAS.get(session["persona"]) or next(iter(PERSONAS.values()))
    used = set(_used(session))
    rows = [r for r in db.list_objections(conn, status="confirmed") if r["id"] not in used]
    for family in persona["families"]:
        fam = [r for r in rows if r["family"] == family]
        if fam:
            return max(fam, key=lambda r: r["times_seen"])
    return rows[0] if rows else None


def scripted_reply(conn: sqlite3.Connection, session) -> Optional[Dict]:
    """Deterministic buyer turn: the persona raises the next library objection in
    its own voice. Honest about being scripted — no fake conversational glue."""
    row = next_scripted_objection(conn, session)
    if row is None:
        return {"text": ("Alright — I'm out of pushback. Wrap it up: what exactly are you "
                         "proposing we do next, and when?"), "objection_id": None}
    return {"text": row["objection"], "objection_id": int(row["id"])}


def _build_buyer_prompt(session, conn: sqlite3.Connection) -> str:
    persona = PERSONAS.get(session["persona"]) or next(iter(PERSONAS.values()))
    lib = db.list_objections(conn, status="confirmed")
    fam_lines = []
    for fam in persona["families"]:
        objs = [r["objection"] for r in lib if r["family"] == fam][:5]
        if objs:
            fam_lines.append(f"- {FAMILIES.get(fam, fam)}: " + " | ".join(objs))
    turns = _transcript(session)
    history = "\n".join(f"{'BUYER' if t['who'] == 'buyer' else 'SELLER'}: {t['text']}"
                        for t in turns[-16:])
    return f"""You are roleplaying a skeptical buyer on a sales discovery call. Stay in character.

CHARACTER: {persona['who']}. {persona['situation']}
VOICE: {persona['voice']}.
The seller works for Chordential (clearance-certified human-composed original music for
ad agencies/brands, $4k-$90k engagements).

RULES:
- You are the BUYER. Reply with ONLY your next spoken line(s) — no stage directions, no name prefix.
- Be genuinely difficult: interrupt jargon, demand specifics, never be won by one clever line.
- Draw pushback from these real objections when natural (rephrase in your voice):
{chr(10).join(fam_lines)}
- Reward honesty and concrete specifics; punish vague claims and sales techniques.
- Keep replies under 120 words. If the seller earns it over multiple turns, concede
  ground slowly. Your realistic best-case outcome: {persona['win_condition']}.

CALL SO FAR:
{history}

Your next line:"""


def _default_buyer_llm(session, conn: sqlite3.Connection) -> Optional[str]:  # pragma: no cover - networked
    """AI buyer (ADR-0005 seam). Off unless ANTHROPIC_API_KEY is set (and
    CHORDENTIAL_SIM_LLM not disabled); returns None to fall back to scripted."""
    if os.environ.get("CHORDENTIAL_SIM_LLM", "1").strip().lower() in (
            "0", "false", "off", "no", ""):
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        model = os.environ.get("CHORDENTIAL_INTAKE_MODEL") or "claude-sonnet-5"
        resp = client.messages.create(
            model=model, max_tokens=400,
            messages=[{"role": "user", "content": _build_buyer_prompt(session, conn)}])
        text = next((b.text for b in resp.content if b.type == "text"), "").strip()
        return text or None
    except Exception:  # noqa: BLE001 — the simulator must never crash a practice call
        return None


def ai_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and (
        os.environ.get("CHORDENTIAL_SIM_LLM", "1").strip().lower()
        not in ("0", "false", "off", "no", ""))


def buyer_reply(conn: sqlite3.Connection, session, *, llm: Optional[LLM] = None) -> Dict:
    """The buyer's next turn. AI mode tries the seam and falls back to scripted —
    a practice call degrades gracefully, it never dies."""
    if session["mode"] == "ai":
        fn = llm if llm is not None else _default_buyer_llm
        text = fn(session, conn)
        if text:
            return {"text": text, "objection_id": None}
    return scripted_reply(conn, session)


# ---------------------------------------------------------------------------- #
# The grader — deterministic, same metrics the playbook holds real calls to.
# ---------------------------------------------------------------------------- #
_PRICE_RE = re.compile(r"\$\s?\d[\d,]*|price|pricing|budget|cost|investment|fee\b", re.I)
_NEXTSTEP_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|tomorrow|next week)\b.{0,40}"
    r"\b(\d{1,2}(:\d{2})?\s?(am|pm)|noon|morning|afternoon)\b|"
    r"\b(\d{1,2}(:\d{2})?\s?(am|pm))\b.{0,40}\b(monday|tuesday|wednesday|thursday|friday|tomorrow)\b",
    re.I)


def grade(transcript: List[Dict], objections_used: List[int]) -> Dict:
    """Score a practice call against the playbook's measurable rules.
    Every metric is computable from the transcript alone — no model, no opinion."""
    seller = [t["text"] for t in transcript if t.get("who") == "seller"]
    buyer = [t["text"] for t in transcript if t.get("who") == "buyer"]
    seller_words = sum(len(s.split()) for s in seller)
    buyer_words = sum(len(b.split()) for b in buyer)
    total = seller_words + buyer_words
    talk_share = round(seller_words / total * 100) if total else 0

    questions = sum(s.count("?") for s in seller)

    price_turn = next((i for i, s in enumerate(seller) if _PRICE_RE.search(s)), None)
    price_mentioned = price_turn is not None
    # back third = first price mention lands in the final third of the seller's turns
    price_late = bool(price_mentioned and seller and price_turn >= (2 * len(seller)) // 3)

    next_step = any(_NEXTSTEP_RE.search(s) for s in seller[-3:]) if seller else False

    longest = max((len(s.split()) for s in seller), default=0)

    checks = [
        ("Talk share 35–50% (target 43%)", 35 <= talk_share <= 50,
         f"you spoke {talk_share}% of the words"),
        ("11–14 questions (7+ on a short call)", questions >= (11 if len(seller) >= 10 else 7),
         f"{questions} question(s) asked"),
        ("Price discussed on the call", price_mentioned,
         "price/budget came up" if price_mentioned else "price never came up — the playbook says raise it on call one"),
        ("Price raised in the back third", price_late,
         "good timing" if price_late else ("raised too early — establish value first" if price_mentioned else "n/a")),
        ("Specific next step (day + time)", next_step,
         "booked with a specific time" if next_step else "no day+time next step detected in your closing turns"),
        ("No monologues (longest turn ≤ 120 words)", longest <= 120,
         f"longest turn was {longest} words"),
    ]
    score = round(sum(1 for _, ok, _ in checks if ok) / len(checks) * 100)
    return {
        "score": score,
        "talk_share": talk_share,
        "questions": questions,
        "price_mentioned": price_mentioned,
        "price_late": price_late,
        "next_step": next_step,
        "longest_turn_words": longest,
        "objections_faced": len(objections_used),
        "checks": [{"rule": r, "ok": ok, "note": n} for r, ok, n in checks],
    }


# ---------------------------------------------------------------------------- #
# The learning loop — harvest objections from REAL call transcripts.
# ---------------------------------------------------------------------------- #
def _build_harvest_prompt(text: str) -> str:
    fams = ", ".join(FAMILIES.keys())
    return f"""From this sales-call transcript, extract every OBJECTION the prospective buyer raised
(pushback, skepticism, competing alternatives, price resistance, process blockers).

Return a JSON array only. Each item:
{{"family": one of [{fams}],
 "objection": the buyer's objection in one sentence (their meaning, cleaned up),
 "context": when/why it came up (<=15 words),
 "response": how the seller responded in one sentence ("" if they didn't),
 "result": "yes" if the response clearly landed, "partial" if mixed, "no" if it failed or went unanswered}}

Only real objections from the text — no inventions. [] if there are none.

TRANSCRIPT:
{text[:12000]}"""


def _default_harvest_llm(text: str) -> Optional[List[Dict]]:  # pragma: no cover - networked
    if os.environ.get("CHORDENTIAL_SIM_LLM", "1").strip().lower() in (
            "0", "false", "off", "no", ""):
        return None
    if not os.environ.get("ANTHROPIC_API_KEY") or not (text or "").strip():
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        model = os.environ.get("CHORDENTIAL_INTAKE_MODEL") or "claude-sonnet-5"
        resp = client.messages.create(
            model=model, max_tokens=1200,
            messages=[{"role": "user", "content": _build_harvest_prompt(text)}])
        raw = next((b.text for b in resp.content if b.type == "text"), "")
        start, end = raw.find("["), raw.rfind("]")
        if start < 0 or end <= start:
            return None
        data = json.loads(raw[start:end + 1])
        return data if isinstance(data, list) else None
    except Exception:  # noqa: BLE001
        return None


def harvest_objections(conn: sqlite3.Connection, text: str, *,
                       capture_id: Optional[int] = None,
                       llm: Optional[LLM] = None) -> int:
    """Extract objections from a real transcript into the library as PROPOSED rows
    (the human confirms/retires them on the library page). Deterministic fallback
    is honest: without the LLM seam, nothing is extracted — no keyword guessing
    that would launder noise into training data. Returns rows added/bumped."""
    fn = llm if llm is not None else _default_harvest_llm
    items = fn(text) or []
    count = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        objection = str(it.get("objection") or "").strip()
        family = str(it.get("family") or "").strip()
        if not objection or family not in FAMILIES:
            continue
        result = str(it.get("result") or "untested").strip().lower()
        if result not in ("yes", "partial", "no"):
            result = "untested"
        db.upsert_objection(
            conn, family=family, objection=objection[:300],
            context=str(it.get("context") or "")[:200],
            response_pattern=str(it.get("response") or "")[:300],
            result=result, source="transcript", status="proposed",
            capture_id=capture_id)
        count += 1
    return count


# ---------------------------------------------------------------------------- #
# Coaching — the "suggested answer" next to each buyer turn after a call ends.
# The trainee attempts their own answer live; on end-of-call they see, per
# objection, the proven APPROACH (from the library, always) plus a concrete
# model LINE (LLM seam, when configured). Deterministic-first: the approach
# is always available offline; the model line is polish.
# ---------------------------------------------------------------------------- #
_GENERIC_APPROACH = (
    "Pause. Label what you heard (\"sounds like…\"), ask one clarifying question, then "
    "answer with a concrete specific — a number, a document, or a named mechanism, not an "
    "adjective. Concede any true limitation before differentiating.")


def _keyword_overlap(a: str, b: str) -> float:
    aw = set(re.findall(r"[a-z]{4,}", (a or "").lower()))
    bw = set(re.findall(r"[a-z]{4,}", (b or "").lower()))
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / len(aw | bw)


def match_objection(conn: sqlite3.Connection, text: str):
    """Best-effort match of free buyer text (AI mode / the opener) to a confirmed
    library objection, by keyword overlap. Returns the row or None below threshold —
    never a bad match dressed up as a good one."""
    best, score = None, 0.0
    for r in db.list_objections(conn, status="confirmed"):
        s = _keyword_overlap(text, r["objection"])
        if s > score:
            best, score = r, s
    return best if score >= 0.18 else None


def _build_examples_prompt(pairs: List) -> str:
    items = "\n".join(
        f'{i + 1}. Buyer said: "{o}"\n   Proven approach: {a}'
        for i, (o, a) in enumerate(pairs))
    return f"""You are coaching a Chordential seller (clearance-certified, human-composed
original music for ad agencies/brands; $4k-$90k; one signature = master+publishing worldwide
perpetual; stems, cutdowns, rights docs; guaranteed no AI audio).

For each buyer objection below, write ONE model response line the seller could say OUT LOUD —
concrete, honest, under 55 words, in the spirit of the given approach. Use real specifics
(numbers, documents, named mechanisms); never vague adjectives; never fabricate a client story.

{items}

Return a JSON array of exactly {len(pairs)} strings, in order — just the model lines, nothing else."""


def _default_examples_llm(pairs: List) -> Optional[List[str]]:  # pragma: no cover - networked
    """Model example lines for each (objection, approach) pair. Off unless the seam
    is configured; returns None to fall back to approach-only coaching."""
    if os.environ.get("CHORDENTIAL_SIM_LLM", "1").strip().lower() in (
            "0", "false", "off", "no", ""):
        return None
    if not os.environ.get("ANTHROPIC_API_KEY") or not pairs:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        model = os.environ.get("CHORDENTIAL_INTAKE_MODEL") or "claude-sonnet-5"
        resp = client.messages.create(
            model=model, max_tokens=1200,
            messages=[{"role": "user", "content": _build_examples_prompt(pairs)}])
        raw = next((b.text for b in resp.content if b.type == "text"), "")
        start, end = raw.find("["), raw.rfind("]")
        if start < 0 or end <= start:
            return None
        data = json.loads(raw[start:end + 1])
        if isinstance(data, list) and len(data) == len(pairs):
            return [str(x) for x in data]
        return None
    except Exception:  # noqa: BLE001 — coaching must never break the end-of-call view
        return None


def coach_turns(conn: sqlite3.Connection, transcript: List[Dict], *,
                llm: Optional[LLM] = None) -> List[Dict]:
    """For every buyer turn, the suggested answer: the proven approach (matched by
    objection_id, else by keyword, else generic) plus — when the seam is on — a
    concrete model line. One batched LLM call for the whole call, so ending a call
    stays fast. Returns [{idx, approach, family, result, example}, …]."""
    entries = []
    for i, turn in enumerate(transcript):
        if turn.get("who") != "buyer":
            continue
        row = None
        oid = turn.get("objection_id")
        if oid:
            row = db.get_objection(conn, int(oid))
        if row is None:
            row = match_objection(conn, turn.get("text", ""))
        if row is None:
            approach, family, result = _GENERIC_APPROACH, "", ""
        else:
            approach = row["response_pattern"] or _GENERIC_APPROACH
            family = FAMILIES.get(row["family"], row["family"])
            result = row["result"] or ""
        entries.append({"idx": i, "text": turn.get("text", ""),
                        "approach": approach, "family": family, "result": result,
                        "example": ""})
    if entries:
        fn = llm if llm is not None else _default_examples_llm
        examples = fn([(e["text"], e["approach"]) for e in entries])
        if examples and len(examples) == len(entries):
            for e, ex in zip(entries, examples):
                e["example"] = ex
    return entries
