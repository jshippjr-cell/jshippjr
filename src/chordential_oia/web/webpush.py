"""Web Push — native phone/desktop alerts for the installed Chordential PWA.

Unlike ntfy (a third-party app with a flaky iOS "wake-and-poll" delivery), Web
Push delivers a *first-class* OS notification straight to the installed PWA:
banner + sound + lock screen, tapping through to the dashboard. This is the
delivery channel for new Signal Radar gigs.

Setup (Render env): a VAPID keypair + subject identify this server to the push
services (Apple/Mozilla/Google):
  - ``CHORDENTIAL_VAPID_PUBLIC``   base64url public key (also sent to the browser)
  - ``CHORDENTIAL_VAPID_PRIVATE``  base64url private key (a secret)
  - ``CHORDENTIAL_VAPID_SUBJECT``  a ``mailto:`` contact

``pywebpush`` is imported lazily and only when actually sending, so the core app
never hard-depends on it and the sandbox/CI (egress blocked) never needs it —
tests monkeypatch the sender. Best-effort throughout: a push never raises.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from . import db

_LAST_PUSH_ERROR = ""


def vapid_public() -> str:
    return os.environ.get("CHORDENTIAL_VAPID_PUBLIC", "").strip()


def vapid_private() -> str:
    return os.environ.get("CHORDENTIAL_VAPID_PRIVATE", "").strip()


def vapid_subject() -> str:
    return os.environ.get("CHORDENTIAL_VAPID_SUBJECT", "mailto:hello@chordential.com").strip()


def is_configured() -> bool:
    """True when the VAPID keypair is set — i.e. Web Push can actually send."""
    return bool(vapid_public() and vapid_private())


def last_push_error() -> str:
    return _LAST_PUSH_ERROR


def _send_one(subscription_info: dict, payload: str) -> int:
    """Send to a single subscription; returns the HTTP status (0 on transport
    error). Raised pywebpush errors are unwrapped to their response code so the
    caller can prune expired (404/410) subscriptions. The push service's
    rejection body (Apple/Mozilla explain *why*) is stashed in _LAST_PUSH_ERROR
    so the radar can show it."""
    global _LAST_PUSH_ERROR
    from pywebpush import WebPushException, webpush  # lazy — Render-only

    # Fresh claims per send: Apple rejects a JWT whose `exp` is in the past or
    # >24h out, so let pywebpush stamp `exp` itself each time (never reuse).
    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=vapid_private(),
            vapid_claims={"sub": vapid_subject()},
            timeout=8,
        )
        return 200
    except WebPushException as exc:  # has .response on HTTP errors
        resp = getattr(exc, "response", None)
        code = getattr(resp, "status_code", 0) or 0
        body = ""
        try:
            body = (getattr(resp, "text", "") or "").strip()[:160]
        except Exception:  # noqa: BLE001
            body = ""
        _LAST_PUSH_ERROR = f"push returned {code or '—'}: {body or exc}"[:240]
        return code


def send_web_push(title: str, body: str = "", url: str = "/signals") -> dict:
    """Push a notification to every subscribed device. Returns a summary dict
    ``{"configured", "subscriptions", "sent", "pruned"}``. Prunes subscriptions
    the push service reports as gone (404/410). Best-effort — never raises."""
    global _LAST_PUSH_ERROR
    if not is_configured():
        return {"configured": False, "subscriptions": 0, "sent": 0, "pruned": 0}

    payload = json.dumps({
        "title": title or "New gig on Chordential",
        "body": body or "",
        "url": url or "/signals",
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    conn = db.connect()
    sent = pruned = 0
    try:
        subs = db.list_push_subscriptions(conn)
        for s in subs:
            info = {
                "endpoint": s["endpoint"],
                "keys": {"p256dh": s["p256dh"], "auth": s["auth"]},
            }
            try:
                code = _send_one(info, payload)
            except Exception as e:  # noqa: BLE001 — best-effort push
                _LAST_PUSH_ERROR = f"{type(e).__name__}: {e}"[:200]
                continue
            if code in (404, 410):           # subscription expired → forget it
                db.delete_push_subscription(conn, s["endpoint"])
                pruned += 1
            elif code == 200:
                sent += 1
                _LAST_PUSH_ERROR = ""        # cleared on a clean send
            # else: _send_one already stashed the push service's rejection body
        return {"configured": True, "subscriptions": len(subs), "sent": sent, "pruned": pruned}
    finally:
        conn.close()
