"""Talent source interface (Cycle 2.1) — supply-side mirror of OpportunitySource.

Everything a source yields must enter at the review gate: Pending, Prospect, and
NOT matchable until Jon approves the reel.
"""

import pytest

from chordential_oia.talent import InviteStatus, ReviewStatus
from chordential_oia.talent_sources import (
    AVAILABLE_TALENT_SOURCES,
    SampleTalentSource,
    TalentSource,
)


def test_base_is_abstract():
    with pytest.raises(TypeError):
        TalentSource()  # abstract fetch — cannot instantiate


def test_registry_resolves_sample():
    assert "sample" in AVAILABLE_TALENT_SOURCES
    src = AVAILABLE_TALENT_SOURCES["sample"]()
    assert isinstance(src, SampleTalentSource)


def test_sample_yields_pending_prospect_talent():
    creators = SampleTalentSource().fetch()
    assert creators, "sample source should yield candidates"
    for t in creators:
        assert t.review_status is ReviewStatus.PENDING
        assert t.invite_status is InviteStatus.PROSPECT
        # Pending creators are never matchable — the human gate holds.
        assert not t.matchable
        assert t.name and t.disciplines


def test_limit_is_respected():
    assert len(SampleTalentSource().fetch(limit=2)) == 2


def test_pending_helper_forces_gate_state():
    # Even if a source tries to pass an approved status, _pending overrides it.
    t = TalentSource._pending(
        name="X", review_status=ReviewStatus.APPROVED,
        invite_status=InviteStatus.JOINED,
    )
    assert t.review_status is ReviewStatus.PENDING
    assert t.invite_status is InviteStatus.PROSPECT
