"""Signing in — the shared passphrase, and real accounts (ADR-0054).

Extracted from `app.py` the moment adding accounts pushed it past the size guard
`tests/test_app_structure.py` enforces. That guard exists because `app.py` was 9,133
lines once, and the way back there is exactly this: a few lines at a time, each with a
good reason.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import accounts, db
from .shell import (
    ADMIN_COOKIE, admin_cookie_value as _admin_cookie_value,
    admin_secret as _admin_secret, admin_authed as _admin_authed,
    render, safe_local as _safe_local,
)

router = APIRouter(tags=["auth"])


@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, next: str = "/dashboard"):
    if _admin_authed(request):
        return RedirectResponse(_safe_local(next, "/dashboard"), status_code=303)
    return render(
        request, "admin_login.html", next=_safe_local(next, "/dashboard"), error=False
    )


@router.post("/admin/login")
def admin_login(request: Request, password: str = Form(""), email: str = Form(""),
                next: str = Form("/dashboard")):
    """Sign in with an ACCOUNT (email + password) or the shared passphrase.

    Both, on purpose (ADR-0054). An account gives the decision log a name; the
    passphrase is break-glass and is tried second so a real account always wins. The
    order matters only for the log, but the log is the point.
    """
    target = _safe_local(next, "/dashboard")

    if email.strip():
        conn = db.connect()
        try:
            user = accounts.authenticate(conn, email, password)
            if user is not None:
                token = accounts.start_session(
                    conn, user["id"], request.headers.get("user-agent", ""))
            else:
                token = ""
        finally:
            conn.close()
        if token:
            resp = RedirectResponse(target, status_code=303)
            resp.set_cookie(
                accounts.SESSION_COOKIE, token, httponly=True, samesite="lax",
                secure=request.url.scheme == "https",
                max_age=60 * 60 * 24 * accounts.SESSION_DAYS,
            )
            return resp
        return render(request, "admin_login.html", next=target, error=True)

    token = _admin_secret()
    if not token:
        return RedirectResponse("/dashboard", status_code=303)
    if hmac.compare_digest(password.strip(), token):
        resp = RedirectResponse(target, status_code=303)
        resp.set_cookie(
            ADMIN_COOKIE, _admin_cookie_value(token),
            httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
        )
        return resp
    return render(
        request, "admin_login.html", next=target, error=True
    )


@router.get("/admin/logout")
def admin_logout(request: Request):
    """Revoke the session server-side, not merely forget the cookie. A sign-out that
    only clears the browser leaves a token that still works for anyone who kept it."""
    token = request.cookies.get(accounts.SESSION_COOKIE) or ""
    if token:
        conn = db.connect()
        try:
            accounts.end_session(conn, token)
        finally:
            conn.close()
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(ADMIN_COOKIE)
    resp.delete_cookie(accounts.SESSION_COOKIE)
    return resp


# The /lanes kanban was deleted (ADR-0035). It rendered the SAME rows as /inbox —
# measured identical on the seeded book — and its one unique control, a "Won"
# button, POSTed status=Won with no outcome_value, booking a won deal at $0 and
# contradicting the rule documented above at _NEXT_STATUS. /inbox is the deal list
# (search + six filters + the same advance); the dashboard is the daily read.


# --------------------------------------------------------------------------- #
# Discovery scheduling (ADR-0014 §4/§6) — the meeting is tied to the opportunity
# before it begins. Manual today (log the time + link); the Zoom + Recall auto-flow
# lights up behind the same routes when the provider seams are configured.
# --------------------------------------------------------------------------- #


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


