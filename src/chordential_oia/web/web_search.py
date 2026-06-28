"""Web search seam — a provider-agnostic way to look up a person's public
LinkedIn profile and press mentions when the agency's own site doesn't expose
them. Null by default (returns nothing) exactly like the payments / mailer / LLM
seams, so the system is fully deterministic and offline until a provider is
configured; real when ``CHORDENTIAL_SEARCH_PROVIDER`` + that provider's key are set.

    search("Jane Doe Acme linkedin") -> [{"title", "url", "snippet"}, ...]

Honesty rule: this returns what the search engine returns — nothing is invented.
The caller (the Decision Maker engine) only ACCEPTS a found LinkedIn URL if it
structurally matches the person's name, and only treats off-site results as press.
Providers: SerpAPI (CHORDENTIAL_SEARCH_PROVIDER=serpapi, SERPAPI_KEY) and Google
Programmable Search (=google_cse, CHORDENTIAL_GOOGLE_CSE_KEY + _CX).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Dict, List

_TIMEOUT = 12.0
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _provider() -> str:
    return os.environ.get("CHORDENTIAL_SEARCH_PROVIDER", "").strip().lower()


def search_enabled() -> bool:
    """True only when a provider is configured (and thus a search can be made)."""
    return bool(_provider())


def _get_json(url: str) -> dict:                       # pragma: no cover - networked
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _serpapi(query: str, limit: int) -> List[Dict]:    # pragma: no cover - networked
    key = os.environ.get("SERPAPI_KEY") or os.environ.get("CHORDENTIAL_SERPAPI_KEY")
    if not key:
        return []
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(
        {"q": query, "api_key": key, "num": limit, "engine": "google"})
    data = _get_json(url)
    out = []
    for r in (data.get("organic_results") or [])[:limit]:
        if r.get("link"):
            out.append({"title": r.get("title", ""), "url": r["link"],
                        "snippet": r.get("snippet", "")})
    return out


def _google_cse(query: str, limit: int) -> List[Dict]:  # pragma: no cover - networked
    key = os.environ.get("CHORDENTIAL_GOOGLE_CSE_KEY")
    cx = os.environ.get("CHORDENTIAL_GOOGLE_CSE_CX")
    if not key or not cx:
        return []
    url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(
        {"key": key, "cx": cx, "q": query, "num": min(limit, 10)})
    data = _get_json(url)
    out = []
    for r in (data.get("items") or [])[:limit]:
        if r.get("link"):
            out.append({"title": r.get("title", ""), "url": r["link"],
                        "snippet": r.get("snippet", "")})
    return out


def search(query: str, *, limit: int = 6) -> List[Dict]:
    """Run a web search via the configured provider. Returns [] when no provider is
    set or on any error — best-effort, never raises, never blocks the engine."""
    provider = _provider()
    if not provider or not (query or "").strip():
        return []
    try:
        if provider == "serpapi":
            return _serpapi(query, limit)
        if provider in ("google_cse", "google", "cse"):
            return _google_cse(query, limit)
    except Exception:
        return []
    return []
