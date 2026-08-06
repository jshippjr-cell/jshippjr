"""Who did this.

The product's central law is *"the machine proposes, Jon disposes"* — and until now the
disposal had no signature. Dozens of routes are decision buttons (qualify, assign,
approve, release, publish, unlock), and the actor recorded on them was a hardcoded
string: `"Studio"`, `"ChordOS"`, or nothing at all. With one operator that is merely
untidy. The moment there is a second, **every past decision becomes unattributable and
every future one ambiguous** — which is why the launch review calls multi-user auth the
precondition for the first hire.

This is the bottom of that: identity on every decision, before any login work. It is
additive, it cannot lock anyone out, and the account work is worth nothing without it.

**It records a role, not a name, and that is deliberate.** Today the admin gate is a
single shared passphrase — the system genuinely does not know *which human* is behind
it, and writing "Jon" into an audit trail on the strength of a shared secret would be a
lie in exactly the record that exists to be trusted. What it does know is which door the
request came through, and that is what it writes. When real accounts arrive, the actor
gains a name and no call site changes.

Never store the token itself: a share token in a log is a credential in a log. The
fingerprint is enough to tell two clients apart and useless to anyone who reads it.
"""

from __future__ import annotations

import hashlib
from typing import Optional

OPERATOR = "operator"
CLIENT = "client"
CREATOR = "creator"
PUBLIC = "public"


def _fingerprint(token: str) -> str:
    """A stable, non-reversible handle for a token — enough to say "the same client
    again", useless to anyone who gets hold of the log."""
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def identify(request) -> dict:
    """``{kind, label, ref}`` for whoever is making this request.

    Derived from the request alone, so it costs nothing and cannot fail: the admin
    cookie, a `?k=`/`?r=` client token, or a `/creator/<token>` path.
    """
    from .shell import admin_authed

    try:
        path = request.url.path
        params = request.query_params
    except Exception:                      # noqa: BLE001 — never break a request over this
        return {"kind": PUBLIC, "label": "public", "ref": ""}

    if path.startswith("/creator/"):
        parts = [p for p in path.split("/") if p]
        token = parts[1] if len(parts) > 1 else ""
        return {"kind": CREATOR, "label": "a creator (portal link)",
                "ref": _fingerprint(token)}

    reviewer = params.get("r") or ""
    share = params.get("k") or ""
    if reviewer or share:
        return {"kind": CLIENT,
                "label": "a reviewer (personal link)" if reviewer else "a client (shared link)",
                "ref": _fingerprint(reviewer or share)}

    try:
        # A real account (ADR-0054) is the only thing that can put a NAME here. This is
        # the seam ADR-0053 was built against: the log gained names without a single
        # call site changing.
        from .shell import signed_in_user
        user = signed_in_user(request)
        if user is not None:
            label = (user["name"] or "").strip() or user["email"]
            return {"kind": OPERATOR, "label": label, "ref": f"user:{user['id']}"}
    except Exception:                      # noqa: BLE001
        pass
    try:
        if admin_authed(request):
            # The shared passphrase: still a ROLE, because it genuinely is one. Naming a
            # human on the strength of a shared secret would be a lie in an audit trail.
            return {"kind": OPERATOR, "label": "the operator (shared passphrase)",
                    "ref": ""}
    except Exception:                      # noqa: BLE001
        pass
    return {"kind": PUBLIC, "label": "public", "ref": ""}


# Paths whose subject is worth pulling out of the URL, so the log can answer "what
# happened to THIS project" without anyone parsing strings later.
_SUBJECTS = (("/project/", "project"), ("/opportunity/", "opportunity"),
             ("/agency/", "agency"), ("/talent/", "talent"), ("/invoice/", "invoice"))


def subject_of(path: str):
    """``(type, id)`` for the record this request acts on, or ``(None, None)``."""
    for prefix, kind in _SUBJECTS:
        if path.startswith(prefix):
            rest = path[len(prefix):].split("/")[0]
            if rest.isdigit():
                return kind, int(rest)
    return None, None


def record(conn, request, status: int) -> None:
    """Append one decision to the log. Best-effort — an audit trail that can 500 a
    client's approval is worse than no audit trail."""
    from datetime import datetime, timezone

    try:
        who = identify(request)
        stype, sid = subject_of(request.url.path)
        conn.execute(
            "INSERT INTO decision_log (at, actor_kind, actor_label, actor_ref, method, "
            "path, subject_type, subject_id, status) VALUES (?,?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), who["kind"], who["label"],
             who["ref"], request.method, request.url.path, stype, sid, int(status)))
        conn.commit()
    except Exception:                      # noqa: BLE001 — see docstring
        try: conn.rollback()
        except Exception: pass
