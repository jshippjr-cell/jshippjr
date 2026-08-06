"""Agency Intelligence — the buyer-discovery surface, as its own router.

ADR-0044, the first slice of the ``app.py`` breakup. This group was chosen on
measurement, not taste: 26 routes (10% of the file) referencing only four helpers
defined in ``app.py``, against 23 and 29 for ``/opportunity`` and ``/project``. It
also has **no** route-pattern collision with any other group and only one route
interleaved in its span, so the block could move without changing which handler
answers any URL.

The two helpers that were only ever used here — ``_profile_from_row`` (shared with
one ``/sources`` route, which now imports it from this module) and
``_decision_maker_view`` — moved with it. Everything else comes from ``shell.py``
or a sibling engine module, so this file does not import ``app.py`` and no cycle
exists.

Routes are registered on an ``APIRouter`` and included by ``app.py``. Registration
order within the group is unchanged, which is what makes the move a no-op to
FastAPI's matcher.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from .. import mailer
from . import (
    db, directory_crawl, directory_parsers, enrichment, intelligence,
    music_opportunity, opportunity_signals, outreach_engine, relationships,
    scheduler, signals,
)
from .shell import public_base as _public_base, render

router = APIRouter(tags=["agencies"])

AGENCIES_PAGE_SIZE = 50
# Marker the enrichment state blob carries when an agency is fully enriched —
# lets us filter/paginate by status in SQL without an N+1 over thousands of rows.
_COMPLETE_MARKER = '%"status": "complete"%'


def _profile_from_row(row) -> dict:
    """Parse the stored Agency Profile (+ status) off an agencies row's JSON blob,
    with no extra query — so a page of 50 costs 50 zero-DB parses, not 50 reads."""
    raw = row["enrichment_json"]
    state = {}
    if raw:
        try:
            state = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            state = {}
    profile = enrichment.AgencyProfile.from_dict(state.get("profile")).to_dict()
    if not profile.get("company"):
        profile["company"] = row["company"] or ""
    if not profile.get("website"):
        profile["website"] = row["website"] or ""
    return {"status": state.get("status", ""), "profile": profile}


@router.get("/agencies", response_class=HTMLResponse)
def agencies_page(request: Request, source: str = "", enriched: str = "",
                  page: int = 1, ingested: str = "", new: str = "", added: str = "",
                  crawled: str = "", pages: str = "", cstatus: str = "",
                  eb_started: str = "", eb_n: str = "",
                  rb_started: str = "", rb_n: str = "",
                  dm_started: str = "", dm_n: str = "",
                  intel_started: str = "", intel_n: str = "", sig_started: str = "",
                  score_started: str = ""):
    """Paginated accordion of harvested agencies; each row expands to its enriched
    Agency Profile inline. Filter/paginate happen in SQL so this scales to
    thousands of rows."""
    page = max(1, page)
    conn = db.connect()
    try:
        all_sources = [r["source"] for r in conn.execute(
            "SELECT DISTINCT source FROM agencies WHERE source IS NOT NULL "
            "ORDER BY source")]
        where, params = [], []
        if source:
            where.append("source = ?"); params.append(source)
        if enriched == "yes":
            where.append("enrichment_json LIKE ?"); params.append(_COMPLETE_MARKER)
        elif enriched == "no":
            where.append("(enrichment_json IS NULL OR enrichment_json NOT LIKE ?)")
            params.append(_COMPLETE_MARKER)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        matched = conn.execute(
            f"SELECT COUNT(*) c FROM agencies{wsql}", params).fetchone()["c"]
        offset = (page - 1) * AGENCIES_PAGE_SIZE
        rows = conn.execute(
            f"SELECT * FROM agencies{wsql} ORDER BY company COLLATE NOCASE "
            "LIMIT ? OFFSET ?", (*params, AGENCIES_PAGE_SIZE, offset)).fetchall()
        agencies = []
        for r in rows:
            pp = _profile_from_row(r)
            agencies.append({
                "id": r["id"], "company": r["company"], "website": r["website"],
                "location": r["location"], "source": r["source"],
                "status": pp["status"] or "—", "profile": pp["profile"],
            })
        pending = db.count_needing_enrichment(conn, source or None)
        dm_pending = db.count_needing_decision_makers(conn, source or None)
        dm_total = db.count_decision_makers(conn)
        intel_pending = db.count_needing_intelligence(conn, source or None)
        sig_total = db.count_opportunity_signals(conn, active_only=True)
        movers = [{"id": r["id"], "company": r["company"],
                   "score": r["opportunity_score"], "tier": r["opportunity_tier"],
                   "movement": r["score_movement"]}
                  for r in db.top_movers(conn, limit=6, source=source or None)]
        top_opps = [{"id": r["id"], "company": r["company"],
                     "score": r["opportunity_score"], "tier": r["opportunity_tier"]}
                    for r in db.top_opportunities(conn, limit=6, source=source or None)]
        total = db.count_agencies(conn, source or None)
        crawl_states = []
        for key in directory_parsers.SOURCE_FACTORIES:
            st = db.get_crawl_state(conn, key)
            crawl_states.append({
                "key": key,
                "status": (st["status"] if st else "idle"),
                "pages_done": (st["pages_done"] if st else 0) or 0,
                "total_pages": (st["total_pages"] if st else None),
                "records_new": (st["records_new"] if st else 0) or 0,
                "detail": (st["detail"] if st else "") or "",
                "stored": db.count_agencies(conn, key),
                "crawlable": key not in directory_parsers.PASTE_ONLY_SOURCES,
                "note": directory_parsers.PASTE_ONLY_SOURCES.get(key, ""),
            })
    finally:
        conn.close()
    page_count = max(1, -(-matched // AGENCIES_PAGE_SIZE))  # ceil
    from . import setup_agencies
    return render(request, "agencies.html", nav="agencies", agencies=agencies,
                  sources=all_sources, source=source, enriched=enriched,
                  pending=pending, total=total, matched=matched,
                  page=page, page_count=page_count,
                  ingest_sources=directory_parsers.INGEST_SOURCES,
                  ingested=ingested, new=new, added=added,
                  setup_count=setup_agencies.setup_count(),
                  crawl_states=crawl_states, crawled=crawled, pages=pages,
                  cstatus=cstatus, pages_per_click=PAGES_PER_CRAWL_CLICK,
                  eb_started=eb_started, eb_n=eb_n,
                  rb_started=rb_started, rb_n=rb_n,
                  auto_reenrich=scheduler.reenrich_status(),
                  dm_started=dm_started, dm_n=dm_n,
                  dm_pending=dm_pending, dm_total=dm_total,
                  intel_started=intel_started, intel_n=intel_n,
                  intel_pending=intel_pending,
                  sig_started=sig_started, sig_total=sig_total,
                  auto_enrich=scheduler.enrich_status(),
                  auto_dm=scheduler.dm_status(),
                  auto_intel=scheduler.intel_status(),
                  auto_signals=scheduler.signals_engine_status(),
                  auto_score=scheduler.score_status(),
                  score_started=score_started, movers=movers, top_opps=top_opps,
                  scrape_on=enrichment.scrape_enabled())


@router.post("/agencies/ingest")
def agencies_ingest(source: str = Form(...), html: str = Form("")):
    """Parse a pasted directory/listing page with that source's parser and store
    the agencies in the Master Company Database. Deterministic — it reads only the
    page you paste, so it never depends on the directory site being reachable."""
    records = directory_parsers.parse_listing(source, html or "")
    new_count = 0
    conn = db.connect()
    try:
        for rec in records:
            if db.upsert_agency(conn, source, rec.to_db()):
                new_count += 1
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(
        f"/agencies?source={source}&ingested={len(records)}&new={new_count}#add-panel",
        status_code=303)


# How many directory pages one "Crawl" click walks. Bounded so the request
# returns quickly; the crawl is resumable (checkpointed per page), so pressing
# Crawl again continues from where it stopped.
PAGES_PER_CRAWL_CLICK = 5


@router.post("/agencies/crawl")
def agencies_crawl(source: str = Form(...), reset: str = Form("")):
    """Run the LIVE paginating directory crawl for one source, a bounded number
    of pages per click (resumable). Actually fetches the directory only where
    scraping is enabled (Render); in the sandbox, or if the directory blocks the
    request, it reports the failure honestly rather than inventing rows."""
    factory_base = directory_parsers.SOURCE_FACTORIES.get(source)
    if not factory_base:
        return RedirectResponse("/agencies", status_code=303)
    factory, base = factory_base
    conn = db.connect()
    try:
        do_reset = bool(reset)
        st = db.get_crawl_state(conn, source)
        start = 1 if do_reset else ((st["next_page"] if st and st["next_page"] else 1))
        summary = directory_crawl.run_crawl(
            conn, source, factory(base),
            max_pages=start + PAGES_PER_CRAWL_CLICK - 1, reset=do_reset)
    finally:
        conn.close()
    return RedirectResponse(
        f"/agencies?source={source}&crawled={summary['records_new']}"
        f"&pages={summary['pages_done']}&cstatus={summary['outcome']}#crawl-panel",
        status_code=303)


@router.get("/agencies/status")
def agencies_status(source: str = ""):
    """Live JSON snapshot of the background engines + pending counts, for the
    /agencies page to poll and update its progress in place — instead of blindly
    reloading the whole page every 15s (which cost ~8 table scans a tick and wiped
    any half-typed form input). Cheap: status dicts + a few COUNT(*) queries, no
    agency rows materialized."""
    src = source or None
    conn = db.connect()
    try:
        counts = {
            "enrich": db.count_needing_enrichment(conn, src),
            "dm": db.count_needing_decision_makers(conn, src),
            "intel": db.count_needing_intelligence(conn, src),
        }
    finally:
        conn.close()
    engines = {
        "enrich": scheduler.enrich_status(),
        "reenrich": scheduler.reenrich_status(),
        "dm": scheduler.dm_status(),
        "intel": scheduler.intel_status(),
        "signals": scheduler.signals_engine_status(),
        "score": scheduler.score_status(),
    }
    any_running = any(bool(e.get("running")) for e in engines.values())
    return JSONResponse({"engines": engines, "counts": counts,
                         "any_running": any_running})


@router.post("/agencies/enrich-pending")
def agencies_enrich_pending(limit: str = Form("")):
    """Manually nudge the agent to enrich a batch of enrichable agencies now (the
    background scheduler does this on its own; this is the on-demand push).

    Fire-and-forget: a batch of live-site enrichments takes minutes — far longer
    than an HTTP request can wait — so we kick it off in a background thread and
    return immediately. Progress shows up in the auto-enrichment status card on
    refresh. Re-press to queue more once the running pass finishes."""
    # 25 at a time. Safe to do a real batch now that enrichment runs in a separate,
    # killable worker process (a hostile page can't pin or freeze the web server) —
    # the worker does them one at a time, paced, and a watchdog reaps any runaway.
    n = 25
    try:
        n = max(1, min(50, int(limit)))
    except (TypeError, ValueError):
        n = 25
    started = scheduler.start_manual_enrich(n)
    return RedirectResponse(
        f"/agencies?eb_started={'1' if started else '0'}&eb_n={n}",
        status_code=303)


@router.post("/agencies/reenrich-pending")
def agencies_reenrich_pending(limit: str = Form("")):
    """Nudge a batch of re-enrichment now — refresh stale agencies' data so the
    Signal Detection Framework has fresh changes to diff. Fire-and-forget (re-
    fetching sites takes minutes); the background scheduler also does this on its
    own cadence."""
    n = 10
    try:
        n = max(1, min(50, int(limit)))
    except (TypeError, ValueError):
        n = 10
    started = scheduler.start_manual_reenrich(n)
    return RedirectResponse(
        f"/agencies?rb_started={'1' if started else '0'}&rb_n={n}",
        status_code=303)


@router.post("/agencies/decision-makers-pending")
def agencies_dm_pending(limit: str = Form("")):
    """Nudge a batch of decision-maker discovery now — fire-and-forget, same as
    enrich-pending (a batch of live crawls takes minutes). The background scheduler
    also does this on its own; progress shows in the discovery status card."""
    n = 25
    try:
        n = max(1, min(50, int(limit)))
    except (TypeError, ValueError):
        n = 25
    started = scheduler.start_manual_dm(n)
    return RedirectResponse(
        f"/agencies?dm_started={'1' if started else '0'}&dm_n={n}",
        status_code=303)


@router.post("/agencies/intelligence-pending")
def agencies_intel_pending(limit: str = Form("")):
    """Nudge a batch of Company Intelligence generation now — fire-and-forget; the
    background scheduler also does this on its own. Progress shows in the
    intelligence status card."""
    n = 25
    try:
        n = max(1, min(100, int(limit)))
    except (TypeError, ValueError):
        n = 25
    started = scheduler.start_manual_intel(n)
    return RedirectResponse(
        f"/agencies?intel_started={'1' if started else '0'}&intel_n={n}",
        status_code=303)


@router.post("/agencies/signals-pending")
def agencies_signals_pending(limit: str = Form("")):
    """Nudge a batch of signal detection now — fire-and-forget; the background
    scheduler also sweeps on its own. Progress shows in the signals status card."""
    n = 100
    try:
        n = max(1, min(500, int(limit)))
    except (TypeError, ValueError):
        n = 100
    started = scheduler.start_manual_signals(n)
    return RedirectResponse(
        f"/agencies?sig_started={'1' if started else '0'}",
        status_code=303)


@router.post("/agencies/score-pending")
def agencies_score_pending(limit: str = Form("")):
    """Nudge a batch of Music Opportunity scoring now — fire-and-forget; the
    background scheduler also re-scores on its own."""
    n = 100
    try:
        n = max(1, min(1000, int(limit)))
    except (TypeError, ValueError):
        n = 100
    started = scheduler.start_manual_score(n)
    return RedirectResponse(
        f"/agencies?score_started={'1' if started else '0'}",
        status_code=303)


@router.post("/agencies/import-setup")
def agencies_import_setup():
    """Load the agencies recovered from the directory pages pasted during setup
    (committed seed) into the Master Company Database — the one-click populate."""
    from . import setup_agencies
    conn = db.connect()
    try:
        res = setup_agencies.load(conn)
    finally:
        conn.close()
    return RedirectResponse(
        f"/agencies?ingested={res['total']}&new={res['new']}", status_code=303)


@router.post("/agencies/add")
def agencies_add(company: str = Form(...), website: str = Form(""),
                 location: str = Form("")):
    """Add a single agency by hand (source 'manual') — the quickest way to seed a
    row you can immediately Enrich."""
    from .directory_crawl import AgencyRecord
    rec = AgencyRecord(company=company.strip(), website=website.strip(),
                       location=location.strip())
    ok = bool(rec.company)
    if ok:
        conn = db.connect()
        try:
            db.upsert_agency(conn, "manual", rec.to_db())
            conn.commit()
        finally:
            conn.close()
    return RedirectResponse(
        f"/agencies?source=manual&added={'1' if ok else '0'}#add-panel",
        status_code=303)


@router.get("/agencies/{agency_id}", response_class=HTMLResponse)
def agency_detail(request: Request, agency_id: int):
    """One agency's enriched Agency Profile (or the empty shell before a run)."""
    conn = db.connect()
    try:
        row = db.get_agency(conn, agency_id)
        if row is None:
            return PlainTextResponse("No such agency", status_code=404)
        state = db.get_agency_enrichment(conn, agency_id) or {}
        dm_rows = [_decision_maker_view(r) for r in
                   db.list_decision_makers(conn, agency_id)]
        intel = db.get_agency_intel(conn, agency_id) or {}
        timeline = opportunity_signals.agency_timeline(conn, agency_id)
        opportunity = db.get_agency_score(conn, agency_id) or {}
        outreach = [dict(o) for o in db.list_agency_outreach(conn, agency_id)]
        relationships.seed_memory(conn, agency_id)       # institutional memory
        relationship = relationships.relationship_view(conn, agency_id)
        outreach_ws = outreach_engine.outreach_workspace(conn, agency_id)
    finally:
        conn.close()
    profile = enrichment.AgencyProfile.from_dict(state.get("profile")).to_dict()
    if not profile.get("company"):
        profile["company"] = row["company"]
    if not profile.get("website"):
        profile["website"] = row["website"]
    return render(request, "agency_detail.html", nav="agencies",
                  agency={"id": row["id"], "company": row["company"],
                          "website": row["website"], "source": row["source"]},
                  profile=profile, status=state.get("status", ""),
                  detail=state.get("detail", ""),
                  steps_done=state.get("steps_done", []),
                  decision_makers=dm_rows, intel=intel, timeline=timeline,
                  opportunity=opportunity, outreach=outreach,
                  relationship=relationship, stages=relationships.STAGES,
                  outreach_ws=outreach_ws, mail_configured=mailer.mail_configured(),
                  sent=request.query_params.get("sent", ""),
                  scrape_on=enrichment.scrape_enabled())


def _decision_maker_view(r) -> dict:
    """Flatten a decision_makers row for the template (JSON blobs → objects)."""
    def _loads(v, default):
        try:
            return json.loads(v) if v else default
        except (json.JSONDecodeError, TypeError):
            return default
    return {
        "name": r["name"], "title": r["title"], "department": r["department"],
        "bio": r["bio"], "photo_url": r["photo_url"],
        "linkedin": r["linkedin"], "email": r["email"], "phone": r["phone"],
        "social": _loads(r["social_json"], {}),
        "source_urls": _loads(r["source_urls_json"], []),
        "press": _loads(r["press_json"], []),
        "role_category": r["role_category"], "priority": r["priority"],
        "music_relevance": r["music_relevance"],
        "relevance_reason": r["relevance_reason"],
        "confidence": r["confidence"],
        "linkedin_verified": bool(r["linkedin_verified"]),
        "classified_by": r["classified_by"], "last_verified": r["last_verified"],
    }


@router.post("/agencies/{agency_id}/decision-makers")
def agency_find_decision_makers(agency_id: int, reset: str = Form("")):
    """Discover ONE agency's decision makers — visit its leadership/team/about
    pages, extract every person, classify + score them. Fire-and-forget: it fetches
    live pages (slow), so running it inline spins the request — instead it runs in
    the background and the page shows results on refresh. Safe to re-press."""
    scheduler.start_agency_decision_makers(agency_id, reset=bool(reset))
    return RedirectResponse(f"/agencies/{agency_id}#decision-makers", status_code=303)


@router.post("/agencies/{agency_id}/intelligence")
def agency_generate_intelligence(agency_id: int):
    """Generate the Company Intelligence Profile for ONE agency from its collected
    data. Pure computation (no network), so it runs inline and returns at once —
    safe to re-run; it just refreshes from the latest collected data."""
    conn = db.connect()
    try:
        intelligence.generate_intelligence(conn, agency_id)
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#intelligence", status_code=303)


@router.post("/agencies/{agency_id}/signals")
def agency_detect_signals(agency_id: int):
    """Scan ONE agency for new opportunity signals (change detection over its
    collected profile). Pure computation; runs inline. First scan baselines the
    agency, later scans surface what's new."""
    conn = db.connect()
    try:
        opportunity_signals.detect_signals(conn, agency_id, force=True)
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#timeline", status_code=303)


@router.post("/agencies/{agency_id}/score")
def agency_score(agency_id: int):
    """Recompute the Music Opportunity score for ONE agency from its collected
    intelligence + signals + outreach. Pure reasoning; runs inline."""
    conn = db.connect()
    try:
        music_opportunity.score_agency(conn, agency_id)
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#opportunity", status_code=303)


@router.post("/agencies/{agency_id}/outreach")
def agency_log_outreach(agency_id: int, kind: str = Form("email"),
                        contact: str = Form(""), note: str = Form(""),
                        responded: str = Form("")):
    """Log a touch in the relationship history. The Reminder Agent then ensures a
    follow-up, and the score re-runs (outreach lowers Relationship Readiness — the
    score reacts immediately)."""
    conn = db.connect()
    try:
        db.log_agency_outreach(conn, agency_id, kind=kind or "email",
                               contact=contact, note=note, responded=bool(responded))
        conn.commit()
        relationships.ensure_followup(conn, agency_id, contact=contact)
        music_opportunity.score_agency(conn, agency_id)
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#opportunity", status_code=303)


@router.post("/agencies/{agency_id}/outreach/send")
def agency_send_outreach(agency_id: int, subject: str = Form(""),
                         body: str = Form(""), email: str = Form(""),
                         contact: str = Form(""), angle: str = Form("")):
    """Actually SEND an agency outreach draft through the mailer seam, then log the
    touch (so the relationship history + score react exactly as 'Log as sent' does).
    The drafts used to dead-end at 'Log as sent' — recording a touch that never sent
    anything. Falls back to ?sent=manual when mail isn't configured or there's no
    recipient email; the panel then offers Copy / Open-in-mail instead."""
    email = (email or "").strip()
    if not email or not mailer.mail_configured():
        return RedirectResponse(
            f"/agencies/{agency_id}?sent=manual#opportunity", status_code=303)
    base = _public_base()
    status = mailer.send_email(email, subject or "Chordential", body or "",
                               html=mailer.branded_html(base, body or ""))
    if status == "sent":
        conn = db.connect()
        try:
            db.log_agency_outreach(conn, agency_id, kind="email", contact=contact,
                                   note=(f"{angle}: {subject}".strip(": ") or "email"))
            conn.commit()
            relationships.ensure_followup(conn, agency_id, contact=contact)
            music_opportunity.score_agency(conn, agency_id)
        finally:
            conn.close()
    return RedirectResponse(
        f"/agencies/{agency_id}?sent={status}#opportunity", status_code=303)


@router.post("/agencies/{agency_id}/relationship/stage")
def agency_set_stage(agency_id: int, stage: str = Form(...)):
    """Manually override the relationship stage (the Relationship Agent's auto
    derivation is the default; this pins it) — "the machine proposes, Jon disposes".

    Refused if it is not a stage: the override is READ BACK as the answer on two pages
    now (ADR-0057), so a value outside the vocabulary would pin one company to a stage
    no filter can select and no rule can ever clear.
    """
    if stage not in relationships.STAGES:
        return PlainTextResponse(f"Not a relationship stage: {stage}", status_code=400)
    conn = db.connect()
    try:
        db.upsert_relationship(conn, agency_id, stage=stage, stage_overridden=1)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#relationship", status_code=303)


@router.post("/agencies/{agency_id}/relationship/task")
def agency_add_task(agency_id: int, title: str = Form(...), due_at: str = Form("")):
    conn = db.connect()
    try:
        db.add_agency_task(conn, agency_id, title=title, due_at=due_at)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#relationship", status_code=303)


@router.post("/agencies/{agency_id}/relationship/task/{task_id}/done")
def agency_complete_task(agency_id: int, task_id: int):
    conn = db.connect()
    try:
        db.complete_agency_task(conn, task_id)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#relationship", status_code=303)


@router.post("/agencies/{agency_id}/relationship/memory")
def agency_add_memory(agency_id: int, fact: str = Form(...), contact: str = Form("")):
    conn = db.connect()
    try:
        db.add_agency_memory(conn, agency_id, fact=fact, contact=contact)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#relationship", status_code=303)


@router.post("/agencies/{agency_id}/relationship/document")
def agency_add_document(agency_id: int, title: str = Form(...), url: str = Form(""),
                        note: str = Form("")):
    conn = db.connect()
    try:
        db.add_agency_document(conn, agency_id, title=title, url=url, note=note)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#relationship", status_code=303)


@router.post("/agencies/{agency_id}/enrich")
def agency_enrich(agency_id: int, reset: str = Form("")):
    """Run the Company Enrichment Engine on ONE agency. Fire-and-forget: it reads
    the agency's live website (homepage + ~10 sub-pages), which is far too slow to
    do inside the request — so it runs in the background and the profile fills in on
    refresh. Safe to re-press: it resumes unless 'reset' is set."""
    scheduler.start_agency_enrich(agency_id, reset=bool(reset))
    return RedirectResponse(f"/agencies/{agency_id}", status_code=303)


@router.post("/agencies/{agency_id}/pipeline")
def agency_full_pipeline(agency_id: int, reset: str = Form("")):
    """One press → build the COMPLETE profile for this agency: enrich → decision
    makers → intelligence → signals → score, run in order in a single background
    job. Returns instantly; the page fills in over the next minute on refresh."""
    scheduler.start_agency_pipeline(agency_id, reset=bool(reset))
    return RedirectResponse(f"/agencies/{agency_id}", status_code=303)


