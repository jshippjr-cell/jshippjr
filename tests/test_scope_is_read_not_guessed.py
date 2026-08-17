"""A brief that states its own length must be believed.

Traced from a live quote: a deal recorded as *"Branded documentary needs an original
score and supervision"* was priced at **$124,500** against a stated budget of
$20,000–$40,000. Roughly $48,000 of that was desk hours no brief had implied.

Two faults, compounding.

**The duration parser could not read a duration.** ``3 minute`` matched and ``3-minute``
did not, because the pattern required whitespace before the unit. Neither did
``three-minute``, ``90 seconds``, ``:90`` or ``30-second`` — and advertising music is
written in seconds nearly always. So a brief that stated its length was read as stating
nothing, and the format default won.

**The format default was a broadcast documentary.** "branded documentary" matched
``documentary`` and inherited thirty minutes and twenty cues. A branded piece is an
advertisement wearing documentary grammar; it runs a few minutes.

The honest fix is not a smaller default. It is reading what the brief actually says, and
keeping ``minutes_stated`` truthful either way — a client is entitled to know whether the
figure beside their fee was measured or assumed (ADR-0058).
"""
import pytest

from chordential_oia.estimation import (
    _stated_minutes, build_estimate, infer_scope,
)
from chordential_oia.models import (
    BuyerType, MusicDiscipline, MusicRequirement, Opportunity,
)


# ── the parser reads how people actually write durations ─────────────────────────────
@pytest.mark.parametrize("text,minutes", [
    ("a 3 minute film", 3.0),          # the one form that already worked
    ("3-minute film", 3.0),            # …and the more common one, which did not
    ("three-minute film", 3.0),
    ("2-minute brand film", 2.0),
    ("90 seconds of music", 1.5),      # advertising is written in seconds
    ("ninety seconds of score", 1.5),
    (":90 hero film", 1.5),
    ("30-second cutdown", 0.5),
    ("6 mins of underscore", 6.0),
])
def test_a_stated_duration_is_read_however_it_is_written(text, minutes):
    assert _stated_minutes(text) == pytest.approx(minutes)


def test_a_brief_that_states_nothing_still_says_nothing():
    """None and zero are different answers, and the difference is what `minutes_stated`
    reports to a client."""
    assert _stated_minutes("branded documentary, original score") is None


def test_the_piece_is_the_scope_not_a_part_of_it():
    """"A three-minute film with a 90-second wordless middle section" states both the
    piece and a part of it. Taking the first match would price the part."""
    assert _stated_minutes(
        "a three-minute film with a 90-second wordless middle section") == 3.0


def test_a_timestamp_is_not_a_runtime():
    """":90" is ninety seconds; "1:45:00" is not a ninety-minute cue."""
    assert _stated_minutes("see 1:45:00 in the cut") is None


# ── branded content is an advertisement, not a broadcast documentary ─────────────────
def test_branded_content_does_not_inherit_the_long_form_default():
    """The live defect. Thirty minutes and twenty cues, assumed, from the word
    'documentary' in a brief for a brand film."""
    scope = infer_scope("branded documentary needs an original score and supervision")
    assert scope.kind == "scored"
    assert scope.minutes <= 6, f"still assuming {scope.minutes} minutes of music"
    assert scope.cues <= 6
    assert not scope.minutes_stated, "an assumed figure must not claim to be stated"


def test_a_real_documentary_keeps_its_scale():
    """The guard on the fix: this must not quietly become cheap for everyone."""
    scope = infer_scope("feature documentary, original score, 30 minutes of music")
    assert scope.minutes == 30.0 and scope.minutes_stated


def test_a_branded_brief_that_states_a_duration_is_believed_over_any_default():
    scope = infer_scope("3-minute branded documentary, original score")
    assert scope.minutes == 3.0 and scope.minutes_stated


def test_assumed_cues_cannot_outnumber_the_minutes_stated():
    """Twenty assumed cues across a stated three minutes is twenty spotting-and-delivery
    allowances for a piece that can hold about three."""
    scope = infer_scope("3-minute documentary, original score")
    assert scope.cues <= 3
    # A STATED cue count is theirs, and is not trimmed.
    stated = infer_scope("3-minute documentary, original score, 8 cues")
    assert stated.cues == 8 and stated.cues_stated


# ── what it does to the number ───────────────────────────────────────────────────────
def _est(desc, need="Original score"):
    # `need` is neutral by default: it is fed to the inference along with the description,
    # and a fixture whose TITLE said "Branded Documentary" made every case branded —
    # including the ones written to prove long-form work still prices like long-form.
    opp = Opportunity(client="Brightline Films", need=need, description=desc,
                      buyer_type=BuyerType.AGENCY,
                      music_requirement=MusicRequirement.ORIGINAL)
    return build_estimate(opp, [], MusicDiscipline.COMPOSITION)


def test_the_live_deal_stops_costing_a_feature_documentary():
    """$124,500 quoted against a stated $20,000–$40,000, on a brief that never asked for
    thirty minutes of music."""
    est = _est("Branded documentary needs an original score and supervision.",
               need="Original Score for Branded Documentary")
    assert est.estimated_cost < 15_000, (
        f"still costing ${est.estimated_cost:,.0f} for a branded film")


def test_a_genuine_long_form_score_is_still_priced_like_one():
    """The number that must NOT move. If this falls with the rest, the fix is not a fix,
    it is a discount."""
    est = _est("Feature documentary, original score, 30 minutes of music, 20 cues.")
    assert est.estimated_cost > 30_000


def test_reading_the_duration_moves_the_price_by_an_order_of_magnitude():
    """The two readings of one brief, side by side — the reason a parser gap is a
    commercial defect and not a tidiness one."""
    assumed = _est("Feature documentary, original score.")
    stated = _est("Feature documentary, original score, 3 minutes of music.")
    assert assumed.estimated_cost > stated.estimated_cost * 3
