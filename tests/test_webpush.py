"""Web Push (PWA native alerts) — subscription CRUD, send fan-out + prune, routes.

Network is never touched: the per-subscription sender is monkeypatched, so these
run in the sandbox exactly as on Render (the real send is lazy-imported pywebpush).
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
    from chordential_oia.web import webpush as wp_mod
    importlib.reload(wp_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod, wp_mod


def _vapid(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_VAPID_PUBLIC", "PUBKEY")
    monkeypatch.setenv("CHORDENTIAL_VAPID_PRIVATE", "PRIVKEY")
    monkeypatch.setenv("CHORDENTIAL_VAPID_SUBJECT", "mailto:t@t.com")


def test_pwa_assets_served(ctx):
    client, _, _ = ctx
    man = client.get("/manifest.webmanifest")
    assert man.status_code == 200 and man.json()["start_url"] == "/dashboard"
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "addEventListener('push'" in sw.text
    assert client.get("/apple-touch-icon.png").status_code == 200


def test_vapid_public_reflects_env(ctx, monkeypatch):
    client, _, _ = ctx
    assert client.get("/push/vapid-public").json()["key"] == ""
    _vapid(monkeypatch)
    assert client.get("/push/vapid-public").json()["key"] == "PUBKEY"


def test_subscribe_stores_and_dedupes(ctx):
    client, db, _ = ctx
    sub = {"endpoint": "https://push.example/abc",
           "keys": {"p256dh": "k1", "auth": "a1"}}
    assert client.post("/push/subscribe", json=sub).json()["ok"] is True
    client.post("/push/subscribe", json=sub)              # same endpoint again
    conn = db.connect()
    assert db.push_subscription_count(conn) == 1           # deduped on endpoint
    # missing fields are rejected
    assert client.post("/push/subscribe", json={"endpoint": "x"}).status_code == 400


def test_send_fans_out_and_prunes_expired(ctx, monkeypatch):
    client, db, wp = ctx
    _vapid(monkeypatch)
    conn = db.connect()
    db.add_push_subscription(conn, endpoint="https://push/keep", p256dh="p", auth="a")
    db.add_push_subscription(conn, endpoint="https://push/gone", p256dh="p", auth="a")

    sent = []

    def fake_send_one(info, payload):
        sent.append(info["endpoint"])
        return 410 if info["endpoint"].endswith("gone") else 200

    monkeypatch.setattr(wp, "_send_one", fake_send_one)
    res = wp.send_web_push("hi", body="there", url="/signals")
    assert len(sent) == 2                                  # one message per device
    assert res["sent"] == 1 and res["pruned"] == 1
    conn = db.connect()
    assert db.push_subscription_count(conn) == 1           # expired one removed


def test_test_push_route_states(ctx, monkeypatch):
    client, db, wp = ctx
    # No VAPID configured → 'unset'
    r = client.post("/push/test", follow_redirects=False)
    assert "push=unset" in r.headers["location"]
    # Configured but no device subscribed → 'nosub'
    _vapid(monkeypatch)
    r = client.post("/push/test", follow_redirects=False)
    assert "push=nosub" in r.headers["location"]
    # Configured + a subscription + a successful send → 'sent'
    conn = db.connect()
    db.add_push_subscription(conn, endpoint="https://push/x", p256dh="p", auth="a")
    monkeypatch.setattr(wp, "_send_one", lambda info, payload: 200)
    r = client.post("/push/test", follow_redirects=False)
    assert "push=sent" in r.headers["location"]


def test_send_noop_when_unconfigured(ctx):
    _, _, wp = ctx
    res = wp.send_web_push("hi")                           # no VAPID env
    assert res["configured"] is False and res["sent"] == 0
