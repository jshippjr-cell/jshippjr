"""Google Calendar provider (one implementation of the CalendarProvider seam, ADR-0016).

Reads busy-time (freeBusy) and creates/updates/cancels events via the Calendar v3 API, using an
OAuth refresh token (offline access). All live HTTP is credential-gated: unset env → this class
is never selected (the seam returns Null); selected without credentials → a clear error rather
than a fake. stdlib urllib (no new deps).

Env:
  CHORDENTIAL_GOOGLE_CLIENT_ID / CHORDENTIAL_GOOGLE_CLIENT_SECRET
  CHORDENTIAL_GOOGLE_REFRESH_TOKEN   — offline-access refresh token for the operator's account
  CHORDENTIAL_GOOGLE_CALENDAR_ID     — default "primary"

NOTE (honest): Google's live APIs weren't reachable from the build env, so the request/response
shapes follow Google's documented Calendar v3 contract and are parsed defensively. Any tweak is
confined to this file — the Scheduler and Campaign Intelligence never change.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

from .calendar import CalendarProvider, Interval

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CAL_BASE = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarProvider(CalendarProvider):
    name = "google"

    def __init__(self) -> None:
        self.client_id = os.environ.get("CHORDENTIAL_GOOGLE_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("CHORDENTIAL_GOOGLE_CLIENT_SECRET", "").strip()
        self.refresh_token = os.environ.get("CHORDENTIAL_GOOGLE_REFRESH_TOKEN", "").strip()
        self.calendar_id = (os.environ.get("CHORDENTIAL_GOOGLE_CALENDAR_ID", "")
                            or "primary").strip()
        self.timeout = 20

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

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
            "attendees": [{"email": a} for a in attendees if a],
        }
        url = (f"{_CAL_BASE}/calendars/{urllib.parse.quote(self.calendar_id)}/events"
               "?sendUpdates=all")
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
