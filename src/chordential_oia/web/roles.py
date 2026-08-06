"""What each account is allowed to do.

`user_account.role` existed and nothing read it, which with one account is harmless and
with two is the whole problem: a hire could release a delivery, confirm a licence, or
delete an opportunity, and the only thing standing in the way was that they had not
thought to.

Three roles, because a business this size has three kinds of person and not seven:

    owner      Jon. Everything, including the things that cost money or assert a
               licence, and (later) managing accounts.
    operator   a hire who runs campaigns: qualify, assign, upload, publish, approve,
               deliver. Everything the day's work needs.
    viewer     read-only. An accountant, an advisor, a prospective hire being shown
               around. GET and nothing else.

**Two invariants, and both matter more than the rules themselves.**

1. **The shared passphrase keeps full access.** It is the break-glass (ADR-0054), and a
   break-glass that lands you in a permission error is not one. Restricting it would
   also be pointless: anyone holding it can change `CHORDENTIAL_ADMIN_TOKEN`.
2. **With no accounts, nothing changes.** A single-operator instance that has never
   created an account must behave exactly as it did before this file existed.

Enforced in ONE place — the gate middleware — for the same reason the decision log is:
a rule applied at forty routes is a rule missing from the forty-first, and the one it
misses is the one that matters. The cost is that these are path patterns rather than
domain calls; the mitigation is that the default is RESTRICTIVE, so a new dangerous
route is owner-or-operator by its method, never accidentally public.
"""

from __future__ import annotations

import re

OWNER = "owner"
OPERATOR = "operator"
VIEWER = "viewer"

# Ordered least → most. A role satisfies a requirement when its rank is >= the rule's.
_RANK = {VIEWER: 0, OPERATOR: 1, OWNER: 2}
ROLES = (VIEWER, OPERATOR, OWNER)


def rank(role: str) -> int:
    return _RANK.get((role or "").strip().lower(), 0)


def satisfies(role: str, needed: str) -> bool:
    return rank(role) >= rank(needed)


# Paths only an OWNER may act on. Each is here because getting it wrong is expensive,
# irreversible, or someone else's money — not because it felt important.
_OWNER_ONLY = tuple(re.compile(p) for p in (
    # Asserts the licence grant on the certificate a client signs against.
    r"^/project/\d+/delivery/release$",
    r"^/project/\d+/delivery/license",
    # Withdrawing a client's signature (ADR-0059). Irreversible and legal: the row is
    # kept, but the document stops reading as signed.
    r"^/project/\d+/delivery/signature/\d+/void$",
    # Releasing the commercial review is the moment a price becomes an offer.
    r"^/opportunity/\d+/commercial/release$",
    # Money.
    r"^/invoice/\d+/(status|checkout|send-pay-link)$",
    r"^/project/\d+/invoice$",
    # Destruction. A deleted opportunity takes its history with it.
    r"^/opportunity/\d+/delete$",
    r"^/leads/\d+/delete$",
    # Rotating the share link locks out whoever currently holds it — including a
    # client mid-review.
    r"^/project/\d+/delivery/rotate-link$",
))


def required_for(method: str, path: str) -> str:
    """The minimum role for this request.

    A GET is a look and needs only `viewer`. Everything else needs at least `operator`,
    and the list above needs `owner`. Restrictive by default ON PURPOSE: a route added
    tomorrow is covered by its method rather than by someone remembering this file.
    """
    if (method or "").upper() in ("GET", "HEAD", "OPTIONS"):
        return VIEWER
    for pattern in _OWNER_ONLY:
        if pattern.match(path or ""):
            return OWNER
    return OPERATOR


def may(user, method: str, path: str) -> bool:
    """Is this account allowed to make this request?

    ``user is None`` means the caller is not signed in with an account — the passphrase,
    or a token-gated client surface — and this module has nothing to say about them.
    Both are decided elsewhere (the gate, the share token), and answering True here
    keeps this file about ROLES rather than quietly becoming a second gate.
    """
    if user is None:
        return True
    try:
        role = user["role"]
    except Exception:                          # noqa: BLE001 — a row without the column
        role = OPERATOR
    return satisfies(role or OPERATOR, required_for(method, path))
