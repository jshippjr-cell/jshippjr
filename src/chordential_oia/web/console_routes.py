"""The operator's console — every screen that is not a record's own surface.

ADR-0044, slice 11. The dashboard, the two inboxes, the buyer directory and profile, the
Match Board, the project index, the revenue view, the disposition queue, the company
profile, and the two engine triggers (triage, chips).

Nineteen routes that had nothing in common except being small, which is why they were the
last to move: each was too little to justify a pass of its own, and together they are the
console's landing surfaces. Three helpers travelled with them and are used by nothing
else.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import (HTMLResponse, PlainTextResponse,
                               RedirectResponse)

from .. import mailer
from ..matching import match_talent
from ..talent import profile_completeness
from . import (db, next_action, queue as queue_mod, rehearsal, relationships,
               scheduler as scheduler_mod, sources, triage)
from .buyer_intel import STAGES, days_since, relationship_for
from .estimate import estimate_for
from .evaluate import evaluate
from .delivery_ops import _gate_banner
from .opportunity_ops import _buyer_context, _ensure_project_for_opp
from .shell import render

router = APIRouter(tags=["console"])


# The Company Profile (ADR-0022) — entered once, the source for every procurement document.
_COMPANY_PROFILE_FIELDS = [
    {"key": "legal_name", "label": "Legal company name", "group": "Identity"},
    {"key": "dba", "label": "DBA", "group": "Identity"},
    {"key": "website", "label": "Website", "group": "Identity"},
    {"key": "business_address", "label": "Business address", "group": "Identity"},
    {"key": "mailing_address", "label": "Mailing address", "group": "Identity"},
    {"key": "ein", "label": "Tax ID / EIN", "group": "Tax"},
    {"key": "tax_class", "label": "Tax classification", "group": "Tax"},
    {"key": "bank_name", "label": "Bank name", "group": "Banking"},
    {"key": "routing", "label": "Routing number", "group": "Banking"},
    {"key": "account", "label": "Account number", "group": "Banking"},
    {"key": "account_type", "label": "Account type", "group": "Banking"},
    {"key": "remittance_address", "label": "Remittance address", "group": "Banking"},
    {"key": "insurance_carrier", "label": "Insurance carrier", "group": "Insurance"},
    {"key": "insurance_limits", "label": "Insurance limits", "group": "Insurance"},
    {"key": "primary_contact", "label": "Primary contact", "group": "Contacts"},
    {"key": "finance_contact", "label": "Finance / AP contact", "group": "Contacts"},
    {"key": "procurement_contact", "label": "Procurement contact", "group": "Contacts"},
    {"key": "capabilities", "label": "Capabilities statement", "group": "Profile"},
    {"key": "naics", "label": "NAICS codes (optional)", "group": "Profile"},
    {"key": "uei_sam", "label": "UEI / SAM (optional)", "group": "Profile"},
    {"key": "duns", "label": "DUNS (legacy, optional)", "group": "Profile"},
]


@router.get("/relationships", response_class=HTMLResponse)
def relationships_dashboard(request: Request):
    """Today's Priorities + the relationship pipeline — what to act on, derived
    from the engines (movements, follow-ups, recommended outreach)."""
    conn = db.connect()
    try:
        priorities = relationships.daily_priorities(conn)
        rows = db.top_opportunities(conn, limit=50)
        # Batched: one outreach aggregate + one relationships fetch + one commit for
        # the whole page, instead of a query-per-row + a commit-per-changed-row.
        pipeline = relationships.pipeline_stages(conn, rows)
    finally:
        conn.close()
    return render(request, "relationships.html", nav="relationships",
                  priorities=priorities, pipeline=pipeline, stages=relationships.STAGES)


@router.post("/triage/run")
def triage_run():
    """Manually run agentic Gmail triage (Phase B1): read unread alert emails,
    extract the real opportunities, land them on the radar in the review queue.
    No autonomy yet — this is the verify-extraction-quality step."""
    conn = db.connect()
    try:
        triage.run_triage(conn)
    finally:
        conn.close()
    return RedirectResponse("/signals?triage=1", status_code=303)


# --------------------------------------------------------------------------- #
# Executive summary
# --------------------------------------------------------------------------- #
def _suggested_price(opp) -> float:
    """Suggested price for one opportunity, via the same engines as the estimate
    page (qualify → discipline/team → estimate). Deterministic and LLM-free."""
    return estimate_for(opp).suggested_price


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    raw = db.connect()
    # Read-only render that composes several views of the same rows: `next_action` and
    # `compute_queue` each correctly re-read what this handler already read, and on the
    # seeded demo that cost 71 queries for four projects. The memo answers the repeats
    # from memory and is discarded with the request (ADR-0051).
    conn = db.read_memo(raw)
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
        # "Needs triage" home module (ruling #4) — fed by the unified Incoming queue.
        incoming_all = db.list_incoming(conn)
        incoming = incoming_all[:6]            # home preview — first few, newest first
        incoming_total = len(incoming_all)
        metrics = db.exec_metrics(conn)
        # Same valuation basis as the headline pipeline number, scoped to the
        # column — so the subtotal and the KPI above it are commensurable. Won is
        # a settled figure and stays exactly what was recorded.
        totals = {
            "tentative_value": db.open_pipeline(conn, ["Submitted"])["value"],
            "won_value": sum((r["outcome_value"] or 0) for r in won),
        }
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        health = sources.health_rows(db.source_activity(conn, since),
                                     db.get_source_costs(conn))
        src_health = {
            "total": len(health["rows"]),
            "receiving": sum(1 for r in health["rows"] if r["status"] == "Receiving"),
            "quiet": sum(1 for r in health["rows"] if r["status"] == "Quiet"),
            "monthly_cost": health["total_monthly_cost"],
        }
        # ── Mission Control (Living OS P3) ──────────────────────────────────
        # "Waiting on you" counts ONLY decisions that truly block on the human
        # (council ruling): follow-ups due, unactioned incoming, new discovery
        # requests. The machine can't do any of these.
        dr_new = conn.execute(
            "SELECT COUNT(*) AS n FROM discovery_requests WHERE status='new'"
        ).fetchone()["n"]
        # New creators who came in through the public funnel (applied or were referred)
        # and are still waiting at the reel-review gate — a decision only Jon can make
        # (approve → they become matchable). Reported live: "I get no notification when
        # a composer applies — not on the dashboard nor on my phone." The phone push
        # fires from /apply; this is the durable in-app surface that needs no push setup.
        new_applicants = [
            {"id": r["id"], "name": r["name"], "source": r["source"] or "applicant",
             "at": r["created_at"] or ""}
            for r in conn.execute(
                "SELECT id, name, source, created_at FROM talent "
                "WHERE review_status = 'Pending' AND source IN ('applicant', 'referral') "
                "ORDER BY created_at DESC, id DESC LIMIT 50"
            ).fetchall()
        ]
        # Composer submissions waiting at the taste gate — a creator has uploaded a version
        # and it's on Jon to review + publish (or send back) before the client sees it.
        pending_reviews = []
        # ADR-0020 §6: every ACTIVE deal whose next move is the operator's ("assign the
        # composer", "start production", "send the final invoice", "release the proposal") —
        # surfaced so nothing waits unseen. The client's court-state, pointed inward.
        operator_moves = []
        # Deals that are MOVING but don't need the operator right now (ball in the
        # client's / studio's court). Surfaced read-only so Jon always knows the stage,
        # even when "waiting on you" is zero — no action, just situational awareness.
        in_flight = []
        _seen_opps = set()
        _projects = db.list_projects(conn) if hasattr(db, "list_projects") else []
        # Two queries now answer what the loop below (and `compute_queue` after it)
        # would otherwise ask twice per project. The per-row code is unchanged — it
        # simply never reaches the database (ADR-0051).
        db.prime_project_reads(conn, [p["id"] for p in _projects])
        for prow in _projects:
            d = db.get_delivery(conn, prow["id"])
            pv = d.get("pending_version")
            if pv:
                pending_reviews.append({
                    "project_id": prow["id"], "campaign": prow["need"],
                    "client": prow["client"], "by": (pv.get("by") or "a composer"),
                    "at": pv.get("at") or ""})
            opprow = db.get_opportunity(conn, prow["opp_id"]) if prow["opp_id"] else None
            if opprow is not None and opprow["id"] not in _seen_opps:
                _seen_opps.add(opprow["id"])
                na = next_action.compute(conn, db, opprow, prow)
                if na["court"] == "you" and na.get("url") and not pv:
                    operator_moves.append({"campaign": opprow["need"], "client": opprow["client"],
                                           "label": na["label"], "detail": na.get("detail", ""),
                                           "url": na["url"], "post": na.get("post", False)})
                elif na["court"] in ("client", "team", "scheduled"):
                    in_flight.append({"campaign": opprow["need"], "client": opprow["client"],
                                      "label": na["label"], "detail": na.get("detail", ""),
                                      "court": na["court"],
                                      "url": na.get("url") or f"/opportunity/{opprow['id']}"})
        # deals still in sales (a released proposal awaiting your move to assign, etc.)
        for r in tentative:
            if r["id"] in _seen_opps:
                continue
            _seen_opps.add(r["id"])
            na = next_action.compute(conn, db, db.get_opportunity(conn, r["id"]), None)
            if na["court"] == "you" and na.get("url"):
                operator_moves.append({"campaign": r["need"], "client": r["client"],
                                       "label": na["label"], "detail": na.get("detail", ""),
                                       "url": na["url"], "post": na.get("post", False)})
            elif na["court"] in ("client", "team", "scheduled"):
                in_flight.append({"campaign": r["need"], "client": r["client"],
                                  "label": na["label"], "detail": na.get("detail", ""),
                                  "court": na["court"],
                                  "url": na.get("url") or f"/opportunity/{r['id']}"})
        # ONE authority for "what is waiting on you". This used to be a second,
        # independently-coded sum living here — and the two disagreed in the open:
        # the dashboard said 2 while /queue said 11 on the same database, because
        # this line counted six things and the Disposition Queue ranks ten. The
        # queue is the richer aggregator and the surface built for the question,
        # so the dashboard reports its total and links to it for the detail.
        queue_cards = queue_mod.compute_queue(conn, db)
        waiting_count = len(queue_cards)
        if operator_moves and not pending_reviews:
            m0 = operator_moves[0]
            _featured_move = {"kind": "Your move", "title": f"{m0['label']} — {m0['campaign']}",
                              "sub": m0["detail"] or m0["client"], "href": m0["url"],
                              "cta": "Go →", "post": m0.get("post", False)}
        else:
            _featured_move = None
        featured = None
        if pending_reviews:
            pr0 = pending_reviews[0]
            featured = {"kind": "New version to review", "title": pr0["campaign"],
                        "sub": f"{pr0['by']} submitted — review &amp; publish to {pr0['client']}",
                        "href": f"/project/{pr0['project_id']}/delivery", "cta": "Review →"}
        elif _featured_move:
            featured = _featured_move
        elif followups:
            f = followups[0]
            featured = {"kind": "Follow-up due", "title": f["need"],
                        "sub": f"{f['client']} · {f['next_action'] or 'follow up'}",
                        "href": f"/opportunity/{f['id']}", "cta": "Open & act →"}
        elif incoming_total:
            i0 = incoming[0]
            featured = {"kind": "Lead to triage", "title": i0["title"],
                        "sub": i0["subtitle"] or "promote or dismiss",
                        "href": "/incoming", "cta": "Triage →"}
        elif dr_new:
            featured = {"kind": "Discovery requested", "title": "A client asked for a call",
                        "sub": "pick a time", "href": "/inbox", "cta": "Schedule →"}
        elif new_applicants:
            a0 = new_applicants[0]
            featured = {"kind": "New creator applied", "title": a0["name"],
                        "sub": "review their reel — approve to make them matchable",
                        "href": f"/talent/{a0['id']}", "cta": "Review →"}
        # "Machine running" — ONLY real recorded events with real timestamps
        # (council ruling: no invented feed lines).
        def _feed(sql, icon, fmt):
            out = []
            for r in conn.execute(sql).fetchall():
                try:
                    out.append({"icon": icon, "text": fmt(r), "at": r["at"] or ""})
                except Exception:  # noqa: BLE001 — one bad row never kills the feed
                    pass
            return out
        machine_feed = sorted(
            _feed("SELECT title, found_at AS at FROM signals ORDER BY found_at DESC LIMIT 4",
                  "📡", lambda r: f"Signal found — {r['title']}")
            + _feed("SELECT company, updated_at AS at FROM agencies "
                    "WHERE updated_at IS NOT NULL ORDER BY updated_at DESC LIMIT 4",
                    "✦", lambda r: f"Agency profile updated — {r['company']}")
            + _feed("SELECT contact_name, company, created_at AS at FROM inbound_leads "
                    "ORDER BY created_at DESC LIMIT 3",
                    "📥", lambda r: f"Lead received — {r['company'] or r['contact_name']}")
            + _feed("SELECT name, created_at AS at FROM discovery_requests "
                    "ORDER BY created_at DESC LIMIT 2",
                    "🎥", lambda r: f"Discovery call requested — {r['name'] or 'a client'}")
            + _feed("SELECT i.kind, i.amount, i.paid_at AS at, p.client AS client "
                    "FROM invoices i JOIN projects p ON p.id = i.project_id "
                    "WHERE i.status = 'Paid' AND i.paid_at IS NOT NULL "
                    "ORDER BY i.paid_at DESC LIMIT 4",
                    "💰", lambda r: f"{r['kind'] or 'Payment'} paid — {r['client'] or 'a client'}"
                    + (f" (${r['amount']:,.0f})" if r['amount'] else "")),
            key=lambda e: e["at"], reverse=True)[:8]
    finally:
        conn.close()
    return render(
        request, "dashboard.html", nav="dashboard",
        engine_lease=scheduler_mod.lease_status(),
        pursue=pursue, tentative=tentative, won=won, totals=totals,
        review=review, spotlight=spotlight, followups=followups, metrics=metrics,
        src_health=src_health, incoming=incoming, incoming_total=incoming_total,
        waiting_count=waiting_count, featured=featured, machine_feed=machine_feed,
        pending_reviews=pending_reviews, operator_moves=operator_moves,
        in_flight=in_flight, new_applicants=new_applicants,
    )


# --------------------------------------------------------------------------- #
# Front-of-House — inbound lead review queue (NOT the opportunity pipeline)
# --------------------------------------------------------------------------- #
# Leads come from the public site. They are reviewed and explicitly promoted into
# the pipeline by hand — a lead is never auto-injected as an opportunity (the
# precision-bias rule: a human qualifies first).
# --------------------------------------------------------------------------- #
# Incoming — the unified intake queue (a UNION view over inbound_leads + signals,
# not a table merge). Every new lead from every source rolls up here, newest
# first, with a source chip + inline Promote/Dismiss.
# --------------------------------------------------------------------------- #
@router.get("/incoming", response_class=HTMLResponse)
def incoming_queue(request: Request):
    conn = db.connect()
    try:
        rows = db.list_incoming(conn)
    finally:
        conn.close()
    return render(request, "incoming.html", nav="incoming", rows=rows)


@router.get("/incoming/count")
def incoming_count():
    """Live count of unactioned incoming items (all sources) — polled by the nav badge."""
    conn = db.connect()
    try:
        return {"new": db.incoming_unactioned_count(conn)}
    finally:
        conn.close()


@router.get("/capture", response_class=HTMLResponse)
def capture_page(
    request: Request, title: str = "", company: str = "",
    link: str = "", notes: str = "", budget: str = "",
):
    """Focused 'log a gig' page — prefilled from query params so it works as a
    one-click bookmarklet target, plus a paste-the-post box that auto-fills the
    fields. The fast path from a Reddit gig to an Inbound Lead."""
    base = str(request.base_url).rstrip("/")
    return render(
        request, "capture.html", nav="leads", base_url=base,
        title=title, company=company, link=link, notes=notes, budget=budget,
    )


@router.get("/inbox", response_class=HTMLResponse)
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
# Storage — the cutover surface (ADR-0043)
# --------------------------------------------------------------------------- #
# The operator needs to see where client media is going, and move it, WITHOUT a
# terminal. Until this page existed the only signal was a line printed at boot: if
# a credential is revoked six months from now, uploads start failing and nothing
# surfaces it until someone scrolls back through deploy logs. And the migration
# itself lived only in a script, so it needed a working web shell — which is not a
# thing you can count on at the moment you need it.
#
# "The machine proposes, Jon disposes": nothing here runs on its own. The page
# reports; the buttons are pressed by a human.
@router.get("/settings/storage", response_class=HTMLResponse)
def storage_page(request: Request, ran: str = ""):
    from chordential_oia.storage import storage_status
    from chordential_oia.storage.migrate import audit_referenced_media, inventory
    from .uploads import upload_dir

    root = upload_dir()
    conn = db.connect()
    try:
        inv = inventory(conn, root)
        audit = audit_referenced_media(conn, root)
    finally:
        conn.close()
    return render(request, "storage.html", nav="pipeline",
                  status=storage_status(root), inv=inv, root=root, result=None, ran=ran,
                  audit=audit, upload_dir_env=os.environ.get("CHORDENTIAL_UPLOAD_DIR", ""))


@router.post("/settings/storage/verify", response_class=HTMLResponse)
def storage_verify(request: Request):
    """Round-trip one throwaway object. `durable=True` only says the credentials and
    the SDK are present — nothing in it makes a network call."""
    from chordential_oia.storage import storage_status
    from chordential_oia.storage.migrate import (audit_referenced_media, inventory,
                                                 verify_round_trip)
    from .uploads import upload_dir

    root = upload_dir()
    probe = verify_round_trip(root)
    conn = db.connect()
    try:
        inv = inventory(conn, root)
        audit = audit_referenced_media(conn, root)
    finally:
        conn.close()
    return render(request, "storage.html", nav="pipeline", status=storage_status(root),
                  inv=inv, root=root, result=None, probe=probe, ran="verify", audit=audit,
                  upload_dir_env=os.environ.get("CHORDENTIAL_UPLOAD_DIR", ""))


@router.post("/settings/storage/cors", response_class=HTMLResponse)
def storage_cors(request: Request):
    """What does the bucket actually return for a browser request?

    The animated waveform turns on one response header, and neither side could see it:
    the server fetches its own objects happily and learns nothing about what a browser may
    do with them, and a browser that is refused cannot read the headers explaining why.
    This signs a URL exactly as the read path does and asks with a review player's own
    `Origin` and `Range`.
    """
    from chordential_oia.storage import storage_status
    from chordential_oia.storage.migrate import (audit_referenced_media, inventory,
                                                 probe_cors)
    from .uploads import upload_dir

    root = upload_dir()
    conn = db.connect()
    try:
        inv = inventory(conn, root)
        audit = audit_referenced_media(conn, root)
    finally:
        conn.close()
    key = next((r["key"] for r in audit["rows"] if r.get("in_store")), "")
    origin = os.environ.get("CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com").rstrip("/")
    cors = probe_cors(root, origin, key)
    cors["key"] = key
    return render(request, "storage.html", nav="pipeline", status=storage_status(root),
                  inv=inv, root=root, result=None, ran="cors", audit=audit, cors=cors,
                  upload_dir_env=os.environ.get("CHORDENTIAL_UPLOAD_DIR", ""))


@router.post("/settings/storage/migrate", response_class=HTMLResponse)
def storage_migrate(request: Request, mode: str = Form("dry")):
    """Copy the media onto the bucket. `mode=dry` reports and writes nothing.

    Refuses unless the active store is durable — copying onto the disk we are about
    to remove is not a migration. Idempotent, and every object is verified by
    SHA-256 read-back rather than by trusting `put()`.
    """
    from chordential_oia.storage import storage_status
    from chordential_oia.storage.migrate import (audit_referenced_media, inventory,
                                                 migrate as run_migrate)
    from .uploads import upload_dir

    root = upload_dir()
    conn = db.connect()
    try:
        result = run_migrate(conn, root, dry_run=(mode != "live"))
        inv = inventory(conn, root)
        # Re-audited AFTER the copy: "moved=12, failed=0" answers what the migration
        # did, not whether the portal can now find what it asks for. Those are
        # different questions and only the second one is the operator's.
        audit = audit_referenced_media(conn, root)
    finally:
        conn.close()
    return render(request, "storage.html", nav="pipeline", status=storage_status(root),
                  inv=inv, root=root, result=result, ran=mode, audit=audit,
                  upload_dir_env=os.environ.get("CHORDENTIAL_UPLOAD_DIR", ""))


@router.get("/settings/company-profile", response_class=HTMLResponse)
def company_profile_page(request: Request):
    """The Company Profile — entered ONCE, the source for every generated procurement
    document (ADR-0022)."""
    conn = db.connect()
    try:
        profile = db.get_company_profile(conn)
    finally:
        conn.close()
    return render(request, "company_profile.html", nav="pipeline", profile=profile,
                  fields=_COMPANY_PROFILE_FIELDS)


@router.post("/settings/company-profile")
async def company_profile_save(request: Request):
    form = await request.form()
    data = {f["key"]: (form.get(f["key"], "") or "").strip() for f in _COMPANY_PROFILE_FIELDS}
    conn = db.connect()
    try:
        db.save_company_profile(conn, data)
    finally:
        conn.close()
    return RedirectResponse("/settings/company-profile?saved=1", status_code=303)


@router.get("/matchboard", response_class=HTMLResponse)
def matchboard(request: Request, opp: Optional[int] = None,
               err: str = "", t: Optional[int] = None):
    conn = db.connect()
    try:
        opp_rows = db.staffable_opportunities(conn)
        talents = [t for t in db.load_talent(conn) if t.matchable]

        # Each opportunity's crew comes from its project (the real assignments
        # that also show on the Projects page).
        opps = []
        for r in opp_rows:
            proj = db.project_for_opp(conn, r["id"])
            crew = db.list_assignments(conn, proj["id"]) if proj else []
            opps.append({
                "row": r, "project_id": (proj["id"] if proj else None), "crew": crew,
            })

        # Optional focus: rank the right column by fit for one opportunity.
        focus_id, focus_label = None, None
        scores = {}
        valid_ids = {r["id"] for r in opp_rows}
        if opp in valid_ids:
            focus_id = opp
            frow = db.get_opportunity(conn, opp)
            fopp = db.opportunity_from_row(frow)
            fq, _ = evaluate(fopp)
            focus_label = frow["need"]
            for mt in match_talent(fq.discipline, fq.secondary_disciplines,
                                   f"{fopp.need} {fopp.description}", talents):
                scores[mt.talent.id] = mt.score
    finally:
        conn.close()

    def role_of(t):
        return t.discipline_labels[0] if t.discipline_labels else "Creator"

    metric = "fit" if focus_id is not None else "ready"
    bubbles = [{
        "id": t.id, "name": t.name, "role": role_of(t),
        "score": scores.get(t.id, 0) if focus_id is not None else profile_completeness(t),
        "metric": metric,
    } for t in talents]
    bubbles.sort(key=lambda b: b["score"], reverse=True)

    return render(
        request, "matchboard.html", nav="matchboard", opps=opps, bubbles=bubbles,
        focus_id=focus_id, focus_label=focus_label,
        gate_banner=_gate_banner(err, t),
    )


@router.post("/matchboard/assign")
def matchboard_assign(opp_id: int = Form(...), talent_id: int = Form(...)):
    """Assign a creator to an opportunity by staffing its project: ensure the
    project exists (so it shows on Projects), add the assignment, and broadcast
    to the whole crew so the team knows who they're working with."""
    conn = db.connect()
    try:
        t = db.get_talent(conn, talent_id)
        if t is None:
            return RedirectResponse("/matchboard", status_code=303)
        # ADR-0024 (the A-3 floor): no assignment without an executed agreement +
        # rate. Server-side refusal — the rights chain the certificate warrants
        # starts here. Checked BEFORE ensure-project so a blocked assign has no
        # side effects.
        if db.talent_assignment_blockers(t):
            return RedirectResponse(
                f"/matchboard?err=agreement&t={talent_id}", status_code=303)
        pid = _ensure_project_for_opp(conn, opp_id)
        if pid is None:
            return RedirectResponse("/matchboard", status_code=303)
        tt = db.talent_from_row(t)
        role = tt.discipline_labels[0] if tt.discipline_labels else "Crew"
        already = {a["talent_id"] for a in db.list_assignments(conn, pid)}
        if talent_id not in already:
            db.add_assignment(conn, pid, role, talent_id)
            crew = db.project_crew(conn, pid)
            names = ", ".join(c["name"] for c in crew) or tt.name
            db.add_update(
                conn, pid,
                f"{tt.name} joined the crew as {role}. Current team: {names}.",
                "assignment",
            )
    finally:
        conn.close()
    return RedirectResponse("/matchboard", status_code=303)


@router.post("/matchboard/unassign")
def matchboard_unassign(assignment_id: int = Form(...)):
    conn = db.connect()
    try:
        a = db.get_assignment(conn, assignment_id)
        db.remove_assignment(conn, assignment_id)
        if a is not None and a["project_id"]:
            db.add_update(
                conn, a["project_id"],
                f"{a['talent_name'] or 'A creator'} left the crew.", "assignment",
            )
    finally:
        conn.close()
    return RedirectResponse("/matchboard", status_code=303)


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


@router.get("/buyers", response_class=HTMLResponse)
def buyers_directory(
    request: Request, stage: Optional[str] = None, order_by: str = "relationship"
):
    conn = db.connect()
    try:
        rows = db.all_buyers(conn)
        # The other half of the evidence, in two batched queries rather than two per
        # row: the same companies' Agency Intelligence records, and the outreach logged
        # against them. Without this the directory stages a buyer from `opportunities`
        # alone and disagrees with /relationships about the same company (ADR-0057).
        orgs = db.orgs_by_ids(conn, [r["org_id"] for r in rows])
        agency_ids = [o["agency_id"] for o in orgs.values() if o["agency_id"]]
        agg = db.outreach_aggregate(conn, agency_ids)
    finally:
        conn.close()
    buyers = []
    for r in rows:
        tier = _strat_tier_for_value(r["strategic_value"])
        org = orgs.get(r["org_id"])
        # dict(row) works on both backends — sqlite3.Row and _PgRow each expose the
        # mapping protocol (keys() + __getitem__).
        rel = relationship_for(
            deal=dict(r),
            outreach=agg.get(org["agency_id"]) if org is not None else None,
            strategic_tier=tier,
        )
        days = days_since(r["last_contacted"])
        buyers.append({"row": r, "rel": rel, "strategic_tier": tier,
                       "days_since": days,
                       "agency_id": org["agency_id"] if org is not None else None})
    if stage:
        buyers = [b for b in buyers if b["rel"].stage == stage]
    # Sort keys — default ranks by relationship strength then strategic value.
    sorters = {
        "relationship": lambda b: (b["rel"].score, b["row"]["strategic_value"] or 0),
        "strategic": lambda b: (b["row"]["strategic_value"] or 0, b["rel"].score),
        "touches": lambda b: b["row"]["touches"] or 0,
        "recent": lambda b: -(b["days_since"] if b["days_since"] is not None else 10**6),
        "fit": lambda b: b["row"]["avg_alignment"] or 0,
    }
    buyers.sort(key=sorters.get(order_by, sorters["relationship"]), reverse=True)
    return render(
        request, "buyers.html", nav="buyers", buyers=buyers, stages=list(STAGES),
        active={"stage": stage or "", "order_by": order_by},
    )


@router.get("/buyer/{client}", response_class=HTMLResponse)
def buyer_profile(request: Request, client: str):
    conn = db.connect()
    try:
        ctx = _buyer_context(conn, client)
    finally:
        conn.close()
    if ctx is None:
        return HTMLResponse("Buyer not found", status_code=404)
    return render(request, "buyer.html", nav="buyers", **ctx)


@router.post("/chips/custom")
def chips_custom(
    request: Request, family: str = Form(""), label: str = Form(""),
    sentence: str = Form(""),
):
    """Save a reusable custom chip into "My chips" (global across deals)."""
    conn = db.connect()
    try:
        db.add_custom_chip(conn, family, label, sentence)
    finally:
        conn.close()
    back = request.headers.get("referer") or "/"
    return RedirectResponse(back, status_code=303)


@router.post("/buyer/{client}/website")
def set_buyer_website(client: str, website: str = Form("")):
    """Persist the company's website (a company-level attribute, not per-opp)."""
    conn = db.connect()
    try:
        db.set_company_website(conn, client, website)
    finally:
        conn.close()
    return RedirectResponse(f"/buyer/{client}", status_code=303)


# --------------------------------------------------------------------------- #
# Projects + assignment (supply side) — Jon assigns; nothing auto-assigns
# --------------------------------------------------------------------------- #
@router.get("/projects", response_class=HTMLResponse)
def projects_directory(request: Request, status: Optional[str] = None):
    conn = db.connect()
    try:
        rows = db.list_projects(conn)
    finally:
        conn.close()
    counts = {"all": len(rows)}
    for s in db.PROJECT_STATES:
        counts[s] = sum(1 for r in rows if r["status"] == s)
    if status in db.PROJECT_STATES:
        rows = [r for r in rows if r["status"] == status]
    from datetime import date as _date
    today = _date.today().isoformat()
    projects = []
    for r in rows:
        roles = json.loads(r["roles"]) if r["roles"] else []
        understaffed = (r["assigned"] or 0) < len(roles)
        deadline = r["deadline"]
        overdue = bool(deadline and deadline < today and r["status"] != "Delivered")
        total = r["ms_total"] or 0
        pct = round((r["ms_done"] or 0) / total * 100) if total else 0
        projects.append({
            "row": r, "roles": roles, "understaffed": understaffed,
            "overdue": overdue, "pct": pct,
        })
    return render(
        request, "projects.html", nav="projects", projects=projects,
        counts=counts, active_status=(status or ""),
    )


# --------------------------------------------------------------------------- #
# Revenue dashboard — the CRO's home screen. Cash collected is the number that
# matters; pipeline + funnel + A/R are the leading indicators. Read-only, built
# from existing data (invoices, proposals, projects, opportunities).
# --------------------------------------------------------------------------- #
@router.get("/revenue", response_class=HTMLResponse)
def revenue_dashboard(request: Request):
    conn = db.connect()
    try:
        summary = db.revenue_summary(conn)
        outstanding = db.list_outstanding_invoices(conn)
        payments = db.recent_payments(conn)
    finally:
        conn.close()
    return render(
        request, "revenue.html", nav="revenue", summary=summary,
        outstanding=outstanding, payments=payments,
    )


# --------------------------------------------------------------------------- #
# Payout ledger — pay the crew. Owed rows are generated when a client invoice is
# Paid; Jon pays off-platform and marks each Paid (W-9 must be on file first).
# --------------------------------------------------------------------------- #
def _safe_next(nxt: str, fallback: str) -> str:
    """Where an action returns to. Same-site paths only — a caller-supplied absolute
    URL would make these POST handlers an open redirect."""
    nxt = (nxt or "").strip()
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else fallback


@router.get("/queue", response_class=HTMLResponse)
def disposition_queue(request: Request):
    """The Disposition Queue — every pending founder decision, one ranked surface.
    Pure aggregation (queue.py) over existing decision routes; the queue renders
    and links, the decision buttons stay where they live. Machine proposes, the
    operator disposes — here, ergonomically."""
    show_all = (request.query_params.get("all") or "").strip() not in ("", "0", "false")
    conn = db.connect()
    try:
        view = queue_mod.queue_view(conn, db, include_snoozed=show_all)
    finally:
        conn.close()
    return render(request, "queue.html", nav="queue", **view)


@router.post("/queue/snooze")
def queue_snooze(key: str = Form(...), days: int = Form(7), next: str = Form("/queue")):
    """Hold one card back for a while. NOT a decision and NOT a delete: the row expires
    and the card returns if the thing still needs doing. That is what makes the list
    clearable without making it a liar."""
    conn = db.connect()
    try:
        db.snooze_queue_card(conn, key, days)
    finally:
        conn.close()
    return RedirectResponse(_safe_next(next, "/queue"), status_code=303)


@router.post("/queue/unsnooze")
def queue_unsnooze(next: str = Form("/queue")):
    """Bring every snoozed card back at once."""
    conn = db.connect()
    try:
        db.clear_queue_snoozes(conn)
    finally:
        conn.close()
    return RedirectResponse(_safe_next(next, "/queue"), status_code=303)


@router.post("/rehearsal")
def rehearsal_create():
    """Create a rehearsal deal standing at the moment the Discovery Summary is sent.

    The client experience could only be tested by walking a real funnel or practising on
    a real buyer. This drops a deal in at the interesting step — the call already held,
    so the summary is priced and signable — addressed to the operator's own inbox, so
    every client email arrives here and every link in it is clickable. Marked
    `source='rehearsal'` so it is never mistaken for pipeline, and deletable in one click
    when the run is over.
    """
    conn = db.connect()
    try:
        opp_id = rehearsal.create(conn, db)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}?rehearsal=1", status_code=303)


# --------------------------------------------------------------------------- #
# The outbox (ADR-0086) — what the system sent, or would have sent.
# --------------------------------------------------------------------------- #
@router.get("/pricing", response_class=HTMLResponse)
def pricing_reference(request: Request, cost: int = 9000, media: str = "broadcast",
                      territory: str = "national", term: str = "3",
                      exclusivity: str = "none"):
    """WHAT WE CHARGE, AND WHY — the pricing model, readable without a deal in front of you.

    Every other pricing surface in the product is attached to one opportunity: the estimate,
    the proposal, the call prep sheet's guide. That is right for pricing a job and useless
    for LEARNING the model, which is a thing the operator has to hold in their head on a
    call while a client is talking. Reading it out of `pricing.py` was the only way to see
    the whole shape of it, and source is not a reference.

    Everything here is READ from the engine, never restated (ADR-0033/0065): the factor
    tables are the dicts `build_quote` multiplies, the worked example is a real
    `build_quote` call, and the levers are priced by the same `price_guide` the prep sheet
    uses. A pricing page that quoted numbers of its own would be a second authority, and
    the first day it drifted would be a day nobody noticed.
    """
    from ..pricing import (BASE_LICENCE_SHARE, EXCLUSIVITY_FACTORS, EXCLUSIVITY_LABELS,
                           LICENCE_FACTOR_CAP, MARKET_BENCHMARKS, MEDIA_FACTORS,
                           MEDIA_LABELS, MIN_MARGIN, PRIOR_NOTE, TERM_FACTORS,
                           TERRITORY_FACTORS, TERRITORY_LABELS, LicenceTerms, build_quote,
                           derivation, price_guide, reference_estimate)
    from ..estimation import BAND_SPREAD, ROLE_RATES, TARGET_MARGIN

    # The sandbox's settings, clamped to what the tables actually hold. A hand-typed URL
    # must not be able to price a job at a factor that does not exist.
    cost = max(500, min(int(cost or 0), 500_000))
    media = media if media in MEDIA_FACTORS else "broadcast"
    territory = territory if territory in TERRITORY_FACTORS else "national"
    exclusivity = exclusivity if exclusivity in EXCLUSIVITY_FACTORS else "none"
    term_years = None if str(term).lower() in ("none", "perpetual", "perpetuity") else 3
    if str(term).isdigit() and int(term) in TERM_FACTORS:
        term_years = int(term)

    licence = LicenceTerms(media=media, territory=territory, term_years=term_years,
                           exclusivity=exclusivity)
    estimate = reference_estimate(cost)
    quote = build_quote(estimate, licence)
    guide = price_guide(estimate, licence)

    def _factors(table, labels, current):
        return [{"key": str(k), "label": labels.get(k, str(k)), "factor": v,
                 "current": k == current}
                for k, v in table.items()]

    terms = [{"key": ("perpetual" if k is None else str(k)),
              "label": ("in perpetuity" if k is None
                        else f"{k} year" + ("" if k == 1 else "s")),
              "factor": v, "current": k == term_years}
             for k, v in TERM_FACTORS.items()]

    return render(
        request, "pricing.html", nav="pricing",
        cost=cost, quote=quote, rows=derivation(quote), guide=guide,
        licence=licence, prior_note=PRIOR_NOTE,
        media=_factors(MEDIA_FACTORS, MEDIA_LABELS, media),
        territory=_factors(TERRITORY_FACTORS, TERRITORY_LABELS, territory),
        terms=terms,
        exclusivity=_factors(EXCLUSIVITY_FACTORS, EXCLUSIVITY_LABELS, exclusivity),
        cap=LICENCE_FACTOR_CAP, base_share=BASE_LICENCE_SHARE,
        target_margin=TARGET_MARGIN, min_margin=MIN_MARGIN, band_spread=BAND_SPREAD,
        role_rates=sorted(ROLE_RATES.items(), key=lambda kv: -kv[1]),
        benchmarks=MARKET_BENCHMARKS,
    )


@router.get("/outbox", response_class=HTMLResponse)
def outbox_page(request: Request, project: Optional[int] = None):
    """Every outbound message, newest first.

    This is the surface that lets a whole deal be walked with mail switched OFF and the
    client's experience still be READ — the emails were the one part of that experience
    nobody could look at without configuring SMTP and mailing a real person. It is also
    the production answer to "did the pay link go out, and to whom?", which nothing could
    answer before, because a notification is best-effort and silent by design.
    """
    conn = db.connect()
    try:
        rows = [dict(r) for r in db.list_outbox(conn, limit=200, project_id=project)]
    finally:
        conn.close()
    live = mailer.mail_configured()
    return render(request, "outbox.html", nav="settings", rows=rows, live=live,
                  statuses=db.OUTBOX_STATUS, project=project,
                  counts={
                      "all": len(rows),
                      "sent": sum(1 for r in rows if r["status"] == "sent"),
                      "logged": sum(1 for r in rows if r["status"] == "logged"),
                      "error": sum(1 for r in rows if r["status"] == "error"),
                  })


@router.get("/outbox/{outbox_id}", response_class=HTMLResponse)
def outbox_one(request: Request, outbox_id: int, raw: str = ""):
    """One message. ``?raw=1`` serves the stored HTML BODY ALONE, so the branded shell
    can be previewed in an iframe exactly as a mail client renders it — which is the
    only honest way to answer "what does the client see".

    Served with a restrictive CSP and `nosniff`: this is stored content being replayed
    into a same-origin frame behind the admin gate, and a mail body is not a page we
    wrote today. Nothing in it may fetch, script, or frame anything.
    """
    conn = db.connect()
    try:
        row = db.get_outbound(conn, outbox_id)
        row = dict(row) if row is not None else None
    finally:
        conn.close()
    if row is None:
        return HTMLResponse("Not found", status_code=404)
    if raw:
        body = row["body_html"] or ""
        if not body:
            return PlainTextResponse(row["body_text"] or "",
                                     headers={"X-Content-Type-Options": "nosniff"})
        return HTMLResponse(body, headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; img-src data: https:; style-src 'unsafe-inline'"),
        })
    return render(request, "outbox_one.html", nav="settings", row=row,
                  statuses=db.OUTBOX_STATUS)


@router.post("/outbox/clear")
def outbox_clear(project: str = Form("")):
    """Empty the outbox, or one project's — for clearing a rehearsal's noise before the
    next run. Deliberately not automatic: a record that tidies itself is not a record."""
    pid = int(project) if (project or "").strip().isdigit() else None
    conn = db.connect()
    try:
        db.clear_outbox(conn, project_id=pid)
    finally:
        conn.close()
    return RedirectResponse("/outbox", status_code=303)
