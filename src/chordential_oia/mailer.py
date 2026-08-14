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

import html as _html
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
                   sender: str, ics: Optional[str] = None) -> EmailMessage:
    """Assemble a proper EmailMessage (text, an optional html alternative, and an
    optional iCalendar invite). When ``ics`` is present it is attached as
    ``text/calendar; method=REQUEST`` — the MIME type Gmail/Apple/Outlook read to
    show an "Add to calendar" card and drop the event on the recipient's calendar,
    so a calendar block appears with no Google-API connection required."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    if ics:
        # The calendar goes in TWICE, and the first one is the one that matters.
        #
        # As an ALTERNATIVE part: text/calendar; method=REQUEST, with no
        # Content-Disposition. That is the shape Google Calendar and Outlook
        # themselves send, and the shape Gmail/Apple/Outlook read as an INVITATION —
        # the thing that produces an RSVP card and drops the event on the
        # recipient's calendar.
        #
        # It used to be added with add_attachment(), which stamps
        # `Content-Disposition: attachment; filename="invite.ics"`. A calendar part
        # marked as an attachment is a FILE: the client offers to download it, and
        # no block ever appears on anyone's calendar. The invite was being built
        # correctly, sent correctly, and then presented as a download.
        msg.add_alternative(ics, subtype="calendar")
        cal = msg.get_payload()[-1]
        cal.set_param("method", "REQUEST")
        cal.set_param("charset", "UTF-8")
        del cal["Content-Disposition"]
        # ...and again as a real file, for the clients that only look for one. This
        # is the fallback, which is why it is second and why it is application/ics:
        # a second text/calendar part would compete with the invitation above.
        msg.add_attachment(ics.encode("utf-8"), maintype="application", subtype="ics",
                           filename="invite.ics")
    return msg


def _send_smtp(to: str, subject: str, text: str, html: Optional[str],
               ics: Optional[str] = None) -> str:
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

    msg = _build_message(to, subject, text, html, sender, ics)
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


def branded_html(base_url: str, body_text: str, *, footer: str = "Chordential · original, clearance-certified music.") -> str:
    """Wrap a plain-text email body in the Chordential-branded HTML shell:
    wordmark logo, brand palette, a simple card. Plain hex colors (not the
    site's oklch() custom properties) since email client CSS support is
    much narrower than a browser's. ``base_url`` must be an absolute
    origin (e.g. https://chordential.com) — a relative image path is dead
    in a mail client.

    Every recruiting/outreach/capabilities-doc email shares this ONE shell
    so they read as the same studio, not three different tools bolted
    together."""
    # Linkify bare URLs into real <a> tags BEFORE escaping the rest — many mobile HTML mail
    # clients do NOT auto-detect plain-text URLs inside HTML, so an un-tagged link simply
    # won't open. Split on URLs, escape the non-URL parts, wrap the URLs.
    import re as _re
    parts = _re.split(r"(https?://[^\s<>\"]+)", body_text or "")
    out = []
    for i, seg in enumerate(parts):
        if i % 2 == 1:   # a URL
            safe = _html.escape(seg, quote=True)
            out.append(f'<a href="{safe}" style="color:#C8552B;font-weight:bold" '
                       f'target="_blank" rel="noopener">{safe}</a>')
        else:
            out.append(_html.escape(seg).replace("\n", "<br>"))
    escaped = "".join(out)
    logo = f"{base_url.rstrip('/')}/static/public/wordmark-dark.png"
    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:32px 16px;background:#FCF7F8;
             font-family:Georgia,'Times New Roman',serif;">
  <div style="max-width:560px;margin:0 auto;">
    <img src="{logo}" alt="Chordential" height="26"
         style="height:26px;width:auto;display:block;margin:0 0 24px">
    <div style="background:#fff;border:1px solid #D8CDB6;border-radius:12px;
                padding:28px 30px;color:#1F1E1E;font-size:15px;line-height:1.65;">
      {escaped}
    </div>
    <p style="color:#737469;font-size:12px;margin:20px 4px 0">{_html.escape(footer)}</p>
  </div>
</body>
</html>"""


def send_email(to: str, subject: str, text: str, html: Optional[str] = None,
               ics: Optional[str] = None) -> str:
    """Send one email, best-effort. NEVER raises.

    Returns ``"sent"`` (handed to SMTP), ``"logged"`` (null/unconfigured — recorded
    intent, sent nothing), or ``"error"`` (an exception was swallowed). The default
    provider is **null**, so out of the box this is a no-op log."""
    to = (to or "").strip()
    if not to:
        return "error"
    try:
        # Gate on the FULL config (provider + host + from), not just the provider
        # switch: a half-set env (e.g. provider=smtp but no host yet) must be a
        # clean no-op, never a blind connection attempt that could hang.
        if mail_configured():
            return _send_smtp(to, subject, text, html, ics)
        # Null / unconfigured provider (default): log the intent, send nothing.
        logger.info("mailer(null): would send to=%s subject=%r", to, subject)
        return "logged"
    except Exception:  # noqa: BLE001 — defensive; send_email must never raise
        logger.exception("mailer: send to %s crashed", to)
        return "error"


def _public_base() -> str:
    """Absolute origin for branded-email assets/links (mirrors the web app's
    ``CHORDENTIAL_PUBLIC_DOMAIN``); chordential.com by default."""
    return (os.environ.get("CHORDENTIAL_PUBLIC_DOMAIN")
            or "https://chordential.com").strip().rstrip("/")


def intake_ack_body(name: str) -> tuple:
    """Subject + plain-text body for the automated acknowledgment sent after ANY
    inbound client intake (project questionnaire, book-a-call, discovery request).
    The greeting uses the first name they entered; blank falls back to a warm
    generic. Copy is fixed by the owner — keep it verbatim."""
    raw = (name or "").strip()
    first = raw.split()[0] if raw else "there"
    subject = "Thanks for reaching out to Chordential"
    body = (
        f"Hi {first},\n\n"
        "Thanks for reaching out. We've received your request and are reviewing "
        "your project. We'll take a look at what you've shared and follow up with "
        "the most appropriate next step.\n\n"
        "If a discovery conversation makes sense, we'll reach out with a few "
        "proposed meeting times based on our availability.\n\n"
        "If there's anything else you'd like us to know in the meantime, simply "
        "reply to this email.\n\n"
        "We appreciate the opportunity and look forward to connecting.\n\n"
        "Best,\nJon Shipp"
    )
    return subject, body


def send_intake_ack(to: str, name: str = "") -> str:
    """Send the intake acknowledgment to the client. Best-effort, NEVER raises;
    a no-op (logged) until an SMTP provider is configured, like every seam here.
    Safe to fire-and-forget off the request thread."""
    to = (to or "").strip()
    if not to:
        return "error"
    subject, body = intake_ack_body(name)
    return send_email(to, subject, body, html=branded_html(_public_base(), body))


__all__ = [
    "send_email", "mail_configured", "branded_html",
    "intake_ack_body", "send_intake_ack", "PROVIDER_ENV",
]
