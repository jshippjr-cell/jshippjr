"""Signal Engine — the Opportunity Detection layer (Phase 1).

A *signal* is the trading-desk tape: a detected opportunity the moment we learn
of it, scored and stamped with when it was posted vs. when we found it. Signals
are ranked by **freshness × score** (not score alone) and promoted into the
pipeline through the same human gate leads use.

Detection is the new layer; parsing (``intake``) and scoring (``evaluate``)
already exist and are reused here.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import quote_plus

from ..intake import extract_budget, parse_alert_email
from ..models import Opportunity
from . import db, rss
from .evaluate import evaluate

# Source priority (from the council weighting). Longest-match wins.
SOURCE_WEIGHTS = {
    "productionhub": 10, "mandy": 10, "agency": 10, "hitmarker": 9,
    "staffmeup": 8, "linkedin": 7, "thedots": 7, "f5bot": 7, "email": 7,
    "behance": 6, "google": 6, "rss": 6, "paste": 6, "reddit": 6,
    "upwork": 5, "soundbetter": 4,
}

# Freshness half-life: a signal's rank decays as it ages, so a fresh B-tier
# outranks a day-old A-tier (you can still be the first email in the inbox).
TAU_HOURS = 12.0


def weight_for(source: str) -> int:
    s = (source or "").lower()
    best = 5
    for key, w in SOURCE_WEIGHTS.items():
        if key in s:
            best = max(best, w)
    return best


# --------------------------------------------------------------------------- #
# Scoring + freshness ranking
# --------------------------------------------------------------------------- #
def _score(title: str, body: str, bmin, bmax):
    opp = Opportunity(
        client="Unknown", need=title or "Opportunity", description=body or "",
        budget_min=bmin, budget_max=bmax,
    )
    _, scored = evaluate(opp)
    return scored.score, getattr(scored.tier, "value", str(scored.tier))


def age_hours(posted_at: Optional[str], now: Optional[datetime] = None) -> float:
    if not posted_at:
        return 0.0
    now = now or datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(posted_at)
    except Exception:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def freshness(age_h: float) -> float:
    return math.exp(-age_h / TAU_HOURS)


def rank_value(score: Optional[float], posted_at: Optional[str], now=None) -> float:
    return (score or 0.0) * freshness(age_hours(posted_at, now))


def rank_signals(rows) -> List[dict]:
    """Attach age + freshness×score rank to each signal and sort, freshest-best."""
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        a = age_hours(r["posted_at"], now)
        out.append({
            "row": r, "age_hours": a, "age_label": _age_label(a), "fresh": a < 2.0,
            "rank": rank_value(r["score"], r["posted_at"], now),
        })
    out.sort(key=lambda d: d["rank"], reverse=True)
    return out


def _age_label(h: float) -> str:
    if h < 1:
        return f"{int(h * 60)}m"
    if h < 24:
        return f"{int(h)}h"
    return f"{int(h / 24)}d"


# --------------------------------------------------------------------------- #
# Ingest adapters — many feeders, one tape
# --------------------------------------------------------------------------- #
def ingest_signal(
    conn, *, source: str, title: str, body: str = "", url: str = "",
    external_ref: str = "", budget_min=None, budget_max=None, posted_at=None,
) -> Optional[int]:
    title = (title or "").strip()
    if not title:
        return None
    bmin, bmax = budget_min, budget_max
    if bmin is None and bmax is None:
        bmin, bmax = extract_budget(f"{title}\n{body}", labeled_only=True)
    score, tier = _score(title, body, bmin, bmax)
    return db.insert_signal(
        conn, source=source, source_weight=weight_for(source),
        title=title[:300], body=(body or "")[:5000], url=url,
        external_ref=external_ref or url, budget_min=bmin, budget_max=bmax,
        score=score, tier=tier, posted_at=posted_at,
    )


def ingest_alert(conn, raw: str, source: str = "email") -> int:
    """Parse a forwarded saved-search / F5Bot alert email into signals."""
    n = 0
    for o in parse_alert_email(raw):
        ref = f"{o.need}|{o.client or ''}"[:200]
        if ingest_signal(
            conn, source=source, title=o.need, body=o.description or "",
            budget_min=o.budget_min, budget_max=o.budget_max, external_ref=ref,
        ):
            n += 1
    return n


_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_LABEL_RE = re.compile(r"(?im)^\s*(title|role|gig|position|job|project)\s*[:\-]")


def _signals_from_links(body: str) -> List[dict]:
    """Link-list alerts (F5Bot / Google Alerts): one candidate per URL, titled by
    the text on its line (or the nearest preceding non-empty line). Deduped."""
    out, seen = [], set()
    lines = (body or "").splitlines()
    for i, line in enumerate(lines):
        for m in _URL_RE.finditer(line):
            url = m.group(0).rstrip(".,);]")
            if url in seen:
                continue
            seen.add(url)
            title = line.replace(url, "").strip(" -–—|:•\t")
            if len(title) < 4:
                for j in range(i - 1, -1, -1):
                    if lines[j].strip():
                        title = lines[j].strip()
                        break
            out.append({"title": (title or url)[:200], "url": url})
    return out


def ingest_email(conn, subject: str, body: str, source: str = "email") -> int:
    """Robustly turn any forwarded alert email into signals. Labeled digests
    (Mandy/ProductionHUB) go through the structured parser; link-list alerts
    (F5Bot/Google Alerts) become one signal per link."""
    body = body or ""
    text = f"{subject}\n{body}" if subject else body
    links = _signals_from_links(body)
    # Structured digest, or a single forwarded posting → the rich parser.
    if _LABEL_RE.search(body) or len(links) < 2:
        n = 0
        for o in parse_alert_email(text):
            ref = f"{o.need}|{o.client or ''}"[:200]
            if ingest_signal(
                conn, source=source, title=o.need, body=o.description or "",
                budget_min=o.budget_min, budget_max=o.budget_max, external_ref=ref,
            ):
                n += 1
        if n:
            return n
    # Link-list alert → one signal per match.
    n = 0
    for c in links:
        if ingest_signal(
            conn, source=source, title=c["title"], url=c["url"], external_ref=c["url"]
        ):
            n += 1
    return n


def ingest_feed(conn, feed_url: str, source: str = "rss") -> int:
    """Poll one RSS/Atom feed of live gigs into signals (deduped on item link)."""
    n = 0
    for it in rss.fetch_feed(feed_url):
        posted = it["published"].isoformat() if it.get("published") else None
        if ingest_signal(
            conn, source=source, title=it["title"], body=it.get("summary", ""),
            url=it.get("link", ""), external_ref=it.get("link") or it["title"],
            posted_at=posted,
        ):
            n += 1
    return n


# --------------------------------------------------------------------------- #
# Leading indicators (the moat) — detect "music spend incoming" via Google News
# RSS, BEFORE a brief exists. These are not gigs to qualify; they're accounts to
# get ahead of. Scored by the indicator's strength, not the gig rubric.
# --------------------------------------------------------------------------- #
def _gnews(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
    )


# (label, base_score, google-news query) — tune freely.
LEAD_INDICATOR_FEEDS = [
    ("Agency-of-record wins", 72,
     '"agency of record" OR "wins creative account" OR "names creative agency"'),
    ("Brand rebrands (sonic branding)", 66,
     '"new brand identity" OR rebrand OR "brand refresh" OR "rebranding"'),
    ("New film/TV productions", 60,
     '"ordered to series" OR greenlit OR "begins production" series'),
    ("New game productions", 58,
     '"announces new game" OR "reveals new game" OR "new game studio"'),
    ("New ad campaigns", 54,
     '"launches campaign" OR "unveils new campaign" OR "debuts campaign"'),
]


def ingest_indicator_feed(conn, label: str, base_score: float, query: str) -> int:
    """Poll one leading-indicator Google-News feed into signals (type=indicator)."""
    n = 0
    for it in rss.fetch_feed(_gnews(query)):
        posted = it["published"].isoformat() if it.get("published") else None
        if db.insert_signal(
            conn, source=label, source_weight=weight_for("agency"),
            title=(it["title"] or "")[:300], body=(it.get("summary") or "")[:2000],
            url=it.get("link", ""), external_ref=it.get("link") or it["title"],
            score=base_score, tier="Indicator", posted_at=posted,
            signal_type="indicator",
        ):
            n += 1
    return n
