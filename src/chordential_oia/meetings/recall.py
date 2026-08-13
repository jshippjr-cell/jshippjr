"""Recall.ai capture provider (one implementation of the CaptureProvider seam).

Recall is a unified meeting-bot API: one adapter covers Zoom/Meet/Teams. It joins a meeting
URL, records, transcribes, and exposes the transcript. This class is the ONE place Recall's
API + payloads are understood; it normalizes everything into provider-agnostic Transcripts /
MeetingEvents, so Campaign Intake stays coupled only to the Meeting domain.

Two ways to get the transcript back, both handled here:
  • POLLING (default, webhook-free): ``fetch_transcript`` checks the bot's status and pulls the
    transcript when it's done. The scheduler drives this — the only setup is the API key.
  • WEBHOOK (optional): ``parse_webhook`` verifies + normalizes a pushed event for instant
    ingest. Not required; kept for when low latency matters.

Config (env; the seam is null until a key is set):
  CHORDENTIAL_RECALL_API_KEY          — required to make any live call
  CHORDENTIAL_RECALL_REGION           — API region, default "us-east-1"
  CHORDENTIAL_RECALL_BOT_NAME         — the bot's display name in the call
  CHORDENTIAL_RECALL_TRANSCRIPT_PROVIDER — Recall transcription provider (default
                                        recallai_streaming; meeting_captions needs the host's
                                        captions ON and silently yields nothing when they are off)
  CHORDENTIAL_RECALL_LANGUAGE         — transcription language, default "auto"
  CHORDENTIAL_RECALL_WEBHOOK_SECRET   — only if you opt into the webhook path

WHY THE DEFAULT IS RECALL'S OWN ASR (and not the platform's captions):
``meeting_captions`` transcribes by reading the *meeting platform's* closed captions. It is
the cheapest option and it was this file's default — but it only works if the HOST has
captions switched on. When they are off the bot still joins, still records, still reaches
``done``, and simply never produces a transcript. Recall's own docs name this as the usual
cause of "the bot didn't generate a transcript". Nothing surfaced it: no error, no failed
state, just a discovery call whose notes never arrived.

So the default is ``recallai_streaming`` — Recall's native speech-to-text. It needs no
third-party key and no cooperation from the host's Zoom settings. ``fetch_transcript`` also
REPAIRS the older case: a finished recording with no transcript artifact is asked for one
via the async ASR endpoint, which is how a call already recorded under meeting_captions
still gets its notes.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import urllib.error
import urllib.request
from hashlib import sha256
from typing import Mapping, Optional

from .base import (EV_FAILED, EV_IGNORED, EV_TRANSCRIPT_READY, CaptureProvider,
                   MeetingEvent, Transcript, TranscriptSegment)

_log = logging.getLogger("chordential.recall")

# Bot status codes that mean "recording finished, transcript should be available".
_DONE_CODES = {"done", "call_ended", "recording_done", "analysis_done", "transcript_done"}
_FATAL_CODES = {"fatal", "call_failed", "recording_failed"}


class RecallCaptureProvider(CaptureProvider):
    name = "recall"

    def __init__(self) -> None:
        self.api_key = os.environ.get("CHORDENTIAL_RECALL_API_KEY", "").strip()
        self.region = (os.environ.get("CHORDENTIAL_RECALL_REGION", "us-east-1")
                       or "us-east-1").strip()
        self.bot_name = (os.environ.get("CHORDENTIAL_RECALL_BOT_NAME", "")
                         or "Chordential Notetaker").strip()
        self.transcript_provider = (
            os.environ.get("CHORDENTIAL_RECALL_TRANSCRIPT_PROVIDER", "")
            or "recallai_streaming").strip()
        self.language = (os.environ.get("CHORDENTIAL_RECALL_LANGUAGE", "")
                         or "auto").strip()
        self.webhook_secret = os.environ.get("CHORDENTIAL_RECALL_WEBHOOK_SECRET", "").strip()
        self.timeout = 20

    # ── seam contract ─────────────────────────────────────────────────────────
    def configured(self) -> bool:
        return bool(self.api_key)

    def invite(self, *, join_url: str, meeting_ref: str) -> str:
        """Send a Recall bot into the meeting with transcription on. Returns the bot id.

        Recall's own ASR by default, because the platform-captions provider depends on a
        setting in someone else's Zoom account (see the module docstring) and fails silent."""
        if not self.configured():
            raise RuntimeError(
                "Recall provider selected but CHORDENTIAL_RECALL_API_KEY is unset.")
        payload = {
            "meeting_url": join_url,
            "bot_name": self.bot_name,
            "recording_config": {
                "transcript": {
                    "provider": {self.transcript_provider: self._provider_options()},
                    # who said what, when the platform gives us separate audio streams
                    "diarization": {"use_separate_streams_when_available": True},
                },
            },
        }
        data = self._post("/bot/", payload)
        return str((data or {}).get("id") or "")

    def _provider_options(self) -> dict:
        """The options object Recall expects INSIDE the chosen provider's key. Its shape is
        per-provider: the native ASR takes a mode + language, the platform-captions provider
        takes nothing. An unknown provider gets an empty object rather than a guess."""
        if self.transcript_provider == "recallai_streaming":
            return {"mode": "prioritize_accuracy", "language_code": self.language}
        if self.transcript_provider == "recallai_async":
            return {"language_code": self.language}
        return {}

    def fetch_transcript(self, external_ref: str) -> Optional[Transcript]:
        """POLLING: return the normalized transcript once the bot is done; None while it's still
        recording / not ready (so the scheduler simply tries again next tick). None on any error
        — a transient provider hiccup must never crash the loop."""
        if not self.configured() or not external_ref:
            return None
        try:
            bot = self._get(f"/bot/{external_ref}/")
        except Exception as e:  # noqa: BLE001 — treat as 'not ready yet', but say why
            _log.warning("Recall bot fetch failed for %s: %s", external_ref, e)
            return None
        codes = _bot_codes(bot)
        state = _bot_state(bot)
        _log.info("Recall bot %s state=%s codes=%s", external_ref, state, codes)
        if state != "done":
            return None            # still recording (or fatal) — poll again later
        # New Recall API: the legacy /bot/{id}/transcript/ is retired. The finished transcript
        # lives at a signed download_url on the bot's recording artifact — find it and fetch it.
        url = _transcript_download_url(bot)
        if not url:
            # Fallback: the bot may carry only a transcript ID → retrieve it (the endpoint the
            # legacy error pointed to: GET /transcript/{id}/) to get the signed download_url.
            tid = _transcript_id(bot)
            if tid:
                try:
                    meta = self._get(f"/transcript/{tid}/")
                    url = _transcript_download_url(meta) or str(
                        (meta.get("data") or {}).get("download_url") or "")
                except Exception as e:  # noqa: BLE001
                    _log.warning("Recall transcript retrieve failed for %s: %s", external_ref, e)
        if not url:
            # The recording finished and carries NO transcript artifact. That is the
            # meeting_captions failure: the host had captions off, so nothing was ever
            # transcribed. The audio still exists, so ask Recall's own ASR to transcribe
            # it now — this is what rescues a call whose notes would otherwise never come.
            rid = _recording_id(bot)
            if rid and self._request_async_transcript(rid):
                return None        # requested; a later poll picks up the download_url
            _log.warning("Recall bot %s done but no transcript download_url found; bot shape=%s",
                         external_ref, _summarize(bot))
            return None
        try:
            raw = self._download(url)
        except Exception as e:  # noqa: BLE001
            _log.warning("Recall transcript download failed for %s: %s", external_ref, e)
            return None
        t = _normalize_transcript(raw, external_ref)
        _log.info("Recall transcript for %s: %s", external_ref,
                  ("%d chars / %d speakers" % (len(t.text), len(t.speakers)))
                  if t else "downloaded but empty/unparseable (shape=%s)" % type(raw).__name__)
        return t

    def _request_async_transcript(self, recording_id: str) -> bool:
        """Ask Recall to transcribe an already-finished recording with its own ASR.

        POST /recording/{id}/create_transcript/. Best-effort and idempotent in practice:
        a second request for a recording that already has one is refused by Recall, which
        we log and treat as "nothing more to do" rather than an error — the poller is on a
        backoff, so this is attempted a bounded number of times."""
        try:
            self._post(f"/recording/{recording_id}/create_transcript/",
                       {"provider": {"recallai_async": {"language_code": self.language}}})
        except Exception as e:  # noqa: BLE001 — never raise into the poll loop
            _log.info("Recall async transcript not created for recording %s: %s",
                      recording_id, e)
            return False
        _log.info("Recall async transcript requested for recording %s "
                  "(no transcript existed — likely captions were off during the call)",
                  recording_id)
        return True

    def parse_webhook(self, headers: Mapping, body: bytes) -> MeetingEvent:
        """Verify the shared secret, then normalize Recall's pushed event into a MeetingEvent.
        Unverified or irrelevant → EV_IGNORED (never trust an unsigned payload)."""
        if self.webhook_secret:
            sig = (headers.get("x-recall-signature")
                   or headers.get("X-Recall-Signature") or "")
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
                                raw_event_id=raw_id, transcript=_normalize_transcript(
                                    data.get("transcript") or data.get("segments"), bot_id))
        if event in ("bot.fatal", "transcript.failed"):
            return MeetingEvent(type=EV_FAILED, external_ref=bot_id, raw_event_id=raw_id,
                                error=str(data.get("error") or "capture failed"))
        return MeetingEvent(type=EV_IGNORED, external_ref=bot_id, raw_event_id=raw_id)

    # ── HTTP (stdlib; runs off the event loop / in the scheduler thread) ────────
    def _base(self) -> str:
        return f"https://{self.region}.recall.ai/api/v1"

    def _headers(self) -> dict:
        return {"Authorization": f"Token {self.api_key}", "Content-Type": "application/json",
                "Accept": "application/json"}

    def _open(self, req):
        """Open a request and surface Recall's ERROR BODY on 4xx/5xx — the body says exactly
        which field it rejected (a bare 'HTTP 400' is useless for debugging)."""
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8") or "{}"
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "ignore")[:600]
            except Exception:  # noqa: BLE001
                body = ""
            raise RuntimeError(f"Recall HTTP {e.code} at {req.full_url}: {body}") from None

    def _get(self, path: str):
        return self._open(urllib.request.Request(self._base() + path, headers=self._headers()))

    def _post(self, path: str, payload: dict):
        return self._open(urllib.request.Request(
            self._base() + path, data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(), method="POST"))

    def _download(self, url: str):
        """Fetch a signed transcript download URL (no API auth — the signature is in the URL)."""
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "ignore")[:400]
            except Exception:  # noqa: BLE001
                body = ""
            raise RuntimeError(f"download HTTP {e.code}: {body}") from None


# ── new-API transcript retrieval helpers ─────────────────────────────────────
def _transcript_download_url(bot) -> str:
    """Find the transcript's signed download_url anywhere under a 'transcript' key in the bot
    object (recordings[].media_shortcuts.transcript.data.download_url, tolerant of nesting)."""
    def walk(obj, under_transcript=False):
        if isinstance(obj, dict):
            if under_transcript:
                dl = obj.get("download_url")
                if isinstance(dl, str) and dl:
                    return dl
            for k, v in obj.items():
                u = walk(v, under_transcript or k == "transcript")
                if u:
                    return u
        elif isinstance(obj, list):
            for v in obj:
                u = walk(v, under_transcript)
                if u:
                    return u
        return ""
    return walk(bot) or ""


def _recording_id(bot) -> str:
    """The finished recording's id — what the async-transcript endpoint is addressed by.
    Recall has carried it as ``recordings[]`` and (older) ``recording``; take the first
    id we find under either."""
    if not isinstance(bot, dict):
        return ""
    recs = bot.get("recordings")
    if isinstance(recs, list):
        for r in recs:
            if isinstance(r, dict) and r.get("id"):
                return str(r["id"])
    rec = bot.get("recording")
    if isinstance(rec, dict) and rec.get("id"):
        return str(rec["id"])
    if isinstance(rec, str) and rec:
        return rec
    return ""


def _transcript_id(bot) -> str:
    """Find a transcript artifact id under a 'transcript' key (for the /transcript/{id}/ call)."""
    def walk(obj, under_transcript=False):
        if isinstance(obj, dict):
            if under_transcript and obj.get("id"):
                return str(obj["id"])
            for k, v in obj.items():
                u = walk(v, under_transcript or k == "transcript")
                if u:
                    return u
        elif isinstance(obj, list):
            for v in obj:
                u = walk(v, under_transcript)
                if u:
                    return u
        return ""
    return walk(bot) or ""


def _summarize(bot) -> str:
    """A compact shape hint for the logs when we can't find the transcript URL."""
    if not isinstance(bot, dict):
        return type(bot).__name__
    recs = bot.get("recordings")
    rec0 = (recs[0] if isinstance(recs, list) and recs else {})
    return "top_keys=%s recording_keys=%s" % (
        list(bot.keys()), list(rec0.keys()) if isinstance(rec0, dict) else type(rec0).__name__)


# ── normalization helpers (defensive across Recall's shape variants) ──────────
def _bot_codes(bot) -> list:
    """Every status code a Recall bot object reports (status_changes[].code + top-level
    status), lower-cased — logged so we can see exactly what Recall calls 'done'."""
    if not isinstance(bot, dict):
        return []
    codes = []
    for sc in (bot.get("status_changes") or []):
        if isinstance(sc, dict) and sc.get("code"):
            codes.append(str(sc["code"]).lower())
    for key in ("status", "state"):
        top = str(bot.get(key) or "").lower()
        if top:
            codes.append(top)
    status = bot.get("status_change") or bot.get("latest_status")  # some shapes nest it
    if isinstance(status, dict) and status.get("code"):
        codes.append(str(status["code"]).lower())
    return codes


def _bot_state(bot) -> str:
    """Reduce a Recall bot object to done | fatal | pending, tolerant of its shape."""
    codes = _bot_codes(bot)
    if any(c in _FATAL_CODES for c in codes):
        return "fatal"
    if any(c in _DONE_CODES for c in codes):
        return "done"
    return "pending"


def _ts(value) -> float:
    """A timestamp field may be a float (seconds) or {'relative': 1.2} / {'absolute': …}."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ("relative", "seconds", "start", "value"):
            if isinstance(value.get(k), (int, float)):
                return float(value[k])
    return 0.0


def _normalize_transcript(raw, bot_id: str) -> Optional[Transcript]:
    """Normalize Recall's transcript into the domain Transcript. Tolerant of: a bare list or a
    dict wrapper ({transcript|segments|results|data:[…]}); a speaker as ``speaker``/
    ``speaker_name``/``participant.name``; a turn as ``words``[] OR a ``text`` string; and the
    several timestamp encodings Recall has used."""
    if isinstance(raw, dict):
        raw = (raw.get("transcript") or raw.get("segments") or raw.get("results")
               or raw.get("data") or raw.get("monologues") or [])
    if not raw or not isinstance(raw, list):
        return None
    segs, speakers, parts = [], [], []
    for turn in raw:
        if not isinstance(turn, dict):
            continue
        part = turn.get("participant") if isinstance(turn.get("participant"), dict) else {}
        spk = str(turn.get("speaker") or turn.get("speaker_name")
                  or part.get("name") or "").strip()
        words = turn.get("words")
        if isinstance(words, list) and words:
            text = " ".join(str(w.get("text", "")) for w in words if isinstance(w, dict)).strip()
            t0 = _ts(words[0].get("start_timestamp") or words[0].get("start_time")
                     or words[0].get("start"))
            last = words[-1]
            t1 = _ts(last.get("end_timestamp") or last.get("end_time") or last.get("end"))
        else:
            text = str(turn.get("text") or "").strip()
            t0 = _ts(turn.get("start_timestamp") or turn.get("start_time") or turn.get("start"))
            t1 = _ts(turn.get("end_timestamp") or turn.get("end_time") or turn.get("end"))
        if not text:
            continue
        segs.append(TranscriptSegment(speaker=spk, t0=t0, t1=t1, text=text))
        if spk and spk not in speakers:
            speakers.append(spk)
        parts.append(text)
    if not parts:
        return None
    return Transcript(text=" ".join(parts), segments=segs, speakers=speakers,
                      provider="recall", external_ref=bot_id,
                      duration_s=int(segs[-1].t1) if segs and segs[-1].t1 else None)
