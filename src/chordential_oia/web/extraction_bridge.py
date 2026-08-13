"""The web-layer bridge into the extraction engine (ADR-0023).

The engine package is pure (strings + dicts). This module is the impure edge: it
assembles EVERY available artifact for a capture from storage — the capture text itself,
meeting metadata, Opportunity Intelligence, the confirmed board snapshot, and every
prior capture's raw evidence (RFPs, briefs, notes, emails) — and returns a callable that
plugs into ``campaign_intake.extract``'s EXISTING LLM seam. The intake pipeline keeps
sole ownership of the write path (capture envelope → contribute → gap questions), so the
orchestrated engine upgrades extraction without touching how anything reaches the board.

Returns None when the engine isn't enabled — intake then behaves exactly as before
(single-prompt seam when a key is present, deterministic heuristics otherwise).
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from ..extraction import engine, providers
from . import db, intake_lanes

# Cost guards: workers each read the full bundle, so the bundle is bounded.
_PRIMARY_CAP = 24000   # the capture being ingested (the star witness)
_ARTIFACT_CAP = 6000   # each supplementary artifact
_PRIOR_CAPTURES = 4    # how many earlier captures ride along as context


class EngineSeam:
    """A callable matching intake's LLM seam ``(text, stance, priors) -> candidates|None``
    that runs the orchestrated engine over the full artifact bundle. Exposes ``report``
    (the structured run report) so the capture envelope can preserve it as evidence."""

    def __init__(self, conn, *, ci_id: Optional[int] = None, opp_id: Optional[int] = None,
                 lane=None, metadata: Optional[dict] = None):
        self._conn = conn
        self._ci_id = ci_id
        self._opp_id = opp_id
        self._lane = lane
        self._metadata = metadata or {}
        self.report: Optional[Dict] = None

    # ── artifact assembly: every worker receives every available artifact ──
    def _artifacts(self, text: str) -> List[Dict]:
        lane = self._lane
        primary_name = (getattr(lane, "label", "") or "Capture") + " (this capture)"
        arts: List[Dict] = [{"name": primary_name,
                             "kind": getattr(lane, "modality", "notes"),
                             "text": (text or "")[:_PRIMARY_CAP]}]
        if self._metadata:
            try:
                meta_text = json.dumps(self._metadata, default=str)[:1500]
                arts.append({"name": "Meeting Metadata", "kind": "metadata",
                             "text": meta_text})
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._opp_id:
                opp = db.get_opportunity(self._conn, self._opp_id)
                if opp is not None:
                    lines = [f"Client: {opp['client']}", f"Need: {opp['need']}"]
                    if opp["description"]:
                        lines.append(f"Description: {opp['description']}")
                    if opp["budget_min"] or opp["budget_max"]:
                        lines.append(f"Known budget: {opp['budget_min']}–{opp['budget_max']}")
                    if opp["contact_name"]:
                        lines.append(f"Contact: {opp['contact_name']} "
                                     f"({opp['contact_role'] or 'role unknown'})")
                    arts.append({"name": "Opportunity Intelligence", "kind": "opportunity",
                                 "text": "\n".join(lines)[:_ARTIFACT_CAP]})
        except Exception:  # noqa: BLE001 — context is a bonus, never a blocker
            pass
        try:
            if self._ci_id:
                rows = db.list_ci_fields(self._conn, self._ci_id)
                lines = [f"{r['facet']}.{r['key']} = {(r['value'] or '')[:160]}"
                         for r in rows if (r["value"] or "").strip()][:60]
                if lines:
                    arts.append({"name": "Campaign Intelligence (already on the board)",
                                 "kind": "board",
                                 "text": "\n".join(lines)[:_ARTIFACT_CAP]})
                caps = self._conn.execute(
                    "SELECT lane, raw_text FROM captures WHERE ci_id=? "
                    "ORDER BY id DESC LIMIT ?", (self._ci_id, _PRIOR_CAPTURES)).fetchall()
                for c in caps:
                    raw = (c["raw_text"] or "").strip()
                    if not raw:
                        continue
                    lane_row = intake_lanes.LANES_BY_KEY.get(c["lane"])
                    label = (lane_row.label if lane_row else (c["lane"] or "Capture"))
                    arts.append({"name": f"Prior capture — {label}", "kind": "capture",
                                 "text": raw[:_ARTIFACT_CAP]})
        except Exception:  # noqa: BLE001
            pass
        return arts

    def __call__(self, text: str, stance: str, priors: str = "") -> Optional[List[Dict]]:
        # The Producer Debrief is the human's subjective read — kinds-only by design
        # (§2bis). Fact-hunting specialists would launder interpretation into fact, so
        # the debrief lane keeps its dedicated single-pass extractor.
        if stance == intake_lanes.DEBRIEF:
            return None
        result = engine.run(self._artifacts(text), priors=priors)
        if result is None:
            return None
        self.report = result.report
        return result.candidates or None


def for_capture(conn, *, ci_id: Optional[int] = None, opp_id: Optional[int] = None,
                campaign_id: Optional[int] = None, lane=None,
                metadata: Optional[dict] = None) -> Optional[EngineSeam]:
    """The intake pipeline's hook: an EngineSeam when the orchestrated engine is enabled
    AND this month's estimated AI spend is under the operator's cap; else None (intake falls
    back to its free extractors, byte-for-byte unchanged). The cap is the hard promise that
    the tool can never quietly run up an API bill — reported live, this exists because a
    silent per-analyze cost drained an operator's credit."""
    del campaign_id  # anchor is the CI; campaign context arrives through it
    if not providers.is_enabled():
        return None
    if spend_over_cap(conn):                 # hard monthly ceiling → fall back to free
        return None
    return EngineSeam(conn, ci_id=ci_id, opp_id=opp_id, lane=lane, metadata=metadata)


def _month() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m")


def spend_over_cap(conn) -> bool:
    """True when this month's estimated AI spend has hit the operator's monthly cap."""
    cap = providers.monthly_cap_usd()
    if cap <= 0:
        return False
    try:
        return db.ai_spend_month(conn, _month())["est_cost"] >= cap
    except Exception:  # noqa: BLE001 — a ledger hiccup must not silently unlock spend
        return False


def record_spend(conn, run_report: Optional[dict]) -> None:
    """Add a completed engine run's estimated cost to this month's ledger (best-effort)."""
    if not run_report:
        return
    # Accounting is advisory, but a swallowed failure here used to abort the whole
    # transaction on Postgres and take the capture down with it (see db.best_effort).
    with db.best_effort(conn, "ai_spend"):
        cost = float(run_report.get("est_cost_usd") or 0)
        if cost <= 0 and not run_report.get("api_calls"):
            return
        db.add_ai_spend(conn, _month(), cost,
                        calls=int(run_report.get("api_calls") or 0),
                        in_tokens=int(run_report.get("input_tokens") or 0),
                        out_tokens=int(run_report.get("output_tokens") or 0))


def spend_status(conn) -> dict:
    """This month's spend + cap for the operator's meter."""
    cap = providers.monthly_cap_usd()
    row = db.ai_spend_month(conn, _month())
    return {"spent": round(row["est_cost"], 2), "cap": cap, "calls": row["calls"],
            "over": (cap > 0 and row["est_cost"] >= cap), "enabled": providers.is_enabled()}
