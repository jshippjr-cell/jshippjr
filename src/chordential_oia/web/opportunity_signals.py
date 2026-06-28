"""Signal Detection Framework — the Opportunity Intelligence layer.

The breakthrough the spec calls for: don't monitor websites, monitor CHANGE. The
enrichment engine already collects each agency's portfolio, awards, leadership,
careers, news and clients. This framework diffs that collected profile against a
stored baseline and emits a standardized **Signal** only for meaningful, NEW
changes — the moments a sales exec would say "I should call them today."

Architecture (each detector has ONE responsibility — check for change, else stop,
else emit a Signal):
    Hiring · News · Portfolio · Award · Client · Leadership  →  Signal
Adding a source later = writing another detector that yields the same Signal shape.

Two design points from the spec:
  * Change detection via a "seen" set, not re-scraping. First scan BASELINES the
    agency (records what already exists); later scans emit only what's new. A
    fingerprint short-circuits agencies that haven't changed at all. Current-
    activity detectors (Hiring, News) emit on the baseline too, since an open role
    or a recent press item is a live signal now; back-catalogue detectors
    (Portfolio, Award, Client, Leadership) baseline silently and emit only
    additions — a 2-year-old case study isn't a fresh signal.
  * Music Trigger on every signal: beyond generic importance, each Signal carries
    a music_relevance + reason — does THIS event raise the odds they'll commission
    original music? That's the layer that makes outreach well-timed, not generic.

This engine does NOT score. It discovers and stores verified signals; scoring is a
later layer that simply reads the timeline. Pure computation over stored data — no
network — so it's deterministic and safe to re-run.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import db
from .enrichment import AgencyProfile

_LEVELS = ("Low", "Medium", "High", "Very High")


def _key(*parts: str) -> str:
    raw = "|".join(re.sub(r"\s+", " ", (p or "")).strip().lower() for p in parts)
    return parts[0] + ":" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


@dataclass
class Signal:
    dedup_key: str
    event_type: str
    category: str
    importance: str
    music_relevance: str
    summary: str
    source: str = "Agency Website"
    source_url: str = ""
    confidence: int = 85
    evidence: List[str] = field(default_factory=list)
    ttl_days: int = 90

    def to_row(self, now: datetime) -> dict:
        return {
            "dedup_key": self.dedup_key, "event_type": self.event_type,
            "category": self.category, "importance": self.importance,
            "music_relevance": self.music_relevance, "confidence": self.confidence,
            "summary": self.summary, "source": self.source,
            "source_url": self.source_url, "evidence": self.evidence,
            "event_date": now.isoformat(), "detected_at": now.isoformat(),
            "expires_at": (now + timedelta(days=self.ttl_days)).isoformat(),
        }


# --------------------------------------------------------------------------- #
# Music Trigger Detector — does THIS event raise the odds of needing music?
# Centralized so every detector tags its signal the same way (with a reason).
# --------------------------------------------------------------------------- #
_FILM_WORDS = re.compile(r"film|cinematic|broadcast|commercial|tvc|spot|brand film|documentary|trailer", re.I)
_SOCIAL_WORDS = re.compile(r"social|tiktok|short-form|reel|web design|website|banner|seo|ux|ui", re.I)


def music_trigger(event_type: str, detail: str) -> tuple:
    """(music_relevance, reason) for an event. The spec's table, generalized:
    music/production/cinematic → very high; web/social/admin → low."""
    d = detail or ""
    if event_type == "Hiring":
        if re.search(r"compos|music", d, re.I):
            return "Very High", "Hiring a music/composer role — a direct in-house music need."
        if re.search(r"executive producer|head of production", d, re.I):
            return "Very High", "Hiring a senior producer — owns production budgets incl. music."
        if re.search(r"sound design|audio", d, re.I):
            return "High", "Hiring audio/sound — adjacent to music commissioning."
        if re.search(r"\bproducer\b|production", d, re.I):
            return "High", "Hiring a producer — commissions music for productions."
        if re.search(r"creative director|chief creative", d, re.I):
            return "High", "Hiring a creative lead — sets briefs that call for music."
        if re.search(r"editor|motion|animat", d, re.I):
            return "Medium", "Hiring craft/post — production ramp-up that often needs music."
        return "Low", "Hiring in a non-creative function — limited music signal."
    if event_type in ("New client", "New client win", "Account win"):
        if re.search(r"agency of record|aor|global", d, re.I):
            return "Very High", "Won a global / agency-of-record account — sustained production = recurring music need."
        return "High", "New client win — new productions likely, which need music."
    if event_type in ("Campaign launch", "New work"):
        if _FILM_WORDS.search(d):
            return "Very High", "Cinematic / broadcast work — original music is typically central."
        if _SOCIAL_WORDS.search(d):
            return "Low", "Web/social work — lower likelihood of commissioned original music."
        return "High", "New campaign work — a likely music moment."
    if event_type == "Award":
        if _FILM_WORDS.search(d) or re.search(r"craft|sound|music|film", d, re.I):
            return "High", "Film/craft award — signals high-production work that uses music."
        if _SOCIAL_WORDS.search(d) or re.search(r"web|design|digital", d, re.I):
            return "Low", "Web/design award — limited music signal."
        return "Medium", "Industry award — signals production activity."
    if event_type == "Partnership":
        return "Medium", "New partnership — may lead to co-produced work."
    if event_type in ("Acquisition", "Merger"):
        return "Medium", "M&A — capability/account changes that can drive new productions."
    if event_type == "Expansion":
        return "Low", "Office expansion — growth signal, weak music signal."
    if event_type == "Leadership change":
        if re.search(r"compos|music|producer|creative", d, re.I):
            return "High", "New creative/production leader — re-sets vendor relationships."
        return "Medium", "Leadership change — a relationship opening."
    return "Low", "General activity."


_GENERIC_IMPORTANCE = {
    "Hiring": "Medium", "New client": "High", "Campaign launch": "High",
    "New work": "Medium", "Award": "High", "Partnership": "High",
    "Acquisition": "High", "Merger": "High", "Expansion": "Medium",
    "Leadership change": "Medium", "Press": "Low",
}
_TTL = {
    "Hiring": 60, "New client": 90, "Campaign launch": 90, "New work": 90,
    "Award": 180, "Partnership": 120, "Acquisition": 180, "Merger": 180,
    "Expansion": 150, "Leadership change": 120, "Press": 45,
}


def _make(event_type: str, category: str, detail: str, summary: str,
          *, source="Agency Website", source_url="", confidence=85,
          evidence=None, key_extra="") -> Signal:
    mr, reason = music_trigger(event_type, detail)
    return Signal(
        dedup_key=_key(_CAT_KEY.get(event_type, "sig"), category, detail or summary, key_extra),
        event_type=event_type, category=category,
        importance=_GENERIC_IMPORTANCE.get(event_type, "Medium"),
        music_relevance=mr, summary=summary, source=source, source_url=source_url,
        confidence=confidence, evidence=(evidence or []) + [reason],
        ttl_days=_TTL.get(event_type, 90))


_CAT_KEY = {
    "Hiring": "hiring", "New client": "client", "Campaign launch": "news",
    "New work": "work", "Award": "award", "Partnership": "news",
    "Acquisition": "news", "Merger": "news", "Expansion": "news",
    "Leadership change": "leader", "Press": "news",
}


# --------------------------------------------------------------------------- #
# Detectors. Each yields (signals, emit_on_baseline). Detectors do not touch the
# DB or the network — they read the profile and return candidate Signals.
# --------------------------------------------------------------------------- #
def detect_hiring(profile: AgencyProfile) -> List[Signal]:
    out = []
    src = profile.careers_url or profile.website
    for role in profile.open_roles:
        role = role.strip()
        if not role:
            continue
        out.append(_make("Hiring", "Hiring", role, f"Hiring: {role}",
                         source="Careers", source_url=src,
                         evidence=[f"Open role listed: “{role}”"]))
    return out


_NEWS_RULES = [
    (re.compile(r"agency of record|\baor\b", re.I), "New client", "Client"),
    (re.compile(r"\bwins?\b|won|secures?|appointed by|named (?:agency|by)|adds? .* (?:as|to) client", re.I), "New client", "Client"),
    (re.compile(r"acquir", re.I), "Acquisition", "M&A"),
    (re.compile(r"\bmerg", re.I), "Merger", "M&A"),
    (re.compile(r"partner(?:s|ship|ed)?\b|teams up|collaborat", re.I), "Partnership", "Partnership"),
    (re.compile(r"open(?:s|ed|ing)? (?:a )?(?:new )?office|expand|new studio|new hq", re.I), "Expansion", "Expansion"),
    (re.compile(r"launch|unveil|debut|releas|premiere|drops?\b|new campaign|new film", re.I), "Campaign launch", "Campaign"),
    (re.compile(r"\blion\b|cannes|d&ad|one show|clio|effie|grand prix|award|wins gold", re.I), "Award", "Award"),
    (re.compile(r"appoints?|hires?|joins?|promotes?|names? .* (?:ceo|cco|ecd|director|head)", re.I), "Leadership change", "Leadership"),
]


def detect_news(profile: AgencyProfile) -> List[Signal]:
    out = []
    for item in profile.news:
        title = item.get("title", "") if isinstance(item, dict) else str(item)
        url = item.get("url", "") if isinstance(item, dict) else ""
        title = title.strip()
        if not title:
            continue
        etype, cat = "Press", "Press"
        for pat, et, c in _NEWS_RULES:
            if pat.search(title):
                etype, cat = et, c
                break
        out.append(_make(etype, cat, title, title, source="Press/News",
                         source_url=url, evidence=[f"News item: “{title[:120]}”"],
                         key_extra=title))
    return out


def detect_portfolio(profile: AgencyProfile) -> List[Signal]:
    out = []
    for title in profile.portfolio:
        title = title.strip()
        if not title:
            continue
        out.append(_make("New work", "Portfolio", title,
                         f"New work in portfolio: {title}",
                         source_url=profile.sources.get("work", profile.website),
                         evidence=[f"Portfolio entry: “{title[:120]}”"], key_extra=title))
    return out


def detect_awards(profile: AgencyProfile) -> List[Signal]:
    out = []
    for award in profile.awards:
        award = award.strip()
        if not award:
            continue
        out.append(_make("Award", "Award", award, f"Award: {award}",
                         source_url=profile.sources.get("awards", profile.website),
                         evidence=[f"Award listed: “{award[:120]}”"], key_extra=award))
    return out


def detect_clients(profile: AgencyProfile) -> List[Signal]:
    out = []
    for client in profile.clients:
        client = client.strip()
        if not client:
            continue
        out.append(_make("New client", "Client", client,
                         f"Client on roster: {client}",
                         source_url=profile.sources.get("clients", profile.website),
                         evidence=[f"Client named: “{client}”"], key_extra=client))
    return out


def detect_leadership(profile: AgencyProfile) -> List[Signal]:
    out = []
    for person in profile.leadership:
        name = (person.get("name") or "").strip() if isinstance(person, dict) else str(person)
        title = (person.get("title") or "").strip() if isinstance(person, dict) else ""
        if not name:
            continue
        out.append(_make("Leadership change", "Leadership", title or name,
                         f"Leadership: {name}" + (f", {title}" if title else ""),
                         source_url=profile.sources.get("leadership", profile.website),
                         evidence=[f"Listed on leadership page: {name}"
                                   + (f" ({title})" if title else "")], key_extra=name))
    return out


# (detector fn, emits-on-first-baseline?) — current-activity detectors emit on the
# baseline; back-catalogue detectors baseline silently and emit only additions.
_DETECTORS = [
    (detect_hiring, True),
    (detect_news, True),
    (detect_portfolio, False),
    (detect_awards, False),
    (detect_clients, False),
    (detect_leadership, False),
]


def _fingerprint(profile: AgencyProfile) -> str:
    parts = [
        "|".join(profile.open_roles), "|".join(profile.awards),
        "|".join(profile.portfolio), "|".join(profile.clients),
        "|".join(n.get("title", "") if isinstance(n, dict) else str(n) for n in profile.news),
        "|".join(p.get("name", "") if isinstance(p, dict) else str(p) for p in profile.leadership),
    ]
    return hashlib.md5("␟".join(parts).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def detect_signals(conn, agency_id: int, *, force: bool = False) -> Dict:
    """Scan ONE agency for new opportunity signals. Diffs the current enriched
    profile against the stored snapshot; baselines on first scan, then emits only
    NEW changes. A fingerprint short-circuit skips agencies that haven't changed.
    Returns {status, new, baselined}. Stores nothing it has seen before."""
    row = db.get_agency(conn, agency_id)
    if row is None:
        return {"agency_id": agency_id, "status": "error", "detail": "no such agency"}

    state = db.get_agency_enrichment(conn, agency_id) or {}
    if state.get("status") != "complete":
        return {"agency_id": agency_id, "status": "skipped",
                "detail": "not enriched yet", "new": 0}
    profile = AgencyProfile.from_dict(state.get("profile"))

    snapshot = db.get_agency_signal_snapshot(conn, agency_id)
    seen = set(snapshot.get("seen") or [])
    baselined = bool(snapshot.get("baselined"))
    fp = _fingerprint(profile)
    if not force and baselined and snapshot.get("fingerprint") == fp:
        return {"agency_id": agency_id, "status": "unchanged", "new": 0}

    now = datetime.now(timezone.utc)
    new_count = 0
    for detect, emit_on_baseline in _DETECTORS:
        for sig in detect(profile):
            if sig.dedup_key in seen:
                continue
            seen.add(sig.dedup_key)
            if not baselined and not emit_on_baseline:
                continue                          # silent baseline of back-catalogue
            if db.insert_opportunity_signal(conn, agency_id, sig.to_row(now)):
                new_count += 1

    db.save_agency_signal_snapshot(conn, agency_id, {
        "fingerprint": fp, "baselined": True, "seen": sorted(seen),
        "last_scan": now.isoformat()})
    conn.commit()
    return {"agency_id": agency_id, "status": "complete", "new": new_count,
            "baselined": not baselined}


def detect_batch(conn, *, source: Optional[str] = None, limit: int = 100,
                 force: bool = False) -> Dict:
    """Scan a rotating batch of enriched agencies for new signals. Cheap: the
    fingerprint short-circuits unchanged agencies. Resumable — least-recently-
    scanned first, so repeated calls sweep the whole database."""
    rows = db.agencies_for_signal_scan(conn, source=source, limit=limit)
    new_total = 0
    scanned = 0
    for r in rows:
        res = detect_signals(conn, r["id"], force=force)
        if res["status"] in ("complete", "unchanged"):
            scanned += 1
            new_total += res.get("new", 0)
    return {"scanned": scanned, "new": new_total, "considered": len(rows)}


def agency_timeline(conn, agency_id: int, *, active_only: bool = False) -> List[dict]:
    """The agency's opportunity timeline as plain dicts (evidence decoded)."""
    import json
    out = []
    for r in db.list_opportunity_signals(conn, agency_id, active_only=active_only):
        try:
            evidence = json.loads(r["evidence_json"]) if r["evidence_json"] else []
        except (json.JSONDecodeError, TypeError):
            evidence = []
        out.append({
            "event_type": r["event_type"], "category": r["category"],
            "importance": r["importance"], "music_relevance": r["music_relevance"],
            "confidence": r["confidence"], "summary": r["summary"],
            "source": r["source"], "source_url": r["source_url"],
            "evidence": evidence, "detected_at": r["detected_at"],
            "expires_at": r["expires_at"],
            "expired": bool(r["expires_at"]) and r["expires_at"] < datetime.now(timezone.utc).isoformat(),
        })
    return out
