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
from starlette.middleware.gzip import GZipMiddleware

from ..estimation import ROLE_RATES, stated_length
from ..storage import get_object_store, storage_status
from .. import mailer
from .. import recruiting
from ..models import MusicDiscipline, Opportunity
from ..payments import get_payment_provider
from ..proposals import build_proposal
from ..capabilities import (
    build_capabilities_doc, default_toggles, quote_band as capabilities_quote_band,
)
from ..delivery import (
    brief_rollup, build_clearance_certificate, build_cue_sheet,
    build_manifest, build_timeline, current_version,
    delivery_completeness,
    license_confirmation, merge_license, merge_signatory, reconcile_brief,
    revision_status, scoped_deliverables, seed_brief, version_label,
    versions_list, version_name,
    ASSIGNABLE_FOLDERS, BRIEF_FIELDS, CONTENT_ID_HONEST, DELIVERY_STATES, VERSION_STATES,
)
from ..talent import Talent, normalize_url, profile_completeness
from ..matching import match_talent
from . import (
    campaign_intake, campaign_intelligence, campaigns, commercial, db, decision_makers,
    directory_crawl, directory_parsers, discovery,
    enrichment, intelligence, kickoff, meeting_scheduler, meetings_service,
    music_opportunity, next_action, opportunity_signals, outreach_engine, production, queue as queue_mod, relationships,
    scheduler, seed, signals, simulator, sources, triage, webpush, workspace,
)
from .buyer_intel import assess_relationship, days_since
from .estimate import estimate_for
from .evaluate import evaluate
from .filters import displayurl, money, pct, slug
from . import uploads
# Imported back under the names the routes below already use. ADR-0044: the helper
# layer moved OUT of this file so /opportunity and /project can follow it; importing
# the names back keeps the move a pure relocation, with no edit inside any handler.
from .billing import (
    _apply_invoice_payment, _client_portal_url, _ensure_final_invoice_issued,
    _invoice_from_proposal_row, _proposal_from_row, _send_invoice_pay_link,
)
from .delivery_ops import (
    _approve_version_core, _build_delivery_package, _campaign_label,
    _current_version_tag, _gate_banner, _maybe_finalize_delivery,
    _notify_assigned_creators, _notify_operator_review,
)
from .opportunity_ops import (
    _brief_ci_context, _buyer_context, _ensure_project_for_opp,
    _load, _quote_band_for, _reconcile_opp_status, _to_utc_iso,
)
from .uploads import (
    _AUDIO_EXTS, _CUT_MIRROR_BYTES, _persist_upload, _store_pending_submission,
)
from .shell import (
    ADMIN_COOKIE, admin_authed as _admin_authed, admin_cookie_value as _admin_cookie_value,
    admin_secret as _admin_secret,
)
from .agencies_routes import _profile_from_row, router as agencies_router
from .discovery_routes import router as discovery_router
from .talent_routes import _parse_rate, router as talent_router
from .opportunity_routes import router as opportunity_router
from .public import router as public_router

_HERE = os.path.dirname(__file__)
# ADR-0044: created in shell.py so a route module can import it without importing
# app.py (which imports the route modules). Everything below still decorates THIS
# object — the filters and globals did not move.
from .shell import (
    public_base as _public_base, render, safe_local as _safe_local, templates,
)  # noqa: E402


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

# Every uploaded file — founder samples, client picture cuts, masters, stems. Path is
# overridable (CHORDENTIAL_UPLOAD_DIR) with a module-relative default; created on
# import so the upload + serve routes can rely on it existing.
# NOTE (persistence): the module-relative default lives INSIDE the installed package,
# which on Render is rebuilt every deploy — anything written there is gone on the next
# push. Production must point this at the persistent disk (render.yaml sets
# /var/data/uploads). That disk is also single-attach, so it blocks the blue-green
# cutover: durable, deploy-independent storage needs object storage (S3/R2).
# Resolved HERE, at app-import time, from `uploads.upload_dir()` — the routes below
# and a dozen test modules read `app.UPLOAD_DIR`, and those tests set the env var and
# then reload `app`, so the value has to be recomputed by this module's own execution.
UPLOAD_DIR = uploads.upload_dir()

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

# Phase 2 (The Picture): the client's cut. Range streaming is served by the
# existing /uploads route (FileResponse handles Range — Safari requires it).
# Size policy is ADR-0026: hard cap per cut; DB-mirror only under the threshold.
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
_CUT_MAX_BYTES = int(os.environ.get("CHORDENTIAL_CUT_MAX_MB", "512")) * 1024 * 1024
# A composer's submitted take / deliverable (audio-weight, occasionally a video mix)
# rides the same chunked cap — token-gated routes must never buffer an unbounded body.
_SUBMISSION_MAX_BYTES = int(os.environ.get("CHORDENTIAL_SUBMISSION_MAX_MB", "512")) * 1024 * 1024



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
    # ADR-0043: say where client media is going, at every boot. "We never actually
    # turned object storage on" must not be something discovered by losing a master,
    # and a half-configured switch (CHORDENTIAL_STORAGE=s3 with a missing key) falls
    # back to disk — silently, unless it announces itself here.
    _st = storage_status(UPLOAD_DIR)
    if _st["misconfigured"]:
        print(f"[storage] WARNING: CHORDENTIAL_STORAGE={_st['requested']} was requested "
              f"but the bucket is not fully configured — falling back to the LOCAL disk "
              f"at {UPLOAD_DIR}. Uploads are NOT durable.", flush=True)
    elif not _st["durable"]:
        print(f"[storage] local disk at {UPLOAD_DIR} — not durable across a disk "
              f"removal; set CHORDENTIAL_STORAGE=s3 before the Postgres cutover.",
              flush=True)
    else:
        print("[storage] object storage active — uploads are durable.", flush=True)
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


class SelectiveGZip:
    """GZip for text, and strictly nothing else.

    Starlette's GZipMiddleware compresses by size alone: it has no notion of Range
    requests, so it will happily gzip a 206 body while leaving ``content-range``
    describing the *uncompressed* extent — the response then contradicts itself and
    the client cannot assemble the file. Every audio and video element in the client
    delivery portal seeks through exactly those range requests, so that is not a
    theoretical concern.

    Two bypasses, both delegating to the raw app: a request carrying ``Range``, and
    a path whose extension is already-compressed media (where gzip buys nothing and
    costs CPU on every byte of a 512 MB master).
    """

    _ALREADY_COMPRESSED = (
        ".mp4", ".webm", ".mov", ".m4v", ".mp3", ".wav", ".m4a", ".aac", ".ogg",
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".ico",
        ".zip", ".gz", ".woff", ".woff2", ".pdf",
    )

    def __init__(self, app, minimum_size: int = 1024):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        if any(k == b"range" for k, _ in scope.get("headers") or ()):
            return await self.app(scope, receive, send)
        if scope.get("path", "").lower().endswith(self._ALREADY_COMPRESSED):
            return await self.app(scope, receive, send)
        return await self.gzip(scope, receive, send)


app = FastAPI(title="Chordential — Procurement OS", lifespan=lifespan)
# Nothing was encoded before this: the vendored three.js build (~594 KB) and the
# largest templates (~107 KB) went out raw over whatever connection the visitor had.
# Text compresses ~4x here; media does not, and must not (see SelectiveGZip).
app.add_middleware(SelectiveGZip, minimum_size=1024)
app.mount("/static", StaticFiles(directory=os.path.join(_HERE, "static")), name="static")
# Public front-of-house site (magazine/brochure surface + inbound intake), at the
# site root (/). Shares this app + DB; renders its own standalone layout, no internal nav.
# ADR-0044: /agencies lives in its own module. Included here so registration
# order — and therefore which handler answers a URL — is unchanged.
app.include_router(agencies_router)
app.include_router(discovery_router)
app.include_router(talent_router)
app.include_router(opportunity_router)
app.include_router(public_router)


# Public surfaces served at the site root — these never require the admin secret.
# Everything NOT listed here is gated, so new internal routes are private by
# default; a new *public* page must be added to this set.
_PUBLIC_PATHS = frozenset({
    "/", "/capabilities", "/samples", "/start", "/book", "/thanks", "/apply",
    "/delivery-sample", "/refer", "/for-artists", "/showreel", "/reel", "/stills",
    # Added late: both are front-of-house pages that were left out of this set when
    # their routes were written, so in production (where the token is set) they
    # answered 303 -> /admin/login. A sales page nobody outside the login can open
    # is the same defect as a CTA that goes nowhere. If you add a route to
    # public.py, add it here — test_launch_review_phase1 asserts the two lists agree.
    "/commission",
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
_REVIEW_ACTIONS = ("comment", "approve", "changes", "resolve", "asset", "reopen",
                   "picture", "reference")
_REVIEW_ACTION_RE = re.compile(
    r"^/project/\d+/review/(?:" + "|".join(_REVIEW_ACTIONS) + r")/?$")
# Payment-gated deliverable download — opened from the token-gated portal; the route
# itself validates the share/reviewer token AND the paid-in-full gate.
_DELIVERY_DL_RE = re.compile(r"^/project/\d+/dl/[^/]+/?$")
# The composer portal — a qualified creator's token-gated home (view assignments,
# submit work versions). The per-creator portal token IS the access control, so it
# bypasses the admin login gate (same exemption as the client delivery portal).
# EVERY composer POST must be listed here — the per-creator portal token is the
# access control, so these bypass the admin login gate. Missing an action here
# silently 303s the composer to /admin/login on their own token-gated page (this
# recurred: reply/address/capture were omitted and broke in prod with the gate on;
# tests/test_admin_gate.py now asserts every /creator/* route is covered).
_CREATOR_PORTAL_RE = re.compile(
    r"^/creator/[A-Za-z0-9_-]+"
    r"(/project/\d+/(version|deliverable|capture|note/\d+/(reply|address)))?/?$")
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
    return estimate_for(opp).suggested_price


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


# The /lanes kanban was deleted (ADR-0035). It rendered the SAME rows as /inbox —
# measured identical on the seeded book — and its one unique control, a "Won"
# button, POSTed status=Won with no outcome_value, booking a won deal at $0 and
# contradicting the rule documented above at _NEXT_STATUS. /inbox is the deal list
# (search + six filters + the same advance); the dashboard is the daily read.


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


# --------------------------------------------------------------------------- #
# Discovery scheduling (ADR-0014 §4/§6) — the meeting is tied to the opportunity
# before it begins. Manual today (log the time + link); the Zoom + Recall auto-flow
# lights up behind the same routes when the provider seams are configured.
# --------------------------------------------------------------------------- #


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


def _live_brief_ctx(conn, opp_id):
    """The Campaign Brief render context, live from Campaign Intelligence, ready to embed in
    the Client Workspace (ADR-0018). Builds the SAME ``doc`` the standalone brief route builds
    (single source), in read-only/public/embedded mode — the workspace is the frame, so the
    brief's own threshold cover is suppressed and no operator edit affordances render."""
    row, opp, ev = _load(conn, opp_id)
    if row is None:
        return None
    qual, _scored = ev
    est = estimate_for(opp, qual=qual)
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
    # ADR-0034: a fraction of the band the client is shown, not of the estimate.
    # ci_view/overrides are already loaded here — no extra query on a client page.
    deposit_amount = build_proposal(
        opp, qual, est,
        quote_band=capabilities_quote_band(
            opp, est, ci_fields=(ci_view or {}).get("fields") or {},
            commercial_overrides=(overrides or {}).get("commercial")),
    ).deposit_amount
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
# The persistence caveat that used to sit here ("these land on the LOCAL disk...
# durable storage needs object storage (S3/R2). Acceptable for now") is answered:
# ADR-0043 put every write and read behind `storage.get_object_store()`. Set
# CHORDENTIAL_STORAGE=s3 and the bytes stop depending on this machine. Left unset,
# behaviour is exactly what it was.
#
# `_safe_upload_path` lived here and is gone: its traversal guard now belongs to
# LocalObjectStore._path, so the check travels with the store that needs it rather
# than sitting beside one of several callers.
# --------------------------------------------------------------------------- #


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
    # SECURITY (Phase-2 review P0): only audio/video/image render INLINE. Anything
    # else — .html/.svg/.xml above all — downloads as an attachment with nosniff,
    # so a token-holding client can never plant same-origin script behind /uploads.
    import mimetypes as _mt
    _guess = _mt.guess_type(name or "")[0] or "application/octet-stream"
    _inline = _guess.split("/")[0] in ("audio", "video", "image") and not _guess.endswith("svg+xml")
    _headers = {"X-Content-Type-Options": "nosniff"}
    # ADR-0043: the store answers first. A LOCAL store hands back a real path, so
    # FileResponse still gives native Range/seek — that is what makes a long cut
    # scrub in the review player. A REMOTE store hands back a presigned URL and the
    # browser fetches the bucket directly, so the bytes never stream through this
    # process (and Range is the bucket's problem, which it is good at).
    _store = get_object_store(UPLOAD_DIR)
    _key = os.path.basename(name or "")
    path = _store.local_path(_key) if _key and _key == name else None
    if path is not None:
        if _inline:
            return FileResponse(path, headers=_headers)
        return FileResponse(path, headers=_headers, filename=os.path.basename(name),
                            media_type="application/octet-stream",
                            content_disposition_type="attachment")
    if _key and _key == name and getattr(_store, "durable", False):
        signed = _store.url(_key)
        if signed:
            return RedirectResponse(signed, status_code=307)
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
            # ADR-0043: put it back through the STORE. On local this restores the
            # disk copy so the next read hits FileResponse and Range works; with a
            # bucket configured it repairs the missing object instead of writing a
            # local file nothing would serve.
            get_object_store(UPLOAD_DIR).put(base, data, ctype)
            _rh_inline = (ctype or "").split("/")[0] in ("audio", "video", "image") \
                and not (ctype or "").endswith("svg+xml")
            if _rh_inline:
                return Response(content=data, media_type=ctype, headers=_headers)
            # Encode the filename the same way FileResponse does (RFC 5987) rather
            # than raw-interpolating into the header — defense-in-depth even though
            # `base` is always an os.urandom-generated key here, never user input.
            from urllib.parse import quote as _q
            _headers["Content-Disposition"] = (
                f"attachment; filename*=utf-8''{_q(base)}")
            return Response(content=data, media_type="application/octet-stream",
                            headers=_headers)
    return PlainTextResponse("not found", status_code=404)


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
    # ADR-0043: the gate above has already passed, so it is safe to hand the client
    # a direct URL. Local keeps serving the file itself.
    _store = get_object_store(UPLOAD_DIR)
    _key = os.path.basename(name or "")
    path = _store.local_path(_key) if _key and _key == name else None
    if path is not None:
        return FileResponse(path, filename=os.path.basename(path))
    if _key and _key == name and getattr(_store, "durable", False):
        signed = _store.url(_key)
        if signed:
            return RedirectResponse(signed, status_code=307)
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
            # ADR-0043: put it back through the STORE. On local this restores the
            # disk copy so the next read hits FileResponse and Range works; with a
            # bucket configured it repairs the missing object instead of writing a
            # local file nothing would serve.
            get_object_store(UPLOAD_DIR).put(base, data, ctype)
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
            "id": c["id"], "t": c["t_seconds"],
            "t_end": (c["t_end"] if "t_end" in keys else None),
            "author": c["author"],
            "body": c["body"], "kind": c["kind"], "resolved": bool(c["resolved"]),
            "addressed": bool(c["composer_addressed"]
                              if "composer_addressed" in keys else 0),
            # Species (EP P1): a conform (re-sync to a new cut) is free — the
            # composer must SEE that per-note, not just in the banner.
            "conform": bool(c["conform"] if "conform" in keys else 0),
            "at": c["created_at"] or "",
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
    # Scoped rounds come from the SAME source the console/portal read — the
    # estimate's revision multiplier via revision_status — not a phantom
    # ``revisions_included`` field that was never written (so the composer's
    # round sentence was always blank; EP review P0). One source, three doors.
    row = db.get_project(conn, project_id)
    est = _project_estimate(conn, row) if row is not None else None
    rs = revision_status(row, est, delivery) if row is not None else {}
    used = int(rs.get("used", delivery.get("revisions_used") or 0))
    scoped = int(rs.get("scoped") or 0) or None
    return {
        "notes": notes,
        # What's WAITING: every open human note the composer hasn't handled —
        # timeline comments AND formal change requests (asset_change is system
        # bookkeeping, excluded). The client-side recompute after "Mark addressed"
        # uses the identical rule, so the number is consistent from first paint
        # through every click (composer review P0: it read 0 on load with notes
        # waiting, then jumped once JS took over).
        "open_count": sum(1 for n in notes
                          if n["kind"] in ("comment", "change_request")
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
            # Phase 2 — the picture + references + conform marking
            "picture": delivery.get("picture") or None,
            "references": list(delivery.get("references") or []),
            # Phase 3 — the Cue Layer: cue regions + hit diamonds on the spine.
            # Read-only for the composer (Jon owns the cue list); they score to it.
            "cues": db.get_cues(conn, a["project_id"]),
            # Phase 4 §13 — the private Capture shelf (composer + studio only).
            "captures": db.get_captures(conn, a["project_id"]),
        })
    # Needs-me-first (composer review P1): rooms owing the composer work come
    # before in-motion rooms; delivered rooms sink to the bottom.
    def _urgency(v):
        closed = v["delivery_state"] in ("Released", "Delivered")
        needs_me = (v["feedback"]["open_count"] > 0
                    or (not v["versions"] and not v["pending"] and not closed))
        return 2 if closed else (0 if needs_me else 1)
    out.sort(key=_urgency)
    return out


@app.get("/creator/{token}", response_class=HTMLResponse)
def creator_portal(request: Request, token: str, p: Optional[int] = None):
    """The composer's Session Room(s). ``?p=<project_id>`` is a room's own door
    (ADR-0025): one token, each engagement individually addressable; without it,
    every room stacks needs-first."""
    conn = db.connect()
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        t = db.talent_from_row(row)
        assignments = _creator_assignment_view(conn, row["id"])
    finally:
        conn.close()
    all_rooms = assignments
    if p is not None:
        assignments = [a for a in assignments if a["project_id"] == p] or all_rooms
    return render(
        request, "creator_portal.html", nav="", token=token, t=t,
        completeness=profile_completeness(t), assignments=assignments,
        all_rooms=all_rooms, focused=p,
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
async def creator_reply_note(request: Request, token: str, project_id: int,
                             comment_id: int, body: str = Form("")):
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
        text = (body or "").strip()[:600]     # server-side cap; maxlength is advisory
        if text:
            parent = conn.execute(
                "SELECT id FROM review_comments WHERE id = ? AND project_id = ?",
                (comment_id, project_id)).fetchone()
            # Only mark success + notify when the reply ACTUALLY threaded onto a real
            # note — a stale/cross-project/guessed comment_id must not fabricate a
            # reply bubble or ping the operator about work that was never recorded
            # (eng P0). ``who`` is the signal the insert happened.
            if parent is not None:
                who = row["name"]
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
    # XHR (Phase 4): thread the reply in place — no full reload, so the composer
    # keeps their playhead + open sheet (the flow the composer review flagged).
    if (request.headers.get("x-requested-with") or "").lower() in ("fetch", "xmlhttprequest"):
        return JSONResponse({"ok": bool(who), "author": who, "body": text if who else ""})
    return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)


@app.post("/creator/{token}/project/{project_id}/capture")
def creator_capture(request: Request, token: str, project_id: int,
                    text: str = Form("")):
    """Capture (Phase 4 §13): the composer jots an idea/motif to the room's private
    shelf — timestamped, composer + studio only, NEVER shown to the client."""
    conn = db.connect()
    entry = None
    try:
        row = db.get_talent_by_portal_token(conn, token)
        if row is None:
            return HTMLResponse("Not found", status_code=404)
        if not db.talent_is_assigned(conn, row["id"], project_id):
            return HTMLResponse("Not assigned to this project", status_code=403)
        entry = db.add_capture(conn, project_id, text, by=row["name"])
    finally:
        conn.close()
    if (request.headers.get("x-requested-with") or "").lower() in ("fetch", "xmlhttprequest"):
        return JSONResponse({"ok": bool(entry),
                             "text": entry["text"] if entry else "",
                             "at": entry["at"] if entry else ""})
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
        data = await _read_capped(file, _SUBMISSION_MAX_BYTES)
        if not data:                              # over cap or empty — never buffer unbounded
            return RedirectResponse(f"/creator/{token}#p{project_id}", status_code=303)
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
        data = await _read_capped(file, _SUBMISSION_MAX_BYTES)
        if not data:                              # empty OR over cap — never buffer unbounded
            return _fail("file missing or too large", 400)
        # Collision-proof on-disk name (random suffix) so nothing can overwrite another
        # upload's file — no counter to race on.
        safe_ext = ext if ext else (".mp3" if kind == "audio" else ".bin")
        safe_name = f"proj{project_id}-{os.urandom(5).hex()}{safe_ext}"
        _persist_upload(conn, safe_name, data, mirror=len(data) <= _CUT_MIRROR_BYTES)  # ADR-0026
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
    est = estimate_for(opp, qual=qual)
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
    return estimate_for(opp, conn=conn, project_id=row["id"])


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
    # Tie conform classification to the cue that changed (EP P0): map each
    # timecoded change request to the cue its timecode falls under, and name the
    # cues the current cut touches. Both read the live cue list — the once-dead
    # cue_for_time/cues_touched_by_cut helpers now drive the console's conform copy.
    _cues_now = db.get_cues(conn, project_id)
    note_cue = {}
    for _c in comments:
        # Any timecoded note (a client's pinned comment or a timed change request)
        # gets tagged with the cue(s) it falls under — a RANGE note names every cue
        # its span overlaps ('m01–m02') so the operator weighing conform-vs-revision
        # sees a section note touches a section, not just its first frame (EP P0).
        if _c["t_seconds"] is not None:
            _te = _c["t_end"] if "t_end" in _c.keys() else None
            _code = db.cues_for_note(_cues_now, _c["t_seconds"], _te)
            if _code:
                note_cue[_c["id"]] = _code
    conform_cut_cues = db.cues_touched_by_cut(conn, project_id) if delivery.get("picture") else []

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
        # ADR-0019/0036: the client-facing production experience answers the court
        # question FIRST. Computed, never stored — one engine, and the portal and the
        # workspace render the same sentence.
        "court": production.court_state(row, delivery),
        "cert": cert,
        # The honest Content-ID sentence — the ONE source of truth (delivery.py),
        # so the browser doc and the ZIP doc can't drift on legally-material copy.
        "content_id_honest": CONTENT_ID_HONEST,
        "cues": cues,
        # The Cue Layer (Phase 3): the scoring cue list + hits + per-cue state.
        # Distinct from ``cues`` (the licensing cue SHEET above) — this is the
        # timed, scoreable spine the composer works against.
        "scoring_cues": _cues_now,
        "cue_states": db.CUE_STATES,
        # Conform↔cue tie (EP P0): which cue each timecoded change request lands
        # under, and which cues the current cut touches — surfaced where the
        # operator actually classifies conform vs revision.
        "note_cue": note_cue,
        "conform_cut_cues": conform_cut_cues,
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


@app.post("/project/{project_id}/delivery/rotate-link")
def delivery_rotate_link(project_id: int):
    """Cut a leaked client link and mint a fresh one (ADR-0039).

    The share token is the ONLY credential on the delivery portal: whoever holds the
    URL can stream the unreleased masters, read the brief, and post a change request
    — which spends a contractual revision round. Until now it could never be changed,
    so a forwarded email or an exported Slack channel was permanent access.

    Destructive by design (the client's existing link stops working the moment this
    runs), so the button carries a confirm and this is an operator press — the
    machine never rotates on its own.
    """
    conn = db.connect()
    try:
        if db.get_project(conn, project_id) is None:
            return HTMLResponse("Project not found", status_code=404)
        token = db.rotate_share_token(conn, project_id=project_id)
        if token:
            db.add_update(
                conn, project_id,
                "Client link rotated — the previous link no longer opens this project.",
                "rights")
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#reviewers", status_code=303)


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


# ── The Cue Layer (Phase 3) — operator doors. "The machine proposes, Jon ──────
# disposes": Jon builds the cue list + hits; the composer scores against it; per-cue
# approval maps onto the same human-pressed sign-off as deliverables. Namespaced
# under /delivery/cues/… to stay clear of the legacy /delivery/cue metadata route.
@app.post("/project/{project_id}/delivery/cues/add")
def delivery_cue_add(project_id: int, code: str = Form(""), name: str = Form(""),
                     t_in: str = Form(""), t_out: str = Form(""),
                     direction: str = Form("")):
    """Add a scoring cue (a named, timed span the composer scores)."""
    conn = db.connect()
    try:
        if db.get_project(conn, project_id) is None:
            return HTMLResponse("Project not found", status_code=404)
        db.add_cue(conn, project_id, code=code, name=name, t_in=t_in, t_out=t_out,
                   direction=direction)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@app.post("/project/{project_id}/delivery/cues/{cue_id}/state")
def delivery_cue_state(project_id: int, cue_id: int, state: str = Form("")):
    """Advance/reset a cue's state (open|take|published|approved). Approving a cue
    is a human decision (Constitution §4.1) — the machine never self-approves."""
    conn = db.connect()
    try:
        db.set_cue_state(conn, project_id, cue_id, (state or "").strip())
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@app.post("/project/{project_id}/delivery/cues/{cue_id}/edit")
def delivery_cue_edit(project_id: int, cue_id: int, code: str = Form(""),
                      name: str = Form(""), t_in: str = Form(""),
                      t_out: str = Form(""), direction: str = Form("")):
    """Edit a cue's label/timing/direction in place."""
    conn = db.connect()
    try:
        db.update_cue(conn, project_id, cue_id, code=(code or "").strip(),
                      name=(name or "").strip(), t_in=t_in, t_out=t_out,
                      direction=(direction or "").strip())
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@app.post("/project/{project_id}/delivery/cues/{cue_id}/delete")
def delivery_cue_delete(project_id: int, cue_id: int):
    """Remove a cue."""
    conn = db.connect()
    try:
        db.delete_cue(conn, project_id, cue_id)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@app.post("/project/{project_id}/delivery/cues/{cue_id}/hit")
def delivery_cue_hit_add(project_id: int, cue_id: int, t: str = Form(""),
                         name: str = Form("")):
    """Add a hit (a moment the music must honor) inside a cue."""
    conn = db.connect()
    try:
        db.add_hit(conn, project_id, cue_id, t=t, name=name)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


@app.post("/project/{project_id}/delivery/cues/{cue_id}/hit/{hit_id}/delete")
def delivery_cue_hit_delete(project_id: int, cue_id: int, hit_id: int):
    """Remove a hit from a cue."""
    conn = db.connect()
    try:
        db.delete_hit(conn, project_id, cue_id, hit_id)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#cues", status_code=303)


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


def _master_stem(conn, project_id: int, row, n: int, label: str) -> str:
    """The deterministic filename stem for a project's master version (ADR-0037).

    Both upload paths — the admin Assets agent and the composer portal — go through
    here so they cannot drift, and so neither invents a token. Previously both called
    ``version_name(campaign, "Master", 60, "Master", n, f"v{n}")``, which produced
    e.g. ``SUMMER_Master_60_MASTER_v1_V1``: a hardcoded :60 on a brief that never said
    :60, the word Master twice (once filling the CUE slot), and the version number
    twice (``f"v{n}"`` landing in the STATE slot, which is for FINAL).

    Length comes from what the brief STATES — the project's need plus the linked
    opportunity's need/description — and is omitted when nothing states one. A master
    spans the whole piece, so there is no cue to name; that slot stays empty.
    """
    campaign = (row["need"] if row is not None else "") or "Campaign"
    text = campaign
    opp_id = row["opp_id"] if row is not None and "opp_id" in row.keys() else None
    if opp_id:
        opp_row = db.get_opportunity(conn, opp_id)
        if opp_row is not None:
            text = f"{campaign} {opp_row['need'] or ''} {opp_row['description'] or ''}"
    return version_name(
        campaign, "", stated_length(text) or "", "Master", n,
        "FINAL" if "FINAL" in label.upper() else "",
    )


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
    stem = _master_stem(conn, project_id, row, n, label)
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
    stem = _master_stem(conn, project_id, row, n, label)
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
    parent_id: str = Form(""), r: str = Form(""), t_end: str = Form(""),
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
                # …and the same 24h sanity cap cues use, so a guest can't plant a
                # garbled "1666666666666:40" label in the client feed (eng P2).
                if t_seconds is not None and (
                        not math.isfinite(t_seconds) or t_seconds < 0
                        or t_seconds > db._MAX_TIMECODE_SECONDS):
                    t_seconds = None
            project = db.get_project(conn, project_id)
            delivery = db.get_delivery(conn, project_id)
            # Phase 4: an optional end timecode makes this a RANGE note (a span of
            # the picture), guarded the same way as the start. Ignored on replies.
            t_end_val = None
            if parent is None and str(t_end).strip() != "":
                try:
                    _te = float(t_end)
                    if math.isfinite(_te) and _te >= 0:
                        t_end_val = _te
                except ValueError:
                    t_end_val = None
            db.add_review_comment(
                conn, project_id, version=_current_version_tag(delivery),
                t_seconds=t_seconds, t_end=t_end_val, author=name, email=mail,
                body=body.strip(), kind="comment", parent_id=parent,
                verified=reviewer is not None,
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


async def _store_picture(conn, project_id: int, file: UploadFile, by: str) -> Optional[dict]:
    """Store the client's cut as the room's PICTURE (Phase 2). The current cut is
    archived to ``picture_history`` and the cut number bumps — a new cut is a
    CONFORM event, never a revision (production model): notes from the prior cut
    get marked by the room. Returns the new picture dict, or None on a bad file."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _VIDEO_EXTS:
        return None
    data = await _read_capped(file, _CUT_MAX_BYTES)
    if not data:
        return None
    safe_name = f"proj{project_id}-cut-{os.urandom(5).hex()}{ext}"
    # ADR-0026: cuts mirror into the DB only under the threshold; larger cuts are
    # disk-only until the object-storage seam ships.
    _persist_upload(conn, safe_name, data, content_type=file.content_type or "",
                    mirror=len(data) <= _CUT_MIRROR_BYTES)
    delivery = db.get_delivery(conn, project_id)
    prior = delivery.get("picture") or None
    from datetime import datetime as _dt, timezone as _tz
    if len((by or "").strip()) < 2:
        by = "The client"                       # attribution fallback (EP P2-3)
    pic = {"url": f"/uploads/{safe_name}", "filename": safe_name,
           "orig": file.filename, "by": by,
           "at": _dt.now(_tz.utc).isoformat(),
           "n": (int(prior.get("n") or 0) + 1) if prior else 1}
    if prior:
        hist = list(delivery.get("picture_history") or [])
        hist.append(prior)
        db.update_delivery(conn, project_id, "picture_history", hist)
    db.update_delivery(conn, project_id, "picture", pic)
    db.add_update(conn, project_id,
                  f"{by} uploaded cut {pic['n']} of the picture ({file.filename})."
                  + (" Notes from the prior cut are marked — changes it causes are"
                     " conforms, not revisions." if prior else ""))
    return pic


_REF_BLOCKED_EXTS = {".html", ".htm", ".svg", ".xml", ".xhtml", ".js", ".mjs"}
_REF_MAX_BYTES = int(os.environ.get("CHORDENTIAL_REF_MAX_MB", "128")) * 1024 * 1024


async def _read_capped(file: UploadFile, cap: int) -> Optional[bytes]:
    """Read an upload in chunks up to ``cap`` bytes; None if it exceeds the cap
    (never buffer an unbounded body — Phase-2 review P1-3)."""
    chunks, total = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def _store_reference(conn, project_id: int, file: UploadFile, by: str,
                           label: str = "") -> Optional[dict]:
    """Store an audible/visual REFERENCE for the composer (Phase 2 pull-forward:
    'Bonobo' is a career, not a reference — give them the actual track).

    Markup/script extensions are rejected outright (stored-XSS lane — review P0)
    and the serving layer additionally forces attachment on anything non-media."""
    # Normalize before the blocklist check: os.path.splitext("evil.html.") yields
    # ".", sneaking markup past a raw ext test (eng P2). Strip trailing dots/space.
    ext = os.path.splitext((file.filename or "").rstrip(". ").strip())[1].lower()
    if ext in _REF_BLOCKED_EXTS:
        return None
    data = await _read_capped(file, _REF_MAX_BYTES)
    if not data:
        return None
    kind = ("audio" if ext in _AUDIO_EXTS else
            "video" if ext in _VIDEO_EXTS else "file")
    safe_name = f"proj{project_id}-ref-{os.urandom(5).hex()}{ext or '.bin'}"
    # ADR-0026 mirror cap applies to references too — a 128MB video reference must
    # not blob into SQLite (eng P0: this path defaulted mirror=True, defeating the
    # ADR). Disk always; DB mirror only under the same threshold as a cut.
    _persist_upload(conn, safe_name, data, content_type=file.content_type or "",
                    mirror=len(data) <= _CUT_MIRROR_BYTES)
    delivery = db.get_delivery(conn, project_id)
    refs = list(delivery.get("references") or [])
    from datetime import datetime as _dt, timezone as _tz
    ref = {"label": (label or "").strip() or (file.filename or "Reference"),
           "url": f"/uploads/{safe_name}", "filename": safe_name, "kind": kind,
           "by": by, "at": _dt.now(_tz.utc).isoformat()}
    refs.append(ref)
    db.update_delivery(conn, project_id, "references", refs)
    db.add_update(conn, project_id, f"{by} added a reference: {ref['label']}.")
    return ref


@app.post("/project/{project_id}/review/picture")
async def review_upload_picture(
    request: Request, project_id: int, k: str = Form(""), r: str = Form(""),
    author: str = Form(""), email: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """The client door's Drop: upload the cut the music is written to. Token-gated
    like every review action; the room dresses itself around the picture."""
    conn = db.connect()
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        who = (reviewer.get("name") if reviewer else "") or author.strip() or "The client"
        pic = None
        if file is not None and (file.filename or "").strip():
            pic = await _store_picture(conn, project_id, file, who)
        project = db.get_project(conn, project_id)
    finally:
        conn.close()
    if pic is not None:
        await run_in_threadpool(
            _notify_operator_review, project_id, project,
            f"Picture uploaded — {_campaign_label(project) if project else 'campaign'}",
            f"{pic['by']} uploaded cut {pic['n']}. The composer's room now carries it.")
        await run_in_threadpool(
            _notify_assigned_creators, project_id, project,
            subject=f"The picture is in — cut {pic['n']}",
            body_text=("The client's cut just landed in your session room — the picture "
                       "is waiting for your music."))
    return _review_redirect(project_id, k, name=author, email=email, r=r)


@app.post("/project/{project_id}/review/reference")
async def review_upload_reference(
    request: Request, project_id: int, k: str = Form(""), r: str = Form(""),
    author: str = Form(""), email: str = Form(""), label: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """The client adds a hearable/viewable reference for the composer."""
    conn = db.connect()
    try:
        ok, reviewer = _access_ok(conn, project_id, k, r)
        if not ok:
            return HTMLResponse("Not found", status_code=404)
        who = (reviewer.get("name") if reviewer else "") or author.strip() or "The client"
        ref = None
        if file is not None and (file.filename or "").strip():
            ref = await _store_reference(conn, project_id, file, who, label=label)
        project = db.get_project(conn, project_id)
    finally:
        conn.close()
    if ref is not None:
        # the studio hears about every client reference (temp-love / rights lane —
        # EP review): the operator can veto before the composer leans on it
        await run_in_threadpool(
            _notify_operator_review, project_id, project,
            f"Client reference — {_campaign_label(project) if project else 'campaign'}",
            f"{ref['by']} added '{ref['label']}'. Listen before the composer leans on it.")
    return _review_redirect(project_id, k, name=author, email=email, r=r)


@app.post("/project/{project_id}/delivery/picture")
async def delivery_upload_picture(project_id: int,
                                  file: Optional[UploadFile] = File(None)):
    """Operator door: log the client's cut from the console (email handoffs
    happen; the room should still get the picture)."""
    conn = db.connect()
    try:
        pic = None
        if file is not None and (file.filename or "").strip():
            pic = await _store_picture(conn, project_id, file, "The studio")
        project = db.get_project(conn, project_id)
    finally:
        conn.close()
    if pic is not None:
        await run_in_threadpool(
            _notify_assigned_creators, project_id, project,
            subject=f"The picture is in — cut {pic['n']}",
            body_text=("The cut just landed in your session room — the picture is "
                       "waiting for your music."))
    return RedirectResponse(f"/project/{project_id}/delivery#picture", status_code=303)


@app.post("/project/{project_id}/delivery/reference")
async def delivery_upload_reference(project_id: int, label: str = Form(""),
                                    file: Optional[UploadFile] = File(None)):
    """Operator door: add a reference for the composer."""
    conn = db.connect()
    try:
        if file is not None and (file.filename or "").strip():
            await _store_reference(conn, project_id, file, "The studio", label=label)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#picture", status_code=303)


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

    Identity, two strengths (ADR-0020 — the client's single approval IS the award, so
    it must not be gated behind a link they may not have): a **verified reviewer link**
    (``?r=<reviewer_token>``) signs with the roster's LOCKED name + email, unspoofable;
    the workspace share link (``?k=``) may also approve, signing with a captured name +
    email, which is intent enough under ESIGN/UETA. Both paths record who and when.

    Note what that means operationally: the share link is forwardable, so anyone holding
    it can approve under any typed name. That is accepted, not overlooked — the mitigation
    is reviewer links for consequential sign-off and treating ``?k=`` as a bearer token.
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


@app.post("/project/{project_id}/review/note/{comment_id}/species")
def review_note_species(project_id: int, comment_id: int):
    """Operator door: classify a note as conform (picture-caused, free) or
    revision (counts against rounds) — the round ledger's species record.

    Classifying a change request as a conform RETURNS its round to the budget
    (and flipping back consumes one again, floored at zero). Without this the
    'conform · free' label was cosmetic — the round was already spent at
    request time and nothing gave it back (EP review P0). This keeps the one
    ``revisions_used`` counter — read identically by console, portal, and the
    composer room — actually honest."""
    conn = db.connect()
    try:
        new_val = db.toggle_comment_conform(conn, project_id, comment_id)
        if new_val is not None:
            crow = conn.execute(
                "SELECT kind FROM review_comments WHERE id = ? AND project_id = ?",
                (comment_id, project_id)).fetchone()
            # Only change requests consume rounds; praise/comments never did.
            if crow is not None and crow["kind"] == "change_request":
                delivery = db.get_delivery(conn, project_id)
                used = int(delivery.get("revisions_used") or 0)
                used = max(0, used - 1) if new_val == 1 else used + 1
                db.update_delivery(conn, project_id, "revisions_used", used)
    finally:
        conn.close()
    return RedirectResponse(f"/project/{project_id}/delivery#versions", status_code=303)


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
            # A rejected deliverable must not stay downloadable: remove the blob
            # (best-effort, path-guarded inside UPLOAD_DIR — engineering P2).
            try:
                blob = os.path.realpath(os.path.join(UPLOAD_DIR, hit.get("filename") or ""))
                if blob.startswith(os.path.realpath(UPLOAD_DIR) + os.sep) and os.path.isfile(blob):
                    os.remove(blob)
            except OSError:
                pass
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
        # ``project_id`` pulls in the assigned talent's own rates, so the
        # client-facing proposal reflects real assigned cost — not role defaults.
        est = estimate_for(opp, conn=conn, project_id=project_id, qual=qual)
        proposal = build_proposal(
            opp, qual, est, quote_band=_quote_band_for(conn, row, opp, est))
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
