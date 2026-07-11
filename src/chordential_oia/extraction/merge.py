"""The merge engine (ADR-0023) — candidate facts → board-shaped contributions.

Deterministic folding of the validated fact set into the EXACT candidate shape the
intake pipeline writes through ``campaign_intelligence.contribute``. The merge never
loses information:

  • evidence      — every supporting quote/speaker/timestamp/artifact rides in value_json
  • corroboration — the same fact from two workers keeps both evidence records
  • alternates    — conflicting values are preserved on the primary's value_json (and
                    validation already raised the flagged confirm_* question)
  • list slots    — deliverables / reference_playlist / milestones union rather than
                    compete: recall-maximizing slots merge into one richer value

The board's own machinery stays the arbiter downstream: contribute() parks disagreements
with human-owned values as conflicts, and every field lands OPEN for the human gate.
"""
from __future__ import annotations

from typing import Dict, List

from .schemas import LIST_KEYS, evidence_record, norm_value, to_candidate

_SPLIT = (",", ";", "\n", "•")


def _items(value: str) -> List[str]:
    parts = [value]
    for sep in _SPLIT:
        parts = [p for chunk in parts for p in chunk.split(sep)]
    return [p.strip(" -\t") for p in parts if p.strip(" -\t")]


def _union(values: List[str]) -> str:
    seen, out = set(), []
    for v in values:
        for item in _items(v):
            key = norm_value(item)
            if key and key not in seen:
                seen.add(key)
                out.append(item)
    return ", ".join(out)


def _all_evidence(fact: Dict) -> List[Dict]:
    ev = [evidence_record(fact)]
    for extra in fact.get("corroborated_by", []) or []:
        ev.append(evidence_record(extra))
    return [e for e in ev if e]


def merge(facts: List[Dict]) -> List[Dict]:
    """Fold the validated fact set into intake candidates, one per board slot."""
    groups: Dict[tuple, List[Dict]] = {}
    order: List[tuple] = []
    for f in facts:
        slot = (f["facet"], f["key"], f["kind"])
        if slot not in groups:
            order.append(slot)
        groups.setdefault(slot, []).append(f)

    out: List[Dict] = []
    for slot in order:
        group = groups[slot]
        _facet, key, _kind = slot
        evidence = [e for g in group for e in _all_evidence(g)]
        if len(group) == 1:
            out.append(to_candidate(group[0], evidence=evidence))
            continue
        if key in LIST_KEYS:
            # List slot: union every worker's finds into one complete value; the best
            # confidence carries (a longer list is corroboration, not conflict).
            primary = dict(max(group, key=lambda g: (g.get("confidence") or 0)))
            primary["value"] = _union([g["value"] for g in group])
            primary["is_concern"] = any(g.get("is_concern") for g in group)
            out.append(to_candidate(primary, evidence=evidence))
            continue
        # Scalar slot: highest confidence (then richest value) is primary; every other
        # distinct value is PRESERVED as an alternate — ambiguity survives the merge.
        ranked = sorted(group, key=lambda g: ((g.get("confidence") or 0),
                                              len(g.get("value") or "")), reverse=True)
        primary, rest = ranked[0], ranked[1:]
        alternates = [r for r in rest
                      if norm_value(r["value"]) != norm_value(primary["value"])]
        cand = to_candidate(primary, alternates=alternates, evidence=evidence)
        cand["is_concern"] = any(g.get("is_concern") for g in group)
        out.append(cand)
    return out
