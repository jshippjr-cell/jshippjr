"""Source registry + Source Health — the truth about where leads come from.

The signal engine can *rank* a lead from any source, but a source only actually
produces leads if something is wired to it. This module is the canonical list of
sources, maps incoming leads to them (e.g. an email from mandy.com → "mandy"),
and builds the dashboard's Source Health table: when each source last delivered a
lead, how many, and what the operator pays to subscribe.

Honesty by design: a source with no leads shows "never" — so an aspirational
entry (e.g. "Agency Intelligence", which isn't a platform you sign up for) can't
masquerade as a live feed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

# Canonical sources shown on the dashboard. `kind` sets expectations; `connect`
# is the one-line "how leads actually arrive" so nothing looks connected when it
# isn't. Reddit + Discord added per request.
SOURCES = [
    {"key": "productionhub", "label": "ProductionHUB", "url": "https://www.productionhub.com",
     "kind": "Paid board", "connect": "Saved-search email → Gmail label → triage",
     "tip": "Real lead source — commercial/film production. Paid to post (~$75+)."},
    {"key": "mandy", "label": "Mandy", "url": "https://www.mandy.com",
     "kind": "Paid board", "connect": "Saved-search email → Gmail label → triage",
     "tip": "Real but film/TV-weighted. Cheap applicant tier (~$8/mo)."},
    {"key": "agency", "label": "Agency Intelligence", "url": "",
     "kind": "Concept — not a signup platform", "connect": "Not a feed you subscribe to",
     "tip": "Not a platform — a monitoring idea. There is nothing here to subscribe to; it will always read 'never'."},
    {"key": "hitmarker", "label": "Hitmarker", "url": "https://hitmarker.net",
     "kind": "Free board (games/esports)", "connect": "Alert email → Gmail label → triage",
     "tip": "Real & free; game-focused, paid roles only. Good for game-audio leads."},
    {"key": "staffmeup", "label": "Staff Me Up", "url": "https://www.staffmeup.com",
     "kind": "Board (TV/film crew)", "connect": "Alert email → Gmail label → triage",
     "tip": "Marginal for a music house — TV post crew. Free tier is enough."},
    {"key": "linkedin", "label": "LinkedIn", "url": "https://www.linkedin.com",
     "kind": "Network", "connect": "Job-alert email → Gmail label → triage",
     "tip": "Real but relationship/outbound, not a brief feed. Don't pay for Premium just for this."},
    {"key": "thedots", "label": "The Dots", "url": "https://the-dots.com",
     "kind": "Network (UK)", "connect": "Alert email → Gmail label → triage",
     "tip": "Weak/niche — UK design & marketing. Only if you target UK agencies. Free."},
    {"key": "behance", "label": "Behance", "url": "https://www.behance.net",
     "kind": "Portfolio (visual)", "connect": "—",
     "tip": "Not a music lead source — visual-design network, ~no audio demand. Recommend skipping."},
    {"key": "upwork", "label": "Upwork", "url": "https://www.upwork.com",
     "kind": "Freelance marketplace", "connect": "Saved-search email → Gmail label → triage",
     "tip": "High volume but low-budget skew. Use selectively for entry leads."},
    {"key": "soundbetter", "label": "SoundBetter", "url": "https://soundbetter.com",
     "kind": "Music marketplace", "connect": "Alert email → Gmail label → triage",
     "tip": "Best 'pure music' marketplace here. Premium unlocks the job board (+5% commission)."},
    {"key": "reddit", "label": "Reddit", "url": "https://www.reddit.com",
     "kind": "Community (free)", "connect": "Subreddit RSS feeds (CHORDENTIAL_RSS_FEEDS)",
     "tip": "Free. Densest paid demand on r/gameDevClassifieds & r/forhire. See recommended channels below."},
    {"key": "discord", "label": "Discord", "url": "https://discord.com",
     "kind": "Community (manual)", "connect": "Manual — monitor #hiring channels (no public API)",
     "tip": "No public API; automated scraping breaks Discord ToS. Monitor #hiring channels manually. See recommended servers below."},
]

# From research — the channels actually worth following (see docs/lead-sources-research.md).
REDDIT_CHANNELS = [
    {"name": "r/gameDevClassifieds", "why": "Studios hiring composers/sound — best single source. This feed targets the [PAID] flair only.",
     "rss": 'https://www.reddit.com/r/gameDevClassifieds/search.rss?q=flair_name:"PAID"&restrict_sr=1&sort=new'},
    {"name": "r/forhire", "why": "General freelance; filter Hiring flair + music/composer/audio.",
     "rss": 'https://www.reddit.com/r/forhire/search.rss?q=flair_name:"hiring" (music OR composer OR audio)&restrict_sr=1&sort=new'},
    {"name": "r/composer", "why": "Commission/hire requests — lower volume, high relevance.",
     "rss": "https://www.reddit.com/r/composer/new/.rss"},
    {"name": "r/gameDevJobs", "why": "Game-dev jobs including audio roles.",
     "rss": "https://www.reddit.com/r/gameDevJobs/new/.rss"},
    {"name": "r/podcasting", "why": "Theme/intro music + sonic branding — recurring branding work.",
     "rss": 'https://www.reddit.com/r/podcasting/search.rss?q=music OR theme OR "sound design"&restrict_sr=1&sort=new'},
    {"name": "r/advertising", "why": "Agency sonic-branding / ad-music — rare but high-value.",
     "rss": 'https://www.reddit.com/r/advertising/search.rss?q="sonic branding" OR jingle OR "audio logo"&restrict_sr=1&sort=new'},
]

DISCORD_CHANNELS = [
    {"name": "Work With Indies", "why": "Indie-games jobs (~51K). Audio roles regularly — and a public web job board.",
     "invite": "https://discord.com/invite/workwithindies"},
    {"name": "Game Audio (Denizens)", "why": "Premier game-audio community; work/opportunities channels.",
     "invite": ""},
    {"name": "r/gamedev Discord", "why": "Large gamedev hub; recruitment/looking-for-team channels.",
     "invite": ""},
    {"name": "Video Game Music Lounge", "why": "VGM composers' network + collab channels.",
     "invite": "https://discord.com/invite/video-game-music-lounge"},
    {"name": "Gaming Careers", "why": "Games careers including audio; jobs channels.",
     "invite": "https://discord.com/invite/gamingcareers"},
    {"name": "TEAMMATES", "why": "Early-career composers/assistants — film/TV scoring (via VI-Control).",
     "invite": ""},
]

# Email sender domain → canonical source, so a board's alert email forwarded
# through Gmail triage is attributed to the board (not just "gmail").
_SENDER_SOURCE = {
    "mandy.com": "mandy", "productionhub.com": "productionhub", "hitmarker": "hitmarker",
    "staffmeup": "staffmeup", "linkedin.com": "linkedin", "the-dots": "thedots",
    "thedots": "thedots", "behance.net": "behance", "upwork.com": "upwork",
    "soundbetter.com": "soundbetter",
}


def source_for_sender(sender: str) -> str:
    """Map an email sender to a canonical source key; "gmail" if unrecognized."""
    s = (sender or "").lower()
    for domain, key in _SENDER_SOURCE.items():
        if domain in s:
            return key
    return "gmail"


def _bucket(raw_source: str) -> Optional[str]:
    """Bucket a stored signal source ("reddit-forhire", "mandy", …) into a
    canonical key (the canonical key it contains), else None (→ "other")."""
    s = (raw_source or "").lower()
    for src in SOURCES:
        if src["key"] in s:
            return src["key"]
    return None


def _ago(last_iso: Optional[str], now: datetime) -> str:
    if not last_iso:
        return "never"
    try:
        dt = datetime.fromisoformat(last_iso)
    except Exception:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = max(0, (now - dt).total_seconds())
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def health_rows(activity_rows, costs) -> dict:
    """Build the Source Health table: one row per canonical source + an "Other"
    bucket for everything else (paste, direct, f5bot…). ``activity_rows`` is from
    db.source_activity; ``costs`` is db.get_source_costs."""
    now = datetime.now(timezone.utc)
    # Aggregate raw signal sources into canonical buckets.
    agg = {src["key"]: {"last": None, "total": 0, "recent": 0} for src in SOURCES}
    other = {"last": None, "total": 0, "recent": 0}
    for r in activity_rows:
        key = _bucket(r["source"])
        slot = agg[key] if key else other
        slot["total"] += r["total"] or 0
        slot["recent"] += r["recent"] or 0
        if r["last_found"] and (slot["last"] is None or r["last_found"] > slot["last"]):
            slot["last"] = r["last_found"]

    rows = []
    total_cost = 0.0
    for src in SOURCES:
        a = agg[src["key"]]
        meta = costs.get(src["key"])
        cost = meta["monthly_cost"] if meta and meta["monthly_cost"] is not None else None
        if cost:
            total_cost += cost
        if a["recent"] > 0:
            status = "Receiving"
        elif a["total"] > 0:
            status = "Quiet"
        else:
            status = "No leads yet"
        rows.append({
            **src,
            "last": _ago(a["last"], now),
            "received": a["last"] is not None,
            "total": a["total"], "recent": a["recent"],
            "cost": cost, "notes": (meta["notes"] if meta else "") or "",
            "status": status,
        })
    return {
        "rows": rows,
        "other": {**other, "last_label": _ago(other["last"], now)},
        "total_monthly_cost": round(total_cost, 2),
    }
