"""There was no way to create an opportunity by hand.

Reported live: the operator assumed a deal he had been told about already existed, went
looking for its prep sheet, and found nothing — because nothing had created it. Every
opportunity in the system had to arrive as an inbound lead through the public intake and
then be PROMOTED. That is correct for something that came through the front door, and pure
friction for a referral, a phone call, or a test run: two pages and four steps to type in
a name.

`/opportunity/new` is one page, two required fields, and it lands you on the deal.
"""
import importlib

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "new.db"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    for m in ("db", "campaign_intelligence", "campaigns", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c


def test_the_form_serves(client):
    """It nearly did not. `/opportunity/{opp_id}` is declared first and takes an int, and
    FastAPI matches in declaration order — so with the literal route added below it,
    "new" was parsed as an id and answered 422 instead of a form. A static segment has to
    be declared above its parameterised sibling."""
    r = client.get("/opportunity/new")
    assert r.status_code == 200
    for field in ('name="client"', 'name="need"', 'name="description"',
                  'name="contact_name"', 'name="contact_email"'):
        assert field in r.text


def test_two_fields_and_you_are_on_the_deal(client):
    from chordential_oia.web import db
    r = client.post("/opportunity/new",
                    data={"client": "The Larkspur Trust",
                          "need": "Winter appeal film — original score"},
                    follow_redirects=False)
    assert r.status_code == 303
    oid = int(r.headers["location"].rsplit("/", 1)[1])
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, oid)
    finally:
        conn.close()
    assert row["client"] == "The Larkspur Trust"
    assert row["need"] == "Winter appeal film — original score"
    assert row["source"] == "manual", "so it is distinguishable from a promoted lead"


def test_the_contact_is_carried_when_given(client):
    from chordential_oia.web import db
    r = client.post("/opportunity/new",
                    data={"client": "The Larkspur Trust", "need": "Winter appeal film",
                          "contact_name": "Nadia Okonjo",
                          "contact_email": "nadia@larkspur.example"},
                    follow_redirects=False)
    conn = db.connect()
    try:
        row = db.get_opportunity(conn, int(r.headers["location"].rsplit("/", 1)[1]))
    finally:
        conn.close()
    assert row["contact_name"] == "Nadia Okonjo"
    assert row["contact_email"] == "nadia@larkspur.example"


def test_a_buyer_and_a_title_are_the_only_requirements(client):
    """Budget, timeline and deliverables are what the discovery call is FOR. Demanding
    them on this form would collect guesses made at the moment you know least."""
    r = client.get("/opportunity/new")
    assert "come from the call" in r.text
    for never_asked in ('name="budget', 'name="deadline"', 'name="deliverables"'):
        assert never_asked not in r.text


@pytest.mark.parametrize("data", [
    {"client": "", "need": "A film"},
    {"client": "Larkspur", "need": ""},
    {"client": "   ", "need": "   "},
])
def test_a_half_filled_form_comes_back_rather_than_creating_a_ghost(client, data):
    from chordential_oia.web import db

    def count():
        conn = db.connect()
        try:
            return conn.execute("SELECT COUNT(*) c FROM opportunities").fetchone()["c"]
        finally:
            conn.close()

    before = count()          # the app seeds demo rows at boot; measure the DELTA
    r = client.post("/opportunity/new", data=data, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/opportunity/new?err=missing"
    assert count() == before, "a half-filled form must not leave a ghost behind"


def test_the_error_is_readable_on_the_page(client):
    assert "A buyer and a title" in client.get("/opportunity/new?err=missing").text


def test_it_is_reachable_from_the_opportunity_list(client):
    """A form nobody can find is the same as no form, which is how this went unnoticed."""
    page = client.get("/inbox").text
    assert "/opportunity/new" in page and "Add a deal" in page


def test_the_new_deal_goes_straight_to_a_usable_page(client):
    """Straight to the deal, ready to schedule the call — the whole point of skipping the
    promote dance."""
    r = client.post("/opportunity/new",
                    data={"client": "The Larkspur Trust", "need": "Winter appeal film"},
                    follow_redirects=False)
    oid = int(r.headers["location"].rsplit("/", 1)[1])
    detail = client.get(f"/opportunity/{oid}").text
    assert "The Larkspur Trust" in detail
    assert f"/opportunity/{oid}/schedule" in detail, "book the call from here"
