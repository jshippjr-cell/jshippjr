"""Payment gate on deliverable downloads.

A client can stream/preview the work to review it, but cannot DOWNLOAD the
deliverables (ZIP + per-asset masters) until paid in full — or until Jon manually
unlocks the delivery. The operator (Jon) downloads freely to inspect the package.
Preview streaming on /uploads is never gated.
"""

import hashlib
import importlib
import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "secret")  # gate ON → real op/client split
    os.makedirs(tmp_path / "uploads", exist_ok=True)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod, str(tmp_path / "uploads")


ADMIN_COOKIE = {"cdl_admin": hashlib.sha256(b"cdl|secret").hexdigest()}


def _setup(db_mod, upload_dir, *, invoice_status="Issued"):
    """Project + share token + a zip/audio file + a Final invoice. Returns
    (project_id, share_token, invoice_id)."""
    conn = db_mod.connect()
    try:
        pid = db_mod.insert_project(conn, None, "AURORA", "Anthem", 0, 5000,
                                    ["Composer"], None)
        tok = db_mod.ensure_project_share_token(conn, pid)
        open(os.path.join(upload_dir, "AURORA_Delivery.zip"), "wb").write(b"PKzip")
        open(os.path.join(upload_dir, f"proj{pid}-v1.mp3"), "wb").write(b"ID3a")
        iid = conn.execute(
            "INSERT INTO invoices (project_id, kind, status, amount, created_at) "
            "VALUES (?,?,?,?,?)", (pid, "Final", invoice_status, 5000, "x")).lastrowid
        conn.commit()
    finally:
        conn.close()
    return pid, tok, iid


def test_streaming_preview_is_never_gated(ctx):
    client, db_mod, up = ctx
    pid, tok, _ = _setup(db_mod, up)
    # Audio preview on /uploads serves even while unpaid (client must review).
    r = client.get(f"/uploads/proj{pid}-v1.mp3")
    assert r.status_code == 200


def test_zip_is_blocked_on_uploads_route(ctx):
    client, db_mod, up = ctx
    _setup(db_mod, up)
    # The ZIP is never served from /uploads — closes the deterministic-name backdoor.
    # (admin gate ON + no cookie → redirect to login, also not the file)
    r = client.get("/uploads/AURORA_Delivery.zip", follow_redirects=False)
    assert r.status_code in (404, 303)
    if r.status_code == 303:
        assert "/admin/login" in r.headers["location"]


def test_client_download_blocked_until_paid(ctx):
    client, db_mod, up = ctx
    pid, tok, iid = _setup(db_mod, up)
    # Unpaid → 402 Payment Required.
    r = client.get(f"/project/{pid}/dl/AURORA_Delivery.zip?k={tok}")
    assert r.status_code == 402
    # Pay in full → unlocks.
    client.post(f"/invoice/{iid}/status", data={"status": "Paid"}, cookies=ADMIN_COOKIE)
    r = client.get(f"/project/{pid}/dl/AURORA_Delivery.zip?k={tok}")
    assert r.status_code == 200


def test_bad_token_is_not_found(ctx):
    client, db_mod, up = ctx
    pid, tok, _ = _setup(db_mod, up)
    # Wrong token + no admin cookie → 404 (no leak of existence/state).
    r = client.get(f"/project/{pid}/dl/AURORA_Delivery.zip?k=wrong")
    assert r.status_code == 404


def test_operator_downloads_freely(ctx):
    client, db_mod, up = ctx
    pid, tok, _ = _setup(db_mod, up)
    # Jon (admin cookie, no client token) downloads the unpaid package to inspect it.
    r = client.get(f"/project/{pid}/dl/AURORA_Delivery.zip", cookies=ADMIN_COOKIE)
    assert r.status_code == 200


def test_operator_override_unlock_and_relock(ctx):
    client, db_mod, up = ctx
    pid, tok, _ = _setup(db_mod, up)
    assert client.get(f"/project/{pid}/dl/AURORA_Delivery.zip?k={tok}").status_code == 402
    client.post(f"/project/{pid}/delivery/unlock", data={"unlock": "1"}, cookies=ADMIN_COOKIE)
    assert client.get(f"/project/{pid}/dl/AURORA_Delivery.zip?k={tok}").status_code == 200
    client.post(f"/project/{pid}/delivery/unlock", data={"unlock": "0"}, cookies=ADMIN_COOKIE)
    assert client.get(f"/project/{pid}/dl/AURORA_Delivery.zip?k={tok}").status_code == 402


def test_balance_helper(ctx):
    client, db_mod, up = ctx
    pid, tok, iid = _setup(db_mod, up)
    conn = db_mod.connect()
    try:
        b = db_mod.invoice_balance(conn, pid)
        assert b["outstanding"] == 5000 and not b["paid_in_full"]
    finally:
        conn.close()
    client.post(f"/invoice/{iid}/status", data={"status": "Paid"}, cookies=ADMIN_COOKIE)
    conn = db_mod.connect()
    try:
        b = db_mod.invoice_balance(conn, pid)
        assert b["outstanding"] == 0 and b["paid_in_full"]
    finally:
        conn.close()
