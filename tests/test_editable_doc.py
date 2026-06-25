"""Editable client document — synopsis, delivery templates, overrides, chips,
and the per-deal save endpoints (the backend half of the feature)."""

import importlib

import pytest

from chordential_oia.capabilities import (
    DELIVERY_TEMPLATES, SUPPORT_CHIPS, build_capabilities_doc, build_understanding,
    chips_for, default_toggles, pick_delivery_template,
)
from chordential_oia.models import MusicDiscipline, Opportunity
from chordential_oia.web.estimate import build_estimate
from chordential_oia.web.evaluate import evaluate


def _opp(need, description=""):
    return Opportunity(client="Acme", need=need, description=description,
                       budget_min=12000, budget_max=12000)


def _doc(opp, status="Submitted", overrides=None, **toggle):
    qual, _ = evaluate(opp)
    disc = qual.discipline if qual.qualified else MusicDiscipline.COMPOSITION
    est = build_estimate(opp, qual.team_shape or disc.team_shape, disc)
    toggles = default_toggles(status)
    toggles.update(toggle)
    return build_capabilities_doc(opp, qual, est, toggles=toggles, overrides=overrides)


# --- understanding synopsis (client-facing, no scoring jargon) --------------- #
def test_understanding_is_client_facing_no_jargon():
    text = build_understanding(_opp("Original :30 brand spot music"))
    assert "aligned" not in text.lower()
    assert "review" not in text.lower()
    assert "%" not in text
    assert text.lower().startswith("you")


def test_understanding_handles_empty_need():
    # never crashes / never empty even with a bare lead
    assert build_understanding(Opportunity(client="X", need="")).strip()


def test_doc_understanding_is_not_fit_summary():
    opp = _opp("Original :30 brand spot music",
               "Original composition for a national TV spot.")
    qual, _ = evaluate(opp)
    doc = _doc(opp)
    assert doc.understanding != qual.fit_summary
    assert "Review" not in doc.understanding


# --- delivery-template selection -------------------------------------------- #
def test_film_lead_picks_film_tv():
    assert pick_delivery_template(
        _opp("Music producer for an indie feature film",
             "Scoring an independent feature.")) == "film_tv"


def test_brand_spot_picks_campaign():
    assert pick_delivery_template(
        _opp("Original :30 brand spot", "National advertising campaign.")) == "campaign"


def test_sonic_and_artist_picks():
    assert pick_delivery_template(_opp("Sonic logo / mnemonic identity")) == "sonic"
    assert pick_delivery_template(_opp("Produce a single / song for an artist")) == "artist"


def test_unknown_defaults_to_campaign():
    assert pick_delivery_template(_opp("Something unclassifiable")) == "campaign"


def test_film_doc_has_no_ad_cutdowns():
    opp = _opp("Music producer for an indie feature film",
               "Scoring an independent feature, ~25 cues to picture.")
    doc = _doc(opp, delivery=True)
    assert doc.delivery_template == "film_tv"
    assert doc.show_delivery is True
    blob = " ".join(f"{d.asset} {d.spec}" for d in doc.deliverables).lower()
    assert ":30" not in blob and "cutdown" not in blob
    assert any("picture" in d.asset.lower() for d in doc.deliverables)
    assert doc.rollout == []        # a film doesn't get an ad rollout map
    assert "feature-film" in doc.delivery_assumptions


# --- overrides apply and reset ---------------------------------------------- #
def test_client_override_applies_and_resets():
    opp = _opp("Original :30 brand spot")
    assert _doc(opp).client == "Acme"
    assert _doc(opp, overrides={"client": "Globex Films"}).client == "Globex Films"
    # clearing falls back to the generated default
    assert _doc(opp, overrides={}).client == "Acme"


def test_delivery_template_override_wins():
    opp = _opp("Original :30 brand spot")     # auto would be campaign
    doc = _doc(opp, delivery=True, overrides={"delivery_template": "film_tv"})
    assert doc.delivery_template == "film_tv"
    assert doc.delivery_template_label == DELIVERY_TEMPLATES["film_tv"]["label"]


def test_assumptions_override_wins():
    doc = _doc(_opp("brand spot"), delivery=True,
               overrides={"delivery_assumptions": "Custom assumption."})
    assert doc.delivery_assumptions == "Custom assumption."


# --- chip library ----------------------------------------------------------- #
def test_chips_for_filters_deliverable_by_template():
    film = {c["label"] for c in chips_for("deliverables", "film_tv")}
    campaign = {c["label"] for c in chips_for("deliverables", "campaign")}
    assert "Cues to picture" in film and "Cues to picture" not in campaign
    assert "Multi-format cutdowns" in campaign and "Multi-format cutdowns" not in film
    # universal deliverable chip is in both
    assert "Stems for flexibility" in film and "Stems for flexibility" in campaign


def test_chips_for_craft_is_universal_regardless_of_template():
    a = {c["label"] for c in chips_for("understanding", "film_tv")}
    b = {c["label"] for c in chips_for("understanding", "campaign")}
    assert a == b and "Original composition" in a


def test_support_chip_library_shape():
    fams = {c["family"] for c in SUPPORT_CHIPS}
    assert fams == {"craft", "aesthetic", "deliverable", "assurance"}
    # only deliverable chips are template-scoped
    for c in SUPPORT_CHIPS:
        if c["family"] != "deliverable":
            assert c["templates"] is None


# --- save endpoints persist into doc_overrides ------------------------------ #
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c


def _overrides(tmp_db):
    from chordential_oia.web import db
    conn = db.connect()
    try:
        return db.get_doc_overrides(conn, 1)
    finally:
        conn.close()


def test_field_endpoint_persists_and_resets(client, monkeypatch):
    from chordential_oia.web import db
    r = client.post("/opportunity/1/doc/field",
                    data={"name": "client", "value": "Globex"}, follow_redirects=False)
    assert r.status_code == 303 and "edit=1" in r.headers["location"]
    conn = db.connect()
    try:
        assert db.get_doc_overrides(conn, 1)["client"] == "Globex"
        # blank value resets the field
        client.post("/opportunity/1/doc/field", data={"name": "client", "value": ""})
        assert "client" not in db.get_doc_overrides(conn, 1)
    finally:
        conn.close()


def test_chip_endpoint_persists(client):
    from chordential_oia.web import db
    client.post("/opportunity/1/doc/chip", data={
        "section": "assurance", "action": "add",
        "label": "Full buyout", "sentence": "You own it."})
    conn = db.connect()
    try:
        ov = db.get_doc_overrides(conn, 1)
        assert ov["support_chips"]["assurance"][0]["label"] == "Full buyout"
    finally:
        conn.close()
    # remove it
    client.post("/opportunity/1/doc/chip", data={
        "section": "assurance", "action": "remove",
        "label": "Full buyout", "sentence": "You own it."})
    conn = db.connect()
    try:
        assert "support_chips" not in db.get_doc_overrides(conn, 1)
    finally:
        conn.close()


def test_link_endpoint_persists(client):
    from chordential_oia.web import db
    client.post("/opportunity/1/doc/link", data={
        "action": "add", "label": "Reel", "url": "https://example.com/track"})
    conn = db.connect()
    try:
        ov = db.get_doc_overrides(conn, 1)
        assert ov["relevant_links"][0]["url"] == "https://example.com/track"
    finally:
        conn.close()


def test_custom_chip_endpoint_persists(client):
    from chordential_oia.web import db
    client.post("/chips/custom", data={
        "family": "craft", "label": "Bespoke", "sentence": "A bespoke score."})
    conn = db.connect()
    try:
        rows = db.list_custom_chips(conn)
        assert any(r["label"] == "Bespoke" for r in rows)
    finally:
        conn.close()


def test_capabilities_route_still_renders_with_edit_flag(client):
    page = client.get("/opportunity/1/capabilities?edit=1")
    assert page.status_code == 200
    assert "Capabilities" in page.text
