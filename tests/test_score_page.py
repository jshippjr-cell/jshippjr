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


# --------------------------------------------------------------------------- #
# The delivery beat lists the package the engine actually assembles
# --------------------------------------------------------------------------- #

def test_the_delivery_beat_lists_engine_derived_rows(client):
    """The beat must not describe a package build_manifest would not assemble."""
    import html as _html
    from chordential_oia.web import landing
    # unescaped: Jinja turns "Cue sheet & rights certificate" into "&amp;"
    body = _html.unescape(client.get("/score").text)
    lines = landing.sample_package_lines()
    assert lines, "the package list is empty"
    for line in lines:
        assert line["asset"] in body, f"{line['asset']!r} is not on the page"
        assert line["spec"] in body


def test_the_version_summary_is_derived_not_typed(client):
    """The count and the current label come from the same rows the package page
    renders — a hand-typed '3 versions' is a number that can go stale silently."""
    from chordential_oia.web import landing
    summary = landing.sample_package_lines()[-1]["spec"]
    assert str(len(landing.VERSIONS)) in summary
    assert (landing.VERSIONS[-1]["label"]) in summary


def test_the_delivery_beat_hands_off_to_the_package(client):
    """The scroll is the doorway; the document lives at its own address because it
    is the thing a producer forwards."""
    assert "/delivery-sample" in client.get("/score").text


# --------------------------------------------------------------------------- #
# The review beat: the mechanism, not a paragraph about the mechanism
# --------------------------------------------------------------------------- #

def test_the_review_beat_is_interactive_not_a_screenshot(client):
    """The claim is about a mechanism, and a mechanism is demonstrated by working."""
    body = client.get("/score").text
    for hook in ("revRail", "revMark", "revForm", "revList", "score-note.js"):
        assert hook in body, f"{hook} is missing — the beat is inert"


def test_the_versions_come_from_the_ladder_not_the_template(client):
    """A hand-typed version label on a pin is the same trap as a hand-typed version
    count: the pin is the one place on this page the version must be exactly right."""
    from chordential_oia.web import landing
    body = client.get("/score").text
    for v in landing.review_versions():
        assert f'data-v="{v["label"]}"' in body, f"{v['label']} is not offered"


def test_the_demo_says_nothing_is_sent(client):
    """A public text box that mimes a submit is the thing we do not build. The
    disclosure sits inside the component's own frame so it survives a screenshot
    cropped to the interaction — a footnote does not travel with a Slack paste."""
    body = client.get("/score").text
    frame = body.split('class="rev"')[1].split("</div>")[0] + body.split('id="rev"')[1][:4000]
    assert "Nothing here is sent" in frame
    assert "nothing leaves this browser" in frame


def test_the_review_demo_stores_nothing_on_the_server(client):
    """Anonymous public traffic must never reach review_comments — that table is the
    approval record, carries `verified`, and is joined by person_id. No route, no
    form action, no identity fields."""
    js = open(os.path.join(_STATIC, "score-note.js")).read()
    assert "sessionStorage" in js
    assert "fetch(" not in js and "XMLHttpRequest" not in js
    for field in ('name="email"', 'name="name"', "action="):
        assert field not in client.get("/score").text.split('id="rev"')[1][:4000]


def test_the_review_demo_survives_no_webgl2():
    """score-gl.js returns early with no WebGL2. The claim this beat makes may not
    die with the scene, so the interaction lives in its own file and touches no
    renderer state."""
    js = open(os.path.join(_STATIC, "score-note.js")).read()
    for renderer_thing in ("webgl2", "getContext", "PSTATE", "requestAnimationFrame"):
        assert renderer_thing not in js, f"the review demo reaches into the renderer ({renderer_thing})"


def test_it_never_claims_the_note_is_bound_to_a_recording(client):
    """Nothing hashes the audio. The binding is to a VERSION in the ladder, and a
    version's file can be removed while its comments survive. Say version."""
    body = client.get("/score").text.lower()
    for overstated in ("exact recording", "tamper-proof", "immutable",
                       "locked to that recording"):
        assert overstated not in body, f"'{overstated}' overstates what the product does"
