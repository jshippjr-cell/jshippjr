"""Agentic Gmail triage (Phase B1) — orchestration, gated landing, idempotency.

Network and the LLM are never touched: a fake Gmail object and a fake extractor
are injected, so these run in the sandbox exactly as on Render (the real Gmail
client + Anthropic call are lazy-imported only by the default code path).
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import signals as sig_mod
    importlib.reload(sig_mod)
    from chordential_oia.web import triage as tri_mod
    importlib.reload(tri_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod, tri_mod


class FakeGmail:
    """Stands in for web.gmail_client — configured, with a fixed inbox."""

    def __init__(self, messages):
        self._messages = {m["id"]: m for m in messages}
        self.processed = []

    def is_configured(self):
        return True

    def list_candidates(self, limit=25):
        return [{"id": mid} for mid in self._messages]

    def get_message(self, mid):
        return self._messages[mid]

    def mark_processed(self, mid):
        self.processed.append(mid)
        return True


_INBOX = [
    {"id": "m1", "sender": "alerts@mandy.com", "subject": "Composer for ad",
     "body": "Agency needs original music for a national spot, $8000."},
    {"id": "m2", "sender": "noreply@news.com", "subject": "Weekly newsletter",
     "body": "Industry headlines and gossip."},
]


def _fake_extractor(message):
    """Real gig → structured record; anything else → not an opportunity."""
    if "Composer" in message["subject"]:
        return {
            "is_opportunity": True, "title": "Composer for national ad",
            "client": "BigAgency", "budget": "$8000", "location": "Remote",
            "contact": "alerts@mandy.com", "summary": message["body"],
        }
    return {"is_opportunity": False, "title": "", "client": "", "budget": "",
            "location": "", "contact": "", "summary": ""}


def test_triage_lands_opportunities_and_skips_noise(ctx):
    _, db, tri = ctx
    gmail = FakeGmail(_INBOX)
    conn = db.connect()
    res = tri.run_triage(conn, gmail=gmail, extractor=_fake_extractor)

    assert res == {"configured": True, "scanned": 2, "created": 1, "skipped": 1}
    rows = db.list_signals(db.connect())
    assert len(rows) == 1
    assert rows[0]["source"] == "gmail"
    assert "Composer" in rows[0]["title"]
    assert rows[0]["external_ref"] == "gmail:m1"
    assert set(gmail.processed) == {"m1", "m2"}        # both leave the queue


def test_triage_is_idempotent(ctx):
    """A second run over the same inbox creates no duplicates — dedup on the
    Gmail id skips already-landed mail before the extractor is even called."""
    _, db, tri = ctx
    gmail = FakeGmail(_INBOX)
    conn = db.connect()
    tri.run_triage(conn, gmail=gmail, extractor=_fake_extractor)

    calls = []

    def counting_extractor(message):
        calls.append(message["id"])
        return _fake_extractor(message)

    res2 = tri.run_triage(db.connect(), gmail=gmail, extractor=counting_extractor)
    assert res2["created"] == 0                          # nothing new
    assert "m1" not in calls                             # landed gig never re-extracted
    assert db.push_subscription_count is not None        # sanity: module intact
    assert len(db.list_signals(db.connect())) == 1       # still one signal


def test_triage_noop_when_gmail_unconfigured(ctx):
    _, db, tri = ctx

    class Unconfigured:
        def is_configured(self):
            return False

    res = tri.run_triage(db.connect(), gmail=Unconfigured())
    assert res == {"configured": False, "scanned": 0, "created": 0, "skipped": 0}


def test_triage_run_route_redirects(ctx, monkeypatch):
    client, _, tri = ctx
    called = {}
    monkeypatch.setattr(tri, "run_triage", lambda conn, **kw: called.setdefault("ran", True))
    r = client.post("/triage/run", follow_redirects=False)
    assert r.status_code == 303 and "triage=1" in r.headers["location"]
    assert called.get("ran")
