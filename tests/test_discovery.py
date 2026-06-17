"""Human-gated discovery crawler (Cycle 2.3).

Core contract: the system proposes targets deterministically and never fetches
anything until Jon approves it. Network is additionally env-gated and is never
touched in tests except via a monkeypatched fetch.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent_sources import scraped
from chordential_oia.talent_sources.scraped import (
    ScrapedTalentSource,
    parse_talent_html,
    scrape_enabled,
)
from chordential_oia.web import discovery


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
    with TestClient(app_mod.app) as c:
        yield c, db_mod


# --- Proposal generation (pure, deterministic, no network) ----------------- #
def test_propose_talent_targets_deterministic():
    a = discovery.propose_talent_targets([MusicDiscipline.COMPOSITION])
    b = discovery.propose_talent_targets([MusicDiscipline.COMPOSITION])
    assert a == b and a, "proposals must be deterministic and non-empty"
    for t in a:
        assert t["kind"] == "talent"
        assert t["url"].startswith("http")


def test_propose_opportunity_targets():
    targets = discovery.propose_opportunity_targets(["original music RFP"])
    assert targets
    assert all(t["kind"] == "opportunity" for t in targets)


# --- Pure parsers ---------------------------------------------------------- #
def test_parse_talent_html_yields_pending_crawl_talent():
    creators = parse_talent_html(TALENT_HTML, source_url="https://ex.com")
    names = {c.name for c in creators}
    assert names == {"Web Wendy", "Crawl Carl"}      # non-creator element ignored
    for c in creators:
        assert c.source == "crawl"
        assert not c.matchable                         # Pending until reviewed
    wendy = next(c for c in creators if c.name == "Web Wendy")
    assert MusicDiscipline.COMPOSITION in wendy.disciplines
    assert MusicDiscipline.SOUND_DESIGN in wendy.disciplines


def test_parse_opportunity_html():
    recs = discovery.parse_opportunity_html(OPP_HTML)
    assert len(recs) == 1
    assert recs[0]["company"] == "Acme Brand"


# --- The gate: no fetch without approval, no network without the flag ------ #
def test_scrape_disabled_by_default():
    assert scrape_enabled() is False
    # With the flag off, the source never touches the network and yields nothing.
    assert ScrapedTalentSource("https://example.com").fetch() == []


def test_run_target_refuses_unapproved(ctx):
    _, db_mod = ctx
    conn = db_mod.connect()
    tid = db_mod.insert_crawl_target(
        conn, "talent", "L", "q", "https://ex.com", "google", "why"
    )
    target = db_mod.get_crawl_target(conn, tid)
    conn.close()
    with pytest.raises(ValueError):
        discovery.run_target(db_mod.connect(), target)  # status is Proposed


def test_generate_dedupes(ctx):
    _, db_mod = ctx
    conn = db_mod.connect()
    try:
        first = discovery.generate_targets(conn, "talent")
        again = discovery.generate_targets(conn, "talent")
    finally:
        conn.close()
    assert first > 0
    assert again == 0          # identical proposals are deduped on kind+url


# --- Web flow: propose -> approve -> fetch (gate enforced at each step) ----- #
def test_web_flow_propose_approve_fetch(ctx):
    client, db_mod = ctx
    assert client.get("/discovery").status_code == 200

    # Propose targets.
    client.post("/discovery/generate", data={"kind": "talent"})
    conn = db_mod.connect()
    tid = conn.execute(
        "SELECT id FROM crawl_targets WHERE kind='talent' LIMIT 1"
    ).fetchone()[0]
    conn.close()

    # Fetching a PROPOSED target does nothing (the gate).
    client.post(f"/discovery/{tid}/fetch", data={"kind": "talent"})
    conn = db_mod.connect()
    assert db_mod.get_crawl_target(conn, tid)["status"] == "Proposed"
    conn.close()

    # Approve it.
    client.post(f"/discovery/{tid}/status", data={"status": "Approved", "kind": "talent"})
    conn = db_mod.connect()
    assert db_mod.get_crawl_target(conn, tid)["status"] == "Approved"
    conn.close()

    # Fetch with scrape OFF: allowed (approved) but yields nothing, marked Fetched.
    client.post(f"/discovery/{tid}/fetch", data={"kind": "talent"})
    conn = db_mod.connect()
    row = db_mod.get_crawl_target(conn, tid)
    conn.close()
    assert row["status"] == "Fetched"
    assert row["result_count"] == 0


def test_approved_fetch_ingests_when_enabled(ctx, monkeypatch):
    client, db_mod = ctx
    # Turn the flag on and monkeypatch the network fetch to return fixture HTML.
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    monkeypatch.setattr(scraped, "_fetch_url", lambda url, timeout=10.0: TALENT_HTML)

    conn = db_mod.connect()
    tid = db_mod.insert_crawl_target(
        conn, "talent", "L", "q", "https://ex.com", "google", "why"
    )
    db_mod.update_crawl_target_status(conn, tid, "Approved")
    target = db_mod.get_crawl_target(conn, tid)
    n = discovery.run_target(conn, target)
    conn.close()
    assert n == 2                          # both creators ingested

    # They land Pending in the roster with crawl provenance — Jon still reviews.
    conn = db_mod.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM talent WHERE source='crawl'"
        ).fetchall()
    finally:
        conn.close()
    assert {r["name"] for r in rows} == {"Web Wendy", "Crawl Carl"}
    assert all(r["review_status"] == "Pending" for r in rows)
