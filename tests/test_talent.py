"""Tests for the Talent domain model (supply-side foundation)."""

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import (
    InviteStatus,
    ReviewStatus,
    Talent,
    normalize_url,
    profile_completeness,
)


def test_normalize_url_assumes_https_when_scheme_is_missing():
    """Reported live: entering "chordential.com/reel" as a demo reel URL was
    rejected as "not a URL" (the admin form's HTML5 type="url" input
    demands an explicit scheme), and even where it got through, a scheme-
    less value stored as-is renders as a RELATIVE link — <a
    href="chordential.com/reel"> resolves against the CURRENT page, not the
    external site, so the link "goes nowhere." Assuming https:// when no
    scheme is present fixes both."""
    assert normalize_url("chordential.com/reel") == "https://chordential.com/reel"
    assert normalize_url("www.example.com") == "https://www.example.com"


def test_normalize_url_leaves_an_explicit_scheme_alone():
    assert normalize_url("https://chordential.com/reel") == "https://chordential.com/reel"
    assert normalize_url("http://example.com") == "http://example.com"


def test_normalize_url_blank_becomes_none():
    assert normalize_url("") is None
    assert normalize_url("   ") is None
    assert normalize_url(None) is None


def test_matchable_requires_approval_and_a_discipline():
    t = Talent(name="Maya", disciplines=[MusicDiscipline.COMPOSITION])
    assert t.matchable is False  # pending review by default
    t.review_status = ReviewStatus.APPROVED
    assert t.matchable is True


def test_approved_but_no_discipline_is_not_matchable():
    t = Talent(name="Theo", review_status=ReviewStatus.APPROVED)
    assert t.matchable is False


def test_declined_is_never_matchable():
    t = Talent(name="X", disciplines=[MusicDiscipline.SOUND_DESIGN],
               review_status=ReviewStatus.DECLINED)
    assert t.matchable is False


def test_discipline_labels():
    t = Talent(name="Sofia", disciplines=[MusicDiscipline.SONIC_BRANDING])
    assert t.discipline_labels == ["Sonic branding"]


def test_profile_completeness_scales_with_fields():
    bare = Talent(name="Only Name")
    full = Talent(
        name="Maya", email="m@x.com", disciplines=[MusicDiscipline.COMPOSITION],
        credits="Lots of credits", location="LA",
        demo_reel_url="https://x/reel",
    )
    assert profile_completeness(bare) < profile_completeness(full)
    assert profile_completeness(full) == 100


def test_default_funnel_stage_is_prospect():
    assert Talent(name="Z").invite_status is InviteStatus.PROSPECT


def test_audio_mixing_engineer_is_a_valid_discipline():
    # The new discipline resolves everywhere a per-discipline lookup happens.
    d = MusicDiscipline.MIXING
    assert d.label == "Audio mixing engineer"
    assert d.fit_weight == 1.0
    assert d.team_shape  # has a default team (no KeyError)
    # A creator can hold it; it's an approvable craft.
    t = Talent(name="Mix Pro", disciplines=[d])
    assert d in t.disciplines
