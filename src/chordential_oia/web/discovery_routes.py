"""The discovery surface — where work arrives before it is a deal.

ADR-0044, second slice. Four route groups that the console's own nav already treats as
one section: the **signal engine** (market gigs the crawlers detect), the **crawler**
itself, **source health**, and the **inbound lead** queue. 25 routes with **zero**
references to any helper defined in ``app.py`` — the cleanest group left after
``/agencies``.

Unlike ``/agencies``, these were **not** one contiguous block: ten unrelated routes
(the dashboard, the admin login, `/incoming`, an opportunity delete) were interleaved
through their span, so the extraction was per-route rather than one cut. The relative
order of these 25 is preserved, and no route pattern in this group collides with any
other group — both checked before moving anything.

Imports point one way: ``app.py`` → here → ``shell.py``. Nothing in this module knows
that ``app.py`` exists.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from ..models import Opportunity
from . import db, discovery, scheduler, signals, sources, triage, webpush
from .filters import slug
from .shell import render

router = APIRouter(tags=["discovery"])


@router.get("/sources", response_class=HTMLResponse)
def sources_page(request: Request, tested: str = ""):
    """Source Health — when each source last delivered a lead, the monthly cost
    you've entered, and a per-source test button. Lead activity is live; cost is
    operator-entered."""
    from datetime import datetime, timedelta, timezone
    conn = db.connect()
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        health = sources.health_rows(db.source_activity(conn, since),
                                     db.get_source_costs(conn))
    finally:
        conn.close()
    for row in health["rows"]:
        row["weight"] = signals.weight_for(row["key"])
    tested_label = next((s["label"] for s in sources.SOURCES if s["key"] == tested), "")
    return render(request, "sources.html", nav="sources", health=health,
                  tested=tested_label, reddit_channels=sources.REDDIT_CHANNELS,
                  discord_channels=sources.DISCORD_CHANNELS)


@router.post("/sources/cost")
def sources_set_cost(source_key: str = Form(...), monthly_cost: str = Form(""),
                     notes: str = Form("")):
    cost = None
    raw = monthly_cost.strip().lstrip("$").replace(",", "")
    if raw:
        try:
            cost = float(raw)
        except ValueError:
            cost = None
    conn = db.connect()
    try:
        db.set_source_cost(conn, source_key, cost, notes.strip())
    finally:
        conn.close()
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/test")
def sources_test(source_key: str = Form(...)):
    """Inject a marked [TEST] lead for a source so its 'last lead' updates —
    proves the Source Health wiring without waiting for a real lead."""
    label = next((s["label"] for s in sources.SOURCES if s["key"] == source_key), source_key)
    conn = db.connect()
    try:
        db.insert_test_signal(conn, source_key, label)
    finally:
        conn.close()
    return RedirectResponse(f"/sources?tested={source_key}", status_code=303)


@router.post("/sources/cleartests")
def sources_clear_tests():
    conn = db.connect()
    try:
        db.clear_test_signals(conn)
    finally:
        conn.close()
    return RedirectResponse("/sources", status_code=303)


# --------------------------------------------------------------------------- #
# Agencies — the harvested Master Company Database + the Company Enrichment
# Engine. The list shows every harvested agency and its enrichment status; the
# per-row "Enrich" button runs the engine live (it actually fetches the agency's
# website when CHORDENTIAL_ENABLE_SCRAPE is on, i.e. on Render). This is the
# one-agency smoke test: click Enrich on Render, then read the profile.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Relationship Management Platform
# --------------------------------------------------------------------------- #
@router.get("/signals/selftest", response_class=HTMLResponse)
def signals_selftest(request: Request):
    """Run one synthetic lead from every weighted source through the real
    ingest → score → rank pipeline (throwaway DB — live data untouched) so the
    whole engine is verifiable end-to-end across all sources."""
    return render(request, "engine_selftest.html", nav="signals",
                  report=signals.engine_selftest())


@router.post("/signals/poll")
def signals_poll():
    """Run every configured feed (RSS + Reddit) right now and report what each
    returned — an on-demand test of the discovery feeds."""
    scheduler.poll_now()
    return RedirectResponse("/signals?poll=1", status_code=303)


@router.get("/leads", response_class=HTMLResponse)
def inbound_queue(request: Request, status: Optional[str] = None):
    conn = db.connect()
    try:
        leads = db.list_inbound_leads(conn, status=status)
        counts = db.inbound_counts(conn)
    finally:
        conn.close()
    return render(
        request, "inbound_queue.html", nav="leads", leads=leads, counts=counts,
        statuses=db.INBOUND_STATES, active_status=(status or ""),
    )


def _safe_next(nxt: str, fallback: str) -> str:
    """Where an action should return to. Only a same-site path is honoured — a
    caller-supplied absolute URL would make these POST handlers an open redirect."""
    nxt = (nxt or "").strip()
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else fallback


@router.post("/leads/{lead_id}/status")
def inbound_set_status(lead_id: int, status: str = Form(...), next: str = Form("")):
    conn = db.connect()
    try:
        db.update_inbound_lead_status(conn, lead_id, status)
    finally:
        conn.close()
    # Dismissing from Incoming used to land on /leads — a page the left nav does not
    # link — so actioning one row threw away the queue you were working. The form
    # carries where it was submitted from; the lead list stays the fallback.
    return RedirectResponse(_safe_next(next, "/leads"), status_code=303)


@router.post("/leads/{lead_id}/delete")
def inbound_delete(lead_id: int):
    """Permanently remove a Dismissed lead — for clearing out ones already
    addressed, distinct from Dismiss (which just files it out of the New
    queue but keeps the record)."""
    conn = db.connect()
    try:
        db.delete_inbound_lead(conn, lead_id)
    finally:
        conn.close()
    return RedirectResponse("/leads?status=Dismissed", status_code=303)


@router.post("/leads/{lead_id}/promote")
def inbound_promote(lead_id: int):
    """Promote a reviewed lead into the pipeline — the human qualify-gate.

    Builds an Opportunity from the lead's facts and runs it through the same
    insert path (qualify + score + strategic) as any other opportunity, then
    links the lead to it. This is the only way a lead enters the pipeline.
    """
    conn = db.connect()
    try:
        lead = db.get_inbound_lead(conn, lead_id)
        if lead is None:
            return HTMLResponse("Lead not found", status_code=404)
        if lead["linked_opp_id"]:
            return RedirectResponse(
                f"/opportunity/{lead['linked_opp_id']}", status_code=303
            )
        client = (lead["company"] or lead["contact_name"] or "Inbound lead").strip()
        need = (lead["project_type"] or "Inbound commission").strip()
        # Pull the budget out of the captured field, or the "Budget:" line in the
        # pasted post — so a promoted gig shows its real budget, not "Unknown".
        from ..intake import extract_budget

        bmin, bmax = extract_budget(lead["budget_text"] or "")
        if bmin is None and bmax is None:
            bmin, bmax = extract_budget(lead["description"] or "", labeled_only=True)
        opp = Opportunity(
            client=client,
            need=need,
            description=lead["description"] or "",
            budget_min=bmin,
            budget_max=bmax,
            source="front_of_house",
        )
        new_id = db.insert_opportunity(conn, opp)
        if not new_id:
            # Promote failed before linking — don't link to a null id or redirect
            # to a ghost /opportunity/None. Send the human back with an error flag.
            return RedirectResponse("/incoming?error=promote", status_code=303)
        db.link_inbound_to_opp(conn, lead_id, new_id)
        # Carry the lead's contact details onto the new opportunity so the detail
        # page surfaces them up top as tap-to-act links (best-effort).
        try:
            keys = lead.keys()
            db.set_opp_contact(
                conn, new_id,
                contact_name=(lead["contact_name"] or "") if "contact_name" in keys else "",
                contact_email=(lead["contact_email"] or "") if "contact_email" in keys else "",
                contact_phone=(lead["phone"] or "") if "phone" in keys else "",
                contact_linkedin=(lead["contact_linkedin"] or "") if "contact_linkedin" in keys else "",
            )
        except Exception:
            pass
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{new_id}?promoted=1", status_code=303)


# --------------------------------------------------------------------------- #
# Discovery — human-gated crawler ("the machine proposes, Jon disposes")
# --------------------------------------------------------------------------- #
# The system proposes WHERE to look; Jon approves each target; only approved
# targets are ever fetched. Results land in a review queue, never auto-pursued.
@router.get("/discovery", response_class=HTMLResponse)
def discovery_page(request: Request, kind: str = "talent"):
    if kind not in db.CRAWL_KINDS:
        kind = "talent"
    conn = db.connect()
    try:
        targets = db.list_crawl_targets(conn, kind=kind)
        sites = db.list_discovery_sites(conn, kind=kind)
        site_counts = db.discovery_site_counts(conn)
        activity = db.discovery_site_activity(conn)
        attribution = db.source_attribution(conn)
    finally:
        conn.close()
    # Split into the console's sections (Row objects → filter in Python, not Jinja):
    #   • pending_sites  — suggested, non-gated sources awaiting your approval
    #   • gated_sites    — login/ToS-walled sources → manual-assist (never scraped)
    #   • managed_sites  — your active/paused sources with an on/off fetch toggle
    #   • proposed_targets / done_targets — approval queue vs. approved+fetched
    pending_sites = [s for s in sites if s["status"] == "Suggested" and not s["login_gated"]]
    gated_sites = [s for s in sites if s["login_gated"]]
    review_searches = {s["id"]: discovery.manual_assist_searches(s) for s in gated_sites}
    managed_sites = [s for s in sites if not s["login_gated"] and s["status"] != "Suggested"]
    proposed_targets = [t for t in targets if t["status"] == "Proposed"]
    done_targets = [t for t in targets if t["status"] != "Proposed"]
    return render(
        request, "discovery.html", nav="discovery", kind=kind,
        kinds=db.CRAWL_KINDS, scrape_on=discovery.scrape_enabled(),
        site_counts=site_counts, active_states=db.ACTIVE_SITE_STATES,
        activity=activity, pending_sites=pending_sites, gated_sites=gated_sites,
        managed_sites=managed_sites, proposed_targets=proposed_targets,
        done_targets=done_targets, review_searches=review_searches,
        pending_count=len(pending_sites) + len(proposed_targets),
        autofetch=scheduler.status(),
        attribution=attribution,
    )


# --------------------------------------------------------------------------- #
# Signal Engine — the Opportunity Detection layer (freshness × score radar)
# --------------------------------------------------------------------------- #
@router.get("/signals", response_class=HTMLResponse)
def signals_radar(request: Request, push: str = "", triage: str = "", poll: str = ""):
    conn = db.connect()
    try:
        ranked = signals.rank_signals(db.list_signals(conn))
        push_subs = db.push_subscription_count(conn)
    finally:
        conn.close()
    gigs = [x for x in ranked if (x["row"]["signal_type"] or "gig") != "indicator"]
    from . import triage as triage_mod  # local alias: param shadows the module
    return render(
        request, "signals.html", nav="signals", gigs=gigs,
        feeds=scheduler.configured_feeds(),
        push_result=push, push_configured=webpush.is_configured(),
        push_subs=push_subs, push_error=webpush.last_push_error(),
        triage_result=triage, triage_configured=triage_mod.is_configured(),
        triage_status=triage_mod.last_run(), triage_auto=scheduler.triage_status(),
        poll_result=poll, poll_status=scheduler.last_poll(),
        # Which instance is actually running the engines. On one instance this is
        # always "this one" and reads as noise; during a cutover it is the difference
        # between "the engines are stopped" and "the engines are elsewhere", and only
        # one of those is a problem.
        engine_lease=scheduler.lease_status(),
    )


@router.post("/signals/test-push")
def signals_test_push():
    """Fire a test phone alert through the real push pipeline so you can confirm
    your ntfy setup end-to-end. Reports back whether the topic is configured."""
    status = signals.send_push(
        "Chordential test alert",
        body="If you see this on your phone, new-gig alerts are working.",
        click_url="https://chordential.com/signals",
    )
    return RedirectResponse(f"/signals?push={status}", status_code=303)


@router.post("/signals/paste")
def signals_paste(text: str = Form("")):
    """Paste a forwarded saved-search / F5Bot alert → parse into signals."""
    conn = db.connect()
    try:
        signals.ingest_email(conn, "", text, source="paste")
    finally:
        conn.close()
    return RedirectResponse("/signals", status_code=303)


@router.post("/signals/ingest")
async def signals_ingest(request: Request, token: str = "", source: str = "email"):
    """Email-in webhook (Phase 2 backbone) — a mail service POSTs a forwarded
    alert here. Protected by a shared secret (CHORDENTIAL_SIGNAL_TOKEN), not the
    admin cookie, since it's machine-to-machine."""
    secret = os.environ.get("CHORDENTIAL_SIGNAL_TOKEN")
    if not secret or token != secret:
        return PlainTextResponse("unauthorized", status_code=401)
    ctype = request.headers.get("content-type", "")
    subject = ""
    if "form" in ctype or "urlencoded" in ctype:
        form = await request.form()       # Mailgun / SendGrid inbound parse
        body = (form.get("body-plain") or form.get("stripped-text")
                or form.get("text") or form.get("body") or "")
        subject = form.get("subject") or ""
    else:
        body = (await request.body()).decode("utf-8", "replace")
    conn = db.connect()
    try:
        n = signals.ingest_email(conn, str(subject), str(body), source=source)
    finally:
        conn.close()
    return {"ingested": n}


@router.post("/signals/{signal_id}/promote")
def signal_promote(signal_id: int):
    """Promote a signal into the pipeline — the same human gate leads use."""
    conn = db.connect()
    try:
        s = db.get_signal(conn, signal_id)
        if s is None:
            return HTMLResponse("Signal not found", status_code=404)
        if s["linked_opp_id"]:
            return RedirectResponse(f"/opportunity/{s['linked_opp_id']}", status_code=303)
        opp = Opportunity(
            client="Unknown", need=s["title"] or "Detected opportunity",
            description=s["body"] or "", budget_min=s["budget_min"],
            budget_max=s["budget_max"], source="signal", url=s["url"] or "",
        )
        new_id = db.insert_opportunity(conn, opp)
        # Carry the poster's handle so the channel-aware Respond button can DM them.
        handle = s["contact_handle"] if "contact_handle" in s.keys() else None
        if handle:
            db.set_contact_handle(conn, new_id, handle)
        db.link_signal_to_opp(conn, signal_id, new_id)
        triage.record_feedback(s, "promoted")   # B3 — a triaged gig the human kept
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{new_id}", status_code=303)


@router.get("/signals/count")
def signals_count():
    """Live count of unactioned gigs — polled by the nav badge."""
    conn = db.connect()
    try:
        return {"new": db.new_signal_count(conn)}
    finally:
        conn.close()


@router.post("/signals/clear")
def signals_clear():
    """Wipe the open radar — start fresh after a filter change."""
    conn = db.connect()
    try:
        db.clear_signals(conn)
    finally:
        conn.close()
    return RedirectResponse("/signals", status_code=303)


@router.post("/signals/{signal_id}/status")
def signal_set_status(signal_id: int, status: str = Form(...), next: str = Form("")):
    conn = db.connect()
    try:
        if status.strip().lower() == "dismissed":   # B3 — a triaged gig the human rejected
            s = db.get_signal(conn, signal_id)
            if s is not None:
                triage.record_feedback(s, "dismissed")
        db.set_signal_status(conn, signal_id, status)
    finally:
        conn.close()
    return RedirectResponse(_safe_next(next, "/signals"), status_code=303)


@router.post("/discovery/lead")
def discovery_add_lead(
    title: str = Form(...),
    company: str = Form(""),
    link: str = Form(""),
    notes: str = Form(""),
    budget: str = Form(""),
):
    """Capture a lead by hand from a manual-assist source — closes the launchpad
    loop (open the right search → see a gig → add it). Lands in the same Inbound
    Leads review queue as everything else."""
    title = title.strip()
    if not title:
        return RedirectResponse("/discovery?kind=opportunity", status_code=303)
    desc = notes.strip()
    if link.strip():
        desc = (desc + ("\n" if desc else "") + link.strip()).strip()
    conn = db.connect()
    try:
        db.insert_inbound_lead(
            conn, contact_name="(added by hand)", company=company.strip(),
            project_type=title, description=desc, budget_text=budget.strip(),
            source="manual",
        )
    finally:
        conn.close()
    return RedirectResponse("/leads", status_code=303)


@router.post("/discovery/generate")
def discovery_generate(
    kind: str = Form("talent"), location: str = Form(""), terms: str = Form("")
):
    """Propose targets from the active curated sites (deterministic, no fetching)."""
    conn = db.connect()
    try:
        discovery.generate_targets(
            conn, kind, keyword=terms.strip() or None,
            location=location.strip() or None,
        )
    finally:
        conn.close()
    return RedirectResponse(f"/discovery?kind={kind}", status_code=303)


@router.post("/discovery/site/{site_id}/status")
def discovery_site_decide(
    site_id: int, status: str = Form(...), kind: str = Form("talent")
):
    """Approve or reject a suggested site — Jon's permission before it can be
    scanned. Turning a source On (Approved/Established) also seeds a default
    Approved target so it starts fetching immediately."""
    conn = db.connect()
    try:
        db.update_discovery_site_status(conn, site_id, status)
        if status in db.ACTIVE_SITE_STATES:
            site_row = db.get_discovery_site(conn, site_id)
            if site_row is not None:
                discovery.seed_active_targets(conn, site_row)
    finally:
        conn.close()
    return RedirectResponse(f"/discovery?kind={kind}", status_code=303)


@router.post("/discovery/site/add")
def discovery_site_add(
    name: str = Form(...),
    url: str = Form(...),
    kind: str = Form("opportunity"),
    rationale: str = Form(""),
):
    """Jon points the crawler at his own site/area. Added as an active custom
    site (his own call) and a Proposed target so it's ready to approve + fetch.
    Put ``{q}`` in the URL to make it keyword-driven on later generations."""
    if kind not in db.CRAWL_KINDS:
        kind = "opportunity"
    name = name.strip()
    url = url.strip()
    if not (name and url):
        return RedirectResponse(f"/discovery?kind={kind}", status_code=303)
    key = "custom-" + (slug(name) or "site")
    conn = db.connect()
    try:
        db.upsert_discovery_site(
            conn, key=key, name=name, homepage=url, kind=kind, category="Custom",
            recommended_by="Jon (CEO)", rationale=rationale.strip() or "Added by Jon.",
            status="Approved", board_url=url,
        )
        # Immediately propose a target for it so it's ready to approve + fetch.
        row = db.get_discovery_site_by_key(conn, key)
        t = discovery._custom_site_target(row, kind, None, None)
        if t:
            db.insert_crawl_target(
                conn, t["kind"], t["label"], t["query"], t["url"],
                t["source_key"], t["rationale"],
            )
    finally:
        conn.close()
    return RedirectResponse(f"/discovery?kind={kind}", status_code=303)


@router.post("/discovery/{target_id}/status")
def discovery_decide(target_id: int, status: str = Form(...), kind: str = Form("talent")):
    """Approve or dismiss a proposed target — Jon's explicit go-ahead/refusal."""
    conn = db.connect()
    try:
        db.update_crawl_target_status(conn, target_id, status)
    finally:
        conn.close()
    return RedirectResponse(f"/discovery?kind={kind}", status_code=303)


@router.post("/discovery/{target_id}/fetch")
def discovery_fetch(target_id: int, kind: str = Form("talent")):
    """Fetch an Approved target. Refuses anything not Approved (the gate)."""
    conn = db.connect()
    try:
        target = db.get_crawl_target(conn, target_id)
        if target is None:
            return HTMLResponse("Target not found", status_code=404)
        if target["status"] != "Approved":
            return RedirectResponse(f"/discovery?kind={kind}", status_code=303)
        discovery.run_target(conn, target)
    finally:
        conn.close()
    return RedirectResponse(f"/discovery?kind={kind}", status_code=303)


# --------------------------------------------------------------------------- #
# Inbox (search + filtering + ranking)
# --------------------------------------------------------------------------- #
