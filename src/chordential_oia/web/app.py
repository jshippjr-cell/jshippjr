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
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from .. import agreement, signing
from ..storage import get_object_store, storage_status
from . import (accounts, actor, campaigns, db, discovery, roles, scheduler, seed,
               uploads, webpush)
from .filters import displayurl, money, pct, slug
from .shell import (admin_authed as _admin_authed, admin_secret as _admin_secret,
                    signed_in_user as _signed_in_user)
from .agencies_routes import router as agencies_router
from .discovery_routes import router as discovery_router
from .talent_routes import router as talent_router
from .opportunity_routes import router as opportunity_router
from .project_routes import router as project_router
from .creator_routes import router as creator_router
from .contributor_routes import router as contributor_router
from .campaign_routes import router as campaign_router
from .simulator_routes import router as simulator_router
from .workspace_routes import router as workspace_router
from .console_routes import router as console_router
from .billing_routes import router as billing_router
from .meetings_routes import router as meetings_router
from .auth_routes import router as auth_router
from .public import router as public_router

_HERE = os.path.dirname(__file__)
# ADR-0044: created in shell.py so a route module can import it without importing
# app.py (which imports the route modules). Everything below still decorates THIS
# object — the filters and globals did not move.
from .shell import templates  # noqa: E402


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


def _media_offsite() -> bool:
    """Does `/uploads/{name}` hand the browser a URL on ANOTHER ORIGIN?

    True whenever a durable object store is active, because `serve_upload` then 307s to a
    presigned bucket URL. The templates pass this to `wave-live.js`, which must not tap
    such an element: cross-origin media that is not CORS-approved makes a
    `MediaElementAudioSourceNode` emit SILENCE by spec — no error, element still
    "playing". Switching the bucket on silenced every client's review player, including
    files uploaded long before, and nothing reported it because nothing was broken.

    Callable, not a frozen value: the tests flip `CHORDENTIAL_STORAGE` on a live app.
    """
    return bool(storage_status(UPLOAD_DIR)["durable"])


templates.env.globals["media_offsite"] = _media_offsite
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
# What a client agrees to when they sign (ADR-0065) + the e-signature consent (ADR-0059).
# Globals, not route context: a route that forgot to pass them would render a signature
# block with a blank acceptance line. They live in Python because this text is part of the
# signed DOCUMENT — it enters the digest, so editing it is a change signatures can detect.
templates.env.globals["acceptance_text"] = agreement.ACCEPTANCE_TEXT
templates.env.globals["acceptance_limits"] = agreement.ACCEPTANCE_LIMITS
templates.env.globals["consent_text"] = signing.CONSENT_TEXT


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
    # The same honesty the storage line owes: on Postgres, say whether connections are
    # actually pooled. `psycopg_pool` is an optional package, and a declared dependency
    # that production never installed is exactly how uploads once landed with zero copies
    # while the boot line announced durability (ADR-0043, amended). "We thought pooling
    # was on" must not be a thing anyone can believe by default.
    _pool = db.pool_status()
    if _pool["applicable"] and not _pool["requested"]:
        print("[db] connection pooling is DISABLED by CHORDENTIAL_DB_POOL — every call "
              "opens a new Postgres connection.", flush=True)
    elif _pool["applicable"] and not _pool["available"]:
        print("[db] WARNING: psycopg_pool is NOT installed, so every call opens a new "
              "Postgres connection (TCP + TLS + auth, several per page). Install the "
              "`postgres` extra — and check the BUILD COMMAND in the Render dashboard, "
              "which is what actually runs.", flush=True)
    elif _pool["applicable"]:
        print(f"[db] Postgres connection pool: {_pool['min']}–{_pool['max']}.", flush=True)

    conn = db.connect()
    db.init_db(conn)
    # The first account, from the environment, once (ADR-0054). A public sign-up page on
    # an internal console is an open door and a seeded default password is a published
    # one; env vars are set by whoever already controls the deploy, so they prove nothing
    # new — the right bar for a bootstrap, and no lower.
    try:
        _uid = accounts.bootstrap_from_env(conn)
        if _uid:
            print(f"[auth] created the first account (#{_uid}) from "
                  f"CHORDENTIAL_FIRST_USER — those variables can be removed now.",
                  flush=True)
    except Exception as _e:                      # noqa: BLE001 — never block a boot
        print(f"[auth] first-account bootstrap skipped: {_e}", flush=True)
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
    # Canonical identity, AFTER seeding and purging — both write the very rows these
    # passes exist to link, and running first left a fresh instance unlinked until its
    # SECOND boot (proved by test_buyer_org.py::test_the_boot_links_organisations).
    # Both are idempotent and self-limiting: rows already linked, and rows that carry no
    # identifier and never can, are excluded by the query, so this costs a scan on the
    # first boot and nothing on the ones after.
    try:
        _people = db.link_people(conn)           # ADR-0050 — the person
        if _people["linked"]:
            print(f"[identity] linked {_people['linked']} rows to "
                  f"{_people['people']} buyers ({_people['no_email']} rows carry no "
                  f"email and cannot be identified).", flush=True)
    except Exception as _e:                      # noqa: BLE001 — never block a boot
        print(f"[identity] buyer linking skipped: {_e}", flush=True)
    try:
        _orgs = db.link_orgs(conn)               # ADR-0056 — the organisation
        if _orgs["linked"]:
            print(f"[identity] linked {_orgs['linked']} rows to {_orgs['orgs']} "
                  f"organisations ({_orgs['no_name']} rows carry no name; "
                  f"{_orgs['domain_conflicts']} domain conflicts).", flush=True)
    except Exception as _e:                      # noqa: BLE001 — never block a boot
        print(f"[identity] organisation linking skipped: {_e}", flush=True)
    try:
        # ADR-0064 — facts read correctly and filed one column away from their canonical
        # slot, before the facet was derived rather than accepted. Free (no model call),
        # idempotent, and it never overwrites a slot that already holds a value.
        _refiled = db.refile_ci_fields_to_canonical_slots(conn)
        if _refiled:
            print(f"[intelligence] refiled {_refiled} extracted facts onto their canonical "
                  f"slots (Budget / Timeline / Deliverables …).", flush=True)
    except Exception as _e:                      # noqa: BLE001 — never block a boot
        print(f"[intelligence] canonical refile skipped: {_e}", flush=True)
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
        # Hand the engine lease over on the way out. Without this the incoming
        # instance waits out the TTL before anything runs — which is the whole
        # length of a blue-green handover spent with the engines stopped.
        scheduler._drop_lease()
        # Release the pooled connections too, so a draining instance is not still
        # holding a slice of a capped Postgres connection limit that the incoming
        # instance is at that moment trying to claim.
        db.close_pool()


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
app.include_router(contributor_router)
app.include_router(campaign_router)
app.include_router(simulator_router)
app.include_router(workspace_router)
app.include_router(console_router)
app.include_router(billing_router)
app.include_router(meetings_router)
app.include_router(auth_router)
app.include_router(public_router)


# Public surfaces served at the site root — these never require the admin secret.
# Everything NOT listed here is gated, so new internal routes are private by
# default; a new *public* page must be added to this set.
_PUBLIC_PATHS = frozenset({
    "/", "/capabilities", "/samples", "/start", "/book", "/thanks", "/apply",
    "/delivery-sample", "/refer", "/for-artists", "/showreel", "/reel", "/stills",
    "/score",
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
# EVERY action behind the workspace token, or the client meets the internal login the
# moment they press the button (test_the_client_never_meets_the_login derives this).
_WORKSPACE_RE = re.compile(r"^/workspace/[A-Za-z0-9_-]+"
                           r"(/approve|/confirm-scope|/approve-version|/sign|/court\.json)?/?$")


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
# The client SIGNS the Clearance Certificate from the token-gated portal (ADR-0059), so
# this POST cannot sit behind the admin gate. The route does its own, STRICTER check: a
# verified reviewer's personal ?r= token only — the generic share link may read the
# certificate and may not sign it. Note the deliberate asymmetry with
# /delivery/signature/{id}/void, which is NOT exempt: withdrawing a signature is an
# operator act and stays owner-only behind the gate.
_DELIVERY_SIGN_RE = re.compile(r"^/project/\d+/delivery/sign/?$")
# A verified reviewer invites a colleague from that same portal (ADR-0060). Also not
# admin-gated, and also doing its own stricter check: an ACTIVE reviewer holding
# `can_delegate`, which by default means one the operator named. The two OPERATOR
# controls over the same roster — /delivery/reviewer/revoke and /reviewer/extend — are
# deliberately absent from this list and stay behind the gate.
_DELIVERY_DELEGATE_RE = re.compile(r"^/project/\d+/delivery/delegate/?$")
# The composer portal — a qualified creator's token-gated home (view assignments,
# submit work versions). The per-creator portal token IS the access control, so it
# bypasses the admin login gate (same exemption as the client delivery portal).
# EVERY composer POST must be listed here — the per-creator portal token is the
# access control, so these bypass the admin login gate. Missing an action here
# silently 303s the composer to /admin/login on their own token-gated page (this
# recurred: reply/address/capture were omitted and broke in prod with the gate on;
# tests/test_admin_gate.py now asserts every /creator/* route is covered).
_CREATOR_PORTAL_RE = re.compile(
    r"^/creator/[A-Za-z0-9_-]+(/agreement(/sign)?|/project/\d+/(version|deliverable"
    r"|capture|contributor/\d+/(remind|remove)|contributor"
    r"|note/\d+/(reply|address)))?/?$")
# A session player's release. No account, ever — the link is the whole credential.
_CONTRIBUTOR_RE = re.compile(r"^/contributor/[A-Za-z0-9_-]+(/sign)?/?$")
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
        or _DELIVERY_SIGN_RE.match(path)
        or _DELIVERY_DELEGATE_RE.match(path)
        or _CREATOR_PORTAL_RE.match(path)
        or _CONTRIBUTOR_RE.match(path)
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


async def _log_decision(request: Request, status: int) -> None:
    """Append to the decision log, off the event loop and never into the response.

    An audit trail that can 500 a client's approval is worse than no audit trail, so
    every failure here is swallowed — the write it was recording has already happened.
    """
    import asyncio

    def _write():
        conn = None
        try:
            conn = db.connect()
            actor.record(conn, request, status)
        except Exception:                       # noqa: BLE001 — see docstring
            pass
        finally:
            if conn is not None:
                try: conn.close()
                except Exception: pass
    try:
        await asyncio.to_thread(_write)
    except Exception:                           # noqa: BLE001
        pass


@app.middleware("http")
async def _admin_gate(request: Request, call_next):
    if (_admin_secret() and not _is_public_path(request.url.path)
            and not _is_tokened_brief(request) and not _admin_authed(request)):
        if request.method == "HEAD":
            return Response(status_code=200)  # let platform health probes through
        return RedirectResponse(f"/admin/login?next={request.url.path}", status_code=303)
    # WHAT they are allowed to do (ADR-0055). Checked here, not at forty routes, for
    # the same reason the decision log is written here. Two things it must never do:
    # restrict the shared passphrase (that is the break-glass, and anyone holding it can
    # change the env var anyway), or change anything on an instance with no accounts.
    _user = _signed_in_user(request)
    if _user is not None and not roles.may(_user, request.method, request.url.path):
        return PlainTextResponse(
            "Your account does not have permission for this action. "
            "Ask the owner if you need it.", status_code=403)
    response = await call_next(request)
    # WHO did this (ADR-0053). Recorded HERE because this is the one place every state
    # change already passes — stamping forty decision routes by hand would miss the
    # forty-first, and the one it misses is the one someone disputes. Only mutating
    # methods: a GET is a look, not a decision, and logging every page view would bury
    # the record it exists to keep.
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        await _log_decision(request, response.status_code)
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
    # The redirect is only offered for an object that is ACTUALLY THERE. `url()` signs a
    # key without asking the bucket anything, so a missing object used to be answered with
    # a 307 to a presigned URL that R2 replies to with a 404 — which an <audio> element
    # renders as silence, with no error anywhere. Worse, returning here skipped the DB
    # mirror fallback below, so a key that exists ONLY in the mirror (which is exactly what
    # `persist_upload` leaves behind when a bucket write fails) was unplayable while every
    # existence check said it was fine. One HEAD, and a mirror-only key now serves AND
    # repairs itself into the bucket on the way past.
    if _key and _key == name and getattr(_store, "durable", False) and _store.exists(_key):
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




def main() -> None:  # console entry point
    import uvicorn

    host = os.environ.get("CHORDENTIAL_HOST", "127.0.0.1")
    port = int(os.environ.get("CHORDENTIAL_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
