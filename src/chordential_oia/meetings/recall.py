"""Recall.ai capture provider (one implementation of the CaptureProvider seam).

Recall is a unified meeting-bot API: one adapter covers Zoom/Meet/Teams. It joins a meeting
URL, records, and posts a webhook when the transcript is ready. This class is the ONE place
Recall's payloads are understood; it normalizes them into provider-agnostic MeetingEvents /
Transcripts, so Campaign Intake stays coupled only to the Meeting domain.

Live HTTP (invite/fetch) is credential-gated. ``parse_webhook`` verifies the shared secret and
normalizes the event shape — the deterministic part that CAN be exercised without the network.
"""
from __future__ import annotations

import hmac
import json
import os
from hashlib import sha256
from typing import Mapping, Optional

from .base import (EV_FAILED, EV_IGNORED, EV_TRANSCRIPT_READY, CaptureProvider,
                   MeetingEvent, Transcript, TranscriptSegment)


class RecallCaptureProvider(CaptureProvider):
    name = "recall"

    def __init__(self) -> None:
        self.api_key = os.environ.get("CHORDENTIAL_RECALL_API_KEY", "").strip()
        self.webhook_secret = os.environ.get("CHORDENTIAL_RECALL_WEBHOOK_SECRET", "").strip()

    def configured(self) -> bool:
        return bool(self.api_key)

    def invite(self, *, join_url: str, meeting_ref: str) -> str:
        if not self.configured():
            raise RuntimeError(
                "Recall provider selected but CHORDENTIAL_RECALL_API_KEY is unset.")
        # Live: POST /bot {meeting_url, ...} → bot id. Deferred until credentials exist.
        raise NotImplementedError(
            "Recall API call not wired yet — connect a key to enable auto-capture.")

    def fetch_transcript(self, external_ref: str) -> Optional[Transcript]:
        if not self.configured():
            return None
        raise NotImplementedError("Recall transcript fetch not wired yet.")

    def parse_webhook(self, headers: Mapping, body: bytes) -> MeetingEvent:
        """Verify the shared secret, then normalize Recall's event into a MeetingEvent.
        Unverified or irrelevant → EV_IGNORED (never trust an unsigned payload)."""
        if self.webhook_secret:
            sig = (headers.get("x-recall-signature") or headers.get("X-Recall-Signature") or "")
            expected = hmac.new(self.webhook_secret.encode(), body, sha256).hexdigest()
            if not sig or not hmac.compare_digest(str(sig), expected):
                return MeetingEvent(type=EV_IGNORED)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return MeetingEvent(type=EV_IGNORED)
        event = str(payload.get("event") or "")
        data = payload.get("data") or {}
        bot_id = str(data.get("bot_id") or payload.get("bot_id") or "")
        raw_id = str(payload.get("id") or payload.get("event_id") or "")
        if event in ("transcript.done", "bot.done", "recording.done"):
            return MeetingEvent(type=EV_TRANSCRIPT_READY, external_ref=bot_id,
                                raw_event_id=raw_id, transcript=_transcript_from(data, bot_id))
        if event in ("bot.fatal", "transcript.failed"):
            return MeetingEvent(type=EV_FAILED, external_ref=bot_id, raw_event_id=raw_id,
                                error=str(data.get("error") or "capture failed"))
        return MeetingEvent(type=EV_IGNORED, external_ref=bot_id, raw_event_id=raw_id)


def _transcript_from(data: Mapping, bot_id: str) -> Optional[Transcript]:
    """Normalize Recall's transcript payload (if inlined) into the domain Transcript."""
    raw = data.get("transcript") or data.get("segments")
    if not raw:
        return None
    segs, speakers, parts = [], [], []
    for s in raw:
        spk = str(s.get("speaker") or s.get("speaker_name") or "")
        text = str(s.get("text") or "")
        segs.append(TranscriptSegment(speaker=spk, t0=float(s.get("start_time") or 0),
                                      t1=float(s.get("end_time") or 0), text=text))
        if spk and spk not in speakers:
            speakers.append(spk)
        parts.append(text)
    return Transcript(text=" ".join(p for p in parts if p), segments=segs,
                      speakers=speakers, provider="recall", external_ref=bot_id,
                      duration_s=int(segs[-1].t1) if segs else None)
