"""`held: False` meant two opposite things, and the console showed the reassuring one.

Another instance is running the engines (normal during a deploy) and NOBODY is running
them (an outage: no meeting transcript polled, no engine run) were the same state. The
banner said "running on another instance" for both — so a total stop read as routine.
"""
import pytest


@pytest.fixture(autouse=True)
def _lease_on(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_SCHEDULER_LEASE", "1")


def _sched():
    from chordential_oia.web import scheduler
    return scheduler


def test_a_database_that_cannot_be_reached_reads_as_stopped(monkeypatch):
    s = _sched()
    monkeypatch.setattr(s.db, "connect", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("could not connect")))
    assert s._claim_lease() is False
    st = s.lease_status()
    assert st["stopped"] is True, "nothing is running the engines — that is an outage"
    assert "could not connect" in st["error"]


def test_another_instance_holding_it_is_not_an_outage(monkeypatch):
    s = _sched()
    monkeypatch.setattr(s.db, "connect", lambda *a, **k: object())
    monkeypatch.setattr(s.db, "acquire_lease", lambda *a, **k: False)
    monkeypatch.setattr(s.db, "lease_holder", lambda *a, **k: {"owner": "other-instance"})
    assert s._claim_lease() is False
    st = s.lease_status()
    assert st["stopped"] is False, "standing by is normal, not an outage"
    assert not st["error"]
    assert st["holder"]["owner"] == "other-instance"


def test_no_holder_and_no_claim_is_an_outage_even_without_an_exception(monkeypatch):
    """The quiet one: the lease row cannot be claimed OR read back, nothing raised."""
    s = _sched()
    monkeypatch.setattr(s.db, "connect", lambda *a, **k: object())
    monkeypatch.setattr(s.db, "acquire_lease", lambda *a, **k: False)
    monkeypatch.setattr(s.db, "lease_holder", lambda *a, **k: None)
    assert s._claim_lease() is False
    assert s.lease_status()["stopped"] is True


def test_holding_it_is_never_an_outage(monkeypatch):
    s = _sched()
    monkeypatch.setattr(s.db, "connect", lambda *a, **k: object())
    monkeypatch.setattr(s.db, "acquire_lease", lambda *a, **k: True)
    monkeypatch.setattr(s.db, "lease_holder", lambda *a, **k: {"owner": s._OWNER})
    assert s._claim_lease() is True
    st = s.lease_status()
    assert st["held"] is True and st["stopped"] is False and not st["error"]


def test_the_dashboard_says_so_when_the_engines_are_stopped(tmp_path, monkeypatch):
    """It belongs where the day starts, not on a page you open once you suspect."""
    import importlib
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.sqlite"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    from fastapi.testclient import TestClient
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import scheduler, console_routes
    monkeypatch.setattr(console_routes.scheduler_mod, "lease_status", lambda: dict(
        held=False, holder=None, error="boom", enabled=True, ttl=90,
        owner="x", checked_at="", stopped=True))
    with TestClient(app_mod.app) as c:
        page = c.get("/dashboard").text
    assert "not running" in page.lower()
    assert "boom" in page
