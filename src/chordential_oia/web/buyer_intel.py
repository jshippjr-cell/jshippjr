"""Buyer Relationship Intelligence — the ONE relationship layer.

Deterministic (no LLM): aggregates what we already store — opportunities, their
pipeline status and strategic value, plus every logged touch on either side — into an
organisation-level *relationship* view. This is the moat asset the strategy names the
north star: the buyer↔Chordential relationship over time, not a single pursuit.

It answers three questions per organisation: where does the relationship stand
(Cold→Client), is it still alive (dormant or not), and what is the single next action.

**Why this file is now the only one that answers them.** There were two engines over
the same companies, each blind to half the evidence:

* the Buyer Graph (`/buyers`) derived Cold / Warming / Engaged / Client from
  `opportunities` and `outreach_events` — so it knew we had been PAID by someone, but
  not that a relationship had gone quiet;
* Relationship Management (`/relationships`) derived Cold / Warm Prospect / Active /
  Dormant from `agency_outreach` — so it knew about dormancy, and **could not return
  "Client" at all**, no matter how much work we had won and delivered. "Client" was in
  its vocabulary and unreachable in its code; only a human override could set it.

Two vocabularies, two answers, one company — and until ADR-0056 gave organisations a
canonical id there was not even a join to notice it with. So: ONE stage, over ALL the
evidence, reported by both surfaces.

The two things the merged vocabulary had to keep, because each engine had exactly one
of them:

    stage    Cold → Warm → Engaged → Client   "how far has this relationship got"
    dormant  a flag, not a stage               "is it alive right now"

Dormancy is deliberately NOT a fifth stage. A client who has gone quiet is still a
client, and that pair — *we have been paid by these people and have not spoken in eight
months* — is the single most actionable fact the old split could not express.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Relationship stages, coldest → warmest. "Client" means we have won work before.
STAGES = ("Cold", "Warm", "Engaged", "Client")
_STAGE_BASE = {"Cold": 18, "Warm": 42, "Engaged": 62, "Client": 82}
_STAGE_CLASS = {"Cold": "cold", "Warm": "warming", "Engaged": "engaged",
                "Client": "client"}

# A conversation is LIVE for a fortnight (the Buyer Graph's rule) and a relationship is
# ALIVE for a quarter, or a third of a year once they have ever replied to us (the
# Relationship Management rule). Both survive; they were never in conflict, they were
# answering different questions in two places that each thought it was the only one.
FRESH_DAYS = 14
QUIET_DAYS = 90
QUIET_DAYS_IF_REPLIED = 120

# Old stage names, still stored in `relationships.stage` wherever a human overrode one.
# Mapped rather than migrated: an override is something Jon typed, and rewriting his
# rows to make a refactor tidy is not a trade worth making. "Dormant" was never a stage
# in the new vocabulary — it is the flag — so it maps to None and sets `dormant`.
LEGACY_STAGES = {
    "Cold": "Cold",
    "Warming": "Warm",
    "Warm Prospect": "Warm",
    "Warm": "Warm",
    "Active": "Engaged",
    "Engaged": "Engaged",
    "Client": "Client",
    "Dormant": None,
}


@dataclass
class BuyerRelationship:
    stage: str
    score: int  # 0-100 relationship strength
    next_best_action: str
    signals: List[str] = field(default_factory=list)
    dormant: bool = False

    @property
    def stage_class(self) -> str:
        return _STAGE_CLASS.get(self.stage, "cold")

    @property
    def label(self) -> str:
        """What the pill says. Dormancy rides WITH the stage rather than replacing
        it — "Client · dormant" is the fact; "Dormant" alone throws away the half
        that says these people have paid us."""
        return f"{self.stage} · dormant" if self.dormant else self.stage


def days_since(iso: Optional[str]) -> Optional[int]:
    """Whole days since an ISO timestamp, or None if missing/unparseable."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - dt).days)


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
    responded: bool = False,
    fit_score: Optional[int] = None,
) -> BuyerRelationship:
    """Derive the stage, dormancy, score, signals, and next action — from ALL of it.

    Stage rules (deterministic):
      - **Client**  — we have won at least one job with this buyer. Nothing outranks
        having been paid.
      - **Engaged** — a touch inside the last fortnight: the conversation is live.
      - **Warm**    — touched before that, OR never touched but scoring well enough
        that Agency Intelligence flagged them (`fit_score >= 60`).
      - **Cold**    — nothing has happened.

    ``dormant`` is orthogonal: touched once, and not for a quarter (a third of a year
    if they ever replied). A Cold buyer cannot be dormant — there is nothing to have
    gone quiet.

    ``responded`` and ``fit_score`` are the evidence Relationship Management held and
    the Buyer Graph could not see. They default to the Buyer Graph's old behaviour, so
    a caller that has only the deal side still gets the answer it used to get.
    """
    fresh = last_contacted_days is not None and last_contacted_days <= FRESH_DAYS
    if won >= 1:
        stage = "Client"
    elif touches > 0 and fresh:
        stage = "Engaged"
    elif touches > 0 or (fit_score is not None and fit_score >= 60):
        stage = "Warm"
    else:
        stage = "Cold"

    quiet_after = QUIET_DAYS_IF_REPLIED if responded else QUIET_DAYS
    dormant = bool(touches > 0 and last_contacted_days is not None
                   and last_contacted_days > quiet_after)

    score = _STAGE_BASE[stage]
    score += min(touches, 5) * 2          # engagement effort
    if strategic_tier in ("Door-opener", "High"):
        score += 10                        # strategically valuable relationship
    if open_pursuits > 0:
        score += 5                         # live momentum
    if dormant:
        score -= 10                        # it was warmer than this once
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
        signals.append(f"{touches} outreach touch{'es' if touches != 1 else ''} · last {recency}"
                       + (" · they replied" if responded else ""))
    else:
        signals.append("no outreach logged yet")
    if dormant:
        signals.append("gone quiet — no contact this quarter")
    if strategic_tier in ("Door-opener", "High"):
        signals.append(f"{strategic_tier} strategic value")

    # Single next best action, tuned to the stage and whether anything is live.
    if dormant:
        action = (
            "Re-open — you have won here before and it has gone quiet; send a "
            "reconnect note." if stage == "Client"
            else "Revive or retire — nothing has moved this quarter; make one more "
                 "attempt or take it off the board."
        )
    elif stage == "Cold":
        action = (
            "Open the top opportunity and send the first outreach touch."
            if open_pursuits or qualified
            else "Qualify a new opportunity for this buyer to start the relationship."
        )
    elif stage == "Warm":
        action = "Follow up — contact was made but has gone quiet; re-engage on the open pursuit."
    elif stage == "Engaged":
        action = "Keep momentum — advance the open pursuit toward a proposal and a call."
    else:  # Client
        action = (
            "Nurture — you've won before; pitch the next project or ask for a referral."
            if open_pursuits == 0
            else "Convert — you have history here and a live pursuit; push it to a win."
        )

    return BuyerRelationship(stage=stage, score=score, next_best_action=action,
                             signals=signals, dormant=dormant)


# --------------------------------------------------------------------------- #
# The one entry point both surfaces call
# --------------------------------------------------------------------------- #
def _merge_touches(deal: Dict[str, Any], outreach: Dict[str, Any]) -> Dict[str, Any]:
    """Fold the two logs into one. `outreach_events` hangs off an opportunity; the
    `agency_outreach` log hangs off an Agency Intelligence record. They are the same
    act — someone contacted this company — recorded in whichever surface the operator
    happened to be standing in."""
    a_days = days_since((deal or {}).get("last_contacted"))
    b_days = days_since((outreach or {}).get("last_touch"))
    both = [d for d in (a_days, b_days) if d is not None]
    return {
        "touches": int((deal or {}).get("touches") or 0)
                   + int((outreach or {}).get("count") or 0),
        "last_contacted_days": min(both) if both else None,
        "responded": bool((outreach or {}).get("responded")),
    }


def relationship_for(*, deal: Optional[Dict[str, Any]] = None,
                     outreach: Optional[Dict[str, Any]] = None,
                     strategic_tier: Optional[str] = None,
                     fit_score: Optional[int] = None) -> BuyerRelationship:
    """The relationship for one organisation, from both halves of its evidence.

    ``deal``     — the opportunity rollup: opps, qualified, won, lost, open_pursuits,
                   touches (outreach_events), last_contacted.
    ``outreach`` — the agency rollup: count, last_touch, responded.

    Either may be missing: an organisation Agency Intelligence has never scored still
    has deals, and an agency nobody has raised an opportunity against still has touches.
    Calling this — rather than either half's own rule — is what stops the two pages
    disagreeing about the same company.
    """
    deal = dict(deal or {})
    merged = _merge_touches(deal, outreach or {})
    return assess_relationship(
        opps=int(deal.get("opps") or 0),
        qualified=int(deal.get("qualified") or 0),
        won=int(deal.get("won") or 0),
        lost=int(deal.get("lost") or 0),
        open_pursuits=int(deal.get("open_pursuits") or 0),
        touches=merged["touches"],
        last_contacted_days=merged["last_contacted_days"],
        strategic_tier=strategic_tier,
        responded=merged["responded"],
        fit_score=fit_score,
    )


def apply_override(rel: BuyerRelationship, stored: Optional[str]) -> BuyerRelationship:
    """Honour a human's stored stage over the derived one — "the machine proposes,
    Jon disposes" applies to this too. Legacy names are translated, and a stored
    "Dormant" sets the flag rather than becoming a stage that no longer exists."""
    if not stored:
        return rel
    mapped = LEGACY_STAGES.get(stored.strip(), stored.strip())
    if mapped is None:                       # stored "Dormant"
        return BuyerRelationship(stage=rel.stage, score=rel.score,
                                 next_best_action=rel.next_best_action,
                                 signals=rel.signals, dormant=True)
    if mapped not in STAGES:
        return rel
    return BuyerRelationship(stage=mapped, score=rel.score,
                             next_best_action=rel.next_best_action,
                             signals=rel.signals, dormant=rel.dormant)
