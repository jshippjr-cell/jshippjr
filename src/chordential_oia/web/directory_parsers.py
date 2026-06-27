"""Per-site parsers that turn one directory page into AgencyRecords for the
resumable crawl engine (directory_crawl.run_crawl).

Each site gets: a pure ``parse_*`` function (HTML string -> records, no network,
unit-tested against real markup) and a ``make_*_source`` factory that wraps fetch
+ parse into the ``page_source`` the engine drives. Network is gated by
CHORDENTIAL_ENABLE_SCRAPE, exactly like the other crawlers, so tests and the
sandbox never hit the wire.

Fitted so far: AdForum (real markup). The other directories slot in here the same
way once a sample page is available.
"""

from __future__ import annotations

import html as _html
import math
import re
import urllib.parse
import urllib.request
from typing import List, Optional

from ..talent_sources.scraped import scrape_enabled
from .directory_crawl import AgencyRecord, PageResult

_UA = "ChordentialDirectoryBot/1.0 (+https://chordential.com)"
_PER_PAGE_DEFAULT = 25


def _text(fragment: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", fragment or ""))).strip()


# --------------------------------------------------------------------------- #
# AdForum  (server-rendered HTML; one .b-search_result__item per agency)
# --------------------------------------------------------------------------- #
_AF_BASE = "https://www.adforum.com"
_AF_ITEM = 'class="b-search_result__item"'
_AF_TITLE = re.compile(
    r'href="(/agency/[^"]+)"\s+class="b-search_result__link--title"[^>]*>(.*?)</a>', re.S)
_AF_SUB = re.compile(r'class="b-search_result__link--subtitle"[^>]*>(.*?)</a>', re.S)
_AF_COMP = re.compile(r'class="b-search_result__link--competency"[^>]*>(.*?)</a>', re.S)
_AF_COUNT = re.compile(r'b-search_result__title">\s*([\d,]+)\s*Results', re.S)


def _af_location(raw: str) -> str:
    loc = _text(raw).replace(" ,", ",").strip().strip(",").strip()
    return loc


def _af_industries(raw: str) -> str:
    parts = [p.strip() for p in _text(raw).split(",")]
    parts = [p for p in parts if p and p.lower() != "more..."]
    return ", ".join(parts)


def parse_adforum_listing(html: str) -> List[AgencyRecord]:
    """One AdForum agency-search results page -> AgencyRecords.

    The listing carries company, location, industries (AdForum "competencies")
    and the profile URL. Website / employees / description live on each agency's
    profile page (a per-agency sub-fetch — see make_adforum_source docs), so they
    are left blank here.
    """
    out: List[AgencyRecord] = []
    for block in (html or "").split(_AF_ITEM)[1:]:
        m = _AF_TITLE.search(block)
        if not m:
            continue
        name = _text(m.group(2))
        if not name:
            continue
        sub = _AF_SUB.search(block)
        comp = _AF_COMP.search(block)
        out.append(AgencyRecord(
            company=name,
            location=_af_location(sub.group(1)) if sub else "",
            industries=_af_industries(comp.group(1)) if comp else "",
            source_url=urllib.parse.urljoin(_AF_BASE, m.group(1)),
        ))
    return out


def adforum_total_results(html: str) -> Optional[int]:
    m = _AF_COUNT.search(html or "")
    return int(m.group(1).replace(",", "")) if m else None


# An agency's profile page carries website + description (the listing omits them).
# AdForum does NOT publish an employee count anywhere on the profile, so that
# field stays blank for this source — we don't invent it.
_AF_SITE = re.compile(r'href="([^"]+)"[^>]*class="contact__link--site"', re.S)
_AF_DESC = re.compile(r'class="agency-description__text">(.*?)</div>', re.S)


def parse_adforum_profile(html: str) -> dict:
    """One AdForum agency profile page -> {website, description}. Pure, no network."""
    site = ""
    m = _AF_SITE.search(html or "")
    if m:
        site = _html.unescape(m.group(1)).strip()
    descs = [_text(b) for b in _AF_DESC.findall(html or "")]
    description = " ".join(d for d in descs if d)[:1000]
    return {"website": site, "description": description}


def make_adforum_enricher():
    """Return an ``enrich(record)`` for the engine that fetches each agency's
    AdForum profile (record.source_url) and fills website + description. Gated by
    the scrape flag; on failure it returns the record unchanged (listing fields
    survive). Employees aren't on AdForum, so that field is left blank."""
    def enrich(rec):
        if not scrape_enabled() or not rec.source_url:
            return rec
        text, ok = _fetch(rec.source_url)
        if not ok:
            return rec
        prof = parse_adforum_profile(text)
        if prof["website"]:
            rec.website = prof["website"]
        if prof["description"]:
            rec.description = prof["description"]
        return rec
    return enrich


def _fetch(url: str, timeout: float = 15.0):
    """GET (text, ok). Only reached when the scrape flag is on."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace"), True
    except Exception:
        return "", False


def make_adforum_source(base_url: str, per_page: int = _PER_PAGE_DEFAULT):
    """Return a ``page_source(page)`` for the engine that fetches + parses one
    AdForum results page. ``base_url`` is the filtered search (e.g. US agencies:
    ``/agency/search?location=country_strkey:COU149``); pagination appends
    ``&page=N`` (AdForum's "See more" loader). Total pages are derived from the
    reported result count so the crawl knows when it's done.

    Network is gated: with scraping off (sandbox/CI) it returns ok=False so the
    engine records an error rather than pretending. Fitting the per-agency
    profile sub-fetch (website/employees/description) is a follow-up once a
    profile-page sample is available.
    """
    def page_source(page: int) -> PageResult:
        if not scrape_enabled():
            return PageResult(ok=False, detail="scraping disabled")
        sep = "&" if "?" in base_url else "?"
        url = base_url if page == 1 else f"{base_url}{sep}page={page}"
        text, ok = _fetch(url)
        if not ok:
            return PageResult(ok=False, detail="fetch failed")
        records = parse_adforum_listing(text)
        total = adforum_total_results(text)
        total_pages = math.ceil(total / per_page) if total else None
        return PageResult(records=records, total_pages=total_pages, ok=True)
    return page_source


# Registry: source_key -> (factory, default base URL). A runner does
#   run_crawl(conn, key, make(base)) to crawl that directory to completion.
SOURCE_FACTORIES = {
    "adforum": (make_adforum_source,
                "https://www.adforum.com/agency/search?location=country_strkey:COU149"),
}
