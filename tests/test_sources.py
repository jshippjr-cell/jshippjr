"""Source Health — attribution, the live activity/cost table, and per-source test."""

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
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod


def test_source_for_sender_attribution():
    from chordential_oia.web import sources
    assert sources.source_for_sender("jobs@mandy.com") == "mandy"
    assert sources.source_for_sender("noreply@productionhub.com") == "productionhub"
    assert sources.source_for_sender("alerts@soundbetter.com") == "soundbetter"
    assert sources.source_for_sender("someone@gmail.com") == "gmail"   # unrecognized


def test_health_rows_buckets_and_status():
    from chordential_oia.web import sources

    class Row(dict):
        def __getitem__(self, k):
            return self.get(k)

    now_iso = "2999-01-01T00:00:00+00:00"
    activity = [
        Row(source="reddit-forhire", last_found=now_iso, total=3, recent=3),  # → reddit
        Row(source="mandy", last_found=now_iso, total=1, recent=1),
        Row(source="paste", last_found=now_iso, total=5, recent=5),           # → other
    ]
    costs = {"soundbetter": Row(source_key="soundbetter", monthly_cost=29.99, notes="")}
    health = sources.health_rows(activity, costs)
    by_key = {r["key"]: r for r in health["rows"]}
    assert by_key["reddit"]["total"] == 3 and by_key["reddit"]["status"] == "Receiving"
    assert by_key["mandy"]["received"] is True
    assert by_key["agency"]["status"] == "No leads yet"      # never connected → honest
    assert by_key["soundbetter"]["cost"] == 29.99
    assert health["total_monthly_cost"] == 29.99
    assert health["other"]["total"] == 5                     # paste bucketed to Other


def test_sources_page_and_cost_and_test(ctx):
    client, db = ctx
    r = client.get("/sources")
    assert r.status_code == 200
    assert "Source Health" in r.text and "Not a music lead source" in r.text  # Behance flagged

    # Enter a monthly cost — persists and totals.
    client.post("/sources/cost", data={"source_key": "soundbetter", "monthly_cost": "$29.99"})
    assert "29.99" in client.get("/sources").text

    # Test-inject a lead → that source's last-lead updates; clearing removes it.
    client.post("/sources/test", data={"source_key": "productionhub"}, follow_redirects=False)
    page = client.get("/sources").text
    assert "just now" in page
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM signals WHERE notes='source-test'").fetchone()[0] == 1
    client.post("/sources/cleartests")
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM signals WHERE notes='source-test'").fetchone()[0] == 0


def test_sources_page_lists_recommended_channels(ctx):
    client, _ = ctx
    page = client.get("/sources").text
    assert "r/gameDevClassifieds" in page          # reddit recs
    assert "Work With Indies" in page              # discord recs
