"""Chordential — Procurement OS dashboard (FastAPI + SQLite + Jinja).

The user-facing product: opportunities are stored, viewed, filtered, ranked, and
managed across Pursue / Review / Pass lanes, with detail, buyer, estimate, and
qualification-rationale pages, search/filtering, win/loss tracking, and an
executive summary. All evaluation comes from the existing engines (see
:mod:`evaluate`); no scoring logic lives here.

Run it::

    chordential-web                 # then open http://127.0.0.1:8000
    uvicorn chordential_oia.web.app:app --reload
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..models import BuyerValue, MusicDiscipline
from ..prepare import build_pursuit_brief
from ..outreach import build_outreach_plan
from ..strategic import assess_strategic_value
from ..talent import Talent, profile_completeness
from ..matching import match_talent
from . import db, seed
from .buyer_intel import assess_relationship, days_since
from .estimate import build_estimate
from .evaluate import evaluate

_HERE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))


# --------------------------------------------------------------------------- #
# Jinja helpers
# --------------------------------------------------------------------------- #
def money(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"${value:,.0f}"


def pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.0f}%"


def slug(value: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in (value or "").lower()).strip("-")


_ACTION_CLASS = {"Pursue": "pursue", "Review": "review", "Watch": "watch", "Pass": "pass"}
_TIER_CLASS = {"A-Tier": "a", "B-Tier": "b", "C-Tier": "c", "Watch": "watch"}
_STATUS_CLASS = {
    "New": "new", "Pursuing": "pursuing", "Submitted": "submitted",
    "Won": "won", "Lost": "lost", "Passed": "passed",
}

templates.env.filters["money"] = money
templates.env.filters["pct"] = pct
templates.env.filters["slug"] = slug
templates.env.globals["action_class"] = lambda a: _ACTION_CLASS.get(a, "")
templates.env.globals["tier_class"] = lambda t: _TIER_CLASS.get(t, "")
templates.env.globals["status_class"] = lambda s: _STATUS_CLASS.get(s, "")
_STRAT_CLASS = {"Door-opener": "door", "High": "high", "Medium": "medium", "Low": "low"}
templates.env.globals["strat_class"] = lambda s: _STRAT_CLASS.get(s, "")
templates.env.globals["PIPELINE_STATES"] = db.PIPELINE_STATES


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn)
    count = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
    if count == 0:
        seed.seed(conn)
    seed.seed_talent(conn)
    seed.seed_demo_pipeline(conn)
    conn.close()
    yield


app = FastAPI(title="Chordential — Procurement OS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(_HERE, "static")), name="static")


def render(request: Request, name: str, **kw):
    """Render a template, compatible with Starlette's (request, name, context) API."""
    context = {"nav": kw.pop("nav", "")}
    context.update(kw)
    return templates.TemplateResponse(request=request, name=name, context=context)


# --------------------------------------------------------------------------- #
# Executive summary
# --------------------------------------------------------------------------- #
def _suggested_price(opp) -> float:
    """Suggested price for one opportunity, via the same engines as the estimate
    page (qualify → discipline/team → estimate). Deterministic and LLM-free."""
    qual, _ = evaluate(opp)
    team = qual.team_shape or qual.discipline.team_shape
    return build_estimate(opp, team, qual.discipline).suggested_price


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    conn = db.connect()
    try:
        # Pipeline column 1 — top targets to pursue, each with a suggested price
        # (the estimator is deterministic and cheap, so per-row is fine here).
        pursue = [
            {"r": r, "price": _suggested_price(db.opportunity_from_row(r))}
            for r in db.pursue_targets(conn)
        ]
        tentative = db.tentative_bids(conn)   # column 2 — bids out for decision
        won = db.won_deals(conn)              # column 3 — closed wins + crew
        review = db.list_opportunities(conn, action="Review", order_by="alignment")[:5]
        spotlight = db.strategic_spotlight(conn)
        followups = db.followups_due(conn)
        totals = {
            "tentative_value": sum((r["outcome_value"] or 0) for r in tentative),
            "won_value": sum((r["outcome_value"] or 0) for r in won),
        }
    finally:
        conn.close()
    return render(
        request, "dashboard.html", nav="dashboard",
        pursue=pursue, tentative=tentative, won=won, totals=totals,
        review=review, spotlight=spotlight, followups=followups,
    )


# --------------------------------------------------------------------------- #
# Inbox (search + filtering + ranking)
# --------------------------------------------------------------------------- #
@app.get("/inbox", response_class=HTMLResponse)
def inbox(
    request: Request,
    q: Optional[str] = None,
    action: Optional[str] = None,
    tier: Optional[str] = None,
    discipline: Optional[str] = None,
    buyer_type: Optional[str] = None,
    status: Optional[str] = None,
    min_alignment: Optional[float] = None,
    order_by: str = "alignment",
):
    conn = db.connect()
    try:
        rows = db.list_opportunities(
            conn, q=q, action=action, tier=tier, discipline=discipline,
            buyer_type=buyer_type, status=status, min_alignment=min_alignment,
            order_by=order_by,
        )
        filters = {
            "action": db.distinct_values(conn, "action"),
            "tier": db.distinct_values(conn, "tier"),
            "discipline": db.distinct_values(conn, "discipline"),
            "buyer_type": db.distinct_values(conn, "buyer_type"),
            "status": db.distinct_values(conn, "status"),
        }
    finally:
        conn.close()
    active = {
        "q": q or "", "action": action or "", "tier": tier or "",
        "discipline": discipline or "", "buyer_type": buyer_type or "",
        "status": status or "", "min_alignment": min_alignment or "",
        "order_by": order_by,
    }
    return render(
        request, "inbox.html", nav="inbox", rows=rows, filters=filters, active=active
    )


# --------------------------------------------------------------------------- #
# Lanes (Pursue / Review / Pass kanban)
# --------------------------------------------------------------------------- #
@app.get("/lanes", response_class=HTMLResponse)
def lanes(request: Request):
    conn = db.connect()
    try:
        pursue = db.list_opportunities(conn, action="Pursue", order_by="alignment")
        review = (
            db.list_opportunities(conn, action="Review", order_by="alignment")
            + db.list_opportunities(conn, action="Watch", order_by="alignment")
        )
        passed = db.list_opportunities(conn, action="Pass", order_by="created")
    finally:
        conn.close()
    return render(
        request, "lanes.html", nav="lanes", pursue=pursue, review=review, passed=passed
    )


# --------------------------------------------------------------------------- #
# Opportunity detail + subpages
# --------------------------------------------------------------------------- #
def _load(conn, opp_id: int):
    row = db.get_opportunity(conn, opp_id)
    if row is None:
        return None, None, None
    opp = db.opportunity_from_row(row)
    qual, scored = evaluate(opp)
    return row, opp, (qual, scored)


@app.get("/opportunity/{opp_id}", response_class=HTMLResponse)
def opportunity_detail(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        buyer_rows = db.buyer_opportunities(conn, row["client"])
        project = db.project_for_opp(conn, opp_id)
    finally:
        conn.close()
    qual, scored = ev
    sv = assess_strategic_value(opp)
    return render(
        request, "detail.html", nav="inbox", row=row, opp=opp, qual=qual, scored=scored,
        sv=sv, buyer_count=len(buyer_rows), buyer_values=list(BuyerValue),
        project_id=(project["id"] if project else None),
    )


@app.get("/opportunity/{opp_id}/qualification", response_class=HTMLResponse)
def qualification_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
    finally:
        conn.close()
    qual, scored = ev
    return render(
        request, "qualification.html", nav="inbox", row=row, opp=opp, qual=qual, scored=scored
    )


@app.get("/opportunity/{opp_id}/estimate", response_class=HTMLResponse)
def estimate_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
    finally:
        conn.close()
    qual, scored = ev
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or discipline.team_shape, discipline)
    return render(
        request, "estimate.html", nav="inbox", row=row, opp=opp, qual=qual, est=est
    )


def _brief_for(conn, opp_id: int):
    """Load an opportunity and assemble its pursuit brief (None if missing)."""
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None, None, None
    qual, scored = ev
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or discipline.team_shape, discipline)
    strategic = assess_strategic_value(opp)
    brief = build_pursuit_brief(opp, qual, scored, est, strategic)
    return row, opp, brief


@app.get("/opportunity/{opp_id}/brief", response_class=HTMLResponse)
def brief_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, brief = _brief_for(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
    finally:
        conn.close()
    return render(request, "brief.html", nav="inbox", row=row, opp=opp, brief=brief)


@app.get("/opportunity/{opp_id}/brief.txt", response_class=PlainTextResponse)
def brief_text(opp_id: int):
    conn = db.connect()
    try:
        row, opp, brief = _brief_for(conn, opp_id)
        if row is None:
            return PlainTextResponse("Opportunity not found", status_code=404)
    finally:
        conn.close()
    return PlainTextResponse(brief.render_text())


def _outreach_for(conn, opp_id: int):
    """Load an opportunity and assemble its outreach plan (None if missing)."""
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None, None, None
    qual, scored = ev
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or discipline.team_shape, discipline)
    strategic = assess_strategic_value(opp)
    plan = build_outreach_plan(opp, qual, scored, est, strategic)
    return row, opp, plan


@app.get("/opportunity/{opp_id}/outreach", response_class=HTMLResponse)
def outreach_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, plan = _outreach_for(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        events = db.list_outreach_events(conn, opp_id)
    finally:
        conn.close()
    return render(
        request, "outreach.html", nav="inbox", row=row, opp=opp, plan=plan, events=events
    )


@app.get("/opportunity/{opp_id}/outreach.txt", response_class=PlainTextResponse)
def outreach_text(opp_id: int):
    conn = db.connect()
    try:
        row, opp, plan = _outreach_for(conn, opp_id)
        if row is None:
            return PlainTextResponse("Opportunity not found", status_code=404)
    finally:
        conn.close()
    return PlainTextResponse(plan.render_text())


@app.post("/opportunity/{opp_id}/outreach")
def set_outreach(
    opp_id: int,
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    contact_role: str = Form(""),
    next_action: str = Form(""),
    next_action_due: str = Form(""),
):
    conn = db.connect()
    try:
        db.update_outreach(
            conn, opp_id, contact_name, contact_email, contact_role,
            next_action, next_action_due,
        )
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/outreach", status_code=303)


@app.post("/opportunity/{opp_id}/outreach/event")
def add_outreach_event(
    opp_id: int,
    channel: str = Form("Email"),
    direction: str = Form("Sent"),
    note: str = Form(""),
):
    conn = db.connect()
    try:
        if note.strip():
            db.add_outreach_event(conn, opp_id, channel, direction, note.strip())
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/outreach", status_code=303)


@app.get("/opportunity/{opp_id}/match", response_class=HTMLResponse)
def talent_match_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        talents = db.load_talent(conn)
    finally:
        conn.close()
    qual, scored = ev
    matches = match_talent(qual.discipline, qual.secondary_disciplines,
                           f"{opp.need} {opp.description}", talents)
    # Detail for the eventual human decision: how many were considered vs gated out.
    matchable = sum(1 for t in talents if t.matchable)
    pending = sum(1 for t in talents if t.review_status.value == "Pending")
    return render(
        request, "match.html", nav="inbox", row=row, opp=opp, qual=qual, scored=scored,
        matches=matches, matchable=matchable, pending=pending, roster=len(talents),
    )


@app.post("/opportunity/{opp_id}/status")
def set_status(opp_id: int, status: str = Form(...), outcome_value: str = Form("")):
    conn = db.connect()
    try:
        value = float(outcome_value) if outcome_value.strip() else None
        db.update_status(conn, opp_id, status, value)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


@app.post("/opportunity/{opp_id}/strategic")
def set_strategic(opp_id: int, buyer_value: str = Form("unknown"), marquee: str = Form("")):
    conn = db.connect()
    try:
        db.update_strategic_inputs(conn, opp_id, buyer_value, bool(marquee.strip()))
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


@app.post("/opportunity/{opp_id}/notes")
def set_notes(opp_id: int, notes: str = Form("")):
    conn = db.connect()
    try:
        db.update_notes(conn, opp_id, notes)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


# --------------------------------------------------------------------------- #
# Buyer Graph — directory + profile
# --------------------------------------------------------------------------- #
def _strat_tier_for_value(value) -> Optional[str]:
    if value is None:
        return None
    if value >= 80:
        return "Door-opener"
    if value >= 65:
        return "High"
    if value >= 45:
        return "Medium"
    return "Low"


@app.get("/buyers", response_class=HTMLResponse)
def buyers_directory(request: Request):
    conn = db.connect()
    try:
        rows = db.all_buyers(conn)
    finally:
        conn.close()
    buyers = []
    for r in rows:
        tier = _strat_tier_for_value(r["strategic_value"])
        rel = assess_relationship(
            opps=r["opps"], qualified=int(r["qualified"] or 0),
            won=int(r["won"] or 0), lost=int(r["lost"] or 0),
            open_pursuits=int(r["open_pursuits"] or 0), touches=int(r["touches"] or 0),
            last_contacted_days=days_since(r["last_contacted"]),
            strategic_tier=tier,
        )
        buyers.append({"row": r, "rel": rel, "strategic_tier": tier})
    # Rank by relationship strength, then strategic value.
    buyers.sort(
        key=lambda b: (b["rel"].score, b["row"]["strategic_value"] or 0), reverse=True
    )
    return render(request, "buyers.html", nav="buyers", buyers=buyers)


@app.get("/buyer/{client}", response_class=HTMLResponse)
def buyer_profile(request: Request, client: str):
    conn = db.connect()
    try:
        rows = db.buyer_opportunities(conn, client)
        touch = db.buyer_touch_summary(conn, client)
        contacts = db.buyer_contacts(conn, client)
    finally:
        conn.close()
    if not rows:
        return HTMLResponse("Buyer not found", status_code=404)

    won = [r for r in rows if r["status"] == "Won"]
    lost = [r for r in rows if r["status"] == "Lost"]
    pursuing = [r for r in rows if r["status"] in ("Pursuing", "Submitted")]
    decided = len(won) + len(lost)

    # Strategic standing is a buyer-level attribute — resolve the strongest seen.
    bv_rank = {"enterprise": 3, "repeat": 2, "one_time": 1, "unknown": 0}
    best_bv = max((r["buyer_value"] or "unknown" for r in rows), key=lambda v: bv_rank.get(v, 0))
    tier_rank = {"Door-opener": 3, "High": 2, "Medium": 1, "Low": 0}
    best_tier = max(
        (r["strategic_tier"] for r in rows if r["strategic_tier"]),
        key=lambda t: tier_rank.get(t, 0), default=None,
    )
    strat_vals = [r["strategic_value"] for r in rows if r["strategic_value"] is not None]

    summary = {
        "client": client,
        "buyer_type": rows[0]["buyer_type"],
        "total": len(rows),
        "qualified": sum(1 for r in rows if r["qualified"]),
        "won": len(won),
        "lost": len(lost),
        "pursuing": len(pursuing),
        "win_rate": (len(won) / decided * 100.0) if decided else None,
        "won_value": sum((r["outcome_value"] or 0) for r in won),
        "avg_alignment": (sum(r["alignment"] or 0 for r in rows) / len(rows)),
        "disciplines": sorted({r["discipline"] for r in rows if r["qualified"]}),
        # CMO buyer-value standing
        "buyer_value": BuyerValue(best_bv).label,
        "marquee": any(r["marquee"] for r in rows),
        "strategic_tier": best_tier,
        "avg_strategic": (sum(strat_vals) / len(strat_vals)) if strat_vals else None,
    }
    rel = assess_relationship(
        opps=len(rows), qualified=summary["qualified"],
        won=len(won), lost=len(lost), open_pursuits=len(pursuing),
        touches=int(touch["touches"] or 0),
        last_contacted_days=days_since(touch["last_contacted"]),
        strategic_tier=best_tier,
    )
    return render(
        request, "buyer.html", nav="buyers", summary=summary, rows=rows,
        rel=rel, contacts=contacts, last_contacted=touch["last_contacted"],
    )


# --------------------------------------------------------------------------- #
# Talent (supply side) — roster, profile, demo-reel review, invite funnel
# --------------------------------------------------------------------------- #
# Disciplines offered in talent forms (exclude the disqualified NON_CRAFT bucket).
FORM_DISCIPLINES = [d for d in MusicDiscipline if d is not MusicDiscipline.NON_CRAFT]


@app.get("/talent", response_class=HTMLResponse)
def talent_roster(
    request: Request,
    discipline: Optional[str] = None,
    review: Optional[str] = None,
    invite: Optional[str] = None,
):
    conn = db.connect()
    try:
        rows = db.list_talent(conn, discipline=discipline, review=review, invite=invite)
        talents = [db.talent_from_row(r) for r in rows]
    finally:
        conn.close()
    cards = [{"t": t, "completeness": profile_completeness(t)} for t in talents]
    counts = {
        "total": len(cards),
        "approved": sum(1 for c in cards if c["t"].is_approved),
        "pending": sum(1 for c in cards if c["t"].review_status.value == "Pending"),
        "matchable": sum(1 for c in cards if c["t"].matchable),
    }
    active = {"discipline": discipline or "", "review": review or "", "invite": invite or ""}
    return render(
        request, "talent_roster.html", nav="talent", cards=cards, counts=counts,
        disciplines=FORM_DISCIPLINES, review_states=db.REVIEW_STATES,
        invite_states=db.INVITE_STATES, active=active,
    )


@app.get("/talent/new", response_class=HTMLResponse)
def talent_new(request: Request):
    return render(
        request, "talent_form.html", nav="talent", talent=None, disciplines=FORM_DISCIPLINES
    )


@app.post("/talent")
def talent_create(
    name: str = Form(...),
    email: str = Form(""),
    disciplines: List[str] = Form([]),
    credits: str = Form(""),
    location: str = Form(""),
    demo_reel_url: str = Form(""),
    notes: str = Form(""),
):
    valid = [MusicDiscipline(d) for d in disciplines if d in {m.value for m in MusicDiscipline}]
    t = Talent(
        name=name.strip(), email=email.strip() or None, disciplines=valid,
        credits=credits.strip(), location=location.strip() or None,
        demo_reel_url=demo_reel_url.strip() or None, notes=notes.strip(),
    )
    conn = db.connect()
    try:
        new_id = db.insert_talent(conn, t)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{new_id}", status_code=303)


@app.get("/talent/{talent_id}", response_class=HTMLResponse)
def talent_detail(request: Request, talent_id: int):
    conn = db.connect()
    try:
        row = db.get_talent(conn, talent_id)
        if row is None:
            return HTMLResponse("Talent not found", status_code=404)
        t = db.talent_from_row(row)
    finally:
        conn.close()
    return render(
        request, "talent_detail.html", nav="talent", t=t,
        completeness=profile_completeness(t), disciplines=FORM_DISCIPLINES,
        review_states=db.REVIEW_STATES, invite_states=db.INVITE_STATES,
    )


@app.post("/talent/{talent_id}")
def talent_edit(
    talent_id: int,
    name: str = Form(...),
    email: str = Form(""),
    disciplines: List[str] = Form([]),
    credits: str = Form(""),
    location: str = Form(""),
    demo_reel_url: str = Form(""),
    notes: str = Form(""),
):
    conn = db.connect()
    try:
        db.update_talent_profile(
            conn, talent_id, name.strip(), email, disciplines, credits.strip(),
            location, demo_reel_url, notes.strip(),
        )
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}", status_code=303)


@app.post("/talent/{talent_id}/review")
def talent_review(talent_id: int, review_status: str = Form(...)):
    conn = db.connect()
    try:
        db.update_talent_review(conn, talent_id, review_status)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}", status_code=303)


@app.post("/talent/{talent_id}/invite")
def talent_invite(talent_id: int, invite_status: str = Form(...)):
    conn = db.connect()
    try:
        db.update_talent_invite(conn, talent_id, invite_status)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}", status_code=303)


# --------------------------------------------------------------------------- #
# Projects + assignment (supply side) — Jon assigns; nothing auto-assigns
# --------------------------------------------------------------------------- #
@app.get("/projects", response_class=HTMLResponse)
def projects_directory(request: Request):
    conn = db.connect()
    try:
        rows = db.list_projects(conn)
        projects = []
        for r in rows:
            roles = json.loads(r["roles"]) if r["roles"] else []
            projects.append({"row": r, "roles": roles})
    finally:
        conn.close()
    return render(request, "projects.html", nav="projects", projects=projects)


@app.post("/opportunity/{opp_id}/project")
def create_project(opp_id: int):
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        existing = db.project_for_opp(conn, opp_id)
        if existing is not None:
            return RedirectResponse(f"/project/{existing['id']}", status_code=303)
        qual, scored = ev
        discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
        roles = qual.team_shape or discipline.team_shape
        pid = db.insert_project(
            conn, opp_id, opp.client, opp.need, opp.budget_min, opp.budget_max, roles
        )
        db.seed_default_milestones(conn, pid, roles)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{pid}", status_code=303)


def _project_view(conn, project_id: int):
    """Assemble a project with its roles, current assignments, and ranked candidates."""
    row = db.get_project(conn, project_id)
    if row is None:
        return None
    roles = json.loads(row["roles"]) if row["roles"] else []
    assignments = db.list_assignments(conn, project_id)
    by_role = {role: [] for role in roles}
    for a in assignments:
        by_role.setdefault(a["role"], []).append(a)

    # Ranked candidates come from the linked opportunity's discipline (the matcher).
    matches = []
    if row["opp_id"] is not None:
        opp_row = db.get_opportunity(conn, row["opp_id"])
        if opp_row is not None:
            opp = db.opportunity_from_row(opp_row)
            qual, scored = evaluate(opp)
            matches = match_talent(
                qual.discipline, qual.secondary_disciplines,
                f"{opp.need} {opp.description}", db.load_talent(conn),
            )
    milestones = db.list_milestones(conn, project_id)
    progress = db.milestone_progress(conn, project_id)
    return {
        "row": row, "roles": roles, "by_role": by_role, "matches": matches,
        "milestones": milestones, "progress": progress,
        "updates": db.list_updates(conn, project_id),
        "crew": db.project_crew(conn, project_id),
    }


@app.get("/project/{project_id}", response_class=HTMLResponse)
def project_detail(request: Request, project_id: int):
    conn = db.connect()
    try:
        view = _project_view(conn, project_id)
        if view is None:
            return HTMLResponse("Project not found", status_code=404)
    finally:
        conn.close()
    return render(
        request, "project_detail.html", nav="projects",
        project_states=db.PROJECT_STATES, milestone_states=db.MILESTONE_STATES, **view,
    )


@app.post("/project/{project_id}/assign")
def project_assign(project_id: int, role: str = Form(...), talent_id: int = Form(...)):
    """The decision action — Jon assigns a creator to a role. The only assign path."""
    conn = db.connect()
    try:
        db.add_assignment(conn, project_id, role, talent_id)
        t = db.get_talent(conn, talent_id)
        name = t["name"] if t else "a creator"
        db.add_update(conn, project_id, f"{name} assigned to {role}.", "assignment")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@app.post("/project/{project_id}/unassign")
def project_unassign(project_id: int, assignment_id: int = Form(...)):
    conn = db.connect()
    try:
        a = db.get_assignment(conn, assignment_id)
        db.remove_assignment(conn, assignment_id)
        if a is not None:
            db.add_update(
                conn, project_id,
                f"{a['talent_name'] or 'A creator'} removed from {a['role']}.",
                "assignment",
            )
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@app.post("/project/{project_id}/status")
def project_status(project_id: int, status: str = Form(...)):
    conn = db.connect()
    try:
        db.update_project_status(conn, project_id, status)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@app.post("/project/{project_id}/milestone")
def project_add_milestone(project_id: int, title: str = Form(...), role: str = Form("")):
    conn = db.connect()
    try:
        if title.strip():
            db.add_milestone(conn, project_id, title.strip(), role.strip() or None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@app.post("/project/{project_id}/milestone/status")
def project_milestone_status(
    project_id: int, milestone_id: int = Form(...), status: str = Form(...)
):
    conn = db.connect()
    try:
        db.update_milestone_status(conn, milestone_id, status)
        m = db.get_milestone(conn, milestone_id)
        if m is not None:
            db.add_update(conn, project_id, f"“{m['title']}” → {status}.", "milestone")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@app.post("/project/{project_id}/update")
def project_post_update(project_id: int, body: str = Form("")):
    """Jon posts a note that broadcasts to everyone assigned to the project."""
    conn = db.connect()
    try:
        if body.strip():
            db.add_update(conn, project_id, body.strip(), "update")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


@app.post("/project/{project_id}/milestone/delete")
def project_milestone_delete(project_id: int, milestone_id: int = Form(...)):
    conn = db.connect()
    try:
        db.remove_milestone(conn, milestone_id)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}", status_code=303)


def main() -> None:  # console entry point
    import uvicorn

    host = os.environ.get("CHORDENTIAL_HOST", "127.0.0.1")
    port = int(os.environ.get("CHORDENTIAL_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
