"""Direct Reddit polling into the signals tape (the cap-free F5Bot replacement).

The Reddit HTTP adapter is mocked, so these run offline: a fake fetch_reddit
returns records, and we assert only real music gigs land (via the strict
is_music_gig filter), with dedup and gating.
"""

import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    _c = db_mod.connect(); db_mod.init_db(_c); _c.close()
    from chordential_oia.web import signals as sig_mod
    importlib.reload(sig_mod)
    from chordential_oia.web import scheduler as sched_mod
    importlib.reload(sched_mod)
    from chordential_oia.web import crawl_adapters as ca_mod
    # speed: no real politeness sleep between queries
    monkeypatch.setattr(sched_mod.time, "sleep", lambda *_: None)
    yield db_mod, sched_mod, ca_mod


_RECORDS = [
    {"company": "u/devstudio",
     "need": "[Hiring] Composer for our indie game — $2000/track",
     "description": "We need original music.", "url": "https://reddit.com/r/x/1"},
    {"company": "u/chatter",
     "need": "Late night discussion thread about scores",
     "description": "just chatting", "url": "https://reddit.com/r/x/2"},
]


def test_poll_reddit_lands_only_real_gigs(ctx, monkeypatch):
    db, sched, ca = ctx
    monkeypatch.setattr(ca, "fetch_reddit",
                        lambda url: {"records": _RECORDS, "outcome": "ok", "detail": ""})
    monkeypatch.setenv("CHORDENTIAL_REDDIT_QUERIES", "https://www.reddit.com/r/x/new/")

    landed = sched.poll_reddit()
    assert landed == 1                                  # gig lands; discussion filtered out
    rows = db.list_signals(db.connect())
    assert len(rows) == 1
    assert rows[0]["source"] == "reddit"
    assert rows[0]["contact_handle"] == "u/devstudio"   # poster handle carried for Respond
    assert rows[0]["external_ref"] == "https://reddit.com/r/x/1"


def test_poll_reddit_is_idempotent(ctx, monkeypatch):
    db, sched, ca = ctx
    monkeypatch.setattr(ca, "fetch_reddit",
                        lambda url: {"records": _RECORDS, "outcome": "ok", "detail": ""})
    monkeypatch.setenv("CHORDENTIAL_REDDIT_QUERIES", "https://www.reddit.com/r/x/new/")
    sched.poll_reddit()
    assert sched.poll_reddit() == 0                     # dedup on the permalink URL
    assert len(db.list_signals(db.connect())) == 1


def test_reddit_enabled_requires_creds(ctx, monkeypatch):
    _, sched, _ = ctx
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    assert sched.reddit_enabled() is False             # no creds → off (would 403 anyway)
    monkeypatch.setenv("REDDIT_CLIENT_ID", "x")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "y")
    assert sched.reddit_enabled() is True
    monkeypatch.setenv("CHORDENTIAL_REDDIT", "0")
    assert sched.reddit_enabled() is False             # explicit off
