"""Minimal RSS 2.0 / Atom feed reader for the Signal Engine.

Stdlib only, best-effort: returns [] on any error (a blocked or malformed feed
must never stall the poller). Job boards that expose a public feed plug straight
into the detection layer with near-zero latency.
"""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from urllib.parse import quote, urlsplit, urlunsplit


def _safe_url(url: str) -> str:
    """Percent-encode a feed URL so unencoded spaces / quotes in a search query
    (e.g. ``?q=composer OR music``) don't break the HTTP request. Already-encoded
    ``%xx`` are preserved (``%`` is in the safe set, so no double-encoding)."""
    p = urlsplit(url.strip())
    return urlunsplit((
        p.scheme, p.netloc,
        quote(p.path, safe="/%:@"),
        quote(p.query, safe="=&%+:,@"),
        p.fragment,
    ))


def _get(url: str, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(
        _safe_url(url),
        headers={"User-Agent": "ChordentialSignal/1.0 (+https://chordential.com)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return r.read()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _find(el, name: str):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def _parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)            # RFC-822 (RSS pubDate)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))  # ISO-8601 (Atom)
    except Exception:
        return None


def _rss_item(it) -> dict:
    return {
        "title": _text(_find(it, "title")),
        "link": _text(_find(it, "link")),
        "summary": _text(_find(it, "description")),
        "published": _parse_date(_text(_find(it, "pubdate"))),
    }


def _atom_entry(it) -> dict:
    le = _find(it, "link")
    link = (le.get("href") if le is not None else "") or _text(le)
    return {
        "title": _text(_find(it, "title")),
        "link": link,
        "summary": _text(_find(it, "summary")) or _text(_find(it, "content")),
        "published": _parse_date(_text(_find(it, "updated")) or _text(_find(it, "published"))),
    }


def parse_feed(raw) -> List[dict]:
    """Parse feed bytes/text into items. Exposed for testing without network."""
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    out: List[dict] = []
    for el in root.iter():
        ln = _local(el.tag)
        if ln == "item":
            out.append(_rss_item(el))
        elif ln == "entry":
            out.append(_atom_entry(el))
    return [i for i in out if i and i["title"]]


def fetch_feed(url: str) -> List[dict]:
    """Fetch + parse one feed. Returns [] on any failure (blocked/404/malformed)."""
    try:
        return parse_feed(_get(url))
    except Exception:
        return []
