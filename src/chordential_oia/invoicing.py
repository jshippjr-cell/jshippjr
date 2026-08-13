"""Invoicing — deterministic, derived from an accepted proposal.

Deposit and final invoices reconcile exactly to the proposal total: the deposit
invoice is the proposal's deposit; the final invoice is the remaining balance.
Like proposals, this generates the document only — payment *execution* (Stripe)
is the separate, later, isolated step in :mod:`chordential_oia.payments`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .proposals import Proposal

INVOICE_KINDS = ["Deposit", "Final"]
INVOICE_STATES = ["Draft", "Issued", "Paid"]


@dataclass
class Invoice:
    client: str
    need: str
    kind: str          # "Deposit" | "Final"
    amount: float
    note: str = ""

    def render_text(self) -> str:
        return "\n".join([
            f"INVOICE ({self.kind}) · {self.need}",
            f"Client: {self.client}",
            "",
            f"Amount due: ${self.amount:,.0f}",
            *([self.note] if self.note else []),
        ])


def build_invoice(proposal: Proposal, kind: str) -> Invoice:
    """Build a deposit or final invoice from a proposal. Amounts come straight
    from the proposal — deposit = deposit_amount, final = balance_due."""
    if kind not in INVOICE_KINDS:
        raise ValueError(f"Unknown invoice kind {kind!r}")
    if kind == "Deposit":
        amount = proposal.deposit_amount
        note = f"Deposit ({proposal.deposit_pct:.0%}) to begin work."
    else:
        amount = proposal.balance_due
        note = "Balance due on delivery."
    return Invoice(
        client=proposal.client, need=proposal.need, kind=kind,
        amount=amount, note=note,
    )
