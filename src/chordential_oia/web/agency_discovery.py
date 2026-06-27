"""Agency Discovery Agent — a manually-run, paginating directory crawler.

Objective (the spec this module implements):

    Search Clutch. Start on page 1. Extract Company, Website, City, Employees,
    Services, Clutch URL. Go to next page. Continue. If a company already
    exists, skip it. Stop only when there are no more pages. Save everything to
    the database.

It is **run by hand** (no scheduler) while the pipeline is being validated, and
it is built to be observable and restartable:

- **Progress + ETA.** Each page logs ``page X of Y`` with an estimated time to
  completion (when the directory advertises a page total).
- **Counters.** Total parsed, unique new, duplicates skipped, and failed pages
  are tracked and reported.
- **Detailed logging.** Every step emits a line to the ``chordential.agency_discovery``
  logger *and* is captured on the report for the console / JSON export.
- **Resume.** Progress is checkpointed to ``agency_runs`` after every successful
  page; an interrupted run resumes from the last good page.
- **Retry with backoff.** A failed page is retried with exponential backoff
  (2s, 4s, 8s …) before it counts as failed.
- **Verify before import.** A run can be a *dry run* that writes the discovered
  agencies to JSON for human verification; :func:`import_from_json` then loads a
  verified file into the database.

House rules preserved: the network is double-gated by ``CHORDENTIAL_ENABLE_SCRAPE``
(inert in the sandbox / CI), parsing is a pure function unit-tested against
fixtures, the fetch fails soft, and discovered agencies land as ``New`` for a
human to keep or dismiss — the machine proposes, Jon disposes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional

from ..talent_sources.scraped import _fetch_url, scrape_enabled
from . import db

logger = logging.getLogger("chordential.agency_discovery")

#: The directory the agent searches. Overridable for tests / other directories.
DEFAULT_BASE_URL = "https://clutch.co/agencies"

#: Safety stop so a malformed "next page forever" link can't loop unbounded.
#: Far above any real directory depth; the true stop is "no more pages".
MAX_PAGES = 500

#: Retry policy for a failing page fetch (attempts incl. the first; backoff base).
RETRY_ATTEMPTS = 4
BACKOFF_BASE = 2.0  # delays after failed attempts: 2s, 4s, 8s …


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
    """Extract agency records (and pagination hints) from a documented listing::

        <li class="provider" data-company="Northwind Studio"
            data-website="https://northwind.example"
            data-city="Austin, TX" data-employees="50-249"
            data-services="Branding, Video Production"
            data-clutch-url="https://clutch.co/profile/northwind"></li>

    Pagination hints it understands (any that appear):
      * an element carrying ``data-total-pages="12"`` (or ``data-total-results``),
      * numbered page controls ``<a class="page" data-page="N">`` (max wins),
      * a ``next`` control (``class="next"`` or ``rel="next"``).

    Only ``provider`` elements become records, so page chrome is ignored. A record
    needs at least a company name to count.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: List[dict] = []
        self.has_next: bool = False
        self.total_pages: Optional[int] = None
        self.total_results: Optional[int] = None
        self._max_page_link: int = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        rel = (a.get("rel") or "").split()

        if "next" in classes or "next" in rel or a.get("data-page-next"):
            self.has_next = True

        tp = a.get("data-total-pages")
        if tp and tp.strip().isdigit():
            self.total_pages = int(tp.strip())
        tr = a.get("data-total-results")
        if tr and tr.strip().isdigit():
            self.total_results = int(tr.strip())

        # Numbered page links: remember the highest as a total-pages fallback.
        if "page" in classes:
            dp = a.get("data-page") or ""
            if dp.strip().isdigit():
                self._max_page_link = max(self._max_page_link, int(dp.strip()))

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

    def resolved_total_pages(self) -> Optional[int]:
        if self.total_pages:
            return self.total_pages
        if self._max_page_link:
            return self._max_page_link
        return None


def _parse(html: str) -> _AgencyListingParser:
    parser = _AgencyListingParser()
    try:
        parser.feed(html or "")
    except Exception:  # malformed markup — keep whatever parsed cleanly
        pass
    return parser


def parse_clutch_html(html: str) -> List[dict]:
    """Pure parser: structured directory HTML → agency-record dicts. No network."""
    return _parse(html).records


def has_next_page(html: str) -> bool:
    """Pure: does this page advertise a next page (a ``next`` pagination control)?"""
    return _parse(html).has_next


def parse_total_pages(html: str) -> Optional[int]:
    """Pure: the directory's total page count if it advertises one (via
    ``data-total-pages`` or numbered page links), else None."""
    return _parse(html).resolved_total_pages()


# --------------------------------------------------------------------------- #
# Network fetch with retry + exponential backoff (isolated, gated)
# --------------------------------------------------------------------------- #
def _fetch_with_retry(
    url: str,
    *,
    attempts: int,
    backoff_base: float,
    sleep: Callable[[float], None],
    on_log: Callable[[str], None],
) -> Optional[str]:
    """Fetch a page, retrying transient failures with exponential backoff. Returns
    the HTML, or None once all attempts are exhausted (fail soft). ``sleep`` is
    injected so tests don't actually wait."""
    last_err: Optional[Exception] = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return _fetch_url(url)
        except Exception as exc:  # network hiccup, timeout, transient 5xx, …
            last_err = exc
            if attempt < attempts:
                delay = backoff_base ** attempt
                on_log(
                    f"fetch failed (attempt {attempt}/{attempts}) for {url}: "
                    f"{exc!r} — retrying in {delay:.0f}s"
                )
                sleep(delay)
            else:
                on_log(
                    f"fetch failed (attempt {attempt}/{attempts}) for {url}: "
                    f"{exc!r} — giving up"
                )
    return None


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@dataclass
class DiscoveryReport:
    """Everything one run did — counters, progress, timing, log, and records."""
    run_id: Optional[int] = None
    dry_run: bool = False
    pages_scanned: int = 0
    last_page: int = 0
    total_pages: Optional[int] = None
    found: int = 0              # records parsed across all pages
    new_count: int = 0         # unique agencies not already stored
    duplicate_count: int = 0   # records skipped because the company already exists
    imported_count: int = 0    # agencies actually written to the DB (0 on a dry run)
    failed_pages: List[int] = field(default_factory=list)
    stopped_reason: str = ""   # no_more_pages | empty_page | scrape_disabled |
    #                            fetch_failed | max_pages
    elapsed_seconds: float = 0.0
    eta_seconds: Optional[float] = None
    export_path: Optional[str] = None
    log: List[str] = field(default_factory=list)
    records: List[dict] = field(default_factory=list)

    @property
    def resumed_incomplete(self) -> bool:
        """True if the run stopped without reaching the end (so it's resumable)."""
        return self.stopped_reason in ("fetch_failed",)

    def as_dict(self) -> Dict[str, object]:
        return {
            "run_id": self.run_id, "dry_run": self.dry_run,
            "pages_scanned": self.pages_scanned, "last_page": self.last_page,
            "total_pages": self.total_pages, "found": self.found,
            "new_count": self.new_count, "duplicate_count": self.duplicate_count,
            "imported_count": self.imported_count,
            "failed_pages": list(self.failed_pages),
            "stopped_reason": self.stopped_reason,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "eta_seconds": self.eta_seconds, "export_path": self.export_path,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Export / import (verify a JSON file before it touches the database)
# --------------------------------------------------------------------------- #
def export_dir() -> str:
    """Where JSON exports are written. ``CHORDENTIAL_EXPORT_DIR`` overrides a
    module-relative default; created on demand."""
    d = os.environ.get("CHORDENTIAL_EXPORT_DIR") or os.path.join(
        os.path.dirname(__file__), "exports"
    )
    os.makedirs(d, exist_ok=True)
    return d


def write_export(report: DiscoveryReport, source: str, path: Optional[str] = None) -> str:
    """Write the discovered records to a JSON file for human verification before
    import. Returns the path written."""
    if path is None:
        stamp = _now_iso().replace(":", "").replace("-", "")[:15]
        rid = report.run_id if report.run_id is not None else "x"
        path = os.path.join(export_dir(), f"agencies-{source}-run{rid}-{stamp}.json")
    payload = {
        "exported_at": _now_iso(),
        "source": source,
        "summary": report.as_dict(),
        "log": report.log,
        "agencies": report.records,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return path


def _load_export_records(path: Optional[str]) -> List[dict]:
    """Best-effort read of a prior export's records (for a cumulative resume).
    Returns [] if the file is missing/unreadable."""
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            return list(json.load(fh).get("agencies") or [])
    except Exception:
        return []


def import_from_json(conn, path: str, source: Optional[str] = None) -> Dict[str, int]:
    """Load a verified export file into the database. Inserts new agencies, skips
    ones already stored (the same dedupe rule), and returns a summary
    ``{found, imported, skipped}``. Records flagged ``status == 'duplicate'`` in
    the export are still re-checked against the live DB, not trusted blindly."""
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    agencies = payload.get("agencies") or []
    src = source or payload.get("source") or "clutch"
    imported = skipped = 0
    for rec in agencies:
        company = (rec.get("company") or "").strip()
        if not company:
            continue
        new_id = db.insert_agency(
            conn,
            company=company, website=rec.get("website") or "",
            city=rec.get("city") or "", employees=rec.get("employees") or "",
            services=rec.get("services") or "", clutch_url=rec.get("clutch_url") or "",
            source=src,
        )
        if new_id is None:
            skipped += 1
        else:
            imported += 1
    logger.info("import_from_json %s: imported=%d skipped=%d", path, imported, skipped)
    return {"found": len(agencies), "imported": imported, "skipped": skipped}


# --------------------------------------------------------------------------- #
# The agent: paginate → extract → dedupe → (save | preview) — observable + resumable
# --------------------------------------------------------------------------- #
def run(
    conn,
    *,
    base_url: str = DEFAULT_BASE_URL,
    source: str = "clutch",
    start_page: int = 1,
    max_pages: int = MAX_PAGES,
    dry_run: bool = False,
    resume: bool = False,
    export: bool = True,
    retry_attempts: int = RETRY_ATTEMPTS,
    backoff_base: float = BACKOFF_BASE,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> DiscoveryReport:
    """Run the discovery loop and return a :class:`DiscoveryReport`.

    Start on ``start_page`` (or, with ``resume=True``, just after the last good
    page of the most recent interrupted run); fetch each page with retry/backoff;
    parse; save new agencies and skip existing ones; advance while a next page is
    advertised; stop at the last page. Checkpoints to ``agency_runs`` after every
    page so an interruption is resumable. ``dry_run=True`` previews without
    writing agencies (for JSON verification); ``export`` writes the JSON file.

    Network-gated — with the scrape flag off, returns immediately with
    ``stopped_reason='scrape_disabled'`` (no run row, nothing fetched).
    """
    report = DiscoveryReport(dry_run=dry_run)

    def emit(msg: str) -> None:
        line = f"{_now_iso()} {msg}"
        report.log.append(line)
        logger.info(msg)

    if not scrape_enabled():
        report.stopped_reason = "scrape_disabled"
        emit("scraping disabled (CHORDENTIAL_ENABLE_SCRAPE off) — nothing fetched")
        return report

    # Resume bookkeeping: continue an interrupted run, or open a fresh one.
    run_id: int
    seen: set = set()  # company keys seen in this run (within-batch dedupe)
    resumed = db.latest_resumable_agency_run(conn, source) if resume else None
    if resumed is not None:
        run_id = resumed["id"]
        start_page = (resumed["last_page"] or 0) + 1
        report.pages_scanned = resumed["pages_scanned"] or 0
        report.found = resumed["found"] or 0
        report.new_count = resumed["new_count"] or 0
        report.duplicate_count = resumed["duplicate_count"] or 0
        report.imported_count = resumed["imported_count"] or 0
        report.failed_pages = list(json.loads(resumed["failed_pages"] or "[]"))
        report.total_pages = resumed["total_pages"]
        # Carry the earlier pages' records forward so the new export stays
        # cumulative (and so a preview's in-batch dedupe still sees them).
        for rec in _load_export_records(resumed["export_path"]):
            report.records.append(rec)
            seen.add(db._agency_key(rec.get("company") or ""))
        db.checkpoint_agency_run(conn, run_id, status="running")
        emit(f"resuming run #{run_id} from page {start_page} "
             f"({len(report.records)} records carried forward)")
    else:
        run_id = db.start_agency_run(conn, source, base_url, max(1, start_page), dry_run)
        emit(f"started run #{run_id} ({'preview' if dry_run else 'live import'}) "
             f"at page {max(1, start_page)}")
    report.run_id = run_id

    page = max(1, start_page)
    pages_left = max_pages
    started = clock()

    while pages_left > 0:
        url = page_url(page, base_url)
        html = _fetch_with_retry(
            url, attempts=retry_attempts, backoff_base=backoff_base,
            sleep=sleep, on_log=emit,
        )
        if html is None:
            # A page we couldn't read after all retries — record it, stop, and
            # leave the run resumable from the last good page.
            report.failed_pages.append(page)
            report.stopped_reason = "fetch_failed"
            emit(f"page {page} failed after {retry_attempts} attempts — "
                 f"run is resumable from here")
            db.finish_agency_run(
                conn, run_id, "interrupted",
                failed_pages=json.dumps(report.failed_pages),
                stopped_reason=report.stopped_reason,
                elapsed_seconds=clock() - started,
            )
            break

        report.pages_scanned += 1
        report.last_page = page
        pages_left -= 1

        parsed = _parse(html)
        if report.total_pages is None:
            report.total_pages = parsed.resolved_total_pages()
        records = parsed.records

        if not records:
            report.stopped_reason = "empty_page"
            emit(f"page {page} had no listings — treating as the end of the directory")
            db.finish_agency_run(
                conn, run_id, "completed",
                last_page=page, pages_scanned=report.pages_scanned,
                total_pages=report.total_pages, stopped_reason=report.stopped_reason,
                elapsed_seconds=clock() - started,
            )
            break

        for rec in records:
            report.found += 1
            key = db._agency_key(rec["company"])
            is_dup = key in seen or db.agency_exists(conn, rec["company"])
            rec_out = dict(rec, page=page, status="duplicate" if is_dup else "new")
            report.records.append(rec_out)
            if is_dup:
                report.duplicate_count += 1
                continue
            seen.add(key)
            report.new_count += 1
            if not dry_run:
                new_id = db.insert_agency(
                    conn,
                    company=rec["company"], website=rec["website"], city=rec["city"],
                    employees=rec["employees"], services=rec["services"],
                    clutch_url=rec["clutch_url"], source=source,
                )
                if new_id is not None:
                    report.imported_count += 1

        # Progress + ETA after each completed page.
        elapsed = clock() - started
        report.elapsed_seconds = elapsed
        total = report.total_pages
        of_y = f" of {total}" if total else ""
        if total and report.pages_scanned:
            per_page = elapsed / report.pages_scanned
            remaining = max(0, total - page)
            report.eta_seconds = round(per_page * remaining, 1)
            eta_txt = f" · ETA ~{report.eta_seconds:.0f}s"
        else:
            eta_txt = ""
        emit(f"page {page}{of_y} done — {len(records)} parsed, "
             f"{report.new_count} new / {report.duplicate_count} dup so far{eta_txt}")

        db.checkpoint_agency_run(
            conn, run_id, last_page=page, total_pages=report.total_pages,
            pages_scanned=report.pages_scanned, found=report.found,
            new_count=report.new_count, duplicate_count=report.duplicate_count,
            imported_count=report.imported_count,
            failed_pages=json.dumps(report.failed_pages),
            elapsed_seconds=elapsed,
        )

        if not parsed.has_next:
            report.stopped_reason = "no_more_pages"
            emit(f"page {page} is the last page — stopping")
            db.finish_agency_run(
                conn, run_id, "completed",
                stopped_reason=report.stopped_reason, elapsed_seconds=clock() - started,
            )
            break
        page += 1
    else:
        report.stopped_reason = "max_pages"
        emit(f"hit the {max_pages}-page safety cap — stopping")
        db.finish_agency_run(
            conn, run_id, "completed",
            stopped_reason=report.stopped_reason, elapsed_seconds=clock() - started,
        )

    report.elapsed_seconds = clock() - started

    if export and report.records:
        try:
            report.export_path = write_export(report, source)
            db.checkpoint_agency_run(conn, run_id, export_path=report.export_path)
            emit(f"exported {len(report.records)} records → {report.export_path}")
        except Exception as exc:  # export is best-effort — never fail the run
            emit(f"export failed: {exc!r}")

    return report
