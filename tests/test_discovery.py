"""Human-gated discovery crawler (Cycles 2.3 + curated sources).

Core contract: the crawler combs a council-vetted catalog of industry sites (no
broad web search), proposes nothing from a site until that site is active, and
fetches nothing until Jon approves the target. Network is env-gated and never
touched in tests except via a monkeypatched fetch.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.talent_sources import scraped
from chordential_oia.talent_sources.scraped import (
    ScrapedTalentSource,
    parse_talent_html,
    scrape_enabled,
)
from chordential_oia.web import discovery
from chordential_oia.web import discovery_sources as catalog


TALENT_HTML = """
<ul>
  <li class="creator" data-name="Web Wendy"
      data-disciplines="composition,sound_design" data-location="Remote"
      data-url="https://ex.com/wendy" data-credits="Two national spots"></li>
  <li class="creator" data-name="Crawl Carl" data-disciplines="sonic_branding"
      data-url="https://ex.com/carl"></li>
  <li class="other" data-name="Ignore Me"></li>
</ul>
"""

OPP_HTML = """
<li class="opportunity" data-company="Acme Brand" data-need="Brand spot music"
    data-url="https://ex.com/rfp" data-description="National campaign, original"></li>
"""


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.delenv("CHORDENTIAL_ENABLE_SCRAPE", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:   # lifespan syncs the catalog
        yield c, db_mod


# --- Curated catalog (pure, no network) ------------------------------------ #
def test_catalog_has_real_industry_sites():
    keys = {s.key for s in catalog.CATALOG}
    for expected in ("productionhub", "taxi", "vicontrol", "soundbetter"):
        assert expected in keys


def test_site_targets_build_real_urls():
    site = catalog.get_site("reddit_gamedev")
    targets = catalog.site_targets(site, "opportunity", keyword="composer")
    assert targets and all(t["url"].startswith("https://www.reddit.com") for t in targets)


def test_no_broad_search_providers_in_active_proposals(ctx):
    _, db_mod = ctx
    conn = db_mod.connect()
    try:
        for kind in ("opportunity", "talent"):
            keys = db_mod.active_discovery_site_keys(conn, kind)
            for p in discovery.propose_targets(keys, kind, keyword="composer"):
                assert "google.com/search" not in p["url"]
                assert "bing.com/search" not in p["url"]
    finally:
        conn.close()


# --- Catalog sync + site-level gate ---------------------------------------- #
def test_catalog_synced_with_established_active_and_suggested(ctx):
    _, db_mod = ctx
    conn = db_mod.connect()
    try:
        counts = db_mod.discovery_site_counts(conn)
        assert counts["active"] > 0
        assert counts["Suggested"] > 0          # emerging sites await approval
    finally:
        conn.close()


def test_suggested_site_not_used_until_approved(ctx):
    client, db_mod = ctx
    conn = db_mod.connect()
    # x_gigs is a Suggested opportunity site.
    site = conn.execute(
        "SELECT * FROM discovery_sites WHERE key='x_gigs'"
    ).fetchone()
    assert site["status"] == "Suggested"
    keys_before = db_mod.active_discovery_site_keys(conn, "opportunity")
    conn.close()
    assert "x_gigs" not in keys_before          # not active → never proposed

    # Approve the site (Jon's permission), then it becomes active.
    client.post(f"/discovery/site/{site['id']}/status",
                data={"status": "Approved", "kind": "opportunity"})
    conn = db_mod.connect()
    try:
        keys_after = db_mod.active_discovery_site_keys(conn, "opportunity")
    finally:
        conn.close()
    assert "x_gigs" in keys_after


def test_generate_proposes_from_active_sites_and_dedupes(ctx):
    _, db_mod = ctx
    conn = db_mod.connect()
    try:
        first = discovery.generate_targets(conn, "opportunity", keyword="composer")
        again = discovery.generate_targets(conn, "opportunity", keyword="composer")
    finally:
        conn.close()
    assert first > 0
    assert again == 0          # identical proposals deduped on kind+url


# --- Pure parsers ---------------------------------------------------------- #
def test_parse_talent_html_yields_pending_crawl_talent():
    creators = parse_talent_html(TALENT_HTML, source_url="https://ex.com")
    assert {c.name for c in creators} == {"Web Wendy", "Crawl Carl"}
    for c in creators:
        assert c.source == "crawl"
        assert not c.matchable


def test_parse_opportunity_html():
    recs = discovery.parse_opportunity_html(OPP_HTML)
    assert len(recs) == 1 and recs[0]["company"] == "Acme Brand"


# --- The gate: no fetch without approval, no network without the flag ------ #
def test_scrape_disabled_by_default():
    assert scrape_enabled() is False
    assert ScrapedTalentSource("https://example.com").fetch() == []


def test_run_target_refuses_unapproved(ctx):
    _, db_mod = ctx
    conn = db_mod.connect()
    tid = db_mod.insert_crawl_target(
        conn, "talent", "L", "q", "https://ex.com", "vicontrol", "why"
    )
    target = db_mod.get_crawl_target(conn, tid)
    conn.close()
    with pytest.raises(ValueError):
        discovery.run_target(db_mod.connect(), target)


# --- Web flow: propose -> approve -> fetch (gate enforced at each step) ----- #
def test_web_flow_propose_approve_fetch(ctx):
    client, db_mod = ctx
    assert client.get("/discovery").status_code == 200

    # Keyworded generate produces NEW Proposed targets (distinct from the default
    # Approved targets that active sources are seeded with).
    client.post("/discovery/generate", data={"kind": "talent", "terms": "violinist"})
    conn = db_mod.connect()
    row = conn.execute(
        "SELECT id FROM crawl_targets WHERE kind='talent' AND status='Proposed' LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None, "active talent sites should have produced targets"
    tid = row[0]

    # Fetching a PROPOSED target does nothing (the gate).
    client.post(f"/discovery/{tid}/fetch", data={"kind": "talent"})
    conn = db_mod.connect()
    assert db_mod.get_crawl_target(conn, tid)["status"] == "Proposed"
    conn.close()

    client.post(f"/discovery/{tid}/status", data={"status": "Approved", "kind": "talent"})
    client.post(f"/discovery/{tid}/fetch", data={"kind": "talent"})
    conn = db_mod.connect()
    row = db_mod.get_crawl_target(conn, tid)
    conn.close()
    assert row["status"] == "Fetched"
    assert row["result_count"] == 0          # scrape OFF → nothing ingested


def test_manual_lead_capture_lands_in_queue(ctx):
    client, db_mod = ctx
    client.post("/discovery/lead", data={
        "title": "Indie film score", "company": "Acme Films",
        "link": "https://reddit.com/r/forhire/x", "notes": "warm, orchestral",
    })
    conn = db_mod.connect()
    manual = [r for r in db_mod.list_inbound_leads(conn) if r["source"] == "manual"]
    conn.close()
    assert manual and manual[0]["project_type"] == "Indie film score"
    assert "reddit.com" in (manual[0]["description"] or "")


def test_jon_can_add_custom_site_and_point_crawler(ctx):
    client, db_mod = ctx
    client.post("/discovery/site/add", data={
        "name": "My Indie Board", "url": "https://indieboard.example/jobs",
        "kind": "opportunity", "rationale": "A board I know.",
    })
    conn = db_mod.connect()
    try:
        site = db_mod.get_discovery_site_by_key(conn, "custom-my-indie-board")
        active = db_mod.active_discovery_site_keys(conn, "opportunity")
        targets = conn.execute(
            "SELECT * FROM crawl_targets WHERE source_key='custom-my-indie-board'"
        ).fetchall()
    finally:
        conn.close()
    assert site is not None
    assert site["status"] == "Approved"           # Jon's own call → active
    assert site["board_url"] == "https://indieboard.example/jobs"
    assert "custom-my-indie-board" in active        # usable by the generator
    assert len(targets) == 1                        # queued, awaiting approval
    assert targets[0]["status"] == "Proposed"


def test_custom_site_keyword_slot_substitutes_on_generate(ctx):
    client, db_mod = ctx
    client.post("/discovery/site/add", data={
        "name": "Query Board", "url": "https://qb.example/search?q={q}",
        "kind": "opportunity",
    })
    conn = db_mod.connect()
    try:
        discovery.generate_targets(conn, "opportunity", keyword="sonic branding")
        rows = conn.execute(
            "SELECT url FROM crawl_targets WHERE source_key='custom-query-board'"
        ).fetchall()
    finally:
        conn.close()
    urls = [r["url"] for r in rows]
    assert any("sonic+branding" in u for u in urls)
    assert all("{q}" not in u for u in urls)        # the slot was filled


def test_approved_fetch_ingests_when_enabled(ctx, monkeypatch):
    _, db_mod = ctx
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    monkeypatch.setattr(scraped, "_fetch_url", lambda url, timeout=10.0: TALENT_HTML)

    conn = db_mod.connect()
    tid = db_mod.insert_crawl_target(
        conn, "talent", "L", "q", "https://ex.com", "vicontrol", "why"
    )
    db_mod.update_crawl_target_status(conn, tid, "Approved")
    target = db_mod.get_crawl_target(conn, tid)
    n = discovery.run_target(conn, target)
    conn.close()
    assert n == 2

    conn = db_mod.connect()
    try:
        rows = conn.execute("SELECT * FROM talent WHERE source='crawl'").fetchall()
    finally:
        conn.close()
    assert {r["name"] for r in rows} == {"Web Wendy", "Crawl Carl"}
    assert all(r["review_status"] == "Pending" for r in rows)
