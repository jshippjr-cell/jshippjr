"""Proposal generation — deterministic, built straight from the estimator.

After a deposit is conceptually accepted, labor is attached and a proposal is
generated. This module assembles that document from existing engine outputs (the
:class:`~chordential_oia.estimation.Estimate` line items and suggested price) — it
introduces **no new pricing math**, mirroring the deterministic-document pattern
of :mod:`chordential_oia.prepare` / :mod:`chordential_oia.outreach`.

Payment *execution* (Stripe) is a separate, later, isolated step; this layer only
generates the paperwork and the deposit figure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .estimation import Estimate, RoleLine
from .models import MusicDiscipline, Opportunity, QualificationResult

# Status lifecycle for a proposal.
PROPOSAL_STATES = ["Draft", "Sent", "Accepted", "Declined"]

# Default deposit fraction taken before work begins (lean: protect cashflow).
DEFAULT_DEPOSIT_PCT = 0.50


@dataclass
class Proposal:
    client: str
    need: str
    discipline: str
    lines: List[RoleLine]
    total_price: float
    deposit_pct: float
    deposit_amount: float
    balance_due: float
    terms: List[str]
    assumptions: List[str] = field(default_factory=list)

    def render_text(self) -> str:
        """Plain-text proposal for copy-paste / export."""
        rows = [
            f"  - {l.role}: {l.breakdown}"
            for l in self.lines
        ] or ["  - —"]
        parts = [
            f"PROPOSAL — {self.need}",
            f"Client: {self.client}",
            f"Discipline: {self.discipline}",
            "",
            "Scope of work (labor):",
            *rows,
            "",
            f"Total: ${self.total_price:,.0f}",
            f"Deposit ({self.deposit_pct:.0%}): ${self.deposit_amount:,.0f}",
            f"Balance on delivery: ${self.balance_due:,.0f}",
            "",
            "Terms:",
            *[f"  - {t}" for t in self.terms],
        ]
        return "\n".join(parts)


def build_proposal(
    opp: Opportunity,
    qual: QualificationResult,
    estimate: Estimate,
    deposit_pct: float = DEFAULT_DEPOSIT_PCT,
) -> Proposal:
    """Assemble a deterministic proposal from existing engine outputs.

    Line items and total come directly from ``estimate``; the deposit is a simple
    fraction of that total. No independent pricing decision is made here.
    """
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    total = estimate.suggested_price
    deposit = round(total * deposit_pct, 2)
    balance = round(total - deposit, 2)
    terms = [
        f"{deposit_pct:.0%} deposit due to begin work; balance due on delivery.",
        "Includes the revision rounds scoped in the estimate.",
        "Final deliverables released on receipt of the balance.",
    ]
    return Proposal(
        client=opp.client,
        need=opp.need,
        discipline=discipline.label,
        lines=list(estimate.lines),
        total_price=total,
        deposit_pct=deposit_pct,
        deposit_amount=deposit,
        balance_due=balance,
        terms=terms,
        assumptions=list(estimate.assumptions),
    )
