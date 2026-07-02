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

import hashlib
import hmac
import json
import os
import re
from contextlib import asynccontextmanager
from typing import List, Optional
from urllib.parse import quote, unquote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (
    HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..estimation import ROLE_RATES, RoleLine
from ..invoicing import build_invoice
from .. import mailer
from .. import recruiting
from ..models import BuyerValue, MusicDiscipline, Opportunity
from ..payments import get_payment_provider
from ..proposals import Proposal, build_proposal
from ..prepare import build_pursuit_brief
from ..outreach import (
    COMPOSE_BLOCK_KEYS, assemble_email, build_compose_blocks, build_outreach_plan,
    compose_selection, respond_action, _mailto,
)
from ..capabilities import (
    DELIVERY_TEMPLATES, SECTION_FAMILY, build_capabilities_doc, build_understanding,
    chips_for, default_toggles,
)
from ..delivery import (
    brief_rollup, build_clearance_certificate, build_cue_sheet,
    build_delivery_zip, build_manifest, build_timeline, current_version,
    delivery_completeness,
    license_confirmation, merge_license, merge_signatory, reconcile_brief,
    revision_status, scoped_deliverables, seed_brief, version_label,
    versions_list, version_name,
    ASSIGNABLE_FOLDERS, BRIEF_FIELDS, DELIVERY_STATES, VERSION_STATES,
)
from ..strategic import assess_strategic_value
from ..talent import Talent, normalize_url, profile_completeness
from ..matching import match_talent
from . import (
    db, decision_makers, directory_crawl, directory_parsers, discovery,
    enrichment, intelligence, music_opportunity, opportunity_signals,
    outreach_engine, relationships, scheduler, seed, signals, sources, triage,
    webpush,
)
from .buyer_intel import assess_relationship, days_since
from .estimate import build_estimate
from .evaluate import evaluate
from .filters import displayurl, money, pct, slug
from .public import router as public_router

_HERE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))

# Founder-uploaded audio samples for the "Relevant work" section. Path is
# overridable (CHORDENTIAL_UPLOAD_DIR) with a module-relative default; created on
# import so the upload + serve routes can rely on it existing.
# NOTE (honest persistence caveat): files saved to this local disk are NOT durable
# on Render once the persistent disk is removed for the zero-downtime (blue-green)
# cutover — durable storage needs object storage (S3/R2). Acceptable for now.
UPLOAD_DIR = os.environ.get("CHORDENTIAL_UPLOAD_DIR") or os.path.join(_HERE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Audio uploads we accept for relevant-work samples.
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


# --------------------------------------------------------------------------- #
# Jinja helpers (filter functions live in .filters — shared with the public site)
# --------------------------------------------------------------------------- #
# One-click pipeline advance for the Overview action bar. Won is intentionally
# omitted — closing a deal goes through the win/loss form so the value is captured.
_NEXT_STATUS = {"New": "Pursuing", "Pursuing": "Submitted"}

# Stepper "expected next step" (Phase 5, ruling #7). Extends the linear flow all the
# way to Won — kept separate from _NEXT_STATUS so the action-bar's "close via the
# win/loss form" behaviour is undisturbed. New → Reaching out → Proposal out → Won.
_STEPPER_NEXT = {"New": "Pursuing", "Pursuing": "Submitted", "Submitted": "Won"}

# Status kanban (Pipeline) — the human pipeline as columns, with a one-click
# forward advance. Won is terminal; the Submitted ("Proposal out") column offers
# the win/loss decision directly. Lost + Passed collapse into one "Closed" column
# (ruling #2) — friendly labels are applied at the view layer via stage_label.
_KANBAN_STAGES = ["New", "Pursuing", "Submitted", "Won"]
# Statuses folded into the single trailing "Closed" archive column.
_CLOSED_STAGES = ["Lost", "Passed"]


def _safe_local(path: str, fallback: str) -> str:
    """Only redirect to a same-site path (guards the ``return_to`` field)."""
    if path and path.startswith("/") and not path.startswith("//"):
        return path
    return fallback


_ACTION_CLASS = {"Pursue": "pursue", "Review": "review", "Watch": "watch", "Pass": "pass"}
_TIER_CLASS = {"A-Tier": "a", "B-Tier": "b", "C-Tier": "c", "Watch": "watch"}
_STATUS_CLASS = {
    "New": "new", "Pursuing": "pursuing", "Submitted": "submitted",
    "Won": "won", "Lost": "lost", "Passed": "passed",
}

templates.env.filters["money"] = money
templates.env.filters["pct"] = pct
templates.env.filters["slug"] = slug
templates.env.filters["displayurl"] = displayurl
templates.env.globals["action_class"] = lambda a: _ACTION_CLASS.get(a, "")
templates.env.globals["tier_class"] = lambda t: _TIER_CLASS.get(t, "")
templates.env.globals["status_class"] = lambda s: _STATUS_CLASS.get(s, "")
_STRAT_CLASS = {"Door-opener": "door", "High": "high", "Medium": "medium", "Low": "low"}
templates.env.globals["strat_class"] = lambda s: _STRAT_CLASS.get(s, "")
templates.env.globals["PIPELINE_STATES"] = db.PIPELINE_STATES
# View-layer stage relabel (ruling #2): friendly label for a raw pipeline status.
templates.env.globals["stage_label"] = db.stage_label
templates.env.filters["stage_label"] = db.stage_label
# True only when the internal gate is active (CHORDENTIAL_ADMIN_TOKEN set).
templates.env.globals["admin_gate_on"] = bool(os.environ.get("CHORDENTIAL_ADMIN_TOKEN"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn)
    discovery.sync_catalog(conn)
    discovery.seed_all_active(conn)  # On sources get a default target → they fetch
    if seed.seed_demo_enabled():     # dev/tests: populate placeholder data
        if conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 0:
            seed.seed(conn)
        seed.seed_talent(conn)
        seed.ingest_talent_prospects(conn)
        seed.seed_demo_pipeline(conn)
        seed.seed_delivery_demo(conn)  # P5: fictional campaigns at every stage
    else:                            # production: clean slate — real data only
        seed.purge_demo_data(conn)
    conn.execute("DELETE FROM signals WHERE signal_type = 'indicator'")  # feature dropped
    conn.commit()
    conn.close()
    # Background auto-fetcher (Phase 2): runs in-process, no-ops unless scraping
    # is enabled. Cancelled cleanly on shutdown.
    import asyncio

    autofetch_task = asyncio.create_task(scheduler.run_loop())
    try:
        yield
    finally:
        autofetch_task.cancel()


app = FastAPI(title="Chordential — Procurement OS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(_HERE, "static")), name="static")
# Public front-of-house site (magazine/brochure surface + inbound intake), at the
# site root (/). Shares this app + DB; renders its own standalone layout, no internal nav.
app.include_router(public_router)


# --------------------------------------------------------------------------- #
# Internal admin gate — a light single-operator shared secret (NOT multi-user
# auth). OFF unless CHORDENTIAL_ADMIN_TOKEN is set, so dev/tests are unchanged;
# set it in the Render env to keep the dashboard (/dashboard + all internal
# routes) private while the public site at / stays open.
# --------------------------------------------------------------------------- #
ADMIN_COOKIE = "cdl_admin"

# Public surfaces served at the site root — these never require the admin secret.
# Everything NOT listed here is gated, so new internal routes are private by
# default; a new *public* page must be added to this set.
_PUBLIC_PATHS = frozenset({
    "/", "/capabilities", "/samples", "/start", "/book", "/thanks", "/apply",
    "/delivery-sample", "/refer", "/for-artists", "/showreel", "/reel", "/stills",
})


# The token-gated first-touch page: /opportunity/<id>/first-touch . Matched here
# (not a fixed string in _PUBLIC_PATHS) because the opp id varies — token check in
# the route is the real access control.
_FIRST_TOUCH_RE = re.compile(r"^/opportunity/\d+/first-touch/?$")


def _is_first_touch_path(path: str) -> bool:
    return bool(_FIRST_TOUCH_RE.match(path))


# The token-gated client delivery portal: /project/<id>/delivery-portal . Same
# pattern as first-touch — the per-project share token (?k=<token>) checked in the
# route is the access control, so the path bypasses the admin login gate.
_DELIVERY_PORTAL_RE = re.compile(r"^/project/\d+/delivery-portal/?$")
# The review-portal client actions are posted by the agency from the same token-gated
# link — each route token-validates (share token ?k= guest OR verified reviewer ?r=)
# and 404s on a bad token, so the path bypasses the admin login gate. Defined as ONE
# list so the exemption can't drift from the actual routes (it did once: resolve + asset
# were added without updating the matcher, bouncing clients to the admin login). When
# you add a review action, add it here — and it MUST token-validate in-route.
_REVIEW_ACTIONS = ("comment", "approve", "changes", "resolve", "asset")
_REVIEW_ACTION_RE = re.compile(
    r"^/project/\d+/review/(?:" + "|".join(_REVIEW_ACTIONS) + r")/?$")
# Payment-gated deliverable download — opened from the token-gated portal; the route
# itself validates the share/reviewer token AND the paid-in-full gate.
_DELIVERY_DL_RE = re.compile(r"^/project/\d+/dl/[^/]+/?$")
# The composer portal — a qualified creator's token-gated home (view assignments,
# submit work versions). The per-creator portal token IS the access control, so it
# bypasses the admin login gate (same exemption as the client delivery portal).
_CREATOR_PORTAL_RE = re.compile(r"^/creator/[A-Za-z0-9_-]+(/project/\d+/version)?/?$")


def _is_delivery_portal_path(path: str) -> bool:
    return bool(
        _DELIVERY_PORTAL_RE.match(path)
        or _REVIEW_ACTION_RE.match(path)
        or _DELIVERY_DL_RE.match(path)
        or _CREATOR_PORTAL_RE.match(path)
    )


def _admin_secret() -> Optional[str]:
    return os.environ.get("CHORDENTIAL_ADMIN_TOKEN") or None


def _admin_cookie_value(token: str) -> str:
    # Store proof-of-knowledge, never the raw token.
    return hashlib.sha256(f"cdl|{token}".encode()).hexdigest()


def _admin_authed(request: Request) -> bool:
    token = _admin_secret()
    if not token:
        return True  # gate disabled
    cookie = request.cookies.get(ADMIN_COOKIE) or ""
    return bool(cookie) and hmac.compare_digest(cookie, _admin_cookie_value(token))


def _is_public_path(path: str) -> bool:
    """Public surfaces that never require the admin secret."""
    return (
        path in _PUBLIC_PATHS
        or path.startswith("/static/")
        # The tailored first-touch page is meant for an external recipient, so it
        # bypasses the admin login gate — but it stays protected by the unguessable
        # per-opp share token in the URL (validated in the route), not by login.
        or _is_first_touch_path(path)
        # The client delivery portal is opened by the buyer — same token-gated
        # exemption as first-touch (the per-project share token IS the access control).
        or _is_delivery_portal_path(path)
        or path in ("/healthz", "/favicon.ico")
        # PWA install assets — fetched by the browser/OS (sometimes without the
        # admin cookie), and non-sensitive, so they bypass the gate.
        or path in ("/sw.js", "/manifest.webmanifest", "/apple-touch-icon.png")
        or path.startswith("/admin/login")
        or path.startswith("/admin/logout")
        or path == "/signals/ingest"   # email-in webhook (its own shared-secret token)
        or path == "/webhooks/stripe"  # Stripe webhook (verified by Stripe signature)
    )


@app.middleware("http")
async def _admin_gate(request: Request, call_next):
    if _admin_secret() and not _is_public_path(request.url.path) and not _admin_authed(request):
        if request.method == "HEAD":
            return Response(status_code=200)  # let platform health probes through
        return RedirectResponse(f"/admin/login?next={request.url.path}", status_code=303)
    response = await call_next(request)
    # Let browsers cache static assets so a looping hero video / replayed audio
    # loads ONCE and replays from cache, instead of re-streaming from this single
    # worker on every navigation (which starves other media → stutter). Change a
    # file's ?v= query to bust it.
    if request.url.path.startswith("/static/") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "public, max-age=604800"  # 7 days
    elif "text/html" in response.headers.get("content-type", ""):
        # Always revalidate HTML so content / media-URL changes land immediately on
        # EVERY device — mobile browsers otherwise serve a stale cached page.
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


def render(request: Request, name: str, **kw):
    """Render a template, compatible with Starlette's (request, name, context) API."""
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


# --------------------------------------------------------------------------- #
# Health / readiness — cheap endpoints for Render's probe and uptime monitors.
# Render (and most pingers) issue HEAD requests; our content routes are GET-only,
# so without these a HEAD / returns 405 and the deploy probe looks unhealthy.
# --------------------------------------------------------------------------- #
@app.get("/healthz")
@app.head("/healthz")
def healthz():
    return {"status": "ok"}


@app.head("/")
def root_head():
    # Respond to the platform health probe without running the dashboard query.
    return Response(status_code=200)


# --------------------------------------------------------------------------- #
# PWA (installable iOS/desktop app) — served from the site root so the service
# worker's scope covers the whole origin. "Add to Home Screen" → a Chordential
# app icon that opens the dashboard standalone; new gigs arrive via Web Push.
# --------------------------------------------------------------------------- #
_MANIFEST = {
    "name": "Chordential — Procurement OS",
    "short_name": "Chordential",
    "description": "Find, qualify, and win commercial music work.",
    "start_url": "/dashboard",
    "scope": "/",
    "display": "standalone",
    "background_color": "#FCF7F8",
    "theme_color": "#E4671F",
    "icons": [
        {"src": "/static/icon-192.png?v=3", "sizes": "192x192", "type": "image/png",
         "purpose": "any maskable"},
        {"src": "/static/icon-512.png?v=3", "sizes": "512x512", "type": "image/png",
         "purpose": "any maskable"},
    ],
}


@app.get("/manifest.webmanifest")
def manifest():
    return Response(json.dumps(_MANIFEST), media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    with open(os.path.join(_HERE, "static", "sw.js"), encoding="utf-8") as f:
        js = f.read()
    # Root-scope SW must not be cached stale; allow control of the whole origin.
    return Response(js, media_type="application/javascript", headers={
        "Cache-Control": "no-cache", "Service-Worker-Allowed": "/",
    })


@app.get("/apple-touch-icon.png")
def apple_touch_icon():
    from fastapi.responses import FileResponse
    # no-cache so a re-add picks up a changed icon instead of a stale iOS copy.
    return FileResponse(
        os.path.join(_HERE, "static", "apple-touch-icon.png"),
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/favicon.ico")
def favicon():
    from fastapi.responses import FileResponse
    # Serve the wordmark for the implicit /favicon.ico browser request. The
    # base layouts link an explicit icon, but the standalone client-facing pages
    # (delivery + creator portals, capabilities doc) don't, so their browsers fall
    # back to /favicon.ico — without this route that's a 404 console error on every
    # portal load a paying client opens. One route covers them all.
    return FileResponse(
        os.path.join(_HERE, "static", "public", "wordmark-dark.png"),
        media_type="image/png", headers={"Cache-Control": "public, max-age=604800"},
    )


# --------------------------------------------------------------------------- #
# Web Push subscription + delivery (native phone alerts for the installed PWA)
# --------------------------------------------------------------------------- #
@app.get("/push/vapid-public")
def push_vapid_public():
    """The VAPID public key the browser needs to subscribe (empty until set)."""
    return {"key": webpush.vapid_public()}


@app.post("/push/subscribe")
async def push_subscribe(request: Request):
    """Store this device's push subscription so it receives new-gig alerts."""
    try:
        body = await request.json()
    except Exception:
        return Response("bad request", status_code=400)
    endpoint = (body or {}).get("endpoint") or ""
    keys = (body or {}).get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return Response("missing subscription fields", status_code=400)
    conn = db.connect()
    try:
        db.add_push_subscription(
            conn, endpoint=endpoint, p256dh=keys["p256dh"], auth=keys["auth"])
    finally:
        conn.close()
    return {"ok": True}


@app.post("/push/test")
def push_test():
    """Fire a test alert through the real Web Push pipeline so you can confirm
    your phone receives it. Reports the outcome on the radar."""
    if not webpush.is_configured():
        return RedirectResponse("/signals?push=unset", status_code=303)
    res = webpush.send_web_push(
        "🎵 Chordential test alert",
        body="If you see this on your phone, new-gig alerts are working.",
        url="/signals",
    )
    if res["subscriptions"] == 0:
        state = "nosub"
    elif res["sent"] > 0:
        state = "sent"
    else:
        state = "error"
    return RedirectResponse(f"/signals?push={state}", status_code=303)


@app.get("/sources", response_class=HTMLResponse)
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


@app.post("/sources/cost")
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


@app.post("/sources/test")
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


@app.post("/sources/cleartests")
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


@app.get("/agencies", response_class=HTMLResponse)
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


@app.post("/agencies/ingest")
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


@app.post("/agencies/crawl")
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


@app.get("/agencies/status")
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


@app.post("/agencies/enrich-pending")
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


@app.post("/agencies/reenrich-pending")
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


@app.post("/agencies/decision-makers-pending")
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


@app.post("/agencies/intelligence-pending")
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


@app.post("/agencies/signals-pending")
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


@app.post("/agencies/score-pending")
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


@app.post("/agencies/import-setup")
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


@app.post("/agencies/add")
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


@app.get("/agencies/{agency_id}", response_class=HTMLResponse)
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
                  outreach_ws=outreach_ws,
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


@app.post("/agencies/{agency_id}/decision-makers")
def agency_find_decision_makers(agency_id: int, reset: str = Form("")):
    """Discover ONE agency's decision makers — visit its leadership/team/about
    pages, extract every person, classify + score them. Fire-and-forget: it fetches
    live pages (slow), so running it inline spins the request — instead it runs in
    the background and the page shows results on refresh. Safe to re-press."""
    scheduler.start_agency_decision_makers(agency_id, reset=bool(reset))
    return RedirectResponse(f"/agencies/{agency_id}#decision-makers", status_code=303)


@app.post("/agencies/{agency_id}/intelligence")
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


@app.post("/agencies/{agency_id}/signals")
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


@app.post("/agencies/{agency_id}/score")
def agency_score(agency_id: int):
    """Recompute the Music Opportunity score for ONE agency from its collected
    intelligence + signals + outreach. Pure reasoning; runs inline."""
    conn = db.connect()
    try:
        music_opportunity.score_agency(conn, agency_id)
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#opportunity", status_code=303)


@app.post("/agencies/{agency_id}/outreach")
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


# --------------------------------------------------------------------------- #
# Relationship Management Platform
# --------------------------------------------------------------------------- #
@app.get("/relationships", response_class=HTMLResponse)
def relationships_dashboard(request: Request):
    """Today's Priorities + the relationship pipeline — what to act on, derived
    from the engines (movements, follow-ups, recommended outreach)."""
    conn = db.connect()
    try:
        priorities = relationships.daily_priorities(conn)
        rows = db.top_opportunities(conn, limit=50)
        pipeline = []
        for r in rows:
            interactions = list(db.list_agency_outreach(conn, r["id"]))
            stage = relationships.current_stage(
                conn, r["id"], score=r["opportunity_score"],
                interactions=interactions,
                responded=any(o["responded"] for o in interactions))
            pipeline.append({"id": r["id"], "company": r["company"],
                             "score": r["opportunity_score"], "tier": r["opportunity_tier"],
                             "stage": stage, "movement": r["score_movement"]})
    finally:
        conn.close()
    return render(request, "relationships.html", nav="relationships",
                  priorities=priorities, pipeline=pipeline, stages=relationships.STAGES)


@app.post("/agencies/{agency_id}/relationship/stage")
def agency_set_stage(agency_id: int, stage: str = Form(...)):
    """Manually override the relationship stage (the Relationship Agent's auto
    derivation is the default; this pins it)."""
    conn = db.connect()
    try:
        db.upsert_relationship(conn, agency_id, stage=stage, stage_overridden=1)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#relationship", status_code=303)


@app.post("/agencies/{agency_id}/relationship/task")
def agency_add_task(agency_id: int, title: str = Form(...), due_at: str = Form("")):
    conn = db.connect()
    try:
        db.add_agency_task(conn, agency_id, title=title, due_at=due_at)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#relationship", status_code=303)


@app.post("/agencies/{agency_id}/relationship/task/{task_id}/done")
def agency_complete_task(agency_id: int, task_id: int):
    conn = db.connect()
    try:
        db.complete_agency_task(conn, task_id)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#relationship", status_code=303)


@app.post("/agencies/{agency_id}/relationship/memory")
def agency_add_memory(agency_id: int, fact: str = Form(...), contact: str = Form("")):
    conn = db.connect()
    try:
        db.add_agency_memory(conn, agency_id, fact=fact, contact=contact)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#relationship", status_code=303)


@app.post("/agencies/{agency_id}/relationship/document")
def agency_add_document(agency_id: int, title: str = Form(...), url: str = Form(""),
                        note: str = Form("")):
    conn = db.connect()
    try:
        db.add_agency_document(conn, agency_id, title=title, url=url, note=note)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/agencies/{agency_id}#relationship", status_code=303)


@app.post("/agencies/{agency_id}/enrich")
def agency_enrich(agency_id: int, reset: str = Form("")):
    """Run the Company Enrichment Engine on ONE agency. Fire-and-forget: it reads
    the agency's live website (homepage + ~10 sub-pages), which is far too slow to
    do inside the request — so it runs in the background and the profile fills in on
    refresh. Safe to re-press: it resumes unless 'reset' is set."""
    scheduler.start_agency_enrich(agency_id, reset=bool(reset))
    return RedirectResponse(f"/agencies/{agency_id}", status_code=303)


@app.post("/agencies/{agency_id}/pipeline")
def agency_full_pipeline(agency_id: int, reset: str = Form("")):
    """One press → build the COMPLETE profile for this agency: enrich → decision
    makers → intelligence → signals → score, run in order in a single background
    job. Returns instantly; the page fills in over the next minute on refresh."""
    scheduler.start_agency_pipeline(agency_id, reset=bool(reset))
    return RedirectResponse(f"/agencies/{agency_id}", status_code=303)


@app.get("/signals/selftest", response_class=HTMLResponse)
def signals_selftest(request: Request):
    """Run one synthetic lead from every weighted source through the real
    ingest → score → rank pipeline (throwaway DB — live data untouched) so the
    whole engine is verifiable end-to-end across all sources."""
    return render(request, "engine_selftest.html", nav="signals",
                  report=signals.engine_selftest())


@app.post("/signals/poll")
def signals_poll():
    """Run every configured feed (RSS + Reddit) right now and report what each
    returned — an on-demand test of the discovery feeds."""
    scheduler.poll_now()
    return RedirectResponse("/signals?poll=1", status_code=303)


@app.post("/triage/run")
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
# Admin sign-in (only meaningful when CHORDENTIAL_ADMIN_TOKEN is set)
# --------------------------------------------------------------------------- #
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, next: str = "/dashboard"):
    if _admin_authed(request):
        return RedirectResponse(_safe_local(next, "/dashboard"), status_code=303)
    return render(
        request, "admin_login.html", next=_safe_local(next, "/dashboard"), error=False
    )


@app.post("/admin/login")
def admin_login(request: Request, password: str = Form(""), next: str = Form("/dashboard")):
    token = _admin_secret()
    if not token:
        return RedirectResponse("/dashboard", status_code=303)
    if hmac.compare_digest(password.strip(), token):
        resp = RedirectResponse(_safe_local(next, "/dashboard"), status_code=303)
        resp.set_cookie(
            ADMIN_COOKIE, _admin_cookie_value(token),
            httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
        )
        return resp
    return render(
        request, "admin_login.html", next=_safe_local(next, "/dashboard"), error=True
    )


@app.get("/admin/logout")
def admin_logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(ADMIN_COOKIE)
    return resp


# --------------------------------------------------------------------------- #
# Executive summary
# --------------------------------------------------------------------------- #
def _suggested_price(opp) -> float:
    """Suggested price for one opportunity, via the same engines as the estimate
    page (qualify → discipline/team → estimate). Deterministic and LLM-free."""
    qual, _ = evaluate(opp)
    team = qual.team_shape or qual.discipline.team_shape
    return build_estimate(opp, team, qual.discipline).suggested_price


@app.get("/dashboard", response_class=HTMLResponse)
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
        # "Needs triage" home module (ruling #4) — fed by the unified Incoming queue.
        incoming_all = db.list_incoming(conn)
        incoming = incoming_all[:6]            # home preview — first few, newest first
        incoming_total = len(incoming_all)
        metrics = db.exec_metrics(conn)
        totals = {
            "tentative_value": sum((r["outcome_value"] or 0) for r in tentative),
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
    finally:
        conn.close()
    return render(
        request, "dashboard.html", nav="dashboard",
        pursue=pursue, tentative=tentative, won=won, totals=totals,
        review=review, spotlight=spotlight, followups=followups, metrics=metrics,
        src_health=src_health, incoming=incoming, incoming_total=incoming_total,
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
@app.get("/incoming", response_class=HTMLResponse)
def incoming_queue(request: Request):
    conn = db.connect()
    try:
        rows = db.list_incoming(conn)
    finally:
        conn.close()
    return render(request, "incoming.html", nav="incoming", rows=rows)


@app.get("/incoming/count")
def incoming_count():
    """Live count of unactioned incoming items (all sources) — polled by the nav badge."""
    conn = db.connect()
    try:
        return {"new": db.incoming_unactioned_count(conn)}
    finally:
        conn.close()


@app.get("/leads", response_class=HTMLResponse)
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


@app.post("/leads/{lead_id}/status")
def inbound_set_status(lead_id: int, status: str = Form(...)):
    conn = db.connect()
    try:
        db.update_inbound_lead_status(conn, lead_id, status)
    finally:
        conn.close()
    return RedirectResponse("/leads", status_code=303)


@app.post("/leads/{lead_id}/delete")
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


@app.post("/leads/{lead_id}/promote")
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
@app.get("/discovery", response_class=HTMLResponse)
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
@app.get("/signals", response_class=HTMLResponse)
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
    )


@app.post("/signals/test-push")
def signals_test_push():
    """Fire a test phone alert through the real push pipeline so you can confirm
    your ntfy setup end-to-end. Reports back whether the topic is configured."""
    status = signals.send_push(
        "Chordential test alert",
        body="If you see this on your phone, new-gig alerts are working.",
        click_url="https://chordential.com/signals",
    )
    return RedirectResponse(f"/signals?push={status}", status_code=303)


@app.post("/signals/paste")
def signals_paste(text: str = Form("")):
    """Paste a forwarded saved-search / F5Bot alert → parse into signals."""
    conn = db.connect()
    try:
        signals.ingest_email(conn, "", text, source="paste")
    finally:
        conn.close()
    return RedirectResponse("/signals", status_code=303)


@app.post("/signals/ingest")
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


@app.post("/signals/{signal_id}/promote")
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


@app.get("/signals/count")
def signals_count():
    """Live count of unactioned gigs — polled by the nav badge."""
    conn = db.connect()
    try:
        return {"new": db.new_signal_count(conn)}
    finally:
        conn.close()


@app.post("/signals/clear")
def signals_clear():
    """Wipe the open radar — start fresh after a filter change."""
    conn = db.connect()
    try:
        db.clear_signals(conn)
    finally:
        conn.close()
    return RedirectResponse("/signals", status_code=303)


@app.post("/signals/{signal_id}/status")
def signal_set_status(signal_id: int, status: str = Form(...)):
    conn = db.connect()
    try:
        if status.strip().lower() == "dismissed":   # B3 — a triaged gig the human rejected
            s = db.get_signal(conn, signal_id)
            if s is not None:
                triage.record_feedback(s, "dismissed")
        db.set_signal_status(conn, signal_id, status)
    finally:
        conn.close()
    return RedirectResponse("/signals", status_code=303)


@app.get("/capture", response_class=HTMLResponse)
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


@app.post("/discovery/lead")
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


@app.post("/discovery/generate")
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


@app.post("/discovery/site/{site_id}/status")
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


@app.post("/discovery/site/add")
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


@app.post("/discovery/{target_id}/status")
def discovery_decide(target_id: int, status: str = Form(...), kind: str = Form("talent")):
    """Approve or dismiss a proposed target — Jon's explicit go-ahead/refusal."""
    conn = db.connect()
    try:
        db.update_crawl_target_status(conn, target_id, status)
    finally:
        conn.close()
    return RedirectResponse(f"/discovery?kind={kind}", status_code=303)


@app.post("/discovery/{target_id}/fetch")
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
    """The human pipeline as a status kanban (New → Pursuing → Submitted →
    Won/Lost), each card advanceable one stage with a click. Matches the
    Dashboard's pipeline model — same statuses, here as a working board."""
    conn = db.connect()
    try:
        columns = [
            {"status": s, "rows": db.list_opportunities(conn, status=s, order_by="alignment")}
            for s in _KANBAN_STAGES
        ]
        # Lost + Passed collapse into one "Closed" archive column (ruling #2).
        closed_rows = []
        for s in _CLOSED_STAGES:
            closed_rows += db.list_opportunities(conn, status=s, order_by="created")
        columns.append({"status": "Lost", "rows": closed_rows})
    finally:
        conn.close()
    return render(
        request, "lanes.html", nav="lanes", columns=columns,
        advance=_NEXT_STATUS,
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
    # Guided-not-gated stepper: the expected next stage along the working flow
    # (New → Reaching out → Proposal out → Won). Computed separately from the
    # action-bar's _NEXT_STATUS so adding Submitted→Won here doesn't change the
    # Won-via-win/loss-form behaviour elsewhere.
    stepper_next = _STEPPER_NEXT.get(row["status"])
    return render(
        request, "detail.html", nav="inbox", row=row, opp=opp, qual=qual, scored=scored,
        sv=sv, buyer_count=len(buyer_rows), buyer_values=list(BuyerValue),
        project_id=(project["id"] if project else None),
        next_status=_NEXT_STATUS.get(row["status"]),
        stepper_next=stepper_next, stepper_stages=_KANBAN_STAGES,
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


def _brief_checklist(brief, done_keys):
    """Pair each checklist step with a stable key and its done state.

    Key = index + slug so it survives reloads (the list is deterministic per opp)
    and stays unique even if two steps share a prefix."""
    items = []
    for i, text in enumerate(brief.checklist):
        key = f"{i}-{slug(text)[:48]}"
        items.append({"key": key, "text": text, "done": key in done_keys})
    done = sum(1 for it in items if it["done"])
    total = len(items)
    progress = {"done": done, "total": total, "pct": round(done / total * 100) if total else 0}
    return items, progress


@app.get("/opportunity/{opp_id}/brief", response_class=HTMLResponse)
def brief_page(request: Request, opp_id: int):
    conn = db.connect()
    try:
        row, opp, brief = _brief_for(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        done_keys = db.brief_done_keys(conn, opp_id)
    finally:
        conn.close()
    items, progress = _brief_checklist(brief, done_keys)
    return render(
        request, "brief.html", nav="inbox", row=row, opp=opp, brief=brief,
        checklist_items=items, progress=progress,
    )


@app.post("/opportunity/{opp_id}/brief/step")
def toggle_brief_step(opp_id: int, step_key: str = Form(...), done: str = Form("")):
    conn = db.connect()
    try:
        db.set_brief_step(conn, opp_id, step_key, bool(done.strip()))
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/brief", status_code=303)


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
    plan = build_outreach_plan(
        opp, qual, scored, est, strategic, contact_name=row["contact_name"]
    )
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
        request, "outreach.html", nav="inbox", row=row, opp=opp, plan=plan, events=events,
        respond=respond_action(row, plan),
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
    contact_linkedin: str = Form(""),
    contact_phone: str = Form(""),
):
    conn = db.connect()
    try:
        db.update_outreach(
            conn, opp_id, contact_name, contact_email, contact_role,
            next_action, next_action_due, contact_linkedin, contact_phone,
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


# --------------------------------------------------------------------------- #
# Block composer (Phase 1) — on/off blocks + live preview, choices persisted per
# deal under the `compose` doc-override; the send action builds a personal
# plain-text email into Jon's own mail client (mailto). Mirrors the doc save
# routes' style.
# --------------------------------------------------------------------------- #
def _compose_state(conn, opp_id: int):
    """Load the opp/plan, build the composer blocks, and resolve the saved
    selection + assembled body from the `compose` override. Returns
    ``(row, opp, plan, blocks, selected, body)`` (all None when missing)."""
    row, opp, plan = _outreach_for(conn, opp_id)
    if row is None:
        return None, None, None, None, None, None
    overrides = db.get_doc_overrides(conn, opp_id)
    # Mint (or fetch) the unguessable share token so the page-link block carries the
    # real token-gated URL — the same token the first-touch route validates.
    share_token = db.ensure_share_token(conn, opp_id)
    blocks = build_compose_blocks(
        opp, None, plan, overrides=overrides, opp_id=opp_id,
        contact_name=row["contact_name"], share_token=share_token,
    )
    selected = compose_selection(blocks, overrides)
    body = assemble_email(blocks, selected)
    return row, opp, plan, blocks, selected, body


@app.get("/opportunity/{opp_id}/compose", response_class=HTMLResponse)
def compose_page(request: Request, opp_id: int, sent: str = ""):
    conn = db.connect()
    try:
        row, opp, plan, blocks, selected, body = _compose_state(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        overrides = db.get_doc_overrides(conn, opp_id)
        relevant_uploads = overrides.get("relevant_uploads") or []
        token = db.ensure_share_token(conn, opp_id)
    finally:
        conn.close()
    subject = plan.email_subject
    mailto = _mailto(row["contact_email"] or "", subject, body)
    page_url = f"/opportunity/{opp_id}/first-touch?k={token}"
    return render(
        request, "compose.html", nav="inbox", row=row, opp=opp, plan=plan,
        blocks=blocks, selected=selected, body=body, subject=subject, mailto=mailto,
        relevant_uploads=relevant_uploads, page_url=page_url,
        mail_configured=mailer.mail_configured(), sent=sent,
    )


@app.post("/opportunity/{opp_id}/compose")
async def set_compose(request: Request, opp_id: int):
    """Persist the composer state: the checked block keys + any edited block texts
    are written into the `compose` doc-override. Mirrors the doc save routes."""
    form = await request.form()
    on = [str(k) for k in form.getlist("on")]
    text = {}
    for key in COMPOSE_BLOCK_KEYS:
        raw = form.get(f"text_{key}")
        if isinstance(raw, str) and raw.strip():
            text[key] = raw
    compose = {"on": on}
    if text:
        compose["text"] = text
    conn = db.connect()
    try:
        db.update_doc_override(conn, opp_id, "compose", compose)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/compose", status_code=303)


@app.post("/opportunity/{opp_id}/compose/send")
def compose_send(opp_id: int):
    """Actually send the composed email via the configured mail provider,
    instead of only opening a mailto: draft in Jon's own mail client (where
    it sits until he separately hits Send there). Falls back to "manual" —
    same as the recruiting invite — when there's no contact email or mail
    isn't configured; the mailto link stays on the page either way, so
    nothing is lost, this just adds a real send on top."""
    conn = db.connect()
    try:
        row, opp, plan, blocks, selected, body = _compose_state(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
    finally:
        conn.close()
    email = (row["contact_email"] or "").strip()
    if not email or not mailer.mail_configured():
        return RedirectResponse(f"/opportunity/{opp_id}/compose?sent=manual", status_code=303)
    base = _public_base()
    status = mailer.send_email(
        email, plan.email_subject, body, html=mailer.branded_html(base, body),
    )
    return RedirectResponse(f"/opportunity/{opp_id}/compose?sent={status}", status_code=303)


# --------------------------------------------------------------------------- #
# The tailored first-touch page (Phase 2) — a SELF-CONTAINED public page the
# soft email link points at. NOT admin-gated (an external recipient opens it);
# the unguessable per-opp share token in ?k=<token> IS the access control. A
# valid load also stamps the Phase-3 engagement signal (view count / last seen).
#
# Option C (branded HTML send via Gmail) remains DEFERRED — this page + its view
# measurement are the gate that decides whether Option C is ever worth building.
# --------------------------------------------------------------------------- #
def _reply_to_address() -> str:
    """A real recipient for the first-touch 'Reply' CTA. Prefer the configured
    send-from address; otherwise derive hello@<public-domain> so the mailto never
    opens an empty, recipient-less draft."""
    configured = mailer._smtp_from()
    if configured:
        return configured
    domain = os.environ.get(
        "CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com")
    host = domain.split("://", 1)[-1].strip("/").split("/")[0] or "chordential.com"
    return f"hello@{host}"


@app.get("/opportunity/{opp_id}/first-touch", response_class=HTMLResponse)
def first_touch_page(request: Request, opp_id: int, k: str = ""):
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        token = row["share_token"] if row is not None else None
        # Token check is the access control: a missing opp, an unset token, or a
        # mismatch all 404 identically so the page never leaks an opp's existence.
        if row is None or not token or not k or not hmac.compare_digest(str(k), str(token)):
            return HTMLResponse("Not found", status_code=404)
        opp = db.opportunity_from_row(row)
        overrides = db.get_doc_overrides(conn, opp_id)
        # Phase 3: a valid load is the engagement signal surfaced on the outreach view.
        db.record_first_touch_view(conn, opp_id)
    finally:
        conn.close()

    understanding = build_understanding(opp)
    relevant_uploads = overrides.get("relevant_uploads") or []
    relevant_links = overrides.get("relevant_links") or []
    # Never dead-end the highest-intent click with silence: when nothing was
    # hand-picked for this opportunity, fall back to the showcase demo tracks
    # (honest craft demos, invented brands) so there is always music to hear.
    showcase_tracks = []
    if not relevant_uploads and not relevant_links:
        from .showcase import get_showcase
        showcase_tracks = [
            {"label": f"{d.title} — {d.discipline_label}", "url": d.audio_url}
            for d in get_showcase().demos if d.audio_url
        ]
    call_url = os.environ.get("CHORDENTIAL_DISCOVERY_CALL_URL", "").strip()
    return render(
        request, "first_touch.html", nav="", row=row, opp=opp,
        client=row["client"], understanding=understanding,
        relevant_uploads=relevant_uploads, relevant_links=relevant_links,
        showcase_tracks=showcase_tracks, reply_to=_reply_to_address(),
        call_url=call_url,
    )


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


# --------------------------------------------------------------------------- #
# Match Board — opportunities (left) × qualified talent (right), drag/tap assign
# --------------------------------------------------------------------------- #
@app.get("/matchboard", response_class=HTMLResponse)
def matchboard(request: Request, opp: Optional[int] = None):
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
    )


@app.post("/matchboard/assign")
def matchboard_assign(opp_id: int = Form(...), talent_id: int = Form(...)):
    """Assign a creator to an opportunity by staffing its project: ensure the
    project exists (so it shows on Projects), add the assignment, and broadcast
    to the whole crew so the team knows who they're working with."""
    conn = db.connect()
    try:
        pid = _ensure_project_for_opp(conn, opp_id)
        t = db.get_talent(conn, talent_id)
        if pid is None or t is None:
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


@app.post("/matchboard/unassign")
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


@app.post("/opportunity/{opp_id}/status")
def set_status(
    opp_id: int,
    status: str = Form(...),
    outcome_value: str = Form(""),
    return_to: str = Form(""),
):
    conn = db.connect()
    try:
        value = float(outcome_value) if outcome_value.strip() else None
        db.update_status(conn, opp_id, status, value)
    finally:
        conn.close()
    return RedirectResponse(
        _safe_local(return_to, f"/opportunity/{opp_id}"), status_code=303
    )


@app.post("/opportunity/{opp_id}/delivery-sent")
def mark_delivery_sent(opp_id: int, return_to: str = Form("")):
    """Stamp the 'Delivery doc sent' milestone (the outreach → closing hand-off)."""
    conn = db.connect()
    try:
        db.mark_delivery_doc_sent(conn, opp_id)
    finally:
        conn.close()
    return RedirectResponse(
        _safe_local(return_to, f"/opportunity/{opp_id}"), status_code=303
    )


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
def buyers_directory(
    request: Request, stage: Optional[str] = None, order_by: str = "relationship"
):
    conn = db.connect()
    try:
        rows = db.all_buyers(conn)
    finally:
        conn.close()
    buyers = []
    for r in rows:
        tier = _strat_tier_for_value(r["strategic_value"])
        days = days_since(r["last_contacted"])
        rel = assess_relationship(
            opps=r["opps"], qualified=int(r["qualified"] or 0),
            won=int(r["won"] or 0), lost=int(r["lost"] or 0),
            open_pursuits=int(r["open_pursuits"] or 0), touches=int(r["touches"] or 0),
            last_contacted_days=days, strategic_tier=tier,
        )
        buyers.append({"row": r, "rel": rel, "strategic_tier": tier, "days_since": days})
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
    stages = ["Cold", "Warming", "Engaged", "Client"]
    return render(
        request, "buyers.html", nav="buyers", buyers=buyers, stages=stages,
        active={"stage": stage or "", "order_by": order_by},
    )


def _buyer_context(conn, client: str) -> Optional[dict]:
    """Assemble the full buyer-profile context (None when the buyer is unknown).
    Shared by the standalone /buyer/{client} page and the opp-scoped tab."""
    rows = db.buyer_opportunities(conn, client)
    if not rows:
        return None
    touch = db.buyer_touch_summary(conn, client)
    contacts = db.buyer_contacts(conn, client)
    website = db.company_website(conn, client)

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
    return {
        "summary": summary, "rows": rows, "rel": rel, "contacts": contacts,
        "last_contacted": touch["last_contacted"], "company_website": website,
    }


@app.get("/buyer/{client}", response_class=HTMLResponse)
def buyer_profile(request: Request, client: str):
    conn = db.connect()
    try:
        ctx = _buyer_context(conn, client)
    finally:
        conn.close()
    if ctx is None:
        return HTMLResponse("Buyer not found", status_code=404)
    return render(request, "buyer.html", nav="buyers", **ctx)


@app.get("/opportunity/{opp_id}/buyer", response_class=HTMLResponse)
def opportunity_buyer(request: Request, opp_id: int):
    """The buyer profile rendered inside the opportunity's tabbed context, so the
    subnav stays put instead of jumping to the standalone company page."""
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        ctx = _buyer_context(conn, row["client"])
    finally:
        conn.close()
    if ctx is None:
        return HTMLResponse("Buyer not found", status_code=404)
    return render(request, "buyer.html", nav="inbox", opp_row=row, **ctx)


@app.get("/opportunity/{opp_id}/capabilities", response_class=HTMLResponse)
def opportunity_capabilities(request: Request, opp_id: int):
    """Branded, toggleable capabilities/proposal doc → preview and Save as PDF.

    Sections default by deal stage (discovery hides cost; proposal adds the price
    band; contract adds terms + DocuSign). Once the toggle bar is submitted, each
    section follows its checkbox so you can tailor what the buyer sees."""
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        # The deal's project + its Deposit invoice (if either exists yet) — used to
        # surface the Stripe "Pay deposit" button, exactly as the detail page looks
        # the project up. No project/invoice → we fall back to showing the amount.
        project = db.project_for_opp(conn, opp_id)
        deposit_invoice = None
        stored_proposal = None
        if project is not None:
            stored_proposal = db.proposal_for_project(conn, project["id"])
            for inv in db.list_invoices(conn, project["id"]):
                if inv["kind"] == "Deposit":
                    deposit_invoice = inv
                    break
        # Per-deal hand edits (client name, understanding, chips, links, template).
        overrides = db.get_doc_overrides(conn, opp_id)
        custom_chips = db.list_custom_chips(conn)
    finally:
        conn.close()
    qual, scored = ev
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or discipline.team_shape, discipline)

    toggles = default_toggles(row["status"])
    qp = request.query_params
    if qp.get("submitted"):                       # toggle bar was applied
        for key in ("cost", "examples", "call", "terms", "delivery"):
            toggles[key] = qp.get(key) == "1"
    doc = build_capabilities_doc(
        opp, qual, est, toggles=toggles, overrides=overrides,
        call_url=os.environ.get("CHORDENTIAL_DISCOVERY_CALL_URL", "").strip(),
    )

    # Edit-mode payload the (later) editable-template UI consumes: the chip library
    # per editable section (deliverable chips scoped to the chosen template), the
    # available delivery templates for the override dropdown, and saved "My chips".
    edit = qp.get("edit") == "1"
    chip_library = {
        section: chips_for(section, doc.delivery_template)
        for section in SECTION_FAMILY
    }
    delivery_templates = {
        key: tmpl["label"] for key, tmpl in DELIVERY_TEMPLATES.items()
    }

    # Deposit amount for the Pay-deposit element: the stored proposal's deposit if
    # the project's been spun up, otherwise the estimate-derived deposit.
    if stored_proposal is not None and stored_proposal["deposit_amount"]:
        deposit_amount = stored_proposal["deposit_amount"]
    else:
        deposit_amount = build_proposal(opp, qual, est).deposit_amount

    return render(
        request, "capabilities_doc.html", nav="inbox", row=row, doc=doc,
        deposit_amount=deposit_amount,
        deposit_invoice_id=(deposit_invoice["id"] if deposit_invoice else None),
        edit=edit, overrides=overrides, chip_library=chip_library,
        custom_chips=custom_chips, delivery_templates=delivery_templates,
        section_family=SECTION_FAMILY,
    )


# --------------------------------------------------------------------------- #
# Editable client document — per-deal save endpoints (the UI pass calls these).
# Each is best-effort, validates inputs minimally, and redirects back into edit
# mode so the toolbar/edit affordances stay visible after a save.
# --------------------------------------------------------------------------- #
_DOC_FIELDS = {"client", "understanding", "delivery_template", "delivery_assumptions"}


def _doc_redirect(opp_id: int):
    return RedirectResponse(
        f"/opportunity/{opp_id}/capabilities?edit=1", status_code=303
    )


def _doc_back(opp_id: int, return_to: str = ""):
    """Redirect back to the caller (e.g. the composer) when a safe local
    ``return_to`` is supplied, else to the capabilities doc editor."""
    rt = (return_to or "").strip()
    if rt.startswith("/opportunity/") and "//" not in rt and " " not in rt:
        return RedirectResponse(rt, status_code=303)
    return _doc_redirect(opp_id)


@app.post("/opportunity/{opp_id}/doc/field")
def doc_field(opp_id: int, name: str = Form(""), value: str = Form("")):
    """Set/reset a scalar override field (client, understanding, delivery_template,
    delivery_assumptions). A blank value resets that field to the generated default."""
    if name in _DOC_FIELDS:
        conn = db.connect()
        try:
            db.update_doc_override(conn, opp_id, name, value)
        finally:
            conn.close()
    return _doc_redirect(opp_id)


@app.post("/opportunity/{opp_id}/doc/chip")
def doc_chip(
    opp_id: int, section: str = Form(""), action: str = Form(""),
    label: str = Form(""), sentence: str = Form(""),
):
    """Add/remove a support chip in one section's ``support_chips`` list."""
    section = (section or "").strip()
    if section and action in ("add", "remove"):
        conn = db.connect()
        try:
            overrides = db.get_doc_overrides(conn, opp_id)
            chips = dict(overrides.get("support_chips") or {})
            current = list(chips.get(section) or [])
            if action == "add" and (label.strip() or sentence.strip()):
                current.append({"label": label.strip(), "sentence": sentence.strip()})
            elif action == "remove":
                current = [
                    c for c in current
                    if not (c.get("label") == label and c.get("sentence") == sentence)
                ]
            if current:
                chips[section] = current
            else:
                chips.pop(section, None)
            db.update_doc_override(conn, opp_id, "support_chips", chips or None)
        finally:
            conn.close()
    return _doc_redirect(opp_id)


@app.post("/opportunity/{opp_id}/doc/link")
def doc_link(
    opp_id: int, action: str = Form(""), label: str = Form(""), url: str = Form(""),
):
    """Add/remove a hand-picked relevant-work link ({label, url})."""
    if action in ("add", "remove"):
        conn = db.connect()
        try:
            overrides = db.get_doc_overrides(conn, opp_id)
            links = list(overrides.get("relevant_links") or [])
            if action == "add" and url.strip():
                links.append({"label": label.strip() or url.strip(), "url": url.strip()})
            elif action == "remove":
                links = [l for l in links if l.get("url") != url]
            db.update_doc_override(conn, opp_id, "relevant_links", links or None)
        finally:
            conn.close()
    return _doc_redirect(opp_id)


@app.post("/opportunity/{opp_id}/doc/pill")
def doc_pill(
    opp_id: int, section: str = Form(""), action: str = Form(""), label: str = Form(""),
):
    """Hide/restore an auto-generated pill (discipline, music need, team role) per
    deal. Hidden labels live in ``overrides['hidden_pills'][section]``; the builder
    leaves the generated pills intact, the template just skips the hidden ones, so a
    'show' fully restores it."""
    section = (section or "").strip()
    label = (label or "").strip()
    if section and label and action in ("hide", "show"):
        conn = db.connect()
        try:
            overrides = db.get_doc_overrides(conn, opp_id)
            hidden = dict(overrides.get("hidden_pills") or {})
            current = list(hidden.get(section) or [])
            if action == "hide" and label not in current:
                current.append(label)
            elif action == "show":
                current = [x for x in current if x != label]
            if current:
                hidden[section] = current
            else:
                hidden.pop(section, None)
            db.update_doc_override(conn, opp_id, "hidden_pills", hidden or None)
        finally:
            conn.close()
    return _doc_redirect(opp_id)


@app.post("/chips/custom")
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


# --------------------------------------------------------------------------- #
# Relevant-work audio uploads — the founder uploads samples from their machine.
#
# PERSISTENCE CAVEAT (honest): these files land on the LOCAL disk (UPLOAD_DIR).
# That is NOT durable on Render once the persistent disk is removed for the
# zero-downtime (blue-green) cutover — a redeploy/instance swap loses them.
# Durable storage needs object storage (S3/R2). Acceptable for now; note it.
# --------------------------------------------------------------------------- #
def _safe_upload_path(name: str) -> Optional[str]:
    """Resolve a bare filename to a real path inside UPLOAD_DIR, or None. Guards
    against path traversal (only a bare basename that exists is accepted)."""
    base = os.path.basename(name or "")
    if not base or base != name:
        return None
    path = os.path.join(UPLOAD_DIR, base)
    if os.path.realpath(path) != os.path.join(os.path.realpath(UPLOAD_DIR), base):
        return None
    return path if os.path.isfile(path) else None


@app.get("/uploads/{name}")
def serve_upload(name: str):
    """Serve a stored upload by basename (streaming previews, static media).

    The delivery ZIP is NEVER served here — it's a payment-gated deliverable that
    only ever goes through /project/<id>/dl/<name>. Blocking .zip closes the
    deterministic-filename backdoor on the bundle while leaving audio streaming open
    (so a client can still review/preview before paying)."""
    from fastapi.responses import FileResponse
    if (name or "").lower().endswith(".zip"):
        return PlainTextResponse("not found", status_code=404)
    path = _safe_upload_path(name)
    if path is None:
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(path)


@app.get("/project/{project_id}/dl/{name}")
def delivery_download(request: Request, project_id: int, name: str, k: str = "", r: str = ""):
    """Payment-gated deliverable download (ZIP + per-asset masters/docs).

    Two access modes, distinguished by whether a share/reviewer TOKEN is presented:

    * **Client** (a valid ``?k=``/``?r=`` token) — the payment gate applies: the file
      is served only when deliverables are UNLOCKED (paid in full, or Jon manually
      unlocked this delivery), else **402 Payment Required**. We key on token presence
      (not admin status) deliberately: when the admin gate is disabled, ``_admin_authed``
      is True for everyone, so an admin-status check would silently bypass the paywall.
    * **Operator** (no token) — must be the admin; Jon downloads freely to inspect the
      package. 404 if not authorized.

    Streaming previews are unaffected (they stay on /uploads); this gate is only on the
    downloadable deliverables."""
    from fastapi.responses import FileResponse
    conn = db.connect()
    try:
        row = db.get_project(conn, project_id)
        if row is None:
            return PlainTextResponse("not found", status_code=404)
        token = db.ensure_project_share_token(conn, project_id)
        delivery = db.get_delivery(conn, project_id)
        verified = reviewer_from_token(delivery, r)
        k_ok = bool(token and k and hmac.compare_digest(str(k), str(token)))
        has_client_token = k_ok or verified is not None
        if has_client_token:
            unlocked = (bool(delivery.get("download_unlocked"))
                        or db.invoice_balance(conn, project_id)["paid_in_full"])
            if not unlocked:
                return PlainTextResponse(
                    "Payment required: your deliverables unlock once your invoice is "
                    "paid in full. You can still stream and review the work.",
                    status_code=402)
        elif not _admin_authed(request):
            # No client token and not the operator → no access.
            return PlainTextResponse("not found", status_code=404)
    finally:
        conn.close()
    path = _safe_upload_path(name)
    if path is None:
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(path, filename=os.path.basename(path))


@app.post("/project/{project_id}/delivery/unlock")
def delivery_unlock(project_id: int, unlock: str = Form("1")):
    """Operator override (admin-only via the gate): manually unlock/relock the
    client's deliverable downloads independent of payment. Machine proposes (pay in
    full → unlock); Jon disposes (release anyway, or hold)."""
    conn = db.connect()
    try:
        db.update_delivery(conn, project_id, "download_unlocked",
                           True if unlock == "1" else None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#delivery", status_code=303)


@app.post("/opportunity/{opp_id}/doc/upload")
async def doc_upload(
    opp_id: int,
    request: Request,
    label: str = Form(""),
    action: str = Form("add"),
    filename: str = Form(""),
    return_to: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """Upload (or remove) a founder audio sample for the Relevant-work section.

    Add: validates the file is audio (by extension or content-type), saves it under
    a safe unique name in UPLOAD_DIR, and appends {label, url, filename} to
    ``overrides["relevant_uploads"]``. Remove: drops the entry and unlinks the file
    best-effort.

    PERSISTENCE CAVEAT: see the note above — local disk is not durable on Render's
    zero-downtime deploys; durable storage needs S3/R2.
    """
    conn = db.connect()
    try:
        if action == "remove" and filename.strip():
            base = os.path.basename(filename.strip())
            overrides = db.get_doc_overrides(conn, opp_id)
            uploads = [
                u for u in list(overrides.get("relevant_uploads") or [])
                if u.get("filename") != base
            ]
            db.update_doc_override(conn, opp_id, "relevant_uploads", uploads or None)
            try:    # best-effort unlink; never fail the request on a missing file
                os.remove(os.path.join(UPLOAD_DIR, base))
            except OSError:
                pass
            return _doc_back(opp_id, return_to)

        if file is None or not (file.filename or "").strip():
            return _doc_back(opp_id, return_to)

        ext = os.path.splitext(file.filename)[1].lower()
        ctype = (file.content_type or "").lower()
        is_audio = ext in _AUDIO_EXTS or ctype.startswith("audio/")
        if not is_audio:
            return PlainTextResponse(
                "Only audio files are accepted (.mp3, .wav, .m4a, .aac, .ogg, .flac).",
                status_code=400,
            )
        if ext not in _AUDIO_EXTS:
            ext = ".mp3"   # audio/* with an odd extension → store under a known one

        data = await file.read()
        # Safe, unique on-disk name: opp-scoped + a counter so re-uploads don't clash.
        existing = {
            u.get("filename")
            for u in (db.get_doc_overrides(conn, opp_id).get("relevant_uploads") or [])
        }
        n = 1
        while f"opp{opp_id}-{n}{ext}" in existing or os.path.exists(
            os.path.join(UPLOAD_DIR, f"opp{opp_id}-{n}{ext}")
        ):
            n += 1
        safe_name = f"opp{opp_id}-{n}{ext}"
        with open(os.path.join(UPLOAD_DIR, safe_name), "wb") as fh:
            fh.write(data)

        overrides = db.get_doc_overrides(conn, opp_id)
        uploads = list(overrides.get("relevant_uploads") or [])
        uploads.append({
            "label": label.strip() or file.filename,
            "url": f"/uploads/{safe_name}",
            "filename": safe_name,
        })
        db.update_doc_override(conn, opp_id, "relevant_uploads", uploads)
    finally:
        conn.close()
    return _doc_back(opp_id, return_to)


@app.post("/buyer/{client}/website")
def set_buyer_website(client: str, website: str = Form("")):
    """Persist the company's website (a company-level attribute, not per-opp)."""
    conn = db.connect()
    try:
        db.set_company_website(conn, client, website)
    finally:
        conn.close()
    return RedirectResponse(f"/buyer/{client}", status_code=303)


# --------------------------------------------------------------------------- #
# Talent (supply side) — roster, profile, demo-reel review, invite funnel
# --------------------------------------------------------------------------- #
# Disciplines offered in talent forms (exclude the disqualified NON_CRAFT bucket).
FORM_DISCIPLINES = [d for d in MusicDiscipline if d is not MusicDiscipline.NON_CRAFT]


_SOURCE_CHANNELS = ["applied", "sourced", "referral", "manual"]


@app.get("/talent", response_class=HTMLResponse)
def talent_roster(
    request: Request,
    discipline: Optional[str] = None,
    review: Optional[str] = None,
    invite: Optional[str] = None,
    source: Optional[str] = None,
    sort: str = "name",
):
    conn = db.connect()
    try:
        rows = db.list_talent(conn, discipline=discipline, review=review, invite=invite)
        talents = [db.talent_from_row(r) for r in rows]
        # The reel-review queue is the gate only Jon can clear — show every
        # pending creator regardless of the current filter, with completeness.
        review_queue = [
            {"t": t, "completeness": profile_completeness(t)}
            for t in (db.talent_from_row(r) for r in db.list_talent(conn, review="Pending"))
        ]
        # Roster-wide counts (independent of the active filter).
        all_talents = [db.talent_from_row(r) for r in db.list_talent(conn)]
    finally:
        conn.close()
    # Origin-channel filter (applied | sourced | referral | manual) — answers
    # "where's my sourced channel?" by making each intake lane visible/filterable.
    if source in _SOURCE_CHANNELS:
        talents = [t for t in talents if t.source_channel == source]
    cards = [{"t": t, "completeness": profile_completeness(t)} for t in talents]
    sorters = {
        "name": lambda c: c["t"].name.lower(),
        "completeness": lambda c: -c["completeness"],
        "matchable": lambda c: (not c["t"].matchable, -c["completeness"]),
        "discipline": lambda c: (c["t"].discipline_labels[0] if c["t"].discipline_labels else "~"),
    }
    cards.sort(key=sorters.get(sort, sorters["name"]))
    counts = {
        "total": len(all_talents),
        "approved": sum(1 for t in all_talents if t.is_approved),
        "pending": sum(1 for t in all_talents if t.review_status.value == "Pending"),
        "matchable": sum(1 for t in all_talents if t.matchable),
        "sourced": sum(1 for t in all_talents if t.source_channel == "sourced"),
    }
    active = {
        "discipline": discipline or "", "review": review or "",
        "invite": invite or "", "source": source if source in _SOURCE_CHANNELS else "",
        "sort": sort,
    }
    return render(
        request, "talent_roster.html", nav="talent", cards=cards, counts=counts,
        disciplines=FORM_DISCIPLINES, review_states=db.REVIEW_STATES,
        invite_states=db.INVITE_STATES, source_channels=_SOURCE_CHANNELS,
        active=active, review_queue=review_queue,
    )


_ADD_SOURCES = {"manual", "sourced", "referral"}


@app.get("/talent/new", response_class=HTMLResponse)
def talent_new(request: Request, source: str = "manual"):
    # ?source=sourced renders the "log a candidate I found myself" variant — the
    # human-in-the-loop workaround for bot-blocked sites: browse the site in your
    # own signed-in browser, then log the worth-reviewing creators here.
    preset = source if source in _ADD_SOURCES else "manual"
    return render(
        request, "talent_form.html", nav="talent", talent=None,
        disciplines=FORM_DISCIPLINES, source_preset=preset,
    )


_RATE_UNITS = {"hourly", "day", "project"}


def _clean_rate_unit(unit: str) -> str:
    unit = (unit or "hourly").strip().lower()
    return unit if unit in _RATE_UNITS else "hourly"


def _parse_rate(raw: str) -> Optional[float]:
    """Blank rate → None (no rate set); otherwise a float, ignoring bad input."""
    raw = (raw or "").strip().replace("$", "").replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@app.post("/talent")
def talent_create(
    name: str = Form(...),
    email: str = Form(""),
    disciplines: List[str] = Form([]),
    credits: str = Form(""),
    location: str = Form(""),
    demo_reel_url: str = Form(""),
    notes: str = Form(""),
    rate: str = Form(""),
    rate_unit: str = Form("hourly"),
    source: str = Form("manual"),
):
    valid = [MusicDiscipline(d) for d in disciplines if d in {m.value for m in MusicDiscipline}]
    origin = source if source in _ADD_SOURCES else "manual"
    reel_url = normalize_url(demo_reel_url)
    t = Talent(
        name=name.strip(), email=email.strip() or None, disciplines=valid,
        credits=credits.strip(), location=location.strip() or None,
        demo_reel_url=reel_url, notes=notes.strip(),
        rate=_parse_rate(rate), rate_unit=_clean_rate_unit(rate_unit),
        source=origin, source_url=reel_url,
    )
    conn = db.connect()
    try:
        new_id = db.insert_talent(conn, t)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{new_id}", status_code=303)


@app.get("/talent/{talent_id}", response_class=HTMLResponse)
def talent_detail(request: Request, talent_id: int, invite: str = ""):
    invite_result = invite  # ?invite=<send-status> flash; renamed to avoid shadowing
    conn = db.connect()
    try:
        row = db.get_talent(conn, talent_id)
        if row is None:
            return HTMLResponse("Talent not found", status_code=404)
        t = db.talent_from_row(row)
        portal_token = row["portal_token"] if "portal_token" in row.keys() else None
        w9_at = row["w9_received_at"] if "w9_received_at" in row.keys() else None
    finally:
        conn.close()
    portal_url = f"{_public_base()}/creator/{portal_token}" if portal_token else None
    # Recruiting composer: a personalized, deterministic invite draft Jon can copy,
    # edit, and send to a prospect (machine proposes, Jon disposes).
    base = _public_base()
    invite = recruiting.compose_invite(
        t, apply_url=f"{base}/apply", artists_url=f"{base}/for-artists")
    return render(
        request, "talent_detail.html", nav="talent", t=t,
        completeness=profile_completeness(t), disciplines=FORM_DISCIPLINES,
        review_states=db.REVIEW_STATES, invite_states=db.INVITE_STATES,
        portal_token=portal_token, portal_url=portal_url, w9_received_at=w9_at,
        invite=invite, mail_configured=mailer.mail_configured(),
        invite_result=invite_result,
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
    rate: str = Form(""),
    rate_unit: str = Form("hourly"),
):
    conn = db.connect()
    try:
        db.update_talent_profile(
            conn, talent_id, name.strip(), email, disciplines, credits.strip(),
            location, normalize_url(demo_reel_url) or "", notes.strip(),
            rate=_parse_rate(rate), rate_unit=_clean_rate_unit(rate_unit),
        )
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}", status_code=303)


@app.post("/talent/{talent_id}/review")
def talent_review(talent_id: int, review_status: str = Form(...), return_to: str = Form("")):
    """The reel-review verdict. An applicant left hearing nothing after
    applying is the exact gap reported live — a real transition INTO
    Approved or Declined (never a re-click of the state it's already in)
    emails them the outcome, with role/rate for an acceptance."""
    conn = db.connect()
    try:
        before = db.get_talent(conn, talent_id)
        was = before["review_status"] if before is not None else None
        db.update_talent_review(conn, talent_id, review_status)
        t = db.talent_from_row(db.get_talent(conn, talent_id)) if before is not None else None
    finally:
        conn.close()
    if (
        t is not None and was != review_status
        and review_status in ("Approved", "Declined")
        and t.email and mailer.mail_configured()
    ):
        base = _public_base()
        dec = recruiting.compose_review_decision(
            t, accepted=(review_status == "Approved"), artists_url=f"{base}/for-artists",
        )
        mailer.send_email(
            t.email, dec["subject"], dec["body"], html=mailer.branded_html(base, dec["body"]),
        )
    return RedirectResponse(
        _safe_local(return_to, f"/talent/{talent_id}"), status_code=303
    )


@app.post("/talent/{talent_id}/invite")
def talent_invite(talent_id: int, invite_status: str = Form(...)):
    conn = db.connect()
    try:
        db.update_talent_invite(conn, talent_id, invite_status)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}", status_code=303)


@app.post("/talent/{talent_id}/invite/send")
def talent_send_invite(talent_id: int):
    """Email the personalized recruiting invite to the creator and advance them to
    Invited. Falls back gracefully: with no email on file or mail unconfigured, it
    just flags 'copy it manually' (the draft is always on the page)."""
    conn = db.connect()
    try:
        row = db.get_talent(conn, talent_id)
        if row is None:
            return RedirectResponse("/talent", status_code=303)
        t = db.talent_from_row(row)
    finally:
        conn.close()
    email = (t.email or "").strip()
    if not email or not mailer.mail_configured():
        return RedirectResponse(f"/talent/{talent_id}?invite=manual#invite", status_code=303)
    base = _public_base()
    inv = recruiting.compose_invite(
        t, apply_url=f"{base}/apply", artists_url=f"{base}/for-artists")
    status = mailer.send_email(
        email, inv["subject"], inv["body"],
        html=mailer.branded_html(base, inv["body"]),
    )
    if status == "sent":
        conn = db.connect()
        try:
            db.update_talent_invite(conn, talent_id, "Invited")  # funnel advances
        finally:
            conn.close()
    return RedirectResponse(f"/talent/{talent_id}?invite={status}#invite", status_code=303)


@app.post("/talent/{talent_id}/portal")
def talent_issue_portal(talent_id: int):
    """Mint (or reveal) the creator's portal access token — their only credential
    for /creator/<token>. Jon issues this when a creator is qualified, then sends
    them the link. Idempotent: re-issuing returns the same token. If mail is
    configured and the creator has an email, also send them the link (best-effort)."""
    conn = db.connect()
    try:
        token = db.ensure_talent_portal_token(conn, talent_id)
        row = db.get_talent(conn, talent_id)
        email = (row["email"] or "").strip() if row is not None else ""
    finally:
        conn.close()
    if token and email and mailer.mail_configured():
        url = f"{_public_base()}/creator/{token}"
        mailer.send_email(
            email, "Your Chordential creator workspace",
            "You're set up in Chordential. Your personal workspace — where you'll see "
            f"assigned briefs and submit your work — is here:\n\n{url}\n\n"
            "It's private to you; no password needed. — Chordential")
    return RedirectResponse(f"/talent/{talent_id}#access", status_code=303)


@app.post("/talent/{talent_id}/w9")
def talent_set_w9(talent_id: int, received: str = Form("")):
    """Record/clear the creator's W-9-on-file date (the payout-ledger gate)."""
    from datetime import date as _date
    conn = db.connect()
    try:
        db.set_talent_w9(conn, talent_id,
                         _date.today().isoformat() if received == "1" else None)
    finally:
        conn.close()
    return RedirectResponse(f"/talent/{talent_id}#access", status_code=303)


# --------------------------------------------------------------------------- #
# Composer portal — a qualified creator's token-gated home. NOT admin-gated;
# the per-creator portal token IS the credential (same model as the client
# delivery portal). They see their assigned briefs and submit work versions.
# --------------------------------------------------------------------------- #
def _creator_feedback(conn, project_id: int, delivery: dict) -> dict:
    """The client's review feedback on the current version, shaped read-only for the
    composer's portal — so they see the timecoded notes and change requests directly
    instead of Jon hand-relaying them (the whole point of the timecode feature).
    Returns the actionable notes for the current version + the revision budget."""
    cur = current_version(delivery)
    cur_n = str(cur["n"]) if cur else "0"
    notes = []
    for c in db.list_review_comments(conn, project_id):
        # Only the notes a composer acts on, and only for the version they're on now.
        if c["kind"] not in ("comment", "change_request", "asset_change"):
            continue
        if (c["version"] or "") != cur_n:
            continue
        notes.append({
            "t": c["t_seconds"], "author": c["author"], "body": c["body"],
            "kind": c["kind"], "resolved": bool(c["resolved"]),
        })
    return {
        "notes": notes,
        "open_count": sum(1 for n in notes if not n["resolved"]),
        "revisions_used": int(delivery.get("revisions_used") or 0),
        "revisions_included": int(delivery.get("revisions_included") or 0) or None,
    }


def _creator_assignment_view(conn, talent_id: int) -> list:
    """Per-assignment cards for the composer portal: brief, role, deadline, the
    delivery state, the versions THIS creator can submit/see, and the client's
    review feedback on the current version (read-only)."""
    out = []
    for a in db.list_talent_assignments(conn, talent_id):
        delivery = db.get_delivery(conn, a["project_id"])
        out.append({
            "project_id": a["project_id"],
            "role": a["role"],
            "client": a["client"],
            "need": a["need"],
            "deadline": a["deadline"],
            "status": a["status"],
            "delivery_state": (delivery.get("state") or "Not started"),
            "version_state": (delivery.get("version_state") or ""),
            "versions": versions_list(delivery),
            "feedback": _creator_feedback(conn, a["project_id"], delivery),
        })
    return out


@app.get("/creator/{token}", response_class=HTMLResponse)
def creator_portal(request: Request, token: str):
    conn = db.connect()
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        t = db.talent_from_row(row)
        assignments = _creator_assignment_view(conn, row["id"])
    finally:
        conn.close()
    return render(
        request, "creator_portal.html", nav="", token=token, t=t,
        completeness=profile_completeness(t), assignments=assignments,
    )


@app.post("/creator/{token}/project/{project_id}/version")
async def creator_submit_version(
    token: str, project_id: int, file: Optional[UploadFile] = File(None),
):
    """A creator submits a work version for a project they're assigned to.

    Reuses the exact version-ladder mechanism the admin Assets agent uses, so a
    creator-submitted master is a first-class version. Guarded twice: a valid
    portal token AND an actual assignment to this project."""
    conn = db.connect()
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        if not db.talent_is_assigned(conn, row["id"], project_id):
            return HTMLResponse("Not assigned to this project", status_code=403)
        if file is None or not (file.filename or "").strip():
            return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)
        data = await file.read()
        who = row["name"]
        # A creator's submission does NOT go straight to the client — it waits as a
        # pending submission for Jon to vet, then publish. This is the "machine
        # proposes, Jon disposes" gate the old code claimed but never enforced (it
        # appended directly to the client-visible ladder).
        _store_pending_submission(conn, project_id, data, file.filename, who)
        prow = db.get_project(conn, project_id)
        campaign = (prow["need"] if prow is not None else "") or "Campaign"
        db.add_update(conn, project_id, f"{who} submitted a new version — pending your review.")
    finally:
        conn.close()
    # Composer-direction notification: ping Jon (the operator) that new work landed
    # — NOT the client. Offloaded to a thread: the push/SMTP calls do blocking network
    # I/O, and this is an async handler on uvicorn's single event loop — inline they'd
    # freeze the whole site (every page, every portal, /healthz) for the send.
    await run_in_threadpool(
        _notify_operator_review,
        project_id, None, f"New work submitted — {campaign}",
        f"{who} submitted a new version. Review and publish it in the delivery console.")
    return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)


# --------------------------------------------------------------------------- #
# Projects + assignment (supply side) — Jon assigns; nothing auto-assigns
# --------------------------------------------------------------------------- #
@app.get("/projects", response_class=HTMLResponse)
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


def _ensure_project_for_opp(conn, opp_id: int) -> Optional[int]:
    """Return the opportunity's project id, creating the project (with scoped
    roles + default milestones) if it doesn't exist yet. Shared by the project
    button and the Match Board so both stay in sync."""
    existing = db.project_for_opp(conn, opp_id)
    if existing is not None:
        return existing["id"]
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None
    qual, scored = ev
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    roles = qual.team_shape or discipline.team_shape
    pid = db.insert_project(
        conn, opp_id, opp.client, opp.need, opp.budget_min, opp.budget_max, roles
    )
    db.seed_default_milestones(conn, pid, roles)
    return pid


@app.post("/opportunity/{opp_id}/project")
def create_project(opp_id: int):
    conn = db.connect()
    try:
        if db.get_opportunity(conn, opp_id) is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        pid = _ensure_project_for_opp(conn, opp_id)
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
        # Per-role pay priors so Jon sees the cost of each scoped role.
        "role_rates": {role: ROLE_RATES.get(role) for role in roles},
        # When an assigned talent has their own rate it overrides the role
        # default in the proposal — surface it so the cost source is clear.
        "rate_overrides": db.assigned_rate_overrides(conn, project_id),
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
    """The decision action — Jon assigns a creator to a role. The only assign
    path. Reported live: signing a creator should email them the project
    scope — this is the one place that decision is made, so it's the one
    place the email fires from."""
    conn = db.connect()
    try:
        db.add_assignment(conn, project_id, role, talent_id)
        row = db.get_talent(conn, talent_id)
        t = db.talent_from_row(row) if row is not None else None
        name = t.name if t else "a creator"
        db.add_update(conn, project_id, f"{name} assigned to {role}.", "assignment")
        project = db.get_project(conn, project_id)
    finally:
        conn.close()
    if t is not None and t.email and mailer.mail_configured() and project is not None:
        base = _public_base()
        scope = recruiting.compose_project_assignment(
            t, role=role, client=project["client"], need=project["need"],
            budget_low=project["budget_min"], budget_high=project["budget_max"],
            deadline=project["deadline"] or "",
        )
        mailer.send_email(
            t.email, scope["subject"], scope["body"],
            html=mailer.branded_html(base, scope["body"]),
        )
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
        # Delivery folds into the money flow: once every milestone is Done and a
        # proposal exists, draft the final invoice (once) so closing the work and
        # billing for it are one motion. Jon still issues + marks it paid.
        if status == "Done":
            progress = db.milestone_progress(conn, project_id)
            prop = db.proposal_for_project(conn, project_id)
            if (
                progress["total"] > 0 and progress["done"] == progress["total"]
                and prop is not None and not db.has_invoice(conn, project_id, "Final")
            ):
                prow = db.get_project(conn, project_id)
                inv = _invoice_from_proposal_row(prow, prop, "Final")
                db.insert_invoice(conn, project_id, prop["id"], inv)
                db.add_update(
                    conn, project_id,
                    "Final invoice drafted (all milestones delivered).", "invoice",
                )
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


# --------------------------------------------------------------------------- #
# Delivery OS (Phase 0, Pass A) — the delivery engine + generated package +
# client-facing portal. Deterministic assembly; Jon presses the human buttons
# (license terms, log a revision, approve, release). See chordential_oia.delivery.
# --------------------------------------------------------------------------- #
def _project_estimate(conn, row):
    """The estimate behind a project (for scoped revision rounds), or None.

    Rebuilt from the linked opportunity the same way the project view does — used
    only to read the revision multiplier. None when there's no linked opp."""
    opp_id = row["opp_id"] if "opp_id" in row.keys() else None
    if opp_id is None:
        return None
    opp_row = db.get_opportunity(conn, opp_id)
    if opp_row is None:
        return None
    opp = db.opportunity_from_row(opp_row)
    qual, _ = evaluate(opp)
    team = list(qual.team_shape or qual.discipline.team_shape)
    overrides = db.assigned_rate_overrides(conn, row["id"])
    return build_estimate(opp, team, qual.discipline, rate_overrides=overrides)


def _delivery_view(conn, project_id: int, selected_v=None):
    """Assemble the Delivery OS data for a project (engine docs + state), or None.

    ``selected_v`` (IP2) picks which version the review surface opens — its track
    loads in the player and its comments filter to that version's number. Defaults
    to the current (latest) version so the existing behaviour is unchanged."""
    row = db.get_project(conn, project_id)
    if row is None:
        return None
    assignments = db.list_assignments(conn, project_id)
    delivery = db.get_delivery(conn, project_id)
    license = delivery.get("license") or {}
    estimate = _project_estimate(conn, row)

    versions = versions_list(delivery)
    current = current_version(delivery)

    # IP3 (defensible rights): the certificate carries a signatory block, the
    # version it certifies, the date, and reads the license grant as a draft until
    # the operator explicitly confirms the terms (no silent buyout-by-default).
    from datetime import date as _date
    license_conf = license_confirmation(delivery)
    certified_version = (current.get("label") if current else "") or ""
    cert = build_clearance_certificate(
        row, assignments, license,
        signatory=delivery.get("signatory"),
        license_confirmed=license_conf,
        certified_version=certified_version,
        certified_date=_date.today().isoformat(),
    )
    cues = build_cue_sheet(row, assignments, delivery=delivery)
    manifest = build_manifest(
        row, assets=delivery.get("assets") or [], versions=versions
    )
    revisions = revision_status(row, estimate, delivery)
    token = db.ensure_project_share_token(conn, project_id)

    # The creative brief (Phase 4): the logged brief, or defaults seeded from the
    # opportunity behind the project (need → objective, description → references/tone).
    opp_row = db.get_opportunity(conn, row["opp_id"]) if row["opp_id"] is not None else None
    brief = seed_brief(row, opp_row, delivery)
    # Brief-as-contract: reconcile the brief's deliverables against the delivered
    # assets so both portal + console show what was promised vs delivered.
    brief_recon = reconcile_brief(brief, delivery.get("assets") or [])
    brief_roll = brief_rollup(brief_recon)
    # Delivery-completeness gate: which scoped, upload-required deliverables have a
    # real uploaded asset vs which are silently missing — drives the portal/console
    # warnings + the honest partial labelling so we never ship "everything" when the
    # cutdowns/stems were never uploaded.
    completeness = delivery_completeness(row, delivery)
    comments = db.list_review_comments(conn, project_id)
    timeline = build_timeline(row, delivery, comments)

    # Per-asset approval (granular sign-off): attach each deliverable asset's
    # current per-asset status + stable key so the portal/console can render a
    # badge and the reviewer can Approve / Request changes one asset at a time.
    assets_for_approval = list(delivery.get("assets") or [])
    assets_with_approval = []
    for a in assets_for_approval:
        a2 = dict(a)
        a2["approval"] = db.get_asset_approval(delivery, a)
        a2["asset_key"] = db.asset_key(a)
        assets_with_approval.append(a2)

    # Make per-asset approval discoverable on the client portal: surface EVERY
    # scoped deliverable with a clear status — ✓ uploaded (carrying the matching
    # asset's per-asset-approval row + stable key, so verified reviewers get the
    # Approve / Request-changes controls) vs ⧗ not uploaded yet ("waiting on
    # Chordential"). Most demo deliverables are referenced-only, so showing only
    # uploaded assets hid the per-deliverable controls; this surfaces the full list.
    _by_label = {}
    for a in assets_with_approval:
        lbl = (a.get("label") or a.get("filename") or "").strip()
        if lbl and lbl not in _by_label:
            _by_label[lbl] = a
    scoped_list = []
    n_scoped_approved = 0
    for d in scoped_deliverables(row, delivery):
        item = dict(d)
        match_asset = _by_label.get(d.get("match") or "")
        if match_asset is not None:
            item["asset_key"] = match_asset.get("asset_key")
            item["approval"] = match_asset.get("approval")
            item["url"] = match_asset.get("url")
            item["kind"] = match_asset.get("kind")
            if (match_asset.get("approval") or {}).get("status") == "Approved":
                n_scoped_approved += 1
        else:
            item["asset_key"] = ""
            item["approval"] = None
        scoped_list.append(item)
    scoped_rollup = {
        "approved": n_scoped_approved,
        "total": len(scoped_list),
        "uploaded": sum(1 for s in scoped_list if s.get("uploaded")),
    }

    current_n = int(current["n"]) if current else 0

    # IP2: the reviewer can open ANY version, not just current. Resolve the
    # selected version (default = current); its track drives the player and its
    # comments filter to that version's number, so v1 ↔ v2 is navigable/playable.
    selected = current
    if selected_v not in (None, ""):
        try:
            want = int(selected_v)
        except (TypeError, ValueError):
            want = None
        if want is not None:
            match = next((v for v in versions if int(v.get("n") or 0) == want), None)
            if match is not None:
                selected = match
    selected_n = int(selected["n"]) if selected else 0

    # The version under review (anti-chaos): the SELECTED version's audio drives
    # the review player; fall back to the first uploaded audio asset for Phase-0
    # projects that never logged a version.
    review_track = selected
    if review_track is None:
        assets = delivery.get("assets") or []
        review_track = next((a for a in assets if a.get("kind") == "audio"), None)

    # IP2: per-version open/resolved counts for the SELECTED version (kind='comment'
    # top-level notes only — replies inherit their parent's thread, approvals/change
    # requests aren't resolvable).
    sel_open = sel_resolved = 0
    for c in comments:
        if (c["kind"] or "comment") != "comment" or c["parent_id"] is not None:
            continue
        if selected_n != 0 and str(c["version"]) != str(selected_n):
            continue
        if c["resolved"]:
            sel_resolved += 1
        else:
            sel_open += 1

    # Payment gate on DOWNLOADS (not on streaming/preview — the client must be able
    # to review before paying). Deliverables unlock when the client is paid in full
    # OR Jon has manually unlocked this delivery. Streaming src stays on /uploads;
    # only the ZIP + per-asset DOWNLOAD links route through the gated _can-download_ path.
    balance = db.invoice_balance(conn, project_id)
    download_unlocked = bool(delivery.get("download_unlocked")) or balance["paid_in_full"]
    # Build gated download URLs (carry the share token so the route can authorize).
    def _dl(name: str) -> str:
        base = os.path.basename(name or "")
        return f"/project/{project_id}/dl/{base}?k={token}" if base else ""
    zip_obj = delivery.get("delivery_zip")
    if zip_obj:
        zip_obj = dict(zip_obj)
        zip_obj["dl_url"] = _dl(zip_obj.get("filename") or "")
    for a in assets_with_approval:
        fn = a.get("filename") or os.path.basename(a.get("url") or "")
        a["dl_url"] = _dl(fn)

    return {
        "row": row,
        "project": row,
        "assignments": assignments,
        "delivery": delivery,
        "download_unlocked": download_unlocked,
        "invoice_balance": balance,
        "state": delivery.get("state") or DELIVERY_STATES[0],
        "version_state": revisions["state"],
        "cert": cert,
        "cues": cues,
        "manifest": manifest,
        "revisions": revisions,
        "license": cert.license,
        # IP3 — defensible rights: signatory block + explicit license confirmation.
        "signatory": merge_signatory(delivery.get("signatory")),
        "license_confirmed": license_conf,
        "assignable_folders": ASSIGNABLE_FOLDERS,
        "cue_meta": delivery.get("cue_meta") or {},
        "approvals": delivery.get("approvals") or [],
        # Verified-identity approval: the operator-invited reviewer roster — each has
        # a personal ?r= invite link (the only way to approve).
        "reviewers": delivery.get("reviewers") or [],
        # Outbound-email status: honest indicator on the reviewers card — whether
        # invites / new-version notices go out automatically or links are copied
        # by hand (mailer is null/unconfigured until SMTP env is set).
        "mail_configured": mailer.mail_configured(),
        # A creator's submission awaiting Jon's publish decision (console-only; the
        # client portal never reads this — pending work stays off the client's page).
        "pending_version": delivery.get("pending_version") or None,
        "assets": assets_with_approval,
        # Per-asset approval rollup ("N of M deliverables approved") — surfaced
        # next to the whole-version Approve so the gap is visible.
        "asset_rollup": db.asset_approval_rollup(delivery, assets_for_approval),
        "asset_approval_states": db.ASSET_APPROVAL_STATES,
        # Delivery-completeness gate: {expected, uploaded, missing, complete, text}
        # — drives the warnings + honest partial labelling on portal + console.
        "completeness": completeness,
        # The FULL scoped deliverable list with per-item upload status (✓/⧗) +
        # per-asset approval controls on the uploaded ones, + an N-of-M rollup.
        "scoped_deliverables": scoped_list,
        "scoped_rollup": scoped_rollup,
        "versions": versions,
        "current_version": current,
        "current_n": current_n,
        # IP2: which version the review surface is showing (default = current).
        "selected_version": selected,
        "selected_n": selected_n,
        "open_count": sel_open,
        "resolved_count": sel_resolved,
        "review_track": review_track,
        "released_at": delivery.get("released_at"),
        "share_token": token,
        "comments": comments,
        # Delivery automation (Phase 3): the assembled ZIP + the payoff checklist.
        "delivery_zip": zip_obj,
        "delivery_checklist": delivery.get("delivery_checklist") or [],
        # Creative brief + campaign timeline (Phase 4) — the dashboard's spine.
        "brief": brief,
        "brief_fields": BRIEF_FIELDS,
        # Brief-as-contract: the reconciliation list + the "N of M" rollup.
        "brief_items": brief_recon,
        "brief_rollup": brief_roll,
        "timeline": timeline,
        "version_states": VERSION_STATES,
    }


@app.get("/project/{project_id}/delivery", response_class=HTMLResponse)
def delivery_console(request: Request, project_id: int, release: str = ""):
    """The Campaign Dashboard / Delivery Console (Phase 4) — the operator's command
    center for one campaign. One screen tying the creative brief, the five-agent
    status row, the version rail, the review activity feed, the campaign timeline,
    the deliverable assets + upload controls, and the action toolbar (client review
    link, delivery package, build, release) together. The delivery mutation routes
    all redirect here, so it renders the console (no longer a bounce to the package).

    ``release=needs_license`` (IP3) flags that a release was refused because the
    license has not been explicitly confirmed yet."""
    conn = db.connect()
    try:
        view = _delivery_view(conn, project_id)
        if view is None:
            return HTMLResponse("Project not found", status_code=404)
    finally:
        conn.close()
    view["release_flag"] = release
    return render(request, "delivery_console.html", nav="projects", **view)


@app.post("/project/{project_id}/delivery/brief")
def delivery_set_brief(
    project_id: int,
    objective: str = Form(""),
    references: str = Form(""),
    tone: str = Form(""),
    deliverables_needed: str = Form(""),
    deadline: str = Form(""),
):
    """Creative brief (Phase 4): log/edit the brief that opens the campaign record.

    Stored raw on ``delivery_json['brief']`` (blank fields dropped so the engine
    falls back to the opportunity-seeded default for that field)."""
    conn = db.connect()
    try:
        brief = {
            "objective": objective.strip(),
            "references": references.strip(),
            "tone": tone.strip(),
            "deliverables_needed": deliverables_needed.strip(),
            "deadline": deadline.strip(),
        }
        brief = {k: v for k, v in brief.items() if v}
        db.update_delivery(conn, project_id, "brief", brief or None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#brief", status_code=303)


@app.get("/project/{project_id}/delivery-package", response_class=HTMLResponse)
def delivery_package(request: Request, project_id: int):
    """THE artifact — the generated, on-brand Clearance-Certified delivery package
    (print-to-PDF). Admin-gated; this is the proof-of-concept."""
    conn = db.connect()
    try:
        view = _delivery_view(conn, project_id)
        if view is None:
            return HTMLResponse("Project not found", status_code=404)
    finally:
        conn.close()
    return render(request, "delivery_package.html", nav="projects", **view)


@app.post("/project/{project_id}/delivery/license")
def delivery_set_license(
    project_id: int,
    type: str = Form(""),
    territory: str = Form(""),
    term: str = Form(""),
    exclusivity: str = Form(""),
    content_id: str = Form(""),
):
    """Log the license grant (Rights agent). Stored raw; the engine merges defaults."""
    conn = db.connect()
    try:
        license = {
            "type": type.strip(),
            "territory": territory.strip(),
            "term": term.strip(),
            "exclusivity": exclusivity.strip(),
            "content_id": content_id.strip(),
        }
        # Drop blank fields so the engine falls back to the standard term.
        license = {k: v for k, v in license.items() if v}
        db.update_delivery(conn, project_id, "license", license or None)
        # IP3: editing the license terms invalidates a prior confirmation — the
        # operator must re-confirm the new terms before the cert asserts them.
        db.update_delivery(conn, project_id, "license_confirmed", None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#license", status_code=303)


@app.post("/project/{project_id}/delivery/signatory")
def delivery_set_signatory(
    project_id: int,
    entity: str = Form(""),
    signer: str = Form(""),
    title: str = Form(""),
):
    """IP3 (Rights agent): set the Clearance Certificate's signatory block —
    entity, authorized signer, and title. Stored raw on
    ``delivery_json['signatory']`` (blank fields drop to the Chordential default)."""
    conn = db.connect()
    try:
        signatory = {
            "entity": entity.strip(),
            "signer": signer.strip(),
            "title": title.strip(),
        }
        signatory = {k: v for k, v in signatory.items() if v}
        db.update_delivery(conn, project_id, "signatory", signatory or None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#license", status_code=303)


@app.post("/project/{project_id}/delivery/reviewer")
def delivery_reviewer(
    project_id: int, action: str = Form("add"), name: str = Form(""),
    email: str = Form(""), role: str = Form(""), token: str = Form(""),
):
    """Verified-identity approval (operator side): manage the reviewer roster.

    ``action=add`` invites a named reviewer and mints their unique personal token
    (their ``?r=`` invite link is how the agency approves — a generic share link
    cannot). ``action=remove`` drops a reviewer by their token (their link stops
    working). Stored on ``delivery_json['reviewers']``."""
    conn = db.connect()
    invited = None
    campaign = "Campaign"
    try:
        project = db.get_project(conn, project_id)
        if project is None:
            return HTMLResponse("Project not found", status_code=404)
        if action == "remove":
            db.remove_delivery_reviewer(conn, project_id, token)
        elif name.strip():
            invited = db.add_delivery_reviewer(
                conn, project_id, name=name, email=email, role=role
            )
            campaign = _campaign_label(project)
    finally:
        conn.close()
    # Cheap win: if the mailer is configured, send the new reviewer their personal
    # link automatically. If it isn't, behavior is unchanged — the operator copies
    # the link by hand (nothing breaks today). Best-effort, never blocks the route.
    if invited and mailer.mail_configured():
        _email_reviewer_link(
            project_id, invited, campaign,
            subject=f"Your review link — {campaign}",
            lead="You've been invited to review the work.",
        )
    return RedirectResponse(f"/project/{project_id}/delivery#reviewers", status_code=303)


@app.post("/project/{project_id}/delivery/license/confirm")
def delivery_confirm_license(project_id: int, by: str = Form("")):
    """IP3 (Rights agent): the operator explicitly confirms the license terms —
    records who + when on ``delivery_json['license_confirmed']``. Until this is
    pressed the certificate shows the grant as "DRAFT — pending confirmation"
    (no silent buyout-by-default), and release is refused."""
    from datetime import date as _date
    conn = db.connect()
    try:
        signer = by.strip() or merge_signatory(
            db.get_delivery(conn, project_id).get("signatory")).get("signer", "")
        db.update_delivery(conn, project_id, "license_confirmed", {
            "by": signer or "Operator",
            "date": _date.today().isoformat(),
        })
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#license", status_code=303)


@app.post("/project/{project_id}/delivery/asset/folder")
def delivery_set_asset_folder(
    project_id: int,
    filename: str = Form(""),
    folder: str = Form(""),
):
    """IP3 (Assets agent): assign an uploaded asset's delivery folder so the ZIP
    files it where the operator says, not by keyword guess. Stored on the asset's
    ``folder`` key; a value outside ``ASSIGNABLE_FOLDERS`` clears it (back to the
    heuristic)."""
    conn = db.connect()
    try:
        base = os.path.basename((filename or "").strip())
        if base:
            delivery = db.get_delivery(conn, project_id)
            assets = list(delivery.get("assets") or [])
            chosen = folder.strip() if folder.strip() in ASSIGNABLE_FOLDERS else ""
            for a in assets:
                if a.get("filename") == base:
                    if chosen:
                        a["folder"] = chosen
                    else:
                        a.pop("folder", None)
            db.update_delivery(conn, project_id, "assets", assets or None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)


@app.post("/project/{project_id}/delivery/cue")
def delivery_set_cue_meta(
    project_id: int,
    cue: str = Form(""),
    duration: str = Form(""),
    isrc: str = Form(""),
    iswc: str = Form(""),
):
    """IP3 (Metadata agent): set a cue's Duration / ISRC / ISWC so the cue sheet is
    fileable. Stored on ``delivery_json['cue_meta']`` keyed by the cue name (blank
    fields drop, so an all-blank submit clears that cue's meta)."""
    conn = db.connect()
    try:
        key = (cue or "").strip()
        if key:
            delivery = db.get_delivery(conn, project_id)
            cue_meta = dict(delivery.get("cue_meta") or {})
            row = {
                "duration": duration.strip(),
                "isrc": isrc.strip(),
                "iswc": iswc.strip(),
            }
            row = {k: v for k, v in row.items() if v}
            if row:
                cue_meta[key] = row
            else:
                cue_meta.pop(key, None)
            db.update_delivery(conn, project_id, "cue_meta", cue_meta or None)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#license", status_code=303)


@app.post("/project/{project_id}/delivery/revision")
def delivery_revision(
    project_id: int,
    action: str = Form("log"),
    version_state: str = Form(""),
):
    """Revisions agent: log a round (increment used) or set the version state."""
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, project_id)
        if action == "version" and version_state in VERSION_STATES:
            db.update_delivery(conn, project_id, "version_state", version_state)
        else:  # log a revision round
            used = int(delivery.get("revisions_used") or 0) + 1
            db.update_delivery(conn, project_id, "revisions_used", used)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery", status_code=303)


@app.post("/project/{project_id}/delivery/asset")
async def delivery_asset(
    project_id: int,
    request: Request,
    label: str = Form(""),
    action: str = Form("add"),
    filename: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """Assets agent: upload (or remove) a deliverable file into the project's
    ``delivery_json['assets']`` list. Reuses the doc_upload audio/file handling and
    the local UPLOAD_DIR + /uploads/{name} mechanism (no S3/R2)."""
    conn = db.connect()
    try:
        if action == "remove" and filename.strip():
            base = os.path.basename(filename.strip())
            delivery = db.get_delivery(conn, project_id)
            assets = [
                a for a in list(delivery.get("assets") or [])
                if a.get("filename") != base
            ]
            db.update_delivery(conn, project_id, "assets", assets or None)
            try:
                os.remove(os.path.join(UPLOAD_DIR, base))
            except OSError:
                pass
            return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)

        if file is None or not (file.filename or "").strip():
            return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)

        ext = os.path.splitext(file.filename)[1].lower()
        ctype = (file.content_type or "").lower()
        kind = "audio" if (ext in _AUDIO_EXTS or ctype.startswith("audio/")) else "file"
        data = await file.read()

        # Safe, unique on-disk name: project-scoped + a counter so re-uploads don't clash.
        existing = {
            a.get("filename")
            for a in (db.get_delivery(conn, project_id).get("assets") or [])
        }
        safe_ext = ext if ext else (".mp3" if kind == "audio" else ".bin")
        n = 1
        while f"proj{project_id}-{n}{safe_ext}" in existing or os.path.exists(
            os.path.join(UPLOAD_DIR, f"proj{project_id}-{n}{safe_ext}")
        ):
            n += 1
        safe_name = f"proj{project_id}-{n}{safe_ext}"
        with open(os.path.join(UPLOAD_DIR, safe_name), "wb") as fh:
            fh.write(data)

        delivery = db.get_delivery(conn, project_id)
        assets = list(delivery.get("assets") or [])
        assets.append({
            "label": label.strip() or file.filename,
            "url": f"/uploads/{safe_name}",
            "filename": safe_name,
            "kind": kind,
        })
        db.update_delivery(conn, project_id, "assets", assets)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)


def _next_version_label(delivery: dict, *, final: bool = False) -> tuple:
    """The next version's ``(n, label)`` for a logged version upload.

    n is one past the latest logged version (1 for the first). The label follows
    the v1 Concept → v2 Direction-lock → v3 FINAL ladder, forced to FINAL when the
    delivery is being released/approved (``final=True``)."""
    n = len(versions_list(delivery)) + 1
    return n, version_label(n, final=final)


def _append_version_from_bytes(conn, project_id: int, data: bytes, src_filename: str) -> tuple:
    """Write uploaded audio bytes as the next version in a project's delivery ladder.

    Shared by the admin Assets agent and the composer portal so both produce
    identically-named versions, advance ``version_state``, and reopen an
    already-approved delivery to review (a new master supersedes prior sign-off).
    Returns ``(label, campaign)`` for the caller's notification."""
    from datetime import datetime as _dt, timezone as _tz
    delivery = db.get_delivery(conn, project_id)
    versions = versions_list(delivery)
    ext = os.path.splitext(src_filename or "")[1].lower()
    safe_ext = ext if ext in _AUDIO_EXTS else ".mp3"
    n, label = _next_version_label(delivery)
    row = db.get_project(conn, project_id)
    campaign = (row["need"] if row is not None else "") or "Campaign"
    stem = version_name(campaign, "Master", 60, "Master", n,
                        "FINAL" if "FINAL" in label.upper() else f"v{n}")
    safe_name = f"proj{project_id}-v{n}{safe_ext}"
    bump = 1
    while os.path.exists(os.path.join(UPLOAD_DIR, safe_name)):
        safe_name = f"proj{project_id}-v{n}-{bump}{safe_ext}"
        bump += 1
    with open(os.path.join(UPLOAD_DIR, safe_name), "wb") as fh:
        fh.write(data)
    versions.append({
        "n": n,
        "label": label,
        "url": f"/uploads/{safe_name}",
        "filename": safe_name,
        "name": stem,
        "created_at": _dt.now(_tz.utc).isoformat(),
    })
    db.update_delivery(conn, project_id, "versions", versions)
    db.update_delivery(conn, project_id, "version_state", label)
    # A new version supersedes any prior approval/delivery — reopen to review.
    if (delivery.get("state") or "") in ("Approved", "Delivered"):
        db.update_delivery(conn, project_id, "state", "In review")
    return label, campaign


def _store_pending_submission(conn, project_id: int, data: bytes,
                              src_filename: str, who: str) -> None:
    """A creator's submission lands here — NOT in the client-visible version ladder.
    It waits in ``delivery_json['pending_version']`` until Jon publishes it, so the
    client never hears work he hasn't vetted ("the machine proposes, Jon disposes").
    The file is written now; publishing just moves the metadata into the ladder."""
    from datetime import datetime as _dt, timezone as _tz
    ext = os.path.splitext(src_filename or "")[1].lower()
    safe_ext = ext if ext in _AUDIO_EXTS else ".mp3"
    safe_name = f"proj{project_id}-pending{safe_ext}"
    bump = 1
    while os.path.exists(os.path.join(UPLOAD_DIR, safe_name)):
        safe_name = f"proj{project_id}-pending-{bump}{safe_ext}"
        bump += 1
    with open(os.path.join(UPLOAD_DIR, safe_name), "wb") as fh:
        fh.write(data)
    db.update_delivery(conn, project_id, "pending_version", {
        "url": f"/uploads/{safe_name}",
        "filename": safe_name,
        "orig": src_filename or "",
        "by": who or "A creator",
        "at": _dt.now(_tz.utc).isoformat(),
    })


def _publish_pending_submission(conn, project_id: int):
    """Move the pending creator submission into the live version ladder (Jon's
    'Publish to client' press). Returns ``(label, campaign)`` for the client-direction
    notification, or ``None`` if there was nothing pending."""
    from datetime import datetime as _dt, timezone as _tz
    delivery = db.get_delivery(conn, project_id)
    pv = delivery.get("pending_version")
    if not pv:
        return None
    versions = versions_list(delivery)
    n, label = _next_version_label(delivery)
    row = db.get_project(conn, project_id)
    campaign = (row["need"] if row is not None else "") or "Campaign"
    stem = version_name(campaign, "Master", 60, "Master", n,
                        "FINAL" if "FINAL" in label.upper() else f"v{n}")
    versions.append({
        "n": n, "label": label, "url": pv.get("url"),
        "filename": pv.get("filename"), "name": stem,
        "created_at": _dt.now(_tz.utc).isoformat(),
        "from_creator": pv.get("by") or "",
    })
    db.update_delivery(conn, project_id, "versions", versions)
    db.update_delivery(conn, project_id, "version_state", label)
    db.update_delivery(conn, project_id, "pending_version", "")   # consumed
    if (delivery.get("state") or "") in ("Approved", "Delivered"):
        db.update_delivery(conn, project_id, "state", "In review")
    return label, campaign


@app.post("/project/{project_id}/delivery/version")
async def delivery_version(
    project_id: int,
    request: Request,
    action: str = Form("add"),
    filename: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """Revisions + Assets agents: log a new **version** of the master.

    Uploads an audio file into the project's ``delivery_json['versions']`` ladder
    (reusing the local UPLOAD_DIR + /uploads/{name} mechanism), names it
    deterministically, advances ``version_state`` to the new label, and — if the
    delivery had been Approved — reopens it to "In review" (a new version means the
    prior approval no longer stands). ``action=remove`` drops the newest version."""
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, project_id)
        versions = versions_list(delivery)

        # Remove the newest version (optional housekeeping).
        if action == "remove" and versions:
            dropped = versions[-1]
            db.update_delivery(conn, project_id, "versions", versions[:-1] or None)
            remaining = versions_list(db.get_delivery(conn, project_id))
            new_state = (remaining[-1]["label"] if remaining
                         else VERSION_STATES[0])
            db.update_delivery(conn, project_id, "version_state", new_state)
            try:
                os.remove(os.path.join(UPLOAD_DIR, os.path.basename(
                    dropped.get("filename") or "")))
            except OSError:
                pass
            return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)

        if file is None or not (file.filename or "").strip():
            return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)

        data = await file.read()
        label, campaign = _append_version_from_bytes(conn, project_id, data, file.filename)
        # Agency-direction notification (the documented TODO): email each named
        # reviewer their personal review link so coordination stops leaking to
        # manual messaging. Best-effort, per reviewer — never blocks the upload.
        reviewers = db.list_delivery_reviewers(conn, project_id)
    finally:
        conn.close()
    # Offloaded to a thread: this is an async handler and the per-reviewer email loop
    # does blocking SMTP — inline it would stall uvicorn's single event loop (the whole
    # site, including health probes) for up to N reviewers × the socket timeout.
    await run_in_threadpool(
        _notify_reviewers_new_version, project_id, campaign, label, reviewers)
    return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)


@app.post("/project/{project_id}/delivery/approve")
def delivery_approve(
    project_id: int,
    asset: str = Form(...),
    approver: str = Form(...),
):
    """Approvals agent: log a sign-off (approved_by + today's date) per asset."""
    from datetime import date as _date
    conn = db.connect()
    try:
        if asset.strip() and approver.strip():
            delivery = db.get_delivery(conn, project_id)
            approvals = list(delivery.get("approvals") or [])
            approvals.append({
                "asset": asset.strip(),
                "approver": approver.strip(),
                "date": _date.today().isoformat(),
            })
            db.update_delivery(conn, project_id, "approvals", approvals)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery", status_code=303)


@app.post("/project/{project_id}/delivery/release")
def delivery_release(project_id: int):
    """Approvals agent: mark the delivery Released (state + released_at stamp).

    IP3: REFUSES to release until the license has been explicitly confirmed (the
    "Confirm license terms" console action). Without confirmation the certificate
    would assert a silent perpetual/worldwide/exclusive buyout — so we bounce back
    to the console with a flag instead of releasing."""
    from datetime import date as _date
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, project_id)
        if license_confirmation(delivery) is None:
            return RedirectResponse(
                f"/project/{project_id}/delivery?release=needs_license#delivery",
                status_code=303,
            )
        db.update_delivery(conn, project_id, "state", "Released")
        db.update_delivery(conn, project_id, "released_at", _date.today().isoformat())
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#delivery", status_code=303)


@app.get("/project/{project_id}/delivery-portal", response_class=HTMLResponse)
def delivery_portal(request: Request, project_id: int, k: str = "", v: str = "",
                    r: str = ""):
    """The client-facing, token-gated delivery page. NOT admin-gated — access is by
    one of two tokens:

    * ``?k=<share_token>`` — the generic share link: view + comment as a **guest**
      (still name + email), but the Approve control is disabled.
    * ``?r=<reviewer_token>`` — a **verified** reviewer's personal invite link:
      their name + email are taken (locked) from the roster and they may approve.

    ``r`` is itself an access token (it grants the same view as ``k``), so a valid
    ``r`` works on its own — no ``k`` required.

    ``?v=<n>`` (IP2) selects which logged version the review surface opens — its
    track plays and its comments show — so the reviewer can A/B any round."""
    conn = db.connect()
    try:
        row = db.get_project(conn, project_id)
        token = db.ensure_project_share_token(conn, project_id) if row is not None else None
        delivery = db.get_delivery(conn, project_id) if row is not None else {}
        verified = reviewer_from_token(delivery, r)
        k_ok = bool(token and k and hmac.compare_digest(str(k), str(token)))
        # A verified reviewer token grants access on its own; otherwise the share
        # token must match. A missing project / no valid token 404s identically.
        if row is None or not (k_ok or verified is not None):
            return HTMLResponse("Not found", status_code=404)
        view = _delivery_view(conn, project_id, selected_v=v)
    finally:
        conn.close()
    # The share token is what the page's generic forms carry. If the reviewer
    # arrived only via ?r= (no k), surface the project share token so guest forms
    # still work; verified actions carry ?r= instead.
    view["share_token"] = view.get("share_token") or token
    if verified is not None:
        # Verified reviewer: identity is LOCKED to the roster (not editable, not
        # spoofable by typing a different name) and Approve is enabled.
        view["reviewer_token"] = verified["token"]
        view["verified"] = True
        view["reviewer"] = {
            "name": verified.get("name") or "", "email": verified.get("email") or "",
            "role": verified.get("role") or "", "known": True, "verified": True,
        }
    else:
        # Guest (share-link) mode: free-entry identity for commenting, no approve.
        view["reviewer_token"] = ""
        view["verified"] = False
        r_name, r_email = _reviewer_identity(request)
        view["reviewer"] = {"name": r_name, "email": r_email,
                            "known": bool(r_name and r_email), "verified": False}
    return render(request, "delivery_portal.html", nav="", **view)


def _current_version_tag(delivery: dict) -> str:
    """The version number a comment/approval is tagged with: the current version's
    ``n`` (anti-chaos — feedback always lands on the version it was made against).
    Falls back to ``"0"`` for a Phase-0 project that never logged a version."""
    cur = current_version(delivery)
    return str(cur["n"]) if cur else "0"


def _review_token_ok(conn, project_id: int, k: str) -> bool:
    """The per-project share token is the access control for client review actions."""
    row = db.get_project(conn, project_id)
    if row is None:
        return False
    token = db.ensure_project_share_token(conn, project_id)
    return bool(token and k and hmac.compare_digest(str(k), str(token)))


def reviewer_from_token(delivery: dict, r: str):
    """Resolve a verified reviewer from their personal token (``?r=``), or None.

    The roster (``delivery_json['reviewers']``) is the set of named, operator-invited
    reviewers; a matching token means the reviewer is *verified* — their name + email
    come from the roster (not free-typed) and they may approve. Constant-time match."""
    r = (r or "").strip()
    if not r:
        return None
    for rv in (delivery.get("reviewers") or []):
        tok = (rv.get("token") or "") if isinstance(rv, dict) else ""
        if tok and hmac.compare_digest(str(r), str(tok)):
            return rv
    return None


def _access_ok(conn, project_id: int, k: str, r: str):
    """Resolve portal-action access: either a valid share token (``k``, guest) or a
    verified reviewer token (``r``). Returns ``(ok, reviewer_or_None)`` — ``reviewer``
    is the roster dict when the request came in on a verified ``?r=`` link."""
    delivery = db.get_delivery(conn, project_id)
    reviewer = reviewer_from_token(delivery, r)
    if reviewer is not None:
        return True, reviewer
    return _review_token_ok(conn, project_id, k), None


# Delivery OS IP1 (trust & coordination): the reviewer sets their identity (name +
# email) once; we remember it in a cookie so they never retype it, and every
# comment/approve/change-request is attributed to a real email, not free text.
REVIEWER_COOKIE = "cdl_reviewer"


def _reviewer_identity(request: Request, author: str = "", email: str = ""):
    """Resolve the reviewer's (name, email): a freshly-posted identity wins, else
    fall back to the remembered cookie. Returns ``(name, email)`` (either blank)."""
    name = (author or "").strip()
    mail = (email or "").strip()
    if not name or not mail:
        cookie = request.cookies.get(REVIEWER_COOKIE) or ""
        if cookie:
            try:
                saved = json.loads(unquote(cookie))
                name = name or (saved.get("name") or "").strip()
                mail = mail or (saved.get("email") or "").strip()
            except Exception:  # noqa: BLE001 — a malformed cookie just means "ask again"
                pass
    return name, mail


def _set_reviewer_cookie(resp, name: str, email: str) -> None:
    """Remember the reviewer's identity so they set it once, not per action."""
    if not (name and email):
        return
    value = quote(json.dumps({"name": name, "email": email}))
    resp.set_cookie(
        REVIEWER_COOKIE, value, samesite="lax", max_age=60 * 60 * 24 * 180,
    )


def _delivery_console_url(project_id: int) -> str:
    return f"/project/{project_id}/delivery"


def _public_base() -> str:
    """Absolute public base for links that land in an email (a relative path is
    dead in a mail client). Uses the configured domain; chordential.com default —
    matching the payments seam and outreach._page_url."""
    return os.environ.get(
        "CHORDENTIAL_PUBLIC_DOMAIN", "https://chordential.com"
    ).rstrip("/")


def _reviewer_review_url(project_id: int, token: str) -> str:
    """A reviewer's PERSONAL review link as an absolute URL (the ``?r=`` invite)."""
    return f"{_public_base()}/project/{project_id}/delivery-portal?r={token}"


def _email_reviewer_link(project_id: int, reviewer: dict, campaign: str,
                         *, subject: str, lead: str) -> str:
    """Best-effort: email one roster reviewer their personal review link.

    Skips reviewers without an email and never raises (the mailer itself is
    best-effort). Returns the mailer status for the caller's bookkeeping."""
    email = (reviewer.get("email") or "").strip()
    token = (reviewer.get("token") or "").strip()
    if not email or not token:
        return "skipped"
    url = _reviewer_review_url(project_id, token)
    name = (reviewer.get("name") or "there").strip() or "there"
    text = (
        f"Hi {name},\n\n{lead}\n\n"
        f"Campaign: {campaign}\n\n"
        f"Open your personal review link to listen, comment, and approve:\n{url}\n\n"
        "This link is yours — it's how you sign off on the work.\n\n"
        "— Chordential"
    )
    try:
        return mailer.send_email(email, subject, text)
    except Exception:  # noqa: BLE001 — mail is additive + best-effort, never block
        return "error"


def _notify_reviewers_new_version(project_id: int, campaign: str, label: str,
                                  reviewers: list) -> None:
    """Agency-direction notification: when a new version is uploaded, email each
    roster reviewer (who has an email) their personal review link. Best-effort,
    per reviewer — never blocks the upload (this was the documented TODO)."""
    subject = f"New version ready — {campaign}"
    lead = (
        f"A new version ({label}) is ready for your review."
    )
    for rv in (reviewers or []):
        try:
            _email_reviewer_link(project_id, rv, campaign, subject=subject, lead=lead)
        except Exception:  # noqa: BLE001 — one reviewer's failure must not stop the rest
            pass


def _notify_assigned_creators(project_id: int, project, *, subject: str,
                              body_text: str) -> None:
    """Composer-direction notification: email each assigned creator (with an email)
    when the client acts on their work — approved, or changes requested. Closes the
    loop the review portal opened: the composer hears the verdict from us instead of
    Jon relaying it by hand. Best-effort, per creator, never raises. Runs in its own
    DB connection so it's safe to fire-and-forget off the request thread."""
    conn = db.connect()
    try:
        assignments = db.list_assignments(conn, project_id)
    finally:
        conn.close()
    if not mailer.mail_configured():
        return
    base = _public_base()
    seen = set()
    for a in assignments:
        email = (a["talent_email"] or "").strip() if "talent_email" in a.keys() else ""
        if not email or email.lower() in seen:
            continue
        seen.add(email.lower())
        name = (a["talent_name"] or "there").strip() if "talent_name" in a.keys() else "there"
        text = f"Hi {name},\n\n{body_text}\n\n— Chordential"
        try:
            mailer.send_email(email, subject, text, html=mailer.branded_html(base, text))
        except Exception:  # noqa: BLE001 — best-effort; one creator's failure never stops the rest
            pass


def _notify_operator_review(project_id: int, project, title: str, body: str) -> None:
    """Push the operator (Jon) when the agency comments / requests changes /
    approves — the coordination signal that 'one link, no email' would otherwise
    drop. Best-effort, never blocks the request (mirrors notify_new_gig).

    Operator-direction only. Agency-direction email (notify the reviewer when a new
    version is uploaded) needs the deferred outbound-send infra that doesn't exist
    yet — see the TODO below; we do NOT fake it here.

    TODO(delivery-os): agency-direction notifications. When a new version is
    uploaded or the operator replies, email the reviewer at their captured
    ``review_comments.email``. Requires a transactional send channel (deferred
    outbound email infra) — not wired yet, so left unimplemented rather than faked.
    """
    url = _delivery_console_url(project_id)
    try:
        webpush.send_web_push(title, body=body, url=url)
    except Exception:  # noqa: BLE001 — push is best-effort, never block the action
        pass
    try:
        signals.send_push(title, body=body, click_url=url)
    except Exception:  # noqa: BLE001
        pass


def _campaign_label(project) -> str:
    """A short campaign label for the operator push (client / need)."""
    try:
        return (project["need"] or project["client"] or "Campaign").strip()
    except Exception:  # noqa: BLE001
        return "Campaign"


def _review_redirect(project_id: int, k: str, *, name: str = "", email: str = "",
                     r: str = "", flag: str = ""):
    """Bounce back to the portal after an action. A verified reviewer link (``r``)
    is preserved so the reviewer stays verified; otherwise the share token (``k``).

    ``flag`` (e.g. ``incomplete``) surfaces a portal notice — used by the
    delivery-completeness gate to explain why an approve did NOT deliver."""
    extra = f"&gate={flag}" if (flag or "").strip() else ""
    if (r or "").strip():
        url = f"/project/{project_id}/delivery-portal?r={r}{extra}#review"
    else:
        url = f"/project/{project_id}/delivery-portal?k={k}{extra}#review"
    resp = RedirectResponse(url, status_code=303)
    # Only remember a *guest's* self-typed identity in the cookie — a verified
    # reviewer's identity lives on the roster, not the device.
    if not (r or "").strip():
        _set_reviewer_cookie(resp, name, email)
    return resp


@app.post("/project/{project_id}/review/comment")
def review_comment(
    request: Request, project_id: int, k: str = Form(""), author: str = Form(""),
    email: str = Form(""), t: str = Form(""), body: str = Form(""),
    parent_id: str = Form(""), r: str = Form(""),
):
    """A timecoded comment pinned to the version under review (Frame.io-style).

    Accepts either a share token (``k``, guest) or a verified reviewer token
    (``r``). When verified, the comment is attributed to the roster identity and
    marked verified (not free-typed).

    ``parent_id`` (IP2) makes this a reply threaded one level under that comment —
    a reply answers its parent so it carries no timecode of its own."""
    conn = db.connect()
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        if reviewer is not None:
            name, mail = (reviewer.get("name") or ""), (reviewer.get("email") or "")
        else:
            name, mail = _reviewer_identity(request, author, email)
        # Identity is required so events attribute to a real person, not free text.
        if body.strip() and name and mail:
            # A reply nests under its parent (no timecode); a top-level note carries
            # the live playhead's timecode.
            parent = None
            if str(parent_id).strip():
                p = db.get_review_comment(conn, int(parent_id)) \
                    if str(parent_id).strip().isdigit() else None
                if p is not None and p["project_id"] == project_id:
                    parent = int(parent_id)
            if parent is not None:
                t_seconds = None
            else:
                try:
                    t_seconds = float(t) if str(t).strip() != "" else None
                except ValueError:
                    t_seconds = None
            project = db.get_project(conn, project_id)
            delivery = db.get_delivery(conn, project_id)
            db.add_review_comment(
                conn, project_id, version=_current_version_tag(delivery),
                t_seconds=t_seconds, author=name, email=mail, body=body.strip(),
                kind="comment", parent_id=parent, verified=reviewer is not None,
            )
            verb = "replied" if parent is not None else "commented"
            _notify_operator_review(
                project_id, project,
                title=f"{_campaign_label(project)} — new note",
                body=f"{name} {verb}: {body.strip()[:120]}",
            )
    finally:
        conn.close()
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


@app.post("/project/{project_id}/review/resolve")
def review_resolve(
    request: Request, project_id: int, k: str = Form(""),
    author: str = Form(""), email: str = Form(""), comment_id: str = Form(""),
    r: str = Form(""),
):
    """Toggle a comment's resolved flag (IP2 — Frame.io's resolve checkbox).

    Token-gated like the other review actions (share token ``k`` guest OR verified
    reviewer ``r``), and (like approve/changes) requires a complete reviewer
    identity so a resolve is attributable, not anonymous."""
    conn = db.connect()
    name, mail = "", ""
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        if reviewer is not None:
            name, mail = (reviewer.get("name") or ""), (reviewer.get("email") or "")
        else:
            name, mail = _reviewer_identity(request, author, email)
        if name and mail and str(comment_id).strip().isdigit():
            db.toggle_comment_resolved(conn, project_id, int(comment_id))
    finally:
        conn.close()
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


def _build_delivery_package(conn, project_id: int) -> Optional[dict]:
    """Delivery automation (Phase 3): assemble the delivery ZIP for a project and
    store its descriptor + checklist on ``delivery_json``. Returns the descriptor
    (or None if the project is gone). Deterministic + best-effort: the stdlib ZIP +
    docs always build; audio conversion is attempted only if ffmpeg is available.

    Stored shape::

        delivery_json['delivery_zip']       = {filename, url, built_at}
        delivery_json['delivery_checklist'] = [item, …]   (founder's payoff list)
    """
    row = db.get_project(conn, project_id)
    if row is None:
        return None
    assignments = db.list_assignments(conn, project_id)
    delivery = db.get_delivery(conn, project_id)
    pkg = build_delivery_zip(row, assignments, delivery, UPLOAD_DIR)
    db.update_delivery(conn, project_id, "delivery_zip", {
        "filename": pkg["filename"], "url": pkg["url"], "built_at": pkg["built_at"],
        # Honest partial labelling: the portal card + ZIP descriptor read "Partial
        # delivery — N of M deliverables" (not "everything") when incomplete.
        "partial": pkg.get("partial", False),
        "descriptor": pkg.get("descriptor", ""),
        "completeness": pkg.get("completeness", {}),
    })
    db.update_delivery(conn, project_id, "delivery_checklist", pkg["checklist"])
    return pkg


@app.post("/project/{project_id}/review/approve")
def review_approve(
    request: Request, project_id: int, k: str = Form(""),
    author: str = Form(""), email: str = Form(""), r: str = Form(""),
    deliver_partial: str = Form(""),
):
    """The agency approves the current version — the trigger for Delivery
    Automation (Phase 3). Records the sign-off, locks the FINAL version, then
    **assembles the delivery package** (organise → document → convert → ZIP) and
    flips state to Delivered with the founder's payoff checklist + ZIP url stored.

    Verified-identity gate: Approve — the single most consequential action (it locks
    FINAL + auto-builds the delivery ZIP) — requires a **verified reviewer link**
    (``?r=<reviewer_token>``). The generic share link (``?k=``) can view + comment as
    a guest but CANNOT approve, and a posted free-typed name + email is ignored — the
    sign-off is recorded with the reviewer's LOCKED roster name + email. Approve is no
    longer pressable by anyone with the share token, signed as any typed name.
    """
    conn = db.connect()
    name, mail = "", ""
    try:
        # Access still resolves on either token (so a stale ?k= form 404s vs no-ops
        # consistently with the other actions); the *approve gate* is stricter below.
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        # The verified-identity gate: approve REQUIRES a valid verified reviewer
        # token. A share-link guest (no/invalid ?r=) is refused — no-op, no state
        # change — even if a name + email are posted.
        if reviewer is None:
            return _review_redirect(project_id, k, r=r)
        # The sign-off is recorded with the VERIFIED roster identity, not free text.
        name = (reviewer.get("name") or "").strip()
        mail = (reviewer.get("email") or "").strip()
        if not name:
            return _review_redirect(project_id, k, r=r)
        delivery = db.get_delivery(conn, project_id)
        project = db.get_project(conn, project_id)
        # Delivery-completeness gate: do NOT silently ship an incomplete package as
        # "everything". If scoped deliverables (cutdowns/stems/verticals) were never
        # uploaded, refuse to deliver UNLESS the client explicitly opted into a
        # PARTIAL delivery (deliver_partial=1 — set by the Approve form's confirm()).
        # Without the opt-in this is a no-op: nothing is locked, no approval logged,
        # state unchanged — we bounce back with a flag so the portal explains why.
        completeness = delivery_completeness(project, delivery)
        if not completeness["complete"] and str(deliver_partial).strip() not in ("1", "true", "on", "yes"):
            return _review_redirect(project_id, k, r=r, flag="incomplete")
        approved_n = _current_version_tag(delivery)
        db.add_review_comment(
            conn, project_id, version=approved_n,
            author=name, email=mail,
            body=f"Approved v{approved_n} for delivery.",
            kind="approval", verified=True,
        )
        # Approve locks the FINAL version: stamp the current version's label and
        # the version_state to FINAL so the agency sees the version is final.
        versions = versions_list(delivery)
        if versions:
            versions[-1] = dict(versions[-1])
            versions[-1]["label"] = version_label(versions[-1]["n"], final=True)
            db.update_delivery(conn, project_id, "versions", versions)
            db.update_delivery(conn, project_id, "version_state", versions[-1]["label"])
        # Auto-assemble the delivery package the instant APPROVE is pressed — the
        # payoff moment. Never let a packaging hiccup block recording the approval.
        try:
            _build_delivery_package(conn, project_id)
            db.update_delivery(conn, project_id, "state", "Delivered")
        except Exception:
            db.update_delivery(conn, project_id, "state", "Approved")
        _notify_operator_review(
            project_id, project,
            title=f"{_campaign_label(project)} — approved by {name}",
            body=f"v{approved_n} approved — delivery package building.",
        )
    finally:
        conn.close()
    # Tell the assigned creator(s) their work was approved, off the request thread.
    campaign = _campaign_label(project)
    signals.fire_and_forget(
        _notify_assigned_creators, project_id, project,
        subject=f"Approved — {campaign}",
        body_text=(f"Good news — the client approved your work on {campaign}. "
                   "Thank you. We'll follow up on delivery and anything else needed."))
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


@app.post("/project/{project_id}/delivery/build")
def delivery_build(project_id: int):
    """Admin: (re)build the delivery package by hand — same automation as APPROVE
    triggers, for when assets/versions changed after delivery (idempotent rebuild)."""
    conn = db.connect()
    try:
        pkg = _build_delivery_package(conn, project_id)
        if pkg is None:
            return HTMLResponse("Project not found", status_code=404)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#delivery", status_code=303)


@app.post("/project/{project_id}/delivery/publish")
def delivery_publish(project_id: int, action: str = Form("publish")):
    """Jon's disposition of a creator's pending submission: publish it to the client
    (moves it into the version ladder and notifies the reviewers) or discard it. The
    gate that keeps unvetted creator work off the client's portal."""
    conn = db.connect()
    result = None
    reviewers = []
    try:
        project = db.get_project(conn, project_id)
        if project is None:
            return HTMLResponse("Project not found", status_code=404)
        delivery = db.get_delivery(conn, project_id)
        if not delivery.get("pending_version"):
            return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)
        if action == "discard":
            db.update_delivery(conn, project_id, "pending_version", "")
            db.add_update(conn, project_id, "Discarded the pending creator submission.")
        else:
            result = _publish_pending_submission(conn, project_id)
            if result is not None:
                db.add_update(conn, project_id, f"Published {result[0]} to the client.")
                reviewers = db.list_delivery_reviewers(conn, project_id)
    finally:
        conn.close()
    # Client-direction notification only on a real publish — off the request thread.
    if result is not None:
        label, campaign = result
        signals.fire_and_forget(
            _notify_reviewers_new_version, project_id, campaign, label, reviewers)
    return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)


@app.post("/project/{project_id}/review/changes")
def review_changes(
    request: Request, project_id: int, k: str = Form(""),
    author: str = Form(""), email: str = Form(""), note: str = Form(""),
    r: str = Form(""),
):
    """The agency requests changes — logs the request and bumps the revision count.
    Accepts a share token (``k``, guest) or a verified reviewer token (``r``);
    requires a complete identity (name + email) so the request is attributable."""
    conn = db.connect()
    name, mail = "", ""
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        if reviewer is not None:
            name, mail = (reviewer.get("name") or ""), (reviewer.get("email") or "")
        else:
            name, mail = _reviewer_identity(request, author, email)
        if not (name and mail):
            return _review_redirect(project_id, k, name=name, email=mail, r=r)
        delivery = db.get_delivery(conn, project_id)
        project = db.get_project(conn, project_id)
        note_text = note.strip() or "Requested changes."
        db.add_review_comment(
            conn, project_id, version=_current_version_tag(delivery),
            author=name, email=mail, body=note_text, kind="change_request",
            verified=reviewer is not None,
        )
        db.update_delivery(conn, project_id, "revisions_used",
                           int(delivery.get("revisions_used") or 0) + 1)
        db.update_delivery(conn, project_id, "state", "In production")
        _notify_operator_review(
            project_id, project,
            title=f"{_campaign_label(project)} — changes requested by {name}",
            body=note_text[:160],
        )
    finally:
        conn.close()
    # Tell the assigned creator(s) directly, off the request thread — the composer
    # portal now shows the notes, and this is the nudge to go look.
    campaign = _campaign_label(project)
    signals.fire_and_forget(
        _notify_assigned_creators, project_id, project,
        subject=f"Changes requested — {campaign}",
        body_text=(f"The client requested changes on {campaign}:\n\n\"{note_text}\"\n\n"
                   "Open your creator portal to see the full timecoded feedback and "
                   "submit your next version."))
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


@app.post("/project/{project_id}/review/asset")
def review_asset(
    request: Request, project_id: int, k: str = Form(""),
    filename: str = Form(""), action: str = Form(""), note: str = Form(""),
    r: str = Form(""),
):
    """Per-asset approval: a VERIFIED reviewer signs off (or requests changes on) a
    single deliverable — the :60 master Approved while the :30 cutdown still awaits.

    Gated exactly like the version-level Approve: a valid verified reviewer link
    (``?r=``) is required. A share-link guest (``?k=`` only) sees per-asset status
    read-only — this route no-ops for them, so they cannot change a per-asset state.

    ``filename`` is the asset's stable key (its filename, or ``label:<slug>`` for a
    referenced-only asset). ``action`` is ``approve`` or ``changes``. The status is
    recorded with the roster identity + current version + date, logged into the
    review tape (kind ``asset_approval`` / ``asset_change``, body naming the asset),
    and the operator push fires."""
    conn = db.connect()
    name, mail = "", ""
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        # Per-asset sign-off is gated like the whole-version Approve: a verified
        # reviewer is required. A guest (?k= only) is a no-op — no state change.
        if reviewer is None:
            return _review_redirect(project_id, k, r=r)
        name = (reviewer.get("name") or "").strip()
        mail = (reviewer.get("email") or "").strip()
        key = (filename or "").strip()
        if not name or not key:
            return _review_redirect(project_id, k, r=r)
        delivery = db.get_delivery(conn, project_id)
        # Resolve the asset's display label for the tape (fall back to the key).
        label = key
        for a in (delivery.get("assets") or []):
            if db.asset_key(a) == key:
                label = (a.get("label") or a.get("filename") or key)
                break
        version = _current_version_tag(delivery)
        if action == "changes":
            status, kind = "Changes requested", "asset_change"
            note_text = note.strip() or "Requested changes."
            body = f"Changes requested on {label}: {note_text}"
        else:
            status, kind = "Approved", "asset_approval"
            body = f"Approved {label}."
        rec = db.set_asset_approval(
            conn, project_id, key, status=status, by=name, email=mail,
            version=version,
        )
        if rec is not None:
            project = db.get_project(conn, project_id)
            db.add_review_comment(
                conn, project_id, version=version, author=name, email=mail,
                body=body, kind=kind, verified=True,
            )
            verb = "requested changes on" if action == "changes" else "approved"
            _notify_operator_review(
                project_id, project,
                title=f"{_campaign_label(project)} — {label} {status.lower()}",
                body=f"{name} {verb} {label}.",
            )
    finally:
        conn.close()
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


# --------------------------------------------------------------------------- #
# Proposals — deterministic paperwork generated from the estimator
# --------------------------------------------------------------------------- #
def _proposal_from_row(row) -> Proposal:
    """Reconstruct a Proposal object from a stored row (for render/export)."""
    items = json.loads(row["line_items"]) if row["line_items"] else []
    lines = []
    for i in items:
        line = RoleLine(i["role"], i["hours"], i["rate"], unit=i.get("unit", "hourly"))
        # Preserve a day/flat line cost that isn't simply hours × rate (e.g. an
        # assigned talent's day or per-project rate) so the stored doc renders as
        # generated.
        stored_cost = i.get("cost")
        if stored_cost is not None and abs(stored_cost - line.hours * line.rate) > 1e-9:
            line.cost_override = stored_cost
        lines.append(line)
    return Proposal(
        client="", need="", discipline="", lines=lines,
        total_price=row["total_price"], deposit_pct=row["deposit_pct"],
        deposit_amount=row["deposit_amount"], balance_due=row["balance_due"],
        terms=json.loads(row["terms"]) if row["terms"] else [],
    )


@app.post("/project/{project_id}/proposal")
def project_generate_proposal(project_id: int):
    """Generate a deterministic proposal for a project from the estimator."""
    conn = db.connect()
    try:
        prow = db.get_project(conn, project_id)
        if prow is None:
            return HTMLResponse("Project not found", status_code=404)
        opp_id = prow["opp_id"]
        if opp_id is None:
            return RedirectResponse(f"/project/{project_id}", status_code=303)
        row, opp, ev = _load(conn, opp_id)
        qual, scored = ev
        discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
        # An assigned talent's own rate overrides the global role default for
        # that line, so the client-facing proposal reflects real assigned cost.
        rate_overrides = db.assigned_rate_overrides(conn, project_id)
        est = build_estimate(
            opp, qual.team_shape or discipline.team_shape, discipline, rate_overrides
        )
        proposal = build_proposal(opp, qual, est)
        db.insert_proposal(conn, project_id, opp_id, proposal)
        db.add_update(conn, project_id, "Proposal generated.", "proposal")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/proposal", status_code=303)


@app.get("/project/{project_id}/proposal", response_class=HTMLResponse)
def project_proposal_view(request: Request, project_id: int):
    conn = db.connect()
    try:
        prow = db.get_project(conn, project_id)
        if prow is None:
            return HTMLResponse("Project not found", status_code=404)
        proposal = db.proposal_for_project(conn, project_id)
        line_items = json.loads(proposal["line_items"]) if proposal and proposal["line_items"] else []
        terms = json.loads(proposal["terms"]) if proposal and proposal["terms"] else []
        invoices = db.list_invoices(conn, project_id)
    finally:
        conn.close()
    return render(
        request, "proposal_detail.html", nav="projects", project=prow,
        proposal=proposal, line_items=line_items, terms=terms, invoices=invoices,
        proposal_states=db.PROPOSAL_STATES, invoice_states=db.INVOICE_STATES,
    )


@app.get("/project/{project_id}/proposal.txt", response_class=PlainTextResponse)
def project_proposal_text(project_id: int):
    conn = db.connect()
    try:
        prow = db.get_project(conn, project_id)
        proposal = db.proposal_for_project(conn, project_id) if prow else None
    finally:
        conn.close()
    if proposal is None:
        return PlainTextResponse("No proposal yet", status_code=404)
    obj = _proposal_from_row(proposal)
    obj.client = prow["client"]
    obj.need = prow["need"]
    return PlainTextResponse(obj.render_text())


@app.post("/proposal/{proposal_id}/price")
def proposal_set_price(
    proposal_id: int, total_price: str = Form(...), deposit_pct: str = Form("50"),
):
    """Override a proposal's price with a custom, hand-agreed number — for deals
    quoted per-contract rather than off the estimator (e.g. a flat productized
    offer). Deposit/balance recompute from the new total; the existing invoice +
    Stripe-checkout + payment-gate + revenue-dashboard pipeline is unchanged."""
    conn = db.connect()
    try:
        p = db.get_proposal(conn, proposal_id)
        if p is None:
            return RedirectResponse("/projects", status_code=303)
        total = _parse_rate(total_price)
        if total is not None:
            pct = _parse_rate(deposit_pct) or 50.0
            pct = max(0.0, min(100.0, pct)) / 100.0
            db.update_proposal_price(conn, proposal_id, total, pct)
            if p["project_id"]:
                db.add_update(conn, p["project_id"],
                              f"Proposal price set to {total:,.0f} (custom).", "proposal")
    finally:
        conn.close()
    if p is not None and p["project_id"]:
        return RedirectResponse(f"/project/{p['project_id']}/proposal", status_code=303)
    return RedirectResponse("/projects", status_code=303)


@app.post("/proposal/{proposal_id}/status")
def proposal_set_status(proposal_id: int, status: str = Form(...)):
    conn = db.connect()
    try:
        db.update_proposal_status(conn, proposal_id, status)
        p = db.get_proposal(conn, proposal_id)
        if p is not None and p["project_id"]:
            db.add_update(conn, p["project_id"], f"Proposal {status}.", "proposal")
            return RedirectResponse(
                f"/project/{p['project_id']}/proposal", status_code=303
            )
    finally:
        conn.close()
    return RedirectResponse("/projects", status_code=303)


# --------------------------------------------------------------------------- #
# Invoices — deterministic; reconcile to the proposal
# --------------------------------------------------------------------------- #
def _invoice_from_proposal_row(prow, prop_row, kind: str):
    """Build an Invoice from the stored proposal (client/need from the project)."""
    obj = _proposal_from_row(prop_row)
    obj.client = prow["client"]
    obj.need = prow["need"]
    return build_invoice(obj, kind)


@app.post("/project/{project_id}/invoice")
def project_create_invoice(project_id: int, kind: str = Form(...)):
    """Issue a deposit or final invoice from the project's proposal."""
    conn = db.connect()
    try:
        prow = db.get_project(conn, project_id)
        prop = db.proposal_for_project(conn, project_id)
        if prow is None or prop is None:
            return RedirectResponse(f"/project/{project_id}/proposal", status_code=303)
        if not db.has_invoice(conn, project_id, kind):
            inv = _invoice_from_proposal_row(prow, prop, kind)
            db.insert_invoice(conn, project_id, prop["id"], inv)
            db.add_update(conn, project_id, f"{kind} invoice created.", "invoice")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/proposal", status_code=303)


@app.post("/invoice/{invoice_id}/checkout")
def invoice_checkout(invoice_id: int):
    """Create a checkout for an invoice through the selected payment provider.

    Today the Null provider returns a deterministic reference and the invoice is
    marked Issued; later, selecting the Stripe provider makes this create a real
    checkout — this route and the engines do not change.
    """
    conn = db.connect()
    try:
        inv = db.get_invoice(conn, invoice_id)
        if inv is None:
            return RedirectResponse("/projects", status_code=303)
        ref = get_payment_provider().create_checkout(inv)
        db.update_invoice_status(conn, invoice_id, "Issued", external_ref=ref)
        if inv["project_id"]:
            db.add_update(
                conn, inv["project_id"],
                f"{inv['kind']} invoice issued for payment.", "invoice",
            )
            return RedirectResponse(
                f"/project/{inv['project_id']}/proposal", status_code=303
            )
    finally:
        conn.close()
    return RedirectResponse("/projects", status_code=303)


@app.post("/invoice/{invoice_id}/status")
def invoice_set_status(invoice_id: int, status: str = Form(...)):
    conn = db.connect()
    try:
        inv = db.get_invoice(conn, invoice_id)
        if inv is None:
            return RedirectResponse("/projects", status_code=303)
        db.update_invoice_status(conn, invoice_id, status)
        if inv["project_id"]:
            db.add_update(
                conn, inv["project_id"],
                f"{inv['kind']} invoice {status.lower()}.", "invoice",
            )
            # Client payment in → generate the crew payout ledger (Owed). Idempotent.
            if status == "Paid":
                n = db.ensure_project_payouts(conn, inv["project_id"])
                if n:
                    db.add_update(conn, inv["project_id"],
                                  f"{n} crew payout(s) queued (Owed).", "invoice")
            return RedirectResponse(
                f"/project/{inv['project_id']}/proposal", status_code=303
            )
    finally:
        conn.close()
    return RedirectResponse("/projects", status_code=303)


# --------------------------------------------------------------------------- #
# Revenue dashboard — the CRO's home screen. Cash collected is the number that
# matters; pipeline + funnel + A/R are the leading indicators. Read-only, built
# from existing data (invoices, proposals, projects, opportunities).
# --------------------------------------------------------------------------- #
@app.get("/revenue", response_class=HTMLResponse)
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
@app.get("/payouts", response_class=HTMLResponse)
def payouts_ledger(request: Request, err: str = "", paid: str = ""):
    conn = db.connect()
    try:
        owed = db.list_payouts(conn, status="Owed")
        done = db.list_payouts(conn, status="Paid")
        totals = db.payout_totals(conn)
    finally:
        conn.close()
    return render(
        request, "payouts.html", nav="payouts", owed=owed, done=done,
        totals=totals, err=err, paid_id=paid,
    )


@app.post("/payouts/{payout_id}")
def payout_update(
    payout_id: int,
    qty: str = Form(""),
    amount: str = Form(""),
    reference: str = Form(""),
):
    """Edit an Owed payout's hours/days, amount, and payment reference."""
    conn = db.connect()
    try:
        db.update_payout(conn, payout_id, _parse_rate(qty), _parse_rate(amount),
                         reference.strip())
    finally:
        conn.close()
    return RedirectResponse("/payouts", status_code=303)


@app.post("/payouts/{payout_id}/pay")
def payout_pay(payout_id: int, reference: str = Form("")):
    """Mark a payout Paid — GATED on a W-9 being on file for the creator.

    The ledger never moves money; Jon pays off-platform and records it here. The
    W-9 gate is the compliance discipline the council required before a first payout."""
    conn = db.connect()
    try:
        po = db.get_payout(conn, payout_id)
        if po is None:
            return RedirectResponse("/payouts", status_code=303)
        w9 = po["w9_received_at"] if "w9_received_at" in po.keys() else None
        if not w9:
            # Block: surface which creator needs a W-9 first.
            return RedirectResponse(
                f"/payouts?err=w9&paid={payout_id}", status_code=303)
        db.set_payout_paid(conn, payout_id, True, reference.strip())
    finally:
        conn.close()
    return RedirectResponse("/payouts", status_code=303)


@app.post("/payouts/{payout_id}/unpay")
def payout_unpay(payout_id: int):
    """Revert a payout to Owed (correct a mistaken mark-paid)."""
    conn = db.connect()
    try:
        db.set_payout_paid(conn, payout_id, False)
    finally:
        conn.close()
    return RedirectResponse("/payouts", status_code=303)


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Stripe payment webhook — marks an invoice Paid when its checkout completes.

    Public (no admin cookie): authenticity is the Stripe signature, verified in
    the provider against STRIPE_WEBHOOK_SECRET. Idempotent — a re-delivered event
    for an already-Paid invoice is a no-op. Only acts in Stripe mode.
    """
    provider = get_payment_provider()
    if getattr(provider, "name", "") != "stripe":
        return Response(status_code=200)  # not in Stripe mode — ignore
    body = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = provider.handle_webhook({"body": body, "signature": signature})
    except Exception as e:  # surface the reason in Stripe's delivery log
        return Response(content=f"webhook error: {type(e).__name__}: {e}"[:400],
                        status_code=400)
    invoice_id = event.get("invoice_id")
    if event.get("status") == "Paid" and invoice_id is not None:
        conn = db.connect()
        try:
            inv = db.get_invoice(conn, int(invoice_id))
            if inv is not None and inv["status"] != "Paid":
                db.update_invoice_status(
                    conn, int(invoice_id), "Paid",
                    external_ref=event.get("external_ref"),
                )
                if inv["project_id"]:
                    db.add_update(conn, inv["project_id"],
                                  f"{inv['kind']} invoice paid (Stripe).", "invoice")
                    # Client payment in → generate the crew payout ledger (Owed).
                    n = db.ensure_project_payouts(conn, inv["project_id"])
                    if n:
                        db.add_update(conn, inv["project_id"],
                                      f"{n} crew payout(s) queued (Owed).", "invoice")
        finally:
            conn.close()
    return Response(status_code=200)


def main() -> None:  # console entry point
    import uvicorn

    host = os.environ.get("CHORDENTIAL_HOST", "127.0.0.1")
    port = int(os.environ.get("CHORDENTIAL_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
