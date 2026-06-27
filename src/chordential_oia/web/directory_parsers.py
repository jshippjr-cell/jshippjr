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
            return PageResult(ok=False, detail="fetch failed")
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
            return PageResult(ok=False, detail="fetch failed")
        rec = parse_aaaa_profile(text)
        return PageResult(records=[rec] if rec else [], total_pages=len(urls), ok=True)
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
}
