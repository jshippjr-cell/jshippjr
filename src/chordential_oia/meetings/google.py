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
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

from .calendar import CalendarProvider, Interval

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CAL_BASE = "https://www.googleapis.com/calendar/v3"
_SCOPES = ["https://www.googleapis.com/auth/calendar"]

_log = logging.getLogger("chordential.google_calendar")


def _load_service_account() -> Tuple[Optional[dict], str]:
    """The service-account key as ``(info, problem)``. Accepts raw JSON or base64-wrapped
    JSON (Render env vars are single-line; base64 sidesteps the newlines in the PEM private
    key), or a file path via CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_FILE.

    A key that is SET BUT UNREADABLE returns a problem string rather than None, because
    those two states are not the same thing and treating them as one is how a fixed problem
    quietly un-fixed itself. The operator moved to a service account specifically to escape
    the 7-day OAuth expiry; if the key fails to parse, `None` made it indistinguishable
    from "no service account", `configured()` fell through to the leftover OAuth variables,
    and the app went back to the very token that had been retired — while the page reported
    a connected calendar and Google answered 400. Silence turned a typo into a regression
    of something already solved.
    """
    raw = os.environ.get("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    where = "CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON"
    if not raw:
        path = os.environ.get("CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
        if path:
            where = f"CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_FILE ({path})"
            if not os.path.exists(path):
                return None, f"{where} points at a file that does not exist"
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read().strip()
            except OSError as e:
                return None, f"{where} could not be read: {e}"
    if not raw:
        return None, ""                      # genuinely not configured — the OAuth path is fine
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError:
        pass
    try:
        info = json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None, (
            f"{where} is set but is neither valid JSON nor base64 of valid JSON "
            f"({len(raw)} characters). The usual causes are a truncated paste and pasting "
            f"the key file raw — its private key contains newlines, which an env var drops. "
            f"Re-do it as `base64 -w0 key.json` and paste the single line.")
    if not isinstance(info, dict) or not info.get("private_key"):
        return None, f"{where} decoded but carries no private_key — is it the right file?"
    return info, ""


class GoogleCalendarProvider(CalendarProvider):
    name = "google"

    def __init__(self) -> None:
        self.client_id = os.environ.get("CHORDENTIAL_GOOGLE_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("CHORDENTIAL_GOOGLE_CLIENT_SECRET", "").strip()
        self.refresh_token = os.environ.get("CHORDENTIAL_GOOGLE_REFRESH_TOKEN", "").strip()
        self.calendar_id = (os.environ.get("CHORDENTIAL_GOOGLE_CALENDAR_ID", "")
                            or "primary").strip()
        self.sa_info, self.sa_problem = _load_service_account()
        self.timeout = 20
        if self.sa_problem:
            _log.error("Google Calendar: %s", self.sa_problem)

    def _use_sa(self) -> bool:
        return bool(self.sa_info)

    def auth_mode(self) -> str:
        """``service_account`` | ``oauth`` | ``broken`` | ``none`` — which credential is
        actually in play, which is not always the one that was configured."""
        if self.sa_info:
            return "service_account"
        if self.sa_problem:
            return "broken"
        if self.client_id and self.client_secret and self.refresh_token:
            return "oauth"
        return "none"

    def config_problem(self) -> str:
        """What is wrong with this configuration, in words, or ``""``."""
        if self.sa_problem:
            extra = (" The legacy OAuth variables are still set, and they are NOT being used"
                     " as a fallback: silently going back to the token you retired is how"
                     " this looked fixed while it was not. Fix the key, or clear"
                     " CHORDENTIAL_GOOGLE_SERVICE_ACCOUNT_JSON to use OAuth deliberately."
                     if (self.client_id and self.client_secret and self.refresh_token) else "")
            return self.sa_problem + extra
        return ""

    def configured(self) -> bool:
        """A BROKEN service-account key does not fall back to OAuth.

        It used to, and that is the whole failure: the operator moved to a service account
        to escape the 7-day OAuth expiry, the key did not parse, and the app quietly resumed
        using the expired refresh token — reporting a connected calendar the entire time.
        A stated intent that cannot be honoured must not degrade into the thing it replaced
        (the same rule `signing_providers` follows). Booking is unaffected either way: with
        no native event the emailed .ics is the route to both calendars."""
        if self.sa_problem:
            return False
        return bool(self.sa_info) or bool(
            self.client_id and self.client_secret and self.refresh_token)

    def invites_attendees(self) -> bool:
        """Only the OAuth path invites guests. A service account acts as ITSELF, and a
        consumer calendar will not let it add attendees without domain-wide delegation —
        so `create_event` deliberately sends none, and the client's invitation has to
        come from our own .ics. Saying so here is what stops the scheduler suppressing it."""
        return bool(self.configured()) and not self._use_sa()

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
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return str(json.loads(r.read().decode()).get("access_token") or "")
        except urllib.error.HTTPError as e:
            # The single most likely failure on this path, and it presented as an
            # unexplained 400: a refresh token minted while the Google app is in "Testing"
            # publishing status is revoked after 7 days. Google says exactly that in the
            # body — "invalid_grant: Token has been expired or revoked" — so say it.
            raise GoogleCalendarError(
                _http_reason(e, _TOKEN_URL)
                + (". A refresh token from an app in Testing status expires after 7 days"
                   " — switch to the service account (docs/discovery-setup-guide.md §3-SA),"
                   " which never expires."
                   if getattr(e, "code", 0) == 400 else "")) from e

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json", "Accept": "application/json"}

    def _post(self, url: str, payload: dict):
        return self._request(url, method="POST", payload=payload)

    def _request(self, url: str, *, method: str, payload: Optional[dict] = None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode() or "{}"
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            raise GoogleCalendarError(_http_reason(e, url)) from e


class GoogleCalendarError(RuntimeError):
    """A refusal from Google, carrying the reason Google actually gave."""


def _http_reason(e, url: str = "") -> str:
    """Google's own explanation, which `HTTPError` throws away.

    `str(HTTPError)` is "HTTP Error 400: Bad Request" and nothing else — the reason is in
    the RESPONSE BODY, which urllib does not read for you. That is how a dead OAuth refresh
    token ("invalid_grant: Token has been expired or revoked") reached the operator's screen
    as a generic 400 that named neither the problem nor the fix. Every field Google uses for
    the reason is checked, because the token endpoint and the Calendar API do not answer in
    the same shape."""
    body = ""
    try:
        body = (e.read() or b"").decode("utf-8", "replace")[:600]
    except Exception:  # noqa: BLE001 — a body we cannot read must not mask the status
        body = ""
    detail = ""
    try:
        parsed = json.loads(body) if body.strip().startswith("{") else {}
        err = parsed.get("error")
        if isinstance(err, dict):                       # Calendar API shape
            detail = str(err.get("message") or "")
            errs = err.get("errors") or []
            if not detail and errs:
                detail = str((errs[0] or {}).get("message") or "")
        elif isinstance(err, str):                      # OAuth token endpoint shape
            detail = ": ".join(x for x in (err, parsed.get("error_description")) if x)
    except Exception:  # noqa: BLE001
        detail = ""
    where = "the token endpoint" if _TOKEN_URL in (url or "") else "Calendar"
    if not detail:
        detail = body.strip()[:200] or "no reason given"
    return f"Google {where} refused ({getattr(e, 'code', '?')}): {detail}"


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
