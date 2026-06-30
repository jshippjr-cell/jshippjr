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
    status_code = kw.pop("status_code", 200)
    context = {"active": kw.pop("active", "")}
    context.update(kw)
    return templates.TemplateResponse(
        request=request, name=name, context=context, status_code=status_code,
    )


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


def _validate_lead_contact(email: str, phone: str, linkedin: str):
    """Server-side gate for the intake forms (founder's ruling #6, option b):
    email is ALWAYS required, PLUS at least one of {phone, LinkedIn}. Returns an
    error string when the submission fails, or ``None`` when it's reachable.

    HTML ``required`` is bypassable (bots skip the form entirely), so this runs
    regardless of the client-side attributes.
    """
    email = (email or "").strip()
    if not email or "@" not in email or "." not in email:
        return "Please enter a valid email address so we can reach you."
    if not (phone or "").strip() and not (linkedin or "").strip():
        return "Please add a phone number or LinkedIn so we have a way to follow up."
    return None


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
        request, "public/samples.html", active="samples", demos=show.demos,
        demos_intro=show.demos_intro,
    )


@router.get("/delivery-sample", response_class=HTMLResponse)
def public_delivery_sample(request: Request):
    """Sample agency delivery package — proves the premium delivery experience.
    Self-contained branded page (8 documents) with a Download-PDF action."""
    return render(request, "public/delivery_sample.html", active="")


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
    phone: str = Form(""),
    contact_linkedin: str = Form(""),
    company: str = Form(""),
    project_type: str = Form(""),
    description: str = Form(""),
    budget_text: str = Form(""),
    timeline: str = Form(""),
    company_url: str = Form(""),          # honeypot — must stay blank for humans
):
    # Honeypot: a bot fills the off-screen field. Pretend success without
    # inserting a lead or firing a notification.
    if company_url.strip():
        return RedirectResponse("/thanks?kind=project", status_code=303)

    error = _validate_lead_contact(contact_email, phone, contact_linkedin)
    if error:
        show = get_showcase()
        return render(
            request, "public/start.html", active="start",
            capabilities=show.capabilities, error=error,
            contact_name=contact_name, contact_email=contact_email,
            phone=phone, contact_linkedin=contact_linkedin, company=company,
            project_type=project_type, description=description,
            budget_text=budget_text, timeline=timeline,
            status_code=400,
        )

    band = public_price_band(project_type.strip(), description.strip())
    conn = db.connect()
    try:
        db.insert_inbound_lead(
            conn, contact_name.strip(), contact_email.strip(), company.strip(),
            project_type.strip(), description.strip(), budget_text.strip(),
            timeline.strip(), source="questionnaire",
            shown_price_low=(band["low"] if band else None),
            shown_price_high=(band["high"] if band else None),
            phone=phone.strip(), contact_linkedin=contact_linkedin.strip(),
        )
    finally:
        conn.close()
    try:                                     # best-effort phone push — never blocks the submit
        from . import signals
        signals.notify_new_lead(company.strip() or contact_name.strip(), "website")
    except Exception:
        pass
    # The indicative band is stored on the lead for the internal quoted-vs-won
    # moat, but is NOT shown back to the client — quoting a range at intake reads
    # as untactful (founder call). So the thank-you response carries no price.
    return RedirectResponse("/thanks?kind=project", status_code=303)


@router.get("/book", response_class=HTMLResponse)
def public_book(request: Request):
    return render(request, "public/book.html", active="book")


@router.post("/book", response_class=HTMLResponse)
def public_book_submit(
    request: Request,
    contact_name: str = Form(...),
    contact_email: str = Form(""),
    phone: str = Form(""),
    contact_linkedin: str = Form(""),
    company: str = Form(""),
    timeline: str = Form(""),
    description: str = Form(""),
    company_url: str = Form(""),          # honeypot — must stay blank for humans
):
    # Honeypot: silently accept the bot's submission without storing it.
    if company_url.strip():
        return RedirectResponse("/thanks?kind=call", status_code=303)

    error = _validate_lead_contact(contact_email, phone, contact_linkedin)
    if error:
        return render(
            request, "public/book.html", active="book", error=error,
            contact_name=contact_name, contact_email=contact_email,
            phone=phone, contact_linkedin=contact_linkedin, company=company,
            timeline=timeline, description=description,
            status_code=400,
        )

    conn = db.connect()
    try:
        db.insert_inbound_lead(
            conn, contact_name.strip(), contact_email.strip(), company.strip(),
            project_type="Intro call", description=description.strip(),
            timeline=timeline.strip(), source="book_call",
            phone=phone.strip(), contact_linkedin=contact_linkedin.strip(),
        )
    finally:
        conn.close()
    try:                                     # best-effort phone push — never blocks the submit
        from . import signals
        signals.notify_new_lead(company.strip() or contact_name.strip(), "website")
    except Exception:
        pass
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
@router.get("/for-artists", response_class=HTMLResponse)
def public_for_artists(request: Request):
    """The supply-side analog of the first-touch page: why a creator would join."""
    return render(request, "public/for_artists.html", active="for-artists")


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


# --------------------------------------------------------------------------- #
# Referral loop — a creator we trust refers a peer. Council's recommended,
# ToS-clean supply channel: it needs no scraping at all. The referred creator
# enters the SAME reel-review funnel, tagged source="referral".
# --------------------------------------------------------------------------- #
@router.get("/refer", response_class=HTMLResponse)
def public_refer(request: Request):
    return render(
        request, "public/refer.html", active="", disciplines=APPLY_DISCIPLINES,
    )


@router.post("/refer", response_class=HTMLResponse)
def public_refer_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    disciplines: List[str] = Form([]),
    credits: str = Form(""),
    location: str = Form(""),
    demo_reel_url: str = Form(""),
    referred_by: str = Form(""),
):
    valid = [
        MusicDiscipline(d) for d in disciplines
        if d in {m.value for m in MusicDiscipline}
    ]
    by = referred_by.strip()
    note = f"Referred by {by}." if by else "Peer referral."
    t = Talent(
        name=name.strip(), email=email.strip() or None, disciplines=valid,
        credits=credits.strip(), location=location.strip() or None,
        demo_reel_url=demo_reel_url.strip() or None,
        source="referral", source_url=demo_reel_url.strip() or None, notes=note,
    )
    conn = db.connect()
    try:
        db.insert_talent(conn, t)
    finally:
        conn.close()
    return RedirectResponse("/thanks?kind=refer", status_code=303)
