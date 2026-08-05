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
import os
import re
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import (
    HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from ..storage import get_object_store, storage_status
from .. import mailer
from ..payments import get_payment_provider
from ..proposals import build_proposal
from ..capabilities import (
    build_capabilities_doc, default_toggles, quote_band as capabilities_quote_band,
)
from ..matching import match_talent
from ..talent import profile_completeness
from . import (
    campaign_intelligence, campaigns, commercial, db, decision_makers,
    directory_parsers, discovery,
    enrichment, intelligence, kickoff, meeting_scheduler, meetings_service,
    music_opportunity, next_action, opportunity_signals, production, queue as queue_mod, relationships,
    scheduler, seed, signals, sources, triage, webpush, workspace,
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
    _notify_assigned_creators, _notify_operator_review, _project_estimate,
    _sync_role_milestones,
)
from .opportunity_ops import (
    _brief_ci_context, _buyer_context, _ensure_project_for_opp,
    _load, _quote_band_for, _reconcile_opp_status, _to_utc_iso,
)
from .uploads import (
    _persist_upload, _read_capped, _store_pending_submission,
)
from .shell import (
    ADMIN_COOKIE, admin_authed as _admin_authed, admin_cookie_value as _admin_cookie_value,
    admin_secret as _admin_secret,
)
from .agencies_routes import router as agencies_router
from .discovery_routes import router as discovery_router
from .talent_routes import _parse_rate, router as talent_router
from .opportunity_routes import router as opportunity_router
from .project_routes import router as project_router
from .creator_routes import router as creator_router
from .campaign_routes import router as campaign_router
from .simulator_routes import router as simulator_router
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
app.include_router(project_router)
app.include_router(creator_router)
app.include_router(campaign_router)
app.include_router(simulator_router)
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


def main() -> None:  # console entry point
    import uvicorn

    host = os.environ.get("CHORDENTIAL_HOST", "127.0.0.1")
    port = int(os.environ.get("CHORDENTIAL_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
