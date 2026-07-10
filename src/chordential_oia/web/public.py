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
from ..talent import Talent, normalize_url
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
# One source for the static-asset cache-buster. This used to be a hand-bumped
# constant ("22") — and the failure mode it warned about happened AGAIN: a CSS
# change shipped without a bump and browsers kept the 7-day-cached stylesheet
# (the reel's curtain effect arrived in HTML with no styles). Now computed from
# the static bundle's newest mtime, which changes on every Render build — no
# human step, every deploy busts every browser cache.
def _asset_version() -> str:
    latest = 0.0
    for dirpath, _dirs, files in os.walk(os.path.join(_HERE, "static")):
        for fname in files:
            try:
                latest = max(latest, os.path.getmtime(os.path.join(dirpath, fname)))
            except OSError:
                pass
    return str(int(latest))


ASSET_VERSION = _asset_version()
templates.env.globals["asset_v"] = ASSET_VERSION

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
    """The front door IS the Chordential Experience — the client-facing film
    (docs/design/chordential-experience-final-cut.md). The brochure homepage
    retired when the film passed its ship gate; /start remains the intake."""
    return render(request, "public/experience.html", active="home")


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


_GALLERY_GRADIENTS = [
    "wine-orange", "slate-sand", "ink-orange", "wine-slate", "orange-sand", "ink-wine",
]


@router.get("/experience", response_class=HTMLResponse)
def public_experience(request: Request):
    """The Chordential Experience — 'The One That Ships' (client-facing film,
    built beat by beat per docs/design/chordential-experience-*). Now the
    homepage; this route stays so existing deep links keep working."""
    return render(request, "public/experience.html", active="")


@router.get("/reel")
def public_reel():
    """Retired: the standalone reel spiral is gone — 'See the work' lives on the hero as the
    spinning reel wheel. Any old link/bookmark to /reel lands there via the /#reel deep-link."""
    from fastapi.responses import RedirectResponse
    # ?reel=1 (not #reel) — URL fragments can be dropped across a redirect; the query form
    # survives, and the homepage deep-link handler accepts both.
    return RedirectResponse("/?reel=1", status_code=307)


@router.get("/stills", response_class=HTMLResponse)
def public_stills(request: Request):
    """An editorial alternative to /reel's orbiting carousel: the same tracks
    + case studies as a scroll-tilted grid — each tile rises tipped forward,
    settles into focus, then tilts away as it exits. Pure CSS transform/filter
    driven by a small vanilla-JS scroll engine (scroll-tilted-grid.js); falls
    back to a static grid on touch/reduced-motion/narrow screens via CSS.
    Same card data + gradient tiles as /reel, so no new imagery is needed."""
    show = get_showcase()
    tracks = [d for d in show.demos if (d.audio_url or "").strip()]
    cards = []
    for i, t in enumerate(tracks):
        cards.append({
            "title": t.title, "label": t.discipline_label,
            "href": f"/showreel?t={i}", "kind": "Track",
        })
    for c in show.cases:
        cards.append({
            "title": c.title, "label": "Case study",
            "href": "/capabilities", "kind": "Case",
        })
    for i, c in enumerate(cards):
        c["gradient"] = _GALLERY_GRADIENTS[i % len(_GALLERY_GRADIENTS)]
    return render(request, "public/stills.html", active="", cards=cards)


@router.get("/showreel", response_class=HTMLResponse)
def public_showreel(request: Request):
    """Immersive showreel stage: hero video background, a cursor-following 'play'
    label, and the cleared capability tracks playing in a docked player. Doubles as
    a sell-by-hand asset — a clickable reel of original, cleared music."""
    show = get_showcase()
    tracks = [d for d in show.demos if (d.audio_url or "").strip()]
    return render(
        request, "public/showreel.html", active="", hero=show.hero, tracks=tracks,
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
    # Best-effort phone push, off the request thread so the submit redirects
    # instantly (the push does blocking network I/O; prod has Web Push configured).
    from . import signals
    signals.fire_and_forget(
        signals.notify_new_lead, company.strip() or contact_name.strip(), "website")
    # Automated acknowledgment to the client (best-effort, off-thread; a no-op
    # until SMTP is configured). Confirms we received their request.
    from .. import mailer
    signals.fire_and_forget(
        mailer.send_intake_ack, contact_email.strip(), contact_name.strip())
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
    # Best-effort phone push, off the request thread so the submit redirects
    # instantly (the push does blocking network I/O; prod has Web Push configured).
    from . import signals
    signals.fire_and_forget(
        signals.notify_new_lead, company.strip() or contact_name.strip(), "website")
    # Automated acknowledgment to the client (best-effort, off-thread).
    from .. import mailer
    signals.fire_and_forget(
        mailer.send_intake_ack, contact_email.strip(), contact_name.strip())
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
    reel_url = normalize_url(demo_reel_url)
    t = Talent(
        name=name.strip(), email=email.strip() or None, disciplines=valid,
        credits=credits.strip(), location=location.strip() or None,
        demo_reel_url=reel_url,
        source="applicant", source_url=reel_url,
    )
    conn = db.connect()
    try:
        db.insert_talent(conn, t)
    finally:
        conn.close()
    # Best-effort phone push, off the request thread so the submit redirects
    # instantly (the push does blocking network I/O; prod has Web Push configured).
    from . import signals
    signals.fire_and_forget(signals.notify_new_talent_application, t.name)
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
    reel_url = normalize_url(demo_reel_url)
    t = Talent(
        name=name.strip(), email=email.strip() or None, disciplines=valid,
        credits=credits.strip(), location=location.strip() or None,
        demo_reel_url=reel_url,
        source="referral", source_url=reel_url, notes=note,
    )
    conn = db.connect()
    try:
        db.insert_talent(conn, t)
    finally:
        conn.close()
    # Best-effort phone push (mirrors /apply) — a referral enters the same review gate.
    from . import signals
    label = f"{t.name} (referred{f' by {by}' if by else ''})"
    signals.fire_and_forget(signals.notify_new_talent_application, label)
    return RedirectResponse("/thanks?kind=refer", status_code=303)
