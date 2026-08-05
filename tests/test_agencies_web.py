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
# ADR-0044: reached where they live. `app.py` is the application object now and
# imports none of these; using it as a namespace for the package is what kept 55
# dead imports alive in it.
from chordential_oia.web import directory_parsers  # noqa: E402
from chordential_oia.web import enrichment  # noqa: E402


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
    monkeypatch.setattr(enrichment, "scrape_enabled", lambda: True)
    monkeypatch.setattr(enrichment, "_default_fetch", _fake_fetch)
    aid = _agency_id(app_mod, "Acme")
    # The route is fire-and-forget (it fetches the live site, too slow to do inline),
    # so drive the engine synchronously here, then check the profile renders.
    conn = app_mod.db.connect()
    enrichment.enrich_agency(conn, aid)
    conn.close()
    r = client.get(f"/agencies/{aid}")
    assert "Brand Strategy" in r.text and "Web Design" in r.text
    assert "hi@acme.example" in r.text and "2011" in r.text and "complete" in r.text
    state = app_mod.db.get_agency_enrichment(app_mod.db.connect(), aid)
    assert state["status"] == "complete"
    assert state["profile"]["services"] == ["Brand Strategy", "Web Design"]


def test_enrich_action_is_fire_and_forget(app_db, monkeypatch):
    # Pressing Enrich must NOT run the (slow, live-fetching) engine inside the
    # request — it delegates to the background runner and redirects immediately.
    client, app_mod = app_db
    calls = {}
    monkeypatch.setattr(app_mod.scheduler, "start_agency_enrich",
                        lambda aid, reset=False: calls.setdefault("aid", aid) is None or True)
    aid = _agency_id(app_mod, "Acme")
    r = client.post(f"/agencies/{aid}/enrich", follow_redirects=False)
    assert r.status_code == 303 and calls["aid"] == aid


def test_enrich_action_noop_when_scraping_off(app_db):
    # Default env has scraping OFF (the sandbox case): the background runner is a
    # no-op, so nothing is recorded — and crucially the request returns instantly.
    client, app_mod = app_db
    aid = _agency_id(app_mod, "Acme")
    r = client.post(f"/agencies/{aid}/enrich", follow_redirects=True)
    assert r.status_code == 200
    assert not app_mod.db.get_agency_enrichment(app_mod.db.connect(), aid)


def test_agency_detail_404(app_db):
    client, _ = app_db
    assert client.get("/agencies/99999").status_code == 404


def test_agencies_status_endpoint_returns_engine_state_and_counts(app_db):
    # The /agencies page polls this instead of blindly reloading the whole page.
    # It must return the batch-engine state + pending counts as cheap JSON.
    client, _ = app_db
    r = client.get("/agencies/status")
    assert r.status_code == 200
    data = r.json()
    assert "engines" in data and "counts" in data and "any_running" in data
    # Both seeded agencies have a website and no enrichment → both awaiting.
    assert data["counts"]["enrich"] == 2
    for key in ("enrich", "reenrich", "dm", "intel", "signals", "score"):
        assert key in data["engines"]
    # Idle test env → nothing running.
    assert data["any_running"] is False


def test_agencies_status_honors_source_filter(app_db):
    client, _ = app_db
    data = client.get("/agencies/status", params={"source": "thedrum"}).json()
    assert data["counts"]["enrich"] == 1     # only Acme is in 'thedrum'


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
    monkeypatch.setattr(directory_parsers, "scrape_enabled", lambda: True)
    pages = {1: ["Alpha", "Beta"], 2: ["Gamma"]}

    def fake_fetch(url, timeout=15.0):
        pg = 2 if "page=2" in url else 1
        return (_designrush_page(pages[pg], 2), True)
    monkeypatch.setattr(directory_parsers, "_fetch", fake_fetch)

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
    monkeypatch.setattr(directory_parsers, "scrape_enabled", lambda: True)
    monkeypatch.setattr(directory_parsers, "_fetch",
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


# --------------------------------------------------------------------------- #
# Auto-enrichment (the agent enriches on its own) + accordion / pagination.
# --------------------------------------------------------------------------- #
def test_scheduler_run_enrich_cycle_enriches_pending(app_db, monkeypatch):
    # An autonomous pass drives one killable worker per pending agency. The actual
    # enrich logic is covered in test_enrichment; here we assert the cycle advances
    # through the queue (the worker runs out-of-process, so we stand it in).
    client, app_mod = app_db
    from chordential_oia.web import scheduler, db as dbm

    def fake_run_one(conn, action, agency_id, timeout, *, reset=False,
                     label="enrich", on_timeout=None):
        dbm.save_agency_enrichment(conn, agency_id, {
            "status": "complete", "steps_done": [], "links": [], "profile": {}})
        conn.commit()
        return True

    monkeypatch.setattr(scheduler, "_run_one_supervised", fake_run_one)
    completed = scheduler.run_enrich_cycle(batch=10)
    assert completed >= 1
    aid = _agency_id(app_mod, "Acme")
    assert app_mod.db.get_agency_enrichment(app_mod.db.connect(), aid)["status"] == "complete"


def test_manual_enrich_pending_route_fires_background_pass(app_db, monkeypatch):
    # The route is fire-and-forget (a live batch takes minutes, longer than an
    # HTTP request can wait): it delegates to the background starter and reports
    # whether a pass began, rather than enriching inline.
    client, app_mod = app_db
    calls = {}
    monkeypatch.setattr(app_mod.scheduler, "start_manual_enrich",
                        lambda n=0: calls.setdefault("n", n) or True)
    r = client.post("/agencies/enrich-pending", data={"limit": "10"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "eb_started=1" in r.headers["location"]
    assert calls["n"] == 10


def test_accordion_shows_enriched_profile_inline(app_db, monkeypatch):
    client, app_mod = app_db
    monkeypatch.setattr(enrichment, "scrape_enabled", lambda: True)
    monkeypatch.setattr(enrichment, "_default_fetch", _fake_fetch)
    # drive the engine synchronously (the route fires it in the background)
    conn = app_mod.db.connect()
    enrichment.enrich_batch(conn, limit=10)
    conn.close()
    r = client.get("/agencies")
    # the enriched facts render inside the accordion row, not just on the detail page
    assert "Brand Strategy" in r.text and "Web Design" in r.text


def test_agencies_pagination(app_db, monkeypatch):
    client, app_mod = app_db
    # Seed > one page of agencies.
    conn = app_mod.db.connect()
    for i in range(60):
        app_mod.db.upsert_agency(conn, "bulk", {
            "dedup_key": f"co{i}.example", "company": f"Co {i:02d}",
            "website": f"https://co{i}.example"})
    conn.commit(); conn.close()
    p1 = client.get("/agencies", params={"page": 1})
    p2 = client.get("/agencies", params={"page": 2})
    assert "Page 1 of" in p1.text
    assert p1.text != p2.text                # different slices


def test_crawl_panel_stays_open_after_crawl(app_db):
    # After pressing Crawl, the redirect carries cstatus, so the crawl accordion
    # re-renders OPEN instead of collapsing shut.
    client, app_mod = app_db
    r = client.post("/agencies/crawl", data={"source": "thedrum"},
                    follow_redirects=True)
    assert 'id="crawl-panel"' in r.text
    assert 'id="crawl-panel" class="card" style="margin:14px 0" open' in r.text


def test_adforum_marked_paste_only_in_crawl_panel(app_db):
    # AdForum can't be server-crawled (403 + infinite scroll); the panel should
    # say so and not offer a Crawl button for it.
    client, _ = app_db
    r = client.get("/agencies")
    assert "paste-only" in r.text
    from chordential_oia.web import directory_parsers as dp
    assert "adforum" in dp.PASTE_ONLY_SOURCES
