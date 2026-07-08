"""The Production OS spine (ADR-0019): Directions, the round ledger, Creative Lock, and the
computed court-state.

Built ON the existing machinery, not beside it: the ``delivery_json['versions']`` ladder is
the Version chain, ``review_comments`` is the feedback tape, and the creator publish gate is
the taste gate's seam. This module adds the three pieces of state the agreed business model
(docs/production-lifecycle-model.md) ranked load-bearing — all in the same per-project JSON
blob (house pattern, no new tables) — plus the one thing that is never stored because it is
always derivable: **whose court the ball is in.**

- ``directions``  — the creative territories. A campaign explores Directions; each carries a
  name, a thesis (the hero element — "the one thing this track IS"), and a fate: exploring →
  selected | rejected(+reason). Versions stamp a direction id. Rejection reasons are
  Relationship Intelligence raw material.
- ``round_log``   — one entry per change-request round (when, by whom, the note, against
  which version). The flat ``revisions_used`` counter stays as the total; the log is the
  ledger behind it.
- ``creative_lock`` — ``{version_n, at, by}``. The gate that ends the revision economy:
  changes after lock are scope/conform conversations, and production spend is authorized.
- ``court_state(project, delivery)`` — computed: every project is in exactly ONE of
  ``client`` / ``studio`` / ``scheduled``, with an age. The operational form of "what
  uncertainty did we remove"; the Workspace's production phase speaks it in concierge voice.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from .. import delivery as D


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Directions — the creative territories (first-class, per the ratified principles).
# --------------------------------------------------------------------------- #
DIRECTION_STATES = ["exploring", "selected", "rejected"]


def directions(delivery: dict) -> list:
    return list((delivery or {}).get("directions") or [])


def add_direction(conn, db, project_id: int, *, name: str, thesis: str = "") -> Optional[dict]:
    name = (name or "").strip()
    if not name:
        return None
    entry = {"id": secrets.token_hex(4), "name": name, "thesis": (thesis or "").strip(),
             "status": "exploring", "reason": "", "created_at": _now(), "decided_at": ""}
    rows = directions(db.get_delivery(conn, project_id))
    rows.append(entry)
    db.update_delivery(conn, project_id, "directions", rows)
    return entry


def decide_direction(conn, db, project_id: int, direction_id: str, *, status: str,
                     reason: str = "") -> bool:
    """Select or reject a Direction. A rejection carries its WHY — that reason is what the
    feedback dictionary (RI) learns from. Selecting one leaves the others untouched (they are
    rejected explicitly, each with its own reason — their deaths are informative)."""
    if status not in ("selected", "rejected"):
        return False
    rows = directions(db.get_delivery(conn, project_id))
    hit = False
    for r in rows:
        if r.get("id") == direction_id:
            r["status"] = status
            r["reason"] = (reason or "").strip()
            r["decided_at"] = _now()
            hit = True
    if hit:
        db.update_delivery(conn, project_id, "directions", rows)
    return hit


def selected_direction(delivery: dict) -> Optional[dict]:
    for r in directions(delivery):
        if r.get("status") == "selected":
            return r
    return None


# --------------------------------------------------------------------------- #
# The round ledger — the record behind the revisions_used counter.
# --------------------------------------------------------------------------- #
def round_log(delivery: dict) -> list:
    return list((delivery or {}).get("round_log") or [])


def log_round(conn, db, project_id: int, *, version: str = "", by: str = "",
              note: str = "") -> dict:
    """Record one revision round (called when a change-request lands). The counter is the
    total; this is the history — which version, who asked, what they said. Post-lock rounds
    are stamped ``after_lock`` so scope conversations have a record to stand on."""
    delivery = db.get_delivery(conn, project_id)
    rows = round_log(delivery)
    entry = {"n": len(rows) + 1, "at": _now(), "version": str(version or ""),
             "by": (by or "").strip(), "note": (note or "").strip()[:500],
             "after_lock": bool(creative_lock(delivery))}
    rows.append(entry)
    db.update_delivery(conn, project_id, "round_log", rows)
    return entry


# --------------------------------------------------------------------------- #
# Creative Lock — the hinge of the lifecycle.
# --------------------------------------------------------------------------- #
def creative_lock(delivery: dict) -> Optional[dict]:
    lock = (delivery or {}).get("creative_lock")
    return dict(lock) if lock else None


def set_creative_lock(conn, db, project_id: int, *, version_n, by: str = "operator") -> dict:
    lock = {"version_n": version_n, "at": _now(), "by": (by or "operator").strip()}
    db.update_delivery(conn, project_id, "creative_lock", lock)
    return lock


def clear_creative_lock(conn, db, project_id: int) -> None:
    db.update_delivery(conn, project_id, "creative_lock", None)


# --------------------------------------------------------------------------- #
# The court-state — computed, never stored (ADR-0019).
# --------------------------------------------------------------------------- #
def court_state(project, delivery: dict) -> dict:
    """Whose court is the ball in — exactly one of ``client`` / ``studio`` / ``scheduled``,
    with what/why and the timestamp it entered that state (age is the caller's subtraction).

    Derivation (from the existing state machine, nothing new):
      released/delivered                → scheduled  (nothing owed until the next engagement)
      pending_version awaiting publish  → studio     (the taste gate — operator disposition)
      state == "In review"              → client     (a version awaits their reaction)
      everything else                   → studio     (we're composing/producing)
    """
    delivery = delivery or {}
    state = (delivery.get("state") or "").strip() or "In production"
    versions = D.versions_list(delivery)
    cur = D.current_version(delivery) or {}
    since = cur.get("created_at") or (project["created_at"] if project else "") or ""

    if state in ("Released",):
        return {"court": "scheduled", "since": delivery.get("released_at") or since,
                "what": "released",
                "line": "Your campaign is delivered and released — nothing further to manage."}
    if state in ("Delivered", "Approved"):
        return {"court": "scheduled", "since": since, "what": "delivered",
                "line": "Your delivery package is complete. Nothing is needed from you."}
    if delivery.get("pending_version"):
        pv = delivery["pending_version"] or {}
        return {"court": "studio", "since": pv.get("at") or since, "what": "reviewing",
                "line": "A new version is in our studio review — it reaches you the moment "
                        "it's ready."}
    if state == "In review" and versions:
        label = cur.get("label") or f"Version {cur.get('n', '')}"
        return {"court": "client", "since": since, "what": "version_ready",
                "version": cur,
                "line": f"{label} is ready for you — listen when you have a moment and tell "
                        f"us what you think."}
    # In production (or fresh): the studio owes the next version.
    what = "composing" if not versions else "revising"
    since2 = ""
    if what == "revising":
        rl = round_log(delivery)
        since2 = rl[-1]["at"] if rl else since
    return {"court": "studio", "since": since2 or since, "what": what,
            "line": ("We're composing — nothing is needed from you; you'll hear from us "
                     "when the first version is ready."
                     if what == "composing" else
                     "Your notes are in the room — we're on the revision now. Nothing is "
                     "needed from you.")}


def creative_journey(delivery: dict) -> dict:
    """The client-facing history of creative thinking: directions with their fates, the
    version ladder, the lock, and the round count. Pure projection for the workspace."""
    delivery = delivery or {}
    return {
        "directions": directions(delivery),
        "versions": D.versions_list(delivery),
        "lock": creative_lock(delivery),
        "rounds_used": int(delivery.get("revisions_used") or 0),
        "round_log": round_log(delivery),
    }
