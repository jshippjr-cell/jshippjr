"""Public front-of-house site — the audience-facing surface.

A standalone magazine/brochure layout (``public_base.html``) mounted at ``/site``
on the same FastAPI app and SQLite DB as the internal dashboard, with no internal
navigation and no logins. This module owns the public routes only; it is imported
by :mod:`chordential_oia.web.app` (never the reverse) to avoid a circular import.

Cycle 1.1 ships the brochure pages (home / capabilities / samples). Inbound
intake (questionnaire + book-a-call → review queue) and the client-facing price
band arrive in later cycles of Phase 1.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import db
from .filters import displayurl, money, pct, slug
from .showcase import get_showcase

_HERE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))
templates.env.filters["money"] = money
templates.env.filters["pct"] = pct
templates.env.filters["slug"] = slug
templates.env.filters["displayurl"] = displayurl

router = APIRouter(prefix="/site", tags=["public"])


def render(request: Request, name: str, **kw):
    """Render a public template (active marks the current marketing nav item)."""
    context = {"active": kw.pop("active", "")}
    context.update(kw)
    return templates.TemplateResponse(request=request, name=name, context=context)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def public_home(request: Request):
    show = get_showcase()
    return render(
        request, "public/home.html", active="home",
        hero=show.hero, capabilities=show.capabilities, samples=show.samples[:3],
    )


@router.get("/capabilities", response_class=HTMLResponse)
def public_capabilities(request: Request):
    show = get_showcase()
    return render(
        request, "public/capabilities.html", active="capabilities",
        capabilities=show.capabilities,
    )


@router.get("/samples", response_class=HTMLResponse)
def public_samples(request: Request):
    show = get_showcase()
    return render(
        request, "public/samples.html", active="samples", samples=show.samples,
    )


# --------------------------------------------------------------------------- #
# Inbound intake — questionnaire + book-a-call. Submissions become review-queue
# leads (NOT opportunities); Jon promotes them from the internal dashboard.
# --------------------------------------------------------------------------- #
@router.get("/start", response_class=HTMLResponse)
def public_start(request: Request):
    show = get_showcase()
    return render(
        request, "public/start.html", active="start", capabilities=show.capabilities,
    )


@router.post("/start", response_class=HTMLResponse)
def public_start_submit(
    request: Request,
    contact_name: str = Form(...),
    contact_email: str = Form(""),
    company: str = Form(""),
    project_type: str = Form(""),
    description: str = Form(""),
    budget_text: str = Form(""),
    timeline: str = Form(""),
):
    conn = db.connect()
    try:
        db.insert_inbound_lead(
            conn, contact_name.strip(), contact_email.strip(), company.strip(),
            project_type.strip(), description.strip(), budget_text.strip(),
            timeline.strip(), source="questionnaire",
        )
    finally:
        conn.close()
    return RedirectResponse("/site/thanks?kind=project", status_code=303)


@router.get("/book", response_class=HTMLResponse)
def public_book(request: Request):
    return render(request, "public/book.html", active="book")


@router.post("/book", response_class=HTMLResponse)
def public_book_submit(
    request: Request,
    contact_name: str = Form(...),
    contact_email: str = Form(""),
    company: str = Form(""),
    timeline: str = Form(""),
    description: str = Form(""),
):
    conn = db.connect()
    try:
        db.insert_inbound_lead(
            conn, contact_name.strip(), contact_email.strip(), company.strip(),
            project_type="Intro call", description=description.strip(),
            timeline=timeline.strip(), source="book_call",
        )
    finally:
        conn.close()
    return RedirectResponse("/site/thanks?kind=call", status_code=303)


@router.get("/thanks", response_class=HTMLResponse)
def public_thanks(request: Request, kind: str = "project"):
    return render(request, "public/thanks.html", active="", kind=kind)
