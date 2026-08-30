"""What the system sent, or would have sent.

**The gap this closes.** Twenty-seven call sites send mail and nothing recorded any of
them. On the null provider — the default, and what a rehearsal runs on — a send was one
line of ``logger.info`` carrying a recipient and a subject and no body at all. So two
questions had no answer from inside the product:

*"What does my client actually receive?"* The operator has never seen it. Every defect
found in the client's experience this month was found by sitting a real person in front
of a real screen; the emails were the one surface nobody could look at, because looking
meant configuring SMTP and mailing a real inbox.

*"Did the pay link go out, and to whom?"* Unanswerable. The send was best-effort and
silent by design, which is right for the request — a notification must never fail a
payment — and wrong for the record.

**Why the recorder is injected rather than imported.** ``mailer`` is the engine layer and
must not reach up into ``web`` (ADR-0044). So ``mailer`` exposes ``set_recorder`` and this
module installs it at boot, the same shape as ``room_view(build=…)`` and
``final_invoice_block(heal=…)``.

**The one rule this module must never break:** recording a send cannot fail a send. Every
path here swallows its own errors. An audit trail that can break the thing it audits is
worse than no audit trail — the same reasoning as ``_log_decision`` in ``app.py``.
"""

from __future__ import annotations

from typing import Optional

from . import db

#: Set while a rehearsal walk-through is running, so its messages can be told apart from
#: (and cleared without touching) real ones. A plain module global: it marks rows, and is
#: never the thing that decides whether a message may be sent.
_rehearsal = 0


def set_rehearsal(on: bool) -> None:
    global _rehearsal
    _rehearsal = 1 if on else 0


def _write(**kw) -> None:
    """One row, on its own connection. Called from a mail send that may be running in a
    fire-and-forget thread, so it never borrows the caller's."""
    conn = None
    try:
        conn = db.connect()
        db.record_outbound(conn, rehearsal=_rehearsal, **kw)
    except Exception:      # noqa: BLE001 — see the module docstring
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:      # noqa: BLE001
                pass


def _on_email(*, to: str = "", subject: str = "", text: str = "",
              html: Optional[str] = None, status: str = "",
              attachments: int = 0) -> None:
    _write(channel="email", recipient=to, subject=subject, body_text=text or "",
           body_html=html or "", status=status, attachments=attachments)


def record_alert(*, title: str, body: str = "", status: str = "",
                 channel: str = "push", url: str = "") -> None:
    """The alert side. A phone push has no recipient address — the topic or the
    subscription IS the address — so the channel carries that and `recipient` stays
    blank rather than inventing one."""
    _write(channel=channel, recipient="", subject=title, body_text=body or "",
           body_html="", status=status, attachments=0, url=url or "")


def install() -> None:
    """Point the engine's send hooks at this module. Idempotent; called once at boot."""
    from .. import mailer
    mailer.set_recorder(_on_email)
