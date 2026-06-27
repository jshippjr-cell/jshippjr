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
