"""Tests for the Talent Matcher (deterministic profile + credits matching)."""

from chordential_oia.matching import match_talent
from chordential_oia.models import MusicDiscipline
from chordential_oia.talent import ReviewStatus, Talent


def _t(name, disciplines, credits="", approved=True):
    return Talent(
        name=name, disciplines=disciplines, credits=credits,
        review_status=ReviewStatus.APPROVED if approved else ReviewStatus.PENDING,
    )


def test_only_matchable_creators_are_recommended():
    approved = _t("Approved", [MusicDiscipline.COMPOSITION])
    pending = _t("Pending", [MusicDiscipline.COMPOSITION], approved=False)
    out = match_talent(MusicDiscipline.COMPOSITION, [], "original score", [approved, pending])
    names = [m.name for m in out]
    assert "Approved" in names and "Pending" not in names


def test_no_craft_fit_is_excluded():
    sup = _t("Supervisor only", [MusicDiscipline.SUPERVISION])
    out = match_talent(MusicDiscipline.COMPOSITION, [], "original score", [sup])
    assert out == []


def test_primary_discipline_outranks_secondary():
    composer = _t("Composer", [MusicDiscipline.COMPOSITION])
    arranger = _t("Arranger", [MusicDiscipline.ARRANGEMENT])
    out = match_talent(
        MusicDiscipline.COMPOSITION, [MusicDiscipline.ARRANGEMENT],
        "original composition", [arranger, composer],
    )
    assert out[0].name == "Composer"
    assert out[0].score > out[1].score


def test_credits_overlap_raises_score_and_is_explained():
    generic = _t("Generic", [MusicDiscipline.COMPOSITION], credits="wrote some things")
    relevant = _t("Relevant", [MusicDiscipline.COMPOSITION],
                  credits="composer on a national automotive campaign trailer")
    out = match_talent(
        MusicDiscipline.COMPOSITION, [],
        "Automotive campaign trailer needing an original automotive cue",
        [generic, relevant],
    )
    top = out[0]
    assert top.name == "Relevant"
    assert any("Credits overlap" in r for r in top.reasons)


def test_deterministic_ordering():
    a = _t("Anna", [MusicDiscipline.COMPOSITION])
    b = _t("Bilal", [MusicDiscipline.COMPOSITION])
    o1 = match_talent(MusicDiscipline.COMPOSITION, [], "score", [a, b])
    o2 = match_talent(MusicDiscipline.COMPOSITION, [], "score", [b, a])
    assert [m.name for m in o1] == [m.name for m in o2]
