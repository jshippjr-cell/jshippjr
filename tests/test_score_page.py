"""The notation world survives as a real route, with its scene beside it.

The page is one HTML template plus three static assets. The failure this file
exists to prevent is the quiet one: the template ships, the scene does not, and
the page renders a blank cream rectangle that looks deliberate. Every assertion
here ties a reference in the markup to a file on disk.

It also pins the ADR-0040 boundary. This page has no audio, so it is NOT the
front door — `/` must keep serving the Commission until the listening beat is
built. `test_hear_the_work.py` guards the homepage's music; this guards the
assumption that the world page has not quietly taken its place.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from chordential_oia.web.app import app

_WEB = os.path.dirname(os.path.abspath(__import__(
    "chordential_oia.web.public", fromlist=["public"]).__file__))
_STATIC = os.path.join(_WEB, "static", "public")


@pytest.fixture()
def client():
    return TestClient(app)


def test_the_score_page_renders(client):
    r = client.get("/score")
    assert r.status_code == 200
    assert "every part in the air" in r.text


def test_it_carries_the_copy_not_just_the_picture(client):
    """The words say everything the picture does — that is the no-WebGL2 promise."""
    body = client.get("/score").text
    for line in (
        "Every note",
        "Every campaign begins with understanding.",
        "Everything arrives together.",
        "Start with a brief",
    ):
        assert line in body, line


def test_the_scene_assets_the_page_asks_for_actually_exist(client):
    """The markup names three files. All three must be on disk and non-empty."""
    body = client.get("/score").text
    for name in ("score-gl.js", "score-scene.json", "score-scene.bin"):
        assert name in body, f"{name} is not referenced by the page"
        path = os.path.join(_STATIC, name)
        assert os.path.exists(path), f"{name} is referenced but missing"
        assert os.path.getsize(path) > 0, f"{name} is empty"


def test_the_scene_binary_matches_the_offsets_its_metadata_claims():
    """A truncated buffer draws nothing and raises nothing — check the arithmetic."""
    meta = json.load(open(os.path.join(_STATIC, "score-scene.json")))
    size = os.path.getsize(os.path.join(_STATIC, "score-scene.bin"))
    need = meta["offPieces"] + meta["nPieces"] * 4 * 4
    assert size >= need, f"scene.bin is {size}B, offsets need {need}B"
    assert meta["nPieces"] > 0 and meta["nMarks"] > 0


def test_the_renderer_is_served_by_us(client):
    """Same-origin, like every other asset — nothing on this page comes from a CDN."""
    body = client.get("/score").text
    assert "/static/public/score-gl.js" in body
    assert "http://" not in body.split("<style>")[0]


def test_the_score_page_is_not_the_front_door(client):
    """ADR-0040: the front door plays music. This page has none, so it may not
    take `/` until the listening beat exists. Delete this test when it does."""
    home = client.get("/").text
    assert "every part in the air" not in home
    assert "<audio" in home, "the front door lost its music"
