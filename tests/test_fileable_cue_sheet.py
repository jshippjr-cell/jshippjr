"""A cue sheet a PRO would actually accept.

The launch review reproduced this: with assignments ``[Composer: Maya Chen,
Mixer: Leo Park]`` the generated sheet read ``composers='Maya Chen, Leo Park'`` —
a mix engineer filed as an author of the composition. It also carried one "100%"
share column (writer and publisher share are separate accounts), hardcoded BMI for
every writer, and hardcoded the main cue's usage to ``VV`` — Visual Vocal, which
asserts a sung performance visible on camera, for every campaign bed we ship.

The composer column is a legal claim the PRO pays royalties on. It has to be true.
"""

import csv
import io

import pytest

from chordential_oia.delivery import (
    DEFAULT_PRO, USAGE_BACKGROUND_INSTRUMENTAL, USAGE_BACKGROUND_VOCAL,
    build_cue_sheet, cue_sheet_csv,
)

PROJECT = {"need": "Original :30 brand spot for the Vance Athletic launch",
           "client": "Vance Athletic", "description": ""}
CREW = [
    {"role": "Composer", "talent_name": "Maya Chen", "talent_pro": "ASCAP"},
    {"role": "Mixer", "talent_name": "Leo Park", "talent_pro": None},
    {"role": "Music Editor", "talent_name": "Ana Ruiz", "talent_pro": None},
    {"role": "Project Manager", "talent_name": "Sam Diaz", "talent_pro": None},
]


def test_only_writers_are_credited_as_composers():
    """The reproduction from the review, exactly."""
    for row in build_cue_sheet(PROJECT, CREW):
        assert row.composers == "Maya Chen"
        for non_writer in ("Leo Park", "Ana Ruiz", "Sam Diaz"):
            assert non_writer not in row.composers, (
                f"{non_writer} is filed as an author of the composition")


def test_writer_roles_beyond_composer_still_count():
    """Arrangers, orchestrators and toplines author the work too — the fix must
    not swing to crediting the composer alone."""
    crew = [
        {"role": "Composer", "talent_name": "Maya Chen", "talent_pro": "ASCAP"},
        {"role": "Topline", "talent_name": "Rae Iyer", "talent_pro": "PRS"},
        {"role": "Mixer", "talent_name": "Leo Park", "talent_pro": None},
    ]
    row = build_cue_sheet(PROJECT, crew)[0]
    assert row.composers == "Maya Chen, Rae Iyer"
    assert "Leo Park" not in row.composers


def test_writer_and_publisher_shares_are_separate_accounts():
    """One "100%" column told the PRO either nothing or something impossible.
    Two writers split the writer share; the publisher's share is its own."""
    solo = build_cue_sheet(PROJECT, CREW)[0]
    assert solo.writer_share == "100%"
    assert solo.publisher_share == "100%"

    duo = build_cue_sheet(PROJECT, CREW + [
        {"role": "Arranger", "talent_name": "Rae Iyer", "talent_pro": "PRS"}])[0]
    assert duo.writer_share == "50%", "two writers must split the writer share"
    assert duo.publisher_share == "100%", "the publisher share is not split by writers"


def test_pro_is_per_writer_not_a_house_constant():
    """Every writer on every sheet was declared BMI regardless of affiliation."""
    row = build_cue_sheet(PROJECT, CREW)[0]
    assert row.pro == "ASCAP", "the writer's own PRO must be filed"

    both = build_cue_sheet(PROJECT, CREW + [
        {"role": "Arranger", "talent_name": "Rae Iyer", "talent_pro": "PRS"}])[0]
    assert both.pro == "ASCAP, PRS"


def test_an_unknown_pro_is_left_blank_rather_than_asserted():
    """Blank is honest; a guess is a false filing."""
    row = build_cue_sheet(PROJECT, [
        {"role": "Composer", "talent_name": "Unknown Writer", "talent_pro": None}])[0]
    assert row.pro == "", f"asserted {row.pro!r} for a writer whose PRO we do not know"


def test_usage_never_claims_a_visual_performance():
    """The main cue was hardcoded VV — Visual Vocal — which says performers are
    singing on camera. Nothing in this system knows that."""
    for row in build_cue_sheet(PROJECT, CREW):
        assert row.usage in (USAGE_BACKGROUND_INSTRUMENTAL, USAGE_BACKGROUND_VOCAL)
        assert not row.usage.startswith("V"), "a visual usage code was claimed"


def test_usage_follows_whether_the_brief_has_a_vocal():
    instrumental = build_cue_sheet(PROJECT, CREW)[0]
    assert instrumental.usage == USAGE_BACKGROUND_INSTRUMENTAL

    vocal = build_cue_sheet(
        dict(PROJECT, need="Original :60 anthem with a vocal topline"), CREW)[0]
    assert vocal.usage == USAGE_BACKGROUND_VOCAL


def test_the_operator_can_override_usage_per_cue():
    """Only a human knows whether the spot puts a band on camera."""
    delivery = {"cue_meta": {PROJECT["need"]: {"usage": "VV"}}}
    row = build_cue_sheet(PROJECT, CREW, delivery=delivery)[0]
    assert row.usage == "VV"


def test_the_house_stands_in_when_no_writer_is_assigned():
    """A cue still has to account to somebody — but never to a mixer."""
    rows = build_cue_sheet(PROJECT, [
        {"role": "Mixer", "talent_name": "Leo Park", "talent_pro": None}])
    assert rows[0].composers == "Chordential"
    assert rows[0].pro == DEFAULT_PRO


def test_the_csv_carries_both_share_columns():
    """The CSV is the machine-fileable artefact a coordinator submits."""
    text = cue_sheet_csv(PROJECT, CREW)
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    assert "Writer Share%" in header and "Publisher Share%" in header
    assert "Share%" not in header, "the conflated single share column is back"

    body = rows[1]
    idx = {name: i for i, name in enumerate(header)}
    assert body[idx["Composer"]] == "Maya Chen"
    assert body[idx["PRO"]] == "ASCAP"
    assert body[idx["Writer Share%"]] == "100%"
