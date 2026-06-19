"""Agentic email triage (Phase B1) — the recall play for a starving funnel.

An LLM *reads* each candidate alert email and decides whether it's a real
(paid) music opportunity, then extracts the fields — recovering the gigs the
keyword filters in ``signals.py`` drop on technicalities. Triaged gigs land on
the Signal Radar in the **review queue**, never auto-pursued: the human gate
the rest of the system uses is preserved ("machine proposes, Jon disposes").

B1 is **manual** (POST /triage/run) so extraction quality can be verified on
the real inbox before any autonomy (B2). The Anthropic client is imported
lazily and the extractor is injectable, so CI/sandbox run without an API key —
tests pass a fake. Cheap by design: dedup on the Gmail message id skips
already-seen mail *before* spending a token, and a single Haiku call does the
is-this-a-gig? + extract step.
"""
from __future__ import annotations

import json
import os
from typing import Callable, Optional

from ..intake import extract_budget
from . import db, gmail_client, signals

# Cheap model for the binary gate + extraction (CFO's cost concern). Overridable.
_DEFAULT_MODEL = "claude-haiku-4-5"

_SYSTEM = (
    "You triage forwarded job-alert emails for Chordential, a music house that "
    "takes paid commissions for original music composition, sonic branding, "
    "sound design, and music supervision/licensing — for commercials, film/TV, "
    "games, and brands. Decide whether the email describes a real opportunity "
    "Chordential could pursue (a buyer hiring for music work, paid or plausibly "
    "paid), and if so extract the fields. Mark is_opportunity false for talent "
    "self-promo, newsletters, unrelated roles (video editor, marketer), and "
    "clearly unpaid/hobby/rev-share asks. Be inclusive about *paid* gigs even "
    "when phrased loosely — a budget or rate is a strong positive signal."
)

# Structured output: a flat, guaranteed-valid record. Budget stays a string and
# is parsed downstream with the same extractor the rest of the engine uses, to
# avoid JSON-schema numeric-null edge cases.
_SCHEMA = {
    "type": "object",
    "properties": {
        "is_opportunity": {"type": "boolean"},
        "title": {"type": "string"},
        "client": {"type": "string"},
        "budget": {"type": "string"},
        "location": {"type": "string"},
        "contact": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": [
        "is_opportunity", "title", "client", "budget",
        "location", "contact", "summary",
    ],
    "additionalProperties": False,
}

# Module-level summary of the last run, surfaced on the radar (like webpush).
_LAST_RUN = ""


def last_run() -> str:
    return _LAST_RUN


def is_configured() -> bool:
    """Triage needs both a Gmail connection and an Anthropic key (for the
    default extractor)."""
    return gmail_client.is_configured() and bool(os.environ.get("ANTHROPIC_API_KEY"))


def _llm_extract(message: dict, *, model: Optional[str] = None) -> Optional[dict]:
    """Default extractor: one structured Haiku call per candidate email."""
    import anthropic  # lazy — Render-only; tests inject a fake instead

    client = anthropic.Anthropic()
    model = model or os.environ.get("CHORDENTIAL_TRIAGE_MODEL") or _DEFAULT_MODEL
    text = (
        f"From: {message.get('sender', '')}\n"
        f"Subject: {message.get('subject', '')}\n\n"
        f"{message.get('body', '')}"
    )[:8000]
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": text}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    raw = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(raw) if raw else None


def _land_signal(conn, external_ref: str, message: dict, result: dict) -> Optional[str]:
    """Store a triaged opportunity as a signal — the LLM has already done the
    is-it-a-gig? judgment, so we bypass the keyword filters and insert directly,
    reusing the engine's scoring + the radar's review/promote flow. Returns the
    display title on a successful insert (for the optional new-gig alert)."""
    title = (result.get("title") or message.get("subject") or "Opportunity").strip()
    client = (result.get("client") or "").strip()
    if client and client.lower() not in title.lower():
        title = f"{title} — {client}"
    body = (result.get("summary") or message.get("body") or "")[:5000]
    bmin = bmax = None
    budget = (result.get("budget") or "").strip()
    if budget:
        bmin, bmax = extract_budget(budget, labeled_only=False)
    score, tier = signals._score(title, body, bmin, bmax)
    sid = db.insert_signal(
        conn, source="gmail", source_weight=signals.weight_for("gmail"),
        title=title[:300], body=body, url="", external_ref=external_ref,
        budget_min=bmin, budget_max=bmax, score=score, tier=tier,
        contact_handle=(result.get("contact") or None),
    )
    return title if sid is not None else None


def run_triage(
    conn, *, limit: int = 25, notify: bool = False,
    gmail=gmail_client, extractor: Optional[Callable[[dict], Optional[dict]]] = None,
) -> dict:
    """Read the unread alert queue, extract real opportunities, land them on the
    radar. Idempotent (dedup on Gmail id) and best-effort. When ``notify`` is set
    (the autonomous path), each landed gig fires a phone alert. Returns a summary
    ``{configured, scanned, created, skipped}``. ``gmail`` and ``extractor`` are
    injectable for tests."""
    global _LAST_RUN
    extractor = extractor or _llm_extract

    if not gmail.is_configured():
        _LAST_RUN = "Gmail isn't connected — set the CHORDENTIAL_GMAIL_* secrets."
        return {"configured": False, "scanned": 0, "created": 0, "skipped": 0}

    created = skipped = scanned = 0
    for cand in gmail.list_candidates(limit=limit):
        mid = cand.get("id")
        if not mid:
            continue
        external_ref = f"gmail:{mid}"
        if db.signal_exists(conn, external_ref):       # already triaged → skip, no LLM
            skipped += 1
            continue
        message = gmail.get_message(mid)
        scanned += 1
        try:
            result = extractor(message)
        except Exception as e:                          # noqa: BLE001 — leave unread, retry next run
            _LAST_RUN = f"Extraction error on a message: {type(e).__name__}: {e}"[:200]
            continue
        if not result or not result.get("is_opportunity"):
            gmail.mark_processed(mid)                    # not a gig → clear it
            skipped += 1
            continue
        title = _land_signal(conn, external_ref, message, result)
        gmail.mark_processed(mid)
        created += 1
        if notify and title:                            # autonomous path → alert phone
            try:
                signals.notify_new_gig(title, "/signals")
            except Exception:  # noqa: BLE001 — a push must never stall triage
                pass

    _LAST_RUN = (
        f"Scanned {scanned} new email(s): {created} new opportunit(y/ies) "
        f"landed on the radar, {skipped} skipped."
    )
    if scanned == 0 and created == 0:
        # Nothing read — surface *why* so a silent failure (missing libs, bad auth,
        # wrong label, or a token minted against the wrong Google account) is
        # diagnosable instead of looking like an empty inbox. account_email() also
        # exercises a real Gmail call, so an auth/lib failure shows up as an error.
        acct = ""
        try:
            acct = getattr(gmail, "account_email", lambda: "")()
        except Exception:  # noqa: BLE001
            acct = ""
        err = ""
        try:
            err = getattr(gmail, "last_error", lambda: "")()
        except Exception:  # noqa: BLE001
            err = ""
        if err:
            _LAST_RUN += f"  ⚠ Gmail error: {err}"
        else:
            who = f" for {acct}" if acct else ""
            _LAST_RUN += (
                f"  (No unread mail matched label '{gmail_client.label()}'{who} — "
                "confirm that's the right account + label, and that a few alerts "
                "are unread.)"
            )
    return {"configured": True, "scanned": scanned, "created": created, "skipped": skipped}


# --------------------------------------------------------------------------- #
# B3 — feedback loop. Every human verdict on a triaged gig is a labeled example
# the triage step compounds on (the same "machine proposes, human disposes"
# philosophy as qualification.record_label). Promote = the LLM was right;
# dismiss = a false positive. Written as JSONL, best-effort, never raises.
# --------------------------------------------------------------------------- #
def _labels_path() -> str:
    explicit = os.environ.get("CHORDENTIAL_TRIAGE_LABELS", "").strip()
    if explicit:
        return explicit
    db_path = os.environ.get("CHORDENTIAL_DB", "").strip()
    if db_path:                                          # alongside the DB (persistent disk)
        return os.path.join(os.path.dirname(os.path.abspath(db_path)) or ".",
                            "triage_labels.jsonl")
    return "triage_labels.jsonl"


def is_triaged(signal_row) -> bool:
    """True for a Gmail-sourced (LLM-triaged) signal — the only ones whose
    accept/reject is a meaningful triage label."""
    try:
        return (signal_row["source"] or "") == "gmail"
    except Exception:  # noqa: BLE001
        return False


def record_feedback(signal_row, human_verdict: str) -> Optional[dict]:
    """Append a triage label: the LLM said this email was an opportunity (it only
    lands those), and the human's verdict — ``"promoted"`` (agreed) or
    ``"dismissed"`` (false positive). Best-effort; no-op for non-triaged signals."""
    if not is_triaged(signal_row):
        return None
    try:
        from datetime import datetime, timezone
        record = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "source": "gmail",
            "external_ref": signal_row["external_ref"],
            "title": signal_row["title"],
            "body_excerpt": (signal_row["body"] or "")[:500],
            "llm_verdict": "opportunity",
            "human_verdict": human_verdict,
            "agreement": human_verdict == "promoted",
        }
        with open(_labels_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return record
    except Exception:  # noqa: BLE001 — feedback capture must never break the action
        return None
