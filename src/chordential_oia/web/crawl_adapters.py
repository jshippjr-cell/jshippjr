"""Per-source crawl adapters (Discovery Phase 3).

The generic HTML parser (:func:`discovery.parse_opportunity_html`) is the floor;
sources with a structured feed get a dedicated adapter for cleaner, higher-yield
results.

**Reddit** — a top opportunity source — exposes a public JSON API for any listing
or search (no auth needed). If app credentials are present
(``REDDIT_CLIENT_ID`` / ``REDDIT_CLIENT_SECRET`` — Render secrets, an app's
client credentials, **never a user's password**) we use the official OAuth
endpoint for higher rate limits. Everything else falls back to the HTML scrape.

The human gate is unchanged — this only governs *how* an already-approved target
is fetched, never *whether*.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request
from typing import List, Optional

from ..talent_sources.scraped import scrape_enabled

# Reddit asks for a unique, descriptive User-Agent.
_REDDIT_UA = "web:chordential-discovery:1.0 (+https://chordential.com)"

# App-only OAuth token cache (client-credentials grant). Module-level is fine —
# single always-on instance; the token is short-lived and re-minted on expiry.
_token_cache = {"token": None, "exp": 0.0}


# --------------------------------------------------------------------------- #
# Small HTTP helper (custom headers — the generic path reuses discovery's)
# --------------------------------------------------------------------------- #
def _http_get(url: str, headers: dict, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _get_with_meta(url: str, headers: dict, timeout: float = 10.0):
    """GET returning (text, status, final_url) and never raising — so the caller
    can diagnose *why* a fetch came back empty (login wall, block, etc.)."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace"), resp.status, resp.geturl()
    except urllib.error.HTTPError as e:  # 401/403/429/5xx — keep the status
        return "", e.code, url
    except Exception:
        return "", 0, url


# Strong signals that content is walled behind a login (avoid generic "sign in"
# nav links, which appear on nearly every page and would false-positive).
_LOGIN_HINTS = (
    'type="password"', "sign in to view", "log in to view", "log in to see",
    "please log in", "members only", "subscription required", "subscribers only",
    "create a free account to", "sign up to see", "register to view",
)


def classify_outcome(text: str, status: int, final_url: str, n_records: int) -> str:
    """Diagnose a fetch: ok | login | blocked | error | empty."""
    if n_records > 0:
        return "ok"
    if status == 401:
        return "login"
    if status in (403, 429):
        return "blocked"
    if status == 0 or status >= 500:
        return "error"
    low = (text or "").lower()
    if "login" in (final_url or "").lower() or "signin" in (final_url or "").lower():
        return "login"
    if any(h in low for h in _LOGIN_HINTS):
        return "login"
    return "empty"  # fetched fine, but nothing matched (usually: no adapter yet)


# --------------------------------------------------------------------------- #
# Reddit adapter
# --------------------------------------------------------------------------- #
def is_reddit(target) -> bool:
    return "reddit" in (target["source_key"] or "") or "reddit.com" in (target["url"] or "")


def to_reddit_json_url(url: str, *, oauth: bool = False) -> str:
    """Turn a Reddit listing/search URL into its ``.json`` API form, preserving
    the query (``?q=…&sort=new`` etc.) and asking for a sane page size."""
    p = urllib.parse.urlsplit(url)
    path = p.path.rstrip("/")
    if not path.endswith(".json"):
        path += ".json"
    q = dict(urllib.parse.parse_qsl(p.query))
    q.setdefault("limit", "25")
    q["raw_json"] = "1"
    netloc = "oauth.reddit.com" if oauth else (p.netloc or "www.reddit.com")
    return urllib.parse.urlunsplit(
        (p.scheme or "https", netloc, path, urllib.parse.urlencode(q), "")
    )


def _reddit_token() -> Optional[str]:
    """App-only OAuth bearer token, if client credentials are configured. Returns
    None (→ use the public endpoint) when unset or on any failure."""
    cid = os.environ.get("REDDIT_CLIENT_ID")
    secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    now = time.time()
    if _token_cache["token"] and _token_cache["exp"] > now + 30:
        return _token_cache["token"]
    try:
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        req = urllib.request.Request(
            "https://www.reddit.com/api/v1/access_token",
            data=data,
            headers={"User-Agent": _REDDIT_UA, "Authorization": f"Basic {basic}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode())
        _token_cache["token"] = payload.get("access_token")
        _token_cache["exp"] = now + float(payload.get("expires_in", 3600))
        return _token_cache["token"]
    except Exception:
        return None


def parse_reddit_json(text: str) -> List[dict]:
    """Reddit listing/search JSON → opportunity-lead dicts. Drops ``[For Hire]``
    self-promo (that's talent, not a gig) to keep the demand queue precise."""
    out: List[dict] = []
    try:
        data = json.loads(text)
    except Exception:
        return out
    children = (data.get("data") or {}).get("children") or []
    for ch in children:
        d = ch.get("data") or {}
        title = (d.get("title") or "").strip()
        if not title:
            continue
        low = title.lower()
        if "for hire" in low and "hiring" not in low:
            continue  # a creator advertising themselves, not an opportunity
        author = d.get("author") or ""
        sub = d.get("subreddit") or ""
        permalink = d.get("permalink") or ""
        out.append({
            "company": (f"u/{author}" if author else sub) or "(reddit)",
            "need": title[:200],
            "description": (d.get("selftext") or "")[:1000],
            "url": (f"https://www.reddit.com{permalink}" if permalink else d.get("url")),
        })
    return out


def fetch_reddit(url: str) -> dict:
    token = _reddit_token()
    json_url = to_reddit_json_url(url, oauth=bool(token))
    headers = {"User-Agent": _REDDIT_UA}
    if token:
        headers["Authorization"] = f"bearer {token}"
    text, status, final_url = _get_with_meta(json_url, headers)
    records = parse_reddit_json(text)
    outcome = classify_outcome(text, status, final_url, len(records))
    # Reddit blocks unauthenticated API traffic from datacenters — call that out.
    detail = ""
    if outcome == "blocked" and not token:
        detail = "Reddit blocked the request — add REDDIT_CLIENT_ID/SECRET for the official API."
    return {"records": records, "outcome": outcome, "detail": detail}


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def fetch_opportunity_records(target) -> dict:
    """Fetch one opportunity target via the best adapter for its source. Returns
    a diagnosis: ``{"records": [...], "outcome": ok|login|blocked|empty|error,
    "detail": str}``. ``outcome == "off"`` when scraping is disabled."""
    if not scrape_enabled():
        return {"records": [], "outcome": "off", "detail": ""}
    if is_reddit(target):
        return fetch_reddit(target["url"])
    # Generic HTML floor — reuse discovery's parser (lazy import avoids a cycle).
    from . import discovery
    text, status, final_url = _get_with_meta(
        target["url"], {"User-Agent": "ChordentialDiscoveryBot/1.0 (+https://chordential.com)"}
    )
    records = discovery.parse_opportunity_html(text)
    outcome = classify_outcome(text, status, final_url, len(records))
    return {"records": records, "outcome": outcome, "detail": ""}
