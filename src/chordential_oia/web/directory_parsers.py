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
import json
import math
import re
import urllib.error
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


# Last fetch failure reason, surfaced in the crawl status so a blocked directory
# reads "fetch failed (HTTP 403)" instead of a silent "fetch failed".
_LAST_FETCH_ERROR = ""


def last_fetch_error() -> str:
    return _LAST_FETCH_ERROR


def _fetch(url: str, timeout: float = 15.0):
    """GET (text, ok). Only reached when the scrape flag is on. Records why a
    fetch failed (HTTP code / unreachable reason) in _LAST_FETCH_ERROR."""
    global _LAST_FETCH_ERROR
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            charset = resp.headers.get_content_charset() or "utf-8"
            _LAST_FETCH_ERROR = ""
            return resp.read().decode(charset, errors="replace"), True
    except urllib.error.HTTPError as e:        # blocked / not found / rate-limited
        _LAST_FETCH_ERROR = f"HTTP {e.code}"
        return "", False
    except urllib.error.URLError as e:         # DNS / TLS / connection refused
        _LAST_FETCH_ERROR = f"unreachable: {e.reason}"
        return "", False
    except Exception as e:                      # timeout, decode, anything else
        _LAST_FETCH_ERROR = type(e).__name__
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
            return PageResult(ok=False, detail=f"fetch failed ({last_fetch_error()})")
        records = parse_adforum_listing(text)
        total = adforum_total_results(text)
        total_pages = math.ceil(total / per_page) if total else None
        return PageResult(records=records, total_pages=total_pages, ok=True)
    return page_source


# --------------------------------------------------------------------------- #
# DesignRush  (server-rendered HTML; one <article ... js-agency-item> per agency)
# --------------------------------------------------------------------------- #
# Unlike AdForum, DesignRush puts all six requested fields on the *listing* page
# (company, website, employees, location, description, services), so no per-agency
# profile sub-fetch is needed. Non-agency cards (help/trend/ad boxes) lack the
# data-agency-name attribute, so splitting on it skips them for free.
_DR_BASE = "https://www.designrush.com"
_DR_COUNT = re.compile(r'([\d,]+)\s*Companies', re.S)
_DR_PAGES = re.compile(r'id="paginator"[^>]*data-count="of\s*([\d,]+)"', re.S)
_DR_NAME_SPLIT = 'data-agency-name="'
_DR_REGION = re.compile(r'i-region[^"]*"[^>]*>(.*?)</div>', re.S)
_DR_EMPLOYEES = re.compile(r'i-employees[^"]*"[^>]*>(.*?)</div>', re.S)
_DR_DESC = re.compile(r'class="item-description"[^>]*>(.*?)</div>', re.S)
_DR_SERVICES_UL = re.compile(r'<ul[^>]*inner-tags--services[^>]*>(.*?)</ul>', re.S)
_DR_SERVICES_BOX = re.compile(r'class="item-services"[^>]*>(.*?)</div>', re.S)
_DR_LI = re.compile(r'<li[^>]*>(.*?)</li>', re.S)


def _dr_href_for_class(block: str, cls: str) -> str:
    """Find an element carrying ``cls`` and return its href, tolerating either
    attribute order (class-before-href or href-before-class)."""
    m = re.search(r'class="[^"]*' + cls + r'[^"]*"[^>]*href="([^"]+)"', block)
    if not m:
        m = re.search(r'href="([^"]+)"[^>]*class="[^"]*' + cls + r'[^"]*"', block)
    return _html.unescape(m.group(1)).strip() if m else ""


def _dr_clean_website(url: str) -> str:
    """Drop the utm tracking query DesignRush appends to outbound website links."""
    if not url:
        return ""
    p = urllib.parse.urlsplit(url)
    if not p.netloc:
        return url
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, "", "")).rstrip("/")


def _dr_services(block: str) -> str:
    m = _DR_SERVICES_UL.search(block) or _DR_SERVICES_BOX.search(block)
    if not m:
        return ""
    items = [_text(li) for li in _DR_LI.findall(m.group(1))]
    return ", ".join(s for s in items if s)


def parse_designrush_listing(html: str) -> List[AgencyRecord]:
    """One DesignRush agency-category page -> AgencyRecords (all six fields)."""
    out: List[AgencyRecord] = []
    for block in (html or "").split(_DR_NAME_SPLIT)[1:]:
        name = _text(block.split('"', 1)[0])
        if not name:
            continue
        region = _DR_REGION.search(block)
        emp = _DR_EMPLOYEES.search(block)
        desc = _DR_DESC.search(block)
        out.append(AgencyRecord(
            company=name,
            website=_dr_clean_website(_dr_href_for_class(block, "gtm-agency-website-link")),
            employees=_text(emp.group(1)) if emp else "",
            location=_text(region.group(1)) if region else "",
            description=(_text(desc.group(1))[:1000]) if desc else "",
            industries=_dr_services(block),
            source_url=urllib.parse.urljoin(
                _DR_BASE, _dr_href_for_class(block, "gtm-agency-profile-link")),
        ))
    return out


def designrush_total_results(html: str) -> Optional[int]:
    m = _DR_COUNT.search(html or "")
    return int(m.group(1).replace(",", "")) if m else None


def designrush_total_pages(html: str) -> Optional[int]:
    """DesignRush reports its last page directly (paginator data-count="of N")."""
    m = _DR_PAGES.search(html or "")
    return int(m.group(1).replace(",", "")) if m else None


def make_designrush_source(base_url: str, per_page: int = 50):
    """Return a ``page_source(page)`` for the engine. ``base_url`` is a category
    page (e.g. ``/agency/digital-marketing/us``); pagination appends ``?page=N``.
    Total pages come from the paginator when present, else from the result count.
    """
    def page_source(page: int) -> PageResult:
        if not scrape_enabled():
            return PageResult(ok=False, detail="scraping disabled")
        sep = "&" if "?" in base_url else "?"
        url = base_url if page == 1 else f"{base_url}{sep}page={page}"
        text, ok = _fetch(url)
        if not ok:
            return PageResult(ok=False, detail=f"fetch failed ({last_fetch_error()})")
        records = parse_designrush_listing(text)
        total_pages = designrush_total_pages(text)
        if total_pages is None:
            total = designrush_total_results(text)
            total_pages = math.ceil(total / per_page) if total else None
        return PageResult(records=records, total_pages=total_pages, ok=True)
    return page_source


# --------------------------------------------------------------------------- #
# 4A's  (American Association of Advertising Agencies)
# --------------------------------------------------------------------------- #
# Two surfaces, two stories:
#   * The agency *search* (my.aaaa.org "Community Hub") is a login-walled,
#     JavaScript-rendered Salesforce community — no agency data in the HTML, so
#     it can't be engine-enumerated. That stays manual-assist (login_gated).
#   * Each agency *profile* (www.aaaa.org/agency-profile/<sfid>/<slug>/) is a
#     plain server-rendered WordPress page that carries ALL six fields. The
#     parser below extracts them; the engine then crawls a SUPPLIED list of
#     profile URLs (operator pulls the list from the member directory — the
#     profiles are member/login-tagged content, so scraping them is the
#     operator's ToS call, same caveat as every other public directory here).
_AAAA_OGURL = re.compile(r'<meta\s+property="og:url"\s+content="([^"]+)"', re.S)
_AAAA_HEADER = re.compile(r'module full-width-drawer(.*?)<h2>\s*Overview\s*</h2>', re.S)
_AAAA_NAME = re.compile(r'<h1[^>]*>(.*?)</h1>', re.S)
_AAAA_SITE = re.compile(r'href="(https?://[^"]+)"', re.S)
_AAAA_OWNER = re.compile(r'Ownership:\s*([^<]+)', re.S)
_AAAA_SIZE = re.compile(r'Size:\s*([^<]+)', re.S)
_AAAA_SUMMARY = re.compile(r'<h3>\s*Company Summary\s*</h3>\s*<p>(.*?)</p>', re.S)
_AAAA_CONTACT = re.compile(r'<h3>\s*Contact\s*</h3>\s*<p>(.*?)</p>', re.S)
_AAAA_INDUSTRY = re.compile(r'<h2>\s*Industry Experience\s*</h2>\s*<p>(.*?)</p>', re.S)
_BR_SPLIT = re.compile(r'</?br\s*/?>', re.I)
_ZIP_TAIL = re.compile(r'\s+\d{5}(?:-\d{4})?$')


def _aaaa_location(contact_block: str) -> str:
    """The Contact <p> is address-line / city-state-zip / phone / fax. Take the
    city-state line and drop the trailing ZIP."""
    lines = [_text(p) for p in _BR_SPLIT.split(contact_block)]
    lines = [l for l in lines if l]
    if len(lines) < 2:
        return ""
    return _ZIP_TAIL.sub("", lines[1]).strip()


def parse_aaaa_profile(html: str) -> Optional[AgencyRecord]:
    """One 4A's agency-profile page -> AgencyRecord (all six fields). Pure, no
    network. Returns None if the page has no agency name (not a profile page)."""
    header_m = _AAAA_HEADER.search(html or "")
    header = header_m.group(1) if header_m else ""
    name_m = _AAAA_NAME.search(header)
    name = _text(name_m.group(1)) if name_m else ""
    if not name:
        return None

    site_m = _AAAA_SITE.search(header)
    size_m = _AAAA_SIZE.search(header)
    summary_m = _AAAA_SUMMARY.search(html or "")
    contact_m = _AAAA_CONTACT.search(html or "")
    industry_m = _AAAA_INDUSTRY.search(html or "")
    og_m = _AAAA_OGURL.search(html or "")

    industries = ""
    if industry_m:
        parts = [_text(p) for p in _BR_SPLIT.split(industry_m.group(1))]
        industries = ", ".join(p for p in parts if p)

    return AgencyRecord(
        company=name,
        website=_html.unescape(site_m.group(1)).strip() if site_m else "",
        employees=_text(size_m.group(1)) if size_m else "",
        location=_aaaa_location(contact_m.group(1)) if contact_m else "",
        description=(_text(summary_m.group(1))[:1000]) if summary_m else "",
        industries=industries,
        source_url=_html.unescape(og_m.group(1)).strip() if og_m else "",
    )


def make_aaaa_source(profile_urls):
    """Return a ``page_source(page)`` that walks a SUPPLIED list of 4A's profile
    URLs (one per page), so the resumable engine gives this source the same
    resume / dedup / progress as the others. The list is the operator's input
    (the 4A's search that would enumerate it is login/JS-walled)."""
    urls = list(profile_urls)

    def page_source(page: int) -> PageResult:
        if not scrape_enabled():
            return PageResult(ok=False, detail="scraping disabled")
        if page > len(urls):
            return PageResult(records=[], total_pages=len(urls), ok=True)
        text, ok = _fetch(urls[page - 1])
        if not ok:
            return PageResult(ok=False, detail=f"fetch failed ({last_fetch_error()})")
        rec = parse_aaaa_profile(text)
        return PageResult(records=[rec] if rec else [], total_pages=len(urls), ok=True)
    return page_source


# --------------------------------------------------------------------------- #
# Cannes Lions / lovethework.com  ("The Work" award archive; Next.js flight JSON)
# --------------------------------------------------------------------------- #
# lovethework is not a directory of agency profiles — it's the official archive of
# award-WINNING campaigns. The unit we want is the AGENCY credited on each winner,
# so a reach-out list of award-winning agencies falls out of "The Work". Honesty
# rule: an award credit states the agency name, the campaign, the brand, the
# sector and the award level — NOT website / employees / location / capabilities.
# We fill only what the source actually states and leave the rest blank.
#
# The winners page is server-rendered Next.js: the entry data rides in a
# self.__next_f.push([1,"<flight payload>"]) chunk. The payload is a JSON string;
# decoding it once yields a line whose "searchResults":{...,"documents":[...]} is
# itself valid JSON. Each document carries title + contributors + tags, plus an
# "enrichmentData" JSON string (brand/agency supportText, sector subText,
# mediaTag.awardLevel, slug). enrichmentData is occasionally a deferred React ref
# ("$3e") rather than inline JSON, so we fall back to contributors + tags.
_LTW_BASE = "https://www.lovethework.com/en/awards/winners-shortlists/cannes-lions/film"
_LTW_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', re.S)
_LTW_AWARDS = {
    "grandprix": "Grand Prix", "titanium": "Titanium", "gold": "Gold",
    "silver": "Silver", "bronze": "Bronze",
    "shortlist": "Shortlist", "shortlisted": "Shortlist",
}


def _ltw_award_label(raw: str) -> str:
    """Normalize an award level ('grandprix' / 'Grand Prix') to a display label."""
    s = (raw or "").strip()
    return _LTW_AWARDS.get(re.sub(r"[\s_]+", "", s).lower(), s.title() if s else "")


def _ltw_sector(raw: str) -> str:
    """A Lions category tag reads 'B01: Consumer Goods'; the enrichment subText is
    just 'Consumer Goods'. Strip any leading 'A06:'-style code either way."""
    return re.sub(r"^[A-Z]?\d+\s*:\s*", "", _text(raw)).strip()


def _ltw_search_results(html: str) -> dict:
    """Decode the flight chunk and return the searchResults dict (or {})."""
    for payload in _LTW_PUSH.findall(html):
        if "searchResults" not in payload:
            continue
        try:
            line = json.loads('"' + payload + '"')
        except Exception:
            continue
        k = line.find('"searchResults":')
        if k < 0:
            continue
        start = line.find("{", k)
        depth = 0
        for idx in range(start, len(line)):
            ch = line[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(line[start:idx + 1])
                    except Exception:
                        return {}
        break
    return {}


def _ltw_agencies(doc: dict, enrich: dict) -> List[str]:
    """The agencies credited on one entry. contributors (type=='Agency') is the
    normalized, authoritative list; if absent, fall back to the agency token of
    the 'BRAND, AGENCY' supportText (everything after the brand)."""
    names = [c.get("name", "").strip()
             for c in (doc.get("contributors") or [])
             if c.get("type") == "Agency" and c.get("name", "").strip()]
    if names:
        return names
    support = (enrich.get("supportText") or "").strip()
    if "," in support:
        agency = support.rsplit(",", 1)[1].strip()
        if agency:
            return [agency]
    return []


def lovethework_total_pages(html: str) -> Optional[int]:
    """Pages in this winners list, from the reported totalCount / pageSize."""
    res = _ltw_search_results(html)
    total = res.get("totalCount")
    size = res.get("pageSize") or 24
    return math.ceil(total / size) if total else None


def parse_lovethework_entries(html: str) -> List[AgencyRecord]:
    """One lovethework 'The Work' winners page -> one AgencyRecord per credited
    agency. Records carry no website / employees / location (the archive doesn't
    state them); the award level, campaign and brand go in the description and the
    sector in industries, so each agency is reachable in context. source_url is
    left blank on purpose: an agency that wins repeatedly should collapse to one
    row, and the engine's dedup falls back to the agency name when there's no URL."""
    docs = _ltw_search_results(html).get("documents") or []
    records: List[AgencyRecord] = []
    for doc in docs:
        raw = doc.get("enrichmentData")
        enrich: dict = {}
        if isinstance(raw, str) and raw.startswith("{"):
            try:
                enrich = json.loads(raw)
            except Exception:
                enrich = {}
        agencies = _ltw_agencies(doc, enrich)
        if not agencies:
            continue
        title = _text(doc.get("title") or "")
        support = (enrich.get("supportText") or "").strip()
        brand = support.rsplit(",", 1)[0].strip() if "," in support else support
        award = _ltw_award_label((enrich.get("mediaTag") or {}).get("awardLevel", ""))
        sector = _ltw_sector(enrich.get("subText") or "")
        for tag in (doc.get("tags") or []):          # deferred-enrichment fallback
            if not award and tag.get("level2") == "Award level":
                award = _ltw_award_label(tag.get("level3", ""))
            if not sector and tag.get("level1") == "Lions Award Category":
                sector = _ltw_sector(tag.get("level3", ""))
        desc = ("Cannes Lions " + award).strip() if award else "Cannes Lions winner"
        if title:
            desc += f": “{title}”"
        if brand:
            desc += f" for {brand}"
        for agency in agencies:
            records.append(AgencyRecord(
                company=_text(agency), industries=sector, description=desc))
    return records


def make_lovethework_source(base_url: str):
    """Return a ``page_source(page)`` that walks one lovethework winners list to
    the end. Pagination appends ``?page=N`` (the Next.js search convention) and
    the crawl stops at the reported total page count. Network is gated like the
    other sources: with scraping off it reports an error rather than pretending.

    ``base_url`` is one award category, e.g. Cannes Lions Film
    (``/en/awards/winners-shortlists/cannes-lions/film``); point it at any other
    category to harvest that list's winning agencies the same way."""
    def page_source(page: int) -> PageResult:
        if not scrape_enabled():
            return PageResult(ok=False, detail="scraping disabled")
        sep = "&" if "?" in base_url else "?"
        url = base_url if page == 1 else f"{base_url}{sep}page={page}"
        text, ok = _fetch(url)
        if not ok:
            return PageResult(ok=False, detail=f"fetch failed ({last_fetch_error()})")
        return PageResult(records=parse_lovethework_entries(text),
                          total_pages=lovethework_total_pages(text), ok=True)
    return page_source


# --------------------------------------------------------------------------- #
# Awwwards directory  (server-rendered HTML; one .card-directory per agency)
# --------------------------------------------------------------------------- #
# The directory listing carries company, website and location on the card, plus
# the agency's Awwwards trophy counts (HM / SOTD / SOTM / SOTY). Honesty rule:
# employees / description / industries are NOT on the listing, so they stay blank
# (the awards summary goes in description as the one extra fact the page states).
# The promoted ".card-directory-sp" cards at the top are duplicates of real grid
# entries, so we parse only the main ".card-directory" grid and skip them.
_AW_BASE = "https://www.awwwards.com"
_AW_CARD = '<div class="card-directory">'
_AW_NAME = re.compile(r'avatar-name__name">\s*<strong>(.*?)</strong>', re.S)
_AW_PROFILE = re.compile(r'class="avatar-name__link"\s+href="(/[^"]+)"', re.S)
_AW_LOC = re.compile(r'<strong>Location</strong></div>\s*<div>(.*?)</div>', re.S)
_AW_SITE = re.compile(r'<strong>Website</strong></div>\s*<div><a href="([^"]+)"', re.S)
_AW_SCORE = re.compile(
    r'box-score__top">\s*<strong>(.*?)</strong>\s*</div>\s*'
    r'<div class="box-score__bottom">\s*<strong>(.*?)</strong>', re.S)
_AW_COUNT = re.compile(r'<strong>([\d,]+)</strong>\s*professionals waiting', re.S)
_AW_LABELS = {
    "HM": "Honorable Mentions", "SOTD": "Sites of the Day",
    "SOTM": "Sites of the Month", "SOTY": "Sites of the Year",
}


def _aw_awards(block: str) -> str:
    """Summarize the card's trophy counts (skipping zeros) for the description."""
    bits = []
    for label, value in _AW_SCORE.findall(block):
        val = _text(value)
        if val and val != "0":
            bits.append(f"{val} {_AW_LABELS.get(_text(label), _text(label))}")
    return "Awwwards: " + ", ".join(bits) if bits else ""


def awwwards_total_results(html: str) -> Optional[int]:
    """The "N professionals waiting" count the directory header reports."""
    m = _AW_COUNT.search(html)
    return int(m.group(1).replace(",", "")) if m else None


def parse_awwwards_listing(html: str) -> List[AgencyRecord]:
    """One Awwwards /directory/ page -> AgencyRecords (one per .card-directory)."""
    records: List[AgencyRecord] = []
    for block in html.split(_AW_CARD)[1:]:
        name = _AW_NAME.search(block)
        if not name:
            continue
        prof = _AW_PROFILE.search(block)
        loc = _AW_LOC.search(block)
        site = _AW_SITE.search(block)
        records.append(AgencyRecord(
            company=_text(name.group(1)),
            website=_html.unescape(site.group(1)).strip() if site else "",
            location=_text(loc.group(1)) if loc else "",
            description=_aw_awards(block),
            source_url=(_AW_BASE + prof.group(1)) if prof else "",
        ))
    return records


def make_awwwards_source(base_url: str, per_page: int = 24):
    """Return a ``page_source(page)`` for the engine that fetches + parses one
    Awwwards directory page. Pagination appends ``?page=N``; total pages come
    from the reported professional count so the crawl knows when it's done."""
    def page_source(page: int) -> PageResult:
        if not scrape_enabled():
            return PageResult(ok=False, detail="scraping disabled")
        sep = "&" if "?" in base_url else "?"
        url = base_url if page == 1 else f"{base_url}{sep}page={page}"
        text, ok = _fetch(url)
        if not ok:
            return PageResult(ok=False, detail=f"fetch failed ({last_fetch_error()})")
        records = parse_awwwards_listing(text)
        total = awwwards_total_results(text)
        total_pages = math.ceil(total / per_page) if total else None
        return PageResult(records=records, total_pages=total_pages, ok=True)
    return page_source


# --------------------------------------------------------------------------- #
# The Drum  (server-rendered; the whole ranked list rides in one data attribute)
# --------------------------------------------------------------------------- #
# A Drum "Hotlist" page embeds its entire ranking as HTML-entity-encoded JSON in
# the <td-rankings-list :list-data="[...]"> attribute — no pagination, the full
# list is on the one page. Each entry carries companyName, a /profile/<slug> URL,
# location and a rich editorial blurb (plus yearFounded / topExecutive). Honesty
# rule: there's no outbound website or employee count, so those stay blank; the
# editorial becomes the description and the Drum profile URL the identity.
_TD_BASE = "https://www.thedrum.com"
_TD_LISTDATA = re.compile(r':list-data="([^"]*)"', re.S)


def parse_thedrum_list(html: str) -> List[AgencyRecord]:
    """One Drum ranked-list page -> AgencyRecords, from the embedded list-data."""
    m = _TD_LISTDATA.search(html)
    if not m:
        return []
    try:
        entries = json.loads(_html.unescape(m.group(1)))
    except Exception:
        return []
    records: List[AgencyRecord] = []
    for e in entries:
        name = _text(e.get("companyName") or "")
        if not name:
            continue
        url = (e.get("url") or "").strip()
        records.append(AgencyRecord(
            company=name,
            location=_text(e.get("location") or ""),
            description=_text(e.get("editorial") or ""),
            source_url=(_TD_BASE + url) if url.startswith("/") else url,
        ))
    return records


def make_thedrum_source(base_url: str):
    """Return a ``page_source(page)`` for a Drum Hotlist. The full ranking is on
    one page (embedded in the data attribute), so page 1 yields every agency and
    the crawl completes in a single fetch (total_pages = 1). Point ``base_url`` at
    any other Drum list (e.g. /b2b-agencies) to harvest that ranking the same way."""
    def page_source(page: int) -> PageResult:
        if not scrape_enabled():
            return PageResult(ok=False, detail="scraping disabled")
        if page > 1:
            return PageResult(records=[], total_pages=1, ok=True)
        text, ok = _fetch(base_url)
        if not ok:
            return PageResult(ok=False, detail=f"fetch failed ({last_fetch_error()})")
        return PageResult(records=parse_thedrum_list(text), total_pages=1, ok=True)
    return page_source


# Registry: source_key -> (factory, default base URL). A runner does
#   run_crawl(conn, key, make(base)) to crawl that directory to completion.
# (4A's is intentionally absent — its profiles crawl from a supplied URL list
# via make_aaaa_source, not a self-enumerating base URL.)
SOURCE_FACTORIES = {
    "adforum": (make_adforum_source,
                "https://www.adforum.com/agency/search?location=country_strkey:COU149"),
    "designrush": (make_designrush_source,
                   "https://www.designrush.com/agency/digital-marketing/us"),
    "canneslions": (make_lovethework_source, _LTW_BASE),
    "awwwards": (make_awwwards_source, "https://www.awwwards.com/directory/"),
    "thedrum": (make_thedrum_source, "https://www.thedrum.com/b2b-agencies"),
}


# --------------------------------------------------------------------------- #
# Paste-a-page ingest. Map a source key to the parser for its *listing* page so
# a pasted directory page can be turned into AgencyRecords and stored directly —
# the same workflow used to fit the parsers, now writing to the live database.
# (This is the reliable path: it never depends on the directory site being
# reachable, only on the page you paste.)
# --------------------------------------------------------------------------- #
LISTING_PARSERS = {
    "adforum": parse_adforum_listing,
    "designrush": parse_designrush_listing,
    "awwwards": parse_awwwards_listing,
    "canneslions": parse_lovethework_entries,
    "thedrum": parse_thedrum_list,
}

# (key, human label) for the ingest picker — listing parsers plus the 4A's
# single-profile case, in the order they're easiest to paste.
INGEST_SOURCES = [
    ("thedrum", "The Drum (ranked list)"),
    ("awwwards", "Awwwards directory"),
    ("designrush", "DesignRush directory"),
    ("adforum", "AdForum search results"),
    ("canneslions", "Cannes Lions / lovethework winners"),
    ("aaaa", "4A's agency profile (one page)"),
]


def parse_listing(source_key: str, html: str) -> List[AgencyRecord]:
    """Parse one pasted page for ``source_key`` into AgencyRecords. 4A's pastes
    are a single agency-profile page; the rest are multi-agency listing pages.
    Unknown source or unparseable page -> []."""
    if source_key == "aaaa":
        rec = parse_aaaa_profile(html or "")
        return [rec] if rec else []
    fn = LISTING_PARSERS.get(source_key)
    return fn(html or "") if fn else []
