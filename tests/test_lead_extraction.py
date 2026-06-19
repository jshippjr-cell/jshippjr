"""Lead-capture extraction: budget parsing + composer-title classification.

Covers the fixes for promoted gigs reading "budget Unknown" and a "Music
Composer" post being miscategorised as Sound Design.
"""

from chordential_oia.intake import extract_budget
from chordential_oia.models import MusicDiscipline, Opportunity
from chordential_oia.qualification import classify_discipline


def test_extract_budget_inline_and_clean():
    # Inline mid-paragraph (a pasted Reddit post is one flat block).
    assert extract_budget(
        "…creaking wood. Budget: $1,000-$1,500 USD Deliverables: …", labeled_only=True
    ) == (1000.0, 1500.0)
    # A clean captured field.
    assert extract_budget("$2k-$4k") == (2000.0, 4000.0)
    # Don't mistake a stray year for a budget.
    assert extract_budget("we shipped in 2024", labeled_only=True) == (None, None)


def test_composer_title_classifies_as_composition():
    opp = Opportunity(
        client="x",
        need="[PAID] Looking for Music Composer",
        description="trailer + main menu + ambience; ambient sounds, sound design, soundtrack",
    )
    primary, secondary = classify_discipline(opp)
    assert primary is MusicDiscipline.COMPOSITION             # not Sound Design
    assert MusicDiscipline.SOUND_DESIGN in secondary           # still noted


def test_sound_design_without_composer_title_stays_sound_design():
    opp = Opportunity(
        client="x",
        need="Sound designer for horror game",
        description="ambient sounds, foley, sound design, sfx",
    )
    primary, _ = classify_discipline(opp)
    assert primary is MusicDiscipline.SOUND_DESIGN             # unchanged
