"""Gmail access for the Signal Engine's agentic triage (Phase B1).

Reads candidate alert emails so an agent can decide which are real
opportunities — the recall play for a starving funnel. The Google client
libraries are imported lazily and only when actually talking to Gmail, so the
core app and CI/sandbox (egress blocked, libs absent) never depend on them.
Everything is best-effort: a failure records ``last_error()`` and returns
empty rather than raising.

Setup (Render env / secrets):
  CHORDENTIAL_GMAIL_CLIENT_ID
  CHORDENTIAL_GMAIL_CLIENT_SECRET
  CHORDENTIAL_GMAIL_REFRESH_TOKEN
  CHORDENTIAL_GMAIL_LABEL    (optional Gmail label/search; default "Chordential/Alerts")

The refresh token is minted once via Google's OAuth consent flow with the
``gmail.modify`` scope (read + label). See docs/gmail-triage-setup.md.
"""
from __future__ import annotations

import base64
import os
from typing import List, Optional

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_LAST_ERROR = ""


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def label() -> str:
    return _env("CHORDENTIAL_GMAIL_LABEL") or "Chordential/Alerts"


def is_configured() -> bool:
    """True when the OAuth refresh-token trio is present — i.e. triage *could*
    read Gmail. Does not prove the libraries are installed (that surfaces as a
    last_error() on first use)."""
    return bool(
        _env("CHORDENTIAL_GMAIL_CLIENT_ID")
        and _env("CHORDENTIAL_GMAIL_CLIENT_SECRET")
        and _env("CHORDENTIAL_GMAIL_REFRESH_TOKEN")
    )


def last_error() -> str:
    return _LAST_ERROR


def _service():
    """Build a Gmail API client from the stored refresh token. Lazy-imports the
    Google libraries (Render-only) so their absence never breaks the app."""
    from google.oauth2.credentials import Credentials      # lazy — Render-only
    from googleapiclient.discovery import build             # lazy — Render-only

    creds = Credentials(
        None,
        refresh_token=_env("CHORDENTIAL_GMAIL_REFRESH_TOKEN"),
        client_id=_env("CHORDENTIAL_GMAIL_CLIENT_ID"),
        client_secret=_env("CHORDENTIAL_GMAIL_CLIENT_SECRET"),
        token_uri=_TOKEN_URI,
        scopes=_SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def list_candidates(limit: int = 25) -> List[dict]:
    """Unread messages under the alerts label — the triage queue. Returns a list
    of ``{"id", "thread_id"}``; empty (with last_error set) on any failure."""
    global _LAST_ERROR
    if not is_configured():
        return []
    try:
        svc = _service()
        q = f"label:{label()} is:unread"
        resp = (
            svc.users().messages()
            .list(userId="me", q=q, maxResults=max(1, min(limit, 100)))
            .execute()
        )
        _LAST_ERROR = ""
        return [
            {"id": m.get("id"), "thread_id": m.get("threadId")}
            for m in resp.get("messages", [])
            if m.get("id")
        ]
    except Exception as e:                                  # noqa: BLE001 — best-effort
        _LAST_ERROR = f"{type(e).__name__}: {e}"[:240]
        return []


def get_message(message_id: str) -> dict:
    """Fetch one message, normalized to ``{id, sender, subject, date, body}``.
    Body is the decoded text/plain part (falls back to the snippet)."""
    global _LAST_ERROR
    try:
        svc = _service()
        msg = (
            svc.users().messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        payload = msg.get("payload", {}) or {}
        headers = {h.get("name", "").lower(): h.get("value", "")
                   for h in payload.get("headers", [])}
        body = _extract_text(payload) or msg.get("snippet", "") or ""
        _LAST_ERROR = ""
        return {
            "id": message_id,
            "sender": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "body": body,
        }
    except Exception as e:                                  # noqa: BLE001 — best-effort
        _LAST_ERROR = f"{type(e).__name__}: {e}"[:240]
        return {"id": message_id, "sender": "", "subject": "", "date": "", "body": ""}


def mark_processed(message_id: str) -> bool:
    """Remove UNREAD so a triaged message leaves the queue (the list query is
    ``is:unread``). Idempotency at the source; the DB dedup is the backstop."""
    global _LAST_ERROR
    try:
        svc = _service()
        svc.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        _LAST_ERROR = ""
        return True
    except Exception as e:                                  # noqa: BLE001 — best-effort
        _LAST_ERROR = f"{type(e).__name__}: {e}"[:240]
        return False


def _extract_text(payload: dict) -> Optional[str]:
    """Walk a MIME tree for the first text/plain part and base64url-decode it."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    data = body.get("data")
    if mime == "text/plain" and data:
        return _b64(data)
    for part in payload.get("parts", []) or []:
        found = _extract_text(part)
        if found:
            return found
    # No text/plain anywhere — fall back to any html part, stripped of tags.
    if mime == "text/html" and data:
        import re
        return re.sub(r"<[^>]+>", " ", _b64(data))
    return None


def _b64(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return ""
