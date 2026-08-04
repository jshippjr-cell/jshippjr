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

import os

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import db

_HERE = os.path.dirname(__file__)

#: The one Jinja environment. ``app.py`` adds the filters and globals.
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))


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
        finally:
            conn.close()
    return templates.TemplateResponse(request=request, name=name, context=context)


def public_base() -> str:
    """Absolute public base for links that land in an email (a relative path is
    dead in a mail client). Uses the configured domain; chordential.com default —
    matching the payments seam and outreach._page_url."""
    return os.environ.get(
        "CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com"
    ).rstrip("/")


__all__ = ["templates", "render", "public_base"]
