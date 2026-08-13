"""The one gate every paid model call passes through.

WHY THIS EXISTS. On 2026-08-13 the operator's Anthropic organisation ran out of credit
and the API was switched off — while the console's own meter read "This month: $0.00 of
$10 cap". Both were true. The cap only ever saw ONE caller: Campaign Intake recorded what
it spent, and four others (decision-makers, outreach drafting, inbox triage, the call
simulator) called the API and recorded nothing. A ceiling cannot hold up money it cannot
see, so `$0.00 of $10` never meant "nothing was spent" — it meant "nothing that writes to
this ledger was spent".

Worse, the six agency engines were running autonomously in production (render.yaml set
CHORDENTIAL_AUTONOMOUS=1, against the code's own documented default of OFF), so those
unmetered calls were being made on a timer, unattended, until the balance hit zero.

THE RULE THIS ENFORCES: **nothing spends money unless a human asked for it.**

Not "spends up to a cap" — a cap that stops at $10 has still spent $10 nobody approved.

The line is NOT interactive-vs-background; it is asked-for versus speculative. A
discovery call is scheduled by a person, attended by a person, and recorded because they
asked for it to be: reading that transcript with the ten-agent engine is the machine
finishing the job it was given, and it happens automatically (ADR-0023). Drawing the line
at "did a request thread trigger it" would have broken exactly that, and did for one
commit.

What must never spend unasked is SPECULATIVE work — sweeping every agency for
decision-makers, re-scoring the database, drafting outreach nobody requested. Those run on
a timer over rows nobody pointed at, and they are what emptied the balance.

So a scope that can be traced to a human decision wraps its work in `approved_by()`, and
everything else falls back to the free deterministic path. The default is "no", and the
default is what unattended sweeps get.

The cap still applies ON TOP, as a second floor under an approved run.

The ledger writes on its OWN connection, deliberately. Accounting that shares a caller's
transaction can be rolled back with it (or, on Postgres, poison it — see db.best_effort),
and a spend record that disappears when the work fails is how a ledger starts lying.
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import os
from typing import Optional, Tuple

_log = logging.getLogger("chordential.ai_budget")

# Who, if anyone, has approved spend in the current context. Empty means nobody, which
# is what every background task sees: contextvars do not cross into a plain
# threading.Thread, and that is the safe direction rather than a gap.
_approved: contextvars.ContextVar[str] = contextvars.ContextVar(
    "chordential_ai_spend_approved", default="")

KEY_ENV = "ANTHROPIC_API_KEY"
CAP_ENV = "CHORDENTIAL_EXTRACTION_MONTHLY_CAP"
DEFAULT_CAP = 10.0


@contextlib.contextmanager
def approved_by(actor: str = "operator"):
    """Mark this scope as human-approved spend. Wrap ONLY a handler a person triggered."""
    token = _approved.set((actor or "operator").strip() or "operator")
    try:
        yield
    finally:
        _approved.reset(token)


def approver() -> str:
    """Who approved spend here, if anyone."""
    return _approved.get()


def monthly_cap_usd() -> float:
    try:
        return max(0.0, float(os.environ.get(CAP_ENV, "") or DEFAULT_CAP))
    except ValueError:
        return DEFAULT_CAP


def _month() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m")


def spent_this_month() -> float:
    """What the ledger says, read on its own connection so no caller's transaction
    (or its failure) can affect the answer."""
    from . import db
    conn = None
    try:
        conn = db.connect()
        row = db.ai_spend_month(conn, _month())
        return float((row or {}).get("est_cost") or 0.0)
    except Exception:                       # noqa: BLE001 — an unreadable ledger is not
        return 0.0                          # a licence to spend; the gate below decides
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:               # noqa: BLE001
                pass


def may_spend(source: str) -> Tuple[bool, str]:
    """May this caller spend Anthropic credit right now? Returns (allowed, why not).

    Every reason to say no is checked here so no call site has to remember them, and
    every call site that forgets to ask simply never spends."""
    if not (os.environ.get(KEY_ENV) or "").strip():
        return False, "no ANTHROPIC_API_KEY"
    if (os.environ.get("CHORDENTIAL_EXTRACTION_ENGINE", "1").strip().lower()
            in ("0", "false", "off", "no")):
        return False, "the AI engine is switched off"
    who = approver()
    if not who:
        # The rule. Unattended work uses the free deterministic path, always.
        return False, (f"{source}: nobody approved this spend — background work never "
                       f"spends, by design")
    cap = monthly_cap_usd()
    if cap <= 0:
        return False, "the monthly cap is zero"
    spent = spent_this_month()
    if spent >= cap:
        return False, f"this month's ${spent:.2f} has reached the ${cap:.2f} cap"
    return True, ""


def record(source: str, *, cost: float = 0.0, calls: int = 0,
           in_tokens: int = 0, out_tokens: int = 0) -> None:
    """Write a spend to the ledger. Own connection, best-effort, never raises into the
    caller — but it is the ONLY way the cap ever learns anything, so every paid call
    must reach it."""
    from . import db
    if cost <= 0 and not calls:
        return
    conn = None
    try:
        conn = db.connect()
        db.add_ai_spend(conn, _month(), float(cost or 0.0), calls=int(calls or 0),
                        in_tokens=int(in_tokens or 0), out_tokens=int(out_tokens or 0))
        _log.info("AI spend: %s $%.4f (%d calls)", source, cost or 0.0, calls or 0)
    except Exception:                       # noqa: BLE001
        _log.exception("Could not record AI spend for %s — the cap is now under-counting",
                       source)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:               # noqa: BLE001
                pass


def status() -> dict:
    """The meter, for any surface that shows it."""
    cap = monthly_cap_usd()
    spent = spent_this_month()
    return {"month": _month(), "spent": spent, "cap": cap,
            "over": bool(cap > 0 and spent >= cap),
            "enabled": bool((os.environ.get(KEY_ENV) or "").strip()),
            "approved_here": bool(approver())}


def estimate_cost(in_tokens: int, out_tokens: int, model: Optional[str] = None) -> float:
    """A deliberately CONSERVATIVE dollar estimate: over-counting makes the cap bite
    early, under-counting is how a ledger lets a balance reach zero."""
    # Sonnet-class list pricing, rounded up: $3/M in, $15/M out.
    return (max(0, in_tokens) / 1_000_000.0) * 3.0 + (max(0, out_tokens) / 1_000_000.0) * 15.0
