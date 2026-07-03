"""The Meeting domain — providers abstracted behind seams (ADR-0015).

A **Meeting** is the business object. Zoom is only one way to *host* it; Recall.ai is only
one way to *capture* it. Two seams keep those choices swappable, and everything downstream
consumes the **Meeting** and a normalized **Transcript** — never a provider-specific event:

    Meeting → MeetingProvider (Zoom, Meet, Teams, …)
            → CaptureProvider (Recall.ai, Zoom AI Companion, Fireflies, …)
            → Transcript (normalized)  → Campaign Intake → Campaign Intelligence

Both seams are null by default (ADR-0004): with nothing configured a Meeting is still a real
business object (scheduled manually, transcript pasted through the lanes); a configured
provider upgrades hosting/capture without touching Campaign Intake or Campaign Intelligence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Mapping, Optional, Protocol, runtime_checkable

# ── The Meeting lifecycle (provider-agnostic status vocabulary) ───────────────
SCHEDULED = "scheduled"          # created + tied to the opportunity
BOT_INVITED = "bot_invited"      # a capture bot has been asked to join
IN_PROGRESS = "in_progress"
TRANSCRIPT_READY = "transcript_ready"   # capture returned a transcript, not yet ingested
INGESTED = "ingested"            # Campaign Intake consumed it → CI enriched
FAILED = "failed"
CANCELED = "canceled"
OPEN_STATUSES = (SCHEDULED, BOT_INVITED, IN_PROGRESS, TRANSCRIPT_READY, INGESTED)

# ── Normalized Meeting EVENTS — what the webhook emits, what downstream consumes.
# Provider webhooks (Zoom `recording.transcript_completed`, Recall `transcript.done`, …)
# are each normalized into ONE of these before anything downstream sees them.
EV_BOT_JOINED = "meeting.bot_joined"
EV_TRANSCRIPT_READY = "meeting.transcript_ready"
EV_FAILED = "meeting.failed"
EV_IGNORED = "meeting.ignored"


@dataclass
class TranscriptSegment:
    """One speaker turn — the unit that gives a CI field its evidence citation."""
    speaker: str = ""
    t0: float = 0.0          # seconds from start
    t1: float = 0.0
    text: str = ""


@dataclass
class Transcript:
    """A capture provider's output, NORMALIZED. Campaign Intake only ever sees this shape —
    it never knows whether Recall, Zoom AI, or a pasted file produced it."""
    text: str = ""
    segments: List[TranscriptSegment] = field(default_factory=list)
    speakers: List[str] = field(default_factory=list)
    duration_s: Optional[int] = None
    provider: str = ""
    external_ref: str = ""      # the capture session/bot id it came from

    def metadata(self) -> dict:
        """The capture metadata stamped on the Capture envelope (speakers/duration/provider)."""
        return {"speakers": self.speakers, "duration_s": self.duration_s,
                "provider": self.provider, "external_ref": self.external_ref,
                "segments": len(self.segments)}


@dataclass
class ScheduledMeeting:
    """A meeting-provider's output when it creates/hosts a meeting."""
    external_meeting_id: str = ""
    join_url: str = ""
    host_url: str = ""
    provider: str = "manual"


@dataclass
class MeetingEvent:
    """A normalized event about a Meeting. Downstream consumes THIS, not a provider payload."""
    type: str                    # EV_*
    external_ref: str = ""       # capture bot/session id (correlates to a meeting row)
    external_meeting_id: str = ""
    transcript: Optional[Transcript] = None
    raw_event_id: str = ""       # for idempotency (dedupe re-deliveries)
    error: str = ""


# ── Seam 1: hosting the meeting ───────────────────────────────────────────────
@runtime_checkable
class MeetingProvider(Protocol):
    """Creates/hosts a meeting. Zoom is one implementation; Meet/Teams later."""
    name: str

    def create(self, *, topic: str, start_at: str, duration_min: int,
               attendees: list) -> ScheduledMeeting: ...


# ── Seam 2: capturing the meeting ─────────────────────────────────────────────
@runtime_checkable
class CaptureProvider(Protocol):
    """Records + transcribes a meeting. Recall.ai is one implementation; Zoom AI Companion,
    Fireflies, Otter later. The webhook parser normalizes provider payloads into MeetingEvents
    so nothing downstream is coupled to a provider."""
    name: str

    def invite(self, *, join_url: str, meeting_ref: str) -> str:
        """Ask a capture bot to join the meeting; return the bot/session id (external_ref)."""
        ...

    def fetch_transcript(self, external_ref: str) -> Optional[Transcript]:
        """Pull the normalized transcript for a finished capture (may be None if not ready)."""
        ...

    def parse_webhook(self, headers: Mapping, body: bytes) -> MeetingEvent:
        """Verify + normalize a provider webhook into a MeetingEvent (EV_IGNORED if irrelevant
        or unverified). This is the ONE place a provider payload is understood."""
        ...
