"""The extraction orchestrator (ADR-0023) — fan out, validate, recall until dry, merge.

Execution flow for one capture:

    artifacts ─┬─▶ budget ──────┐
               ├─▶ timeline ────┤        ┌──────────────┐    ┌────────────┐
               ├─▶ deliverables ┤        │  validation  │    │   merge    │   intake
               ├─▶ … (10) ──────┼──facts─▶ dedupe/      ├──▶ │  evidence/ ├─▶ candidates
               └─▶ (parallel)───┘        │ conflicts    │    │ alternates │   (contribute)
                        ▲                └──────┬───────┘    └────────────┘
                        │        recall: "what was missed?"  │
                        └───────────────(loop until dry)◀────┘

Every worker runs independently over every artifact (a thread pool — the work is
network-bound). A failed worker yields nothing and is recorded in the run report; it
never blocks the capture (error recovery = degrade, log, continue: the raw transcript is
permanent evidence and extraction can always re-run). The engine returns intake-shaped
candidates plus a structured run report; the WRITE stays with the intake pipeline —
extraction never touches the board (or any downstream document) directly.
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import merge as merge_mod
from . import providers, recall, validation
from .schemas import coerce_fact, parse_json_array
from .workers import WORKERS, build_worker_prompt

log = logging.getLogger("chordential.extraction")


@dataclass
class RunResult:
    candidates: List[Dict] = field(default_factory=list)
    report: Dict = field(default_factory=dict)


def _run_worker(provider, spec, artifacts, priors) -> Dict:
    """One specialist, end to end: prompt → model → parse → coerce (domain fence).
    Returns {facts, ms, error} — errors are data here, not exceptions."""
    started = time.monotonic()
    try:
        raw = provider.complete(build_worker_prompt(spec, artifacts, priors=priors))
        items = parse_json_array(raw or "")
        if items is None:
            return {"name": spec.name, "facts": [], "error": "no_output",
                    "ms": int((time.monotonic() - started) * 1000)}
        facts = [f for f in (coerce_fact(i, spec) for i in items[:150]) if f]
        return {"name": spec.name, "facts": facts, "error": "",
                "ms": int((time.monotonic() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001 — a worker failure never breaks the capture
        return {"name": spec.name, "facts": [], "error": f"{type(exc).__name__}",
                "ms": int((time.monotonic() - started) * 1000)}


def run(artifacts: List[Dict], *, priors: str = "", provider=None,
        recall_rounds: Optional[int] = None,
        max_workers: Optional[int] = None) -> Optional[RunResult]:
    """Run the full orchestrated extraction over an artifact bundle.

    Returns None when no provider is configured — the caller (the intake seam) falls
    back to its existing extractors, so the engine is a pure upgrade, never a gate."""
    provider = provider if provider is not None else providers.get_provider()
    if not getattr(provider, "available", False):
        return None
    if not any((a.get("text") or "").strip() for a in artifacts or []):
        return None
    rounds = recall_rounds if recall_rounds is not None else max(
        0, int(os.environ.get("CHORDENTIAL_EXTRACTION_RECALL_ROUNDS", "2") or 0))
    pool_size = max_workers or min(
        len(WORKERS), int(os.environ.get("CHORDENTIAL_EXTRACTION_WORKERS", "6") or 6))

    started = time.monotonic()
    worker_reports: List[Dict] = []
    facts: List[Dict] = []
    # ── Fan-out: every specialist reads every artifact, independently, in parallel ──
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        futures = [pool.submit(_run_worker, provider, spec, artifacts, priors)
                   for spec in WORKERS]
        for fut in as_completed(futures):
            rep = fut.result()
            worker_reports.append(rep)
            facts.extend(rep.pop("facts"))
            if rep["error"]:
                log.warning("extraction worker %s failed: %s", rep["name"], rep["error"])

    # ── Validation: dedupe, conflicts (preserved + flagged), impossible values ──
    report = validation.validate(facts)
    facts = report.facts
    questions = list(report.questions)

    # ── Recall loop: hunt omissions until a round comes back dry (bounded) ──
    recall_added = 0
    rounds_run = 0
    for _ in range(rounds):
        rounds_run += 1
        try:
            new = recall.recall_round(provider, artifacts, facts + questions)
        except Exception:  # noqa: BLE001 — recall is a bonus pass, never a blocker
            new = []
        if not new:
            break
        revalidated = validation.validate(facts + new)
        recall_added += max(0, len(revalidated.facts) - len(facts))
        facts = revalidated.facts
        for q in revalidated.questions:
            if q not in questions:
                questions.append(q)

    # ── Merge: board-shaped candidates, evidence + alternates preserved ──
    candidates = merge_mod.merge(facts) + merge_mod.merge(questions)
    # If every worker came back empty AND the provider recorded a failure, the model call
    # itself failed — surface the real reason (e.g. a bad model id, an auth error) so a
    # silent fall-back-to-baseline is DIAGNOSABLE on the Evidence page, not a mystery.
    provider_error = ""
    if not facts and all(w["error"] for w in worker_reports):
        provider_error = getattr(provider, "last_error", "") or "no output from the model"
    run_report = {
        "engine": "extraction-v1", "provider": getattr(provider, "name", "?"),
        "model": getattr(provider, "model", ""), "provider_error": provider_error,
        "workers": sorted(worker_reports, key=lambda r: r["name"]),
        "facts": len(facts), "candidates": len(candidates),
        "duplicates_removed": report.duplicates_removed,
        "conflicts": report.conflicts,
        "impossible_dropped": report.impossible_dropped,
        "recall_rounds": rounds_run, "recall_added": recall_added,
        "ms": int((time.monotonic() - started) * 1000),
    }
    log.info("extraction run: %s candidates in %sms (%s workers, %s recall rounds)",
             run_report["candidates"], run_report["ms"], len(worker_reports), rounds_run)
    return RunResult(candidates=candidates, report=run_report)
