"""The recall pass (ADR-0023) — "what facts were missed?"

After the specialists and validation, one auditor receives the original artifacts AND
the complete extracted-fact inventory, with a single charge: find omissions. Anything it
returns goes back through validation, and the engine repeats until a round comes back
empty (or the bounded round budget is spent — a cost guard, not a correctness one:
every fact still enters the board proposed, for the human gate).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .schemas import coerce_fact, norm_value, parse_json_array
from .workers import RECALL_SPEC, _artifact_blocks


def _inventory(facts: List[Dict], limit: int = 400) -> str:
    """The compact already-extracted list the auditor checks the source against."""
    lines = [f"- {f['facet']}.{f['key']} [{f['kind']}] = {f['value'][:160]}"
             for f in facts[:limit]]
    return "\n".join(lines) if lines else "(nothing extracted yet)"


def build_recall_prompt(artifacts: List[Dict], facts: List[Dict]) -> str:
    return (
        "You are the Recall Auditor on Chordential's Campaign Intelligence extraction "
        "crew. A team of specialists has already extracted the facts listed below from "
        "the artifacts. Your ONLY responsibility: what facts were MISSED?\n\n"
        "Aggressively re-read every artifact, start to finish, hunting for omissions — "
        "stated facts, named people, dates, dollar figures, deliverables, rights terms, "
        "technical specs, risks, references — anything a downstream producer would need "
        "that is NOT already in the inventory. Do not restate inventory items. Do not "
        "summarize. Never invent. If nothing was missed, return [].\n\n"
        "ALREADY EXTRACTED (the inventory):\n" + _inventory(facts) + "\n\n"
        "Return ONLY a JSON array of the MISSED facts; each element:\n"
        '{"facet": one of ["engagement","buyer","direction","commercial","relationship",'
        '"outcome","observed"], "key": "snake_case_field", "kind": one of ["fact",'
        '"insight","recommendation","open_question"], "value": "...", "confidence": '
        '0-100, "evidence": "verbatim quote", "speaker": "", "timestamp": "", '
        '"artifact": "artifact name", "is_concern": false}\n\n'
        + _artifact_blocks(artifacts)
    )


def recall_round(provider, artifacts: List[Dict], facts: List[Dict]) -> List[Dict]:
    """One audit round: ask for omissions, coerce, and return only facts that are NEW
    relative to the inventory (exact-normalized comparison — validation dedupes deeper)."""
    raw = provider.complete(build_recall_prompt(artifacts, facts), max_tokens=4000)
    items = parse_json_array(raw or "") or []
    known = {(f["facet"], f["key"], f["kind"], norm_value(f["value"])) for f in facts}
    out: List[Dict] = []
    for item in items[:150]:
        fact = coerce_fact(item, RECALL_SPEC)
        if fact is None:
            continue
        sig = (fact["facet"], fact["key"], fact["kind"], norm_value(fact["value"]))
        if sig in known:
            continue
        known.add(sig)
        out.append(fact)
    return out
