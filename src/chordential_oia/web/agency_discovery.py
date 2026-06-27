"""Agency Discovery Agent — a paginating crawler over a B2B agency directory.

Objective (the spec this module implements):

    Search Clutch. Start on page 1. Extract Company, Website, City, Employees,
    Services, Clutch URL. Go to next page. Continue. If a company already
    exists, skip it. Stop only when there are no more pages. Save everything to
    the database.

How it honors the house rules:

- **Machine proposes, Jon disposes.** Discovered agencies land as ``New`` rows in
  the ``agencies`` review queue. The agent never qualifies, contacts, or promotes
  them — a human still presses the decision buttons.
- **Network is double-gated.** Nothing is fetched unless ``CHORDENTIAL_ENABLE_SCRAPE``
  is on, so the agent is inert in the egress-blocked sandbox and in CI. It is run
  on demand from the Agencies console (or wherever a caller drives :func:`run`).
- **Pure parsing.** :func:`parse_clutch_html` is a pure function (HTML → records,
  no network) unit-tested against fixture HTML — the same trick the talent/opp
  parsers use. The directory's real markup is mapped onto a documented,
  structured listing contract; the network fetch is isolated and fails soft.

The loop is the heart of it: fetch page N → parse → for each record, skip if the
company already exists else save → if the page advertises a next page, go to
N+1 → repeat → stop when there is no next page (or a page yields nothing).
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, List, Optional

from ..talent_sources.scraped import _fetch_url, scrape_enabled
from . import db

#: The directory the agent searches. Overridable for tests / other directories.
DEFAULT_BASE_URL = "https://clutch.co/agencies"

#: Safety stop so a malformed "next page forever" link can't loop without bound.
#: Far above any real directory depth; the true stop is "no more pages".
MAX_PAGES = 500


# --------------------------------------------------------------------------- #
# Page URL construction (pure)
# --------------------------------------------------------------------------- #
def page_url(page: int, base_url: str = DEFAULT_BASE_URL) -> str:
    """The directory URL for a 1-based page number. Page 1 is the bare directory
    (no query); later pages carry ``?page=N``. Pure — no network."""
    if page <= 1:
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}page={page}"


# --------------------------------------------------------------------------- #
# Listing parser (pure) — parallel to scraped.parse_talent_html
# --------------------------------------------------------------------------- #
class _AgencyListingParser(HTMLParser):
    """Extract agency records from a documented listing structure::

        <li class="provider" data-company="Northwind Studio"
            data-website="https://northwind.example"
            data-city="Austin, TX" data-employees="50-249"
            data-services="Branding, Video Production, Advertising"
            data-clutch-url="https://clutch.co/profile/northwind-studio"></li>

    Only elements whose class includes ``provider`` are read, so page chrome is
    ignored. A record needs at least a company name to count.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: List[dict] = []
        self.has_next: bool = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        # A "next page" control anywhere on the page → another page exists.
        rel = (a.get("rel") or "")
        if "next" in classes or "next" in rel.split() or a.get("data-page-next"):
            self.has_next = True
        if "provider" not in classes:
            return
        company = (a.get("data-company") or "").strip()
        if not company:
            return
        self.records.append({
            "company": company,
            "website": (a.get("data-website") or "").strip(),
            "city": (a.get("data-city") or "").strip(),
            "employees": (a.get("data-employees") or "").strip(),
            "services": (a.get("data-services") or "").strip(),
            "clutch_url": (a.get("data-clutch-url") or "").strip(),
        })


def parse_clutch_html(html: str) -> List[dict]:
    """Pure parser: structured directory HTML → agency-record dicts. No network."""
    return _parse(html).records


def has_next_page(html: str) -> bool:
    """Pure: does this page advertise a next page (a ``next`` pagination control)?"""
    return _parse(html).has_next


def _parse(html: str) -> _AgencyListingParser:
    parser = _AgencyListingParser()
    try:
        parser.feed(html or "")
    except Exception:  # malformed markup — keep whatever parsed cleanly
        pass
    return parser


# --------------------------------------------------------------------------- #
# Network fetch (isolated, gated) — only reached when the scrape flag is on
# --------------------------------------------------------------------------- #
def _fetch_page(url: str) -> Optional[str]:
    """Fetch one directory page's HTML, or None on any failure (fail soft)."""
    try:
        return _fetch_url(url)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# The agent: paginate → extract → dedupe → save
# --------------------------------------------------------------------------- #
@dataclass
class DiscoveryReport:
    """What one run did, for the console + the caller."""
    pages_scanned: int = 0
    found: int = 0           # records parsed across all pages
    saved: int = 0           # new agencies inserted
    skipped: int = 0         # records skipped because the company already existed
    stopped_reason: str = "" # no_more_pages | empty_page | scrape_disabled | fetch_failed | max_pages
    last_page: int = 0

    def as_dict(self) -> Dict[str, object]:
        return {
            "pages_scanned": self.pages_scanned, "found": self.found,
            "saved": self.saved, "skipped": self.skipped,
            "stopped_reason": self.stopped_reason, "last_page": self.last_page,
        }


def run(
    conn,
    *,
    base_url: str = DEFAULT_BASE_URL,
    source: str = "clutch",
    start_page: int = 1,
    max_pages: int = MAX_PAGES,
) -> DiscoveryReport:
    """Run the discovery loop and return a :class:`DiscoveryReport`.

    Start on ``start_page``; fetch and parse each page; save new agencies and skip
    ones already stored; advance to the next page while the current page
    advertises one; stop when there are no more pages. Network-gated — with the
    scrape flag off, returns immediately with ``stopped_reason='scrape_disabled'``
    (nothing fetched, nothing saved).
    """
    report = DiscoveryReport()
    if not scrape_enabled():
        report.stopped_reason = "scrape_disabled"
        return report

    page = max(1, start_page)
    pages_left = max_pages
    while pages_left > 0:
        html = _fetch_page(page_url(page, base_url))
        if html is None:
            report.stopped_reason = "fetch_failed"
            break

        report.pages_scanned += 1
        report.last_page = page
        pages_left -= 1

        parsed = _parse(html)
        records = parsed.records
        if not records:
            # A page with no listings is the natural end of the directory.
            report.stopped_reason = "empty_page"
            break

        for rec in records:
            report.found += 1
            new_id = db.insert_agency(
                conn,
                company=rec["company"], website=rec["website"], city=rec["city"],
                employees=rec["employees"], services=rec["services"],
                clutch_url=rec["clutch_url"], source=source,
            )
            if new_id is None:
                report.skipped += 1   # company already exists → skip
            else:
                report.saved += 1

        if not parsed.has_next:
            report.stopped_reason = "no_more_pages"
            break
        page += 1
    else:
        # Loop exhausted the page budget without a natural stop.
        report.stopped_reason = "max_pages"

    return report
