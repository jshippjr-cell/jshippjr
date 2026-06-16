"""Buyer Relationship Intelligence — the Buyer Graph layer.

Deterministic (no LLM): aggregates what we already store — opportunities, their
pipeline status and strategic value, plus the outreach contacts and logged touches
— into a buyer-level *relationship* view. This is the moat asset the strategy names
the north star: the buyer↔Chordential relationship over time, not a single pursuit.

It answers three questions per buyer: where does the relationship stand
(Cold→Client), how strong is it (0-100), and what is the single next best action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

# Relationship stages, coldest → warmest. "Client" means we have won work before.
_STAGE_BASE = {"Cold": 18, "Warming": 42, "Engaged": 62, "Client": 82}
_STAGE_CLASS = {"Cold": "cold", "Warming": "warming", "Engaged": "engaged", "Client": "client"}


@dataclass
class BuyerRelationship:
    stage: str
    score: int  # 0-100 relationship strength
    next_best_action: str
    signals: List[str] = field(default_factory=list)

    @property
    def stage_class(self) -> str:
        return _STAGE_CLASS.get(self.stage, "cold")


def days_since(iso: Optional[str]) -> Optional[int]:
    """Whole days since an ISO timestamp, or None if missing/unparseable."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


def assess_relationship(
    *,
    opps: int,
    qualified: int,
    won: int,
    lost: int,
    open_pursuits: int,
    touches: int,
    last_contacted_days: Optional[int],
    strategic_tier: Optional[str] = None,
) -> BuyerRelationship:
    """Derive the relationship stage, score, signals, and next best action.

    Stage rules (deterministic):
      - **Client**  — we have won at least one job with this buyer.
      - **Engaged** — outreach logged and contact is recent (≤14 days).
      - **Warming** — outreach logged but it has gone quiet (or no recency signal).
      - **Cold**    — no outreach logged yet.
    """
    recent = last_contacted_days is not None and last_contacted_days <= 14
    if won >= 1:
        stage = "Client"
    elif touches > 0 and recent:
        stage = "Engaged"
    elif touches > 0:
        stage = "Warming"
    else:
        stage = "Cold"

    score = _STAGE_BASE[stage]
    score += min(touches, 5) * 2          # engagement effort
    if strategic_tier in ("Door-opener", "High"):
        score += 10                        # strategically valuable relationship
    if open_pursuits > 0:
        score += 5                         # live momentum
    score = max(0, min(100, score))

    signals: List[str] = []
    signals.append(f"{opps} opportunit{'y' if opps == 1 else 'ies'}"
                   + (f", {qualified} qualified" if qualified else ""))
    if won or lost:
        signals.append(f"{won} won · {lost} lost")
    if open_pursuits:
        signals.append(f"{open_pursuits} open pursuit{'s' if open_pursuits != 1 else ''}")
    if touches:
        recency = (
            "today" if last_contacted_days == 0
            else f"{last_contacted_days}d ago" if last_contacted_days is not None
            else "date unknown"
        )
        signals.append(f"{touches} outreach touch{'es' if touches != 1 else ''} · last {recency}")
    else:
        signals.append("no outreach logged yet")
    if strategic_tier in ("Door-opener", "High"):
        signals.append(f"{strategic_tier} strategic value")

    # Single next best action, tuned to the stage and whether anything is live.
    if stage == "Cold":
        action = (
            "Open the top opportunity and send the first outreach touch."
            if open_pursuits or qualified
            else "Qualify a new opportunity for this buyer to start the relationship."
        )
    elif stage == "Warming":
        action = "Follow up — contact was made but has gone quiet; re-engage on the open pursuit."
    elif stage == "Engaged":
        action = "Keep momentum — advance the open pursuit toward a proposal and a call."
    else:  # Client
        action = (
            "Nurture — you've won before; pitch the next project or ask for a referral."
            if open_pursuits == 0
            else "Convert — you have history here and a live pursuit; push it to a win."
        )

    return BuyerRelationship(stage=stage, score=score, next_best_action=action, signals=signals)
