"""Music Opportunity Engine — Chordential's business logic, where everything
converges. Company Intelligence answers "who are they?", Signal Detection answers
"what's happening now?"; this answers "should Chordential care, and why?".

It REASONS over already-collected data — it never crawls, scrapes or searches. It
consumes Company Intelligence + Decision Makers + active Signals + Relationship
History (prior outreach) and produces a full sales strategy, not just a number:

    Opportunity Score (0–100) = a sum of explainable SUB-scores
      Creative Fit /25 · Business Momentum /20 · Music Need /25 ·
      Relationship Readiness /15 · Contact Confidence /10 · Timing bonus /5
    + Tier (A/B/C/D), Confidence, Supporting Evidence (per sub-score),
      Score Movement vs last run, Score History, Recommended Action,
      Recommended Contact, Best Timing, and Outreach Talking Points.

The score is never a black box: every point awarded cites the evidence it came
from (a signal, an intelligence field, an outreach record). And it's alive — each
run recomputes from the latest signals/outreach and records the movement, so the
dashboard can say "AKQA moved 64 → 91 this week because…".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import db

_TIERS = (("A", 80), ("B", 60), ("C", 40), ("D", 0))
_SIG_IMPORTANCE_PTS = {"Very High": 5, "High": 3, "Medium": 2, "Low": 1}
_MUSIC_FORMATS = {"Brand Films", "Broadcast", "Commercials", "Documentary", "Animation"}


def _days_since(iso: str) -> int:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, TypeError):
        return 9999


def _sub(name: str, value: int, maximum: int, evidence: List[str]) -> Dict:
    return {"name": name, "value": max(0, value), "max": maximum, "evidence": evidence}


def _ival(field: Dict) -> str:
    return (field or {}).get("value") if isinstance((field or {}).get("value"), str) else ""


def _lval(field: Dict) -> List:
    v = (field or {}).get("value")
    return v if isinstance(v, list) else []


# --------------------------------------------------------------------------- #
# Sub-scores — each returns points + the evidence for every point.
# --------------------------------------------------------------------------- #
def _creative_fit(intel: Dict) -> Dict:
    ev: List[str] = []
    pts = 0
    pc = _ival(intel.get("production_complexity"))
    pc_pts = {"High": 10, "Medium": 6, "Low": 3}.get(pc, 0)
    if pc_pts:
        ev.append(f"Production complexity {pc} (+{pc_pts})")
        pts += pc_pts
    focus = set(_lval(intel.get("creative_focus")))
    music_fmt = sorted(focus & _MUSIC_FORMATS)
    fmt_pts = min(10, len(music_fmt) * 3)
    if fmt_pts:
        ev.append(f"Music-friendly formats: {', '.join(music_fmt)} (+{fmt_pts})")
        pts += fmt_pts
    if any("cinematic" in s.lower() or "high-production" in s.lower()
           for s in _lval(intel.get("production_style"))):
        ev.append("Cinematic / high-production style (+5)")
        pts += 5
    if not ev:
        ev.append("Limited creative-fit evidence — needs a richer intelligence profile.")
    return _sub("Creative Fit", min(25, pts), 25, ev)


def _business_momentum(intel: Dict, signals: List[Dict]) -> Dict:
    ev: List[str] = []
    pts = 0
    sig_pts = min(15, sum(_SIG_IMPORTANCE_PTS.get(s["importance"], 0) for s in signals))
    if sig_pts:
        ev.append(f"{len(signals)} active signal(s) on the timeline (+{sig_pts})")
        pts += sig_pts
    growth = [t for t in _lval(intel.get("momentum"))
              if t in ("Hiring", "Winning new accounts", "Award-winning",
                       "Expanding / new offices", "Launching work/products")]
    mom_pts = min(5, len(growth) * 2)
    if mom_pts:
        ev.append("Momentum: " + ", ".join(growth) + f" (+{mom_pts})")
        pts += mom_pts
    if not ev:
        ev.append("No recent business momentum observed.")
    return _sub("Business Momentum", min(20, pts), 20, ev)


def _music_need(intel: Dict, signals: List[Dict], dms: List[Dict]) -> Dict:
    ev: List[str] = []
    pts = 0
    usage = _lval(intel.get("music_usage"))
    use_pts = min(8, len(usage) * 3)
    if use_pts:
        ev.append("Observed music usage: "
                  + ", ".join(v.replace("Uses ", "") for v in usage) + f" (+{use_pts})")
        pts += use_pts
    vh = [s for s in signals if s["music_relevance"] == "Very High"]
    hi = [s for s in signals if s["music_relevance"] == "High"]
    sig_pts = min(12, len(vh) * 5 + len(hi) * 3)
    if sig_pts:
        ev.append(f"{len(vh)} very-high + {len(hi)} high music-relevant signal(s) (+{sig_pts})")
        pts += sig_pts
    dm = next((d for d in dms if d["music_relevance"] in ("Very High", "High")
               and d["priority"] in ("Very High", "High")), None)
    if dm:
        ev.append(f"Music-relevant decision maker: {dm['name']}, {dm['title']} (+3)")
        pts += 3
    if _ival(intel.get("production_complexity")) == "High":
        ev.append("High production complexity implies recurring music need (+4)")
        pts += 4
    if not ev:
        ev.append("No direct music-need evidence yet — additional signals required.")
    return _sub("Music Need Probability", min(25, pts), 25, ev)


def _relationship_readiness(last_out, responded: bool) -> Dict:
    if last_out is None:
        return _sub("Relationship Readiness", 15, 15,
                    ["No prior outreach on record — fully open (+15)"])
    days = _days_since(last_out["occurred_at"])
    if days < 30:
        val, ev = 3, [f"Contacted {days}d ago — give it room (+3)"]
    elif days < 90:
        val, ev = 8, [f"Last contact {days}d ago (+8)"]
    else:
        val, ev = 13, [f"Last contact {days}d ago — fine to re-open (+13)"]
    if responded:
        val = min(15, val + 2)
        ev.append("Prior response on file — warm relationship (+2)")
    return _sub("Relationship Readiness", val, 15, ev)


def _contact_confidence(dms: List[Dict]) -> tuple:
    """Returns (sub_score, best_contact_or_None)."""
    def channel(d):
        return bool(d["email"]) or bool(d["linkedin_verified"])
    senior = [d for d in dms if d["priority"] in ("Very High", "High")]
    strong = next((d for d in senior if channel(d)), None)
    if strong:
        ch = "email" if strong["email"] else "verified LinkedIn"
        return (_sub("Contact Confidence", 10, 10,
                     [f"Strong contact: {strong['name']}, {strong['title']} ({ch}) (+10)"]),
                strong)
    any_channel = next((d for d in dms if channel(d)), None)
    if any_channel:
        return (_sub("Contact Confidence", 6, 10,
                     [f"Reachable contact: {any_channel['name']}, {any_channel['title']} (+6)"]),
                any_channel)
    if senior:
        return (_sub("Contact Confidence", 4, 10,
                     [f"Senior contact known, no direct channel: {senior[0]['name']} (+4)"]),
                senior[0])
    if dms:
        return (_sub("Contact Confidence", 3, 10,
                     ["Contacts identified but none senior or reachable (+3)"]), dms[0])
    return (_sub("Contact Confidence", 0, 10,
                 ["No decision makers identified yet — run decision-maker discovery."]), None)


def _timing(signals: List[Dict]) -> Dict:
    recent = [s for s in signals if s["music_relevance"] in ("Very High", "High")]
    if recent:
        newest = max(recent, key=lambda s: s["detected_at"])
        days = _days_since(newest["detected_at"])
        if days <= 14:
            return _sub("Timing (bonus)", 5, 5,
                        [f"Hot music signal {days}d ago: {newest['summary'][:60]} (+5)"])
        if days <= 30:
            return _sub("Timing (bonus)", 3, 5,
                        [f"Recent music signal {days}d ago (+3)"])
    return _sub("Timing (bonus)", 0, 5, ["No fresh music-relevant signal in the last 30 days."])


# --------------------------------------------------------------------------- #
# Strategy — recommendation, contact, timing, talking points
# --------------------------------------------------------------------------- #
def _tier(score: int) -> str:
    for name, floor in _TIERS:
        if score >= floor:
            return name
    return "D"


def _recommended_action(tier: str, readiness: Dict, timing: Dict, last_out) -> str:
    if last_out is not None and _days_since(last_out["occurred_at"]) < 30:
        wait = 30 - _days_since(last_out["occurred_at"])
        return f"Recently contacted — wait ~{wait} days before following up"
    if tier == "A" and timing["value"] >= 3:
        return "Reach out this week — strong fit with a fresh signal"
    if tier in ("A", "B"):
        return "Reach out within 30 days"
    if tier == "C":
        return "Nurture — monitor for stronger signals before reaching out"
    return "Monitor — not a priority yet"


def _best_timing(tier: str, timing: Dict, last_out) -> str:
    if last_out is not None and _days_since(last_out["occurred_at"]) < 30:
        return f"Hold ~{30 - _days_since(last_out['occurred_at'])} days (recently contacted)"
    if timing["value"] >= 5:
        return "Within 14 days"
    if timing["value"] >= 3 or tier in ("A", "B"):
        return "Within 30 days"
    return "Revisit when new signals appear"


def _talking_points(intel: Dict, signals: List[Dict], contact: Optional[Dict]) -> List[Dict]:
    points: List[Dict] = []

    def add(text, source):
        if text and len(points) < 6:
            points.append({"text": text, "source": source})

    for s in signals:
        if s["event_type"] in ("Campaign launch", "New work") and s["music_relevance"] in ("Very High", "High"):
            add(f"Mention their recent work: {s['summary']}", f"Signal · {s['detected_at'][:10]}")
            break
    for s in signals:
        if s["event_type"] in ("New client", "Account win"):
            add(f"Reference their new client win: {s['summary']}", f"Signal · {s['detected_at'][:10]}")
            break
    for s in signals:
        if s["event_type"] == "Hiring" and s["music_relevance"] in ("Very High", "High"):
            add(f"Note the new hire — production ramp-up: {s['summary']}", f"Signal · {s['detected_at'][:10]}")
            break
    if set(_lval(intel.get("creative_focus"))) & _MUSIC_FORMATS or \
            any("cinematic" in s.lower() for s in _lval(intel.get("production_style"))):
        add("Discuss original/orchestral scoring for their cinematic, emotionally-driven work",
            "Intelligence · Creative focus")
    usage = _lval(intel.get("music_usage"))
    if usage:
        add("They already use " + ", ".join(v.replace("Uses ", "").lower() for v in usage)
            + " — position clearance-certified original music as the upgrade",
            "Intelligence · Observed music usage")
    awards = [s for s in signals if s["event_type"] == "Award"]
    if awards:
        add(f"Reference their award: {awards[0]['summary']}", f"Signal · {awards[0]['detected_at'][:10]}")
    inds = _lval(intel.get("primary_industries"))
    if inds:
        add(f"Tailor to their {inds[0]} work", "Intelligence · Industries")
    if not points:
        add("Lead with a discovery question — limited evidence to personalize yet.",
            "Insufficient evidence")
    return points


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def score_agency(conn, agency_id: int) -> Dict:
    """Compute and store the Music Opportunity for one agency from stored data.
    Pure reasoning — no network. Records movement vs the last run and appends to
    the score history, so the score is alive. Returns a summary."""
    row = db.get_agency(conn, agency_id)
    if row is None:
        return {"agency_id": agency_id, "status": "error", "detail": "no such agency"}

    intel = db.get_agency_intel(conn, agency_id) or {}
    dms = [dict(d) for d in db.list_decision_makers(conn, agency_id)]
    signals = [dict(s) for s in db.list_opportunity_signals(conn, agency_id, active_only=True)]
    outreach = db.list_agency_outreach(conn, agency_id)
    last_out = db.last_agency_outreach(conn, agency_id)
    responded = any(o["responded"] for o in outreach)

    cf = _creative_fit(intel)
    bm = _business_momentum(intel, signals)
    mn = _music_need(intel, signals, dms)
    rr = _relationship_readiness(last_out, responded)
    cc, contact = _contact_confidence(dms)
    tm = _timing(signals)
    subs = [cf, bm, mn, rr, cc, tm]

    score = min(100, sum(s["value"] for s in subs))
    tier = _tier(score)

    prev = db.get_agency_score(conn, agency_id)
    prev_score = prev.get("score")
    movement = 0 if prev_score is None else score - prev_score
    history = list(prev.get("history") or [])
    now = datetime.now(timezone.utc)
    history.append({"date": now.isoformat(), "score": score, "tier": tier})
    history = history[-30:]

    # confidence in the score = how much evidence backs it
    conf = 45
    if (intel.get("overall_confidence") or 0) >= 60:
        conf += 15
    if signals:
        conf += 15
    if dms:
        conf += 10
    if _lval(intel.get("music_usage")):
        conf += 8
    if not intel:
        conf = min(conf, 30)
    conf = min(97, conf)

    action = _recommended_action(tier, rr, tm, last_out)
    why = [e for s in (mn, bm, cf) for e in s["evidence"] if "+" in e][:5]

    blob = {
        "score": score, "tier": tier, "confidence": conf, "movement": movement,
        "prev_score": prev_score, "subscores": subs,
        "why": why or ["Score reflects limited collected evidence."],
        "recommended_action": action,
        "recommended_contact": ({
            "name": contact["name"], "title": contact["title"],
            "email": contact["email"], "linkedin": contact["linkedin"],
            "music_relevance": contact["music_relevance"]} if contact else None),
        "best_timing": _best_timing(tier, tm, last_out),
        "talking_points": _talking_points(intel, signals, contact),
        "history": history, "computed_at": now.isoformat(),
        "inputs": {"signals": len(signals), "decision_makers": len(dms),
                   "outreach": len(outreach), "has_intel": bool(intel)},
    }
    db.save_agency_score(conn, agency_id, score=score, tier=tier,
                         movement=movement, blob=blob)
    conn.commit()
    return {"agency_id": agency_id, "status": "complete", "score": score,
            "tier": tier, "movement": movement}


def score_batch(conn, *, source: Optional[str] = None, limit: int = 100) -> Dict:
    """(Re)score a rotating batch of agencies that have an intelligence profile.
    Pure computation; cheap. Resumable — least-recently-scored first."""
    rows = db.agencies_to_score(conn, source=source, limit=limit)
    scored = 0
    movers = 0
    for r in rows:
        res = score_agency(conn, r["id"])
        if res["status"] == "complete":
            scored += 1
            if res["movement"]:
                movers += 1
    return {"scored": scored, "movers": movers, "considered": len(rows)}
