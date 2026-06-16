"""Tests for the Talent domain model (supply-side foundation)."""

from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import (
    InviteStatus,
    ReviewStatus,
    Talent,
    profile_completeness,
)


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
