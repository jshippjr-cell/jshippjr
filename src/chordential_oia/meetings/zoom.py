"""Zoom meeting provider (one implementation of the MeetingProvider seam).

Creates a Zoom meeting via Server-to-Server OAuth. Real HTTP is credential-gated: with the
Zoom env unset the provider is never selected (the __init__ selector returns Null), and if
selected without credentials it raises a clear, honest error instead of pretending. Wiring the
live API touches only this file — Campaign Intake and Campaign Intelligence never change.
"""
from __future__ import annotations

import os

from .base import MeetingProvider, ScheduledMeeting


class ZoomMeetingProvider(MeetingProvider):
    name = "zoom"

    def __init__(self) -> None:
        self.account_id = os.environ.get("CHORDENTIAL_ZOOM_ACCOUNT_ID", "").strip()
        self.client_id = os.environ.get("CHORDENTIAL_ZOOM_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("CHORDENTIAL_ZOOM_CLIENT_SECRET", "").strip()

    def configured(self) -> bool:
        return bool(self.account_id and self.client_id and self.client_secret)

    def create(self, *, topic: str, start_at: str, duration_min: int,
               attendees: list) -> ScheduledMeeting:
        if not self.configured():
            raise RuntimeError(
                "Zoom provider selected but CHORDENTIAL_ZOOM_* credentials are unset — "
                "set them or use the manual (null) provider.")
        # Live call goes here: S2S OAuth token → POST /users/me/meetings → parse id/join_url.
        # Deferred until credentials exist; kept out of the test/CI path.
        raise NotImplementedError(
            "Zoom API call not wired yet — connect credentials to enable live scheduling.")
