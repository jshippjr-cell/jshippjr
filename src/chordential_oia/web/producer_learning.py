"""The Producer Learning layer (ADR-0021).

ChordOS gets better at discovery after every campaign — not by fine-tuning, not by
vector-memory of arbitrary conversations, but by learning *what an Executive Producer
consistently considers important*.

Every operator disposition of a proposed Campaign Intelligence field is training data:

    transcript fragment → field extracted → AI value → final confirmed value
                        → operator edit distance → outcome

Four actions are recorded (``record_event``):
  - **confirmed**  — the operator accepted the AI's value verbatim (edit_distance 0)
  - **edited**     — the operator changed it (edit_distance 0<d<1); systematic expansion in a
                     facet teaches the extractor to propose richer values there
  - **rejected**   — the operator threw the proposal away (edit_distance 1)
  - **added**      — the operator supplied a field the AI missed entirely (ai_value ''); the
                     **missed-concept** signal, the strongest driver of wider extraction

Those events roll up (``field_prior`` / ``priors_summary``) into a transparent, count-based
per-field prior the extractor consults on the NEXT call — "the machine proposes, Jon disposes,
and the machine learns from the disposition." Auditable, reversible, not a black box.
"""
from __future__ import annotations

import difflib
from datetime import datetime, timezone
from typing import Optional

from . import db


def edit_distance(a: str, b: str) -> float:
    """A normalized 0..1 change magnitude between the AI value and the final value.
    0.0 = identical (accepted verbatim); 1.0 = wholesale change (or rejection)."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    if a == b:
        return 0.0
    return round(1.0 - difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio(), 3)


def record_event(conn, *, ci_id, opp_id, facet: str, key: str, kind: str = "fact",
                 action: str, ai_value: str = "", final_value: str = "",
                 confidence_before=None, transcript_fragment: str = "",
                 capture_id=None) -> int:
    """Append one learning event. ``action`` ∈ confirmed|rejected|edited|added.
    edit_distance is computed unless the action fixes it (rejected → 1, added → 1)."""
    if action == "rejected":
        dist = 1.0
    elif action == "added":
        dist = 1.0            # supplied from nothing — the AI proposed no value to accept
    else:
        dist = edit_distance(ai_value, final_value)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO producer_learning_event
           (ci_id, opp_id, facet, key, kind, action, ai_value, final_value,
            edit_distance, confidence_before, transcript_fragment, capture_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ci_id, opp_id, facet, key, kind, action, (ai_value or "")[:2000],
         (final_value or "")[:2000], dist,
         int(confidence_before) if confidence_before not in (None, "") else None,
         (transcript_fragment or "")[:2000], capture_id, now))
    conn.commit()
    return cur.lastrowid


def _rows(conn):
    return conn.execute("SELECT * FROM producer_learning_event").fetchall()


def field_prior(conn, facet: str, key: str) -> dict:
    """The learned prior for one (facet, key), rolled up across ALL campaigns (the producer's
    consistent taste, not one deal's noise):
      - ``n`` events, ``acceptance`` (confirmed+lightly-edited / n),
      - ``expands`` (mean edit_distance on edits — high = the operator enriches this field),
      - ``missed`` (times added-from-nothing — the extractor should start proposing it),
      - ``stance`` ∈ trusted | expand | contested | learn | unknown (the one-word verdict).
    """
    rows = [r for r in _rows(conn) if r["facet"] == facet and r["key"] == key]
    n = len(rows)
    if not n:
        return {"n": 0, "acceptance": None, "expands": 0.0, "missed": 0, "rejected": 0,
                "stance": "unknown"}
    confirmed = sum(1 for r in rows if r["action"] == "confirmed")
    edited = [r for r in rows if r["action"] == "edited"]
    rejected = sum(1 for r in rows if r["action"] == "rejected")
    missed = sum(1 for r in rows if r["action"] == "added")
    light_edits = sum(1 for r in edited if (r["edit_distance"] or 0) < 0.5)
    acceptance = round((confirmed + light_edits) / n, 3)
    expands = round(sum(r["edit_distance"] or 0 for r in edited) / len(edited), 3) if edited else 0.0
    if rejected >= 2 and rejected >= confirmed:
        stance = "contested"          # the operator keeps throwing this away — stop nagging
    elif missed >= 2 and confirmed + len(edited) == 0:
        stance = "learn"              # the AI keeps missing it — start proposing it
    elif expands >= 0.4 and len(edited) >= 2:
        stance = "expand"             # the operator consistently enriches — propose richer
    elif acceptance >= 0.7 and n >= 2:
        stance = "trusted"            # reliably accepted — propose confidently
    else:
        stance = "learn"
    return {"n": n, "acceptance": acceptance, "expands": expands, "missed": missed,
            "rejected": rejected, "stance": stance}


def priors_summary(conn, *, max_lines: int = 24) -> str:
    """A compact natural-language brief of what this producer consistently values, injected
    into the extraction prompt so the next call is calibrated to real behavior. Empty string
    when there's no history yet (cold start — the extractor runs on its base instructions)."""
    seen = {}
    for r in _rows(conn):
        seen.setdefault((r["facet"], r["key"]), True)
    lines = []
    for facet, key in seen:
        p = field_prior(conn, facet, key)
        if p["n"] < 2:
            continue
        label = f"{facet}.{key}"
        if p["stance"] == "trusted":
            lines.append(f"- {label}: the producer almost always confirms this — propose it "
                         f"confidently when supported.")
        elif p["stance"] == "expand":
            lines.append(f"- {label}: the producer consistently EXPANDS this into a richer, "
                         f"more specific value — propose the fuller read, not a terse one.")
        elif p["stance"] == "contested":
            lines.append(f"- {label}: the producer usually rejects this — only propose it "
                         f"when the transcript states it explicitly.")
        elif p["stance"] == "learn" and p["missed"] >= 2:
            lines.append(f"- {label}: the producer has repeatedly ADDED this after the AI "
                         f"missed it — actively watch for it and propose it.")
    lines = lines[:max_lines]
    if not lines:
        return ""
    return ("WHAT THIS PRODUCER CONSISTENTLY VALUES (learned from past dispositions — "
            "calibrate to it):\n" + "\n".join(lines))
