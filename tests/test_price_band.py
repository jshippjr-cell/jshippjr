"""Client-facing price band (Cycle 1.3).

The public band must come straight from the existing estimator — it brackets the
estimator's suggested price and introduces no separate pricing math.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.models import MusicDiscipline, Opportunity
from chordential_oia.estimation import build_estimate
from chordential_oia.web.evaluate import evaluate


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    from chordential_oia.web import public as public_mod
    with TestClient(app_mod.app) as c:
        yield c, db_mod, public_mod


def _suggested_for(project_type, description):
    opp = Opportunity(client="(prospect)", need=project_type, description=description)
    qual, _ = evaluate(opp)
    disc = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    return build_estimate(opp, qual.team_shape or disc.team_shape, disc).suggested_price


def test_band_brackets_estimator_suggested_price(ctx):
    _, _, public = ctx
    pt, desc = "Original :30 brand spot", "orchestral, hopeful"
    band = public.public_price_band(pt, desc)
    assert band is not None
    assert 0 < band["low"] < band["high"]
    # No divergent math: the estimator's own suggested price sits inside the band.
    suggested = _suggested_for(pt, desc)
    assert band["low"] <= suggested <= band["high"]


def test_band_rounds_to_tidy_hundreds(ctx):
    _, _, public = ctx
    band = public.public_price_band("Sonic logo", "three-note mnemonic")
    assert band["low"] % 100 == 0
    assert band["high"] % 100 == 0


def test_band_is_none_without_input(ctx):
    _, _, public = ctx
    assert public.public_price_band("", "") is None


def test_questionnaire_stores_band_internally_but_hides_it_from_client(ctx):
    client, db_mod, _ = ctx
    r = client.post(
        "/start",
        data={"contact_name": "Ivy Â", "company": "Ivy Co",
              "contact_email": "ivy@ivy.co", "phone": "555-0201",
              "project_type": "Original :30 brand spot",
              "description": "orchestral, hopeful"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers["location"]
    # The client response must NOT carry a price range (untactful at intake).
    assert "low=" not in loc and "high=" not in loc

    # …but it's still stored on the lead for the internal quoted-vs-won moat.
    conn = db_mod.connect()
    try:
        row = conn.execute(
            "SELECT * FROM inbound_leads WHERE company='Ivy Co'"
        ).fetchone()
    finally:
        conn.close()
    assert row["shown_price_low"] and row["shown_price_high"]
    assert row["shown_price_low"] < row["shown_price_high"]

    # The thank-you page shows no price band to the client.
    thanks = client.get(loc)
    assert thanks.status_code == 200
    assert "typically run" not in thanks.text


def test_internal_queue_shows_quoted_band(ctx):
    client, _, _ = ctx
    client.post(
        "/start",
        data={"contact_name": "Quote Tester", "company": "QT Co",
              "contact_email": "qt@qt.co", "phone": "555-0202",
              "project_type": "Original :30 brand spot", "description": "strings"},
    )
    q = client.get("/leads")
    assert "quoted" in q.text
