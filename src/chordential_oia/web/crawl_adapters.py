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
from html.parser import HTMLParser
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
# Agency Spotter adapter — "the Agency Spotter Agent"
#
# Agency Spotter is a directory of marketing/creative/production agencies. Those
# agencies are the demand side (they commission music for brand campaigns and
# hire composers), so each one is ingested as an opportunity lead — a buyer to
# qualify. The novel piece vs. the single-page adapters above is **pagination**:
# the agent walks the directory page-by-page and accumulates every agency it can
# reach, deduping within the run.
#
# Two safety rails keep "every page" honest rather than abusive:
#   - a bounded page cap (CHORDENTIAL_AGENCYSPOTTER_MAX_PAGES) so a runaway or
#     infinite paginator can't loop forever — and when the cap is hit we SAY SO
#     in ``detail`` instead of silently pretending we got everything; and
#   - a polite inter-page delay (CHORDENTIAL_AGENCYSPOTTER_DELAY seconds).
# Whether the agent runs at all is still the human gate (Approved target +
# scrape flag) — Agency Spotter ships login-gated, i.e. manual-assist.
# --------------------------------------------------------------------------- #
_AS_UA = "ChordentialDiscoveryBot/1.0 (+https://chordential.com)"
_AS_DEFAULT_MAX_PAGES = 50
_AS_DEFAULT_DELAY = 1.0


def is_agency_spotter(target) -> bool:
    return ("agencyspotter" in (target["source_key"] or "")
            or "agencyspotter.com" in (target["url"] or ""))


def _as_max_pages() -> int:
    """Hard ceiling on pages walked in one run (env-tunable, always >= 1)."""
    try:
        n = int(os.environ.get("CHORDENTIAL_AGENCYSPOTTER_MAX_PAGES", ""))
        return max(1, n)
    except (TypeError, ValueError):
        return _AS_DEFAULT_MAX_PAGES


def _as_page_delay() -> float:
    """Seconds to wait between page fetches (env-tunable, never negative)."""
    try:
        return max(0.0, float(os.environ.get("CHORDENTIAL_AGENCYSPOTTER_DELAY", "")))
    except (TypeError, ValueError):
        return _AS_DEFAULT_DELAY


def agency_spotter_page_url(url: str, page: int) -> str:
    """Return ``url`` with its ``page`` query param set to ``page`` (replacing any
    existing one), preserving every other param. Pure string work, no network."""
    p = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(p.query, keep_blank_values=True))
    q["page"] = str(page)
    return urllib.parse.urlunsplit(
        (p.scheme or "https", p.netloc, p.path, urllib.parse.urlencode(q), p.fragment)
    )


class _AgencyListingParser(HTMLParser):
    """Extract agency records from a documented listing structure::

        <li class="agency" data-name="AURORA Creative"
            data-specialties="branding,video,advertising"
            data-location="Austin, TX" data-url="https://.../aurora-creative"
            data-description="Full-service brand studio."></li>

    Only elements whose class includes ``agency`` are read, so page chrome,
    filters, and pagination controls are ignored. Mirrors the structured-listing
    convention used by the talent and opportunity parsers.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: List[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "agency" not in (a.get("class") or "").split():
            return
        name = (a.get("data-name") or "").strip()
        if not name:
            return
        specialties = (a.get("data-specialties") or "").strip()
        location = (a.get("data-location") or "").strip()
        desc = (a.get("data-description") or "").strip()
        # Fold specialties + location into the standard opportunity-lead shape so
        # downstream ingestion (insert_inbound_lead) needs no special-casing.
        need = (
            f"Agency — {specialties.replace(',', ', ')}"
            if specialties else "Creative agency (potential music buyer)"
        )
        description = " · ".join(p for p in (location, desc) if p)
        self.records.append({
            "company": name,
            "need": need[:200],
            "description": description[:1000],
            "url": (a.get("data-url") or "").strip() or None,
        })


def parse_agency_spotter_html(html: str) -> List[dict]:
    """Pure parser: one directory page's HTML → agency lead dicts. No network.

    Output records are the SAME shape every opportunity source emits
    (``company`` / ``need`` / ``description`` / ``url``)."""
    parser = _AgencyListingParser()
    try:
        parser.feed(html or "")
    except Exception:  # malformed markup — keep whatever parsed cleanly
        pass
    return parser.records


def _as_dedupe_key(rec: dict) -> str:
    return (rec.get("url") or rec.get("company") or "").strip().lower()


def fetch_agency_spotter(url: str) -> dict:
    """Walk the Agency Spotter directory from ``url``, page by page, accumulating
    every agency reachable within the page cap. Returns the standard
    ``{"records", "outcome", "detail"}`` contract, deduped within the run.

    Stops when a page yields no new agencies (the end of the directory) or the
    page cap is reached — the latter is reported in ``detail`` so a truncated
    sweep never masquerades as a complete one."""
    max_pages = _as_max_pages()
    delay = _as_page_delay()
    headers = {"User-Agent": _AS_UA}

    records: List[dict] = []
    seen: set = set()
    first_text, first_status, first_final = "", 0, url
    pages_walked = 0
    cap_hit = False

    page = 1
    while True:
        if page > max_pages:
            cap_hit = True
            break
        page_url = url if page == 1 else agency_spotter_page_url(url, page)
        text, status, final_url = _get_with_meta(page_url, headers)
        if page == 1:
            first_text, first_status, first_final = text, status, final_url
        pages_walked = page

        fresh = [r for r in parse_agency_spotter_html(text)
                 if _as_dedupe_key(r) and _as_dedupe_key(r) not in seen]
        if not fresh:
            break  # empty / repeated page → end of directory
        for r in fresh:
            seen.add(_as_dedupe_key(r))
        records.extend(fresh)

        page += 1
        if delay and page <= max_pages:
            time.sleep(delay)

    if records:
        outcome = "ok"
    else:
        # Nothing came back — diagnose the first page (login wall? block?).
        outcome = classify_outcome(first_text, first_status, first_final, 0)

    detail = f"Walked {pages_walked} page(s); {len(records)} agencies."
    if cap_hit:
        detail += (f" Stopped at the {max_pages}-page cap — more may remain "
                   f"(raise CHORDENTIAL_AGENCYSPOTTER_MAX_PAGES to go deeper).")
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
    if is_agency_spotter(target):
        return fetch_agency_spotter(target["url"])
    # Generic HTML floor — reuse discovery's parser (lazy import avoids a cycle).
    from . import discovery
    text, status, final_url = _get_with_meta(
        target["url"], {"User-Agent": "ChordentialDiscoveryBot/1.0 (+https://chordential.com)"}
    )
    records = discovery.parse_opportunity_html(text)
    outcome = classify_outcome(text, status, final_url, len(records))
    return {"records": records, "outcome": outcome, "detail": ""}
