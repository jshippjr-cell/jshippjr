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

from . import campaign_intelligence as ci, db

# The two capture STANCES (campaign-intake-prd.md §2bis). Objective capture answers
# "what happened?" (facts); the Producer Debrief answers "what's your read?" (the human
# layer — insight / recommendation / open_question / risk).
OBJECTIVE = "objective"
DEBRIEF = "debrief"
STANCE_SOURCE = {OBJECTIVE: "notes", DEBRIEF: "producer_debrief"}

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


# --------------------------------------------------------------------------- #
# Ingest — the orchestration: create Capture → extract → write to CI → gap Qs.
# --------------------------------------------------------------------------- #
def ingest(conn, campaign, stance: str, text: str, *, modality: str = "notes",
           created_by: str = "operator", llm: Optional[LLM] = None) -> Dict:
    """Run one capture end to end. Creates the immutable Capture, extracts candidates,
    contributes each to Campaign Intelligence (source = the stance's provenance, status =
    open — machine proposes, the human disposes), then raises material gaps as
    open_questions. Returns a summary for the review: understanding %, count added, gaps."""
    ci_row = ci.ensure_for_campaign(conn, campaign)
    ci_id = ci_row["id"]
    stance = stance if stance in (OBJECTIVE, DEBRIEF) else OBJECTIVE
    source = STANCE_SOURCE[stance]
    candidates = extract(text, stance, llm=llm)
    db.insert_capture(conn, ci_id=ci_id, campaign_id=campaign["id"], stance=stance,
                      modality=modality, raw_text=text, extraction=candidates,
                      created_by=created_by)
    for c in candidates:
        ci.contribute(conn, ci_id, c["facet"], c["key"], c["value"],
                      kind=c["kind"], source=source, contributed_by=created_by,
                      confidence=c.get("confidence"), is_concern=c.get("is_concern", False))
    # material gaps → conversational open_questions (only what the proposal needs)
    added_questions = []
    for facet, key, question in gaps(conn, ci_id):
        ci.contribute(conn, ci_id, facet, f"ask_{key}", question,
                      kind="open_question", source="ai", contributed_by="ai",
                      value_json={"facet": facet, "key": key})
        added_questions.append(question)
    return {
        "ci_id": ci_id,
        "understanding_pct": understanding_pct(conn, ci_id),
        "added": len(candidates),
        "questions": added_questions,
        "stance": stance,
    }


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
