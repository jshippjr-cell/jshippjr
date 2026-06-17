"""Talent (supply-side) sources.

Every source implements :class:`base.TalentSource` and yields normalized
:class:`~chordential_oia.talent.Talent` records at the review-gate entry state.
``AVAILABLE_TALENT_SOURCES`` maps a source key to a zero-arg factory, mirroring
:data:`chordential_oia.sources.AVAILABLE_SOURCES`.

The live web-crawl source is intentionally NOT registered as an always-on
default: it only runs against targets Jon has approved (see
:mod:`chordential_oia.web.discovery`) and is gated by an environment flag, so the
demo source is the safe baseline here.
"""

from .base import TalentSource
from .sample import SampleTalentSource

AVAILABLE_TALENT_SOURCES = {
    "sample": SampleTalentSource,
}

__all__ = [
    "TalentSource",
    "SampleTalentSource",
    "AVAILABLE_TALENT_SOURCES",
]
