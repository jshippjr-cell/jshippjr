"""WHICH PATHS THE ADMIN GATE LETS THROUGH — and why each one.

Extracted from `app.py` (2026-08-28) at the ratchet's own instruction: *"If this needs
raising again, extract the gate (`_is_public_path` and its regexes) into its own module
instead. That is a real shrink; another +10 is not."* It had grown by one regex and one
exemption line per token-gated client surface, which is the gate doing its job — the
alternative on offer was deleting the comments, and the comments are load-bearing.

**Every exemption here is a promise that the route does its OWN, stricter check.** The
unguessable token in the URL is the access control; this module only says "do not bounce
this to the operator's login". Get that wrong in either direction and it is invisible in
testing: a missing exemption 303s a real client to an internal login page — which answers
**200 with a login form**, and therefore looks exactly like success — and a too-broad one
hands an operator surface to anyone who guesses a URL. Both have happened.

So: name each path exactly, never wildcard a family, and say in a comment what the route
checks for itself. `tests/test_admin_gate.py` walks the whole set.

No imports from the rest of the web package: this is a pure question about a string, and
it sits at the bottom of the import order beside `shell.py`.
"""

from __future__ import annotations

import re

from fastapi import Request


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


def is_tokened_brief(request: Request) -> bool:
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
                   "picture", "reference", "assets", "address")
_REVIEW_ACTION_RE = re.compile(
    r"^/project/\d+/review/(?:" + "|".join(_REVIEW_ACTIONS) + r")/?$")
# Moving a note's own mark, from the room. Its own pattern rather than a `_REVIEW_ACTIONS`
# entry because it is nested one level deeper (`/review/note/<id>/move`), and DELIBERATELY
# not a wildcard over `/review/note/<id>/*`: its sibling `/species` is an operator
# classification that must stay behind the gate. Named exactly, like every other exemption
# here. The route does its own, stricter check — `_session_role` resolves the credential,
# `room.CAPS` decides whether that role may comment at all, and a note may only be moved
# by the side that wrote it.
_REVIEW_NOTE_MOVE_RE = re.compile(r"^/project/\d+/review/note/\d+/move/?$")
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
# THE room (ADR-0068). The route resolves the caller's role from whichever credential
# they hold (?t=/?k=/?r=) and 404s when none fits — stricter than the gate, which only
# knows whether you are the operator.
_ROOM_RE = re.compile(r"^/room/\d+/?$")
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
        or _REVIEW_NOTE_MOVE_RE.match(path)
        or _DELIVERY_DL_RE.match(path)
        or _DELIVERY_SIGN_RE.match(path)
        or _DELIVERY_DELEGATE_RE.match(path)
        or _CREATOR_PORTAL_RE.match(path)
        or _CONTRIBUTOR_RE.match(path)
        or _ROOM_RE.match(path)
        or _SESSION_ROOM_RE.match(path)
        or _CLIENT_PAY_RE.match(path)
        or path == "/pay/return"
        # Where an unverifiable return lands (ADR-0085). It is a payer-facing page that
        # holds no token, names no project and reads nothing from the database — but it
        # is reached by a customer's browser, so it cannot sit behind the admin login.
        or path == "/pay/confirming"
    )


def is_public(path: str) -> bool:
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
