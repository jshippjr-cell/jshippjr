"""Agencies UI — the harvested Master Company Database list, the per-agency
Agency Profile view, and the one-click Enrich action that runs the Company
Enrichment Engine live (the Render smoke test). Network is faked; nothing here
touches the wire.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


# A tiny site with deliberately odd page names, served by the fake fetcher.
SITE = {
    "https://acme.example/": """<html><head><title>Acme</title>
        <meta name="description" content="Acme is an independent studio founded in 2011."></head>
        <body><nav><a href="/what-we-do">What We Do</a>
        <a href="/say-hello">Say Hello</a></nav></body></html>""",
    "https://acme.example/what-we-do": """<body><h2>What We Do</h2><ul>
        <li>Brand Strategy</li><li>Web Design</li></ul></body>""",
    "https://acme.example/say-hello": """<body>
        <a href="mailto:hi@acme.example">hi@acme.example</a></body>""",
}


def _fake_fetch(url, timeout=15.0):
    u = url if url in SITE else (url + "/" if url + "/" in SITE else url)
    return (SITE.get(u, ""), u in SITE)


@pytest.fixture()
def app_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import enrichment as en_mod
    importlib.reload(en_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    # Seed two harvested agencies into the same DB the app reads.
    conn = app_mod.db.connect()
    app_mod.db.init_db(conn)
    app_mod.db.upsert_agency(conn, "thedrum", {
        "dedup_key": "acme.example", "company": "Acme",
        "website": "https://acme.example", "location": "Portland"})
    app_mod.db.upsert_agency(conn, "awwwards", {
        "dedup_key": "globex.example", "company": "Globex",
        "website": "https://globex.example"})
    conn.commit()
    conn.close()
    with TestClient(app_mod.app) as c:
        yield c, app_mod


def _agency_id(app_mod, company):
    conn = app_mod.db.connect()
    try:
        return conn.execute(
            "SELECT id FROM agencies WHERE company = ?", (company,)).fetchone()["id"]
    finally:
        conn.close()


def test_agencies_page_lists_harvested(app_db):
    client, _ = app_db
    r = client.get("/agencies")
    assert r.status_code == 200
    assert "Acme" in r.text and "Globex" in r.text
    assert "Master Company" in r.text          # the explanatory callout rendered


def test_agencies_page_filters_by_source(app_db):
    client, _ = app_db
    r = client.get("/agencies", params={"source": "thedrum"})
    assert "Acme" in r.text and "Globex" not in r.text


def test_agency_detail_before_enrichment(app_db):
    client, app_mod = app_db
    aid = _agency_id(app_mod, "Acme")
    r = client.get(f"/agencies/{aid}")
    assert r.status_code == 200
    assert "Acme" in r.text and "not run" in r.text


def test_enrich_action_runs_live_and_shows_profile(app_db, monkeypatch):
    client, app_mod = app_db
    # Turn live fetching on for the engine and point it at the fake site.
    monkeypatch.setattr(app_mod.enrichment, "scrape_enabled", lambda: True)
    monkeypatch.setattr(app_mod.enrichment, "_default_fetch", _fake_fetch)
    aid = _agency_id(app_mod, "Acme")

    r = client.post(f"/agencies/{aid}/enrich", follow_redirects=True)
    assert r.status_code == 200
    # The extracted facts render on the profile page.
    assert "Brand Strategy" in r.text and "Web Design" in r.text
    assert "hi@acme.example" in r.text
    assert "2011" in r.text
    assert "complete" in r.text

    # And it persisted to the Master Company Database row.
    state = app_mod.db.get_agency_enrichment(app_mod.db.connect(), aid)
    assert state["status"] == "complete"
    assert state["profile"]["services"] == ["Brand Strategy", "Web Design"]


def test_enrich_action_blocked_when_scraping_off(app_db):
    # Default env has scraping OFF (the sandbox case): Enrich records 'blocked'
    # rather than pretending to fetch.
    client, app_mod = app_db
    aid = _agency_id(app_mod, "Acme")
    r = client.post(f"/agencies/{aid}/enrich", follow_redirects=True)
    assert r.status_code == 200
    state = app_mod.db.get_agency_enrichment(app_mod.db.connect(), aid)
    assert state["status"] == "blocked"


def test_agency_detail_404(app_db):
    client, _ = app_db
    assert client.get("/agencies/99999").status_code == 404


# --------------------------------------------------------------------------- #
# Populating the Master Company Database from the dashboard.
# --------------------------------------------------------------------------- #
def test_add_one_agency_by_hand(app_db):
    client, app_mod = app_db
    r = client.post("/agencies/add", data={
        "company": "AURORA Studio", "website": "https://aurora.example",
        "location": "London"}, follow_redirects=True)
    assert r.status_code == 200 and "AURORA Studio" in r.text
    conn = app_mod.db.connect()
    try:
        assert conn.execute(
            "SELECT COUNT(*) c FROM agencies WHERE company='AURORA Studio'"
        ).fetchone()["c"] == 1
    finally:
        conn.close()


def test_ingest_pasted_directory_page(app_db):
    client, app_mod = app_db
    from tests.test_directory_parsers import THEDRUM_HTML
    before = app_mod.db.count_agencies(app_mod.db.connect(), "thedrum")
    r = client.post("/agencies/ingest", data={
        "source": "thedrum", "html": THEDRUM_HTML}, follow_redirects=True)
    assert r.status_code == 200
    # both agencies from the pasted Drum list are now stored + listed
    assert "Bader Rutter" in r.text and "Marketbridge" in r.text
    after = app_mod.db.count_agencies(app_mod.db.connect(), "thedrum")
    assert after - before == 2


def test_ingest_empty_paste_is_safe(app_db):
    client, _ = app_db
    r = client.post("/agencies/ingest", data={"source": "thedrum", "html": ""},
                    follow_redirects=True)
    assert r.status_code == 200      # no crash, just nothing ingested


# --------------------------------------------------------------------------- #
# One-click import of the agencies recovered from the setup pastes.
# --------------------------------------------------------------------------- #
def test_setup_seed_loads_real_agencies(app_db):
    client, app_mod = app_db
    from chordential_oia.web import setup_agencies
    assert setup_agencies.setup_count() >= 150          # recovered from real pastes
    conn = app_mod.db.connect()
    try:
        res = setup_agencies.load(conn)
        assert res["total"] == setup_agencies.setup_count()
        # idempotent: a second load adds no new rows
        again = setup_agencies.load(conn)
        assert again["new"] == 0
        total = app_mod.db.count_agencies(conn)
    finally:
        conn.close()
    assert total >= 150


def test_import_setup_route_populates_db(app_db):
    client, app_mod = app_db
    r = client.post("/agencies/import-setup", follow_redirects=True)
    assert r.status_code == 200
    # real names from the recovered set show up in the list
    assert "Bader Rutter" in r.text or "Locomotive" in r.text
    from chordential_oia.web import setup_agencies
    assert app_mod.db.count_agencies(app_mod.db.connect()) >= setup_agencies.setup_count()


# --------------------------------------------------------------------------- #
# Live directory crawl trigger (bounded + resumable). Network is faked.
# --------------------------------------------------------------------------- #
# A 2-page DesignRush-style listing: page 1 has two agencies + says "of 2",
# page 2 has one. Proves the button paginates and accumulates across clicks.
def _designrush_page(names, total_pages):
    cards = "".join(
        f'<article data-agency-name="{n}">'
        f'<a class="gtm-agency-website-link" href="https://{n.lower()}.example">site</a>'
        f'<a class="gtm-agency-profile-link" href="/agency/profile/{n.lower()}">p</a>'
        f'<div class="i-region">United States</div>'
        f'<div class="i-employees">10 - 49</div>'
        f'<div class="item-description">Desc for {n}.</div></article>'
        for n in names)
    return (f'<div id="paginator" data-count="of {total_pages}"></div>'
            f'<span>120 Companies</span>{cards}')


def test_live_crawl_button_paginates_and_resumes(app_db, monkeypatch):
    client, app_mod = app_db
    monkeypatch.setattr(app_mod.directory_parsers, "scrape_enabled", lambda: True)
    pages = {1: ["Alpha", "Beta"], 2: ["Gamma"]}

    def fake_fetch(url, timeout=15.0):
        pg = 2 if "page=2" in url else 1
        return (_designrush_page(pages[pg], 2), True)
    monkeypatch.setattr(app_mod.directory_parsers, "_fetch", fake_fetch)

    # One click walks up to PAGES_PER_CRAWL_CLICK pages; this tiny site (2 pages)
    # finishes in a single click.
    r = client.post("/agencies/crawl", data={"source": "designrush"},
                    follow_redirects=True)
    assert r.status_code == 200
    conn = app_mod.db.connect()
    try:
        rows = {row["company"] for row in app_mod.db.list_agencies(conn, "designrush")}
    finally:
        conn.close()
    assert {"Alpha", "Beta", "Gamma"} <= rows


def test_live_crawl_reports_error_when_fetch_blocked(app_db, monkeypatch):
    # Scraping on, but the directory refuses (simulating a bot block): the engine
    # records an error rather than inventing rows.
    client, app_mod = app_db
    monkeypatch.setattr(app_mod.directory_parsers, "scrape_enabled", lambda: True)
    monkeypatch.setattr(app_mod.directory_parsers, "_fetch",
                        lambda url, timeout=15.0: ("", False))
    r = client.post("/agencies/crawl", data={"source": "adforum"},
                    follow_redirects=True)
    assert r.status_code == 200
    st = app_mod.db.get_crawl_state(app_mod.db.connect(), "adforum")
    assert st["status"] == "error"
    assert app_mod.db.count_agencies(app_mod.db.connect(), "adforum") == 0


def test_live_crawl_blocked_when_scraping_off(app_db):
    # Default sandbox case: scraping off -> the source reports not-ok -> error.
    client, app_mod = app_db
    r = client.post("/agencies/crawl", data={"source": "thedrum"},
                    follow_redirects=True)
    assert r.status_code == 200
    st = app_mod.db.get_crawl_state(app_mod.db.connect(), "thedrum")
    assert st["status"] == "error"
