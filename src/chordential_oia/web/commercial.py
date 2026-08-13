"""The Commercial Review engine (ADR-0018, Phase 1).

The Commercial Review is the client's final decision point before Kickoff — the formal
agreement, generated *entirely* from Campaign Intelligence plus the deterministic
estimation/proposals engines. It is the natural continuation of the Campaign Brief: the Brief
answers "what are we making," the Review answers "what are we agreeing to" and "how we'll work
together."

Like the Brief, a Review is a **pure projection** — it stores no copy of scope/pricing/terms.
The only persistent state (in ``commercial_reviews``) is the immutable snapshot captured at
*release*: per the operator's decision, once released the offer is FROZEN so the client
approves a stable version and the Phase-3 approval binds to exactly what was shown. Re-release
regenerates from current CI as a new version. So CI stays the single source of truth for
*generation*; the snapshot is the *agreement record*.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import List, Optional

from ..capabilities import (
    Deliverable, build_capabilities_doc, default_toggles, quote_band,
)
from ..models import MusicRequirement, Opportunity, QualificationResult
from ..proposals import build_proposal


@dataclass
class CommercialReview:
    client: str
    project: str
    version: int
    generated_at: str = ""                     # stamped by the caller (scripts can't clock)
    # Scope
    scope_summary: str = ""
    deliverables: List[Deliverable] = field(default_factory=list)
    # Timeline
    timeline: str = ""
    schedule: List[dict] = field(default_factory=list)     # [{stage, when}]
    # Pricing
    fee_low: Optional[int] = None
    fee_high: Optional[int] = None
    optional_services: List[dict] = field(default_factory=list)   # [{name, note}]
    deposit_pct: float = 0.0
    deposit_amount: int = 0
    balance_amount: int = 0
    payment_schedule: List[dict] = field(default_factory=list)     # [{label, when, amount}]
    # Terms (producer-voiced; Phase 2 makes these fully dynamic)
    terms: List[dict] = field(default_factory=list)               # [{title, body}]
    # Procurement checklist (Phase 5 fills this from captured CI facts)
    procurement: List[dict] = field(default_factory=list)          # [{label, needed}]
    generated_from: str = "campaign_intelligence"


# --------------------------------------------------------------------------- #
def _revision_rounds(ci_fields: dict) -> int:
    raw = (ci_fields.get("revision_rounds") or "").strip()
    for tok in raw.split():
        if tok.isdigit():
            return int(tok)
    return 2  # the house default


def _producer_terms(opp: Opportunity, ci_fields: dict, rounds: int,
                    deposit_pct: float) -> List[dict]:
    """Producer-voiced clauses — professional, human, confident, never adversarial.
    CI-aware where the intelligence supports it (revision count, rights posture, timeline).
    Phase 2 will generate these fully dynamically from scope/rights/schedule."""
    original = getattr(opp, "music_requirement", None) == MusicRequirement.ORIGINAL
    deadline = (ci_fields.get("deadline") or "").strip()
    terms = [
        {"title": "Revision philosophy",
         "body": (f"We work collaboratively to arrive at the strongest creative outcome while "
                  f"protecting the production schedule. {rounds} rounds of revisions are "
                  f"included; further rounds are scoped openly, never sprung on you.")},
        {"title": "Ownership",
         "body": ("Upon final payment, all agreed rights transfer to you according to the "
                  "licensed usage outlined above: "
                  + ("original, cleared, and yours worldwide."
                     if original else "as licensed for this campaign."))},
        {"title": "Delivery",
         "body": ("Every deliverable is provided in the formats described above, organized and "
                  "labeled so anyone on the campaign can find them.")},
        {"title": "Creative direction",
         "body": ("Changes that materially alter the approved creative direction may call for a "
                  "revised scope. We'll always talk it through before anything changes.")},
        {"title": "Payment",
         "body": (f"A {deposit_pct:.0%} deposit confirms the booking and reserves the team; the "
                  f"balance is due on final delivery. Invoiced, never chased.")},
    ]
    if deadline:
        terms.append(
            {"title": "Timeline",
             "body": (f"We plan the production working back from {deadline}, and we'll flag any "
                      f"dependency that could move that date the moment we see it.")})
    terms.append(
        {"title": "Approval",
         "body": ("Approving this proposal authorizes Chordential to begin scheduling production "
                  "resources and start the work.")})
    return terms


def _schedule(ci_fields: dict) -> List[dict]:
    deadline = (ci_fields.get("deadline") or "").strip()
    return [
        {"stage": "Kickoff", "when": "On approval"},
        {"stage": "First cut", "when": "Shortly after kickoff"},
        {"stage": "Revisions", "when": "Collaborative rounds"},
        {"stage": "Final delivery", "when": deadline or "Per the agreed timeline"},
    ]


def build_commercial_review(
    opp: Opportunity, qual: QualificationResult, estimate, ci_view: Optional[dict] = None,
    *, met: bool = True, version: int = 1, overrides: Optional[dict] = None,
) -> CommercialReview:
    """Project a Commercial Review from Campaign Intelligence + the estimation/proposals
    engines. Pure: no persistence, no duplicate copy of the campaign facts. ``overrides`` is
    the per-opp commercial override blob (operator edits to price/deposit before release)."""
    ci_view = ci_view or {}
    ci_fields = dict(ci_view.get("fields") or {})
    overrides = overrides or {}

    # Operator edits before release win over the CI-derived values — the client approves
    # exactly what's on the page. An edited delivery deadline flows into the schedule + the
    # timeline term (reported live: "there's no actual deadline in the commercial review").
    if (overrides.get("timeline") or "").strip():
        ci_fields["deadline"] = overrides["timeline"].strip()
    if (overrides.get("revision_rounds") or "").strip():
        ci_fields["revision_rounds"] = overrides["revision_rounds"].strip()

    # Deliverables + the commercial close come from the SAME brief builder the client already
    # saw — single source, so the Review never disagrees with the Brief.
    toggles = default_toggles(getattr(opp, "status", "") or "Submitted")
    toggles.update({"delivery": True, "cost": True, "terms": True})
    doc = build_capabilities_doc(opp, qual, estimate, toggles=toggles,
                                 ci_view=ci_view, met=met)

    # Price from what the CLIENT actually said they'd spend when we know it (the discovered
    # budget is the number to quote to), falling back to the estimator's cost-based band only
    # when no budget was captured. An operator price override wins over both.
    fee_low, fee_high = quote_band(
        opp, estimate, ci_fields=ci_fields, commercial_overrides=overrides)
    proposal = build_proposal(opp, qual, estimate, quote_band=(fee_low, fee_high))
    deposit_pct = float(overrides.get("deposit_pct") or proposal.deposit_pct)
    if fee_low and fee_high:
        # Re-derive the deposit off the quoted band, not the estimator's, so the schedule
        # matches the number on the page.
        deposit_amount = int(round(((fee_low + fee_high) / 2) * deposit_pct))
    else:
        deposit_amount = int(round(proposal.deposit_amount))
    total_mid = int(round((fee_low + fee_high) / 2)) if (fee_low and fee_high) else 0
    balance_amount = max(0, total_mid - deposit_amount) if total_mid else 0

    scope_summary = ((overrides.get("scope_summary") or "").strip()
                     or ci_fields.get("campaign_objective")
                     or ci_fields.get("business_objective")
                     or doc.understanding or (opp.need or ""))
    rounds = _revision_rounds(ci_fields)

    payment_schedule = [
        {"label": "Deposit", "when": "On approval", "amount": deposit_amount},
        {"label": "Balance", "when": "On final delivery",
         "amount": balance_amount or None},
    ]

    return CommercialReview(
        client=(ci_fields.get("client") or opp.client),
        project=opp.need,
        version=version,
        scope_summary=scope_summary,
        deliverables=list(doc.deliverables),
        timeline=(ci_fields.get("deadline") or ""),
        schedule=_schedule(ci_fields),
        fee_low=fee_low, fee_high=fee_high,
        optional_services=[],   # a catalog arrives with client-selectable add-ons (Phase 3)
        deposit_pct=deposit_pct,
        deposit_amount=deposit_amount,
        balance_amount=balance_amount,
        payment_schedule=payment_schedule,
        terms=_producer_terms(opp, ci_fields, rounds, deposit_pct),
        procurement=[],          # captured + generated in Phase 5
    )


# --------------------------------------------------------------------------- #
def review_to_json(review: CommercialReview) -> str:
    """Freeze the rendered Review at release (the agreement record)."""
    return json.dumps(asdict(review))


def review_from_json(payload: str) -> Optional[CommercialReview]:
    try:
        data = dict(json.loads(payload))
    except (ValueError, TypeError):
        return None
    known = {f.name for f in fields(CommercialReview)}
    data = {k: v for k, v in data.items() if k in known}
    try:
        data["deliverables"] = [Deliverable(**d) for d in data.get("deliverables") or []]
        return CommercialReview(**data)
    except TypeError:
        return None
