"""Public front-of-house site — the audience-facing surface.

A standalone magazine/brochure layout (``public_base.html``) mounted at the site
root (``/``) on the same FastAPI app and SQLite DB as the internal dashboard, with
no internal navigation and no logins. This module owns the public routes only; it is imported
by :mod:`chordential_oia.web.app` (never the reverse) to avoid a circular import.

Cycle 1.1 ships the brochure pages (home / capabilities / samples). Inbound
intake (questionnaire + book-a-call → review queue) and the client-facing price
band arrive in later cycles of Phase 1.
"""

from __future__ import annotations

import os
from typing import List

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..models import MusicDiscipline, Opportunity
from ..talent import Talent
from . import db
from .estimate import build_estimate
from .evaluate import evaluate
from .filters import displayurl, money, pct, slug
from .showcase import get_showcase

# Disciplines offered on the public applicant form (exclude the disqualified bucket).
APPLY_DISCIPLINES = [d for d in MusicDiscipline if d is not MusicDiscipline.NON_CRAFT]

_HERE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))
templates.env.filters["money"] = money
templates.env.filters["pct"] = pct
templates.env.filters["slug"] = slug
templates.env.filters["displayurl"] = displayurl

router = APIRouter(tags=["public"])


def render(request: Request, name: str, **kw):
    """Render a public template (active marks the current marketing nav item)."""
    context = {"active": kw.pop("active", "")}
    context.update(kw)
    return templates.TemplateResponse(request=request, name=name, context=context)


def _round_band(value: float, *, up: bool) -> int:
    """Round a price to a tidy $100 boundary (down for low, up for high)."""
    step = 100.0
    import math
    return int((math.ceil if up else math.floor)(value / step) * step)


def public_price_band(project_type: str, description: str):
    """Indicative client-facing price band from the EXISTING estimator.

    Builds a lightweight Opportunity from the intake fields, runs the same
    qualify→team→estimate path the internal estimate page uses, and returns a
    rounded ``(low, high)`` band around the suggested price — never a hard quote,
    and never any new pricing math. Returns ``None`` when there's nothing to
    estimate from.
    """
    text = f"{project_type} {description}".strip()
    if not text:
        return None
    opp = Opportunity(
        client="(prospect)", need=project_type or "Music commission",
        description=description or "",
    )
    qual, _ = evaluate(opp)
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or discipline.team_shape, discipline)
    # Convert the estimator's COST band into a client PRICE band using the same
    # margin ratio the estimate itself carries (no separate pricing rule here).
    if est.estimated_cost <= 0:
        return None
    ratio = est.suggested_price / est.estimated_cost
    low = _round_band(est.cost_low * ratio, up=False)
    high = _round_band(est.cost_high * ratio, up=True)
    return {"low": low, "high": high}


@router.get("/", response_class=HTMLResponse)
def public_home(request: Request):
    return render(request, "public/home.html", active="home", show=get_showcase())


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
    band = public_price_band(project_type.strip(), description.strip())
    conn = db.connect()
    try:
        db.insert_inbound_lead(
            conn, contact_name.strip(), contact_email.strip(), company.strip(),
            project_type.strip(), description.strip(), budget_text.strip(),
            timeline.strip(), source="questionnaire",
            shown_price_low=(band["low"] if band else None),
            shown_price_high=(band["high"] if band else None),
        )
    finally:
        conn.close()
    target = "/thanks?kind=project"
    if band:
        target += f"&low={band['low']}&high={band['high']}"
    return RedirectResponse(target, status_code=303)


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
    return RedirectResponse("/thanks?kind=call", status_code=303)


@router.get("/thanks", response_class=HTMLResponse)
def public_thanks(
    request: Request, kind: str = "project", low: int = 0, high: int = 0
):
    band = {"low": low, "high": high} if (low and high) else None
    return render(request, "public/thanks.html", active="", kind=kind, band=band)


# --------------------------------------------------------------------------- #
# Creator applications — supply-side intake. Applicants enter the SAME review
# funnel as sourced/manual talent: Pending until Jon reviews the reel.
# --------------------------------------------------------------------------- #
@router.get("/apply", response_class=HTMLResponse)
def public_apply(request: Request):
    return render(
        request, "public/apply.html", active="apply", disciplines=APPLY_DISCIPLINES,
    )


@router.post("/apply", response_class=HTMLResponse)
def public_apply_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    disciplines: List[str] = Form([]),
    credits: str = Form(""),
    location: str = Form(""),
    demo_reel_url: str = Form(""),
):
    valid = [
        MusicDiscipline(d) for d in disciplines
        if d in {m.value for m in MusicDiscipline}
    ]
    t = Talent(
        name=name.strip(), email=email.strip() or None, disciplines=valid,
        credits=credits.strip(), location=location.strip() or None,
        demo_reel_url=demo_reel_url.strip() or None,
        source="applicant", source_url=demo_reel_url.strip() or None,
    )
    conn = db.connect()
    try:
        db.insert_talent(conn, t)
    finally:
        conn.close()
    return RedirectResponse("/thanks?kind=apply", status_code=303)
