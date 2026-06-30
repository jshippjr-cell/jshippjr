"""Revenue dashboard — the CRO's home screen (cash, A/R, pipeline, funnel).

Read-only rollup computed from existing data; the number that matters is cash
collected.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def _seed_money(db_mod):
    conn = db_mod.connect()
    try:
        pid = db_mod.insert_project(conn, None, "AURORA", "Anthem", 0, 10000,
                                    ["Composer"], None)
        conn.execute(
            "INSERT INTO invoices (project_id,kind,status,amount,created_at,paid_at) "
            "VALUES (?,?,?,?,?,?)", (pid, "Deposit", "Paid", 5000, "2026-06-01", "2026-06-02"))
        conn.execute(
            "INSERT INTO invoices (project_id,kind,status,amount,created_at) "
            "VALUES (?,?,?,?,?)", (pid, "Final", "Issued", 5000, "2026-06-10"))
        conn.commit()
    finally:
        conn.close()
    return pid


def test_empty_summary_is_zeroed(ctx):
    _, db_mod = ctx
    conn = db_mod.connect()
    try:
        s = db_mod.revenue_summary(conn)
    finally:
        conn.close()
    assert s["collected"] == 0
    assert s["outstanding"] == 0
    assert s["funnel"]["paid_in_full"] == 0


def test_summary_counts_cash_and_ar(ctx):
    _, db_mod = ctx
    _seed_money(db_mod)
    conn = db_mod.connect()
    try:
        s = db_mod.revenue_summary(conn)
        assert s["collected"] == 5000
        assert s["deposits_paid"] == 5000
        assert s["outstanding"] == 5000          # the Issued final
        assert s["funnel"]["deposits_collected"] == 1
        outstanding = db_mod.list_outstanding_invoices(conn)
        assert len(outstanding) == 1 and outstanding[0]["kind"] == "Final"
        payments = db_mod.recent_payments(conn)
        assert len(payments) == 1 and payments[0]["amount"] == 5000
    finally:
        conn.close()


def test_paid_in_full_counts_only_settled_projects(ctx):
    _, db_mod = ctx
    pid = _seed_money(db_mod)  # deposit paid, final outstanding → NOT paid in full
    conn = db_mod.connect()
    try:
        assert db_mod.revenue_summary(conn)["funnel"]["paid_in_full"] == 0
        # Settle the final.
        conn.execute("UPDATE invoices SET status='Paid' WHERE project_id=? AND kind='Final'",
                     (pid,))
        conn.commit()
        assert db_mod.revenue_summary(conn)["funnel"]["paid_in_full"] == 1
    finally:
        conn.close()


def test_revenue_page_renders(ctx):
    client, db_mod = ctx
    _seed_money(db_mod)
    r = client.get("/revenue")
    assert r.status_code == 200
    assert "Cash collected" in r.text
    assert "Conversion funnel" in r.text
