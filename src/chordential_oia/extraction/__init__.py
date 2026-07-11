"""The Campaign Intelligence Extraction Engine (ADR-0023).

An orchestrated, recall-maximizing extraction system that exists solely to populate the
EXISTING Campaign Intelligence Board as completely as possible. Ten specialist workers
each read every artifact independently and extract only their domain; a deterministic
validation pass dedupes/adjudicates; a recall worker hunts omissions until dry; a merge
engine folds candidates into intake-shaped facts. Everything ultimately writes into
Campaign Intelligence through the ONE provenance API (``campaign_intelligence.contribute``)
via the intake pipeline's capture envelope — nothing writes around the board.

This package is PURE domain logic (strings + dicts in, candidates out): no DB, no web.
The web layer (``web/extraction_bridge.py``) assembles artifacts from storage and plugs
the engine into ``campaign_intake``'s existing LLM seam. With no provider configured the
engine steps aside entirely (returns None) and the deterministic heuristics run — the
product works offline and free, and a real model upgrades recall when configured.
"""
from .engine import RunResult, run
from .providers import get_provider, is_enabled
from .schemas import FACT_SCHEMA
from .workers import WORKERS

__all__ = ["run", "RunResult", "WORKERS", "FACT_SCHEMA", "get_provider", "is_enabled"]
