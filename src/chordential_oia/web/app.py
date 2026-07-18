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
import math
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
    chips_for, default_toggles, doc_from_json, doc_to_json,
)
from ..delivery import (
    brief_rollup, build_clearance_certificate, build_cue_sheet,
    build_delivery_zip, build_manifest, build_timeline, current_version,
    delivery_completeness,
    license_confirmation, merge_license, merge_signatory, reconcile_brief,
    revision_status, scoped_deliverables, seed_brief, version_label,
    versions_list, version_name,
    ASSIGNABLE_FOLDERS, BRIEF_FIELDS, CONTENT_ID_HONEST, DELIVERY_STATES, VERSION_STATES,
)
from ..strategic import assess_strategic_value
from ..talent import Talent, normalize_url, profile_completeness
from ..matching import match_talent
from . import (
    campaign_intake, campaign_intelligence, campaigns, commercial, db, decision_makers,
    directory_crawl, directory_parsers, discovery,
    enrichment, intake_lanes, intelligence, kickoff, meeting_scheduler, meetings_service,
    music_opportunity, next_action, opportunity_signals, outreach_engine, procurement,
    producer_learning, production, queue as queue_mod, relationships,
    scheduler, seed, signals, simulator, sources, triage, webpush, workspace,
)
from .buyer_intel import assess_relationship, days_since
from .estimate import build_estimate
from .evaluate import evaluate
from .filters import displayurl, money, pct, slug
from .public import router as public_router

_HERE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))


def _static_version() -> str:
    """Cache-buster for /static assets (?v=): the newest mtime in the bundle.
    Static files are browser-cached for 7 days (see the Cache-Control
    middleware), so without this a deploy that ships new CSS/JS looks like
    "the site didn't change" until the cache expires. Render clones fresh on
    every build, so mtimes — and therefore this stamp — change per deploy."""
    latest = 0.0
    for dirpath, _dirs, files in os.walk(os.path.join(_HERE, "static")):
        for fname in files:
            try:
                latest = max(latest, os.path.getmtime(os.path.join(dirpath, fname)))
            except OSError:
                pass
    return str(int(latest))


templates.env.globals["static_v"] = _static_version()
templates.env.filters["fromjson"] = json.loads
# The sitewide machine beacon (base.html) breathes only when the autonomous
# engines are actually on — honest liveness. Callable so env changes apply live.
templates.env.globals["machine_on"] = scheduler.autonomous_engines_on

# Founder-uploaded audio samples for the "Relevant work" section. Path is
# overridable (CHORDENTIAL_UPLOAD_DIR) with a module-relative default; created on
# import so the upload + serve routes can rely on it existing.
# NOTE (honest persistence caveat): files saved to this local disk are NOT durable
# on Render once the persistent disk is removed for the zero-downtime (blue-green)
# cutover — durable storage needs object storage (S3/R2). Acceptable for now.
UPLOAD_DIR = os.environ.get("CHORDENTIAL_UPLOAD_DIR") or os.path.join(_HERE, "uploads")

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
# Campaign Workspace (Creative OS) is a flagged module — templates gate the entry
# points on this so the feature is invisible until CHORDENTIAL_CAMPAIGN_WORKSPACE is on.
templates.env.globals["campaign_workspace_enabled"] = campaigns.workspace_enabled
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
# The Campaign Brief is the client-facing deliverable; when opened with a valid share
# token (?k=<token>) it is a public client link (the route validates the token, 404s on a
# bad one). Without ?k it stays the admin edit view behind the login gate — so the token,
# not the path alone, is what opens it publicly (no admin-view leak).
_CAPABILITIES_RE = re.compile(r"^/opportunity/\d+/capabilities/?$")


def _is_first_touch_path(path: str) -> bool:
    return bool(_FIRST_TOUCH_RE.match(path))


def _is_tokened_brief(request: Request) -> bool:
    return bool(_CAPABILITIES_RE.match(request.url.path)
                and (request.query_params.get("k") or "").strip())


# The client-facing Discovery Request form and the client manage (reschedule/cancel) page are
# token-gated public surfaces (the route validates the token), like first-touch (ADR-0016).
_REQUEST_RE = re.compile(r"^/opportunity/\d+/request/?$")
_MANAGE_RE = re.compile(r"^/meeting/\d+/manage/?$")
# The client slot-pick page: /meet/<proposal-token>[/pick] — the unguessable proposal
# token IS the access control (validated in-route), so it bypasses the admin gate.
_MEET_RE = re.compile(r"^/meet/[A-Za-z0-9_-]+(/pick)?/?$")
# The Client Workspace (ADR-0018): /workspace/<token> — the durable client destination.
# The unguessable workspace token IS the access control (validated in-route), so the path
# bypasses the admin login gate, same exemption as first-touch and the delivery portal.
_WORKSPACE_RE = re.compile(
    r"^/workspace/[A-Za-z0-9_-]+(/approve|/confirm-scope|/approve-version|/court\.json)?/?$")


def _is_public_scheduling(path: str) -> bool:
    return bool(_REQUEST_RE.match(path) or _MANAGE_RE.match(path) or _MEET_RE.match(path)
                or _WORKSPACE_RE.match(path))


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
_REVIEW_ACTIONS = ("comment", "approve", "changes", "resolve", "asset", "reopen")
_REVIEW_ACTION_RE = re.compile(
    r"^/project/\d+/review/(?:" + "|".join(_REVIEW_ACTIONS) + r")/?$")
# Payment-gated deliverable download — opened from the token-gated portal; the route
# itself validates the share/reviewer token AND the paid-in-full gate.
_DELIVERY_DL_RE = re.compile(r"^/project/\d+/dl/[^/]+/?$")
# The composer portal — a qualified creator's token-gated home (view assignments,
# submit work versions). The per-creator portal token IS the access control, so it
# bypasses the admin login gate (same exemption as the client delivery portal).
_CREATOR_PORTAL_RE = re.compile(r"^/creator/[A-Za-z0-9_-]+(/project/\d+/(version|deliverable))?/?$")
# Session Room (Living OS P5): the live-room poll + presence ping are hit from the
# token-gated client portal too — each route token-validates in-route (a bad token
# gets the operator-only view refused / 404), so the paths bypass the login gate.
_SESSION_ROOM_RE = re.compile(r"^/project/\d+/(session\.json|presence)/?$")
# Client-facing payment — the buyer starts checkout from their token-gated workspace/
# portal; the route validates the share token in-route. The Stripe success-return is a
# public redirect target. Both bypass the admin login gate.
_CLIENT_PAY_RE = re.compile(r"^/project/\d+/pay/?$")


def _is_delivery_portal_path(path: str) -> bool:
    return bool(
        _DELIVERY_PORTAL_RE.match(path)
        or _REVIEW_ACTION_RE.match(path)
        or _DELIVERY_DL_RE.match(path)
        or _CREATOR_PORTAL_RE.match(path)
        or _SESSION_ROOM_RE.match(path)
        or _CLIENT_PAY_RE.match(path)
        or path == "/pay/return"
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
        # Client Discovery Request form + manage page — token-validated in the route (ADR-0016).
        or _is_public_scheduling(path)
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
        or path.startswith("/webhooks/capture/")  # capture provider (verified by its signature)
    )


@app.middleware("http")
async def _admin_gate(request: Request, call_next):
    if (_admin_secret() and not _is_public_path(request.url.path)
            and not _is_tokened_brief(request) and not _admin_authed(request)):
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


@app.post("/agencies/{agency_id}/outreach/send")
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
        # Batched: one outreach aggregate + one relationships fetch + one commit for
        # the whole page, instead of a query-per-row + a commit-per-changed-row.
        pipeline = relationships.pipeline_stages(conn, rows)
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
        for prow in db.list_projects(conn) if hasattr(db, "list_projects") else []:
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
        waiting_count = (len(followups) + incoming_total + dr_new
                         + len(pending_reviews) + len(operator_moves)
                         + len(new_applicants))
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


@app.post("/opportunity/{opp_id}/delete")
def opportunity_delete(opp_id: int, return_to: str = Form("/inbox")):
    """Permanently delete an opportunity and everything anchored to it — the whole account
    (CI, meetings, procurement, project + delivery, commercial, learning). Built for clearing
    demo accounts. Irreversible; the UI double-confirms before POSTing here."""
    conn = db.connect()
    try:
        summary = db.delete_opportunity(conn, opp_id)
    finally:
        conn.close()
    dest = return_to if (return_to or "").startswith("/") else "/inbox"
    if summary.get("deleted"):
        dest += ("&" if "?" in dest else "?") + "deleted=" + quote(summary.get("client", ""))
    return RedirectResponse(dest, status_code=303)


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
def opportunity_detail(request: Request, opp_id: int, understood: str = "",
                       added: str = "", asked: str = ""):
    conn = db.connect()
    ci = ci_view = None
    intake_sync_lanes = None
    meeting = None
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        buyer_rows = db.buyer_opportunities(conn, row["client"])
        project = db.project_for_opp(conn, opp_id)
        # Campaign Intake lives HERE now (ADR-0013): born on and anchored to the
        # opportunity. Lazily create + seed its CI, then render the provenance view.
        # The intake lanes (ADR-0014) come from the ONE registry — no lane is privileged.
        if campaigns.workspace_enabled():
            ci = campaign_intelligence.ensure_for_opportunity(conn, row)
            ci_view = campaign_intelligence.fields_view(conn, ci["id"])
            intake_sync_lanes = intake_lanes.sync_lanes()
        # Discovery lives in the Campaign Brief now; the opp page shows a meeting only
        # CONTEXTUALLY (the "Upcoming Discovery" panel), never a standing widget.
        meeting = db.meeting_for_opp(conn, opp_id)
        # Pending client Discovery Requests to review + schedule (ADR-0016).
        discovery_requests = db.list_discovery_requests(conn, opp_id, status="new")
        # ADR-0020 §6: the ONE obvious next move for this deal.
        # Keep the pipeline stage honest with reality before we read it (self-heal).
        _reconcile_opp_status(conn, opp_id, project)
        row = db.get_opportunity(conn, opp_id)
        next_act = next_action.compute(conn, db, row, project)
        # Kickoff → Production gate: a project created by client approval sits in Kickoff
        # until the operator confirms Start Production (ADR-0018, Phase 4).
        kickoff_pending = (
            project is not None
            and (project["kickoff_completed_at"] if "kickoff_completed_at" in project.keys()
                 else None) is None
            and db.current_commercial_review(conn, opp_id) is not None
            and db.current_commercial_review(conn, opp_id)["status"] == "approved")
        # The deposit gates Start Production — surfaced so the button reads honestly
        # (offer it only once the deposit has cleared).
        deposit_paid = False
        if project is not None:
            _d = next((i for i in db.list_invoices(conn, project["id"])
                       if (i["kind"] or "") == "Deposit"), None)
            deposit_paid = _d is not None and (_d["status"] or "").lower() in ("paid", "settled")
        # Open Meeting Proposals — times offered, awaiting the client's pick (or unsent drafts).
        open_proposals = [p for p in db.list_meeting_proposals(conn, opp_id)
                          if p["status"] in ("draft", "sent")]
        proposal_slots_et = {
            p["id"]: [meeting_scheduler.fmt_et(s)
                      for s in meeting_scheduler.proposal_slots(p)]
            for p in open_proposals}
    finally:
        conn.close()
    qual, scored = ev
    sv = assess_strategic_value(opp)
    capture_summary = None
    if understood.isdigit():
        capture_summary = {"understood": int(understood),
                           "added": int(added) if added.isdigit() else 0,
                           "asked": int(asked) if asked.isdigit() else 0}
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
        ci=ci, ci_view=ci_view, intake_sync_lanes=intake_sync_lanes,
        meeting=meeting, notetaker_ready=intake_lanes.get_lane("discovery_call").is_available(),
        discovery_requests=discovery_requests, open_proposals=open_proposals,
        proposal_slots_et=proposal_slots_et, capture_summary=capture_summary,
        kickoff_pending=kickoff_pending, deposit_paid=deposit_paid, next_act=next_act,
        ai_spend=_ai_spend_status(),
    )


def _ai_spend_status() -> dict:
    """The AI spend meter for the Analyze panel: whether a click spends API credit, this
    month's estimated spend, the cap, and whether the cap has bitten. Surfaced so cost is
    never a surprise (reported live: a silent per-analyze charge drained the operator)."""
    try:
        from . import extraction_bridge
        conn = db.connect()
        try:
            return extraction_bridge.spend_status(conn)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return {"spent": 0.0, "cap": 0.0, "calls": 0, "over": False, "enabled": False}


# --------------------------------------------------------------------------- #
# Campaign Intake on the Opportunity (ADR-0013) — Update Intelligence + edits.
# --------------------------------------------------------------------------- #
@app.post("/opportunity/{opp_id}/intelligence/analyze")
async def opp_intelligence_analyze(
        opp_id: int, stance: str = Form("objective"), modality: str = Form("notes"),
        lane: str = Form(""), text: str = Form(""),
        file: Optional[UploadFile] = File(None)):
    """Update Intelligence: read ONLY the newly submitted capture, merge it into this
    opportunity's Campaign Intelligence (preserving provenance + the raw-evidence capture,
    never clobbering a human edit — disagreements surface as conflicts), raise follow-up
    questions, and reflect mappable facts back onto the opportunity. The intake LANE
    (ADR-0014) resolves from an explicit key or from stance+modality. Text lanes read
    directly; a binary upload is stored as evidence and marked awaiting transcription."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    text = (text or "").strip()
    the_lane = intake_lanes.resolve_lane(lane_key=lane, stance=stance, modality=modality)
    artifact_ref = upload_name = ""
    if file is not None and (file.filename or "").strip():
        ext = os.path.splitext(file.filename)[1].lower()
        safe = f"intake_{opp_id}_{abs(hash(file.filename)) % 10**8}{ext}"
        try:
            data = await file.read()
            with open(os.path.join(UPLOAD_DIR, safe), "wb") as fh:
                fh.write(data)
            upload_name, artifact_ref = file.filename, safe
            # a text-like upload (transcript/rfp/email exported as .txt) can be read now
            if not text and ext in (".txt", ".md", ".vtt", ".srt"):
                text = data.decode("utf-8", "ignore").strip()
        except (OSError, ValueError):
            pass
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        if not text:
            # No readable text (e.g. a voice memo with no transcription seam configured):
            # store the raw evidence honestly — nothing is extracted or invented.
            ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
            db.insert_capture(
                conn, ci_id=ci_row["id"], opp_id=opp_id, lane=the_lane.key,
                stance=the_lane.stance, modality=the_lane.modality,
                provenance_source=the_lane.provenance_source, artifact_ref=artifact_ref,
                raw_text=(f"[{the_lane.label}: {upload_name or 'no text'} — "
                          f"awaiting transcription]"),
                extraction=[], status="received", created_by="operator")
            return RedirectResponse(
                f"/opportunity/{opp_id}?understood=&added=0&asked=0#intelligence",
                status_code=303)
        summary = campaign_intake.ingest_opportunity(
            conn, row, stance, text, lane_key=the_lane.key, artifact_ref=artifact_ref)
    finally:
        conn.close()
    q = summary["questions"]
    return RedirectResponse(
        f"/opportunity/{opp_id}?understood={summary['understanding_pct']}"
        f"&added={summary['added']}&asked={len(q)}#intelligence", status_code=303)


@app.post("/opportunity/{opp_id}/intelligence/field")
def opp_intelligence_field(opp_id: int, value: str = Form(""), field_id: str = Form(""),
                           facet: str = Form(""), key: str = Form(""),
                           kind: str = Form("fact")):
    """Human edit of a CI field — authoritative (ADR-0013). Edits an existing field by id,
    or fills an empty canonical slot by (facet,key,kind). Then reflects to the opportunity."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    value = (value or "").strip()
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
        if not value:
            pass
        elif str(field_id).strip().isdigit():
            old = db.get_ci_field(conn, int(field_id))
            campaign_intelligence.edit_field(conn, int(field_id), value, actor="operator")
            if old is not None:
                # ADR-0021: the operator edited a proposed value — training data. A
                # consistent enrichment in a facet teaches the extractor to propose richer.
                producer_learning.record_event(
                    conn, ci_id=ci_row["id"], opp_id=opp_id, facet=old["facet"],
                    key=old["key"], kind=old["kind"], action="edited",
                    ai_value=old["value"] or "", final_value=value,
                    confidence_before=old["confidence"], capture_id=old["capture_id"])
        elif facet and key:
            campaign_intelligence.edit_or_create(conn, ci_row["id"], facet, key,
                                                 kind or "fact", value, actor="operator")
            # The operator supplied a field the AI never proposed — the missed-concept signal.
            producer_learning.record_event(
                conn, ci_id=ci_row["id"], opp_id=opp_id, facet=facet, key=key,
                kind=kind or "fact", action="added", ai_value="", final_value=value)
        campaign_intake.sync_ci_to_opportunity(conn, ci_row["id"], opp_id)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#intelligence", status_code=303)


@app.post("/opportunity/{opp_id}/intelligence/answer")
def opp_intelligence_answer(opp_id: int, field_id: str = Form(...), answer: str = Form("")):
    """Answer a follow-up open_question → a confirmed fact; reflect to the opportunity."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    answer = (answer or "").strip()
    conn = db.connect()
    try:
        if answer and str(field_id).strip().isdigit():
            fld = db.get_ci_field(conn, int(field_id))
            if fld is not None:
                campaign_intake.answer_gap(conn, fld, answer, created_by="operator")
                # Answering a follow-up fills a field the AI flagged as unknown — the operator
                # supplying the value is an "added" event on the target field (ADR-0021).
                target_key = (fld["key"] or "")[4:] if (fld["key"] or "").startswith("ask_") \
                    else (fld["key"] or "")
                producer_learning.record_event(
                    conn, ci_id=fld["ci_id"], opp_id=opp_id, facet=fld["facet"],
                    key=target_key, action="added", ai_value="", final_value=answer,
                    capture_id=fld["capture_id"])
                campaign_intake.sync_ci_to_opportunity(conn, fld["ci_id"], opp_id)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#intelligence", status_code=303)


@app.post("/opportunity/{opp_id}/intelligence/dispose")
def opp_intelligence_dispose(opp_id: int, field_id: str = Form(...)):
    """The human disposition gate — confirm / acknowledge / accept / mark-answered."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        if str(field_id).strip().isdigit():
            fld = db.get_ci_field(conn, int(field_id))
            if fld is not None:
                campaign_intelligence.dispose(conn, fld, actor="operator")
                # ADR-0021: confirming a proposal verbatim is the strongest "trust" signal.
                producer_learning.record_event(
                    conn, ci_id=fld["ci_id"], opp_id=opp_id, facet=fld["facet"],
                    key=fld["key"], kind=fld["kind"], action="confirmed",
                    ai_value=fld["value"] or "", final_value=fld["value"] or "",
                    confidence_before=fld["confidence"], capture_id=fld["capture_id"])
                campaign_intake.sync_ci_to_opportunity(conn, fld["ci_id"], opp_id)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#intelligence", status_code=303)


@app.post("/opportunity/{opp_id}/intelligence/conflict")
def opp_intelligence_conflict(opp_id: int, field_id: str = Form(...),
                              decision: str = Form("keep")):
    """Resolve a surfaced conflict: accept the machine's proposed value, or keep your own."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        if str(field_id).strip().isdigit():
            fld = db.get_ci_field(conn, int(field_id))
            if fld is not None:
                accept = (decision == "accept")
                campaign_intelligence.resolve_conflict(
                    conn, int(field_id), accept=accept, actor="operator")
                # ADR-0021: accepting the machine's disputed value = confirmed; keeping your
                # own = the machine value was rejected. Both train the prior.
                producer_learning.record_event(
                    conn, ci_id=fld["ci_id"], opp_id=opp_id, facet=fld["facet"],
                    key=fld["key"], kind=fld["kind"],
                    action=("confirmed" if accept else "rejected"),
                    ai_value=fld["proposed_value"] or "",
                    final_value=(fld["proposed_value"] or "") if accept else (fld["value"] or ""),
                    confidence_before=fld["confidence"], capture_id=fld["capture_id"])
                campaign_intake.sync_ci_to_opportunity(conn, fld["ci_id"], opp_id)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#intelligence", status_code=303)


# --------------------------------------------------------------------------- #
# Procurement Intelligence (ADR-0022) — capture → adapt → generate → onboard → learn.
# ChordOS prepares clients for procurement; it never integrates with their systems.
# --------------------------------------------------------------------------- #
@app.get("/opportunity/{opp_id}/procurement", response_class=HTMLResponse)
def procurement_workspace(request: Request, opp_id: int):
    """The Procurement Workspace: an adaptive checklist assembled from what THIS client
    actually requires (discovered from Campaign Intelligence), the document generation engine,
    readiness, the portal-onboarding action, and the audit timeline."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        # Discover on load (idempotent) + pre-load from this client's history the first time.
        procurement.seed_from_history(conn, opp_id)
        procurement.discover_from_ci(conn, opp_id)
        view = {
            "row": row, "opp_id": opp_id,
            "readiness": procurement.readiness(conn, opp_id),
            "checklist": procurement.checklist(conn, opp_id),
            "portal": procurement.portal_action(conn, opp_id),
            "timeline": procurement.timeline(conn, opp_id),
            "profile": db.get_company_profile(conn),
            "profile_complete": bool((db.get_company_profile(conn) or {}).get("legal_name")),
            "vocab": procurement.VOCAB, "statuses": procurement.STATUSES,
            "status_label": procurement.STATUS_LABEL,
        }
    finally:
        conn.close()
    return render(request, "procurement.html", nav="pipeline", **view)


@app.post("/opportunity/{opp_id}/procurement/add")
def procurement_add(opp_id: int, req_key: str = Form(...)):
    """Add a requirement the machine didn't discover — from the known vocabulary."""
    conn = db.connect()
    try:
        if req_key in procurement.VOCAB:
            procurement.upsert_requirement(conn, opp_id, req_key, source="Operator",
                                           evidence="Added by the operator")
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/procurement", status_code=303)


@app.post("/opportunity/{opp_id}/procurement/{rid}/generate")
def procurement_generate(opp_id: int, rid: int):
    """Generate the artifact from the Company Profile (or a professional placeholder)."""
    conn = db.connect()
    try:
        r = db.get_procurement_requirement_by_id(conn, rid)
        if r is not None and r["opp_id"] == opp_id:
            procurement.generate_document(conn, opp_id, r["req_key"])
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/procurement", status_code=303)


@app.post("/opportunity/{opp_id}/procurement/{rid}/status")
def procurement_status(opp_id: int, rid: int, status: str = Form(...)):
    """Advance a requirement — Mark Complete / uploaded / not-required, tracked in the audit."""
    conn = db.connect()
    try:
        r = db.get_procurement_requirement_by_id(conn, rid)
        if r is not None and r["opp_id"] == opp_id and status in procurement.STATUSES:
            db.update_procurement_requirement(conn, rid, status=status)
            procurement.add_event(conn, opp_id, status,
                                  f"{r['label']} → {procurement.STATUS_LABEL.get(status, status)}")
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/procurement", status_code=303)


@app.post("/opportunity/{opp_id}/procurement/{rid}/upload")
async def procurement_upload(opp_id: int, rid: int, file: UploadFile = File(...)):
    """Upload a client-supplied or externally-signed document against a requirement."""
    conn = db.connect()
    try:
        r = db.get_procurement_requirement_by_id(conn, rid)
        if r is not None and r["opp_id"] == opp_id and (file.filename or "").strip():
            ext = os.path.splitext(file.filename)[1].lower()
            safe = f"procurement_{opp_id}_{r['req_key']}{ext}"
            try:
                data = await file.read()
                os.makedirs(UPLOAD_DIR, exist_ok=True)
                with open(os.path.join(UPLOAD_DIR, safe), "wb") as fh:
                    fh.write(data)
                db.update_procurement_requirement(conn, rid, artifact_ref=f"upload/{safe}",
                                                  status="uploaded")
                procurement.add_event(conn, opp_id, "uploaded", f"Uploaded {r['label']}")
            except OSError:
                pass
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/procurement", status_code=303)


@app.get("/opportunity/{opp_id}/procurement/{rid}/view", response_class=PlainTextResponse)
def procurement_view(opp_id: int, rid: int):
    """View the generated artifact text (a Download, not a page — the PDF is a rendering)."""
    conn = db.connect()
    try:
        r = db.get_procurement_requirement_by_id(conn, rid)
        text = (r["artifact_text"] if r is not None and r["opp_id"] == opp_id else "") or ""
    finally:
        conn.close()
    if not text:
        return PlainTextResponse("Not generated yet.", status_code=404)
    return PlainTextResponse(text)


@app.post("/opportunity/{opp_id}/procurement/complete")
def procurement_complete(opp_id: int):
    """Mark the whole procurement process complete — and LEARN from it for this client."""
    conn = db.connect()
    try:
        procurement.complete_and_learn(conn, opp_id)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/procurement", status_code=303)


@app.get("/settings/company-profile", response_class=HTMLResponse)
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


@app.post("/settings/company-profile")
async def company_profile_save(request: Request):
    form = await request.form()
    data = {f["key"]: (form.get(f["key"], "") or "").strip() for f in _COMPANY_PROFILE_FIELDS}
    conn = db.connect()
    try:
        db.save_company_profile(conn, data)
    finally:
        conn.close()
    return RedirectResponse("/settings/company-profile?saved=1", status_code=303)


@app.get("/opportunity/{opp_id}/evidence", response_class=HTMLResponse)
def opportunity_evidence(request: Request, opp_id: int):
    """The raw evidence behind Campaign Intelligence — every Capture (transcripts, notes, …)
    with its full text next to what the pipeline extracted from it. Raw evidence is permanent
    and reviewable (ADR-0014): this is where you check whether a missing fact is a transcript
    gap (the words weren't captured) or an extraction gap (they were, but not pulled out)."""
    conn = db.connect()
    items = []
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        ci = db.ci_for_opportunity(conn, opp_id)
        for c in (db.list_captures(conn, ci["id"]) if ci else []):
            try:
                meta = json.loads(c["metadata_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                meta = {}
            try:
                extraction = json.loads(c["extraction_json"] or "[]")
            except (json.JSONDecodeError, TypeError):
                extraction = []
            run = meta.get("extraction_run")
            items.append({"c": c, "meta": meta, "extraction": extraction, "run": run,
                          "remedy": _extraction_error_remedy(
                              (run or {}).get("provider_error", ""))})
    finally:
        conn.close()
    from ..extraction import providers as _ext_providers
    return render(request, "evidence.html", nav="inbox", row=row, items=items,
                  engine_enabled=_ext_providers.is_enabled())


def _extraction_error_remedy(err: str) -> str:
    """Map a model-call error to the precise, actionable remedy so the operator isn't sent
    chasing the wrong knob (a billing error is not a model error)."""
    low = (err or "").lower()
    if not low:
        return ""
    if "credit" in low or "billing" in low or "quota" in low or "insufficient" in low:
        return ("The Anthropic API key has no API credit. Note: a Claude Max/Pro plan "
                "(claude.ai) is SEPARATE from API billing and does NOT fund the API — buy "
                "prepaid API credits at console.anthropic.com → Billing (a few dollars is "
                "plenty; each extraction costs cents), and confirm the key belongs to that "
                "same workspace and its spend limit isn't $0. No redeploy — just re-analyze.")
    if "not_found" in low or "not found" in low or "model" in low and "404" in low:
        return ("That model id isn't available to your key — set "
                "CHORDENTIAL_EXTRACTION_MODEL to one it can call, then re-analyze.")
    if "authentication" in low or "401" in low or "api key" in low or "unauthorized" in low:
        return ("The API key was rejected — check ANTHROPIC_API_KEY in the environment, "
                "then re-analyze.")
    if "rate" in low or "429" in low or "overloaded" in low or "529" in low:
        return "The API was rate-limited/overloaded — transient; just re-analyze in a moment."
    return "Re-analyze once the model call above can succeed."


@app.post("/opportunity/{opp_id}/identity")
def opp_identity(opp_id: int, need: str = Form(""), client: str = Form("")):
    """Edit the opportunity's title (need) and/or buyer name (client) — the human-corrected
    values are authoritative and re-evaluate the opportunity (ADR-0013)."""
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        need, client = (need or "").strip(), (client or "").strip()
        db.apply_intelligence_to_opportunity(
            conn, opp_id, need=need or None, client=client or None)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


# --------------------------------------------------------------------------- #
# Discovery scheduling (ADR-0014 §4/§6) — the meeting is tied to the opportunity
# before it begins. Manual today (log the time + link); the Zoom + Recall auto-flow
# lights up behind the same routes when the provider seams are configured.
# --------------------------------------------------------------------------- #


@app.post("/opportunity/{opp_id}/discovery/reschedule")
def discovery_reschedule(opp_id: int, start_at: str = Form(""), tz_offset: str = Form(""),
                         duration_min: int = Form(0)):
    """Reschedule the opportunity's current discovery call to a new time (local → UTC via
    tz_offset) through the shared engine, so the calendar event moves and confirmations resend."""
    conn = db.connect()
    try:
        m = db.meeting_for_opp(conn, opp_id)
        new_start = _to_utc_iso(start_at, tz_offset)
        if m is not None and new_start:
            meeting_scheduler.reschedule(conn, m, new_start, duration_min=duration_min or None)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#discovery", status_code=303)


@app.post("/opportunity/{opp_id}/discovery/{meeting_id}/cancel")
def discovery_cancel(opp_id: int, meeting_id: int):
    """Cancel a scheduled discovery call (drops the calendar event; the record is retained)."""
    conn = db.connect()
    try:
        m = db.get_meeting(conn, meeting_id)
        if m is not None and m["opp_id"] == opp_id:
            meeting_scheduler.cancel(conn, m)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


def _to_utc_iso(local_iso: str, tz_offset_min: str) -> str:
    """Convert a naive LOCAL wall-clock datetime (what the user typed) to a UTC ISO string,
    using the browser's ``getTimezoneOffset()`` minutes (positive when local is behind UTC —
    e.g. US Eastern = 240). No offset → treated as UTC. So the operator never does the math."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    s = (local_iso or "").strip().replace(" ", "T")
    if not s:
        return ""
    try:
        naive = _dt.fromisoformat(s)
    except ValueError:
        return ""
    try:
        off = int(str(tz_offset_min).strip())
    except (ValueError, TypeError):
        off = 0
    return (naive + _td(minutes=off)).replace(tzinfo=_tz.utc).isoformat()


# ── Client Discovery REQUEST (ADR-0016) — the client asks; it schedules nothing. ──────
def _request_token_ok(conn, opp_id: int, k: str):
    row = db.get_opportunity(conn, opp_id)
    token = row["share_token"] if row is not None and "share_token" in row.keys() else None
    if row is None or not token or not k or not hmac.compare_digest(str(k), str(token)):
        return None
    return row


@app.get("/opportunity/{opp_id}/request", response_class=HTMLResponse)
def discovery_request_form(request: Request, opp_id: int, k: str = "", done: str = ""):
    """The client-facing Request-a-Discovery-Call form (token-gated, from the Brief)."""
    conn = db.connect()
    try:
        row = _request_token_ok(conn, opp_id, k)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
    finally:
        conn.close()
    return render(request, "discovery_request.html", nav="", row=row, k=k,
                  done=bool(done), prefill_email=(row["contact_email"] or ""),
                  prefill_name=(row["contact_name"] or ""))


@app.post("/opportunity/{opp_id}/request")
def discovery_request_submit(opp_id: int, k: str = Form(""), name: str = Form(""),
                             email: str = Form(""), company: str = Form(""),
                             preferred_type: str = Form("zoom"), message: str = Form("")):
    """Create a Discovery Request attached to the opportunity + notify the operator. Schedules
    nothing (ADR-0016)."""
    conn = db.connect()
    try:
        row = _request_token_ok(conn, opp_id, k)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        rid = db.create_discovery_request(
            conn, opp_id=opp_id, name=name.strip(), email=email.strip(),
            company=company.strip(), preferred_type=preferred_type, message=message.strip())
        meeting_scheduler.notify_new_request(db.get_discovery_request(conn, rid), row)
    finally:
        conn.close()
    # Automated acknowledgment to the client (best-effort, off-thread; no-op until
    # SMTP is configured) — same confirmation every inbound intake sends.
    signals.fire_and_forget(mailer.send_intake_ack, email.strip(), name.strip())
    return RedirectResponse(f"/opportunity/{opp_id}/request?k={k}&done=1", status_code=303)


# ── Operator SCHEDULING (ADR-0016) — one engine, from a request or manually. ──────────
@app.get("/opportunity/{opp_id}/schedule", response_class=HTMLResponse)
def discovery_schedule_form(request: Request, opp_id: int, req: str = ""):
    """The operator's Meeting Scheduler — type (Zoom/Phone) + date + time. Prefills from a
    Discovery Request when ``req`` is given, or blank for a manual (referral/inbound) booking."""
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        dr = db.get_discovery_request(conn, int(req)) if req.strip().isdigit() else None
    finally:
        conn.close()
    from .. import meetings as _M
    return render(request, "discovery_schedule.html", nav="inbox", row=row, dr=dr,
                  integrations=_M.integration_status(),
                  prefill_name=((dr["name"] if dr else "") or row["contact_name"] or ""),
                  prefill_email=((dr["email"] if dr else "") or row["contact_email"] or ""),
                  prefill_type=((dr["preferred_type"] if dr else "") or "zoom"))


@app.post("/opportunity/{opp_id}/schedule")
def discovery_schedule_submit(opp_id: int, meeting_type: str = Form("zoom"),
                              mode: str = Form("propose"),
                              date: str = Form(""), time: str = Form(""),
                              date2: str = Form(""), time2: str = Form(""),
                              date3: str = Form(""), time3: str = Form(""),
                              message: str = Form(""),
                              duration_min: int = Form(30), client_name: str = Form(""),
                              client_email: str = Form(""), join_url: str = Form(""),
                              request_id: str = Form("")):
    """One form, two modes (ADR-0016/0017). ``propose`` (default): up to three Eastern-time
    options become a Meeting Proposal + a reviewable client email — the client's pick books
    through the shared engine. ``direct``: the time is already agreed; book it now. All wall
    clocks here are Eastern (the client's zone); storage is UTC."""
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        rid = int(request_id) if request_id.strip().isdigit() else None
        slots = [meeting_scheduler.et_to_utc_iso(d.strip(), (t.strip() or "09:00"))
                 for d, t in ((date, time), (date2, time2), (date3, time3)) if d.strip()]
        slots = [s for s in slots if s]
        if mode == "direct":
            meeting_scheduler.schedule(
                conn, row, meeting_type=meeting_type, start_at=(slots[0] if slots else ""),
                duration_min=duration_min or 30, client_name=client_name.strip(),
                client_email=client_email.strip(), join_url=join_url.strip(),
                initiated_by=("client_request" if rid else "operator"), request_id=rid)
            return RedirectResponse(f"/opportunity/{opp_id}#discovery", status_code=303)
        res = meeting_scheduler.propose(
            conn, row, slots=slots, meeting_type=meeting_type,
            duration_min=duration_min or 30, client_name=client_name.strip(),
            client_email=client_email.strip(), message=message.strip(),
            join_url=join_url.strip(), request_id=rid)
        if not res.get("ok"):
            return RedirectResponse(f"/opportunity/{opp_id}/schedule?err=slots",
                                    status_code=303)
        pid = res["proposal"]["id"]
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/proposal/{pid}", status_code=303)


@app.get("/opportunity/{opp_id}/proposal/{pid}", response_class=HTMLResponse)
def meeting_proposal_preview(request: Request, opp_id: int, pid: int):
    """The machine proposes, the operator disposes: review the exact client email (options in
    Eastern time) before anything is sent."""
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        prop = db.get_meeting_proposal(conn, pid)
        if row is None or prop is None or prop["opp_id"] != opp_id:
            return HTMLResponse("Not found", status_code=404)
        email = meeting_scheduler.resolved_proposal_email(row, prop)
        slots = [meeting_scheduler.fmt_et(s, long=True)
                 for s in meeting_scheduler.proposal_slots(prop)]
    finally:
        conn.close()
    return render(request, "meeting_proposal.html", nav="inbox", row=row, prop=prop,
                  email=email, slots_et=slots,
                  pick_url=f"{_public_base()}/meet/{prop['token']}")


def _save_proposal_edits(conn, pid: int, subject: Optional[str], body: Optional[str],
                         reset: bool) -> None:
    """Persist the operator's edits to the exact client email (or reset to the generated
    draft). Stored as overrides — blank means "use the generated text"."""
    if reset:
        db.update_meeting_proposal(conn, pid, subject_override="", body_override="")
        return
    # Only persist NON-empty edits: a blank field means "not submitted / leave as-is"
    # (Form defaults to "" so we can't see None), never "wipe the saved draft" — that's
    # what Reset is for. In the real UI the box is always prefilled, so Send always
    # carries the full text and this WYSIWYG guarantee holds.
    fields = {}
    if (subject or "").strip():
        fields["subject_override"] = subject.strip()
    if (body or "").strip():
        fields["body_override"] = body.strip()
    if fields:
        db.update_meeting_proposal(conn, pid, **fields)


@app.post("/opportunity/{opp_id}/proposal/{pid}/edit")
def meeting_proposal_edit(opp_id: int, pid: int, subject: str = Form(""),
                          body: str = Form(""), reset: str = Form("")):
    """Save the operator's edits to the times email without sending (Save draft / Reset)."""
    conn = db.connect()
    try:
        prop = db.get_meeting_proposal(conn, pid)
        if prop is None or prop["opp_id"] != opp_id:
            return HTMLResponse("Not found", status_code=404)
        _save_proposal_edits(conn, pid, subject, body, reset == "1")
    finally:
        conn.close()
    saved = "reset" if reset == "1" else "saved"
    return RedirectResponse(
        f"/opportunity/{opp_id}/proposal/{pid}?{saved}=1", status_code=303)


@app.post("/opportunity/{opp_id}/proposal/{pid}/send")
def meeting_proposal_send(opp_id: int, pid: int, subject: str = Form(""),
                          body: str = Form("")):
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, opp_id)
        prop = db.get_meeting_proposal(conn, pid)
        if row is None or prop is None or prop["opp_id"] != opp_id:
            return HTMLResponse("Not found", status_code=404)
        # Persist whatever is in the review box FIRST, so we send exactly what's shown.
        _save_proposal_edits(conn, pid, subject, body, reset=False)
        prop = db.get_meeting_proposal(conn, pid)
        res = meeting_scheduler.send_proposal(conn, row, prop)
        if not res.get("ok"):
            return RedirectResponse(
                f"/opportunity/{opp_id}/proposal/{pid}?err=send", status_code=303)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#discovery", status_code=303)


@app.post("/opportunity/{opp_id}/proposal/{pid}/cancel")
def meeting_proposal_cancel(opp_id: int, pid: int):
    conn = db.connect()
    try:
        prop = db.get_meeting_proposal(conn, pid)
        if prop is not None and prop["opp_id"] == opp_id and prop["status"] in ("draft", "sent"):
            db.update_meeting_proposal(conn, pid, status="canceled")
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}#discovery", status_code=303)


# ── Client slot pick — public, token-gated by the unguessable proposal token. ─────────
@app.get("/meet/{token}", response_class=HTMLResponse)
def meet_pick_page(request: Request, token: str, pick: str = ""):
    """The client's view of the offered times (Eastern, never UTC). GET never books —
    email scanners prefetch links — it only preselects; the POST confirms."""
    conn = db.connect()
    try:
        prop = db.meeting_proposal_by_token(conn, token)
        if prop is None:
            return HTMLResponse("Not found", status_code=404)
        opp = db.get_opportunity(conn, prop["opp_id"])
        slots = meeting_scheduler.proposal_slots(prop)
        meeting = (db.get_meeting(conn, prop["meeting_id"])
                   if prop["meeting_id"] else None)
    finally:
        conn.close()
    sel = int(pick) if pick.strip().isdigit() and int(pick) < len(slots) else None
    return render(request, "meet.html", nav="", prop=prop, opp=opp, sel=sel,
                  slots_et=[meeting_scheduler.fmt_et(s, long=True) for s in slots],
                  chosen_et=(meeting_scheduler.fmt_et(prop["chosen_slot"], long=True)
                             if prop["chosen_slot"] else ""),
                  meeting=meeting)


@app.post("/meet/{token}/pick")
def meet_pick_submit(token: str, pick: int = Form(...)):
    """The client confirmed an option: first pick wins (transactional lock), the booking runs
    the full engine — Zoom, Recall, calendar invites both sides, confirmations, timeline —
    and the other options expire with the proposal."""
    conn = db.connect()
    try:
        prop = db.meeting_proposal_by_token(conn, token)
        if prop is None:
            return HTMLResponse("Not found", status_code=404)
        meeting_scheduler.book_from_proposal(conn, prop, pick)
    finally:
        conn.close()
    return RedirectResponse(f"/meet/{token}", status_code=303)


# ── The Client Workspace (ADR-0018) — the ONE durable client destination. ─────────────
def _workspace_signals(conn, opp, project):
    """Gather the phase signals for one deal (ADR-0018). Pure DB reads; the mapping to a
    phase lives in ``workspace.compute_phase`` so it stays trivially testable. Signals for
    phases not yet built (commercial/kickoff) are simply absent."""
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    opp_id = opp["id"]
    met = False
    upcoming = False
    for m in db.list_meetings(conn, opp_id):
        if m["status"] == "canceled":
            continue
        if m["status"] in ("ingested", "transcript_ready") or (
                (m["start_at"] or "") and m["start_at"] <= now_iso):
            met = True
        elif (m["start_at"] or "") and m["start_at"] > now_iso:
            upcoming = True
    if any(p["status"] in ("draft", "sent")
           for p in db.list_meeting_proposals(conn, opp_id)):
        upcoming = True
    # Brief-ready means a client-facing brief moment has actually occurred — discovery
    # happened, or the brief was sent. NOT merely "CI has content": CI is auto-seeded
    # from the opportunity's own fields at creation, so that would flip every new deal to
    # the Brief phase before any discovery (ADR-0018 — honest phase signals).
    brief_ready = met or db.latest_brief_snapshot(conn, opp_id) is not None
    delivered = bool(project) and (project["status"] or "").lower() in ("delivered", "complete")
    # Commercial: released (operator opened the offer) → COMMERCIAL; approved → KICKOFF.
    review = db.current_commercial_review(conn, opp_id)
    kickoff_complete = bool(project) and bool(
        project["kickoff_completed_at"] if "kickoff_completed_at" in project.keys() else None)
    # ADR-0020: the client's scope confirmation ("yes, this reflects our project") advances
    # the workspace into the commercial phase — shown as "preparing your proposal" until the
    # operator releases it.
    scope_confirmed = bool(db.get_doc_overrides(conn, opp_id).get("scope_confirmed"))
    return {
        "has_project": project is not None,
        "delivered": delivered,
        "kickoff_complete": kickoff_complete,
        "commercial_approved": bool(review) and review["status"] == "approved",
        "commercial_ready": (bool(review) and review["status"] == "released")
                            or scope_confirmed,
        "brief_ready": brief_ready,
        "in_discovery": upcoming and not brief_ready,
    }


@app.get("/workspace/{token}", response_class=HTMLResponse)
def client_workspace(request: Request, token: str):
    """The Client Workspace: one durable, token-gated URL that never changes; its contents
    are the current lifecycle phase (ADR-0018). The token resolves the opportunity (its
    project inherits the same token), we compute the phase, and render the shell with the
    active stage's continuation. Existing token-gated surfaces (brief, delivery portal) are
    linked from here today; later phases fold them inline under this same URL."""
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            proj = db.project_by_share_token(conn, token)
            opp = db.get_opportunity(conn, proj["opp_id"]) if proj and proj["opp_id"] else None
        if opp is None:
            return HTMLResponse("Not found", status_code=404)
        project = db.project_for_opp(conn, opp["id"])
        # Self-heal: an awarded deal with no stored proposal (approved before the deposit
        # was wired, or via a path that skipped it) gets one now from the approved review,
        # so the deposit reliably surfaces — Pay button + Kickoff readiness.
        if project is not None and db.proposal_for_project(conn, project["id"]) is None:
            _ensure_proposal_from_review(
                conn, opp, project["id"], db.current_commercial_review(conn, opp["id"]))
        phase = workspace.compute_phase(_workspace_signals(conn, opp, project))
        # Deposit status, computed once up front. The deposit is due the moment the client
        # approves the Commercial Review (that's when the project + its Deposit invoice exist),
        # and it GATES Kickoff: production readiness stays locked until the deposit is in
        # (reported live: "as they approve, that should be the time to pay the deposit … the
        # deposit needs to be completed to initiate kickoff").
        _dep_prop = db.proposal_for_project(conn, project["id"]) if project is not None else None
        _dep_inv = (next((i for i in db.list_invoices(conn, project["id"])
                          if (i["kind"] or "") == "Deposit"), None)
                    if project is not None else None)
        deposit_paid = (_dep_inv is not None
                        and (_dep_inv["status"] or "").lower() in ("paid", "settled"))
        # The Campaign Brief folds INLINE into the workspace (ADR-0018) — one URL, no jump.
        # Other phases still link to their existing surface until they're folded in turn
        # (intro/discovery → scheduling; production/delivery → the portal, folded in P5).
        brief_ctx = None
        review = None
        readiness = None
        approved_note = ""
        preparing = False
        scope_confirm_url = ""
        if phase == workspace.BRIEF:
            brief_ctx = _live_brief_ctx(conn, opp["id"])
            # ADR-0020: the Summary's one action — "yes, this reflects our project".
            if not db.get_doc_overrides(conn, opp["id"]).get("scope_confirmed"):
                scope_confirm_url = f"/workspace/{token}/confirm-scope"
        elif phase == workspace.COMMERCIAL:
            # The frozen Commercial Review — the agreement the client approves; before the
            # operator releases it, the phase reads "we're preparing your proposal".
            cr = db.current_commercial_review(conn, opp["id"])
            if cr is not None and cr["status"] in ("released", "approved"):
                review = commercial.review_from_json(cr["doc_json"])
            else:
                preparing = True
        elif phase == workspace.KICKOFF:
            # The Production Readiness Workspace — the concierge handoff. The deposit is the
            # first readiness gate here ("Send your deposit"); production doesn't start until
            # it's in (enforced on the operator's Start Production action).
            cr = db.current_commercial_review(conn, opp["id"])
            ci_view, _met = _brief_ci_context(conn, opp)
            readiness = kickoff.build_readiness(conn, db, opp, project, cr, ci_view=ci_view)
        prod = None
        if phase in (workspace.PRODUCTION, workspace.DELIVERY) and project is not None:
            # ADR-0019: production answers the court question first — whose move is it —
            # then shows the creative journey. The portal stays the listening room.
            delivery_blob = db.get_delivery(conn, project["id"])
            prod = {
                "court": production.court_state(project, delivery_blob),
                "journey": production.creative_journey(delivery_blob),
                "portal_url": f"/project/{project['id']}/delivery-portal?k={token}",
                "approve_url": f"/workspace/{token}/approve-version",
            }
        stage_url = ""
        if (brief_ctx is None and review is None and readiness is None and prod is None
                and not preparing):
            stage_url = {
                workspace.INTRO: f"/opportunity/{opp['id']}/request?k={token}",
                workspace.DISCOVERY: f"/opportunity/{opp['id']}/request?k={token}",
            }.get(phase, "")
            if not stage_url and project is not None:
                stage_url = f"/project/{project['id']}/delivery-portal?k={token}"
        # Client-facing DEPOSIT payment: once there's a project (awarded), surface the
        # deposit due + a Pay button until it's paid. Uses the project share token so the
        # token-gated /pay route authorizes it.
        deposit_pay = None
        if project is not None:
            dep_amount = (_dep_inv["amount"] if _dep_inv is not None
                          else (_dep_prop["deposit_amount"] if _dep_prop is not None else 0)) or 0
            if _dep_prop is not None and dep_amount and not deposit_paid:
                deposit_pay = {"amount": dep_amount, "pid": project["id"],
                               "ptok": db.ensure_project_share_token(conn, project["id"])}
    finally:
        conn.close()
    # The client can approve only a released (not-yet-approved) review.
    approve_url = (f"/workspace/{token}/approve"
                   if review is not None and not approved_note else "")
    return render(request, "workspace.html", nav="", token=token, opp=opp,
                  project=project, phase=phase, phase_label=workspace.PHASE_LABEL[phase],
                  phase_blurb=workspace.PHASE_BLURB[phase], rail=workspace.rail(phase),
                  stage_url=stage_url, review=review, approve_url=approve_url,
                  approved_note=approved_note, k=readiness, prod=prod,
                  preparing=preparing, scope_confirm_url=scope_confirm_url,
                  back_url=f"/opportunity/{opp['id']}/capabilities?k={token}",
                  deposit_pay=deposit_pay,
                  **(brief_ctx or {}))


# ── The Commercial Review (ADR-0018, Phase 1) — the formal agreement, from CI. ────────
def _reconcile_opp_status(conn, opp_id, project=None) -> None:
    """Keep the pipeline stage honest with where the deal actually is (ADR-0020 §6): the
    New → Reaching out → Proposal out → Won buttons follow the lifecycle automatically.
    FORWARD-only — a manual override or a later stage is never rolled back; a closed deal
    (Won/Lost/Passed) is left alone. Called at each transition and as a self-heal on view."""
    row = db.get_opportunity(conn, opp_id)
    if row is None:
        return
    cur = row["status"]
    if cur in ("Won", "Lost", "Passed"):
        return
    order = _KANBAN_STAGES                       # New, Pursuing, Submitted, Won
    review = db.current_commercial_review(conn, opp_id)
    proj = project if project is not None else db.project_for_opp(conn, opp_id)
    approved = bool(review) and review["status"] == "approved"
    if approved or proj is not None:
        implied = "Won"
    elif review is not None and review["status"] == "released":
        implied = "Submitted"                    # "Proposal out"
    else:
        met = any((m["status"] in ("ingested", "transcript_ready"))
                  for m in db.list_meetings(conn, opp_id))
        confirmed = bool(db.get_doc_overrides(conn, opp_id).get("scope_confirmed"))
        snap = db.latest_brief_snapshot(conn, opp_id) if hasattr(db, "latest_brief_snapshot") else None
        implied = "Pursuing" if (met or confirmed or snap) else "New"   # "Reaching out"
    if cur in order and implied in order and order.index(implied) > order.index(cur):
        try:
            db.update_status(conn, opp_id, implied, row["outcome_value"])
        except Exception:  # noqa: BLE001 — status honesty never blocks the request
            pass


def _build_review_for_opp(conn, opp_id, version=1):
    """Project a Commercial Review for an opportunity, live from Campaign Intelligence.
    Operator edits (price/deposit) live in the ``commercial`` doc-override blob and win."""
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None, None
    qual, _scored = ev
    disc = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or disc.team_shape, disc)
    ci_view, met = _brief_ci_context(conn, row)
    overrides = db.get_doc_overrides(conn, opp_id).get("commercial") or {}
    review = commercial.build_commercial_review(opp, qual, est, ci_view, met=met,
                                                version=version, overrides=overrides)
    return row, review


@app.post("/opportunity/{opp_id}/commercial/edit")
def commercial_edit(opp_id: int, fee_low: str = Form(""), fee_high: str = Form(""),
                    deposit_pct: str = Form(""), scope_summary: str = Form(""),
                    timeline: str = Form(""), revision_rounds: str = Form("")):
    """Operator edits the Commercial Review before releasing it — the whole agreement, not
    just the price: scope summary, delivery deadline (timeline), revision rounds, the price
    band and the deposit %. Stored in the ``commercial`` override blob and consumed on every
    render, so what's on the page is exactly what the client approves. An empty field snaps
    that value back to the Campaign-Intelligence-derived default."""
    conn = db.connect()
    try:
        ov = dict(db.get_doc_overrides(conn, opp_id).get("commercial") or {})
        lo, hi = _parse_rate(fee_low), _parse_rate(fee_high)
        if lo and hi:
            ov["fee_low"], ov["fee_high"] = int(min(lo, hi)), int(max(lo, hi))
        elif not fee_low and not fee_high:
            ov.pop("fee_low", None); ov.pop("fee_high", None)
        pct = _parse_rate(deposit_pct)
        if pct is not None:
            ov["deposit_pct"] = max(0.0, min(100.0, pct)) / 100.0
        # Free-text agreement fields: set when provided, cleared (→ CI default) when blank.
        for key, val in (("scope_summary", scope_summary), ("timeline", timeline),
                         ("revision_rounds", revision_rounds)):
            if val.strip():
                ov[key] = val.strip()
            else:
                ov.pop(key, None)
        db.update_doc_override(conn, opp_id, "commercial", ov)
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/commercial", status_code=303)


@app.get("/opportunity/{opp_id}/commercial", response_class=HTMLResponse)
def commercial_preview(request: Request, opp_id: int):
    """Operator preview of the Commercial Review, generated from CI — 'the machine prepares'.
    Review it, then Release to the client ('the human commits')."""
    conn = db.connect()
    try:
        version = db.next_commercial_version(conn, opp_id)
        row, review = _build_review_for_opp(conn, opp_id, version)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        current = db.current_commercial_review(conn, opp_id)
        token = db.ensure_share_token(conn, opp_id)
        rev_ov = (db.get_doc_overrides(conn, opp_id).get("commercial") or {}).get("revision_rounds")
    finally:
        conn.close()
    return render(request, "commercial_preview.html", nav="inbox", row=row, review=review,
                  current=current, token=token, released_badge="Preview",
                  revision_rounds=(rev_ov or ""))


@app.post("/opportunity/{opp_id}/commercial/release")
def commercial_release(opp_id: int):
    """Freeze + release the Commercial Review to the client (opens the Commercial stage in
    their workspace). Once released it's a stable offer; re-release supersedes with a new
    version. Records a CI timeline event."""
    conn = db.connect()
    try:
        version = db.next_commercial_version(conn, opp_id)
        row, review = _build_review_for_opp(conn, opp_id, version)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        db.release_commercial_review(conn, opp_id, review.version,
                                     commercial.review_to_json(review))
        _reconcile_opp_status(conn, opp_id)      # → Proposal out
        # Email is the notification layer (ADR-0020): the proposal is in their workspace.
        token = db.ensure_share_token(conn, opp_id)
        if (row["contact_email"] or "").strip():
            try:
                mailer.send_email(
                    row["contact_email"].strip(),
                    f"Your proposal is ready — {row['client']}",
                    f"Your proposal for {row['need']} is ready in your workspace — scope, "
                    f"timeline, investment and terms, with one approval at the end.\n\n"
                    f"{_public_base()}/workspace/{token}")
            except Exception:  # noqa: BLE001
                pass
        if campaigns.workspace_enabled():
            try:
                ci = campaign_intelligence.ensure_for_opportunity(conn, row)
                db.add_ci_event(conn, ci["id"], actor="operator", verb="commercial_released",
                                facet="commercial", key="review", to_value=f"v{review.version}",
                                source="commercial")
            except Exception:  # noqa: BLE001
                pass
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}/commercial", status_code=303)


@app.post("/opportunity/{opp_id}/start-production")
def start_production(opp_id: int):
    """The operator confirms the Sales→Production handoff is complete (ADR-0018, Phase 4):
    stamps the project's kickoff gate, advancing the workspace from Kickoff into Production.
    'The machine prepared readiness; the human commits to starting.'"""
    from datetime import datetime, timezone
    conn = db.connect()
    try:
        project = db.project_for_opp(conn, opp_id)
        if project is None:
            return HTMLResponse("No project yet", status_code=404)
        # Deposit gates production start (reported live: "the deposit needs to be completed
        # to initiate kickoff"). Until the deposit invoice is paid, we don't stamp the gate —
        # the operator is bounced back with a reason so nothing kicks off unpaid.
        dep = next((i for i in db.list_invoices(conn, project["id"])
                    if (i["kind"] or "") == "Deposit"), None)
        if dep is None or (dep["status"] or "").lower() not in ("paid", "settled"):
            return RedirectResponse(f"/opportunity/{opp_id}?err=deposit_unpaid", status_code=303)
        conn.execute("UPDATE projects SET kickoff_completed_at = ? WHERE id = ?",
                     (datetime.now(timezone.utc).isoformat(), project["id"]))
        conn.commit()
        if campaigns.workspace_enabled():
            try:
                opp = db.get_opportunity(conn, opp_id)
                ci = campaign_intelligence.ensure_for_opportunity(conn, opp)
                db.add_ci_event(conn, ci["id"], actor="operator", verb="production_started",
                                facet="commercial", key="kickoff", source="kickoff")
            except Exception:  # noqa: BLE001
                pass
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


@app.post("/workspace/{token}/confirm-scope")
def workspace_confirm_scope(request: Request, token: str, confirmed_by: str = Form(""),
                            comment: str = Form(""), decision: str = Form("yes")):
    """ADR-0020: the Discovery Summary has two answers — "yes, this reflects our project"
    (alignment, not commitment: advances to "preparing your proposal" and notifies the
    operator to release it) or "no, something's off" (captures the client's corrections,
    notifies the operator, and does NOT advance — the operator edits the summary and
    re-shares). Reported live: the box only offered "Yes"."""
    from datetime import datetime, timezone
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            return HTMLResponse("Not found", status_code=404)
        if decision.strip().lower() == "no":
            # Something's off — record the correction, ping the operator, don't advance.
            note = comment.strip()[:500]
            db.update_doc_override(conn, opp["id"], "scope_correction", {
                "at": datetime.now(timezone.utc).isoformat(),
                "by": confirmed_by.strip(), "comment": note, "resolved": False})
            if campaigns.workspace_enabled():
                try:
                    ci = campaign_intelligence.ensure_for_opportunity(conn, opp)
                    db.add_ci_event(conn, ci["id"], actor="client", verb="scope_correction",
                                    facet="engagement", key="discovery_summary",
                                    to_value=(note[:200] or "flagged for correction"),
                                    source="workspace")
                except Exception:  # noqa: BLE001
                    pass
            op_mail = meeting_scheduler._operator_email()
            if op_mail:
                try:
                    mailer.send_email(
                        op_mail, f"⚠ Client flagged the summary — {opp['client']}",
                        f"{confirmed_by.strip() or 'The client'} says the Discovery Summary "
                        f"for {opp['need']} needs a fix."
                        + (f"\nTheir note: “{note}”" if note else "")
                        + f"\n\nEdit the summary, then re-share:\n"
                          f"{_public_base()}/opportunity/{opp['id']}/capabilities?edit=1")
                except Exception:  # noqa: BLE001
                    pass
            return RedirectResponse(f"/workspace/{token}?flag=corrections", status_code=303)
        if not db.get_doc_overrides(conn, opp["id"]).get("scope_confirmed"):
            db.update_doc_override(conn, opp["id"], "scope_confirmed", {
                "at": datetime.now(timezone.utc).isoformat(),
                "by": confirmed_by.strip(), "comment": comment.strip()[:500]})
            _reconcile_opp_status(conn, opp["id"])   # → Reaching out
            if campaigns.workspace_enabled():
                try:
                    ci = campaign_intelligence.ensure_for_opportunity(conn, opp)
                    db.add_ci_event(conn, ci["id"], actor="client", verb="scope_confirmed",
                                    facet="engagement", key="discovery_summary",
                                    to_value=(comment.strip()[:200] or "confirmed"),
                                    source="workspace")
                except Exception:  # noqa: BLE001
                    pass
            op_mail = meeting_scheduler._operator_email()
            if op_mail:
                try:
                    mailer.send_email(
                        op_mail, f"✓ Scope confirmed — {opp['client']}",
                        f"The client confirmed the Discovery Summary for {opp['need']}."
                        + (f"\nTheir note: \u201c{comment.strip()}\u201d" if comment.strip() else "")
                        + f"\n\nNext: review and release the proposal.\n"
                          f"{_public_base()}/opportunity/{opp['id']}/commercial")
                except Exception:  # noqa: BLE001
                    pass
    finally:
        conn.close()
    return RedirectResponse(f"/workspace/{token}", status_code=303)


@app.get("/workspace/{token}/court.json")
def workspace_court_signature(token: str):
    """A cheap signature of the deal's current state so the client's Workspace can quietly
    refresh itself the moment something changes (a version lands, an approval fires) — no more
    manual reload. Motion communicates state; nothing reloads unless the state actually moved."""
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        project = db.project_for_opp(conn, opp["id"])
        # A cheap signature: award state + delivery state + version count + pending flag +
        # scope-confirm + review status. Any client-visible transition changes it.
        parts = [opp["status"] or "", "proj" if project else "noproj"]
        review = db.current_commercial_review(conn, opp["id"])
        parts.append((review["status"] if review else "") or "")
        parts.append("sc" if db.get_doc_overrides(conn, opp["id"]).get("scope_confirmed") else "")
        if project is not None:
            d = db.get_delivery(conn, project["id"])
            parts += [d.get("state", "") or "", str(len(d.get("versions") or [])),
                      "p" if d.get("pending_version") else ""]
        sig = ":".join(parts)
    finally:
        conn.close()
    return {"sig": sig}


@app.post("/workspace/{token}/approve-version")
def workspace_approve_version(request: Request, token: str, approver_name: str = Form("")):
    """The client approves the current version straight from their Workspace — the "it's
    perfect, no changes" path (operator feedback). The durable workspace token IS the client's
    identity + access; a typed name captures intent (ESIGN/UETA-sufficient). Records the
    sign-off, locks the creative, and drives delivery — the same core the reviewer route uses."""
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            return HTMLResponse("Not found", status_code=404)
        project = db.project_for_opp(conn, opp["id"])
        if project is None:
            return RedirectResponse(f"/workspace/{token}", status_code=303)
        delivery = db.get_delivery(conn, project["id"])
        # Only meaningful when a version is actually waiting on the client.
        if delivery.get("state") == "In review" and production.court_state(project, delivery)["court"] == "client":
            name = (approver_name.strip() or opp["contact_name"] or "The client").strip()
            mail = (opp["contact_email"] or "").strip()
            _approve_version_core(conn, project["id"], name, mail)
    finally:
        conn.close()
    return RedirectResponse(f"/workspace/{token}", status_code=303)


@app.post("/workspace/{token}/approve")
def workspace_approve(request: Request, token: str, approver_name: str = Form(""),
                      approver_email: str = Form(""), scope_ok: str = Form(""),
                      pricing_ok: str = Form(""), terms_ok: str = Form(""),
                      timeline_ok: str = Form("")):
    """The client approves the released Commercial Review — the primary award trigger
    (ADR-0018). Captures the electronic-approval audit record bound to the FROZEN version,
    marks the review approved, and advances the workspace into Kickoff. Phase 3 enriches
    the audit + adds the optional DocuSign path."""
    conn = db.connect()
    try:
        opp = db.opportunity_by_share_token(conn, token)
        if opp is None:
            proj = db.project_by_share_token(conn, token)
            opp = db.get_opportunity(conn, proj["opp_id"]) if proj and proj["opp_id"] else None
        if opp is None:
            return HTMLResponse("Not found", status_code=404)
        review = db.current_commercial_review(conn, opp["id"])
        if review is not None and review["status"] == "released":
            db.create_commercial_approval(
                conn, opp_id=opp["id"], review_id=review["id"],
                approver_name=approver_name.strip(), approver_email=approver_email.strip(),
                ip=(request.client.host if request.client else ""),
                user_agent=request.headers.get("user-agent", ""),
                scope_ok=bool(scope_ok), pricing_ok=bool(pricing_ok), terms_ok=bool(terms_ok),
                timeline_ok=bool(timeline_ok))
            # Email is the notification layer (ADR-0020): tell the operator the award landed.
            op_mail = meeting_scheduler._operator_email()
            if op_mail:
                try:
                    mailer.send_email(
                        op_mail, f"✓ Proposal approved — {opp['client']}",
                        f"{approver_name.strip() or 'The client'} approved the proposal for "
                        f"{opp['need']}. The workspace has advanced to Kickoff.\n"
                        f"{_public_base()}/opportunity/{opp['id']}")
                except Exception:  # noqa: BLE001
                    pass
            db.set_commercial_review_status(conn, review["id"], "approved")
            # ADR-0018: the client's approval is the primary AWARD TRIGGER — it creates the
            # project (in Kickoff), so the Sales→Production handoff has something real to
            # organize (team, milestones, invoices). The machine prepares; the client
            # committed; the operator confirms Start Production to enter Production.
            pid = _ensure_project_for_opp(conn, opp["id"])
            # Persist a proposal carrying the APPROVED deposit/balance so the deposit is real
            # everywhere downstream — the workspace Pay button, the /pay invoice, and the
            # Kickoff readiness (reported live: Kickoff showed "Everything is ready" with no
            # way to pay the deposit, because no proposal → no deposit amount existed).
            if pid is not None:
                _ensure_proposal_from_review(
                    conn, opp, pid, db.current_commercial_review(conn, opp["id"]))
            _reconcile_opp_status(conn, opp["id"])   # → Won (approval is the award)
            if campaigns.workspace_enabled():
                try:
                    ci = campaign_intelligence.ensure_for_opportunity(conn, opp)
                    db.add_ci_event(conn, ci["id"], actor="client", verb="commercial_approved",
                                    facet="commercial", key="review",
                                    to_value=f"v{review['version']} · {approver_name.strip()}",
                                    source="commercial")
                except Exception:  # noqa: BLE001
                    pass
    finally:
        conn.close()
    return RedirectResponse(f"/workspace/{token}", status_code=303)


@app.post("/opportunity/{opp_id}/request/{req_id}/decline")
def discovery_request_decline(opp_id: int, req_id: int):
    conn = db.connect()
    try:
        db.set_discovery_request_status(conn, req_id, "declined")
    finally:
        conn.close()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


# ── Client MANAGE (reschedule / cancel their own call) — token-gated. ─────────────────
@app.get("/meeting/{meeting_id}/manage", response_class=HTMLResponse)
def meeting_manage(request: Request, meeting_id: int, k: str = "", done: str = ""):
    conn = db.connect()
    try:
        m = db.get_meeting(conn, meeting_id)
        if m is None or not m["manage_token"] or not k or not hmac.compare_digest(
                str(k), str(m["manage_token"])):
            return HTMLResponse("Not found", status_code=404)
    finally:
        conn.close()
    return render(request, "meeting_manage.html", nav="", m=m, k=k, done=bool(done))


@app.post("/meeting/{meeting_id}/manage")
def meeting_manage_action(meeting_id: int, k: str = Form(""), action: str = Form(""),
                          date: str = Form(""), time: str = Form(""), tz_offset: str = Form("")):
    conn = db.connect()
    try:
        m = db.get_meeting(conn, meeting_id)
        if m is None or not m["manage_token"] or not k or not hmac.compare_digest(
                str(k), str(m["manage_token"])):
            return HTMLResponse("Not found", status_code=404)
        if action == "cancel":
            meeting_scheduler.cancel(conn, m)
        elif action == "reschedule" and date.strip():
            start_at = _to_utc_iso(f"{date.strip()}T{time.strip() or '09:00'}", tz_offset)
            if start_at:
                meeting_scheduler.reschedule(conn, m, start_at)
    finally:
        conn.close()
    return RedirectResponse(f"/meeting/{meeting_id}/manage?k={k}&done=1", status_code=303)


@app.post("/webhooks/capture/{provider}")
async def capture_webhook(provider: str, request: Request):
    """Capture-provider webhook (Recall.ai, …). The ONE inbound door for meeting transcripts:
    the provider seam verifies + normalizes the payload into a Meeting event, we correlate it
    to a Meeting and ingest the transcript through Campaign Intake. Signature-verified in the
    provider parser, idempotent, and non-blocking (the work is offloaded). Public surface —
    the provider signature, not the admin login, is the access control (ADR-0011/0015)."""
    body = await request.body()
    headers = dict(request.headers)

    def _work():
        conn = db.connect()
        try:
            return meetings_service.handle_capture_webhook(conn, provider, headers, body)
        finally:
            conn.close()

    result = await run_in_threadpool(_work)
    return JSONResponse(result)


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
    # ADR-0017: the email inherits from Campaign Intelligence, same as the Brief.
    ci_view, met = _brief_ci_context(conn, row)
    blocks = build_compose_blocks(
        opp, None, plan, overrides=overrides, opp_id=opp_id,
        contact_name=row["contact_name"], share_token=share_token,
        ci_view=ci_view, met=met,
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
    # The client link the email carries IS the client Workspace — its Discovery Summary is
    # the single brief the client reads (consolidation, ADR-0018). Token-gated so it's
    # shareable but not enumerable, and "Preview the brief" opens exactly what they'll see.
    page_url = f"/workspace/{token}"
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
    # ADR-0018: the emailed link is the client's durable Workspace (built by the page-link
    # block), which renders the LIVE brief inline — the relationship grows, nothing resets.
    # Sending still freezes a brief snapshot, but its role is the audit/PDF record (its Phase-3
    # job), NOT how the client views the brief; legacy ?v= links still render it on the
    # standalone route for backward compatibility.
    conn = db.connect()
    try:
        ci_view, met = _brief_ci_context(conn, row)
        overrides = db.get_doc_overrides(conn, opp_id)
        qual, _scored = evaluate(opp)
        discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
        est = build_estimate(opp, qual.team_shape or discipline.team_shape, discipline)
        doc = build_capabilities_doc(
            opp, qual, est, toggles=default_toggles(row["status"]), overrides=overrides,
            call_url=os.environ.get("CHORDENTIAL_DISCOVERY_CALL_URL", "").strip(),
            ci_view=ci_view, met=met)
        db.create_brief_snapshot(conn, opp_id, doc_to_json(doc))
    finally:
        conn.close()
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
def _gate_banner(err: str, t: Optional[int]) -> Optional[dict]:
    """The A-3 refusal banner (ADR-0024): who was blocked and what's missing, so
    the operator's next click is the fix, not a mystery. Pure lookup — returns
    None unless this request is the redirect from a refused assign."""
    if err != "agreement" or not t:
        return None
    conn = db.connect()
    try:
        row = db.get_talent(conn, int(t))
    finally:
        conn.close()
    if row is None:
        return None
    blockers = db.talent_assignment_blockers(row)
    missing = " + ".join(
        {"agreement": "an executed Composer Agreement",
         "rate": "a rate"}[b] for b in blockers) or "nothing"
    name = (row["name"] or "This creator") if "name" in row.keys() else "This creator"
    return {"talent_id": row["id"], "name": name, "missing": missing}


@app.get("/matchboard", response_class=HTMLResponse)
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


@app.post("/matchboard/assign")
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


def _brief_ci_context(conn, row):
    """ADR-0017: the brief renders Campaign Intelligence first. Returns (ci_view, met) —
    the canonical CI values + whether a discovery meeting has actually happened (tone)."""
    from datetime import datetime, timezone
    ci_view, met = {}, False
    if campaigns.workspace_enabled():
        try:
            ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
            ci_view = campaign_intelligence.brief_view(conn, ci_row["id"])
        except Exception:  # noqa: BLE001 — the brief must render even if CI hiccups
            ci_view = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    for m in db.list_meetings(conn, row["id"]):
        if m["status"] in ("ingested", "transcript_ready") or (
                m["status"] not in ("canceled",) and (m["start_at"] or "") and
                m["start_at"] <= now_iso):
            met = True
            break
    return ci_view, met


def _live_brief_ctx(conn, opp_id):
    """The Campaign Brief render context, live from Campaign Intelligence, ready to embed in
    the Client Workspace (ADR-0018). Builds the SAME ``doc`` the standalone brief route builds
    (single source), in read-only/public/embedded mode — the workspace is the frame, so the
    brief's own threshold cover is suppressed and no operator edit affordances render."""
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None
    qual, _scored = ev
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or discipline.team_shape, discipline)
    overrides = db.get_doc_overrides(conn, opp_id)
    ci_view, met = _brief_ci_context(conn, row)
    toggles = default_toggles(row["status"])
    # ADR-0020: the Discovery Summary exists only to confirm we heard them — never pricing,
    # never terms, never a deposit. The commercial conversation happens at the proposal.
    toggles.update({"cost": False, "terms": False})
    # The "book a discovery call" CTA belongs BEFORE discovery. Once it's happened (met),
    # this IS the summary of that call — re-inviting them to book one is contradictory.
    # Reported live: "it's still auto attaching the discovery call CTA when that already
    # happened." Suppress the CTA post-discovery; the summary's only action is the confirm box.
    call_url = "" if met else os.environ.get("CHORDENTIAL_DISCOVERY_CALL_URL", "").strip()
    doc = build_capabilities_doc(
        opp, qual, est, toggles=toggles, overrides=overrides,
        call_url=call_url, ci_view=ci_view, met=met)
    project = db.project_for_opp(conn, opp_id)
    deposit_amount = build_proposal(opp, qual, est).deposit_amount
    deposit_invoice_id = None
    if project is not None:
        sp = db.proposal_for_project(conn, project["id"])
        if sp is not None and sp["deposit_amount"]:
            deposit_amount = sp["deposit_amount"]
        for inv in db.list_invoices(conn, project["id"]):
            if inv["kind"] == "Deposit":
                deposit_invoice_id = inv["id"]
                break
    token = db.ensure_share_token(conn, opp_id)
    return {
        "row": row, "doc": doc, "overrides": overrides,
        "request_url": f"/opportunity/{opp_id}/request?k={token}",
        "deposit_amount": deposit_amount, "deposit_invoice_id": deposit_invoice_id,
        "edit": False, "public": True, "embedded": True,
        "chip_library": {}, "section_family": {}, "custom_chips": [], "delivery_templates": {},
    }


@app.get("/opportunity/{opp_id}/capabilities", response_class=HTMLResponse)
def opportunity_capabilities(request: Request, opp_id: int, k: str = "", v: str = ""):
    """The Campaign Brief — the branded, toggleable client-facing deliverable → preview,
    Save as PDF, and (with a valid ?k=<share_token>) the public client link the outreach
    email points to. One artifact: the emailed link opens this same brief.

    Sections default by deal stage (discovery hides cost; proposal adds the price
    band; contract adds terms + DocuSign). Once the toggle bar is submitted, each
    section follows its checkbox so you can tailor what the buyer sees."""
    conn = db.connect()
    try:
        row, opp, ev = _load(conn, opp_id)
        if row is None:
            return HTMLResponse("Opportunity not found", status_code=404)
        # Client link: a valid share token opens the brief publicly (no admin chrome); a
        # missing/bad token on a ?k request 404s so the brief never leaks. No ?k → the
        # admin edit view (already behind the login gate).
        public = False
        if (k or "").strip():
            token = row["share_token"] if "share_token" in row.keys() else None
            if not token or not hmac.compare_digest(str(k), str(token)):
                return HTMLResponse("Not found", status_code=404)
            # Consolidation (ADR-0018): the client's single brief IS the workspace Discovery
            # Summary. The live standalone client link now redirects into the workspace so
            # there's ONE durable client destination — no divergent second page. Reported
            # live: "uploading audio + Preview takes you to a totally different page." A
            # frozen ?v=<snapshot> send still renders verbatim here (historical record); the
            # operator edit view (no ?k, behind the login gate) still renders here too.
            public = True
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
        # The Brief's "Request a Discovery Call" CTA → the token-gated request form (same
        # share token that opens the brief), so the client requests, Jon schedules (ADR-0016).
        brief_token = db.ensure_share_token(conn, opp_id)
        # ADR-0017: Campaign Intelligence first; and a sent snapshot renders VERBATIM.
        ci_view, met = _brief_ci_context(conn, row)
        snapshot_doc = None
        if (v or "").strip().isdigit():
            snap = db.get_brief_snapshot(conn, int(v))
            if snap is not None and snap["opp_id"] == opp_id:
                snapshot_doc = doc_from_json(snap["doc_json"])
    finally:
        conn.close()
    request_url = f"/opportunity/{opp_id}/request?k={brief_token}"
    qual, scored = ev
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or discipline.team_shape, discipline)

    toggles = default_toggles(row["status"])
    qp = request.query_params
    if qp.get("submitted"):                       # toggle bar was applied
        for key in ("cost", "examples", "call", "terms", "delivery"):
            toggles[key] = qp.get(key) == "1"
    doc = snapshot_doc or build_capabilities_doc(
        opp, qual, est, toggles=toggles, overrides=overrides,
        call_url=os.environ.get("CHORDENTIAL_DISCOVERY_CALL_URL", "").strip(),
        ci_view=ci_view, met=met,
    )

    # Edit-mode payload the (later) editable-template UI consumes: the chip library
    # per editable section (deliverable chips scoped to the chosen template), the
    # available delivery templates for the override dropdown, and saved "My chips".
    edit = qp.get("edit") == "1" and not public   # the client link is never editable
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
        section_family=SECTION_FAMILY, public=public, request_url=request_url,
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


# ADR-0017: brief fields that are Campaign Intelligence slots. Editing one in the brief
# writes CI (the single source of truth); the brief then re-renders from the updated
# intelligence — edits are never page-local and never revert to stock copy.
_BRIEF_CI_FIELDS = {
    "business_objective": ("engagement", "business_objective"),
    "budget_band": ("engagement", "budget_band"),
    "deadline": ("engagement", "deadline"),
    "deliverables": ("engagement", "deliverables"),
    "decision_makers": ("buyer", "decision_makers"),
    "brand_notes": ("buyer", "brand_notes"),
    "agency_notes": ("buyer", "agency_notes"),
    "campaign_objective": ("direction", "campaign_objective"),
    "emotional_arc": ("direction", "emotional_arc"),
    "reference_playlist": ("direction", "reference_playlist"),
}


@app.post("/opportunity/{opp_id}/doc/ci-field")
def doc_ci_field(opp_id: int, name: str = Form(""), value: str = Form("")):
    """Apply a brief edit to Campaign Intelligence itself (ADR-0017)."""
    if name in _BRIEF_CI_FIELDS and campaigns.workspace_enabled():
        conn = db.connect()
        try:
            row = db.get_opportunity(conn, opp_id)
            if row is None:
                return HTMLResponse("Opportunity not found", status_code=404)
            ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
            facet, key = _BRIEF_CI_FIELDS[name]
            campaign_intelligence.edit_or_create(
                conn, ci_row["id"], facet, key, "fact", value, actor="operator")
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
    if path is not None:
        return FileResponse(path)
    # Disk copy gone (ephemeral storage wiped on redeploy) — rehydrate from the durable DB
    # mirror so a published version's audio keeps playing across deploys.
    base = os.path.basename(name or "")
    if base and base == name:
        conn = db.connect()
        try:
            blob = db.get_media_blob(conn, base)
        finally:
            conn.close()
        if blob is not None:
            data, ctype = blob
            if not ctype:
                import mimetypes
                ctype = mimetypes.guess_type(base)[0] or "application/octet-stream"
            # Best-effort: restore the file to disk so future reads hit the fast path + so
            # range/seek requests are served natively; then serve the bytes now.
            try:
                os.makedirs(UPLOAD_DIR, exist_ok=True)
                with open(os.path.join(UPLOAD_DIR, base), "wb") as fh:
                    fh.write(data)
            except OSError:
                pass
            return Response(content=data, media_type=ctype)
    return PlainTextResponse("not found", status_code=404)


def _persist_upload(conn, name: str, data: bytes, content_type: str = "") -> None:
    """Write an uploaded file to disk AND mirror it into the durable DB (ADR: uploads survive
    redeploys). The single place that persists media, so every write site is durable."""
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        with open(os.path.join(UPLOAD_DIR, os.path.basename(name)), "wb") as fh:
            fh.write(data)
    except OSError:
        pass
    if not content_type:
        import mimetypes
        content_type = mimetypes.guess_type(name)[0] or ""
    db.save_media_blob(conn, os.path.basename(name), data, content_type)


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
    if path is not None:
        return FileResponse(path, filename=os.path.basename(path))
    # Ephemeral disk wiped: rehydrate from the durable DB mirror (ZIPs are mirrored at build,
    # assets via _persist_upload). A ZIP built BEFORE the mirror existed isn't stored — rebuild
    # it from the durable source media (which _build_delivery_package rehydrates first).
    base = os.path.basename(name or "")
    if base and base == name:
        conn2 = db.connect()
        try:
            blob = db.get_media_blob(conn2, base)
            if blob is None and base.lower().endswith(".zip"):
                pkg = _build_delivery_package(conn2, project_id)
                blob = db.get_media_blob(conn2, base)
                if blob is None and pkg is not None:
                    blob = db.get_media_blob(conn2, os.path.basename(pkg["filename"]))
        finally:
            conn2.close()
        if blob is not None:
            data, ctype = blob
            try:
                os.makedirs(UPLOAD_DIR, exist_ok=True)
                with open(os.path.join(UPLOAD_DIR, base), "wb") as fh:
                    fh.write(data)
            except OSError:
                pass
            return Response(content=data, media_type=ctype or "application/zip",
                            headers={"Content-Disposition": f'attachment; filename="{base}"'})
    return PlainTextResponse("not found", status_code=404)


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
        agreement_at = (row["agreement_executed_at"]
                        if "agreement_executed_at" in row.keys() else None)
        agreement_ref = (row["agreement_ref"]
                         if "agreement_ref" in row.keys() else "") or ""
        assignment_blockers = db.talent_assignment_blockers(row)
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
        agreement_executed_at=agreement_at, agreement_ref=agreement_ref,
        assignment_blockers=assignment_blockers,
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


@app.post("/talent/{talent_id}/agreement")
def talent_set_agreement(talent_id: int, executed: str = Form(""), ref: str = Form("")):
    """Record/clear the standing Composer Agreement (ADR-0024) — the assignment
    gate's other half alongside the rate. Recording stamps today; clearing wipes
    both date and ref."""
    from datetime import date as _date
    conn = db.connect()
    try:
        db.set_talent_agreement(
            conn, talent_id,
            _date.today().isoformat() if executed == "1" else None, ref)
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
    notes, by_id = [], {}
    rows = db.list_review_comments(conn, project_id)
    for c in rows:
        # Only the notes a composer acts on, and only for the version they're on now.
        if c["kind"] not in ("comment", "change_request", "asset_change"):
            continue
        if c["parent_id"]:
            continue                       # replies thread under their parent below
        if (c["version"] or "") != cur_n:
            continue
        keys = c.keys()
        n = {
            "id": c["id"], "t": c["t_seconds"], "author": c["author"],
            "body": c["body"], "kind": c["kind"], "resolved": bool(c["resolved"]),
            "addressed": bool(c["composer_addressed"]
                              if "composer_addressed" in keys else 0),
            "replies": [],
        }
        notes.append(n); by_id[c["id"]] = n
    for c in rows:                          # thread replies (client, studio, composer)
        if c["parent_id"] and c["parent_id"] in by_id:
            keys = c.keys()
            by_id[c["parent_id"]]["replies"].append({
                "author": c["author"], "body": c["body"],
                "internal": bool(c["internal"] if "internal" in keys else 0),
            })
    used = int(delivery.get("revisions_used") or 0)
    scoped = int(delivery.get("revisions_included") or 0) or None
    return {
        "notes": notes,
        # What's OWED: unhandled change requests. Praise/comments never inflate
        # the composer's to-do count (composer review P1-7 / EP P2-5).
        "open_count": sum(1 for n in notes
                          if n["kind"] == "change_request"
                          and not (n["resolved"] or n["addressed"])),
        "revisions_used": used,
        "revisions_included": scoped,
        # ONE round sentence across all three doors (EP P0-2) — identical formula
        # to the delivery portal/console chips.
        "round_phrase": (f"Round {min(used + 1, scoped)} of {scoped}"
                         if scoped else ""),
    }


def _rel_deadline(iso: str) -> str:
    """A deadline as the room speaks it — 'due in 11 days', not raw ISO."""
    try:
        from datetime import date as _d
        days = (_d.fromisoformat(str(iso).strip()[:10]) - _d.today()).days
    except (ValueError, TypeError):
        return str(iso or "")
    if days > 1:
        return f"due in {days} days"
    if days == 1:
        return "due tomorrow"
    if days == 0:
        return "due today"
    return f"{-days} day{'s' if days != -1 else ''} past due"


def _creator_assignment_view(conn, talent_id: int) -> list:
    """Per-assignment cards for the composer portal: brief, role, deadline, the
    delivery state, the versions THIS creator can submit/see, and the client's
    review feedback on the current version (read-only)."""
    out = []
    for a in db.list_talent_assignments(conn, talent_id):
        delivery = db.get_delivery(conn, a["project_id"])
        prow = db.get_project(conn, a["project_id"])
        # Once the client approves the master (creative lock), the composer's job shifts
        # from iterating the master to producing the DERIVATIVE deliverables (instrumental,
        # cutdowns, verticals, stems). Surface those so the portal can ask for them —
        # the master is the version ladder, so it's excluded here.
        locked = bool(production.creative_lock(delivery))
        # Scoped deliverables + specs are DAY-ONE knowledge (composer review P1-8:
        # "I bounce to spec from take one if you tell me on day one"), not a
        # post-approval surprise. Pending = submitted, with the studio (EP P0-3).
        pending_labels = {(a.get("label") or "").strip().lower()
                          for a in (delivery.get("pending_assets") or [])}
        deliverables = []
        if prow is not None:
            for d in scoped_deliverables(prow, delivery):
                if d.get("is_master"):
                    continue
                deliverables.append({
                    "asset": d["asset"], "group": d["group"],
                    "spec": d.get("spec", ""), "uploaded": bool(d.get("uploaded")),
                    "pending": (d["asset"] or "").strip().lower() in pending_labels,
                })
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
            # The creator's OWN latest submission, even while it's still pending Jon's
            # review — so they can see it landed instead of the empty "upload your first"
            # state (reported live: after submitting, the portal looked like nothing happened).
            "pending": delivery.get("pending_version") or None,
            "feedback": _creator_feedback(conn, a["project_id"], delivery),
            "creative_lock": locked,
            "deliverables": deliverables,
            # The room's Brief layer renders the REAL creative brief (the same
            # effective brief the console shows), not a restatement of the title.
            "brief": seed_brief(
                prow,
                db.get_opportunity(conn, prow["opp_id"])
                if prow is not None and prow["opp_id"] else None,
                delivery),
            "deadline_rel": _rel_deadline(a["deadline"]) if a["deadline"] else "",
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


@app.post("/creator/{token}/project/{project_id}/note/{comment_id}/address")
def creator_address_note(token: str, project_id: int, comment_id: int):
    """The composer marks a client note addressed (or reopens it) — COMPOSER-side
    working state only (EP P0-1): the client's resolved flag is untouched, so the
    client never sees a note flip "resolved" without the studio publishing a take.

    Same double guard as every creator action: valid portal token AND an actual
    assignment to this project."""
    conn = db.connect()
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        if not db.talent_is_assigned(conn, row["id"], project_id):
            return HTMLResponse("Not assigned to this project", status_code=403)
        db.toggle_comment_addressed(conn, project_id, comment_id)
    finally:
        conn.close()
    return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)


@app.post("/creator/{token}/project/{project_id}/note/{comment_id}/reply")
async def creator_reply_note(token: str, project_id: int, comment_id: int,
                             body: str = Form("")):
    """The composer asks the studio about a note — the talk-back channel both
    persona reviews named as the #1 reason the phone stays primary.

    The reply is INTERNAL (composer↔studio): it threads under the client's note in
    the composer room and the studio console, and never renders on the client
    portal — the studio mediates what reaches the client (production model:
    feedback→interpretation is the house's craft)."""
    conn = db.connect()
    who = ""
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        if not db.talent_is_assigned(conn, row["id"], project_id):
            return HTMLResponse("Not assigned to this project", status_code=403)
        text = (body or "").strip()
        if text:
            who = row["name"]
            parent = conn.execute(
                "SELECT id FROM review_comments WHERE id = ? AND project_id = ?",
                (comment_id, project_id)).fetchone()
            if parent is not None:
                db.add_review_comment(
                    conn, project_id, author=who,
                    email=(row["email"] or "") if "email" in row.keys() else "",
                    body=text, kind="comment", parent_id=comment_id, internal=True)
        project = db.get_project(conn, project_id)
    finally:
        conn.close()
    if who:
        await run_in_threadpool(
            _notify_operator_review, project_id, project,
            f"Composer question — {_campaign_label(project) if project else 'campaign'}",
            f"{who} replied to a client note. Review it in the delivery console.")
    return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)


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
        _sync_role_milestones(conn, project_id)   # Composer deliverable → In progress
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
    return RedirectResponse(f"/creator/{token}?submitted={project_id}#p{project_id}",
                            status_code=303)


@app.post("/creator/{token}/project/{project_id}/deliverable")
async def creator_submit_deliverable(
    request: Request, token: str, project_id: int, label: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """A creator uploads a scoped DELIVERABLE (instrumental / TV mix, cutdowns, verticals,
    stems) AFTER the master is approved. Lands in ``delivery_json['assets']`` under its
    label so the client can sign it off, and pings the operator. Mirrors the operator
    Assets-agent storage; guarded by a valid portal token AND an assignment to the project.

    Returns an HONEST result: for an AJAX upload (``X-Requested-With`` header) it returns
    JSON ``{ok, count}`` reflecting what actually persisted, so the portal only marks a row
    "Delivered" when the asset truly landed (never on a redirect that stored nothing)."""
    xhr = (request.headers.get("x-requested-with") or "").lower() in ("fetch", "xmlhttprequest")
    def _fail(msg, code=400):
        if xhr:
            return JSONResponse({"ok": False, "error": msg}, status_code=code)
        # No-JS form post: a soft "no file" bounces back to the portal; hard errors
        # (auth, save failure) return their real status code.
        if code == 400:
            return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)
        return HTMLResponse(msg, status_code=code)
    conn = db.connect()
    campaign = "Campaign"
    who = ""
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return _fail("not found", 404)
        if not db.talent_is_assigned(conn, row["id"], project_id):
            return _fail("not assigned", 403)
        if file is None or not (file.filename or "").strip():
            return _fail("no file", 400)
        who = row["name"]
        ext = os.path.splitext(file.filename)[1].lower()
        ctype = (file.content_type or "").lower()
        kind = "audio" if (ext in _AUDIO_EXTS or ctype.startswith("audio/")) else "file"
        data = await file.read()
        if not data:
            return _fail("empty file", 400)
        # Collision-proof on-disk name (random suffix) so nothing can overwrite another
        # upload's file — no counter to race on.
        safe_ext = ext if ext else (".mp3" if kind == "audio" else ".bin")
        safe_name = f"proj{project_id}-{os.urandom(5).hex()}{safe_ext}"
        _persist_upload(conn, safe_name, data)
        delivery = db.get_delivery(conn, project_id)
        # EP review P0-3: deliverables get the SAME studio gate as the master.
        # The upload lands PENDING — the studio vets and publishes it before the
        # client can ever see it (uniform publish gate, stems included).
        from datetime import datetime as _dt, timezone as _tz
        pending = list(delivery.get("pending_assets") or [])
        deliverable = (label.strip() or file.filename)
        pending.append({"label": deliverable, "url": f"/uploads/{safe_name}",
                        "filename": safe_name, "orig": file.filename,
                        "kind": kind, "by": who,
                        "at": _dt.now(_tz.utc).isoformat()})
        db.update_delivery(conn, project_id, "pending_assets", pending)
        # CONFIRM it actually persisted before telling the composer it landed.
        stored = db.get_delivery(conn, project_id).get("pending_assets") or []
        landed = any(a.get("filename") == safe_name for a in stored)
        count = len(stored)
        prow = db.get_project(conn, project_id)
        campaign = (prow["need"] if prow is not None else "") or "Campaign"
        db.add_update(conn, project_id,
                      f"{who} submitted '{deliverable}' — with the studio for review.")
    finally:
        conn.close()
    if not landed:
        return _fail("not saved — please try again", 500)
    await run_in_threadpool(
        _notify_operator_review, project_id, None, f"Deliverable submitted — {campaign}",
        f"{who} submitted a deliverable. Vet it in the delivery console, then publish.")
    if xhr:
        return JSONResponse({"ok": True, "label": deliverable, "count": count})
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


def _ensure_proposal_from_review(conn, opp_row, project_id, review_row) -> None:
    """After the client approves the Commercial Review, persist a Proposal for the project
    carrying the APPROVED money (deposit, balance, total — operator edits included) so the
    deposit is real everywhere downstream: the workspace Pay button, the /pay invoice, and
    the Kickoff readiness. Idempotent — a no-op if the project already has a proposal."""
    if review_row is None or db.proposal_for_project(conn, project_id) is not None:
        return
    review = commercial.review_from_json(review_row["doc_json"])
    if review is None:
        return
    row, opp, ev = _load(conn, opp_row["id"])
    if row is None:
        return
    qual, _scored = ev
    discipline = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or discipline.team_shape, discipline)
    proposal = build_proposal(opp, qual, est)
    # Override the estimator's numbers with exactly what the client approved.
    total_mid = int(round(((review.fee_low or 0) + (review.fee_high or 0)) / 2))
    if review.deposit_pct:
        proposal.deposit_pct = review.deposit_pct
    if review.deposit_amount:
        proposal.deposit_amount = review.deposit_amount
    if total_mid:
        proposal.total_price = total_mid
    proposal.balance_due = (review.balance_amount
                            or max(0, (total_mid or proposal.total_price) - proposal.deposit_amount))
    db.insert_proposal(conn, project_id, opp_row["id"], proposal)


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
    # Thread the buyer link: resolve (and record on the opp) the Agency Intelligence
    # record this opportunity is for, so the project — and the campaign it becomes —
    # can reach the agency's intelligence, not just a client name. Best-effort: an
    # exact name match or nothing (DISCOVERY_INTELLIGENCE_LINEAGE.md, step 1).
    agency_id = db.resolve_opportunity_agency(conn, row)
    # ADR-0018: the project inherits the opportunity's workspace token so the client's
    # single URL never changes across the award boundary.
    workspace_token = db.ensure_share_token(conn, opp_id)
    pid = db.insert_project(
        conn, opp_id, opp.client, opp.need, opp.budget_min, opp.budget_max, roles,
        agency_id=agency_id, share_token=workspace_token,
    )
    db.seed_default_milestones(conn, pid, roles)
    # ADR-0020: Direction is born in Discovery — production inherits it. Seed the approved
    # creative territory from Campaign Intelligence; nobody creates directions later.
    if campaigns.workspace_enabled():
        try:
            ci_row = campaign_intelligence.ensure_for_opportunity(conn, row)
            fields = campaign_intelligence.brief_view(conn, ci_row["id"]).get("fields") or {}
            name_ = (fields.get("campaign_objective") or "").strip()
            thesis = (fields.get("emotional_arc") or "").strip()
            if name_ or thesis:
                d = production.add_direction(conn, db, pid,
                                             name=(name_ or "The approved direction")[:80],
                                             thesis=thesis[:160])
                if d:
                    production.decide_direction(conn, db, pid, d["id"], status="selected")
        except Exception:  # noqa: BLE001 — seeding never blocks the award
            pass
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


# Scoped role name → the craft (MusicDiscipline) that qualifies a creator for it.
# Drives per-role candidate lists so the Composer slot lists composers, the Mixer
# slot lists mixers, etc. — instead of one opp-discipline list shown under every role.
_ROLE_DISCIPLINE = {
    "composer": MusicDiscipline.COMPOSITION,
    "music editor": MusicDiscipline.COMPOSITION,
    "arranger": MusicDiscipline.ARRANGEMENT,
    "orchestrator": MusicDiscipline.ARRANGEMENT,
    "sound designer": MusicDiscipline.SOUND_DESIGN,
    "mixer": MusicDiscipline.MIXING,
    "mix engineer": MusicDiscipline.MIXING,
    "mastering": MusicDiscipline.MIXING,
    "music supervisor": MusicDiscipline.SUPERVISION,
}


def _sync_role_milestones(conn, project_id: int) -> None:
    """Keep the per-role Delivery-progress milestones honest with the actual delivery
    lifecycle (reported live: the Composer milestone stayed 'Pending' after a V1 was
    submitted). Forward-only, and only touches role-tagged (auto-seeded) milestones —
    operator-added milestones stay fully manual. The lead role (first scoped role) owns the
    master; derivative roles begin once the master is locked; everything is Done on ship."""
    prow = db.get_project(conn, project_id)
    if prow is None:
        return
    try:
        roles = list(json.loads(prow["roles"] or "[]"))
    except Exception:  # noqa: BLE001
        roles = []
    lead = roles[0] if roles else None
    delivery = db.get_delivery(conn, project_id)
    has_version = bool(delivery.get("pending_version")) or bool(versions_list(delivery))
    locked = bool(production.creative_lock(delivery))
    shipped = (delivery.get("state") or "") in ("Delivered", "Released")
    rank = {"Pending": 0, "In progress": 1, "Done": 2}
    for m in db.list_milestones(conn, project_id):
        role = (m["role"] or "").strip()
        if not role:
            continue                         # operator-added milestones stay manual
        if shipped:
            target = "Done"
        elif locked:
            target = "Done" if role == lead else "In progress"
        elif has_version and role == lead:
            target = "In progress"
        else:
            target = m["status"]
        if rank.get(target, 0) > rank.get(m["status"], 0):
            db.update_milestone_status(conn, m["id"], target)


def _project_view(conn, project_id: int):
    """Assemble a project with its roles, current assignments, and ranked candidates."""
    row = db.get_project(conn, project_id)
    if row is None:
        return None
    _sync_role_milestones(conn, project_id)  # reflect delivery reality before we read them
    roles = json.loads(row["roles"]) if row["roles"] else []
    assignments = db.list_assignments(conn, project_id)
    by_role = {role: [] for role in roles}
    for a in assignments:
        by_role.setdefault(a["role"], []).append(a)

    # Ranked candidates come from the linked opportunity's discipline (the matcher).
    talent_pool = db.load_talent(conn)
    matches = []
    need_text = ""
    if row["opp_id"] is not None:
        opp_row = db.get_opportunity(conn, row["opp_id"])
        if opp_row is not None:
            opp = db.opportunity_from_row(opp_row)
            qual, scored = evaluate(opp)
            need_text = f"{opp.need} {opp.description}"
            matches = match_talent(
                qual.discipline, qual.secondary_disciplines, need_text, talent_pool,
            )
    # Per-role candidates: each scoped role lists the approved creators whose craft fits
    # THAT role (Composer→composition, Mixer→mixing, …), ranked by fit — not the single
    # opp-discipline list shown identically under every role. Reported live: "I'm not
    # getting a full list of matchable composers to match to a project."
    matches_by_role = {}
    for role in roles:
        disc = _ROLE_DISCIPLINE.get((role or "").strip().lower())
        matches_by_role[role] = (
            match_talent(disc, [], need_text, talent_pool) if disc is not None else matches
        )
    milestones = db.list_milestones(conn, project_id)
    progress = db.milestone_progress(conn, project_id)
    return {
        "row": row, "roles": roles, "by_role": by_role, "matches": matches,
        "matches_by_role": matches_by_role,
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
def project_detail(request: Request, project_id: int,
                   err: str = "", t: Optional[int] = None):
    conn = db.connect()
    try:
        view = _project_view(conn, project_id)
        if view is None:
            return HTMLResponse("Project not found", status_code=404)
    finally:
        conn.close()
    return render(
        request, "project_detail.html", nav="projects",
        project_states=db.PROJECT_STATES, milestone_states=db.MILESTONE_STATES,
        gate_banner=_gate_banner(err, t), **view,
    )


@app.post("/project/{project_id}/assign")
def project_assign(project_id: int, role: str = Form(...), talent_id: int = Form(...)):
    """The decision action — Jon assigns a creator to a role. The only assign
    path. Reported live: signing a creator should email them the project
    scope — this is the one place that decision is made, so it's the one
    place the email fires from."""
    conn = db.connect()
    try:
        row = db.get_talent(conn, talent_id)
        # ADR-0024 (the A-3 floor): no assignment without an executed agreement +
        # rate — refused server-side before any side effect, mirroring the
        # payment gate on release.
        if db.talent_assignment_blockers(row):
            return RedirectResponse(
                f"/project/{project_id}?err=agreement&t={talent_id}",
                status_code=303)
        db.add_assignment(conn, project_id, role, talent_id)
        t = db.talent_from_row(row) if row is not None else None
        name = t.name if t else "a creator"
        # The assignment IS the broadcast — post a roster line to the crew feed
        # automatically (no manual "post an update" step). Names the whole team so
        # everyone on the project sees who they're now working with.
        crew = db.project_crew(conn, project_id)
        names = ", ".join(c["name"] for c in crew) or name
        db.add_update(
            conn, project_id,
            f"{name} joined the crew as {role}. Current team: {names}.",
            "assignment",
        )
        project = db.get_project(conn, project_id)
        # ADR-0020: one decision, many quiet operations — the portal exists the moment the
        # composer does. Mint their portal token now so the scope email carries their one
        # link (brief, feedback, uploads); no separate "issue portal link" step.
        portal_token = db.ensure_talent_portal_token(conn, talent_id) if hasattr(
            db, "ensure_talent_portal_token") else None
        if portal_token is None:
            trow = db.get_talent(conn, talent_id)
            portal_token = trow["portal_token"] if trow is not None and "portal_token" in trow.keys() else None
            if not portal_token:
                import secrets as _sec
                portal_token = _sec.token_urlsafe(12)
                conn.execute("UPDATE talent SET portal_token=? WHERE id=?",
                             (portal_token, talent_id))
                conn.commit()
    finally:
        conn.close()
    if t is not None and t.email and mailer.mail_configured() and project is not None:
        base = _public_base()
        scope = recruiting.compose_project_assignment(
            t, role=role, client=project["client"], need=project["need"],
            deadline=project["deadline"] or "",
        )
        body = scope["body"]
        if portal_token:
            body += (f"\n\nYour portal — the brief, deliverables, timeline, client feedback "
                     f"and your uploads all live here:\n{base}/creator/{portal_token}")
        mailer.send_email(
            t.email, scope["subject"], body,
            html=mailer.branded_html(base, body),
        )
    # Update the CLIENT too — their team is coming together (reported live: assigning a
    # creator should alert the client). Warm status note via the opportunity's contact;
    # never the creator's rate. Best-effort, off the assign decision.
    if project is not None and mailer.mail_configured() and project["opp_id"]:
        conn2 = db.connect()
        try:
            opp = db.get_opportunity(conn2, project["opp_id"])
            contact_email = (opp["contact_email"] if opp is not None
                             and "contact_email" in opp.keys() else "") or ""
            token = db.ensure_share_token(conn2, project["opp_id"]) if opp is not None else ""
        finally:
            conn2.close()
        if contact_email:
            base = _public_base()
            upd = recruiting.compose_client_assignment_update(
                role=role, creator_name=name, need=project["need"],
                contact_name=(opp["contact_name"] if opp is not None
                              and "contact_name" in opp.keys() else "") or "",
                workspace_url=f"{base}/workspace/{token}" if token else "",
            )
            try:
                mailer.send_email(contact_email, upd["subject"], upd["body"],
                                  html=mailer.branded_html(base, upd["body"]))
            except Exception:  # noqa: BLE001 — a client update never blocks the assign
                pass
    # Broadcast the new assignment to the rest of the project crew (the new hire
    # already got the tailored scope email above, so they're excluded here).
    if project is not None:
        _notify_assigned_creators(
            project_id, project,
            subject=f"New teammate on {project['client']} — {project['need']}",
            body_text=(f"{name} just joined the crew as {role}. "
                       f"The full team is now: {names}."),
            exclude_email=(t.email if t is not None else ""),
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


def _delivery_view(conn, project_id: int, selected_v=None, client_view: bool = False):
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
    # The client portal never sees composer↔studio internal notes (publish-gate
    # principle applied to words); the console sees everything.
    comments = db.list_review_comments(conn, project_id,
                                       include_internal=not client_view)
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
    _clock = production.creative_lock(delivery)
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
        elif d.get("from_version"):
            # The primary master is the review version itself — it has no per-row
            # Approve control; the main "Approve the master" button IS its sign-off,
            # so its status simply mirrors the creative lock.
            if _clock:
                item["approval"] = {"status": "Approved", "by": (_clock.get("by") or ""),
                                    "email": "", "date": "", "version": str(_clock.get("version_n") or "")}
                n_scoped_approved += 1
            else:
                item["approval"] = {"status": "Pending", "by": "", "email": "", "date": "", "version": ""}
            item["asset_key"] = ""              # approved via the main button, not a row button
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
    # Self-heal: once delivered, the balance must be a real Issued invoice so the download
    # stays gated behind it — otherwise a paid DEPOSIT reads as "paid in full" (nothing else
    # outstanding) and the files unlock without the balance (reported live).
    if (delivery.get("state") or "") in ("Delivered", "Released"):
        _ensure_final_invoice_issued(conn, project_id)
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
        # ADR-0019: the production spine on the console — directions + the lock.
        "prod_directions": production.directions(delivery),
        "creative_lock": production.creative_lock(delivery),
        "download_unlocked": download_unlocked,
        "invoice_balance": balance,
        "state": delivery.get("state") or DELIVERY_STATES[0],
        "version_state": revisions["state"],
        "cert": cert,
        # The honest Content-ID sentence — the ONE source of truth (delivery.py),
        # so the browser doc and the ZIP doc can't drift on legally-material copy.
        "content_id_honest": CONTENT_ID_HONEST,
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


# --------------------------------------------------------------------------- #
# Campaign Workspace (Creative OS) — the campaign is the workspace root. Flagged
# behind CHORDENTIAL_CAMPAIGN_WORKSPACE (OFF by default); routes 404 when the module
# is disabled, so the existing product is untouched. See docs/campaign-workspace-prd.md.
# --------------------------------------------------------------------------- #
def _campaign_view(conn, campaign_id: int):
    """Assemble the Campaign Home view (or None if not found)."""
    camp = db.get_campaign(conn, campaign_id)
    if camp is None:
        return None
    direction = db.get_campaign_direction(conn, campaign_id)
    sections = [{
        "key": key, "label": label, "hint": hint,
        "body": (direction[key]["body"] if key in direction else ""),
        "complete": bool(direction[key]["complete"]) if key in direction else False,
    } for key, label, hint in campaigns.DIRECTION_SECTIONS]
    # The buyer link (step 1 of the Discovery Intelligence lineage): the campaign now
    # reaches the Agency/Company Intelligence record, not just a client name. Surface
    # whether it's linked and whether intelligence exists to inherit (the next step).
    agency = db.get_agency(conn, camp["agency_id"]) if camp["agency_id"] else None
    agency_has_intel = bool(
        db.get_agency_intel(conn, camp["agency_id"])) if camp["agency_id"] else False
    # Campaign Intelligence — the living canonical record. Lazy-create + seed it (from the
    # opportunity, the linked agency, and the direction cards), then surface it: the
    # provenance panel showing every fact/insight/recommendation/open-question with its
    # kind, sources, and disposition. This is the object every module inherits from.
    ci = campaign_intelligence.ensure_for_campaign(conn, camp)
    ci_view = campaign_intelligence.fields_view(conn, ci["id"])
    return {
        "campaign": camp,
        "phases": campaigns.PHASES,
        "phase_index": campaigns.phase_index(camp["phase"]),
        "next_phase": campaigns.next_phase(camp["phase"]),
        "sections": sections,
        "completeness": campaigns.direction_completeness(direction),
        "agency": agency,
        "agency_has_intel": agency_has_intel,
        "ci": ci,
        "ci_view": ci_view,
    }


@app.post("/project/{project_id}/campaign/open")
def campaign_open(project_id: int):
    """Open (or create) the campaign workspace that wraps a project — the bridge from
    the project record into the Creative OS. Idempotent (lazy-creates once)."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, project_id)
        camp = db.ensure_campaign_for_project(
            conn, project_id, phase=campaigns.hydrate_phase_from_delivery(delivery))
        if camp is None:
            return HTMLResponse("Project not found", status_code=404)
        cid = camp["id"]
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{cid}", status_code=303)


@app.get("/campaign/{campaign_id}", response_class=HTMLResponse)
def campaign_home(request: Request, campaign_id: int):
    """Campaign Home — one screen, one campaign: the creative timeline, the structured
    creative direction, and the link into delivery. The Creative OS command view."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        view = _campaign_view(conn, campaign_id)
        if view is None:
            return HTMLResponse("Campaign not found", status_code=404)
    finally:
        conn.close()
    qp = request.query_params
    view["capture_summary"] = ({
        "understood": qp.get("understood"), "added": qp.get("added"),
        "asked": qp.get("asked"),
    } if qp.get("understood") is not None else None)
    return render(request, "campaign_home.html", nav="projects", **view)


@app.post("/campaign/{campaign_id}/direction")
def campaign_set_direction(campaign_id: int, section: str = Form(...),
                           body: str = Form(""), complete: str = Form("")):
    """Edit one structured creative-direction section (the composer's brief)."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    if section not in campaigns.DIRECTION_KEYS:
        return HTMLResponse("Unknown section", status_code=400)
    done = str(complete).strip() in ("1", "true", "on", "yes")
    conn = db.connect()
    try:
        db.update_campaign_direction(conn, campaign_id, section, body=body, complete=done)
        # Contribute the edit back to Campaign Intelligence so the canonical record stays
        # LIVE — the workspace doesn't keep a private copy, it writes through CI (the
        # stated brief is a `fact`; marking it complete disposes it).
        camp = db.get_campaign(conn, campaign_id)
        if camp is not None and body.strip():
            ci = campaign_intelligence.ensure_for_campaign(conn, camp)
            campaign_intelligence.contribute(
                conn, ci["id"], "direction", section, body.strip(),
                kind="fact", source="workspace", contributed_by="operator",
                confirmed=done)
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{campaign_id}#direction", status_code=303)


@app.post("/campaign/{campaign_id}/capture")
def campaign_capture(campaign_id: int, stance: str = Form("objective"),
                     text: str = Form("")):
    """Campaign Intake: the user tells ChordOS what happened (objective) or what's their
    read (Producer Debrief). The pipeline extracts, classifies by kind, and writes to
    Campaign Intelligence — the user never touches the object. Redirects with a summary
    (understood %, added, gaps)."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    text = (text or "").strip()
    if not text:
        return RedirectResponse(f"/campaign/{campaign_id}#capture", status_code=303)
    conn = db.connect()
    try:
        camp = db.get_campaign(conn, campaign_id)
        if camp is None:
            return HTMLResponse("Campaign not found", status_code=404)
        summary = campaign_intake.ingest(conn, camp, stance, text)
    finally:
        conn.close()
    q = summary["questions"]
    return RedirectResponse(
        f"/campaign/{campaign_id}?understood={summary['understanding_pct']}"
        f"&added={summary['added']}&asked={len(q)}#intelligence", status_code=303)


@app.post("/campaign/{campaign_id}/intelligence/answer")
def campaign_ci_answer(campaign_id: int, field_id: str = Form(...), answer: str = Form("")):
    """Answer a follow-up open_question — the conversational gap-fill. The answer becomes
    a confirmed fact on the target field and the question is marked answered."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    answer = (answer or "").strip()
    conn = db.connect()
    try:
        if answer and str(field_id).strip().isdigit():
            row = db.get_ci_field(conn, int(field_id))
            if row is not None:
                campaign_intake.answer_gap(conn, row, answer, created_by="operator")
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{campaign_id}#intelligence", status_code=303)


@app.post("/campaign/{campaign_id}/intelligence/dispose")
def campaign_ci_dispose(campaign_id: int, field_id: str = Form(...)):
    """The human disposition gate on a Campaign Intelligence field — confirm a fact,
    acknowledge an insight, accept a recommendation, answer a question (machine proposes,
    human disposes, §4.1)."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        if str(field_id).strip().isdigit():
            row = db.get_ci_field(conn, int(field_id))
            if row is not None:
                campaign_intelligence.dispose(conn, row, actor="operator")
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{campaign_id}#intelligence", status_code=303)


@app.post("/campaign/{campaign_id}/agency")
def campaign_link_agency(campaign_id: int, action: str = Form("match"),
                         agency_id: str = Form("")):
    """Link the campaign to an Agency Intelligence record — the buyer thread. Three
    actions: 'match' re-runs the name match against the agencies DB (useful once an
    agency has been enriched after the campaign opened); 'set' links a specific
    agency_id; 'unlink' clears it. Best-effort, honest (an exact match or nothing)."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    conn = db.connect()
    try:
        camp = db.get_campaign(conn, campaign_id)
        if camp is None:
            return HTMLResponse("Campaign not found", status_code=404)
        if action == "unlink":
            db.set_campaign_agency(conn, campaign_id, None)
        elif action == "set" and str(agency_id).strip().isdigit():
            db.set_campaign_agency(conn, campaign_id, int(agency_id))
        else:  # match by the campaign's agency/client name
            m = db.match_agency_by_name(conn, camp["agency_client"] or camp["brand"])
            db.set_campaign_agency(conn, campaign_id, m["id"] if m else None)
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{campaign_id}", status_code=303)


@app.post("/campaign/{campaign_id}/phase")
def campaign_set_phase(campaign_id: int, phase: str = Form(...)):
    """Advance/set the campaign phase — a human-driven transition (the machine only
    proposes the next phase). Rejects a phase outside the creative timeline."""
    if not campaigns.workspace_enabled():
        return HTMLResponse("Not found", status_code=404)
    if phase not in campaigns.PHASES:
        return HTMLResponse("Unknown phase", status_code=400)
    conn = db.connect()
    try:
        db.set_campaign_phase(conn, campaign_id, phase)
    finally:
        conn.close()
    return RedirectResponse(f"/campaign/{campaign_id}", status_code=303)


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


# ── Production spine (ADR-0019): Directions + Creative Lock (operator actions). ───────
@app.post("/project/{project_id}/direction")
def project_direction(project_id: int, action: str = Form("add"), name: str = Form(""),
                      thesis: str = Form(""), direction_id: str = Form(""),
                      status: str = Form(""), reason: str = Form("")):
    """Directions — the creative territories. Add one (name + thesis: the hero element), or
    decide its fate (selected / rejected — a rejection carries its WHY, which is what
    Relationship Intelligence learns from)."""
    conn = db.connect()
    try:
        if db.get_project(conn, project_id) is None:
            return HTMLResponse("Project not found", status_code=404)
        if action == "add":
            production.add_direction(conn, db, project_id, name=name, thesis=thesis)
        elif action == "decide":
            production.decide_direction(conn, db, project_id, direction_id,
                                        status=status, reason=reason)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#directions", status_code=303)


@app.post("/project/{project_id}/creative-lock")
def project_creative_lock(project_id: int, action: str = Form("set")):
    """Creative Lock — the hinge of the lifecycle (ADR-0019). Ends the revision economy:
    changes after lock are scope/conform conversations; production spend is authorized."""
    conn = db.connect()
    try:
        if db.get_project(conn, project_id) is None:
            return HTMLResponse("Project not found", status_code=404)
        delivery = db.get_delivery(conn, project_id)
        if action == "clear":
            production.clear_creative_lock(conn, db, project_id)
        else:
            cur = current_version(delivery) or {}
            production.set_creative_lock(conn, db, project_id,
                                         version_n=cur.get("n") or 0)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#directions", status_code=303)


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
        _persist_upload(conn, safe_name, data)

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
    _persist_upload(conn, safe_name, data)
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
    # Unique, PERMANENT per-submission name (random suffix). The old "proj{id}-pending"
    # scheme reused one filename and — because the disk-existence check misses files that
    # live only in the durable DB mirror after a redeploy — a new submission overwrote the
    # previous version's blob under the same key, so v1/v2 ended up pointing at one file.
    safe_name = f"proj{project_id}-v{os.urandom(5).hex()}{safe_ext}"
    _persist_upload(conn, safe_name, data)
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
    # Publishing a version ALWAYS moves the ball to the client — the court is theirs now,
    # whatever it was before (fresh v1 from "In production", or a re-open after approval).
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
        # The taste gate is UNIVERSAL (operator feedback): every upload — even the operator's
        # own — lands as a pending submission FIRST, so nothing reaches the client until an
        # explicit "Publish to client" press. The operator reviews it on the console, then
        # publishes. "The machine proposes, Jon disposes" — for every version, no exceptions.
        _store_pending_submission(conn, project_id, data, file.filename, "Studio")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)


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


@app.post("/project/{project_id}/delivery/ship")
def delivery_ship(project_id: int):
    """Operator action: finalize + ship the delivery when it's READY (master approved,
    every deliverable uploaded + signed off) but hasn't shipped — e.g. after a reopen/
    un-ship, where nothing re-triggers the automatic finalize. Assembles the package and
    flips to Delivered (idempotent; ships only if genuinely ready)."""
    conn = db.connect()
    shipped = False
    try:
        shipped = _maybe_finalize_delivery(conn, project_id)
    finally:
        conn.close()
    flag = "" if shipped else "?ship=not_ready"
    return RedirectResponse(f"/project/{project_id}/delivery{flag}#delivery", status_code=303)


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
        view = _delivery_view(conn, project_id, selected_v=v, client_view=True)
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
                              body_text: str, exclude_email: str = "") -> None:
    """Composer-direction notification: email each assigned creator (with an email)
    when the client acts on their work — approved, or changes requested. Also used to
    broadcast a new assignment to the whole project crew. Closes the loop the review
    portal opened: the composer hears the verdict from us instead of Jon relaying it by
    hand. ``exclude_email`` skips one recipient (e.g. the just-assigned creator who has
    already had a tailored email). Best-effort, per creator, never raises. Runs in its
    own DB connection so it's safe to fire-and-forget off the request thread."""
    conn = db.connect()
    try:
        assignments = db.list_assignments(conn, project_id)
    finally:
        conn.close()
    if not mailer.mail_configured():
        return
    base = _public_base()
    seen = set()
    if exclude_email:
        seen.add(exclude_email.strip().lower())
    # Look up each creator's portal token so the email can carry their one link (courtesy:
    # the composer opens straight into their portal to see the notes / submit the next take).
    portal_by_talent = {}
    conn2 = db.connect()
    try:
        for a in assignments:
            tid = a["talent_id"] if "talent_id" in a.keys() else None
            if tid is not None:
                trow = db.get_talent(conn2, tid)
                tok = (trow["portal_token"] if trow is not None and "portal_token" in trow.keys()
                       else "") or ""
                if tok:
                    portal_by_talent[tid] = tok
    finally:
        conn2.close()
    for a in assignments:
        email = (a["talent_email"] or "").strip() if "talent_email" in a.keys() else ""
        if not email or email.lower() in seen:
            continue
        seen.add(email.lower())
        name = (a["talent_name"] or "there").strip() if "talent_name" in a.keys() else "there"
        tid = a["talent_id"] if "talent_id" in a.keys() else None
        text = f"Hi {name},\n\n{body_text}"
        tok = portal_by_talent.get(tid)
        if tok:
            text += f"\n\nOpen your portal — the feedback and your upload box are here:\n{base}/creator/{tok}"
        text += "\n\n— Chordential"
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
                # A non-finite timecode (inf/nan — anyone with the share token can
                # POST one) round-trips SQLite REAL and then 500s every template
                # that formats it (creator portal, delivery portal, console).
                # Guard once at the write site; negatives are equally meaningless.
                if t_seconds is not None and (
                        not math.isfinite(t_seconds) or t_seconds < 0):
                    t_seconds = None
            project = db.get_project(conn, project_id)
            delivery = db.get_delivery(conn, project_id)
            db.add_review_comment(
                conn, project_id, version=_current_version_tag(delivery),
                t_seconds=t_seconds, author=name, email=mail, body=body.strip(),
                kind="comment", parent_id=parent, verified=reviewer is not None,
            )
            verb = "replied" if parent is not None else "commented"
            # Session Room bus: the comment becomes an event everyone in the
            # room may see (client-side act; audience = all roles).
            db.add_project_event(
                conn, project_id, "comment", actor_role="client",
                actor_name=name, body=body.strip()[:200],
            )
            _notify_operator_review(
                project_id, project,
                title=f"{_campaign_label(project)} — new note",
                body=f"{name} {verb}: {body.strip()[:120]}",
            )
    finally:
        conn.close()
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


# --------------------------------------------------------------------------- #
# Session Room (Living OS P5) — the live layer over the delivery surfaces.
# One event bus (project_events), role-filtered SERVER-SIDE; presence is
# name + role only (council: never activity surveillance). Increment 1 covers
# the operator console + client portal; talent joins in increment 2. Polling
# transport for now — the endpoint shape (after=cursor) is SSE-compatible.
# --------------------------------------------------------------------------- #
_PRESENCE: dict = {}          # {project_id: {key: (name, role, ts)}} — in-process
_PRESENCE_TTL = 90            # seconds; single-worker deployment, honest scope


def _session_role(conn, project_id: int, k: str, r: str):
    """Resolve the caller's room role. A valid share/reviewer token → client;
    no token → operator (the login gate already protected the path)."""
    if k or r:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return None, ""
        return "client", ((reviewer or {}).get("name") or "Client")
    return "operator", "Studio"


@app.get("/project/{project_id}/session.json")
def session_room_poll(project_id: int, after: int = 0, k: str = "", r: str = ""):
    conn = db.connect()
    try:
        role, _name = _session_role(conn, project_id, k, r)
        if role is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        events = [
            {"id": e["id"], "kind": e["kind"], "role": e["actor_role"],
             "name": e["actor_name"], "body": e["body"], "at": e["created_at"]}
            for e in db.list_project_events(conn, project_id, role=role,
                                            after_id=after)
        ]
    finally:
        conn.close()
    import time as _t
    now = _t.time()
    room = _PRESENCE.get(project_id, {})
    alive = {kk: v for kk, v in room.items() if now - v[2] < _PRESENCE_TTL}
    _PRESENCE[project_id] = alive
    return {"events": events,
            "last": events[-1]["id"] if events else after,
            "presence": [{"name": v[0], "role": v[1]} for v in alive.values()]}


@app.post("/project/{project_id}/presence")
def session_room_presence(project_id: int, k: str = Form(""), r: str = Form(""),
                          name: str = Form("")):
    conn = db.connect()
    try:
        role, fallback = _session_role(conn, project_id, k, r)
    finally:
        conn.close()
    if role is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    import time as _t
    who = (name.strip() or fallback)[:40]
    _PRESENCE.setdefault(project_id, {})[f"{role}:{who}"] = (who, role, _t.time())
    return {"ok": True}


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


def _ready_to_deliver(delivery: dict, project) -> bool:
    """The gate to the full download (Option 1 model): the master is approved (Creative Lock),
    every scoped deliverable is UPLOADED, AND every uploaded derivative is SIGNED OFF by the
    client. The primary master IS the review version — approving it (the main creative approval)
    delivers + approves it; the derivatives (instrumental, cutdowns, verticals, stems) are the
    composer's uploads, each signed off one at a time. Only when all of that is true does the
    full package assemble and the download unlock — so a client can never download an
    incomplete or unapproved delivery."""
    if not production.creative_lock(delivery):            # master approved?
        return False
    if not delivery_completeness(project, delivery)["complete"]:   # everything uploaded?
        return False
    roll = db.asset_approval_rollup(delivery)             # every derivative signed off?
    return roll["total"] == 0 or roll["approved"] == roll["total"]


def _ensure_final_invoice_issued(conn, project_id: int) -> None:
    """When the package is finalized, raise the balance (Final) invoice as *Issued* so it is a
    real outstanding amount. Without this, the download gate treats a paid DEPOSIT as
    "paid in full" (the balance invoice is created lazily, so nothing shows outstanding) and
    the files unlock without the balance ever being paid — reported live. Idempotent; needs a
    stored proposal and a non-zero balance."""
    prow = db.get_project(conn, project_id)
    prop = db.proposal_for_project(conn, project_id)
    if prow is None or prop is None:
        return
    inv = next((i for i in db.list_invoices(conn, project_id)
                if (i["kind"] or "") == "Final"), None)
    if inv is None:
        new_id = db.insert_invoice(
            conn, project_id, prop["id"], _invoice_from_proposal_row(prow, prop, "Final"))
        inv = db.get_invoice(conn, new_id)
    if inv is None:
        return
    status = (inv["status"] or "").lower()
    if (inv["amount"] or 0) and status in ("", "draft"):
        db.update_invoice_status(conn, inv["id"], "Issued")


def _maybe_finalize_delivery(conn, project_id: int) -> bool:
    """Ship the delivery package + mark Delivered ONLY when the creative is approved (Creative
    Lock) AND every deliverable is uploaded + signed off. This is the SINGLE door to the full
    download; approving the master version alone never opens it. Returns True if it finalized."""
    delivery = db.get_delivery(conn, project_id)
    project = db.get_project(conn, project_id)
    if project is None or not production.creative_lock(delivery):
        return False
    if (delivery.get("state") or "") in ("Delivered", "Released"):
        _ensure_final_invoice_issued(conn, project_id)   # self-heal older Delivered deals
        return True
    if not _ready_to_deliver(delivery, project):
        return False
    try:
        _build_delivery_package(conn, project_id)
        db.update_delivery(conn, project_id, "state", "Delivered")
        # The balance is now owed — raise it so the download stays gated behind it, and EMAIL
        # the client their pay link automatically (reported live: the final invoice just sat
        # in the operator's queue). Sent once, here, on the delivery transition.
        _ensure_final_invoice_issued(conn, project_id)
        _fin = next((i for i in db.list_invoices(conn, project_id)
                     if (i["kind"] or "") == "Final"), None)
        if _fin is not None and (_fin["status"] or "").lower() not in ("paid", "settled"):
            try:
                _send_invoice_pay_link(conn, _fin["id"])
            except Exception:  # noqa: BLE001 — the auto-send never blocks delivery
                pass
        db.add_project_event(conn, project_id, "delivered", actor_role="operator",
                             actor_name="ChordOS",
                             body="All deliverables approved — delivery package assembled.")
        return True
    except Exception:  # noqa: BLE001
        return False


def _approve_version_core(conn, project_id: int, name: str, mail: str) -> str:
    """Record the client's approval of the current master version — this is the CREATIVE
    approval (Creative Lock), NOT final delivery. The full package ships only once every
    deliverable is also uploaded + signed off (``_maybe_finalize_delivery``), so a client can
    never download an incomplete package by approving the master alone. Reversible via
    /review/reopen. Returns the approved version tag."""
    delivery = db.get_delivery(conn, project_id)
    project = db.get_project(conn, project_id)
    approved_n = _current_version_tag(delivery)
    db.add_review_comment(
        conn, project_id, version=approved_n, author=name, email=mail,
        body=f"Approved v{approved_n} — creative locked.", kind="approval", verified=True)
    if not production.creative_lock(delivery):
        production.set_creative_lock(conn, db, project_id, version_n=int(approved_n or 0), by=name)
    versions = versions_list(delivery)
    if versions:
        versions[-1] = dict(versions[-1])
        versions[-1]["label"] = version_label(versions[-1]["n"], final=True)
        db.update_delivery(conn, project_id, "versions", versions)
        db.update_delivery(conn, project_id, "version_state", versions[-1]["label"])
    # Creative approved — but delivery stays LOCKED until every deliverable is signed off.
    db.update_delivery(conn, project_id, "state", "Approved")
    finalized = _maybe_finalize_delivery(conn, project_id)   # ships iff complete + all approved
    db.add_project_event(conn, project_id, "approval", actor_role="client", actor_name=name,
                         body=f"Approved v{approved_n} — creative locked.")
    remaining = "" if finalized else " Delivery unlocks once every deliverable is uploaded and signed off."
    _notify_operator_review(
        project_id, project, title=f"{_campaign_label(project)} — creative approved by {name}",
        body=f"v{approved_n} creative approved.{remaining}")
    campaign = _campaign_label(project)
    signals.fire_and_forget(
        _notify_assigned_creators, project_id, project, subject=f"Creative approved — {campaign}",
        body_text=(f"Good news — the client approved the creative on {campaign}. Thank you. "
                   "We'll finish preparing the deliverables for sign-off."))
    return approved_n


def _rehydrate_delivery_media(conn, project_id: int) -> int:
    """Restore a project's delivery media (asset + version files) from the durable DB blob
    mirror back to disk when the ephemeral disk was wiped — so a package (re)build actually
    contains the audio instead of README placeholders. Returns the count restored."""
    delivery = db.get_delivery(conn, project_id)
    names = set()
    for a in (delivery.get("assets") or []):
        if a.get("filename"):
            names.add(os.path.basename(a["filename"]))
    for v in (delivery.get("versions") or []):
        if v.get("filename"):
            names.add(os.path.basename(v["filename"]))
    pv = delivery.get("pending_version") or {}
    if pv.get("filename"):
        names.add(os.path.basename(pv["filename"]))
    restored = 0
    for base in names:
        if not base or os.path.exists(os.path.join(UPLOAD_DIR, base)):
            continue
        blob = db.get_media_blob(conn, base)
        if blob is None:
            continue
        try:
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            with open(os.path.join(UPLOAD_DIR, base), "wb") as fh:
                fh.write(blob[0])
            restored += 1
        except OSError:
            pass
    return restored


def _build_delivery_package(conn, project_id: int) -> Optional[dict]:
    """Delivery automation (Phase 3): assemble the delivery ZIP for a project and
    store its descriptor + checklist on ``delivery_json``. Returns the descriptor
    (or None if the project is gone). Deterministic + best-effort: the stdlib ZIP +
    docs always build; audio conversion is attempted only if ffmpeg is available.

    Durable across ephemeral-disk wipes: rehydrates the source media from the DB mirror
    before zipping, and mirrors the built ZIP itself into the blob store so the download
    survives a redeploy.

    Stored shape::

        delivery_json['delivery_zip']       = {filename, url, built_at}
        delivery_json['delivery_checklist'] = [item, …]   (founder's payoff list)
    """
    row = db.get_project(conn, project_id)
    if row is None:
        return None
    _rehydrate_delivery_media(conn, project_id)      # source audio back on disk before zipping
    assignments = db.list_assignments(conn, project_id)
    delivery = db.get_delivery(conn, project_id)
    pkg = build_delivery_zip(row, assignments, delivery, UPLOAD_DIR)
    # Mirror the built ZIP for durability (the same DB blob store uploads use).
    try:
        with open(os.path.join(UPLOAD_DIR, os.path.basename(pkg["filename"])), "rb") as fh:
            db.save_media_blob(conn, os.path.basename(pkg["filename"]), fh.read(), "application/zip")
    except (OSError, KeyError):
        pass
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
        # Identity gate (ADR-0020): the client can approve from their OWN share link —
        # a captured name + email is intent enough (ESIGN/UETA-sufficient), and it's their
        # durable token. A verified reviewer link is the STRONGER path (locked roster
        # identity), not the only one. Either way the sign-off records who + when.
        if reviewer is not None:
            name = (reviewer.get("name") or "").strip()
            mail = (reviewer.get("email") or "").strip()
        else:
            name, mail = _reviewer_identity(request, author, email)
        if not (name and mail):
            return _review_redirect(project_id, k, r=r, flag="identify")
        # Approving the master version records the CREATIVE approval (Creative Lock). It no
        # longer ships an incomplete package — the full download unlocks only when every
        # deliverable is uploaded + signed off (_maybe_finalize_delivery). So there's no
        # partial-opt-in to gate here; the client can always approve the creative.
        _approve_version_core(conn, project_id, name, mail)   # notifies creators + operator
    finally:
        conn.close()
    return _review_redirect(project_id, k, name=name, email=mail, r=r)


@app.post("/project/{project_id}/review/reopen")
def review_reopen(request: Request, project_id: int, k: str = Form(""), r: str = Form("")):
    """Un-approve / reopen — approval is NOT a one-way door (operator feedback). Clears the
    Creative Lock, drops the FINAL label back to its round label, and returns the project to
    'In review'. Available to the operator (console, no token) or the client (their link)."""
    conn = db.connect()
    try:
        if k or r:                                    # a client action — validate the token
            ok, _rev = _access_ok(conn, project_id, k, r)
            if not ok:
                return HTMLResponse("Not found", status_code=404)
        row = db.get_project(conn, project_id)
        if row is None:
            return HTMLResponse("Project not found", status_code=404)
        delivery = db.get_delivery(conn, project_id)
        state = (delivery.get("state") or "").strip()
        if state in ("Delivered", "Released"):
            # UN-SHIP: the package went out, but pull it back to the DELIVERABLE SIGN-OFF
            # stage — the master stays approved and every prior per-deliverable sign-off is
            # preserved; only the shipped package + the client download are undone. So the
            # operator (or client) can revisit a single deliverable without redoing the master.
            db.update_delivery(conn, project_id, "state", "Approved")
            db.update_delivery(conn, project_id, "download_unlocked", False)
            db.update_delivery(conn, project_id, "delivery_zip", None)
            db.add_project_event(conn, project_id, "reopened", actor_role="operator",
                                 actor_name="Studio",
                                 body="Delivery reopened — back to deliverable sign-off.")
        else:
            # Reopen the CREATIVE (master): back to review, master un-approved.
            production.clear_creative_lock(conn, db, project_id)
            versions = versions_list(delivery)
            if versions:
                versions[-1] = dict(versions[-1])
                versions[-1]["label"] = version_label(versions[-1]["n"], final=False)
                db.update_delivery(conn, project_id, "versions", versions)
                db.update_delivery(conn, project_id, "version_state", versions[-1]["label"])
            db.update_delivery(conn, project_id, "state", "In review")
            db.update_delivery(conn, project_id, "download_unlocked", False)
            db.add_project_event(conn, project_id, "reopened", actor_role="operator",
                                 actor_name="Studio", body="Approval reopened — back in review.")
    finally:
        conn.close()
    if k or r:
        return _review_redirect(project_id, k, r=r)
    return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)


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


@app.post("/project/{project_id}/delivery/asset/publish")
def delivery_publish_asset(project_id: int, filename: str = Form(""),
                           action: str = Form("publish")):
    """Jon's disposition of a creator's pending DELIVERABLE (stems, cutdowns,
    verticals): publish it into the client-visible assets, or discard it. The same
    gate the master gets — uniform, per the EP review (unvetted stems on delivery
    night were the hole)."""
    conn = db.connect()
    try:
        delivery = db.get_delivery(conn, project_id)
        pending = list(delivery.get("pending_assets") or [])
        hit = next((a for a in pending if a.get("filename") == filename), None)
        if hit is None:
            return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)
        pending = [a for a in pending if a.get("filename") != filename]
        db.update_delivery(conn, project_id, "pending_assets", pending)
        if action == "discard":
            db.add_update(conn, project_id,
                          f"Sent back the pending deliverable '{hit.get('label')}'.")
        else:
            assets = list(delivery.get("assets") or [])
            assets.append({"label": hit.get("label"), "url": hit.get("url"),
                           "filename": hit.get("filename"), "kind": hit.get("kind")})
            db.update_delivery(conn, project_id, "assets", assets)
            db.add_update(conn, project_id,
                          f"Published '{hit.get('label')}' — ready for client sign-off.")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#assets", status_code=303)


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
                # The client's own workspace contact — the person the version is FOR — is
                # notified with their durable link, not just the reviewer roster.
                client_email = client_name = client_token = ""
                opp = db.get_opportunity(conn, project["opp_id"]) if project["opp_id"] else None
                if opp is not None:
                    client_email = (opp["contact_email"] or "").strip()
                    client_name = (opp["contact_name"] or "").strip()
                    client_token = db.ensure_share_token(conn, opp["id"])
    finally:
        conn.close()
    # Client-direction notification only on a real publish — off the request thread.
    if result is not None:
        label, campaign = result
        signals.fire_and_forget(
            _notify_reviewers_new_version, project_id, campaign, label, reviewers)
        if client_email:
            portal_url = f"{_public_base()}/project/{project_id}/delivery-portal?k={client_token}"
            signals.fire_and_forget(
                _notify_client_new_version, client_email, client_name, campaign, label,
                client_token, portal_url)
    return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)


def _notify_client_new_version(email: str, name: str, campaign: str, label: str, token: str,
                               portal_url: str = ""):
    """Email the client that a new version is waiting — pointing straight at the listening
    room (the delivery portal) where they play it, comment, and approve. The review IS the
    action, so the link goes to the review surface, not the workspace shell."""
    if not (mailer.mail_configured() and email):
        return
    base = _public_base()
    who = (name or "there").strip()
    link = portal_url or f"{base}/workspace/{token}"
    text = (f"Hi {who},\n\n{label} of {campaign} is ready for you to hear. Open the listening "
            f"room to play it, leave timecoded notes, or approve it:\n\n"
            f"{link}\n\n— Chordential")
    try:
        mailer.send_email(email, f"A new version is ready — {campaign}", text,
                          html=mailer.branded_html(base, text))
    except Exception:  # noqa: BLE001 — best-effort
        pass


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
        # ADR-0019: the round LEDGER behind the counter — which version, who, what they said
        # (post-lock rounds are stamped so scope conversations have a record to stand on).
        production.log_round(conn, db, project_id,
                             version=_current_version_tag(delivery), by=name, note=note_text)
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
    r: str = Form(""), author: str = Form(""), email: str = Form(""),
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
        # Per-deliverable sign-off is open to the identified client on their own share link
        # (operator feedback: the client approves each itemized deliverable before the full
        # download unlocks) — same captured-intent rule as the whole-version Approve. A
        # verified reviewer keeps their locked roster identity.
        if reviewer is not None:
            name = (reviewer.get("name") or "").strip()
            mail = (reviewer.get("email") or "").strip()
        else:
            name, mail = _reviewer_identity(request, author, email)
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
            db.add_project_event(conn, project_id, kind.replace("asset_", "asset-"),
                                 actor_role="client", actor_name=name, body=body[:200])
            # When this sign-off was the LAST one needed (creative locked + every deliverable
            # uploaded + approved), the full package assembles + download unlocks. Approving
            # one deliverable never ships early — only the last approval opens the door.
            if action != "changes":
                _maybe_finalize_delivery(conn, project_id)
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


def _payment_request_email(kind: str, amount: float, client: str, need: str,
                           contact_name: str, pay_url: str) -> dict:
    """A branded 'here's your invoice — pay securely' email for the client."""
    first = (contact_name or "").strip().split()[0] if contact_name.strip() else ""
    greeting = f"Hi {first}," if first else "Hi there,"
    amt = f"${amount:,.0f}" if amount else "your balance"
    label = (kind or "Payment").strip()
    is_final = label.lower().startswith("fin")
    lead = ("Your project is delivered and the final balance is due to release your files."
            if is_final else
            "Here's your deposit invoice to get production underway.")
    tail = ("The moment it's in, your full delivery package unlocks for download."
            if is_final else "Your deposit reserves the team and starts the work.")
    body = (
        f"{greeting}\n\n"
        f"{lead}\n\n"
        f"  {label} due:  {amt}\n"
        f"  Project:      {need or 'your campaign'}\n\n"
        f"Pay securely here:\n{pay_url}\n\n"
        f"{tail}\n\n"
        "— Jon, Chordential")
    subject = f"{label} due ({amt}) — {need or 'your campaign'}"
    return {"subject": subject, "body": body}


def _send_invoice_pay_link(conn, invoice_id: int) -> str:
    """Email the CLIENT a secure pay link for one invoice. Issues the invoice if it's still a
    draft, then sends a branded payment request to the opportunity's contact with a link to
    their token-gated portal (where the Pay button opens a fresh checkout — a hosted-checkout
    URL can expire, the portal never does). Returns a status: 'sent' | 'no_email' | 'no_mail'
    | 'error'. Shared by the operator button AND the automatic send on delivery."""
    inv = db.get_invoice(conn, invoice_id)
    if inv is None or not inv["project_id"]:
        return "error"
    pid = inv["project_id"]
    if (inv["status"] or "").lower() in ("", "draft"):
        ref = get_payment_provider().create_checkout(inv)
        db.update_invoice_status(conn, invoice_id, "Issued", external_ref=ref)
        inv = db.get_invoice(conn, invoice_id)
    prow = db.get_project(conn, pid)
    opp = db.get_opportunity(conn, prow["opp_id"]) if prow and prow["opp_id"] else None
    contact_email = (opp["contact_email"] if opp is not None
                     and "contact_email" in opp.keys() else "") or ""
    if not contact_email:
        return "no_email"
    if not mailer.mail_configured():
        return "no_mail"
    base = _public_base()
    token = db.ensure_project_share_token(conn, pid)
    pay_url = f"{base}{_client_portal_url(pid, token)}"
    contact_name = (opp["contact_name"] if opp is not None
                    and "contact_name" in opp.keys() else "") or ""
    msg = _payment_request_email(inv["kind"], inv["amount"] or 0,
                                 (prow["client"] if prow else "") or "",
                                 (prow["need"] if prow else "") or "", contact_name, pay_url)
    try:
        mailer.send_email(contact_email, msg["subject"], msg["body"],
                          html=mailer.branded_html(base, msg["body"]))
        db.add_update(conn, pid, f"{inv['kind']} pay link emailed to {contact_email}.",
                      "invoice")
        return "sent"
    except Exception:  # noqa: BLE001
        return "error"


@app.post("/invoice/{invoice_id}/send-pay-link")
def invoice_send_pay_link(invoice_id: int):
    """Operator action: email the client a secure pay link for this invoice — so the balance
    actually reaches them instead of sitting in the queue (reported live). Best-effort;
    bounces back with a flash on the proposal page."""
    conn = db.connect()
    try:
        inv = db.get_invoice(conn, invoice_id)
        if inv is None or not inv["project_id"]:
            return RedirectResponse("/projects", status_code=303)
        pid = inv["project_id"]
        flag = _send_invoice_pay_link(conn, invoice_id)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{pid}/proposal?pay={flag}", status_code=303)


def _client_portal_url(project_id: int, k: str, extra: str = "") -> str:
    q = f"?k={k}" if k else ""
    if extra:
        q = (q + "&" if q else "?") + extra
    return f"/project/{project_id}/delivery-portal{q}"


@app.post("/project/{project_id}/pay")
def client_pay(project_id: int, k: str = Form(""), r: str = Form(""), kind: str = Form("final")):
    """Client-facing, token-gated: begin payment for the deposit or final invoice. Ensures the
    invoice exists, opens a provider checkout, and — with Stripe configured — redirects the
    client to the HOSTED checkout page. With the unconfigured Null provider it bounces back
    with an honest 'online payment isn't enabled yet' note (the studio can still collect and
    mark it paid). No admin gate: access is by the client's own share token."""
    conn = db.connect()
    kind = "Deposit" if kind.lower().startswith("dep") else "Final"
    # Where to bounce back on the honest null-provider fallback / errors: the deposit is
    # paid from the workspace, the final from the delivery portal.
    def _back(flag):
        if kind == "Deposit":
            prow0 = db.get_project(conn, project_id)
            if prow0 is not None and prow0["opp_id"]:
                return f"/workspace/{db.ensure_share_token(conn, prow0['opp_id'])}?{flag}"
        return _client_portal_url(project_id, k, flag)
    try:
        ok, _rev = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        prow = db.get_project(conn, project_id)
        prop = db.proposal_for_project(conn, project_id)
        if prow is None or prop is None:
            return RedirectResponse(_back("pay=error"), status_code=303)
        if not db.has_invoice(conn, project_id, kind):
            db.insert_invoice(conn, project_id, prop["id"], _invoice_from_proposal_row(prow, prop, kind))
        invoice = next((i for i in db.list_invoices(conn, project_id)
                        if (i["kind"] or "") == kind), None)
        if invoice is None:
            return RedirectResponse(_back("pay=error"), status_code=303)
        if (invoice["status"] or "").lower() in ("paid", "settled"):
            return RedirectResponse(_back("pay=already"), status_code=303)
        try:
            ref = get_payment_provider().create_checkout(invoice) or ""
        except Exception:  # noqa: BLE001 — never 500 the payer
            ref = ""
        if ref.startswith("http"):                     # Stripe hosted checkout
            db.update_invoice_status(conn, invoice["id"], "Issued", external_ref=ref)
            db.add_update(conn, project_id, f"{kind} checkout opened by the client.", "invoice")
            return RedirectResponse(ref, status_code=303)
        # Null / unconfigured provider — be honest, don't fake a charge.
        return RedirectResponse(_back("pay=unavailable"), status_code=303)
    finally:
        conn.close()


def _payment_receipt_email(kind: str, amount: float, client: str, need: str,
                           contact_name: str, workspace_url: str, paid_at: str) -> dict:
    """A clean, branded receipt for the client when their payment settles."""
    first = (contact_name or "").strip().split()[0] if contact_name.strip() else ""
    greeting = f"Hi {first}," if first else "Hi there,"
    amt = f"${amount:,.0f}" if amount else "your payment"
    label = (kind or "Payment").strip()
    date = (paid_at or "")[:10]
    tail = ("Your deposit is in and we're getting production underway — you'll hear from us "
            "at your first creative milestone."
            if label.lower().startswith("dep") else
            "Your balance is settled and your final files are unlocked in your workspace.")
    body = (
        f"{greeting}\n\n"
        f"Thank you — we've received your {label.lower()} payment. This is your receipt.\n\n"
        f"  Payment:  {label}\n"
        f"  Amount:   {amt}\n"
        f"  Project:  {need or 'your campaign'}\n"
        + (f"  Date:     {date}\n" if date else "")
        + f"\n{tail}\n\n"
        + (f"Everything for your campaign lives in your workspace:\n{workspace_url}\n\n"
           if workspace_url else "")
        + "— Jon, Chordential"
    )
    subject = f"Receipt — {label} payment received ({amt})"
    return {"subject": subject, "body": body}


def _notify_payment_settled(conn, inv, pid: int) -> None:
    """Best-effort notifications when a payment settles: a receipt to the client and a phone
    alert to the operator. Never raises — a notification failure must not undo the payment."""
    try:
        project = db.get_project(conn, pid)
        opp = (db.get_opportunity(conn, project["opp_id"])
               if project is not None and project["opp_id"] else None)
        kind = inv["kind"] or "Payment"
        amount = inv["amount"] or 0
        client = (project["client"] if project is not None else "") or (
            opp["client"] if opp is not None else "a client")
        need = project["need"] if project is not None else ""
        # Operator phone push — the immediate "you got paid" alert.
        signals.fire_and_forget(signals.notify_payment_received, client, kind,
                                f"${amount:,.0f}" if amount else "")
        # Client receipt email.
        contact_email = (opp["contact_email"] if opp is not None
                         and "contact_email" in opp.keys() else "") or ""
        if contact_email and mailer.mail_configured():
            base = _public_base()
            token = db.ensure_share_token(conn, opp["id"]) if opp is not None else ""
            contact_name = (opp["contact_name"] if opp is not None
                            and "contact_name" in opp.keys() else "") or ""
            receipt = _payment_receipt_email(
                kind, amount, client, need, contact_name,
                f"{base}/workspace/{token}" if token else "", inv["paid_at"] or "")
            mailer.send_email(contact_email, receipt["subject"], receipt["body"],
                              html=mailer.branded_html(base, receipt["body"]))
    except Exception:  # noqa: BLE001 — notifications are best-effort
        pass


def _apply_invoice_payment(conn, invoice_id: int, external_ref: str = "") -> bool:
    """Mark an invoice Paid and apply its side effects — unlock the client's downloads
    (Final) + queue crew payouts + notify (client receipt, operator alert) — exactly once.
    Idempotent: a no-op if already paid, so the Stripe success-return and the webhook can
    BOTH fire without double-applying."""
    inv = db.get_invoice(conn, invoice_id)
    if inv is None or not inv["project_id"]:
        return False
    if (inv["status"] or "").lower() in ("paid", "settled"):
        return False
    pid = inv["project_id"]
    db.update_invoice_status(conn, inv["id"], "Paid", external_ref=external_ref or None)
    if (inv["kind"] or "") == "Final":
        db.update_delivery(conn, pid, "download_unlocked", True)
    db.ensure_project_payouts(conn, pid)
    db.add_update(conn, pid, f"{inv['kind']} invoice paid — thank you.", "invoice")
    # Re-read so the receipt carries the stamped paid_at.
    _notify_payment_settled(conn, db.get_invoice(conn, inv["id"]) or inv, pid)
    return True


@app.get("/pay/return", response_class=HTMLResponse)
def pay_return(request: Request, invoice: int = 0):
    """Stripe ``success_url`` target — the payer lands here after a COMPLETED checkout. Applies
    the payment (idempotent — the signature-verified webhook may have beaten the browser here)
    and returns to the workspace/portal with a thank-you."""
    conn = db.connect()
    dest = "/"
    try:
        inv = db.get_invoice(conn, invoice) if invoice else None
        if inv is not None and inv["project_id"]:
            _apply_invoice_payment(conn, invoice)
            pid = inv["project_id"]
            prow = db.get_project(conn, pid)
            if inv["kind"] == "Final":
                dest = _client_portal_url(pid, db.ensure_project_share_token(conn, pid) or "", "paid=1")
            elif prow is not None and prow["opp_id"]:
                dest = f"/workspace/{db.ensure_share_token(conn, prow['opp_id'])}?paid=1"
    finally:
        conn.close()
    return RedirectResponse(dest, status_code=303)


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Stripe payment webhook — the AUTHORITATIVE, signature-verified confirmation of a
    completed payment, independent of whether the payer's browser ever returns. Verifies the
    ``Stripe-Signature`` via the provider (``STRIPE_WEBHOOK_SECRET``), and on a captured
    payment marks the invoice Paid + unlocks downloads + queues payouts, idempotently.
    Bypasses the admin gate (Stripe posts server-to-server) — the signature IS the auth."""
    body = await request.body()
    sig = (request.headers.get("stripe-signature")
           or request.headers.get("Stripe-Signature") or "")
    try:
        event = get_payment_provider().handle_webhook({"body": body, "signature": sig}) or {}
    except Exception:  # noqa: BLE001 — bad signature / malformed body → 400, never 500
        return JSONResponse({"ok": False, "error": "invalid"}, status_code=400)
    inv_id = event.get("invoice_id")
    applied = False
    if inv_id and (event.get("status") or "").lower() == "paid":
        conn = db.connect()
        try:
            applied = _apply_invoice_payment(conn, int(inv_id), event.get("external_ref") or "")
        finally:
            conn.close()
    return JSONResponse({"ok": True, "applied": applied})


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
@app.get("/queue", response_class=HTMLResponse)
def disposition_queue(request: Request):
    """The Disposition Queue — every pending founder decision, one ranked surface.
    Pure aggregation (queue.py) over existing decision routes; the queue renders
    and links, the decision buttons stay where they live. Machine proposes, the
    operator disposes — here, ergonomically."""
    conn = db.connect()
    try:
        view = queue_mod.queue_view(conn, db)
    finally:
        conn.close()
    return render(request, "queue.html", nav="queue", **view)


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


# --------------------------------------------------------------------------- #
# Discovery Call Simulator — practice against buyer personas; the objection
# library learns from real transcripts (see simulator.py). Admin-gated.
# --------------------------------------------------------------------------- #
@app.get("/simulator", response_class=HTMLResponse)
def simulator_home(request: Request):
    conn = db.connect()
    try:
        db.init_db(conn)
        simulator.seed_objections(conn)      # idempotent; inserts only what's missing
        sessions = db.list_sim_sessions(conn)
        proposed = db.list_objections(conn, status="proposed")
        confirmed = db.list_objections(conn, status="confirmed")
        return render(request, "simulator.html", nav="simulator",
                      personas=simulator.PERSONAS, sessions=sessions,
                      n_confirmed=len(confirmed), n_proposed=len(proposed),
                      ai_on=simulator.ai_available())
    finally:
        conn.close()


@app.post("/simulator/start")
def simulator_start(persona: str = Form(...)):
    if persona not in simulator.PERSONAS:
        return RedirectResponse("/simulator", status_code=303)
    conn = db.connect()
    try:
        db.init_db(conn)
        simulator.seed_objections(conn)
        mode = "ai" if simulator.ai_available() else "scripted"
        sid = db.create_sim_session(conn, persona=persona, mode=mode)
        opening = simulator.PERSONAS[persona]["opening"]
        db.update_sim_session(conn, sid, transcript_json=json.dumps(
            [{"who": "buyer", "text": opening}]))
        return RedirectResponse(f"/simulator/{sid}", status_code=303)
    finally:
        conn.close()


@app.get("/simulator/library", response_class=HTMLResponse)
def simulator_library(request: Request):
    conn = db.connect()
    try:
        db.init_db(conn)
        simulator.seed_objections(conn)
        rows = db.list_objections(conn)
        by_family = {}
        for r in rows:
            by_family.setdefault(r["family"], []).append(r)
        return render(request, "simulator_library.html", nav="simulator",
                      by_family=by_family, families=simulator.FAMILIES)
    finally:
        conn.close()


@app.post("/simulator/library/{objection_id}/status")
def simulator_library_status(objection_id: int, status: str = Form(...)):
    conn = db.connect()
    try:
        db.set_objection_status(conn, objection_id, status)
        return RedirectResponse("/simulator/library", status_code=303)
    finally:
        conn.close()


@app.get("/simulator/{session_id}", response_class=HTMLResponse)
def simulator_session(request: Request, session_id: int):
    conn = db.connect()
    try:
        s = db.get_sim_session(conn, session_id)
        if s is None:
            return RedirectResponse("/simulator", status_code=303)
        transcript = json.loads(s["transcript_json"] or "[]")
        scorecard = json.loads(s["scorecard_json"]) if s["scorecard_json"] else None
        coaching = {}
        if scorecard and scorecard.get("coaching"):
            coaching = {c["idx"]: c for c in scorecard["coaching"]}
        return render(request, "simulator_session.html", nav="simulator",
                      s=s, persona=simulator.PERSONAS.get(s["persona"], {}),
                      transcript=transcript, scorecard=scorecard, coaching=coaching)
    finally:
        conn.close()


@app.post("/simulator/{session_id}/say")
def simulator_say(session_id: int, text: str = Form(...)):
    conn = db.connect()
    try:
        s = db.get_sim_session(conn, session_id)
        if s is None or s["status"] != "live" or not text.strip():
            return RedirectResponse(f"/simulator/{session_id}", status_code=303)
        transcript = json.loads(s["transcript_json"] or "[]")
        transcript.append({"who": "seller", "text": text.strip()})
        db.update_sim_session(conn, session_id, transcript_json=json.dumps(transcript))
        s = db.get_sim_session(conn, session_id)
        reply = simulator.buyer_reply(conn, s)
        buyer_turn = {"who": "buyer", "text": reply["text"]}
        if reply.get("objection_id"):
            buyer_turn["objection_id"] = reply["objection_id"]
        transcript.append(buyer_turn)
        used = json.loads(s["objections_used"] or "[]")
        if reply.get("objection_id"):
            used.append(reply["objection_id"])
        db.update_sim_session(conn, session_id, transcript_json=json.dumps(transcript),
                              objections_used=json.dumps(used))
        return RedirectResponse(f"/simulator/{session_id}", status_code=303)
    finally:
        conn.close()


@app.post("/simulator/{session_id}/end")
def simulator_end(session_id: int):
    conn = db.connect()
    try:
        s = db.get_sim_session(conn, session_id)
        if s is None:
            return RedirectResponse("/simulator", status_code=303)
        transcript = json.loads(s["transcript_json"] or "[]")
        used = json.loads(s["objections_used"] or "[]")
        card = simulator.grade(transcript, used)
        card["coaching"] = simulator.coach_turns(conn, transcript)
        from datetime import datetime, timezone
        db.update_sim_session(conn, session_id, status="ended",
                              scorecard_json=json.dumps(card),
                              ended_at=datetime.now(timezone.utc).isoformat())
        return RedirectResponse(f"/simulator/{session_id}", status_code=303)
    finally:
        conn.close()


def main() -> None:  # console entry point
    import uvicorn

    host = os.environ.get("CHORDENTIAL_HOST", "127.0.0.1")
    port = int(os.environ.get("CHORDENTIAL_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
