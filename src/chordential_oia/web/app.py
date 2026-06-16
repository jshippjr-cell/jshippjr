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

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..models import BuyerValue, MusicDiscipline
from ..prepare import build_pursuit_brief
from ..outreach import build_outreach_plan
from ..strategic import assess_strategic_value
from . import db, seed
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
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    conn = db.connect()
    try:
        metrics = db.exec_metrics(conn)
        top = db.list_opportunities(conn, action="Pursue", order_by="alignment")[:6]
        review = db.list_opportunities(conn, action="Review", order_by="alignment")[:5]
        spotlight = db.strategic_spotlight(conn)
        followups = db.followups_due(conn)
    finally:
        conn.close()
    return render(
        request, "dashboard.html", nav="dashboard", metrics=metrics, top=top,
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
    finally:
        conn.close()
    qual, scored = ev
    sv = assess_strategic_value(opp)
    return render(
        request, "detail.html", nav="inbox", row=row, opp=opp, qual=qual, scored=scored,
        sv=sv, buyer_count=len(buyer_rows), buyer_values=list(BuyerValue),
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
# Buyer profile
# --------------------------------------------------------------------------- #
@app.get("/buyer/{client}", response_class=HTMLResponse)
def buyer_profile(request: Request, client: str):
    conn = db.connect()
    try:
        rows = db.buyer_opportunities(conn, client)
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
    return render(
        request, "buyer.html", nav="inbox", summary=summary, rows=rows
    )


def main() -> None:  # console entry point
    import uvicorn

    host = os.environ.get("CHORDENTIAL_HOST", "127.0.0.1")
    port = int(os.environ.get("CHORDENTIAL_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
