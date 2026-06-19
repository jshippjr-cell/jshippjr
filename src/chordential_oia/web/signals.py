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
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

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
# Demand vs. supply intent. F5Bot/keyword alerts can't tell "Composer needed"
# (a gig) from "Composer looking for work" (talent self-promo) — so we filter it
# here. Wide net at the alerter; precision at ingest. Tune these freely.
_SUPPLY_MARKERS = (
    "[for hire]", "for hire", "looking for work", "available for hire",
    "available for work", "available to compose", "open to work",
    "open for commissions", "open for work", "hire me", "i'm a composer",
    "i am a composer", "i'm a music", "offering my", "my portfolio",
    "freelance composer available", "i compose", "i can compose", "i make music",
    "check out my", "my services", "commissions open",
)
_DEMAND_MARKERS = (
    "[hiring]", "[paid]", "needed", "need a", "needs a", "needs an", "in need of",
    "we need", "we're looking", "we are looking",
    "looking for a composer", "looking for composer",
    "looking for a music", "looking for music", "seeking", "hiring", "wanted",
    "commission a", "in search of", "searching for", "looking to hire",
    "paid gig", "budget", "we're making", "we are making", "our game", "our film",
)


def intent(title: str, body: str = "") -> str:
    """'demand' (a real gig), 'supply' (talent self-promo), or 'unknown'."""
    t = f"{title} {body}".lower()
    demand = any(m in t for m in _DEMAND_MARKERS)
    supply = any(m in t for m in _SUPPLY_MARKERS)
    # An explicit self-promo stays 'supply' even if it quotes a rate. Otherwise a
    # money/pay signal is enough to call it a real (demand) gig — it rescues paid
    # posts that never use a hiring verb ("Composer for our game — $500/track").
    if supply and not demand:
        return "supply"
    if demand or _MONEY_RE.search(t):
        return "demand"
    return "unknown"


# A real music gig (for the noisy keyword-alert sources). Must name a music role
# AND express hiring intent AND not be a collab/hobby/unpaid ask. This is the
# "ironclad" filter — everything else (discussions, news, polls, self-promo,
# off-topic, comments-on-old-posts) is dropped before it ever reaches the radar.
_MUSIC_ROLE_MARKERS = (
    "composer", "compose", "composing", "score", "scoring", "soundtrack",
    "original music", "original score", "sound design", "sound designer",
    "sonic brand", "music composer", "film music", "game audio", "music for",
    "theme music", "underscore", "additional music", "music producer",
)
_COLLAB_MARKERS = (
    "collab", "join our", "join my", "join the", "bandmate",
    "band member", "virtual band", "looking for members", "for fun",
    "just for fun", "[hobby]", "hobby project", "passion project", "rev share",
    "revshare", "unpaid", "be a part of", "co-writer", "cowriter",
    "start a band", "form a band", "no pay", "non-paid", "no budget",
)
# A paid gig often signals money instead of saying "hiring" — "$500/track",
# "USD 2k", "paying", "day rate". Treat that as demand so we don't drop real,
# obviously-paid work on a keyword technicality. Currency-anchored so "4k video"
# (a resolution, not a budget) doesn't false-trigger.
_MONEY_RE = re.compile(
    r"\$\s?\d"                                              # $500, $2k, $1,000
    r"|\b(?:usd|eur|gbp|cad|aud)\s?\d"                      # USD 500
    r"|\bper\s+(?:track|song|cue|episode|minute|spot|ep)\b" # per track
    r"|/(?:track|song|cue|episode|min)\b"                   # /track
    r"|\b(?:paying|will pay|paid gig|pay is|rate is|hourly rate|flat fee|day rate)\b",
    re.IGNORECASE,
)


def is_music_gig(title: str, body: str = "") -> bool:
    t = f"{title} {body}".lower()
    if "reddit comment" in t:          # F5Bot comment match → old post, new comment
        return False
    if not any(m in t for m in _MUSIC_ROLE_MARKERS):
        return False
    if any(m in t for m in _COLLAB_MARKERS):
        return False
    return intent(title, body) == "demand"


def ingest_signal(
    conn, *, source: str, title: str, body: str = "", url: str = "",
    external_ref: str = "", budget_min=None, budget_max=None, posted_at=None,
    strict: bool = False, contact_handle: str = "",
) -> Optional[int]:
    title = (title or "").strip()
    if not title:
        return None
    if strict:
        # Noisy keyword-alert source (F5Bot etc.) — keep only real music gigs.
        if not is_music_gig(title, body):
            return None
    elif intent(title, body) == "supply":
        # Curated source — just drop talent self-promo.
        return None
    bmin, bmax = budget_min, budget_max
    if bmin is None and bmax is None:
        bmin, bmax = extract_budget(f"{title}\n{body}", labeled_only=True)
    score, tier = _score(title, body, bmin, bmax)
    sid = db.insert_signal(
        conn, source=source, source_weight=weight_for(source),
        title=title[:300], body=(body or "")[:5000], url=url,
        external_ref=external_ref or url, budget_min=bmin, budget_max=bmax,
        score=score, tier=tier, posted_at=posted_at,
        contact_handle=contact_handle or None,
    )
    if sid is not None:                      # a genuinely new gig cleared the filter
        notify_new_gig(title, url)
    return sid


def push_configured() -> bool:
    """True when a mobile-push topic is set (CHORDENTIAL_NTFY_TOPIC)."""
    return bool(os.environ.get("CHORDENTIAL_NTFY_TOPIC", "").strip())


# Last push failure detail, surfaced on the radar so a silent failure is
# diagnosable instead of vanishing into a bare "error".
_LAST_PUSH_ERROR = ""


def last_push_error() -> str:
    return _LAST_PUSH_ERROR


def _ascii_header(value: str) -> str:
    """HTTP headers are latin-1 only — an emoji or smart-quote in a header value
    makes urllib raise and the whole push silently fail. Drop anything that can't
    encode so the alert always goes out. (Emoji in the body/Tags is fine.)"""
    return (value or "").encode("latin-1", "ignore").decode("latin-1")


def send_push(title: str, body: str = "", click_url: str = "") -> str:
    """Send one ntfy.sh phone push. Returns a status: 'unset' (no topic
    configured), 'sent' (delivered to ntfy), or 'error' (network/ntfy failed).
    Best-effort — never raises."""
    global _LAST_PUSH_ERROR
    topic = os.environ.get("CHORDENTIAL_NTFY_TOPIC", "").strip()
    if not topic:
        return "unset"
    url = topic if topic.startswith("http") else f"https://ntfy.sh/{topic}"
    try:
        req = urllib.request.Request(
            url, data=(body or title or "New gig")[:240].encode("utf-8"),
            headers={
                "Title": _ascii_header(title or "New gig on Chordential")[:120],
                "Click": _ascii_header(click_url or "https://chordential.com/signals"),
                "Tags": "musical_note",   # ntfy renders this as 🎵 on the phone
                "Priority": "max",        # urgent → iOS plays sound + pops a banner
            },
        )
        urllib.request.urlopen(req, timeout=8)  # noqa: S310
        _LAST_PUSH_ERROR = ""
        return "sent"
    except Exception as e:                       # noqa: BLE001 — best-effort push
        _LAST_PUSH_ERROR = f"{type(e).__name__}: {e}"[:200]
        return "error"


def notify_new_gig(title: str, click_url: str = "") -> None:
    """Push a phone alert when a new live gig lands — only fires for gigs that
    passed the ironclad filter, so it's high-signal. Best-effort, never raises.

    Primary channel is native Web Push to the installed PWA (a real iOS/desktop
    notification that opens the app to the radar). ntfy.sh is kept as a fallback
    until Web Push is verified on the phone."""
    try:
        from . import webpush
        webpush.send_web_push("🎵 New gig on Chordential", body=title, url="/signals")
    except Exception:
        pass
    send_push("New gig on Chordential", body=title, click_url=click_url)


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


# "Reddit Posts (/r/sub/): 'Title' by author"  — F5Bot's per-match line.
# Group 4 captures the author handle so we can deep-link a DM to the poster.
_F5BOT_LINE = re.compile(
    r"Reddit\s+(Posts|Comments)\s*\(\s*(/r/[^)]+?)/?\s*\)\s*:\s*['\"]?(.*?)['\"]?(?:\s+by\s+(\S+))?\s*$",
    re.IGNORECASE,
)


def _unwrap_url(url: str) -> str:
    """F5Bot wraps links as f5bot.com/url?u=<real>. Unwrap to the real URL — both
    cleaner to show and easier to dedupe/classify."""
    if "f5bot.com/url" in url:
        q = parse_qs(urlparse(url).query)
        if q.get("u"):
            return unquote(q["u"][0])
    return url


def _signals_from_links(body: str) -> List[dict]:
    """Link-list alerts (F5Bot / Google Alerts): one candidate per URL. Parses
    F5Bot's "Reddit Posts (/r/sub/): 'Title'" lines into a clean title + source,
    DROPS comment matches (they fire on old posts), and unwraps the redirect."""
    out, seen = [], set()
    lines = (body or "").splitlines()
    for i, line in enumerate(lines):
        for m in _URL_RE.finditer(line):
            raw = m.group(0).rstrip(".,);]")
            url = _unwrap_url(raw)
            if url in seen:
                continue
            seen.add(url)
            ctx = line.replace(raw, "").strip(" -–—|:•\t")
            if len(ctx) < 4:
                for j in range(i - 1, -1, -1):
                    if lines[j].strip():
                        ctx = lines[j].strip()
                        break
            fm = _F5BOT_LINE.search(ctx)
            if fm:
                kind, sub, title = fm.group(1).lower(), fm.group(2), fm.group(3).strip()
                if kind == "comments":
                    continue   # a comment on a (usually old) post — never a gig
                handle = (fm.group(4) or "").strip().lstrip("/").removeprefix("u/")
                out.append({"title": (title or url)[:200], "url": url,
                            "source": sub, "handle": handle})
            else:
                out.append({"title": (ctx or url)[:200], "url": url, "source": "alert"})
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
    # Link-list alert (F5Bot/Google Alerts) → one signal per match, through the
    # ironclad music-gig filter (these sources are noisy).
    n = 0
    for c in links:
        if ingest_signal(
            conn, source=c.get("source") or source, title=c["title"],
            url=c["url"], external_ref=c["url"], strict=True,
            contact_handle=c.get("handle", ""),
        ):
            n += 1
    return n


def ingest_feed(conn, feed_url: str, source: str = "rss") -> int:
    """Poll one RSS/Atom feed of live gigs into signals (deduped on item link).
    Reddit feeds are noisy, so they get the strict is_music_gig filter; curated
    board feeds keep the lenient (supply-only) filter."""
    strict = "reddit" in feed_url.lower() or "reddit" in source.lower()
    n = 0
    for it in rss.fetch_feed(feed_url):
        posted = it["published"].isoformat() if it.get("published") else None
        if ingest_signal(
            conn, source=source, title=it["title"], body=it.get("summary", ""),
            url=it.get("link", ""), external_ref=it.get("link") or it["title"],
            posted_at=posted, strict=strict,
        ):
            n += 1
    return n
