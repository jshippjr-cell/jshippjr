"""Signal Engine (Phase 1) — detection layer: ingest, freshness × score, promote."""

import importlib
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_SIGNAL_TOKEN", "sig-secret")
    monkeypatch.delenv("CHORDENTIAL_RSS_FEEDS", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import signals as sig_mod
    importlib.reload(sig_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod, sig_mod


def test_insert_and_dedupe(ctx):
    _, db, _ = ctx
    conn = db.connect()
    a = db.insert_signal(conn, source="rss", source_weight=6, title="Composer gig", external_ref="http://x/1")
    b = db.insert_signal(conn, source="rss", source_weight=6, title="dup", external_ref="http://x/1")
    assert a is not None and b is None        # deduped on external_ref


def test_freshness_outranks_raw_score(ctx):
    _, db, sig = ctx
    conn = db.connect()
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    db.insert_signal(conn, source="rss", source_weight=6, title="stale", score=80, posted_at=old, external_ref="a")
    db.insert_signal(conn, source="rss", source_weight=6, title="fresh", score=60, posted_at=new, external_ref="b")
    ranked = sig.rank_signals(db.list_signals(conn))
    assert ranked[0]["row"]["title"] == "fresh"    # freshness beats a higher raw score


def test_ingest_alert_creates_scored_signal(ctx):
    _, db, sig = ctx
    conn = db.connect()
    raw = (
        "Title: Composer for indie horror game\n"
        "Company: Silversun Games\nBudget: $1,000-$1,500\nLocation: Remote\n"
        "Looking for a music composer for trailer and ambience.\n"
    )
    assert sig.ingest_alert(conn, raw, source="paste") >= 1
    row = db.list_signals(conn)[0]
    assert row["score"] is not None
    assert row["budget_min"] == 1000.0


def test_rss_parse_and_ingest(ctx, monkeypatch):
    _, db, sig = ctx
    from chordential_oia.web import rss
    xml = (
        "<rss><channel>"
        "<item><title>[PAID] Composer wanted</title><link>http://b/1</link>"
        "<description>budget $2000</description>"
        "<pubDate>Wed, 18 Jun 2026 12:00:00 +0000</pubDate></item>"
        "</channel></rss>"
    )
    items = rss.parse_feed(xml)
    assert items and items[0]["title"].startswith("[PAID]")
    monkeypatch.setattr(rss, "fetch_feed", lambda url: items)
    conn = db.connect()
    assert sig.ingest_feed(conn, "http://feed", source="hitmarker") == 1
    assert db.list_signals(conn)[0]["source"] == "hitmarker"


def test_radar_renders_and_promote(ctx):
    client, db, _ = ctx
    conn = db.connect()
    sid = db.insert_signal(conn, source="rss", source_weight=6, title="Score for trailer",
                           body="composer needed", score=55, external_ref="z")
    conn.close()
    assert client.get("/signals").status_code == 200
    r = client.post(f"/signals/{sid}/promote", follow_redirects=False)
    assert r.status_code == 303 and "/opportunity/" in r.headers["location"]
    conn = db.connect()
    assert db.get_signal(conn, sid)["status"] == "Promoted"


def test_f5bot_link_list_ingests_per_link(ctx):
    _, db, sig = ctx
    body = (
        "F5Bot found the following posts:\n\nReddit:\n\n"
        "composer - [Hiring] Composer for indie horror game\n"
        "https://www.reddit.com/r/gameDevClassifieds/comments/abc/\n\n"
        "music producer - [PAID] Looking for music producer\n"
        "https://www.reddit.com/r/wearethemusicmakers/comments/def/\n"
    )
    conn = db.connect()
    assert sig.ingest_email(conn, "F5Bot found 2 matches", body, source="f5bot") == 2
    rows = db.list_signals(conn)
    assert any("[Hiring] Composer" in r["title"] for r in rows)
    assert any("gameDevClassifieds" in (r["url"] or "") for r in rows)


def test_labeled_digest_uses_structured_parser(ctx):
    _, db, sig = ctx
    conn = db.connect()
    raw = "Title: Composer for trailer\nBudget: $4,000\nNeed original score.\n"
    assert sig.ingest_email(conn, "", raw, source="email") == 1
    assert db.list_signals(conn)[0]["budget_min"] == 4000.0   # structured → budget parsed


def test_email_in_webhook_requires_token(ctx):
    client, _, _ = ctx
    assert client.post("/signals/ingest", content="Title: X\nBudget: $5000\n").status_code == 401
    r = client.post("/signals/ingest?token=sig-secret&source=f5bot",
                    content="Title: Composer\nBudget: $5,000\nNeed a composer.\n")
    assert r.status_code == 200 and r.json()["ingested"] >= 1


# --- Phase 3: leading indicators -------------------------------------------- #
def test_indicator_feed_ingests_as_indicator(ctx, monkeypatch):
    _, db, sig = ctx
    from chordential_oia.web import rss
    items = [{"title": "WPP wins Toyota creative account", "link": "http://n/1",
              "summary": "...", "published": None}]
    monkeypatch.setattr(rss, "fetch_feed", lambda url: items)
    conn = db.connect()
    assert sig.ingest_indicator_feed(conn, "Agency-of-record wins", 72, "q") == 1
    row = db.list_signals(conn)[0]
    assert row["signal_type"] == "indicator" and row["score"] == 72


def test_radar_splits_gigs_and_indicators(ctx):
    client, db, _ = ctx
    conn = db.connect()
    db.insert_signal(conn, source="rss", source_weight=6, title="Composer gig", score=50, external_ref="g1")
    db.insert_signal(conn, source="Agency wins", source_weight=10, title="Brand rebrands",
                     score=66, external_ref="i1", signal_type="indicator")
    conn.close()
    t = client.get("/signals").text
    assert "Live gigs" in t and "Leading indicators" in t
    assert "Composer gig" in t and "Brand rebrands" in t


def test_promote_indicator_is_proactive(ctx):
    client, db, _ = ctx
    conn = db.connect()
    sid = db.insert_signal(conn, source="Agency wins", source_weight=10,
                           title="Brand X rebrands", score=66, external_ref="ind1",
                           signal_type="indicator")
    conn.close()
    r = client.post(f"/signals/{sid}/promote", follow_redirects=False)
    oid = int(r.headers["location"].rsplit("/", 1)[-1])
    conn = db.connect()
    opp = db.get_opportunity(conn, oid)
    assert opp["source"] == "lead_indicator"
    assert "LEADING INDICATOR" in opp["description"]
