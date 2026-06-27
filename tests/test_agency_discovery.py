"""Agency Discovery Agent — a manually-run, paginating directory crawler.

Core contract: start on page 1, extract the six fields, skip companies already
stored, advance through pages, and stop only when there are no more pages. Plus
the strengthened behaviours: progress/ETA + counters, detailed logging, resume
from the last good page, retry with exponential backoff, and JSON export →
verify → import. Network is env-gated and never touched in tests except via a
monkeypatched fetch.
"""

import importlib
import json

import pytest

from chordential_oia.web import agency_discovery as agent
from chordential_oia.talent_sources import scraped


# A documented listing page: providers + pagination hints.
def _page(providers, has_next=True, total_pages=None):
    rows = "\n".join(
        f'''<li class="provider" data-company="{p['company']}"
              data-website="{p.get('website','')}"
              data-city="{p.get('city','')}"
              data-employees="{p.get('employees','')}"
              data-services="{p.get('services','')}"
              data-clutch-url="{p.get('clutch_url','')}"></li>'''
        for p in providers
    )
    hint = f'<nav class="pagination" data-total-pages="{total_pages}"></nav>' if total_pages else ""
    nxt = '<a class="next" rel="next" href="?page=2">Next</a>' if has_next else ""
    return f'<ul class="providers">{rows}</ul>{hint}{nxt}'


PAGE_1 = _page([
    {"company": "Northwind Studio", "website": "https://northwind.example",
     "city": "Austin, TX", "employees": "50-249",
     "services": "Branding, Video Production",
     "clutch_url": "https://clutch.co/profile/northwind"},
    {"company": "Vance Athletic Agency", "website": "https://vance.example",
     "city": "Denver, CO", "employees": "10-49", "services": "Advertising",
     "clutch_url": "https://clutch.co/profile/vance"},
], has_next=True, total_pages=2)

PAGE_2 = _page([
    {"company": "Aurora Collective", "city": "Remote", "employees": "2-9",
     "services": "Sound Design", "clutch_url": "https://clutch.co/profile/aurora"},
    # A repeat of a page-1 company — must be skipped, not stored twice.
    {"company": "Northwind Studio, Inc.", "website": "https://northwind.example"},
], has_next=False, total_pages=2)


@pytest.fixture()
def db_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("CHORDENTIAL_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.delenv("CHORDENTIAL_ENABLE_SCRAPE", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)
    conn.close()
    return db_mod


def _serve(monkeypatch, pages, fail_urls=None):
    """Monkeypatch the network fetch to serve fixture pages, optionally raising on
    specific URLs to exercise retry/backoff/failure paths."""
    fail_urls = fail_urls or set()

    def fake_fetch(url, timeout=10.0):
        if url in fail_urls:
            raise OSError("simulated network failure")
        return pages[url]

    monkeypatch.setattr(agent, "_fetch_url", fake_fetch)


# --- Pure URL construction ------------------------------------------------- #
def test_page_url_starts_on_page_one_then_paginates():
    assert agent.page_url(1) == agent.DEFAULT_BASE_URL
    assert agent.page_url(2) == agent.DEFAULT_BASE_URL + "?page=2"
    assert agent.page_url(7) == agent.DEFAULT_BASE_URL + "?page=7"
    assert agent.page_url(3, "https://x.example/dir?sort=az").endswith("&page=3")


# --- Pure parser (the requested parser unit tests) ------------------------- #
def test_parse_extracts_all_six_fields():
    recs = agent.parse_clutch_html(PAGE_1)
    assert len(recs) == 2
    first = recs[0]
    assert first["company"] == "Northwind Studio"
    assert first["website"] == "https://northwind.example"
    assert first["city"] == "Austin, TX"
    assert first["employees"] == "50-249"
    assert "Branding" in first["services"]
    assert first["clutch_url"] == "https://clutch.co/profile/northwind"


def test_parser_ignores_non_provider_chrome():
    html = '<div class="header">Clutch</div><li class="provider" data-company="Solo"></li>'
    recs = agent.parse_clutch_html(html)
    assert [r["company"] for r in recs] == ["Solo"]


def test_parser_skips_records_without_a_company():
    html = '<li class="provider" data-city="Nowhere"></li><li class="provider" data-company="Real Co"></li>'
    assert [r["company"] for r in agent.parse_clutch_html(html)] == ["Real Co"]


def test_parser_tolerates_malformed_markup():
    # Unclosed tags / stray attributes must not raise — fail soft.
    recs = agent.parse_clutch_html('<ul><li class="provider" data-company="Half')
    assert isinstance(recs, list)


def test_has_next_page_detects_the_control():
    assert agent.has_next_page(PAGE_1) is True
    assert agent.has_next_page(PAGE_2) is False


def test_parse_total_pages_from_hint_and_links():
    assert agent.parse_total_pages(PAGE_1) == 2
    # Numbered page links are a fallback when there's no explicit total.
    links = '<a class="page" data-page="1"></a><a class="page" data-page="9"></a>'
    assert agent.parse_total_pages(f'<li class="provider" data-company="X"></li>{links}') == 9
    assert agent.parse_total_pages('<li class="provider" data-company="X"></li>') is None


# --- The gate: no network without the flag --------------------------------- #
def test_run_is_a_noop_when_scraping_disabled(db_mod):
    conn = db_mod.connect()
    try:
        report = agent.run(conn)
    finally:
        conn.close()
    assert report.stopped_reason == "scrape_disabled"
    assert report.imported_count == 0 and report.pages_scanned == 0
    assert report.run_id is None       # no run row created for a no-op


# --- The loop: paginate, dedupe, stop, with counters + progress ------------ #
def test_run_paginates_dedupes_and_stops_at_last_page(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    _serve(monkeypatch, {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2})

    conn = db_mod.connect()
    try:
        report = agent.run(conn)
        rows = conn.execute("SELECT company FROM agencies ORDER BY id").fetchall()
    finally:
        conn.close()

    assert report.pages_scanned == 2
    assert report.total_pages == 2
    assert report.stopped_reason == "no_more_pages"
    assert report.found == 4
    assert report.new_count == 3
    assert report.imported_count == 3
    assert report.duplicate_count == 1
    assert report.eta_seconds is not None      # ETA computed once total is known
    assert {r["company"] for r in rows} == {
        "Northwind Studio", "Vance Athletic Agency", "Aurora Collective"}


def test_detailed_log_records_progress_per_page(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    _serve(monkeypatch, {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2})
    conn = db_mod.connect()
    try:
        report = agent.run(conn)
    finally:
        conn.close()
    blob = "\n".join(report.log)
    assert "page 1 of 2 done" in blob
    assert "page 2 of 2 done" in blob
    assert "last page" in blob


def test_rerun_skips_everything_already_stored(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    _serve(monkeypatch, {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2})
    conn = db_mod.connect()
    try:
        agent.run(conn)
        second = agent.run(conn)
        total = conn.execute("SELECT COUNT(*) c FROM agencies").fetchone()["c"]
    finally:
        conn.close()
    assert second.imported_count == 0
    assert second.new_count == 0
    assert second.duplicate_count == second.found
    assert total == 3


def test_run_stops_on_empty_page(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    empty = '<ul class="providers"></ul>'
    _serve(monkeypatch, {agent.page_url(1): PAGE_1, agent.page_url(2): empty})
    conn = db_mod.connect()
    try:
        report = agent.run(conn)
    finally:
        conn.close()
    assert report.stopped_reason == "empty_page"
    assert report.pages_scanned == 2
    assert report.imported_count == 2


# --- Dry run + JSON export/import (verify before import) ------------------- #
def test_dry_run_exports_json_without_touching_the_db(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    _serve(monkeypatch, {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2})
    conn = db_mod.connect()
    try:
        report = agent.run(conn, dry_run=True)
        in_db = conn.execute("SELECT COUNT(*) c FROM agencies").fetchone()["c"]
    finally:
        conn.close()
    assert in_db == 0                          # nothing imported on a preview
    assert report.new_count == 3               # but it knows what's new
    assert report.imported_count == 0
    assert report.export_path and report.export_path.endswith(".json")
    payload = json.loads(open(report.export_path, encoding="utf-8").read())
    assert len(payload["agencies"]) == 4
    assert {a["company"] for a in payload["agencies"] if a["status"] == "new"} == {
        "Northwind Studio", "Vance Athletic Agency", "Aurora Collective"}
    assert payload["log"]                       # the detailed log is exported too


def test_import_from_json_loads_a_verified_export(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    _serve(monkeypatch, {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2})
    conn = db_mod.connect()
    try:
        report = agent.run(conn, dry_run=True)
        result = agent.import_from_json(conn, report.export_path)
        # A second import is fully deduped.
        again = agent.import_from_json(conn, report.export_path)
        names = {r["company"] for r in conn.execute("SELECT company FROM agencies")}
    finally:
        conn.close()
    assert result["imported"] == 3
    assert again["imported"] == 0
    assert names == {"Northwind Studio", "Vance Athletic Agency", "Aurora Collective"}


# --- Retry with exponential backoff ---------------------------------------- #
def test_retry_uses_exponential_backoff_then_succeeds(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    delays = []
    calls = {"n": 0}

    def flaky(url, timeout=10.0):
        calls["n"] += 1
        if calls["n"] < 3:                      # fail twice, then succeed
            raise OSError("transient")
        return _page([{"company": "Solo Co"}], has_next=False)

    monkeypatch.setattr(agent, "_fetch_url", flaky)
    conn = db_mod.connect()
    try:
        report = agent.run(conn, sleep=lambda d: delays.append(d))
    finally:
        conn.close()
    assert delays == [2.0, 4.0]                 # backoff: 2s then 4s
    assert report.imported_count == 1
    assert report.failed_pages == []


def test_page_failing_all_retries_is_recorded_and_resumable(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    # Page 1 fine; page 2 always fails → run stops, interrupted, resumable.
    _serve(monkeypatch, {agent.page_url(1): PAGE_1}, fail_urls={agent.page_url(2)})
    conn = db_mod.connect()
    try:
        report = agent.run(conn, sleep=lambda d: None)
        run_row = db_mod.get_agency_run(conn, report.run_id)
    finally:
        conn.close()
    assert report.stopped_reason == "fetch_failed"
    assert report.failed_pages == [2]
    assert report.last_page == 1               # last good page
    assert run_row["status"] == "interrupted"


# --- Resume from the last successful page ---------------------------------- #
def test_resume_continues_from_last_good_page(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    # First run: page 2 is down → stops after page 1 (interrupted).
    _serve(monkeypatch, {agent.page_url(1): PAGE_1}, fail_urls={agent.page_url(2)})
    conn = db_mod.connect()
    try:
        first = agent.run(conn, sleep=lambda d: None)
        assert first.stopped_reason == "fetch_failed"
        first_count = conn.execute("SELECT COUNT(*) c FROM agencies").fetchone()["c"]
    finally:
        conn.close()
    assert first_count == 2                      # only page 1's agencies stored

    # Page 2 recovers; resume picks up at page 2 and finishes.
    _serve(monkeypatch, {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2})
    conn = db_mod.connect()
    try:
        resumed = agent.run(conn, resume=True, sleep=lambda d: None)
        names = {r["company"] for r in conn.execute("SELECT company FROM agencies")}
        n_runs = conn.execute("SELECT COUNT(*) c FROM agency_runs").fetchone()["c"]
    finally:
        conn.close()
    assert resumed.run_id == first.run_id        # same run continued
    assert resumed.stopped_reason == "no_more_pages"
    assert resumed.last_page == 2
    # Accumulated counters carry across the resume; no duplicate Northwind.
    assert names == {"Northwind Studio", "Vance Athletic Agency", "Aurora Collective"}
    assert n_runs == 1


def test_dry_run_resume_export_is_cumulative(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    # Interrupt a preview after page 1, then resume — the final export must hold
    # both pages so the eventual import isn't missing the head.
    _serve(monkeypatch, {agent.page_url(1): PAGE_1}, fail_urls={agent.page_url(2)})
    conn = db_mod.connect()
    try:
        first = agent.run(conn, dry_run=True, sleep=lambda d: None)
        assert first.stopped_reason == "fetch_failed"
    finally:
        conn.close()

    _serve(monkeypatch, {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2})
    conn = db_mod.connect()
    try:
        resumed = agent.run(conn, dry_run=True, resume=True, sleep=lambda d: None)
        imported = agent.import_from_json(conn, resumed.export_path)
    finally:
        conn.close()
    payload = json.loads(open(resumed.export_path, encoding="utf-8").read())
    assert len(payload["agencies"]) == 4        # page 1 carried forward + page 2
    assert imported["imported"] == 3            # all uniques across both pages


def test_resume_with_no_interrupted_run_starts_fresh(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    _serve(monkeypatch, {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2})
    conn = db_mod.connect()
    try:
        report = agent.run(conn, resume=True)   # nothing to resume → page 1
    finally:
        conn.close()
    assert report.last_page == 2
    assert report.stopped_reason == "no_more_pages"


# --- DB layer: dedupe key + status lifecycle ------------------------------- #
def test_agency_dedupe_normalizes_company_name(db_mod):
    conn = db_mod.connect()
    try:
        first = db_mod.insert_agency(conn, "Acme, Inc.", city="NYC")
        dupe = db_mod.insert_agency(conn, "acme inc")
        assert first is not None
        assert dupe is None
        assert db_mod.agency_exists(conn, "  ACME   Inc  ") is True
    finally:
        conn.close()


def test_update_agency_status_rejects_unknown(db_mod):
    conn = db_mod.connect()
    try:
        aid = db_mod.insert_agency(conn, "Keepers Co")
        db_mod.update_agency_status(conn, aid, "Reviewed")
        row = conn.execute("SELECT status FROM agencies WHERE id=?", (aid,)).fetchone()
        assert row["status"] == "Reviewed"
        with pytest.raises(ValueError):
            db_mod.update_agency_status(conn, aid, "Bogus")
    finally:
        conn.close()


def test_checkpoint_rejects_unknown_field(db_mod):
    conn = db_mod.connect()
    try:
        rid = db_mod.start_agency_run(conn, "clutch", agent.DEFAULT_BASE_URL, 1, True)
        with pytest.raises(ValueError):
            db_mod.checkpoint_agency_run(conn, rid, bogus_col=1)
    finally:
        conn.close()


# --- Web surface: preview → verify → import, resume, decisions -------------- #
@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.delenv("CHORDENTIAL_ENABLE_SCRAPE", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod, app_mod


def test_agencies_console_renders_and_run_is_gated(client):
    c, _, _ = client
    page = c.get("/agencies")
    assert page.status_code == 200
    assert "Agency Discovery" in page.text
    # Running with scraping OFF is a safe no-op (creates no run row).
    r = c.post("/agencies/run", follow_redirects=True)
    assert r.status_code == 200


def test_web_preview_then_import_then_decide(client, monkeypatch):
    c, db_mod, app_mod = client
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    pages = {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2}
    monkeypatch.setattr(app_mod.agency_discovery, "_fetch_url",
                        lambda url, timeout=10.0: pages[url])

    # Preview run → JSON export, nothing imported yet.
    c.post("/agencies/run", follow_redirects=True)
    conn = db_mod.connect()
    try:
        assert conn.execute("SELECT COUNT(*) c FROM agencies").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM agency_runs").fetchone()["c"] == 1
    finally:
        conn.close()

    # The export is downloadable for verification.
    dl = c.get("/agencies/export.json")
    assert dl.status_code == 200
    assert "Northwind Studio" in dl.text

    # Import the verified export → agencies land in the DB.
    r = c.post("/agencies/import", follow_redirects=True)
    assert "Imported" in r.text or "imported=" in str(r.url)
    conn = db_mod.connect()
    try:
        row = conn.execute(
            "SELECT id FROM agencies WHERE company='Aurora Collective'").fetchone()
    finally:
        conn.close()
    assert row is not None
    c.post(f"/agencies/{row['id']}/status", data={"status": "Dismissed"})
    conn = db_mod.connect()
    try:
        status = conn.execute(
            "SELECT status FROM agencies WHERE id=?", (row["id"],)).fetchone()["status"]
    finally:
        conn.close()
    assert status == "Dismissed"
