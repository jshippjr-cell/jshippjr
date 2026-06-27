"""Resumable directory-crawl engine shared by every agency-directory agent
(AdForum, Cannes Lions, 4A's, Awwwards, DesignRush, The Drum, …).

Each agent is responsible for its own *search* — it supplies a ``page_source``
callable that knows how to fetch + parse one page of its directory. This engine
owns everything the agents have in common, exactly as requested:

  * visit every page          — walks pages until the source says it's done
  * extract the six fields    — Company / Website / Employees / Location /
                                Description / Industries (see AgencyRecord)
  * store in the database      — db.upsert_agency
  * handle duplicates          — collapsed on (source, dedup_key); a re-run
                                 updates rather than duplicates
  * resume if interrupted      — the checkpoint (crawl_state.next_page) is
                                 committed after every page, so re-invoking
                                 continues from where it stopped
  * show progress              — an on_progress callback + the persisted
                                 crawl_state row (pages_done / total_pages /
                                 records_new)
  * run until complete         — loops to the end (or a safety page cap)

The engine is pure orchestration with no site knowledge and no direct network,
so it is unit-tested with an in-memory fake page source.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit

from . import db


@dataclass
class AgencyRecord:
    """One agency, normalized to the six requested fields (+ its profile URL)."""
    company: str
    website: str = ""
    employees: str = ""
    location: str = ""
    description: str = ""
    industries: str = ""          # comma-joined
    source_url: str = ""

    def dedup_key(self) -> str:
        """Stable identity for de-duplication: the website host if we have one
        (the most reliable signal an agency is the same across pages), else the
        company name + location."""
        host = urlsplit(self.website.strip()).netloc.lower() if self.website else ""
        host = host[4:] if host.startswith("www.") else host
        if host:
            return host
        return f"{self.company.strip().lower()}|{self.location.strip().lower()}"

    def to_db(self) -> Dict:
        return {
            "dedup_key": self.dedup_key(),
            "company": self.company.strip(),
            "website": self.website.strip(),
            "employees": self.employees.strip(),
            "location": self.location.strip(),
            "description": self.description.strip(),
            "industries": self.industries.strip(),
            "source_url": self.source_url.strip(),
        }


@dataclass
class PageResult:
    """What a ``page_source`` returns for one page."""
    records: List[AgencyRecord] = field(default_factory=list)
    total_pages: Optional[int] = None     # if the site reports it, we stop exactly there
    ok: bool = True                       # False → fetch/parse failed (stop, keep checkpoint)
    detail: str = ""


# A page source is: given a 1-based page number, return a PageResult.
PageSource = Callable[[int], PageResult]
# Progress sink: given the live crawl_state-ish dict, surface it (log/print/UI).
Progress = Callable[[Dict], None]


def run_crawl(
    conn,
    source_key: str,
    page_source: PageSource,
    *,
    max_pages: int = 1000,
    delay: float = 0.0,
    reset: bool = False,
    on_progress: Optional[Progress] = None,
) -> Dict:
    """Crawl one directory to completion (or resume an interrupted one).

    Returns a summary dict. Safe to call repeatedly: with ``reset=False`` it
    picks up from the persisted checkpoint and de-dupes, so re-running after an
    interruption neither restarts nor double-counts.
    """
    if reset:
        db.reset_crawl_state(conn, source_key)
        conn.commit()

    state = db.get_crawl_state(conn, source_key)
    start_page = (state["next_page"] if state and state["next_page"] else 1)
    pages_done = (state["pages_done"] if state else 0) or 0
    new_total = (state["records_new"] if state else 0) or 0
    seen_total = (state["records_seen"] if state else 0) or 0
    total_pages = (state["total_pages"] if state else None)

    db.save_crawl_state(conn, source_key, status="running")
    conn.commit()

    page = start_page
    outcome = "complete"
    while True:
        if page > max_pages:
            outcome = "capped"
            break
        try:
            res = page_source(page)
        except Exception as e:                      # interruption mid-page
            db.save_crawl_state(conn, source_key, status="error",
                                next_page=page, detail=f"page {page}: {e}")
            conn.commit()
            outcome = "error"
            break

        if not res.ok:
            db.save_crawl_state(conn, source_key, status="error",
                                next_page=page, detail=res.detail or "fetch failed")
            conn.commit()
            outcome = "error"
            break

        if not res.records:                          # end of the directory
            break

        new_here = 0
        for rec in res.records:
            if db.upsert_agency(conn, source_key, rec.to_db()):
                new_here += 1
        pages_done += 1
        new_total += new_here
        seen_total += len(res.records)
        if res.total_pages:
            total_pages = res.total_pages

        # Checkpoint BEFORE moving on, and commit — this is what makes the crawl
        # resumable: if the process dies now, next run starts at page+1.
        db.save_crawl_state(conn, source_key, status="running", next_page=page + 1,
                            pages_done=pages_done, records_new=new_total,
                            records_seen=seen_total, total_pages=total_pages,
                            detail=f"page {page}: +{new_here} new")
        conn.commit()

        if on_progress:
            on_progress({
                "source": source_key, "page": page, "total_pages": total_pages,
                "pages_done": pages_done, "records_new": new_total,
                "records_seen": seen_total,
            })

        if total_pages and page >= total_pages:      # walked the whole directory
            break
        page += 1
        if delay:
            time.sleep(delay)

    if outcome == "complete":
        db.save_crawl_state(conn, source_key, status="complete", detail="done")
        conn.commit()

    return {
        "source": source_key, "outcome": outcome,
        "pages_done": pages_done, "total_pages": total_pages,
        "records_new": new_total, "records_seen": seen_total,
        "duplicates": seen_total - new_total,
    }
