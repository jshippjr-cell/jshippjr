"""Zoom meeting provider (one implementation of the MeetingProvider seam).

Creates a Zoom meeting via Server-to-Server OAuth. Real HTTP is credential-gated: with the
Zoom env unset the provider is never selected (the __init__ selector returns Null), and if
selected without credentials it raises a clear, honest error instead of pretending. Wiring the
live API touches only this file — Campaign Intake and Campaign Intelligence never change.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .base import MeetingProvider, ScheduledMeeting

_TOKEN_URL = "https://zoom.us/oauth/token"
_API = "https://api.zoom.us/v2"


class ZoomMeetingProvider(MeetingProvider):
    name = "zoom"

    def __init__(self) -> None:
        self.account_id = os.environ.get("CHORDENTIAL_ZOOM_ACCOUNT_ID", "").strip()
        self.client_id = os.environ.get("CHORDENTIAL_ZOOM_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("CHORDENTIAL_ZOOM_CLIENT_SECRET", "").strip()
        self.timeout = 20

    def configured(self) -> bool:
        return bool(self.account_id and self.client_id and self.client_secret)

    def create(self, *, topic: str, start_at: str, duration_min: int,
               attendees: list) -> ScheduledMeeting:
        """Create a scheduled Zoom meeting via Server-to-Server OAuth. ``start_at`` is an ISO
        UTC string. Returns join + start URLs. NOTE (honest): built against Zoom's documented
        API; verified live on first real call — any tweak stays in this file."""
        if not self.configured():
            raise RuntimeError(
                "Zoom provider selected but CHORDENTIAL_ZOOM_* credentials are unset — "
                "set them or use the manual (null) provider.")
        token = self._token()
        body = {
            "topic": topic or "Discovery call",
            "type": 2,                                   # scheduled meeting
            "start_time": _zoom_time(start_at),
            "duration": duration_min or 30,
            "timezone": "UTC",
            "settings": {"join_before_host": True, "waiting_room": False,
                         "auto_recording": "none"},
        }
        req = urllib.request.Request(
            f"{_API}/users/me/meetings", data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode())
        return ScheduledMeeting(
            external_meeting_id=str(data.get("id") or ""),
            join_url=str(data.get("join_url") or ""),
            host_url=str(data.get("start_url") or ""), provider="zoom")

    def _token(self) -> str:
        creds = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()).decode()
        data = urllib.parse.urlencode(
            {"grant_type": "account_credentials", "account_id": self.account_id}).encode()
        req = urllib.request.Request(
            _TOKEN_URL, data=data, method="POST",
            headers={"Authorization": f"Basic {creds}",
                     "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return str(json.loads(r.read().decode()).get("access_token") or "")


def _zoom_time(start_at: str) -> str:
    """Normalize an ISO start into Zoom's 'YYYY-MM-DDTHH:MM:SSZ' UTC form."""
    try:
        dt = datetime.fromisoformat((start_at or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return start_at or ""
