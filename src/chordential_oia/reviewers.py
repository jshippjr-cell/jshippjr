"""What a client's access link is allowed to do, and for how long.

A verified reviewer's personal link was four fields::

    {"token": "FwSd7R4HH7oq", "name": "Dana Whitfield",
     "email": "dana@aurora.com", "role": "Business affairs"}

No expiry, so a link mailed once works for ever. No record of use, so nobody can tell a
live link from one sitting in a two-year-old thread. No revocation — only deletion,
which erases the fact that access was ever granted. No record of who issued it. And no
statement of what it may DO, which mattered the moment signing arrived (ADR-0059): every
link could sign the Clearance Certificate, because there was nothing to say otherwise.

And there was no way for a client to give a colleague access at all. In practice that
means the link gets forwarded — so the system's real access-control model was "whoever
has the URL", while its records said "Dana Whitfield". **Delegation is not a new hole;
it is the existing hole, made visible and bounded.**

Two rules shape everything here:

1. **A delegate can never exceed their inviter, and never equals them.** A colleague
   invited by a reviewer may read and comment. They may not sign, may not approve, and
   may not invite anyone else — no chains. Signing and approving are the acts that bind
   the deal (ADR-0020, ADR-0059), and those stay with someone the OPERATOR named.
2. **Expiry is never applied retroactively.** Links already in the wild have no expiry
   and keep none; adding one would cut off live clients mid-review to make a refactor
   tidy. New links get one.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple

# Access states a token can be in.
ACTIVE = "active"
EXPIRED = "expired"
REVOKED = "revoked"
UNKNOWN = "unknown"          # no such token

# How long a new link lasts. 0 (or unset to 0) means "never expires", which is what
# every existing link already is.
LINK_DAYS_ENV = "CHORDENTIAL_REVIEWER_LINK_DAYS"
DEFAULT_LINK_DAYS = 90
# A delegated link is shorter by default AND capped at its inviter's expiry — access
# handed on cannot outlive the access it came from.
DEFAULT_DELEGATE_DAYS = 30


def link_days() -> int:
    try:
        return max(0, int(os.environ.get(LINK_DAYS_ENV, DEFAULT_LINK_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_LINK_DAYS


def _today() -> date:
    return datetime.now(timezone.utc).date()


def expiry_after(days: int, *, cap: str = "") -> str:
    """An ISO date ``days`` out, never later than ``cap``. Blank means never."""
    if days <= 0:
        return "" if not cap else cap
    out = (_today() + timedelta(days=days)).isoformat()
    if cap and cap < out:
        return cap
    return out


def is_delegate(rv: dict) -> bool:
    return bool((rv or {}).get("invited_by"))


def capabilities(rv: dict) -> dict:
    """What this link may do.

    Defaults come from WHO issued it, so a roster entry written before these fields
    existed still behaves exactly as it did: an operator-invited reviewer keeps the
    full set, and anything invited by a client is read-and-comment. An explicit value
    always wins, which is how the operator promotes a delegate.
    """
    rv = rv or {}
    default = not is_delegate(rv)
    return {
        "sign": bool(rv.get("can_sign", default)),
        "approve": bool(rv.get("can_approve", default)),
        "delegate": bool(rv.get("can_delegate", default)),
    }


def state_of(rv: dict, *, today: Optional[str] = None) -> str:
    """ACTIVE / EXPIRED / REVOKED for a roster entry."""
    rv = rv or {}
    if rv.get("revoked_at"):
        return REVOKED
    exp = (rv.get("expires_at") or "").strip()
    if exp and exp < (today or _today().isoformat()):
        return EXPIRED
    return ACTIVE


def access_note(state: str, rv: Optional[dict] = None) -> str:
    """What to tell someone whose link did not work.

    A bare 404 is the wrong answer to an expired link: the person holding it is a real
    client who was invited, and telling them "not found" sends them to their inbox to
    check they clicked the right thing. Say what happened and what to do.
    """
    rv = rv or {}
    if state == EXPIRED:
        return (f"This review link expired on {rv.get('expires_at', '')}. "
                "Ask your Chordential contact for a fresh one. Nothing is lost.")
    if state == REVOKED:
        return ("This review link has been withdrawn. Ask your Chordential contact "
                "if you still need access.")
    return "This link is not valid for this delivery."


def new_reviewer(*, token: str, name: str, email: str = "", role: str = "",
                 invited_by: str = "", inviter_expiry: str = "",
                 days: Optional[int] = None) -> dict:
    """A roster entry with its whole lifecycle stated, not implied.

    A DELEGATE (``invited_by`` set) is deliberately weaker than its inviter in three
    ways at once: shorter by default, capped at the inviter's expiry, and stripped of
    sign / approve / delegate. Access handed on must not outlive or outrank the access
    it came from, and chains of delegation are how a link ends up somewhere nobody
    intended.
    """
    delegate = bool(invited_by)
    if days is None:
        days = DEFAULT_DELEGATE_DAYS if delegate else link_days()
    return {
        "token": token,
        "name": (name or "").strip(),
        "email": (email or "").strip(),
        "role": (role or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expiry_after(days, cap=inviter_expiry if delegate else ""),
        "last_used_at": "",
        "revoked_at": "",
        "revoked_by": "",
        "invited_by": (invited_by or "").strip(),
        "can_sign": not delegate,
        "can_approve": not delegate,
        "can_delegate": not delegate,
    }


def touch(rv: dict) -> Tuple[dict, bool]:
    """Stamp today's use. Returns ``(entry, changed)``.

    DAY granularity on purpose. Per-request would be a JSON merge write on every page
    view of a page clients refresh while listening to a mix — and the question this
    answers is "is anyone still using this link", which a day answers as well as a
    millisecond does.
    """
    today = _today().isoformat()
    if (rv or {}).get("last_used_at") == today:
        return rv, False
    out = dict(rv or {})
    out["last_used_at"] = today
    return out, True
