"""The public delivery sample is rendered by the engine, not maintained by hand.

This is the document a producer forwards to business affairs. Hand-typed, it had
drifted into filing usage code ``VV`` on a campaign bed — an assertion that
performers appear on camera, which nothing in this system knows, and precisely
the defect `delivery` documents having fixed. It also carried one conflated
``100%`` share, a hardcoded ``BMI`` for every writer, and ``Logo`` in a column
that only takes PRO usage codes.

A music coordinator who reads VV on a bed understands it as a claim of an
on-camera vocal performance, and then doubts every other number on the page,
including the ones that are right.

So these tests tie the published page to the builders. The suite goes red the day
`delivery.py` moves and the page does not.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from chordential_oia import delivery
from chordential_oia.web import landing
from chordential_oia.web.app import app


@pytest.fixture()
def html():
    return TestClient(app).get("/delivery-sample").text


# --------------------------------------------------------------------------- #
# The drift that was there, and must not return
# --------------------------------------------------------------------------- #

def test_it_never_files_a_visual_usage_code(html):
    """VI/VV assert a performance visible on camera. We cannot know that."""
    for code in (">VV<", ">VI<"):
        assert code not in html, f"{code} is back on the public cue sheet"


def test_usage_codes_are_ones_the_engine_actually_emits(html):
    rows = landing.sample_cue_sheet()
    allowed = {delivery.USAGE_BACKGROUND_INSTRUMENTAL, delivery.USAGE_BACKGROUND_VOCAL}
    for r in rows:
        assert r.usage in allowed, f"{r.usage} is not a code build_cue_sheet emits"
        assert f"<td>{r.usage}</td>" in html


def test_logo_is_not_presented_as_a_usage_code(html):
    assert ">Logo<" not in html


def test_writer_and_publisher_share_are_accounted_separately(html):
    """A PRO accounts the two sides separately; one 100% told it neither."""
    assert "Writer %" in html and "Pub. %" in html
    assert "<td>100%</td>" not in html, "the conflated single share column is back"


def test_the_pro_is_per_writer_not_a_house_default(html):
    """ADR-0031 made PRO per writer. The fixture carries two, deliberately."""
    rows = landing.sample_cue_sheet()
    assert "ASCAP" in rows[0].pro and "BMI" in rows[0].pro
    assert "ASCAP" in html


# --------------------------------------------------------------------------- #
# The page is the engine's output, not a copy of it
# --------------------------------------------------------------------------- #

def test_every_cue_row_on_the_page_came_from_build_cue_sheet(html):
    for r in landing.sample_cue_sheet():
        assert r.cue in html, f"cue {r.cue!r} is not on the page"
        assert r.composers in html
        assert r.publisher in html


def test_the_grant_of_rights_is_the_certificates_own_license(html):
    """Not paraphrased. The two halves — master bought out, composition publishing
    retained — appear together or the first becomes a full-buyout claim."""
    cert = landing.sample_certificate()
    for value in cert.license.values():
        assert str(value) in html, f"license term {value!r} was rewritten, not rendered"
    assert "publishing" in " ".join(cert.license.keys()).lower()


def test_the_content_id_line_is_the_honest_one_verbatim(html):
    assert landing.sample_certificate().content_id in html
    for banned in ("content-id safe", "safelist", "whitelist"):
        assert banned not in html.lower(), f"{banned!r} is a claim we do not make"


def test_no_indemnity_is_promised(html):
    """The shipping certificate carries no indemnification clause. Until it does,
    the word may not appear on a page business affairs will read."""
    assert "indemnif" not in html.lower()


def test_the_brand_is_invented_and_says_so(html):
    assert landing.SAMPLE_CLIENT in html
    assert "fictional campaign" in html.lower()
    assert "SAMPLE" in html


# --------------------------------------------------------------------------- #
# The engine fix this uncovered
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("brief,expect", [
    ("Warm acoustic bed, no vocal", delivery.USAGE_BACKGROUND_INSTRUMENTAL),
    ("Warm bed, without vocals", delivery.USAGE_BACKGROUND_INSTRUMENTAL),
    ("Anthem, non vocal", delivery.USAGE_BACKGROUND_INSTRUMENTAL),
    ("Anthem with a sung topline", delivery.USAGE_BACKGROUND_VOCAL),
    ("Choir on the hero", delivery.USAGE_BACKGROUND_VOCAL),
    ("No vocal on the :60, but a sung topline on the :30",
     delivery.USAGE_BACKGROUND_VOCAL),
])
def test_a_brief_that_rules_a_vocal_out_is_not_filed_as_vocal(brief, expect):
    """Substring matching read "no vocal" as a vocal and filed BV — the same
    species of defect as the hardcoded VV: a claim the brief actually denies."""
    got = delivery._infer_usage({"need": "Anthem", "description": brief})
    assert got == expect, f"{brief!r} -> {got}, wanted {expect}"


def test_the_sample_needs_no_database():
    """The highest-traffic public route must survive a Postgres blip, so the
    fixture is plain dicts through delivery._val and reads nothing."""
    ctx = landing.sample_context()
    assert ctx["cues"] and ctx["manifest"] and ctx["cert"]
