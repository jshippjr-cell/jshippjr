"""Google Calendar provider (one implementation of the CalendarProvider seam, ADR-0016).

Reads busy-time (freeBusy) and creates/updates/cancels events via the Calendar v3 API. Two auth
modes, tried in order:

  1. **Service account (recommended, never expires).** Set CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON
     to the service-account key (raw JSON or base64 of it) and share your calendar with the
     service-account email ("Make changes to events"); point CHORDENTIAL_GOOGLE_CALENDAR_ID at
     your address. No refresh token, no 7-day "Testing"-mode expiry — this is the durable fix for
     the recurring "auto-booking stopped" problem. Note: a service account can't INVITE guests on
     a consumer calendar without domain-wide delegation, so we drop the block on the operator's
     calendar only; the client is invited via our own confirmation email + .ics (mailer/scheduler).

  2. **OAuth refresh token (legacy).** CHORDENTIAL_GOOGLE_CLIENT_ID / _CLIENT_SECRET /
     _REFRESH_TOKEN act AS the operator's account, so Google natively invites the client too — but
     a token minted from an app in "Testing" publishing status EXPIRES AFTER 7 DAYS. Prefer mode 1.

All live HTTP is credential-gated: unset env → this class is never selected (the seam returns
Null). Service-account signing uses google-auth (the `gmail` extra); the refresh-token path is
stdlib urllib.

Env:
  CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON   — SA key, raw JSON or base64 (mode 1)
  CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_FILE   — path to the SA key file (alt to the above)
  CHORDENTIAL_GOOGLE_CLIENT_ID / _CLIENT_SECRET / _REFRESH_TOKEN   — mode 2
  CHORDENTIAL_GOOGLE_CALENDAR_ID            — default "primary"; for a service account set this to
                                              the shared calendar's address (e.g. your @gmail)
"""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

from .calendar import CalendarProvider, Interval

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CAL_BASE = "https://www.googleapis.com/calendar/v3"
_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _load_service_account() -> Optional[dict]:
    """The service-account key as a dict, or None. Accepts raw JSON or base64-wrapped JSON
    (Render env vars are single-line; base64 sidesteps the newlines in the PEM private key),
    or a file path via CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_FILE."""
    raw = os.environ.get("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        path = os.environ.get("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read().strip()
            except OSError:
                return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception:  # noqa: BLE001 — malformed key → treat as unconfigured, never crash
            return None


class GoogleCalendarProvider(CalendarProvider):
    name = "google"

    def __init__(self) -> None:
        self.client_id = os.environ.get("CHORDENTIAL_GOOGLE_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("CHORDENTIAL_GOOGLE_CLIENT_SECRET", "").strip()
        self.refresh_token = os.environ.get("CHORDENTIAL_GOOGLE_REFRESH_TOKEN", "").strip()
        self.calendar_id = (os.environ.get("CHORDENTIAL_GOOGLE_CALENDAR_ID", "")
                            or "primary").strip()
        self.sa_info = _load_service_account()
        self.timeout = 20

    def _use_sa(self) -> bool:
        return bool(self.sa_info)

    def configured(self) -> bool:
        return bool(self.sa_info) or bool(
            self.client_id and self.client_secret and self.refresh_token)

    # ── availability ────────────────────────────────────────────────────────
    def busy(self, start: datetime, end: datetime) -> List[Interval]:
        if not self.configured():
            return []
        try:
            body = {"timeMin": _iso(start), "timeMax": _iso(end),
                    "items": [{"id": self.calendar_id}]}
            data = self._post(f"{_CAL_BASE}/freeBusy", body)
            cals = (data.get("calendars") or {})
            entry = cals.get(self.calendar_id) or next(iter(cals.values()), {})
            out: List[Interval] = []
            for b in (entry.get("busy") or []):
                s, e = _parse(b.get("start")), _parse(b.get("end"))
                if s and e:
                    out.append((s, e))
            return out
        except Exception:  # noqa: BLE001 — a calendar hiccup must not break booking; treat as
            return []       # "no known busy" (the reserve-time guard still re-checks)

    # ── event lifecycle ──────────────────────────────────────────────────────
    def create_event(self, *, summary: str, description: str, start: datetime,
                      end: datetime, attendees: Sequence[str], location: str = "") -> str:
        if not self.configured():
            return ""
        body = {
            "summary": summary, "description": description, "location": location,
            "start": {"dateTime": _iso(start)}, "end": {"dateTime": _iso(end)},
        }
        if self._use_sa():
            # A service account can't invite guests on a consumer calendar without domain-wide
            # delegation — including attendees would 403 the whole create. So we drop the block
            # on the operator's calendar only; the client's invite rides our own .ics email.
            send = "none"
        else:
            body["attendees"] = [{"email": a} for a in attendees if a]
            send = "all"
        url = (f"{_CAL_BASE}/calendars/{urllib.parse.quote(self.calendar_id)}/events"
               f"?sendUpdates={send}")
        data = self._post(url, body)
        return str((data or {}).get("id") or "")

    def update_event(self, event_id: str, *, start: datetime, end: datetime) -> None:
        if not self.configured() or not event_id:
            return
        url = (f"{_CAL_BASE}/calendars/{urllib.parse.quote(self.calendar_id)}/events/"
               f"{urllib.parse.quote(event_id)}?sendUpdates=all")
        self._request(url, method="PATCH", payload={
            "start": {"dateTime": _iso(start)}, "end": {"dateTime": _iso(end)}})

    def delete_event(self, event_id: str) -> None:
        if not self.configured() or not event_id:
            return
        url = (f"{_CAL_BASE}/calendars/{urllib.parse.quote(self.calendar_id)}/events/"
               f"{urllib.parse.quote(event_id)}?sendUpdates=all")
        try:
            self._request(url, method="DELETE")
        except Exception:  # noqa: BLE001 — a cancel is best-effort; the record is authoritative
            pass

    # ── OAuth + HTTP ─────────────────────────────────────────────────────────
    def _access_token(self) -> str:
        if self.sa_info:
            # Service account: google-auth signs a JWT with the SA key and exchanges it for a
            # short-lived access token — no stored refresh token, so nothing to expire.
            from google.auth.transport.requests import Request  # lazy; gmail extra
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(
                self.sa_info, scopes=_SCOPES)
            creds.refresh(Request())
            return str(creds.token or "")
        data = urllib.parse.urlencode({
            "client_id": self.client_id, "client_secret": self.client_secret,
            "refresh_token": self.refresh_token, "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(_TOKEN_URL, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return str(json.loads(r.read().decode()).get("access_token") or "")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json", "Accept": "application/json"}

    def _post(self, url: str, payload: dict):
        return self._request(url, method="POST", payload=payload)

    def _request(self, url: str, *, method: str, payload: Optional[dict] = None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            raw = r.read().decode() or "{}"
            return json.loads(raw) if raw.strip() else {}


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None
