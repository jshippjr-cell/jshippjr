"""The resumable directory-crawl engine shared by every agency-directory agent.

Exercises the cross-cutting guarantees with an in-memory fake page source (no
network, no site knowledge): run-until-complete, dedup, resume-after-interrupt,
progress, stop-at-total-pages — plus the agencies/crawl_state DB helpers and the
six registered directory sources.
"""

import importlib

import pytest

from chordential_oia.web import db as dbm
from chordential_oia.web import directory_crawl as dc
from chordential_oia.web import discovery_sources as catalog
from chordential_oia.web.directory_crawl import AgencyRecord, PageResult


def _conn(tmp_path):
    conn = dbm.connect(str(tmp_path / "agencies.db"))
    dbm.init_db(conn)
    return conn


def _A(name, host=None, **kw):
    return AgencyRecord(company=name, website=f"https://www.{host or name.lower()}.com", **kw)


def _source(pages, total=None, fail_on=None):
    """Fake page source. ``fail_on`` raises once on that page (simulates an
    interruption) and succeeds on the next visit."""
    fired = set()

    def src(page):
        if fail_on and page == fail_on and page not in fired:
            fired.add(page)
            raise RuntimeError("simulated crash")
        return PageResult(records=pages.get(page, []), total_pages=total)
    return src


# --------------------------------------------------------------------------- #
# AgencyRecord + DB helpers
# --------------------------------------------------------------------------- #
def test_dedup_key_prefers_website_host():
    assert AgencyRecord("X", website="https://www.Foo.com/about").dedup_key() == "foo.com"
    assert AgencyRecord("X", website="http://bar.io").dedup_key() == "bar.io"
    assert AgencyRecord("No Site", location="NYC").dedup_key() == "no site|nyc"


def test_upsert_agency_inserts_then_updates(tmp_path):
    conn = _conn(tmp_path)
    rec = _A("Aurora", employees="11-50").to_db()
    assert dbm.upsert_agency(conn, "adforum", rec) is True       # new
    rec["employees"] = "51-200"
    assert dbm.upsert_agency(conn, "adforum", rec) is False      # same key → update
    assert dbm.count_agencies(conn, "adforum") == 1
    assert dbm.list_agencies(conn, "adforum")[0]["employees"] == "51-200"


# --------------------------------------------------------------------------- #
# Engine guarantees
# --------------------------------------------------------------------------- #
def test_runs_until_complete(tmp_path):
    conn = _conn(tmp_path)
    src = _source({1: [_A("Alpha"), _A("Beta")], 2: [_A("Gamma")]})  # page 3 empty → done
    summary = dc.run_crawl(conn, "adforum", src)
    assert summary["outcome"] == "complete"
    assert summary["records_new"] == 3 and summary["duplicates"] == 0
    assert dbm.count_agencies(conn, "adforum") == 3
    assert dbm.get_crawl_state(conn, "adforum")["status"] == "complete"


def test_handles_duplicates(tmp_path):
    conn = _conn(tmp_path)
    src = _source({1: [_A("Alpha"), _A("Beta")], 2: [_A("Gamma"), _A("Alpha")]}, total=2)
    summary = dc.run_crawl(conn, "adforum", src)
    assert summary["records_seen"] == 4 and summary["records_new"] == 3
    assert summary["duplicates"] == 1
    assert dbm.count_agencies(conn, "adforum") == 3              # Alpha stored once


def test_stops_at_reported_total_pages(tmp_path):
    conn = _conn(tmp_path)
    src = _source({1: [_A("A")], 2: [_A("B")], 3: [_A("C")]}, total=2)  # page 3 never visited
    summary = dc.run_crawl(conn, "adforum", src)
    assert summary["outcome"] == "complete" and summary["pages_done"] == 2
    assert dbm.count_agencies(conn, "adforum") == 2


def test_resumes_after_interruption(tmp_path):
    conn = _conn(tmp_path)
    pages = {1: [_A("A"), _A("B")], 2: [_A("C"), _A("D")], 3: [_A("E")]}
    src = _source(pages, fail_on=3)

    first = dc.run_crawl(conn, "adforum", src)
    assert first["outcome"] == "error"
    assert dbm.get_crawl_state(conn, "adforum")["next_page"] == 3   # checkpoint at the crash
    assert dbm.count_agencies(conn, "adforum") == 4                 # pages 1–2 persisted

    second = dc.run_crawl(conn, "adforum", src)                     # resume — no reset
    assert second["outcome"] == "complete"
    assert dbm.count_agencies(conn, "adforum") == 5                 # E added, nothing doubled
    assert dbm.get_crawl_state(conn, "adforum")["status"] == "complete"


def test_progress_is_reported(tmp_path):
    conn = _conn(tmp_path)
    seen = []
    src = _source({1: [_A("A")], 2: [_A("B")], 3: [_A("C")]})
    dc.run_crawl(conn, "adforum", src, on_progress=seen.append)
    assert [p["page"] for p in seen] == [1, 2, 3]
    assert seen[-1]["records_new"] == 3
    assert dbm.get_crawl_state(conn, "adforum")["records_new"] == 3


def test_page_cap_backstops_a_runaway(tmp_path):
    conn = _conn(tmp_path)
    src = _source({p: [_A(f"A{p}")] for p in range(1, 100)})        # never empties on its own
    summary = dc.run_crawl(conn, "adforum", src, max_pages=3)
    assert summary["outcome"] == "capped" and summary["pages_done"] == 3


def test_reset_restarts_from_page_one(tmp_path):
    conn = _conn(tmp_path)
    src = _source({1: [_A("A")]})
    dc.run_crawl(conn, "adforum", src)
    dc.run_crawl(conn, "adforum", src, reset=True)                  # fresh sweep, deduped
    assert dbm.count_agencies(conn, "adforum") == 1
    assert dbm.get_crawl_state(conn, "adforum")["pages_done"] == 1


# --------------------------------------------------------------------------- #
# The six registered directory agents
# --------------------------------------------------------------------------- #
def test_six_directory_sources_registered():
    public = ["adforum", "canneslions", "awwwards", "designrush", "thedrum"]
    for key in public:
        s = catalog.get_site(key)
        assert s is not None and s.kind == "opportunity"
        assert s.login_gated is False           # public directories → engine-crawled

    aaaa = catalog.get_site("aaaa_directory")
    assert aaaa is not None and aaaa.login_gated is True   # member/login → manual-assist
