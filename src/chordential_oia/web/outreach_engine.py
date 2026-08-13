"""Outreach Engine — the final stage, split into three engines so AI reasons
first, writes second, and remembers over the long term:

  * Outreach Strategy Engine — decides IF/WHEN/WHY/to-WHOM to reach out
    (YES / WAIT / MONITOR / NO), the objective, the Reason-to-Reach-Out
    ("why today"), and a brief. Pure reasoning over collected data.
  * Content Generation Engine — turns the brief into THREE draft approaches
    (relationship / creative / business). Deterministic templates by default; an
    optional LLM seam writes more human drafts when configured. The one question
    it asks: "If Jon were writing this today, what would he say?"
  * Relationship Continuity Engine — after outreach, watches what CHANGED
    (responses, silence, new agency signals) and determines the next best action —
    following reality, not a calendar.

Plus a Relationship Memory summary that reads back the institutional knowledge.

Safety + honesty: this DRAFTS and recommends only. It never sends email and never
invents facts — every draft is built from the agency's own collected signals /
intelligence, and the honest value proposition (clearance-certified, human-composed
original music) is the only claim made. "Jon disposes": he reviews, edits, sends.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from . import db

# LLM seam: (brief, angle) -> {"subject", "body"} | None. Injected in tests.
LLM = Callable[[Dict, str], Optional[Dict]]

ANGLES = ("relationship", "creative", "business")
_VALUE = ("Chordential is a procurement-grade music studio: clearance-certified, "
          "human-composed original music (never AI-generated).")


def _days_since(iso: str) -> int:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, TypeError):
        return 99999


def _ival(field) -> str:
    v = (field or {}).get("value")
    return v if isinstance(v, str) else ""


def _lval(field) -> List:
    v = (field or {}).get("value")
    return v if isinstance(v, list) else []


# --------------------------------------------------------------------------- #
# Reason-to-Reach-Out — why today? The opening line of any outreach.
# --------------------------------------------------------------------------- #
def _strip_prefix(summary: str) -> str:
    """Drop a detector prefix ('Hiring: ', 'Award: ', 'New work in portfolio: ')."""
    return re.sub(r"^(hiring|award|new work in portfolio|client on roster|"
                  r"new work|leadership)\s*[:\-]\s*", "", summary or "", flags=re.I).strip()


def reason_to_reach_out(signals: List[Dict], intel: Dict) -> Dict:
    """The single strongest, freshest reason to reach out now, as a clean clause
    that reads after 'I saw …' — or an honest intelligence-based fallback."""
    ranked = sorted(
        [s for s in signals if s["music_relevance"] in ("Very High", "High")],
        key=lambda s: s["detected_at"], reverse=True)
    for s in ranked:
        et, summ = s["event_type"], (s["summary"] or "").strip()
        src = f"Signal · {s['detected_at'][:10]}"
        if et in ("New client", "Account win"):
            return {"reason": f"the news that {summ}" if summ else "you won a new account",
                    "source": src}
        if et == "Hiring":
            return {"reason": f"you're growing the team: {_strip_prefix(summ)}", "source": src}
        if et in ("Campaign launch", "New work"):
            return {"reason": f"your recent work, {_strip_prefix(summ)}", "source": src}
        if et == "Award":
            return {"reason": f"your recognition: {_strip_prefix(summ)}", "source": src}
    if _ival(intel.get("production_complexity")) == "High" or \
            (set(_lval(intel.get("creative_focus"))) & {"Brand Films", "Broadcast", "Commercials"}):
        return {"reason": "how well your cinematic brand work fits original music",
                "source": "Intelligence · Creative focus"}
    return {"reason": "", "source": ""}


# --------------------------------------------------------------------------- #
# Outreach Strategy Engine — if / when / why / to whom + the brief.
# --------------------------------------------------------------------------- #
def _objective(stage: str, signals: List[Dict], last_out, intel: Dict) -> str:
    fresh_congrats = next((s for s in signals
                           if s["event_type"] in ("Award", "New client", "Account win",
                                                   "Campaign launch")
                           and _days_since(s["detected_at"]) <= 30), None)
    if fresh_congrats:
        return "Congratulations"
    if last_out is None:
        return "Introduction"
    if _days_since(last_out["occurred_at"]) > 120:
        return "Reconnect"
    if stage == "Active":
        return "Check-in"
    return "Reconnect"


def _cta(objective: str) -> str:
    return {
        "Introduction": "a 15-minute introduction call",
        "Congratulations": "an open door whenever a project calls for music",
        "Reconnect": "a quick catch-up",
        "Check-in": "a brief call if anything's on the horizon",
        "Meeting Request": "a 20-minute meeting",
    }.get(objective, "a short conversation")


def build_strategy(conn, agency_id: int) -> Dict:
    """Decide whether/when/why/to-whom to reach out, and build the brief.
    Reasons over the score, relationship history, signals and intelligence."""
    row = db.get_agency(conn, agency_id)
    if row is None:
        return {"status": "error", "detail": "no such agency"}
    score_blob = db.get_agency_score(conn, agency_id) or {}
    intel = db.get_agency_intel(conn, agency_id) or {}
    signals = [dict(s) for s in db.list_opportunity_signals(conn, agency_id, active_only=True)]
    interactions = list(db.list_agency_outreach(conn, agency_id))
    last_out = db.last_agency_outreach(conn, agency_id)
    responded = any(o["responded"] for o in interactions)
    contact = score_blob.get("recommended_contact")
    tier = score_blob.get("tier")
    reachable = bool(contact and (contact.get("email") or contact.get("linkedin")))

    # --- the decision: YES / WAIT / MONITOR / NO ---
    if not reachable:
        decision, detail = "MONITOR", "No reachable contact yet. Run decision-maker discovery first."
    elif last_out is not None and _days_since(last_out["occurred_at"]) < 30 and not responded:
        wait = 30 - _days_since(last_out["occurred_at"])
        decision, detail = "WAIT", f"Contacted {_days_since(last_out['occurred_at'])}d ago; wait ~{wait} days."
    elif tier in ("A", "B"):
        decision, detail = "YES", "Strong opportunity and reachable. Reach out."
    elif tier == "C":
        decision, detail = "MONITOR", "Moderate fit. Wait for a stronger signal."
    else:
        decision, detail = "NO", "Low fit. Not a priority."

    stage_row = db.get_relationship(conn, agency_id)
    stage = (stage_row["stage"] if stage_row else "") or "Cold"
    objective = _objective(stage, signals, last_out, intel)
    reason = reason_to_reach_out(signals, intel)

    inds = _lval(intel.get("primary_industries"))
    mention: List[str] = []
    for s in signals:
        if s["event_type"] in ("Campaign launch", "New work", "Award", "New client") \
                and len(mention) < 2:
            mention.append(s["summary"])
    if inds:
        mention.append(f"their {inds[0]} work")
    # a clean phrase for "your work" in the creative angle (real work, not a win)
    work = next((_strip_prefix(s["summary"]) for s in signals
                 if s["event_type"] in ("Campaign launch", "New work", "Award")), "")
    work_mention = work or (f"your {inds[0]} work" if inds else "your recent work")

    evidence = [s["summary"] for s in signals[:3]]
    pc = _ival(intel.get("production_complexity"))
    if pc in ("High", "Medium"):
        evidence.append(f"{pc} production complexity")

    brief = {
        "agency": row["company"], "objective": objective,
        "why_now": reason["reason"], "why_now_source": reason["source"],
        "evidence": evidence,
        "mention": mention[:3],
        "avoid": ["Pricing details this early", "Generic claims; keep it specific to them",
                  "Any suggestion of AI-generated music"],
        "cta": _cta(objective),
        "contact": contact, "work_mention": work_mention,
    }
    return {"status": "ok", "decision": decision, "detail": detail,
            "objective": objective, "reason": reason, "brief": brief,
            "tier": tier, "score": score_blob.get("score"), "stage": stage}


# --------------------------------------------------------------------------- #
# Content Generation Engine — three draft approaches from the brief.
# --------------------------------------------------------------------------- #
def _default_llm(brief: Dict, angle: str) -> Optional[Dict]:  # pragma: no cover - networked
    if os.environ.get("CHORDENTIAL_OUTREACH_LLM", "1").strip().lower() in (
            "0", "false", "off", "no", ""):
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        model = os.environ.get("CHORDENTIAL_OUTREACH_MODEL") or "claude-haiku-4-5-20251001"
        prompt = (
            "You are drafting an outreach email as Jon, founder of Chordential (a "
            "procurement-grade music studio selling clearance-certified, human-composed "
            "original music, never AI-generated). Write as Jon would personally write "
            "it today: warm, concise, specific, no hype. Use ONLY these facts:\n"
            + json.dumps(brief, indent=2) +
            f"\nAngle: {angle}. Open with the reason-to-reach-out. End with the CTA. "
            "Return JSON {\"subject\": str, \"body\": str}. Do not invent facts or mention pricing.")
        resp = client.messages.create(model=model, max_tokens=600,
                                       messages=[{"role": "user", "content": prompt}])
        raw = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(raw) if raw else None
        if isinstance(data, dict) and data.get("body"):
            return {"subject": data.get("subject", ""), "body": data["body"]}
    except Exception:
        return None
    return None


def _opening(brief: Dict) -> str:
    name = (brief.get("contact") or {}).get("name", "")
    hi = f"Hi {name.split()[0]}," if name else "Hi,"
    if brief["why_now"]:
        tail = ", congratulations." if brief.get("objective") == "Congratulations" else "."
        return f"{hi}\n\nI saw {brief['why_now']}{tail}"
    return f"{hi}\n\nI've been following {brief['agency']}'s work and wanted to reach out."


def _template_draft(brief: Dict, angle: str) -> Dict:
    agency = brief["agency"]
    work = brief.get("work_mention") or "your recent work"
    cta = brief["cta"]
    opening = _opening(brief)
    if angle == "relationship":
        subject = "Quick hello from Chordential"
        mid = ("I'd love to open a line between our teams; I think there's a natural "
               "fit between your work and what we do.")
    elif angle == "creative":
        subject = f"Original scoring for {agency}'s work"
        mid = (f"{work[0].upper()}{work[1:]} is exactly the kind of emotionally-driven, "
               f"high-craft output where original music earns its keep. We compose to "
               f"picture, bespoke to the brief.")
    else:  # business
        subject = f"A cleaner way to source original music"
        mid = (f"As {agency} takes on more production, music clearance and sourcing get "
               f"painful fast. {_VALUE} One partner, fully cleared, no surprises.")
    body = (f"{opening}\n\n{mid}\n\n{_VALUE}\n\n"
            f"Would you be open to {cta}?\n\nBest,\nJon\nChordential")
    return {"angle": angle, "subject": subject, "body": body, "generated_by": "template"}


def generate_drafts(brief: Dict, *, llm: Optional[LLM] = None) -> List[Dict]:
    """Three draft approaches (relationship / creative / business). Uses the LLM
    seam when available, falling back to deterministic templates — so it always
    produces usable drafts, offline and free, and a richer set when configured."""
    fn = llm if llm is not None else _default_llm
    out = []
    for angle in ANGLES:
        drafted = None
        try:
            drafted = fn(brief, angle)
        except Exception:
            drafted = None
        if isinstance(drafted, dict) and drafted.get("body"):
            out.append({"angle": angle, "subject": drafted.get("subject", ""),
                        "body": drafted["body"], "generated_by": "ai"})
        else:
            out.append(_template_draft(brief, angle))
    return out


# --------------------------------------------------------------------------- #
# Relationship Continuity Engine — next best action follows reality, not a calendar.
# --------------------------------------------------------------------------- #
def _signal_phrase(s: Dict) -> str:
    et = s["event_type"]
    if et in ("New client", "Account win"):
        return f"they won new business ({s['summary']})"
    if et == "Hiring":
        return f"they're {s['summary'].lower()}"
    if et in ("Campaign launch", "New work"):
        return f"they released new work ({s['summary']})"
    if et == "Award":
        return f"they won an award ({s['summary']})"
    return s["summary"]


def next_best_action(conn, agency_id: int) -> Dict:
    """What to do next — driven by what CHANGED since the last touch, not a timer."""
    last_out = db.last_agency_outreach(conn, agency_id)
    interactions = list(db.list_agency_outreach(conn, agency_id))
    responded = any(o["responded"] for o in interactions)
    signals = [dict(s) for s in db.list_opportunity_signals(conn, agency_id, active_only=True)]

    if last_out is None:
        return {"action": "Send the introduction", "kind": "introduce",
                "reason": "No outreach yet. Open the relationship.", "changed": []}
    days = _days_since(last_out["occurred_at"])
    changed = [s for s in signals if s["detected_at"] > last_out["occurred_at"]]
    if responded:
        return {"action": "They replied; move toward a meeting", "kind": "meeting",
                "reason": "A response is on file; keep the conversation going.", "changed": changed}
    if changed:
        top = max(changed, key=lambda s: s["detected_at"])
        return {"action": "Send an intelligent follow-up", "kind": "followup",
                "reason": f"Since your last email, {_signal_phrase(top)}; reference it, "
                          f"don't 'just check in'.", "changed": changed}
    if days < 14:
        return {"action": f"Wait: you reached out {days}d ago", "kind": "wait",
                "reason": "No change yet; give it room.", "changed": []}
    if days < 45:
        return {"action": "A light, value-add check-in is reasonable", "kind": "checkin",
                "reason": f"{days}d of quiet and no new signal.", "changed": []}
    return {"action": "Reconnect with a fresh angle", "kind": "reconnect",
            "reason": f"{days}d of silence. Re-open with something new.", "changed": []}


# --------------------------------------------------------------------------- #
# Relationship Memory summary — read back the institutional knowledge.
# --------------------------------------------------------------------------- #
def relationship_summary(conn, agency_id: int) -> Dict:
    """A narrative summary assembled from memory + history + signals + score — the
    institutional memory a seasoned BD lead would carry in their head."""
    row = db.get_agency(conn, agency_id)
    if row is None:
        return {}
    score_blob = db.get_agency_score(conn, agency_id) or {}
    memory = [m["fact"] for m in db.list_agency_memory(conn, agency_id)]
    interactions = list(db.list_agency_outreach(conn, agency_id))
    responded = any(o["responded"] for o in interactions)
    last = interactions[0] if interactions else None
    rel = db.get_relationship(conn, agency_id)
    stage = (rel["stage"] if rel else "") or "Cold"
    nba = next_best_action(conn, agency_id)

    lines = [f"Stage: {stage}."]
    if score_blob.get("score") is not None:
        lines.append(f"Opportunity {score_blob['score']} (tier {score_blob.get('tier')}).")
    if interactions:
        lines.append(f"{len(interactions)} interaction(s); last {last['occurred_at'][:10]}"
                     + (" · they responded." if responded else " · no reply yet."))
    else:
        lines.append("No interactions yet.")
    return {"summary": " ".join(lines), "memory": memory,
            "recommended_next_step": nba["action"], "next_reason": nba["reason"]}


def outreach_workspace(conn, agency_id: int, *, llm: Optional[LLM] = None) -> Dict:
    """Everything the outreach panel shows: strategy + brief + 3 drafts + next
    best action + relationship summary. Drafts are review-only — nothing is sent."""
    strategy = build_strategy(conn, agency_id)
    if strategy.get("status") != "ok":
        return {"status": strategy.get("status", "error")}
    drafts = generate_drafts(strategy["brief"], llm=llm)
    return {"status": "ok", "strategy": strategy, "drafts": drafts,
            "next_best_action": next_best_action(conn, agency_id),
            "memory": relationship_summary(conn, agency_id)}
