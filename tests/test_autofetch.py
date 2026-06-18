"""Background auto-fetch (Discovery Phase 2).

Verifies the scheduler's gate (only approved-lineage targets on active, non-gated
sources are ever due), lead dedup for recurring re-scans, the enable flag, and an
offline cycle that fetches nothing over the network.
"""

import importlib

import pytest


def _modules(tmp_path, monkeypatch, *, scrape=False, autofetch=None):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    if scrape:
        monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    else:
        monkeypatch.delenv("CHORDENTIAL_ENABLE_SCRAPE", raising=False)
    if autofetch is None:
        monkeypatch.delenv("CHORDENTIAL_AUTOFETCH", raising=False)
    else:
        monkeypatch.setenv("CHORDENTIAL_AUTOFETCH", autofetch)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import discovery as disc_mod
    importlib.reload(disc_mod)
    from chordential_oia.web import scheduler as sch_mod
    importlib.reload(sch_mod)
    return db_mod, disc_mod, sch_mod


def _approved(db_mod, conn, source_key, url):
    """Queue + approve an opportunity target on a given source."""
    tid = db_mod.insert_crawl_target(
        conn, "opportunity", f"{source_key} target", "(q)", url, source_key, "why"
    )
    db_mod.update_crawl_target_status(conn, tid, "Approved")
    return tid


def test_due_targets_respect_the_gate(tmp_path, monkeypatch):
    db, disc, _ = _modules(tmp_path, monkeypatch)
    conn = db.connect()
    db.init_db(conn)
    disc.sync_catalog(conn)  # reddit_forhire active; taxi active+login_gated

    reddit = _approved(db, conn, "reddit_forhire", "https://reddit.example/1")
    _approved(db, conn, "taxi", "https://taxi.example/2")          # active but GATED
    db.insert_crawl_target(                                         # Proposed, not Approved
        conn, "opportunity", "p", "(q)", "https://reddit.example/3", "reddit_forhire", "w"
    )

    due_ids = {t["id"] for t in db.autofetch_due_targets(conn, "9999-01-01T00:00:00", limit=10)}
    assert reddit in due_ids                 # approved, active, not gated → due
    assert len(due_ids) == 1                 # taxi gated out; proposed excluded


def test_stale_fetched_target_is_due_again(tmp_path, monkeypatch):
    db, disc, _ = _modules(tmp_path, monkeypatch)
    conn = db.connect()
    db.init_db(conn)
    disc.sync_catalog(conn)
    tid = _approved(db, conn, "reddit_forhire", "https://reddit.example/1")
    db.mark_crawl_target_fetched(conn, tid, 0)   # now Fetched, fetched_at = now

    # A future cutoff means the just-fetched target is already "stale" → due again.
    due = {t["id"] for t in db.autofetch_due_targets(conn, "9999-01-01T00:00:00", limit=10)}
    assert tid in due
    # A past cutoff means it was fetched recently enough → not due.
    not_due = {t["id"] for t in db.autofetch_due_targets(conn, "2000-01-01T00:00:00", limit=10)}
    assert tid not in not_due


def test_lead_dedup(tmp_path, monkeypatch):
    db, _, _ = _modules(tmp_path, monkeypatch)
    conn = db.connect()
    db.init_db(conn)
    db.insert_inbound_lead(
        conn, contact_name="(discovered)", company="Acme", project_type="Spot", source="crawl"
    )
    assert db.inbound_lead_exists(conn, "Acme", "Spot", "crawl") is True
    assert db.inbound_lead_exists(conn, "Acme", "Other", "crawl") is False
    assert db.inbound_lead_exists(conn, "Acme", "Spot", "questionnaire") is False


def test_autofetch_enabled_flag(tmp_path, monkeypatch):
    # Scrape off → never auto-fetch, regardless of the toggle.
    _, _, sch = _modules(tmp_path, monkeypatch, scrape=False)
    assert sch.autofetch_enabled() is False
    # Scrape on, toggle default → on.
    _, _, sch = _modules(tmp_path, monkeypatch, scrape=True)
    assert sch.autofetch_enabled() is True
    # Scrape on, toggle explicitly off → off.
    _, _, sch = _modules(tmp_path, monkeypatch, scrape=True, autofetch="0")
    assert sch.autofetch_enabled() is False


def test_offline_cycle_fetches_nothing_but_marks_fetched(tmp_path, monkeypatch):
    # Scrape OFF: a cycle must run without any network and ingest nothing, while
    # still advancing the approved target to Fetched(0).
    db, disc, sch = _modules(tmp_path, monkeypatch, scrape=False)
    conn = db.connect()
    db.init_db(conn)
    disc.sync_catalog(conn)
    tid = _approved(db, conn, "reddit_forhire", "https://reddit.example/1")
    conn.commit()
    conn.close()

    found = sch.run_cycle(batch=5, delay=0)
    assert found == 0

    conn = db.connect()
    row = db.get_crawl_target(conn, tid)
    assert row["status"] == "Fetched"
    assert row["result_count"] == 0


def test_online_cycle_ingests_then_dedups(tmp_path, monkeypatch):
    # Scrape ON with a stubbed fetcher: two targets return the same listing, so a
    # cycle ingests the lead once and dedups the duplicate.
    db, disc, sch = _modules(tmp_path, monkeypatch, scrape=True)
    html = '<li class="opportunity" data-company="Acme" data-need="Brand spot"></li>'
    monkeypatch.setattr(disc, "_fetch_url", lambda url, timeout=10.0: html)

    conn = db.connect()
    db.init_db(conn)
    disc.sync_catalog(conn)
    _approved(db, conn, "reddit_forhire", "https://reddit.example/a")
    _approved(db, conn, "reddit_forhire", "https://reddit.example/b")
    conn.commit()
    conn.close()

    found = sch.run_cycle(batch=5, delay=0)
    assert found == 1                      # first inserts, second is deduped

    conn = db.connect()
    crawl_leads = [l for l in db.list_inbound_leads(conn) if l["source"] == "crawl"]
    assert len(crawl_leads) == 1
    assert crawl_leads[0]["company"] == "Acme"
