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


def test_rss_url_encoding_handles_spaces():
    """A search feed with raw spaces is percent-encoded; pre-encoded URLs are
    left intact (no double-encoding)."""
    from chordential_oia.web.rss import _safe_url
    out = _safe_url("https://www.reddit.com/r/forhire/search.rss?q=composer OR music&restrict_sr=1")
    assert " " not in out and "q=composer%20OR%20music" in out
    assert _safe_url("https://x/y.rss?q=%22a%20b%22") == "https://x/y.rss?q=%22a%20b%22"


def test_engine_selftest_all_sources_land(ctx):
    """Every weighted source ingests, passes the filter, scores, and ranks."""
    _, _, sig = ctx
    rep = sig.engine_selftest()
    assert rep["all_landed"] is True
    assert len(rep["rows"]) == len(sig.SELFTEST_SOURCES) == 10
    keys = {r["key"] for r in rep["rows"]}
    assert {"productionhub", "mandy", "hitmarker", "soundbetter"} <= keys
    assert all(r["score"] is not None for r in rep["rows"])
    # Source weight now tilts the rank: identical content → a top-weight source
    # ranks first, SoundBetter (un-floored to 4) last.
    assert rep["weight_affects_rank"] is True
    assert rep["rows"][0]["weight"] == 10
    assert rep["rows"][-1]["label"] == "SoundBetter" and rep["rows"][-1]["weight"] == 4


def test_selftest_page_renders(ctx):
    client, _, _ = ctx
    r = client.get("/signals/selftest")
    assert r.status_code == 200
    assert "Engine Self-Test" in r.text and "ProductionHUB" in r.text


def test_reddit_flair_targets_paid(ctx, monkeypatch):
    """The Reddit [PAID]/[Hiring] flair lands the gig even when the title is
    plain; [For Hire] (self-promo) and [Rev Share]/unpaid are dropped."""
    _, db, sig = ctx
    items = [
        {"title": "Composer for our RPG", "summary": "looking for a score",
         "link": "r1", "published": None, "flair": "PAID"},            # plain title, paid flair
        {"title": "Composer available, great portfolio", "summary": "",
         "link": "r2", "published": None, "flair": "For Hire"},        # self-promo
        {"title": "Composer needed for our game", "summary": "",
         "link": "r3", "published": None, "flair": "Rev Share"},       # unpaid
    ]
    monkeypatch.setattr(sig.rss, "fetch_feed", lambda url: items)
    rep = sig.ingest_feed_report(db.connect(),
                                 "https://www.reddit.com/r/gameDevClassifieds/new/.rss",
                                 source="reddit-gamedev")
    assert rep["fetched"] == 3 and rep["landed"] == 1     # only the [PAID] one lands
    rows = db.list_signals(db.connect())
    assert len(rows) == 1 and rows[0]["title"].startswith("[PAID]")


def test_ingest_feed_report_counts(ctx, monkeypatch):
    _, db, sig = ctx
    items = [
        {"title": "[Hiring] Composer needed — $1000", "summary": "music",
         "link": "l1", "published": None},
        {"title": "random chat thread", "summary": "", "link": "l2", "published": None},
    ]
    monkeypatch.setattr(sig.rss, "fetch_feed", lambda url: items)
    rep = sig.ingest_feed_report(db.connect(),
                                 "https://www.reddit.com/r/x/new.rss", source="reddit-x")
    assert rep == {"fetched": 2, "landed": 1}      # both fetched, only the gig lands


def test_poll_now_reports_per_feed(ctx, monkeypatch):
    client, db, sig = ctx
    from chordential_oia.web import scheduler
    monkeypatch.setenv("CHORDENTIAL_RSS_FEEDS",
                       "reddit-x|https://www.reddit.com/r/x/new.rss")
    items = [
        {"title": "[Hiring] Composer for a game — $1000", "summary": "music",
         "link": "https://reddit.com/r/x/1", "published": None},
        {"title": "random chat", "summary": "", "link": "https://reddit.com/r/x/2",
         "published": None},
    ]
    monkeypatch.setattr(sig.rss, "fetch_feed", lambda url: items)
    summary = scheduler.poll_now()
    assert "reddit-x" in summary and "2 items" in summary and "1 new gig" in summary
    assert scheduler.last_poll() == summary


def test_poll_route_redirects(ctx, monkeypatch):
    client, _, _ = ctx
    from chordential_oia.web import scheduler
    monkeypatch.setattr(scheduler, "poll_now", lambda: "polled")
    r = client.post("/signals/poll", follow_redirects=False)
    assert r.status_code == 303 and "poll=1" in r.headers["location"]


def test_reddit_rss_feed_is_strictly_filtered(ctx, monkeypatch):
    """A Reddit RSS feed gets the strict music-gig filter (it's noisy); only real
    gigs land, discussion/noise is dropped."""
    _, db, sig = ctx
    items = [
        {"title": "[Hiring] Composer for our game — $1500/track",
         "summary": "original music", "link": "https://www.reddit.com/r/x/1", "published": None},
        {"title": "What's everyone listening to today?",
         "summary": "chat", "link": "https://www.reddit.com/r/x/2", "published": None},
    ]
    monkeypatch.setattr(sig.rss, "fetch_feed", lambda url: items)
    n = sig.ingest_feed(db.connect(),
                        "https://www.reddit.com/r/forhire/new.rss", source="reddit")
    assert n == 1                              # only the hiring gig clears is_music_gig
    rows = db.list_signals(db.connect())
    assert len(rows) == 1 and "Composer" in rows[0]["title"]


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


def test_promote_carries_original_post_url(ctx):
    """A promoted signal keeps its source link so the opportunity Overview can
    show the original post (the F5Bot/reddit case where body text is empty)."""
    client, db, _ = ctx
    conn = db.connect()
    sid = db.insert_signal(conn, source="reddit", source_weight=6,
                           title="[PAID] Composer needed", body="",
                           url="https://www.reddit.com/r/x/comments/abc/",
                           score=55, external_ref="https://www.reddit.com/r/x/comments/abc/")
    conn.close()
    r = client.post(f"/signals/{sid}/promote", follow_redirects=False)
    loc = r.headers["location"]
    page = client.get(loc).text
    assert "Original post" in page
    assert "https://www.reddit.com/r/x/comments/abc/" in page   # link surfaced in overview


def test_send_push_unset_and_test_route(ctx, monkeypatch):
    client, _, sig = ctx
    monkeypatch.delenv("CHORDENTIAL_NTFY_TOPIC", raising=False)
    assert sig.push_configured() is False
    assert sig.send_push("hi") == "unset"
    r = client.post("/signals/test-push", follow_redirects=False)
    assert r.status_code == 303 and "push=unset" in r.headers["location"]


def test_push_builds_request_with_unicode_title(ctx, monkeypatch):
    """Emoji/unicode in the title must not break the push: header values are
    latin-1 only, so they get sanitized while the request still goes out. We
    stub the network and assert the Request is built without raising."""
    _, _, sig = ctx
    monkeypatch.setenv("CHORDENTIAL_NTFY_TOPIC", "chord-test")
    captured = {}

    def fake_urlopen(req, timeout=8):
        # Would raise UnicodeEncodeError here before the fix if a header held an
        # emoji; reaching this point means headers are latin-1 safe.
        for k, v in req.header_items():
            v.encode("latin-1")
        captured["title"] = req.get_header("Title")
        return None

    monkeypatch.setattr(sig.urllib.request, "urlopen", fake_urlopen)
    assert sig.send_push("🎵 New gig — déjà vu", body="composer needed") == "sent"
    assert "New gig" in captured["title"]            # emoji dropped, text kept


def test_f5bot_filter_keeps_only_real_gigs(ctx):
    _, db, sig = ctx
    body = (
        "F5Bot found the following:\n\n"
        "Reddit Posts (/r/gameDevClassifieds/): '[PAID] Looking for Music Composer' by dev1\n"
        "https://f5bot.com/url?u=https%3A%2F%2Fwww.reddit.com%2Fr%2FgameDevClassifieds%2Fcomments%2Fabc%2F&i=1\n\n"
        "Reddit Comments (/r/Music/): 'Legendary producer dead at 29' by foo\n"
        "https://f5bot.com/url?u=https%3A%2F%2Fwww.reddit.com%2Fr%2FMusic%2Fcomments%2Fxyz%2F&i=2\n\n"
        "Reddit Posts (/r/IndiaSocial/): 'Late Night Random Discussion Thread' by bar\n"
        "https://f5bot.com/url?u=https%3A%2F%2Fwww.reddit.com%2Fr%2FIndiaSocial%2Fcomments%2Fqqq%2F&i=3\n"
    )
    conn = db.connect()
    assert sig.ingest_email(conn, "F5Bot", body, source="f5bot") == 1   # only the PAID gig
    rows = db.list_signals(conn)
    assert len(rows) == 1
    assert "Music Composer" in rows[0]["title"]
    assert rows[0]["url"].startswith("https://www.reddit.com")          # f5bot link unwrapped
    assert rows[0]["source"] == "/r/gameDevClassifieds"


def test_is_music_gig_filter(ctx):
    _, _, sig = ctx
    assert sig.is_music_gig("[PAID] Composer needed for our game")
    assert not sig.is_music_gig("Late Night Random Discussion Thread")        # no role/demand
    assert not sig.is_music_gig("Looking for a video editor and content creator")  # no music role
    assert not sig.is_music_gig("RIP Bobby Prince - Music Composer")          # role, no demand
    assert not sig.is_music_gig("[Hobby] band needs a composer for fun")      # collab/unpaid
    assert not sig.is_music_gig("Reddit Comments (/r/Music/): poll about composers")  # comment


def test_money_signals_demand_recall_fix(ctx):
    """B0 recall fix: a paid gig that signals pay with money — not a hiring
    verb — is demand, and a real music gig instead of being silently dropped."""
    _, _, sig = ctx
    assert sig.intent("Composer for our mobile game", "$500/track, DM me") == "demand"
    assert sig.intent("Original score for short film", "USD 2k flat fee") == "demand"
    assert sig.is_music_gig("Composer for our mobile game — $500/track")
    # A resolution is not a budget: "4k video" must not read as money/demand.
    assert sig.intent("Composer wanted", "delivering a 4k video") == "demand"  # via "wanted"
    assert sig.intent("Editing a 4k video reel") == "unknown"                  # no pay, no demand
    # Explicit self-promo stays supply even if it quotes a rate.
    assert sig.intent("Composer available for hire, my rate is $50/hr, check out my reel") == "supply"


def test_paid_partner_gig_not_dropped_as_collab(ctx):
    """B0 recall fix: 'partner'/'royalty' no longer auto-classify a paid agency
    brief as hobby/collab."""
    _, _, sig = ctx
    assert sig.is_music_gig("Seeking a composer to partner with our agency on a paid campaign")
    # Genuinely unpaid collab is still dropped.
    assert not sig.is_music_gig("Composer wanted to join our band, rev share only")


def test_clear_radar(ctx):
    client, db, _ = ctx
    conn = db.connect()
    db.insert_signal(conn, source="x", source_weight=5, title="a", external_ref="1")
    db.insert_signal(conn, source="x", source_weight=5, title="b", external_ref="2")
    conn.close()
    client.post("/signals/clear")
    conn = db.connect()
    assert db.list_signals(conn) == []


def test_labeled_digest_uses_structured_parser(ctx):
    _, db, sig = ctx
    conn = db.connect()
    raw = "Title: Composer for trailer\nBudget: $4,000\nNeed original score.\n"
    assert sig.ingest_email(conn, "", raw, source="email") == 1
    assert db.list_signals(conn)[0]["budget_min"] == 4000.0   # structured → budget parsed


# --- Intent filter: demand (gigs) vs supply (self-promo) -------------------- #
def test_intent_classifier(ctx):
    _, _, sig = ctx
    assert sig.intent("[Hiring] Composer needed for game") == "demand"
    assert sig.intent("[For Hire] Composer looking for work") == "supply"
    assert sig.intent("Looking for a composer for our indie game") == "demand"
    assert sig.intent("Experienced composer available for hire, check out my portfolio") == "supply"


def test_ingest_drops_self_promo_keeps_gigs(ctx):
    _, db, sig = ctx
    conn = db.connect()
    kept = sig.ingest_signal(conn, source="f5bot", title="[Hiring] Composer needed", external_ref="a")
    dropped = sig.ingest_signal(conn, source="f5bot",
                                title="[For Hire] composer available, hire me", external_ref="b")
    assert kept is not None and dropped is None
    titles = [r["title"] for r in db.list_signals(conn)]
    assert any("Hiring" in t for t in titles) and not any("For Hire" in t for t in titles)


def test_nav_badge_counts_new_gigs(ctx):
    client, db, _ = ctx
    conn = db.connect()
    s1 = db.insert_signal(conn, source="rss", source_weight=6, title="Composer needed", external_ref="1")
    db.insert_signal(conn, source="rss", source_weight=6, title="Score for trailer", external_ref="2")
    conn.close()
    # JSON count + the badge in the nav both reflect 2 unactioned gigs.
    assert client.get("/signals/count").json()["new"] == 2
    assert 'id="signal-badge"' in client.get("/dashboard").text
    # Promoting/dismissing decrements the count.
    client.post(f"/signals/{s1}/status", data={"status": "Dismissed"})
    assert client.get("/signals/count").json()["new"] == 1


def test_email_in_webhook_requires_token(ctx):
    client, _, _ = ctx
    assert client.post("/signals/ingest", content="Title: X\nBudget: $5000\n").status_code == 401
    r = client.post("/signals/ingest?token=sig-secret&source=f5bot",
                    content="Title: Composer\nBudget: $5,000\nNeed a composer.\n")
    assert r.status_code == 200 and r.json()["ingested"] >= 1
