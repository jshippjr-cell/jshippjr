"""The console's shared web primitives — the few things every route surface needs.

ADR-0044. ``app.py`` grew to 9,133 lines and 251 routes, which is the finding this
module starts to answer. Routes move out into their own ``*_routes.py`` modules a
group at a time; the obstacle to moving ANY of them was that the render helper and
the template environment lived in ``app.py``, so a router importing them and
``app.py`` importing the router formed a cycle.

So the environment is CREATED here and DECORATED in ``app.py``: every
``templates.env.filters[...] = ...`` line stays where it is, operating on this same
object. That keeps the move small — the risky part of touching a template
environment is a global that silently goes missing, which fails at render time
rather than import time.

Nothing in here knows about a route. If something needs a database, a model or a
domain engine, it does not belong in this module.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import db

_HERE = os.path.dirname(__file__)

#: The one Jinja environment. ``app.py`` adds the filters and globals.
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))
# Is the money seam live? Only the rehearsal banner asks, to warn that Pay deposit
# opens a REAL Stripe checkout. Callable, so a test that flips the env sees it.
templates.env.globals["payments_live"] = (
    lambda: __import__("chordential_oia.payments", fromlist=["x"]).payments_status()["live"])
# Why a payment bounced, in one place — the room, the delivery portal and the workspace
# render the same sentence. Lazily imported for the same reason as the line above: this
# module is the bottom of the import order and must not reach up into a helper.
templates.env.globals["pay_notice"] = (
    lambda flag: __import__("chordential_oia.web.billing",
                            fromlist=["x"]).pay_notice(flag))
# …and why a balance cannot be asked for at all, said to each side in its own words.
templates.env.globals["delivery_held_text"] = (
    lambda why: __import__("chordential_oia.web.delivery_ops",
                          fromlist=["x"]).DELIVERY_HELD.get(why or "", ""))
templates.env.globals["invoice_block_client"] = (
    lambda why: __import__("chordential_oia.web.billing",
                           fromlist=["x"]).INVOICE_BLOCK_CLIENT.get(why or "", ""))
templates.env.globals["invoice_block_operator"] = (
    lambda why: __import__("chordential_oia.web.billing",
                           fromlist=["x"]).INVOICE_BLOCK_OPERATOR.get(why or "", ""))
# Why a delete was refused. The RULE lives in `db.*_delete_block()`; the sentence
# explaining it lives next to the rule, not inline in a template — two copies of a
# refusal is how the page ends up saying something the code no longer does.
templates.env.globals["delete_override"] = (
    lambda why: db.PROJECT_DELETE_OVERRIDE.get(why or "", ""))
templates.env.globals["delete_refusal"] = (
    lambda kind, why: (db.PROJECT_DELETE_BLOCK if kind == "project"
                       else db.TALENT_DELETE_BLOCK).get(why or "", ""))


def render(request: Request, name: str, **kw):
    """Render a console template, compatible with Starlette's (request, name,
    context) API.

    Supplies the two nav badges every page's chrome expects, unless the caller
    already computed them — a route that has the numbers in hand should pass them
    rather than pay for a second query.
    """
    context = {"nav": kw.pop("nav", "")}
    context.update(kw)
    if "new_signals" not in context:        # nav badge — count of unactioned gigs
        conn = db.connect()
        try:
            context["new_signals"] = db.new_signal_count(conn)
            # Unified "Incoming" badge — all sources (leads + signals).
            context["new_incoming"] = db.incoming_unactioned_count(conn)
            # The taste gate. A composer's submission moves nowhere until the operator
            # publishes it, so "a take is waiting" has to be legible from every page —
            # an email and a card on the Queue were not enough to notice.
            context["new_submissions"] = db.pending_submission_count(conn)
        finally:
            conn.close()
    return templates.TemplateResponse(request=request, name=name, context=context)


def safe_local(path: str, fallback: str) -> str:
    """Only redirect to a same-site path (guards the ``return_to`` field).

    An open redirect is the classic form-field hole, and every route surface that
    accepts a `return_to` needs the same guard — `/admin`, `/opportunity` and
    `/talent` all do. Keeping it here means a route module never has to reach back
    into `app.py` for it (ADR-0044): `//evil.example` is rejected as well as
    `https://…`, because a protocol-relative URL leaves the site just as happily.
    """
    if path and path.startswith("/") and not path.startswith("//"):
        return path
    return fallback


def public_base() -> str:
    """Absolute public base for links that land in an email (a relative path is
    dead in a mail client). Uses the configured domain; chordential.com default —
    matching the payments seam and outreach._page_url."""
    return os.environ.get(
        "CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com"
    ).rstrip("/")


# --------------------------------------------------------------------------- #
# Who is asking
# --------------------------------------------------------------------------- #
# The admin gate itself (the middleware and the public-path allowlist) stays in
# `app.py`, because it is a property of the application object. What lives here is
# only the question a *route* asks — "is this request authenticated?" — which
# /admin, /project and the raw-HTTP handlers all ask, and which therefore blocked
# those groups from moving. No database, no domain: an env var and a cookie.
ADMIN_COOKIE = "cdl_admin"


def admin_secret() -> Optional[str]:
    return os.environ.get("CHORDENTIAL_ADMIN_TOKEN") or None


def admin_cookie_value(token: str) -> str:
    # Store proof-of-knowledge, never the raw token.
    return hashlib.sha256(f"cdl|{token}".encode()).hexdigest()


def signed_in_user(request: Request):
    """The account behind this request, or None (ADR-0054).

    A real account is the only thing that can give the decision log a NAME. Checked on
    every request rather than trusted from the cookie, because a session that cannot be
    revoked is not a session — it is a password you cannot change.
    """
    from . import accounts

    token = request.cookies.get(accounts.SESSION_COOKIE) or ""
    if not token:
        return None
    conn = None
    try:
        conn = db.connect()
        return accounts.session_user(conn, token)
    except Exception:                       # noqa: BLE001 — never 500 the gate
        return None
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass


def admin_authed(request: Request) -> bool:
    """Signed in with an account, OR holding the shared passphrase.

    Both, deliberately and indefinitely. The passphrase is BREAK-GLASS: accounts are an
    addition, and a deploy that could lock the operator out of the system running their
    business — at the exact moment they need to get in and fix it — is not a trade worth
    making for tidiness. Retiring it is a decision to take later, on purpose, with an
    account already proven to work.
    """
    if signed_in_user(request) is not None:
        return True
    token = admin_secret()
    if not token:
        return True  # gate disabled
    cookie = request.cookies.get(ADMIN_COOKIE) or ""
    return bool(cookie) and hmac.compare_digest(cookie, admin_cookie_value(token))


__all__ = ["templates", "render", "public_base", "safe_local",
           "ADMIN_COOKIE", "admin_secret", "admin_cookie_value", "admin_authed",
           "signed_in_user"]
