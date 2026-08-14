"""Campaign Intake (Creative OS) — the capture pipeline.

How everything learned about an engagement enters ChordOS with the least user work.
The user tells ChordOS *what happened* (or *what's their read*); the pipeline extracts,
classifies by epistemic kind, and writes to Campaign Intelligence through the ONE
provenance API — the user never thinks about the object. See docs/campaign-intake-prd.md.

This is Intake-1: the shared ingest→extract→classify→write→gap pipeline with the two
capture stances (objective + Producer Debrief) over pasted text (zero dependencies). The
extractor is a deterministic heuristic baseline with an injectable LLM seam (default
null → heuristic), mirroring the outreach/decision-maker LLM seams (ADR-0005): the
product works with no credentials; a real model upgrades extraction when configured.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Dict, List, Optional

from . import campaign_intelligence as ci, db, intake_lanes

# The two capture STANCES (campaign-intake-prd.md §2bis). Objective capture answers
# "what happened?" (facts); the Producer Debrief answers "what's your read?" (the human
# layer — insight / recommendation / open_question / risk). Canonical home is intake_lanes.
OBJECTIVE = intake_lanes.OBJECTIVE
DEBRIEF = intake_lanes.DEBRIEF
STANCE_SOURCE = {OBJECTIVE: "notes", DEBRIEF: "producer_debrief"}  # back-compat only

# The REQUIRED set that gates follow-up questions (§8): only what the NEXT step (the
# proposal) needs. A gap here → a conversational follow-up, nothing else.
REQUIRED = [
    ("engagement", "budget_band", "What's the budget for the music?"),
    ("engagement", "deadline", "What's the timeline / deadline?"),
    ("engagement", "deliverables", "What deliverables are needed — spot lengths, cutdowns, stems?"),
    ("buyer", "decision_makers", "Who's the decision-maker / final approver?"),
]

LLM = Callable[[str, str], Optional[List[Dict]]]  # (text, stance) -> candidates | None


# --------------------------------------------------------------------------- #
# Extraction — deterministic heuristic baseline (+ an LLM seam).
# --------------------------------------------------------------------------- #
_MONEY = re.compile(
    r"\$?\s?(\d{1,3}(?:,\d{3})+|\d+)\s?(k)?\s?(?:[-–]|to)\s?\$?\s?(\d{1,3}(?:,\d{3})+|\d+)\s?(k)?"
    r"|\$\s?(\d{1,3}(?:,\d{3})+|\d+)\s?(k)?", re.I)
_MONTHS = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
           r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
# "in the next 24 days" was stated plainly on a real discovery call and this missed it:
# the pattern demanded "in 24 days" and the two words between broke it. People do not
# speak in the shape a regex was written in, so the connective words are optional.
_TIMELINE = re.compile(
    r"\bby\s+(?:the\s+)?(?:end of\s+)?(?:%s)[a-z]*\.?(?:\s+\d{1,2})?(?:,?\s*\d{4})?"
    r"|\b(?:in|within|over|inside)\s+(?:the\s+)?(?:next\s+|coming\s+|following\s+)?"
    r"\d+\s+(?:day|week|month)s?\b"
    r"|\b\d+\s+(?:day|week|month)s?\s+from\s+(?:now|today)\b"
    r"|\bby\s+(?:the\s+)?(?:end\s+of\s+)?(?:next\s+)?(?:week|month|quarter)\b"
    r"|\bQ[1-4]\b|\b(?:%s)\s+\d{1,2}\b" % (_MONTHS, _MONTHS),
    re.I)
# "a 60 second cut down" was also stated plainly and also missed: ":60" and "60s" were
# listed but not the way anyone actually says it, and "cutdown" was one word while the
# speaker used two. Spoken lengths and the spaced/hyphenated spellings now count.
_DELIVERABLES = re.compile(
    r"\b(:15|:30|:60|:90|15s|30s|60s"
    r"|\d{1,3}\s*-?\s*(?:second|sec)s?\b"
    r"|anthem|cut\s*-?\s*down[s]?|social|stems?|sonic\s+logo|"
    r"sting[s]?|bed[s]?|jingle|score|vertical[s]?|9:16|broadcast)\b", re.I)
_SPOKEN_LEN = re.compile(r"^(\d{1,3})\s*-?\s*(?:second|sec)s?$", re.I)


def _normalise_deliverable(d: str) -> str:
    """Say a length the way the rest of the system writes it: "60 second" -> ":60"."""
    m = _SPOKEN_LEN.match(d.strip())
    if m:
        return ":%s" % m.group(1)
    return re.sub(r"cut\s*-?\s*down", "cutdown", d.strip(), flags=re.I)


# A budget is very often two numbers and a hedge — "roughly $10,000, we might push to
# $12,000". Reading only the first states a ceiling the buyer did not set.
_STRETCH = re.compile(
    r"\b(push|stretch|up to|as high as|maybe|might|could go|max(?:imum)?)\b", re.I)
_ONE_FIGURE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)\s?(k)?", re.I)


_EXPLICIT_RANGE = re.compile(r"(?:[-–]|\bto\b)\s*\$?\s*\d", re.I)


def _money_band(text: str) -> str:
    """The stated band, when the speaker gave one.

    Two ways a band is stated. Written down it is one phrase — "$18,000 to $24,000" —
    and _MONEY already reads that; SPOKEN it arrives across a sentence break with a
    hedge in between — "roughly $10,000… we might push that to $12,000" — and reading
    only the first figure states a ceiling the buyer never set.
    """
    m = _MONEY.search(text)
    explicit = m.group(0).strip() if m else ""
    if explicit and _EXPLICIT_RANGE.search(explicit):
        return explicit                      # already a band, in one phrase
    figs = [(mm.start(), mm.group(0).strip()) for mm in _ONE_FIGURE.finditer(text)]
    if len(figs) >= 2:
        gap = text[figs[0][0]:figs[1][0]]
        if len(gap) <= 160 and _STRETCH.search(gap) and figs[0][1] != figs[1][1]:
            return "%s to %s" % (figs[0][1], figs[1][1])
    return explicit or (figs[0][1] if figs else "")
# "We want weekly deliverables. We want to check in weekly." Stated twice on a real call
# and dropped both times — there was no canonical slot for a cadence, so nothing looked
# for one. A campaign fact does not need a slot to exist (see the dynamic field on the
# Intelligence card); it only needs somewhere to live, and now it has one.
_CADENCE = re.compile(
    r"\b(?:check[\s-]?ins?|checking\s+in|deliverables?|updates?|reviews?|calls?)\b[^.]{0,40}?"
    r"\b(daily|weekly|bi-?weekly|fortnightly|monthly|every\s+(?:day|week|two\s+weeks|month))\b"
    r"|\b(daily|weekly|bi-?weekly|fortnightly|monthly|every\s+(?:day|week|two\s+weeks|month))\b"
    r"[^.]{0,40}?\b(?:check[\s-]?ins?|checking\s+in|deliverables?|updates?|reviews?|calls?)\b",
    re.I)
_DISCIPLINES = {
    "sound design": "Sound design", "sonic branding": "Sonic branding",
    "music supervision": "Music supervision", "orchestration": "Orchestration",
    "arrangement": "Arrangement", "composition": "Composition", "score": "Composition",
    "mix": "Mix", "mastering": "Mastering",
}
_ROLE = re.compile(
    r"\b(creative director|cd|executive producer|ep|producer|brand manager|"
    r"marketing (?:lead|director|manager)|head of [a-z]+|director)\b", re.I)
_NAME_NEAR_ROLE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*,?\s+(?:the\s+)?(?:%s)"
    % r"creative director|cd|producer|ep|director|brand manager|head of",
    re.I)


def _cand(facet, key, kind, value, *, confidence=None, is_concern=False) -> Dict:
    return {"facet": facet, "key": key, "kind": kind, "value": value.strip(),
            "confidence": confidence, "is_concern": is_concern}


def _extract_objective(text: str) -> List[Dict]:
    """Pull the structured FACTS a note/transcript usually states — budget, timeline,
    deliverables, discipline, decision-maker. Conservative: only what's actually there."""
    out: List[Dict] = []
    band = _money_band(text)
    if band:
        out.append(_cand("engagement", "budget_band", "fact", band, confidence=70))
    else:
        m = _MONEY.search(text)
        if m:
            out.append(_cand("engagement", "budget_band", "fact", m.group(0).strip(),
                             confidence=70))
    t = _TIMELINE.search(text)
    if t:
        out.append(_cand("engagement", "deadline", "fact", t.group(0).strip(),
                         confidence=65))
    dels = sorted({_normalise_deliverable(d).lower() for d in _DELIVERABLES.findall(text)})
    if dels:
        out.append(_cand("engagement", "deliverables", "fact", ", ".join(dels),
                         confidence=60))
    low = text.lower()
    disc = next((label for kw, label in _DISCIPLINES.items() if kw in low), None)
    if disc:
        out.append(_cand("engagement", "primary_discipline", "fact", disc, confidence=55))
    cad = _CADENCE.search(text)
    if cad:
        word = next((g for g in cad.groups() if g), "")
        if word:
            out.append(_cand("engagement", "check_in_cadence", "fact",
                             word.strip().lower(), confidence=55))
    nm = _NAME_NEAR_ROLE.search(text)
    if nm:
        rl = _ROLE.search(text)
        who = nm.group(1) + (f" ({rl.group(0)})" if rl else "")
        out.append(_cand("buyer", "decision_makers", "fact", who, confidence=50))
    return out


_REC_CUES = ("we should", "i'd recommend", "recommend", "lead with", "let's", "i'd ",
             "push back", "don't show", "avoid", "propose", "suggest", "steer")
_Q_CUES = ("unclear", "not sure", "unsure", "don't know", "need to confirm",
           "tbd", "to be confirmed", "open question", "?", "wondering whether")
_RISK_CUES = ("risk", "worried", "worry", "concern", "red flag", "watch out",
              "could go wrong", "nervous")


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip(" -•\t") for p in parts if len(p.strip(" -•\t")) > 3]


def _slug(s: str, n: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", s.lower())[:n]
    return "_".join(words) or "note"


def _extract_debrief(text: str) -> List[Dict]:
    """Classify the producer's read into insight / recommendation / open_question, and
    flag risks. A debrief is subjective by design — nothing here becomes an objective
    fact (§2bis). Each sentence is one item, keyed by a content slug so re-adding the
    same read dedups while distinct reads coexist."""
    out: List[Dict] = []
    for sent in _split_sentences(text):
        low = sent.lower()
        is_risk = any(c in low for c in _RISK_CUES)
        if any(c in low for c in _Q_CUES) or is_risk:
            kind, facet = "open_question", "engagement"
        elif any(low.startswith(c) or c in low for c in _REC_CUES):
            kind, facet = "recommendation", "direction"
        else:
            kind, facet = "insight", "direction"
        out.append(_cand(facet, f"{kind[:3]}_{_slug(sent)}", kind, sent,
                         confidence=None, is_concern=is_risk))
    return out


# The canonical keys the LLM should prefer, so extracted facts land in the labelled slots.
_CANON_KEYS = [k for _f, k, _kind, _l, _p, _o in ci.CANONICAL_FIELDS]


def _build_extraction_prompt(text: str, stance: str, *, priors: str = "") -> str:
    objective = stance != DEBRIEF
    stance_rule = (
        "STANCE = objective ('what happened'): extract everything OBJECTIVELY stated as kind "
        "'fact'. You may ALSO add clearly-supported 'insight' / 'recommendation' / "
        "'open_question', and flag risks."
        if objective else
        "STANCE = debrief ('the producer's read'): this is subjective interpretation — emit "
        "ONLY 'insight' / 'recommendation' / 'open_question'. NEVER emit kind 'fact' (an "
        "inference must not be laundered into objective fact)."
    )
    prior_block = (priors.strip() + "\n\n") if priors and priors.strip() else ""
    return (
        "You are an experienced EXECUTIVE PRODUCER at Chordential, a procurement-grade studio "
        "that sells clearance-certified, human-composed campaign music. You are listening to a "
        "discovery call the way a producer actually listens: as you read, ask yourself — \"If I "
        "walked out of this meeting and had to brief my production team, what would I "
        "immediately write down?\" Capture EVERYTHING that changes how this campaign will be "
        "planned, staffed, priced, scheduled, delivered, approved, or creatively directed. "
        "Optimize for COMPLETENESS, not minimality: silence is more harmful than proposing a "
        "field for review. Err on the side of OVER-capturing. Return a JSON array; each element:\n"
        '{"facet": one of [engagement, buyer, direction, commercial, relationship, outcome, '
        'observed], "key": snake_case, "kind": one of [fact, insight, recommendation, '
        'open_question], "value": faithful content — merge multiple supporting statements into '
        'ONE richer value rather than discarding detail, "confidence": 0-100, "is_concern": '
        "true for a risk/red-flag}.\n\n"
        + prior_block +
        "WHAT TO EXTRACT — attempt EVERY relevant field, not just the easy ones:\n"
        "- engagement: business_objective, campaign_type (feature film / national spot / "
        "social…), budget_band, deadline, critical_deadline, deliverables (list every asset: "
        "score, stems, alt mixes, cutdowns :15/:30/:60, verticals, instrumental, VO/commercial "
        "mix, strings, brass…), distribution (festival / broadcast / streaming), "
        "production_complexity, mix_requirements, asset_package, revision_expectations.\n"
        "- buyer: decision_makers (who signs off), brand_notes, agency_notes, "
        "procurement_requirements, communication_style, success_criteria, client_expectations.\n"
        "- direction: campaign_objective, emotional_arc, reference_playlist, instrumentation, "
        "tone. When the operator's world expands terse language, propose the FULLER read "
        "('warm, cinematic' + 'some brass' -> 'warm, cinematic, with restrained brass').\n"
        "- commercial: rights, term, territory, exclusivity, pricing_signal.\n"
        "- relationship / outcome: anything about the ongoing relationship or success measure.\n"
        "- observed: ANY meaningful fact that doesn't fit a field above yet — a scratchpad of "
        "the producer's working memory (e.g. 'plans a festival premiere', 'wants daily edit "
        "deliveries', 'brass requested', 'budget verbally confirmed'). Use facet 'observed' "
        "with a short snake_case key. Never drop a real observation just because it has no slot.\n\n"
        "RULES:\n"
        f"- {stance_rule}\n"
        "- Extract ONLY what the text supports — never invent. Normalize naturally ('about "
        "twenty thousand dollars' -> '$20,000'; 'by the fall' -> 'Fall'; 'daily video "
        "deliverables' -> a deliverables item).\n"
        "- CONFIDENCE DRIVES ACTION: for anything you can support at MEDIUM or HIGH confidence "
        "(>=50), PROPOSE the fact. For anything genuinely uncertain or merely implied "
        "(<50), do NOT stay silent — instead emit an 'open_question' naming the follow-up to "
        "ask (e.g. 'confirm final mix formats needed'). Every gap becomes a question.\n"
        "- Keep fact (stated) vs insight (inference) vs recommendation (what we should do) vs "
        "open_question (unknown) distinct. Set is_concern=true on risks.\n"
        "- One element per distinct point; merge duplicates into richer values. Return ONLY "
        "the JSON array.\n\n"
        "CAPTURE:\n" + text.strip())


def _loads_array(raw: str):
    """Pull a JSON array out of the model's reply, tolerating code fences / stray prose."""
    s = (raw or "").strip()
    if not s:
        return None
    i, j = s.find("["), s.rfind("]")
    if i != -1 and j != -1 and j > i:
        s = s[i:j + 1]
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def _coerce_candidates(data, stance: str) -> List[Dict]:
    """Validate + normalize the model's JSON into the candidate shape the pipeline writes,
    dropping anything malformed — the LLM proposes, but only well-formed, in-schema items pass."""
    if not isinstance(data, list):
        return []
    out: List[Dict] = []
    for item in data[:150]:
        if not isinstance(item, dict):
            continue
        facet = str(item.get("facet", "")).strip().lower()
        kind = str(item.get("kind", "fact")).strip().lower()
        value = str(item.get("value", "")).strip()
        if facet not in ci.FACETS or kind not in ci.KINDS or not value:
            continue
        if stance == DEBRIEF and kind == "fact":
            continue                                   # debrief is interpretation, never fact
        key = re.sub(r"[^a-z0-9_]+", "_",
                     str(item.get("key", "")).strip().lower()).strip("_") or _slug(value)
        conf = item.get("confidence")
        try:
            conf = max(0, min(100, int(conf))) if conf is not None else None
        except (ValueError, TypeError):
            conf = None
        out.append(_cand(facet, key, kind, value, confidence=conf,
                         is_concern=bool(item.get("is_concern"))))
    return out


def _default_llm(text: str, stance: str, priors: str = "") -> Optional[List[Dict]]:  # pragma: no cover - networked
    """The LLM extractor (ADR-0005 seam): reads a capture as an Executive Producer and returns
    rich, complete CI candidates — every field a producer would write down, plus an Observed-
    Facts scratchpad and follow-up questions for what's uncertain (ADR-0021). ``priors`` is the
    learned "what this producer values" brief. Off unless ANTHROPIC_API_KEY is set (and
    CHORDENTIAL_INTAKE_LLM not disabled); returns None to fall back to the deterministic pass."""
    if os.environ.get("CHORDENTIAL_INTAKE_LLM", "1").strip().lower() in (
            "0", "false", "off", "no", ""):
        return None
    if not (text or "").strip():
        return None
    from . import ai_budget
    ok, _why = ai_budget.may_spend("intake extraction")
    if not ok:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        model = os.environ.get("CHORDENTIAL_INTAKE_MODEL") or "claude-sonnet-5"
        resp = client.messages.create(
            model=model, max_tokens=4000,
            messages=[{"role": "user",
                       "content": _build_extraction_prompt(text, stance, priors=priors)}])
        raw = next((b.text for b in resp.content if b.type == "text"), "")
        return _coerce_candidates(_loads_array(raw), stance) or None
    except Exception:  # noqa: BLE001 — never let the model break capture; fall back
        return None


def extract(text: str, stance: str, *, llm: Optional[LLM] = None, priors: str = "") -> List[Dict]:
    """Extract CI-field candidates from a capture. Uses the LLM seam when configured (an EP's
    complete read of natural conversation, calibrated by learned ``priors``); falls back to the
    deterministic heuristic (always available, offline + free). The LLM proposes — a human
    still disposes downstream, and that disposition trains the priors (ADR-0021)."""
    fn = llm if llm is not None else _default_llm
    try:
        # The injected test/seam llm may accept (text, stance) only; try priors first.
        try:
            got = fn(text, stance, priors)
        except TypeError:
            got = fn(text, stance)
        if got:
            return got
    except Exception:  # noqa: BLE001 — never let the model break capture; fall back
        pass
    return _extract_debrief(text) if stance == DEBRIEF else _extract_objective(text)


# --------------------------------------------------------------------------- #
# Gap analysis + understanding score (§8, §10) — over the REQUIRED set only.
# --------------------------------------------------------------------------- #
def _present_fact_keys(conn, ci_id: int) -> set:
    return {(r["facet"], r["key"]) for r in db.list_ci_fields(conn, ci_id)
            if r["kind"] == "fact" and (r["value"] or "").strip()}


def understanding_pct(conn, ci_id: int) -> int:
    have = _present_fact_keys(conn, ci_id)
    hits = sum(1 for facet, key, _ in REQUIRED if (facet, key) in have)
    return round(hits / len(REQUIRED) * 100) if REQUIRED else 100


def gaps(conn, ci_id: int) -> List[tuple]:
    """The material gaps — required facts not yet present — as (facet, key, question)."""
    have = _present_fact_keys(conn, ci_id)
    return [(f, k, q) for f, k, q in REQUIRED if (f, k) not in have]


# Back-compat surface for callers that still speak in raw modalities; the lane registry
# (intake_lanes) is the real source of truth for how information arrives.
MODALITIES = ("notes", "transcript", "email", "rfp", "document", "voice")
MODALITY_LABEL = {"notes": "Discovery notes", "transcript": "Meeting transcript",
                  "email": "Email thread", "rfp": "RFP", "document": "Client brief",
                  "voice": "Voice memo"}


# --------------------------------------------------------------------------- #
# Ingest — the shared, lane-agnostic pipeline: Capture → extract → write to CI → gap Qs.
# Every intake LANE funnels through here (ADR-0014); only the edge (how the text arrived)
# differs. The Capture is the permanent raw evidence; every field it proposes cites it.
# --------------------------------------------------------------------------- #
def _canonicalise(candidates: List[Dict]) -> List[Dict]:
    """Snap every proposed field name onto the canonical slot it means.

    The engine is STEERED toward the canonical keys by a prompt guide, and on the live
    comprehension call it read every trap correctly and then filed the answers under names
    of its own: $45,000 into "Production Budget", the conditional launch into
    "Seasonality" — while Budget and Timeline sat empty. The estimate, the brief and the
    proposal all read the canonical slots, so a perfect read filed beside them is worth
    nothing. Asking the model more firmly is not a fix; this is.

    A name with no canonical meaning passes through untouched — that is the dynamic field
    working as intended, and it must keep working.
    """
    out = []
    for c in candidates:
        c = dict(c)
        c["key"] = ci.canonical_key(c.get("key", ""))
        out.append(c)
    return out


def _apply_capture(conn, ci_id: int, lane, text: str, *, opp_id=None, campaign_id=None,
                   metadata: Optional[dict] = None, artifact_ref: str = "",
                   external_ref: str = "", created_by: str = "operator",
                   llm: Optional[LLM] = None) -> Dict:
    """Run one capture end to end for a given LANE, against any CI anchor. Writes the
    normalized Capture envelope (permanent evidence), then contributes each extracted
    candidate through the provenance API — stamped with the lane's provenance source and the
    capture_id, so every field can answer 'why did this change?' Machine proposes; a
    human-owned field is never clobbered (a disagreement parks as a conflict); material gaps
    become follow-up open_questions."""
    stance = lane.stance
    source = lane.provenance_source
    # ADR-0021: the extractor is calibrated by what this producer has consistently valued
    # across past campaigns (the learned priors), so it gets better after every deal.
    # Each of the three advisory blocks below runs INSIDE a savepoint. They are all
    # "never block the capture" by intent — but on Postgres a swallowed failure aborts
    # the whole transaction, so `never block` quietly became `always block`, and the
    # insert at the end of this function died with InFailedSqlTransaction naming none of
    # them. The savepoint keeps the swallow honest.
    priors = ""
    with db.best_effort(conn, "priors"):
        from . import producer_learning
        priors = producer_learning.priors_summary(conn)
    # ADR-0023: when the orchestrated extraction engine is enabled, it becomes the seam —
    # ten specialists + validation + recall over EVERY available artifact. An explicitly
    # injected llm (tests/callers) still wins; with the engine off this is None and the
    # single-prompt seam / deterministic heuristics run exactly as before.
    if llm is None:
        with db.best_effort(conn, "engine"):
            from . import extraction_bridge
            llm = extraction_bridge.for_capture(
                conn, ci_id=ci_id, opp_id=opp_id, campaign_id=campaign_id,
                lane=lane, metadata=metadata)
    candidates = _canonicalise(extract(text, stance, llm=llm, priors=priors))
    # Preserve the engine's structured run report on the capture envelope (evidence of
    # HOW the extraction ran: workers, timings, recall rounds, conflicts).
    run_report = getattr(llm, "report", None)
    if run_report:
        metadata = dict(metadata or {})
        metadata["extraction_run"] = run_report
        # Charge this run's estimated cost to the durable monthly ledger, so the app's
        # hard spend cap (extraction_bridge.spend_over_cap) actually bites next time.
        with db.best_effort(conn, "spend"):
            from . import extraction_bridge
            extraction_bridge.record_spend(conn, run_report)
    cap_id = db.insert_capture(
        conn, ci_id=ci_id, campaign_id=campaign_id, opp_id=opp_id, lane=lane.key,
        stance=stance, modality=lane.modality, provenance_source=source, raw_text=text,
        extraction=candidates, artifact_ref=artifact_ref, external_ref=external_ref,
        metadata=metadata, status="ingested", created_by=created_by)
    for c in candidates:
        ci.contribute(conn, ci_id, c["facet"], c["key"], c["value"],
                      kind=c["kind"], source=source, contributed_by=created_by,
                      confidence=c.get("confidence"), is_concern=c.get("is_concern", False),
                      value_json=c.get("value_json"), capture_id=cap_id)
    added_questions = []
    for facet, key, question in gaps(conn, ci_id):
        ci.contribute(conn, ci_id, facet, f"ask_{key}", question,
                      kind="open_question", source="ai", contributed_by="ai",
                      value_json={"facet": facet, "key": key}, capture_id=cap_id)
        added_questions.append(question)
    return {
        "ci_id": ci_id,
        "capture_id": cap_id,
        "lane": lane.key,
        "understanding_pct": understanding_pct(conn, ci_id),
        "added": len(candidates),
        "questions": added_questions,
        "stance": stance,
    }


def reanalyze_capture(conn, capture_id: int, *, created_by: str = "operator") -> Dict:
    """Read a capture we already hold, again — with the engine this time.

    A capture stores its raw text permanently, so when the ten-agent engine could not run
    (no API credit, a rejected key, a rate limit) the transcript is not lost: only the
    READING of it is. The console has told operators to "just re-analyze" since the day
    that error message was written, and there was no way to do it — the only route into
    extraction created a NEW capture from pasted text, which would duplicate the evidence
    and re-file the same call twice.

    This re-reads the text on file and contributes what it finds. The capture row is the
    same row: one call, one piece of evidence, however many times it is read.
    """
    cap = db.get_capture(conn, capture_id)
    if cap is None:
        return {"ok": False, "error": "no such capture"}
    text = (cap["raw_text"] or "").strip()
    if not text:
        return {"ok": False, "error": "this capture has no text to re-read"}
    lane = intake_lanes.LANES_BY_KEY.get(
        cap["lane"] or "", intake_lanes.LANES_BY_KEY["meeting_notes"])
    ci_id = int(cap["ci_id"])
    stance = cap["stance"] or lane.stance
    source = cap["provenance_source"] or lane.provenance_source

    priors = ""
    with db.best_effort(conn, "priors"):
        from . import producer_learning
        priors = producer_learning.priors_summary(conn)
    llm = None
    with db.best_effort(conn, "engine"):
        from . import extraction_bridge
        llm = extraction_bridge.for_capture(
            conn, ci_id=ci_id, opp_id=cap["opp_id"], campaign_id=cap["campaign_id"],
            lane=lane, metadata=_meta(cap))
    candidates = _canonicalise(extract(text, stance, llm=llm, priors=priors))

    run_report = getattr(llm, "report", None)
    meta = dict(_meta(cap) or {})
    if run_report:
        meta["extraction_run"] = run_report
        with db.best_effort(conn, "spend"):
            from . import extraction_bridge
            extraction_bridge.record_spend(conn, run_report)
    db.update_capture(conn, capture_id, extraction=candidates, metadata=meta)

    for c in candidates:
        ci.contribute(conn, ci_id, c["facet"], c["key"], c["value"],
                      kind=c["kind"], source=source, contributed_by=created_by,
                      confidence=c.get("confidence"), is_concern=c.get("is_concern", False),
                      value_json=c.get("value_json"), capture_id=capture_id)
    added_questions = []
    for facet, key, question in gaps(conn, ci_id):
        ci.contribute(conn, ci_id, facet, f"ask_{key}", question,
                      kind="open_question", source="ai", contributed_by="ai",
                      value_json={"facet": facet, "key": key}, capture_id=capture_id)
        added_questions.append(question)
    if cap["opp_id"]:
        sync_ci_to_opportunity(conn, ci_id, int(cap["opp_id"]))
    return {"ok": True, "capture_id": capture_id, "ci_id": ci_id,
            "added": len(candidates), "questions": added_questions,
            "engine": bool(run_report)}


def _meta(cap) -> dict:
    import json as _json
    try:
        return _json.loads(cap["metadata_json"] or "{}")
    except Exception:      # noqa: BLE001
        return {}


def ingest(conn, campaign, stance: str, text: str, *, lane_key: str = "",
           modality: str = "notes", created_by: str = "operator",
           llm: Optional[LLM] = None) -> Dict:
    """Run one capture end to end against a CAMPAIGN's CI (workspace path)."""
    lane = intake_lanes.resolve_lane(lane_key=lane_key, stance=stance, modality=modality)
    ci_row = ci.ensure_for_campaign(conn, campaign)
    return _apply_capture(conn, ci_row["id"], lane, text, campaign_id=campaign["id"],
                          opp_id=campaign["opp_id"], created_by=created_by, llm=llm)


def ingest_transcript(conn, meeting, transcript, *, created_by: str = "capture") -> Dict:
    """Consume a Meeting + a normalized Transcript (ADR-0015) — the boundary where the
    discovery-call lane meets the shared pipeline. Downstream is provider-agnostic: this
    function never sees Zoom or Recall, only a Meeting row and a domain Transcript. Runs the
    discovery_call lane against the meeting's opportunity CI, stamps speaker/duration
    metadata + the provider on the Capture (raw evidence), links the Capture back onto the
    meeting, and returns the review summary. Everything lands proposed — the human reviews.
    """
    opp = db.get_opportunity(conn, meeting["opp_id"]) if meeting["opp_id"] else None
    if opp is None:
        return {"ci_id": None, "capture_id": None, "added": 0, "questions": [],
                "understanding_pct": 0, "lane": intake_lanes.LANES_BY_KEY["discovery_call"].key,
                "stance": OBJECTIVE}
    ci_row = ci.ensure_for_opportunity(conn, opp)
    lane = intake_lanes.LANES_BY_KEY["discovery_call"]
    text = getattr(transcript, "text", "") or ""
    meta = transcript.metadata() if hasattr(transcript, "metadata") else {}
    # APPROVED WORK, and this is the distinction that matters (web/ai_budget.py):
    # a discovery call is scheduled by a person, attended by a person, and recorded
    # because they asked for it to be. Reading it with the ten-agent engine is not the
    # machine deciding to spend — it is finishing the job it was told to do, and it is
    # the whole point of ADR-0023. What must never spend unasked is the SPECULATIVE
    # background work: sweeping every agency for decision-makers, re-scoring the
    # database, drafting outreach nobody requested.
    from . import ai_budget
    with ai_budget.approved_by("discovery call"):
        summary = _apply_capture(
            conn, ci_row["id"], lane, text, opp_id=opp["id"], metadata=meta,
            external_ref=getattr(transcript, "external_ref", ""), created_by=created_by)
    db.update_meeting(conn, meeting["id"], status="ingested",
                      transcript_capture_id=summary["capture_id"])
    sync_ci_to_opportunity(conn, ci_row["id"], opp["id"])
    # The learning loop: harvest buyer objections from the real call into the
    # simulator's objection library as PROPOSED rows (human confirms on the
    # library page). Best-effort — a harvest failure never blocks intake.
    try:
        from . import simulator
        simulator.harvest_objections(conn, text, capture_id=summary["capture_id"])
    except Exception:  # noqa: BLE001
        pass
    return summary


def ingest_opportunity(conn, opp, stance: str, text: str, *, lane_key: str = "",
                       modality: str = "notes", metadata: Optional[dict] = None,
                       artifact_ref: str = "", external_ref: str = "",
                       created_by: str = "operator", llm: Optional[LLM] = None) -> Dict:
    """Run one capture against an OPPORTUNITY's CI (ADR-0013 — the primary intake path, while
    qualifying/pursuing). The lane is resolved from an explicit key or from stance+modality.
    After writing to CI, sync confirmed engagement facts back to the opportunity's own columns
    so every downstream engine recomputes from one source."""
    lane = intake_lanes.resolve_lane(lane_key=lane_key, stance=stance, modality=modality)
    ci_row = ci.ensure_for_opportunity(conn, opp)
    summary = _apply_capture(conn, ci_row["id"], lane, text, opp_id=opp["id"],
                             metadata=metadata, artifact_ref=artifact_ref,
                             external_ref=external_ref, created_by=created_by, llm=llm)
    sync_ci_to_opportunity(conn, ci_row["id"], opp["id"])
    return summary


# --------------------------------------------------------------------------- #
# Review batch — "what did this Capture change, and why?" (derived from stamps).
# The full review SURFACE is a later increment; this is the derivation primitive.
# --------------------------------------------------------------------------- #
def review_batch(conn, capture_id: int) -> Dict:
    """The proposed changes a single Capture produced — its fields (decorated) plus the raw
    evidence, so the operator can review 'why did this change?' before disposing. Fields still
    awaiting a human are the actionable set (machine proposes, human disposes)."""
    cap = db.get_capture(conn, capture_id)
    fields = [ci._decorate(f) for f in db.fields_by_capture(conn, capture_id)]
    return {
        "capture": cap,
        "fields": fields,
        "open": [f for f in fields if f["open"]],
        "counts": {"total": len(fields),
                   "open": sum(1 for f in fields if f["open"])},
    }


# --------------------------------------------------------------------------- #
# Downstream refresh — write confirmed engagement facts back to the opportunity.
# --------------------------------------------------------------------------- #
def _parse_budget(band: str):
    """Pull (min, max) dollars from a budget band string ('$18,000–$24,000', '$20k')."""
    if not band:
        return None, None
    nums = []
    for whole, k in re.findall(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k)?", band, re.I):
        try:
            n = float(whole.replace(",", ""))
        except ValueError:
            continue
        if k:
            n *= 1000
        nums.append(n)
    if not nums:
        return None, None
    return (min(nums), max(nums)) if len(nums) > 1 else (nums[0], nums[0])


def sync_ci_to_opportunity(conn, ci_id: int, opp_id: int) -> None:
    """Reflect the mappable CI engagement facts onto the opportunity's own columns and
    re-evaluate (§18.5). Today: budget_band → budget_min/max (the qualification-fit mover).
    A missing/unparseable fact changes nothing (honesty: no invented numbers)."""
    fields = {(r["facet"], r["key"], r["kind"]): r
              for r in db.list_ci_fields(conn, ci_id)}
    band_row = fields.get(("engagement", "budget_band", "fact"))
    bmin, bmax = _parse_budget(band_row["value"]) if band_row else (None, None)
    if bmin is not None or bmax is not None:
        db.apply_intelligence_to_opportunity(conn, opp_id, budget_min=bmin, budget_max=bmax)


def answer_gap(conn, question_field, answer: str, *, created_by: str = "operator") -> None:
    """Answer a follow-up open_question: contribute the answer as a confirmed FACT on the
    target (facet,key) the question points at, then mark the question answered. This is
    the conversational gap-fill closing the loop from 'I'm missing X' to a real fact."""
    import json as _json
    try:
        target = _json.loads(question_field["value_json"] or "{}")
    except (_json.JSONDecodeError, TypeError):
        target = {}
    facet = target.get("facet") or question_field["facet"]
    key = target.get("key") or question_field["key"]
    ci_id = question_field["ci_id"]
    ci.contribute(conn, ci_id, facet, key, answer.strip(), kind="fact",
                  source="operator", contributed_by=created_by, confirmed=True)
    ci.dispose(conn, question_field, actor=created_by)  # question → answered
