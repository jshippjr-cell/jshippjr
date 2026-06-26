"""Outbound-email seam — pluggable, best-effort transactional send.

Mirrors the payment provider seam (:mod:`chordential_oia.payments`): the provider
is selected at runtime by env, defaulting to a deterministic **null** mailer that
sends nothing (it logs intent only). Real delivery turns on by setting
``CHORDENTIAL_MAIL_PROVIDER=smtp`` plus the SMTP credentials — no behavior change
until configured, so the suite and prod are unaffected today.

Config (env):
  ``CHORDENTIAL_MAIL_PROVIDER``  "null" (default) | "smtp"
  ``CHORDENTIAL_SMTP_HOST``      SMTP server host (required for smtp)
  ``CHORDENTIAL_SMTP_PORT``      default 587
  ``CHORDENTIAL_SMTP_USER``      SMTP auth user (optional)
  ``CHORDENTIAL_SMTP_PASS``      SMTP auth password (optional)
  ``CHORDENTIAL_SMTP_FROM``      From address (required for smtp)
  ``CHORDENTIAL_SMTP_STARTTLS``  "1" (default) — STARTTLS on; "0" to disable

Every send is **best-effort and NEVER raises**: it returns a status string so the
caller (a web request) is never blocked or crashed by a mail failure.
  ``"sent"``   — handed to the SMTP server
  ``"logged"`` — null/unconfigured provider; recorded intent, sent nothing
  ``"error"``  — an exception was swallowed; nothing was delivered
"""

from __future__ import annotations

import logging
import os
import ssl
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)

PROVIDER_ENV = "CHORDENTIAL_MAIL_PROVIDER"


def _provider() -> str:
    return (os.environ.get(PROVIDER_ENV, "null") or "null").strip().lower()


def _smtp_from() -> Optional[str]:
    return (os.environ.get("CHORDENTIAL_SMTP_FROM") or "").strip() or None


def _smtp_host() -> Optional[str]:
    return (os.environ.get("CHORDENTIAL_SMTP_HOST") or "").strip() or None


def mail_configured() -> bool:
    """True when a real (smtp) provider is selected AND has host + from set.

    Used to gate the additive notifications: when False, callers fall back to the
    existing manual-copy flow (nothing breaks); when True, mail goes out."""
    return _provider() == "smtp" and bool(_smtp_host()) and bool(_smtp_from())


def _build_message(to: str, subject: str, text: str, html: Optional[str],
                   sender: str) -> EmailMessage:
    """Assemble a proper EmailMessage (text, with an optional html alternative)."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _send_smtp(to: str, subject: str, text: str, html: Optional[str]) -> str:
    """Hand a message to the configured SMTP server (stdlib smtplib + STARTTLS).

    Best-effort: any failure is swallowed and reported as ``"error"`` — the lazy
    import keeps module import cheap and matches the payments seam's discipline."""
    import smtplib  # stdlib; lazy so import stays trivial

    host = _smtp_host()
    sender = _smtp_from()
    if not host or not sender:
        # Misconfigured smtp provider — degrade to a no-op log, never crash.
        logger.info("mailer: smtp selected but host/from unset; not sending to %s", to)
        return "logged"

    port = int((os.environ.get("CHORDENTIAL_SMTP_PORT") or "587").strip() or "587")
    user = (os.environ.get("CHORDENTIAL_SMTP_USER") or "").strip() or None
    password = os.environ.get("CHORDENTIAL_SMTP_PASS") or None
    starttls = (os.environ.get("CHORDENTIAL_SMTP_STARTTLS", "1") or "1").strip() != "0"

    msg = _build_message(to, subject, text, html, sender)
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            if starttls:
                server.starttls(context=ssl.create_default_context())
            if user and password is not None:
                server.login(user, password)
            server.send_message(msg)
        return "sent"
    except Exception:  # noqa: BLE001 — mail is best-effort, never block the request
        logger.exception("mailer: smtp send to %s failed", to)
        return "error"


def send_email(to: str, subject: str, text: str, html: Optional[str] = None) -> str:
    """Send one email, best-effort. NEVER raises.

    Returns ``"sent"`` (handed to SMTP), ``"logged"`` (null/unconfigured — recorded
    intent, sent nothing), or ``"error"`` (an exception was swallowed). The default
    provider is **null**, so out of the box this is a no-op log."""
    to = (to or "").strip()
    if not to:
        return "error"
    try:
        if _provider() == "smtp":
            return _send_smtp(to, subject, text, html)
        # Null provider (default): log the intent, send nothing.
        logger.info("mailer(null): would send to=%s subject=%r", to, subject)
        return "logged"
    except Exception:  # noqa: BLE001 — defensive; send_email must never raise
        logger.exception("mailer: send to %s crashed", to)
        return "error"


__all__ = ["send_email", "mail_configured", "PROVIDER_ENV"]
