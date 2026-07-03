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
_TIMELINE = re.compile(
    r"\bby\s+(?:the\s+)?(?:end of\s+)?(?:%s)[a-z]*\.?(?:\s+\d{1,2})?(?:,?\s*\d{4})?"
    r"|\bin\s+\d+\s+(?:days|weeks|months)\b|\bQ[1-4]\b|\b(?:%s)\s+\d{1,2}\b" % (_MONTHS, _MONTHS),
    re.I)
_DELIVERABLES = re.compile(
    r"\b(:15|:30|:60|:90|15s|30s|60s|anthem|cutdown[s]?|social|stems?|sonic logo|"
    r"sting[s]?|bed[s]?|jingle|score|vertical[s]?|9:16|broadcast)\b", re.I)
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
    m = _MONEY.search(text)
    if m:
        out.append(_cand("engagement", "budget_band", "fact", m.group(0).strip(),
                         confidence=70))
    t = _TIMELINE.search(text)
    if t:
        out.append(_cand("engagement", "deadline", "fact", t.group(0).strip(),
                         confidence=65))
    dels = sorted({d.lower() for d in _DELIVERABLES.findall(text)})
    if dels:
        out.append(_cand("engagement", "deliverables", "fact", ", ".join(dels),
                         confidence=60))
    low = text.lower()
    disc = next((label for kw, label in _DISCIPLINES.items() if kw in low), None)
    if disc:
        out.append(_cand("engagement", "primary_discipline", "fact", disc, confidence=55))
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


def extract(text: str, stance: str, *, llm: Optional[LLM] = None) -> List[Dict]:
    """Extract CI-field candidates from a capture. Tries the LLM seam (real extraction
    when configured); falls back to the deterministic heuristic (always available)."""
    if llm is not None:
        try:
            got = llm(text, stance)
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
    candidates = extract(text, stance, llm=llm)
    cap_id = db.insert_capture(
        conn, ci_id=ci_id, campaign_id=campaign_id, opp_id=opp_id, lane=lane.key,
        stance=stance, modality=lane.modality, provenance_source=source, raw_text=text,
        extraction=candidates, artifact_ref=artifact_ref, external_ref=external_ref,
        metadata=metadata, status="ingested", created_by=created_by)
    for c in candidates:
        ci.contribute(conn, ci_id, c["facet"], c["key"], c["value"],
                      kind=c["kind"], source=source, contributed_by=created_by,
                      confidence=c.get("confidence"), is_concern=c.get("is_concern", False),
                      capture_id=cap_id)
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


def ingest(conn, campaign, stance: str, text: str, *, lane_key: str = "",
           modality: str = "notes", created_by: str = "operator",
           llm: Optional[LLM] = None) -> Dict:
    """Run one capture end to end against a CAMPAIGN's CI (workspace path)."""
    lane = intake_lanes.resolve_lane(lane_key=lane_key, stance=stance, modality=modality)
    ci_row = ci.ensure_for_campaign(conn, campaign)
    return _apply_capture(conn, ci_row["id"], lane, text, campaign_id=campaign["id"],
                          opp_id=campaign["opp_id"], created_by=created_by, llm=llm)


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
