"""Shared JSON schemas + coercion for the extraction engine (ADR-0023).

One fact envelope travels the whole pipeline: worker output → validation → recall →
merge → intake candidate. The envelope EXTENDS the board's candidate shape (facet, key,
kind, value, confidence, is_concern) with per-fact provenance (evidence quote, speaker,
timestamp, source artifact, worker) — the extras ride in ``value_json`` on the CI field
and verbatim in the capture envelope, so the Board's schema is never changed, renamed,
or reorganized.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

# The Board's dimensions — imported values, never redefined (the Board is canonical).
FACETS = ["engagement", "buyer", "direction", "commercial", "relationship", "outcome",
          "observed"]
KINDS = ["fact", "insight", "recommendation", "open_question"]

# The wire contract every worker (and the recall worker) returns: a JSON array of these.
FACT_SCHEMA: Dict = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["key", "value"],
        "properties": {
            "facet": {"enum": FACETS},
            "key": {"type": "string", "description": "snake_case field name"},
            "kind": {"enum": KINDS},
            "value": {"type": "string", "description": "the faithful extracted content"},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "evidence": {"type": "string", "description": "shortest verbatim supporting quote"},
            "speaker": {"type": "string"},
            "timestamp": {"type": "string"},
            "artifact": {"type": "string", "description": "which source artifact"},
            "is_concern": {"type": "boolean"},
        },
    },
}


def slug_key(raw: str, fallback: str = "note") -> str:
    """Normalize a model-proposed field name into the board's snake_case keys."""
    key = re.sub(r"[^a-z0-9_]+", "_", str(raw or "").strip().lower()).strip("_")
    return key or fallback


def parse_json_array(raw: str) -> Optional[list]:
    """Pull a JSON array out of a model reply, tolerating code fences / stray prose
    (same tolerance the intake seam already uses — models decorate; we don't care)."""
    s = (raw or "").strip()
    if not s:
        return None
    i, j = s.find("["), s.rfind("]")
    if i != -1 and j != -1 and j > i:
        s = s[i:j + 1]
    try:
        data = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, list) else None


def coerce_fact(item, spec) -> Optional[Dict]:
    """Validate + normalize ONE raw worker item into the internal fact envelope.

    Domain fencing happens here: a fact outside the worker's allowed facets or kinds is
    DROPPED (each worker owns exactly one domain; another specialist owns the rest).
    Only well-formed, in-schema items pass — the model proposes, the schema disposes."""
    if not isinstance(item, dict):
        return None
    value = str(item.get("value", "")).strip()
    if not value:
        return None
    facet = str(item.get("facet", "")).strip().lower() or spec.default_facet
    kind = str(item.get("kind", "")).strip().lower() or spec.default_kind
    if facet not in spec.facets or kind not in spec.kinds:
        return None
    conf = item.get("confidence")
    try:
        conf = max(0, min(100, int(conf))) if conf is not None else None
    except (ValueError, TypeError):
        conf = None
    return {
        "worker": spec.name,
        "facet": facet,
        "key": slug_key(item.get("key"), fallback=slug_key(value[:40])),
        "kind": kind,
        "value": value[:2000],
        "confidence": conf,
        "is_concern": bool(item.get("is_concern")) or spec.concern_default,
        "evidence": str(item.get("evidence", "")).strip()[:400],
        "speaker": str(item.get("speaker", "")).strip()[:80],
        "timestamp": str(item.get("timestamp", "")).strip()[:40],
        "artifact": str(item.get("artifact", "")).strip()[:120],
    }


def evidence_record(fact: Dict) -> Dict:
    """The per-fact provenance record preserved through merge into ``value_json``."""
    return {k: v for k, v in (
        ("quote", fact.get("evidence", "")), ("speaker", fact.get("speaker", "")),
        ("t", fact.get("timestamp", "")), ("artifact", fact.get("artifact", "")),
        ("worker", fact.get("worker", "")), ("confidence", fact.get("confidence")),
    ) if v not in ("", None)}


def to_candidate(fact: Dict, *, alternates: Optional[List[Dict]] = None,
                 evidence: Optional[List[Dict]] = None) -> Dict:
    """Fold a merged fact into the EXACT candidate shape the intake pipeline already
    writes through ``campaign_intelligence.contribute`` — plus ``value_json`` carrying
    evidence + preserved alternates (ambiguity is kept, never silently resolved)."""
    vj: Dict = {}
    ev = evidence if evidence is not None else [evidence_record(fact)]
    ev = [e for e in ev if e]
    if ev:
        vj["evidence"] = ev[:6]
    if alternates:
        vj["alternates"] = [{"value": a["value"], **evidence_record(a)}
                            for a in alternates][:4]
    return {
        "facet": fact["facet"], "key": fact["key"], "kind": fact["kind"],
        "value": fact["value"], "confidence": fact.get("confidence"),
        "is_concern": bool(fact.get("is_concern")),
        **({"value_json": vj} if vj else {}),
    }


def norm_value(value: str) -> str:
    """Comparison form of a value (dedupe): lowercase, whitespace collapsed."""
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


# Canonical slots whose value is a LIST by nature: different finds are partial views of
# one whole — merge UNIONS them (recall-maximizing) and validation treats disagreement
# as corroboration, not conflict.
LIST_KEYS = {"deliverables", "reference_playlist", "milestones", "markets",
             "territories", "languages", "file_formats", "delivery_specs",
             "review_dates", "delivery_dates", "broadcast_dates", "creative_adjectives"}
