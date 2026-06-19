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
from datetime import datetime, timezone
from typing import List, Optional

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


def ingest_feed(conn, feed_url: str, source: str = "rss") -> int:
    """Poll one RSS/Atom feed into signals (deduped on item link)."""
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
