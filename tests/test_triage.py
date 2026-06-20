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
    assert rows[0]["source"] == "mandy"        # attributed by sender (alerts@mandy.com)
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


# --- B2: autonomous path fires a phone alert per landed gig ------------------ #
def test_notify_fires_on_landed_gig(ctx, monkeypatch):
    _, db, tri = ctx
    fired = []
    monkeypatch.setattr(tri.signals, "notify_new_gig",
                        lambda title, url="": fired.append(title))
    res = tri.run_triage(db.connect(), notify=True,
                         gmail=FakeGmail(_INBOX), extractor=_fake_extractor)
    assert res["created"] == 1
    assert len(fired) == 1 and "Composer" in fired[0]   # only the real gig alerts


def test_scheduler_triage_gating_and_cycle(ctx, monkeypatch):
    _, db, tri = ctx
    from chordential_oia.web import scheduler
    importlib.reload(scheduler)

    monkeypatch.delenv("CHORDENTIAL_TRIAGE_ENABLED", raising=False)
    assert scheduler.triage_enabled() is False             # off by default
    monkeypatch.setenv("CHORDENTIAL_TRIAGE_ENABLED", "1")
    assert scheduler.triage_enabled() is False             # enabled but not configured
    monkeypatch.setattr(tri, "is_configured", lambda: True)
    assert scheduler.triage_enabled() is True              # enabled + configured

    monkeypatch.setattr(tri, "run_triage", lambda conn, **kw: {"created": 2})
    assert scheduler.run_triage_cycle() == 2               # cycle wires to run_triage


# --- B3: every human verdict on a triaged gig is a labeled example ----------- #
def test_record_feedback_writes_only_for_triaged(ctx, tmp_path, monkeypatch):
    import json
    _, db, tri = ctx
    labels = tmp_path / "labels.jsonl"
    monkeypatch.setenv("CHORDENTIAL_TRIAGE_LABELS", str(labels))
    conn = db.connect()

    sid = db.insert_signal(conn, source="gmail", source_weight=7, title="Gig",
                           body="agency music brief", external_ref="gmail:x",
                           score=60, tier="B")
    tri.record_feedback(db.get_signal(conn, sid), "promoted")
    rec = json.loads(labels.read_text().strip())
    assert rec["human_verdict"] == "promoted" and rec["agreement"] is True

    # A non-triaged (e.g. RSS) signal is not a triage label → no-op.
    sid2 = db.insert_signal(conn, source="rss", source_weight=6, title="X",
                            external_ref="rss:1", score=1, tier="C")
    assert tri.record_feedback(db.get_signal(conn, sid2), "dismissed") is None


def test_dismiss_route_records_false_positive(ctx, tmp_path, monkeypatch):
    client, db, _ = ctx
    labels = tmp_path / "labels.jsonl"
    monkeypatch.setenv("CHORDENTIAL_TRIAGE_LABELS", str(labels))
    conn = db.connect()
    sid = db.insert_signal(conn, source="gmail", source_weight=7, title="Gig",
                           body="b", external_ref="gmail:y", score=50, tier="B")
    r = client.post(f"/signals/{sid}/status", data={"status": "Dismissed"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert labels.exists() and '"human_verdict": "dismissed"' in labels.read_text()
