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
import re
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
# Whether the agent runs at all is still the human gate (Approved target + scrape
# flag). The directory is public (no login), so the source is active rather than
# manual-assist — but bulk extraction is the operator's call against Agency
# Spotter's User Agreement; the page cap + delay keep the crawl courteous.
# --------------------------------------------------------------------------- #
_AS_UA = "ChordentialDiscoveryBot/1.0 (+https://chordential.com)"
_AS_DEFAULT_MAX_PAGES = 50
_AS_DEFAULT_DELAY = 1.0

# The "need" text the agency parser stamps on every record. Exposed as constants
# so downstream readers (e.g. the PDF exporter) can recognize an Agency Spotter
# lead from the persisted ``project_type`` alone — crawl leads don't store a
# source key — without the two sides drifting apart.
AGENCY_NEED_PREFIX = "Agency — "
AGENCY_NEED_DEFAULT = "Creative agency (potential music buyer)"


def is_agency_need(need: Optional[str]) -> bool:
    """True if a lead's ``project_type`` was minted by the Agency Spotter parser."""
    n = (need or "").strip()
    return n.startswith(AGENCY_NEED_PREFIX) or n == AGENCY_NEED_DEFAULT


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


# Agency Spotter is a Next.js app: the listing data is NOT in the visible HTML
# (data-* attributes) but embedded as React Server Component "flight" payloads in
# <script>self.__next_f.push([1,"…"])</script> chunks, which concatenate into one
# JSON-ish stream carrying ``{"agencies":[…],"currentPage":N,"totalPages":M,
# "count":K}``. We reconstruct that stream and read the agency objects + the page
# count straight from it — far more reliable than scraping rendered markup.
_FLIGHT_RE = re.compile(r'self\.__next_f\.push\(\[1,(".*?)\]\)</script>', re.S)
_AS_BASE = "https://www.agencyspotter.com"


def _flight_text(html: str) -> str:
    """Concatenate every RSC flight chunk into one string. Each chunk is a JSON
    string literal, so ``json.loads`` un-escapes it back to raw flight text."""
    parts: List[str] = []
    for m in _FLIGHT_RE.finditer(html or ""):
        try:
            parts.append(json.loads(m.group(1)))
        except Exception:
            continue
    return "".join(parts)


def _match_bracket(text: str, start: int) -> int:
    """Index just past the ``]`` matching the ``[`` at ``text[start]`` (string- and
    escape-aware). Returns -1 if unbalanced."""
    depth = 0
    in_str = esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _agency_record(a: dict) -> Optional[dict]:
    """Map one Agency Spotter agency object onto the standard opportunity-lead
    shape (``company`` / ``need`` / ``description`` / ``url``). Returns None for
    a nameless row."""
    name = (a.get("name") or "").strip()
    if not name:
        return None
    services = [s for s in (a.get("services") or []) if isinstance(s, str)]
    need = AGENCY_NEED_PREFIX + ", ".join(services) if services else AGENCY_NEED_DEFAULT
    loc = ", ".join(p for p in (
        (a.get("city") or "").strip(), (a.get("state") or "").strip(),
        (a.get("country") or "").strip()) if p)
    website = (a.get("url") or "").strip()
    slug = (a.get("slug") or "").strip()
    profile = f"{_AS_BASE}/{slug}" if slug else (website or None)
    # client_list can be a flight reference ("$1e") for very long lists — skip those.
    clients = a.get("client_list")
    clients = clients.replace("\n", ", ").strip() if isinstance(clients, str) and not clients.startswith("$") else ""
    bmin, bmid = a.get("budget_min"), a.get("budget_mid")
    bits = []
    if loc:
        bits.append(loc)
    if a.get("size"):
        bits.append(f"{a['size']} people")
    if a.get("avg_rating") and a.get("review_count"):
        bits.append(f"{a['avg_rating']}★ ({a['review_count']} reviews)")
    try:
        if bmin or bmid:
            bits.append(f"typical ${int(float(bmin or bmid)):,}–${int(float(bmid or bmin)):,}")
    except (TypeError, ValueError):
        pass
    if website:
        bits.append(website)
    if clients:
        bits.append("clients: " + clients[:200])
    return {
        "company": name,
        "need": need[:200],
        "description": " · ".join(bits)[:1000],
        "url": profile,
    }


def parse_agency_spotter_page(html: str) -> dict:
    """Pure parser: one directory/category page's HTML → ``{"records": [...],
    "current_page", "total_pages", "count"}``. No network. ``records`` are the
    standard opportunity-lead shape; the page counts drive pagination."""
    out = {"records": [], "current_page": None, "total_pages": None, "count": None}
    text = _flight_text(html)
    key = '"agencies":['
    idx = text.find(key)
    if idx == -1:
        return out
    arr_start = idx + len(key) - 1            # points at '['
    arr_end = _match_bracket(text, arr_start)
    if arr_end == -1:
        return out
    try:
        agencies = json.loads(text[arr_start:arr_end])
    except Exception:
        return out
    out["records"] = [r for r in (_agency_record(a) for a in agencies if isinstance(a, dict)) if r]
    tail = text[arr_end:arr_end + 300]        # "...],"currentPage":1,"totalPages":21,"count":602..."
    for field, dest in (("currentPage", "current_page"), ("totalPages", "total_pages"), ("count", "count")):
        m = re.search(rf'"{field}":(\d+)', tail)
        if m:
            out[dest] = int(m.group(1))
    return out


def parse_agency_spotter(html: str) -> List[dict]:
    """Convenience: just the lead records from one page (see parse_agency_spotter_page)."""
    return parse_agency_spotter_page(html)["records"]


def _as_dedupe_key(rec: dict) -> str:
    return (rec.get("url") or rec.get("company") or "").strip().lower()


def fetch_agency_spotter(url: str) -> dict:
    """Walk an Agency Spotter directory/category from ``url`` page by page,
    accumulating every agency. Uses the page's own ``totalPages`` to stop exactly
    at the end (or the configurable page cap, whichever comes first). Returns the
    standard ``{"records", "outcome", "detail"}`` contract, deduped within the run.

    A page cap that truncates the walk — and the total it stopped short of — is
    reported in ``detail`` so a partial sweep never masquerades as a complete one."""
    max_pages = _as_max_pages()
    delay = _as_page_delay()
    headers = {"User-Agent": _AS_UA}

    records: List[dict] = []
    seen: set = set()
    first_text, first_status, first_final = "", 0, url
    pages_walked = 0
    total_pages = count = None
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

        parsed = parse_agency_spotter_page(text)
        if total_pages is None:
            total_pages, count = parsed["total_pages"], parsed["count"]

        fresh = [r for r in parsed["records"]
                 if _as_dedupe_key(r) and _as_dedupe_key(r) not in seen]
        if not fresh:
            break  # empty / repeated page → end of directory
        for r in fresh:
            seen.add(_as_dedupe_key(r))
        records.extend(fresh)

        if total_pages and page >= total_pages:
            break  # walked the whole directory
        page += 1
        if delay and page <= max_pages and (not total_pages or page <= total_pages):
            time.sleep(delay)

    if cap_hit and total_pages and total_pages > max_pages:
        pass  # cap_hit already set
    if records:
        outcome = "ok"
    else:
        outcome = classify_outcome(first_text, first_status, first_final, 0)

    total_str = f" of {total_pages}" if total_pages else ""
    count_str = f" of {count}" if count else ""
    detail = f"Walked {pages_walked}{total_str} page(s); {len(records)}{count_str} agencies."
    if cap_hit:
        detail += (f" Stopped at the {max_pages}-page cap — more remain "
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
