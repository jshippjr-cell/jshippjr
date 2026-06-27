"""Agency Discovery Agent — a paginating directory crawler.

Core contract: start on page 1, extract the six fields, skip companies already
stored, advance through pages, and stop only when there are no more pages.
Network is env-gated and never touched in tests except via a monkeypatched fetch.
"""

import importlib

import pytest

from chordential_oia.web import agency_discovery as agent
from chordential_oia.talent_sources import scraped


# A documented listing page: three providers + a "next page" control.
def _page(providers, has_next=True):
    rows = "\n".join(
        f'''<li class="provider" data-company="{p['company']}"
              data-website="{p.get('website','')}"
              data-city="{p.get('city','')}"
              data-employees="{p.get('employees','')}"
              data-services="{p.get('services','')}"
              data-clutch-url="{p.get('clutch_url','')}"></li>'''
        for p in providers
    )
    nxt = '<a class="next" rel="next" href="?page=2">Next</a>' if has_next else ""
    return f'<ul class="providers">{rows}</ul>{nxt}'


PAGE_1 = _page([
    {"company": "Northwind Studio", "website": "https://northwind.example",
     "city": "Austin, TX", "employees": "50-249",
     "services": "Branding, Video Production",
     "clutch_url": "https://clutch.co/profile/northwind"},
    {"company": "Vance Athletic Agency", "website": "https://vance.example",
     "city": "Denver, CO", "employees": "10-49", "services": "Advertising",
     "clutch_url": "https://clutch.co/profile/vance"},
], has_next=True)

PAGE_2 = _page([
    {"company": "Aurora Collective", "city": "Remote", "employees": "2-9",
     "services": "Sound Design", "clutch_url": "https://clutch.co/profile/aurora"},
    # A repeat of a page-1 company — must be skipped, not stored twice.
    {"company": "Northwind Studio, Inc.", "website": "https://northwind.example"},
], has_next=False)


@pytest.fixture()
def db_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.delenv("CHORDENTIAL_ENABLE_SCRAPE", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)
    conn.close()
    return db_mod


# --- Pure URL construction ------------------------------------------------- #
def test_page_url_starts_on_page_one_then_paginates():
    assert agent.page_url(1) == agent.DEFAULT_BASE_URL
    assert agent.page_url(2) == agent.DEFAULT_BASE_URL + "?page=2"
    assert agent.page_url(7) == agent.DEFAULT_BASE_URL + "?page=7"
    # A base that already has a query keeps it and appends with &.
    assert agent.page_url(3, "https://x.example/dir?sort=az").endswith("&page=3")


# --- Pure parser ----------------------------------------------------------- #
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


def test_has_next_page_detects_the_control():
    assert agent.has_next_page(PAGE_1) is True
    assert agent.has_next_page(PAGE_2) is False


# --- The gate: no network without the flag --------------------------------- #
def test_run_is_a_noop_when_scraping_disabled(db_mod):
    conn = db_mod.connect()
    try:
        report = agent.run(conn)
    finally:
        conn.close()
    assert report.stopped_reason == "scrape_disabled"
    assert report.saved == 0 and report.pages_scanned == 0


# --- The loop: paginate, dedupe, stop at the last page --------------------- #
def test_run_paginates_dedupes_and_stops_at_last_page(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    pages = {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2}
    monkeypatch.setattr(agent, "_fetch_url", lambda url, timeout=10.0: pages[url])

    conn = db_mod.connect()
    try:
        report = agent.run(conn)
        rows = conn.execute("SELECT company, city FROM agencies ORDER BY id").fetchall()
    finally:
        conn.close()

    # Two pages scanned; stopped because page 2 advertised no next page.
    assert report.pages_scanned == 2
    assert report.stopped_reason == "no_more_pages"
    # 4 records seen, 3 unique saved, 1 duplicate skipped.
    assert report.found == 4
    assert report.saved == 3
    assert report.skipped == 1
    names = {r["company"] for r in rows}
    assert names == {"Northwind Studio", "Vance Athletic Agency", "Aurora Collective"}


def test_rerun_skips_everything_already_stored(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    pages = {agent.page_url(1): PAGE_1, agent.page_url(2): PAGE_2}
    monkeypatch.setattr(agent, "_fetch_url", lambda url, timeout=10.0: pages[url])

    conn = db_mod.connect()
    try:
        agent.run(conn)
        second = agent.run(conn)
        total = conn.execute("SELECT COUNT(*) c FROM agencies").fetchone()["c"]
    finally:
        conn.close()
    assert second.saved == 0           # nothing new on a re-scan
    assert second.skipped == second.found
    assert total == 3                  # no duplicates piled up


def test_run_stops_on_empty_page(db_mod, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    # Page 1 claims a next page, but page 2 comes back empty → stop there.
    empty = '<ul class="providers"></ul>'
    pages = {agent.page_url(1): PAGE_1, agent.page_url(2): empty}
    monkeypatch.setattr(agent, "_fetch_url", lambda url, timeout=10.0: pages[url])

    conn = db_mod.connect()
    try:
        report = agent.run(conn)
    finally:
        conn.close()
    assert report.stopped_reason == "empty_page"
    assert report.pages_scanned == 2
    assert report.saved == 2


# --- DB layer: dedupe key + status lifecycle ------------------------------- #
def test_agency_dedupe_normalizes_company_name(db_mod):
    conn = db_mod.connect()
    try:
        first = db_mod.insert_agency(conn, "Acme, Inc.", city="NYC")
        dupe = db_mod.insert_agency(conn, "acme inc")
        assert first is not None
        assert dupe is None              # normalized to the same key
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


# --- Web surface: console renders, run is gated, decisions stick ----------- #
@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.delenv("CHORDENTIAL_ENABLE_SCRAPE", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def test_agencies_console_renders_and_run_is_gated(client):
    c, _ = client
    page = c.get("/agencies")
    assert page.status_code == 200
    assert "Agency Discovery" in page.text
    # Running with scraping OFF is a safe no-op that reports the reason.
    r = c.post("/agencies/run", follow_redirects=True)
    assert r.status_code == 200
    assert "scrape_disabled" in r.text


def test_web_run_then_decide(client, monkeypatch):
    c, db_mod = client
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    from chordential_oia.web import agency_discovery as live
    pages = {live.page_url(1): PAGE_1, live.page_url(2): PAGE_2}
    monkeypatch.setattr(live, "_fetch_url", lambda url, timeout=10.0: pages[url])

    r = c.post("/agencies/run", follow_redirects=True)
    assert "saved=3" in r.text or "Northwind Studio" in r.text

    conn = db_mod.connect()
    try:
        row = conn.execute(
            "SELECT id FROM agencies WHERE company='Aurora Collective'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    c.post(f"/agencies/{row['id']}/status", data={"status": "Dismissed"})
    conn = db_mod.connect()
    try:
        status = conn.execute(
            "SELECT status FROM agencies WHERE id=?", (row["id"],)
        ).fetchone()["status"]
    finally:
        conn.close()
    assert status == "Dismissed"
