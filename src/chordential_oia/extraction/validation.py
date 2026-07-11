"""The validation pass (ADR-0023) — deterministic inspection of extracted facts.

Validation workers never read the transcript: they inspect the fact set. Deterministic
by design (free, offline, testable, and honest — no model gets to silently rewrite what
another model extracted):

  • duplicates    — same (facet, key, kind, normalized value) collapses to one, evidence merged
  • conflicts     — same fact slot, different values → ALL values survive (primary +
                    alternates, resolved later by merge) and a flagged open_question asks
                    the operator to confirm — ambiguity is preserved, never guessed away
  • impossible    — non-positive/absurd money on budget-ish keys, empty values → dropped
  • required-empty→ the intake pipeline's EXISTING gap engine (campaign_intake.gaps →
                    ask_* open_questions) already generates clarification questions
                    against the whole board after write — one implementation, not two.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

from .schemas import LIST_KEYS, norm_value

_MONEYISH_KEY = re.compile(r"budget|price|cost|fee", re.I)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class ValidationReport:
    facts: List[Dict] = field(default_factory=list)      # the surviving fact set
    questions: List[Dict] = field(default_factory=list)  # conflict clarifications
    duplicates_removed: int = 0
    impossible_dropped: int = 0
    conflicts: int = 0


def _impossible(fact: Dict) -> bool:
    """Impossible-value gate. Light on purpose — honesty means dropping only what is
    provably wrong, not second-guessing the source."""
    if not (fact.get("value") or "").strip():
        return True
    if fact["kind"] == "fact" and _MONEYISH_KEY.search(fact["key"] or ""):
        nums = [float(n.replace(",", "")) for n in _NUM.findall(fact["value"])]
        if nums and all(n <= 0 or n > 1_000_000_000 for n in nums):
            return True
    return False


def validate(facts: List[Dict]) -> ValidationReport:
    """Run the deterministic validation workers over an extracted fact set."""
    report = ValidationReport()
    seen: Dict[tuple, Dict] = {}          # exact-duplicate collapse
    by_slot: Dict[tuple, List[Dict]] = {}  # conflict detection per fact slot
    for f in facts:
        if _impossible(f):
            report.impossible_dropped += 1
            continue
        exact = (f["facet"], f["key"], f["kind"], norm_value(f["value"]))
        if exact in seen:
            # Same fact found twice (often by two workers) — keep one, remember the
            # corroboration: the max confidence wins, extra evidence rides along.
            kept = seen[exact]
            kept.setdefault("corroborated_by", []).append(f)
            if (f.get("confidence") or 0) > (kept.get("confidence") or 0):
                kept["confidence"] = f["confidence"]
            report.duplicates_removed += 1
            continue
        seen[exact] = f
        report.facts.append(f)
        by_slot.setdefault((f["facet"], f["key"], f["kind"]), []).append(f)

    # Conflicts: one slot, materially different values. Everything is preserved (merge
    # keeps primary + alternates); validation's job is to make the disagreement LOUD —
    # a flagged open_question the operator answers.
    for (facet, key, kind), group in by_slot.items():
        # List-natured slots (deliverables, references, …) union at merge — two partial
        # lists are corroboration, not a conflict to adjudicate.
        if kind != "fact" or len(group) < 2 or key in LIST_KEYS:
            continue
        values = [g["value"] for g in group]
        norms = [norm_value(v) for v in values]
        distinct = len(set(norms)) > 1 and not any(
            a != b and (a in b or b in a) for a in norms for b in norms)
        if distinct:
            report.conflicts += 1
            label = key.replace("_", " ")
            listed = " / ".join(f"“{v[:80]}”" for v in values[:4])
            report.questions.append({
                "facet": facet, "key": f"confirm_{key}", "kind": "open_question",
                "value": f"The source states conflicting {label} values — confirm which "
                         f"is right: {listed}",
                "confidence": None, "is_concern": True, "worker": "validation",
                "evidence": "", "speaker": "", "timestamp": "", "artifact": "",
            })
    return report
