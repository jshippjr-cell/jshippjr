"""Scored media is priced by the minute, and the campaign path is untouched.

The defect, measured on the engine before this existed:

    1 cue,  orchestral, national   ->  $57,446
    60 cues, orchestral, national  ->  $57,446
    2 minutes of score             ->  $57,446
    90 minutes of score            ->  $57,446

The amount of music moved the number by ZERO. Only the format words — "orchestra",
"national", the cutdown list — did anything, and the consequence was not a rounding
error: **a :60 commercial with two cutdowns (90 seconds of music) quoted at 1.33× a
28-cue, 45-minute orchestral feature score.** The product sells a film/TV engagement it
could not price.

Two properties carry the weight here. `test_more_music_costs_more` is the fix. The
frozen-campaign tests are the guard: the campaign path was calibrated into the public
band by ADR-0028 and ADR-0033, and a scoring model that quietly moved it would trade
one mispriced product for another.
"""

import pytest

from chordential_oia.estimation import EstimationEngine, build_estimate, infer_scope
from chordential_oia.models import MusicDiscipline, Opportunity

E = EstimationEngine()


def _est(need, description="", tags=()):
    opp = Opportunity(client="X", need=need, description=description, tags=list(tags))
    return E.estimate(opp, discipline=MusicDiscipline.COMPOSITION)


def _price(need, description=""):
    return _est(need, description).suggested_price


FEATURE = "Original score for a feature film"


# --------------------------------------------------------------------------- #
# The defect
# --------------------------------------------------------------------------- #
def test_more_music_costs_more():
    """The whole item. Before this, every one of these was the same number."""
    prices = [_price(FEATURE, f"Feature film score. {m} minutes of original score. "
                              f"Full orchestra. National.")
              for m in (2, 15, 45, 90)]
    assert prices == sorted(prices), prices
    assert len(set(prices)) == 4, "the amount of music still does not move the price"
    assert prices[-1] > prices[0] * 4, (
        "90 minutes of score is not meaningfully dearer than 2 minutes: "
        f"{prices[0]:,.0f} -> {prices[-1]:,.0f}")


def test_more_cues_over_the_same_minutes_costs_more():
    """45 minutes across 8 cues and 45 minutes across 40 cues are not the same job.
    The difference is thirty-two spotting notes and thirty-two approvals, which is
    what a per-minute rate on its own gets wrong."""
    few = _price(FEATURE, "Feature film score. 45 minutes of score across 8 cues. Orchestral.")
    many = _price(FEATURE, "Feature film score. 45 minutes of score across 40 cues. Orchestral.")
    assert many > few


def test_a_feature_score_outprices_a_sixty_second_commercial():
    """The comparison the review named. A :60 with two cutdowns is ninety seconds of
    music; if it quotes above a 45-minute orchestral feature score, the engine cannot
    be used to sell the engagement the product is built around."""
    spot = _price(":60 anthem with :30 and :15 cutdowns",
                  "National :60 anthem with :30 and :15 cutdowns, full orchestra.")
    film = _price(FEATURE,
                  "Feature film score. 28 cues, approximately 45 minutes of original "
                  "score, full orchestra. National theatrical.")
    assert film > spot * 2, f"feature ${film:,.0f} vs :60 spot ${spot:,.0f}"


# --------------------------------------------------------------------------- #
# The campaign path must not move
# --------------------------------------------------------------------------- #
CAMPAIGN_CASES = [
    (":30 spot", "National broadcast :30 spot."),
    (":60 anthem with :30 and :15 cutdowns", "National :60 anthem, full orchestra."),
    ("Sonic logo", "Short mnemonic for a global brand."),
    ("Social cutdowns", "A :15 and a :06 for social."),
]


@pytest.mark.parametrize("need,desc", CAMPAIGN_CASES)
def test_a_campaign_brief_is_still_priced_per_cue(need, desc):
    """ADR-0028 and ADR-0033 calibrated this path into the public band. A scoring
    model that quietly moved it would trade one mispriced product for another."""
    est = _est(need, desc)
    assert est.scope is None, "a campaign brief was routed onto the scored model"
    assert any(m.name == "Duration" for m in est.multipliers)


def test_the_campaign_numbers_are_bit_for_bit_what_they_were():
    """Golden values MEASURED on the engine immediately before the scoring model went
    in. A band check would pass while the number drifted inside it; these will not.

    If a legitimate campaign-pricing change moves them, update them in the same commit
    that argues for the move — do not widen this into a range."""
    assert round(_price(":30 spot", "National broadcast :30 spot."), 4) == 11132.9167
    assert round(_price(":60 anthem with :30 and :15 cutdowns",
                        "National :60 anthem with :30 and :15 cutdowns, full "
                        "orchestra."), 4) == 76191.3000
    assert round(_price("Sonic logo",
                        "Short mnemonic for a global brand."), 4) == 22265.8333


# --------------------------------------------------------------------------- #
# Reading the brief — and refusing to over-read it
# --------------------------------------------------------------------------- #
def test_a_format_word_alone_does_not_make_it_scored():
    """"Episode" turns up in podcast briefs and "series" in campaign briefs ("the
    series of six spots"). Misreading either swaps a campaign onto a model that prices
    in tens of minutes, so BOTH a format and a scoring signal are required."""
    assert infer_scope("a series of six spots for the spring campaign").kind == "campaign"
    assert infer_scope("podcast episode intro sting").kind == "campaign"
    assert infer_scope("feature film score, 30 cues").kind == "scored"


def test_a_minutes_figure_in_a_campaign_brief_is_not_a_score():
    """"2 minute edit" is a long spot, not two minutes of film score."""
    assert infer_scope("2 minute brand edit, national").kind == "campaign"


def test_a_stated_range_is_read_as_its_midpoint():
    """"20-30 cues" is 25, not 30. Quoting the top of every range someone writes down
    biases every estimate high, and the band already covers the spread."""
    s = infer_scope("feature film score with 20-30 cues")
    assert s.cues == 25 and s.cues_stated


def test_per_episode_quantities_multiply_by_the_episode_count():
    """"10 episodes, 6 minutes of score per episode" is an hour of music, not six
    minutes — the units the buyer speaks in are per-episode."""
    s = infer_scope("original score for a 10 episode series, 6 minutes of score per episode")
    assert s.episodes == 10
    assert s.minutes == 60.0 and s.minutes_stated


def test_an_unstated_scope_falls_back_and_says_so():
    """An estimate has to put a number on a vague brief — but the assumption is the
    biggest driver of that number, so it is never presented as a fact."""
    s = infer_scope("original score for a feature film")
    assert s.minutes > 0 and not s.minutes_stated
    assert "(assumed)" in s.summary


def test_the_assumption_is_flagged_on_the_estimate_itself():
    """The honesty rule, at the surface a client's number comes from.

    A fully specified brief has to answer all four: how much music, how many cues,
    who plays and on how many dates. Stating the minutes alone still leaves the
    session — half the cost — guessed."""
    vague = _est(FEATURE, "Feature film score. Orchestral. National.")
    assert any("ASSUMED" in a for a in vague.assumptions), vague.assumptions

    part = _est(FEATURE, "Feature film score. 45 minutes of score across 28 cues. "
                         "Orchestral. National.")
    flagged = next(a for a in part.assumptions if a.startswith("ASSUMED"))
    assert "minutes of score" not in flagged and "cue count" not in flagged
    assert "player count" in flagged, "the session was quietly assumed without saying so"

    exact = _est(FEATURE, "Feature film score. 45 minutes of score across 28 cues. "
                          "Orchestral, 60 musicians over 4 recording dates. National.")
    assert not any("ASSUMED" in a for a in exact.assumptions), exact.assumptions


def test_the_unmodelled_discount_is_declared_rather_than_hidden():
    """Per-minute hours are linear, and thematic reuse genuinely makes the ninetieth
    minute cheaper than the first. Inventing a decline curve would be a number with
    nothing behind it; not saying so would be worse."""
    est = _est(FEATURE, "Feature film score. 90 minutes of score across 40 cues.")
    assert any("LINEAR" in a for a in est.assumptions)


# --------------------------------------------------------------------------- #
# What the money is made of
# --------------------------------------------------------------------------- #
def test_orchestral_writing_is_not_the_same_purchase_as_hiring_an_orchestra():
    """The conflation that made an indie feature carry a studio's budget: the single
    word "orchestra" bought the orchestration hours AND thirty players on every date.
    A sampled orchestral score is a real and common delivery and had no expression."""
    live = _est(FEATURE, "Feature film score. 45 minutes across 28 cues, full orchestra.")
    sampled = _est(FEATURE, "Feature film score. 45 minutes across 28 cues, orchestral, "
                            "sampled / virtual instruments, no live players.")
    assert sampled.session_cost == 0
    assert live.session_cost > 0
    # The DESK cost is identical — the orchestration hours are still owed.
    assert sampled.estimated_cost + live.session_cost == pytest.approx(live.estimated_cost)
    assert sampled.suggested_price < live.suggested_price


def test_a_stated_player_count_beats_the_style_word():
    """"String quartet" and "full orchestra" are not the same session, whatever the
    writing style says."""
    quartet = _est(FEATURE, "Feature film score. 45 minutes across 28 cues, orchestral "
                            "writing, live string quartet over 2 recording dates.")
    assert quartet.session.players == 4 and quartet.session.players_stated
    assert quartet.session.dates == 2 and quartet.session.dates_stated
    big = _est(FEATURE, "Feature film score. 45 minutes across 28 cues, full orchestra, "
                        "60 musicians over 4 recording dates.")
    assert big.session.players == 60
    assert big.session_cost > quartet.session_cost * 5


def test_naming_the_players_is_answering_the_live_question():
    """A brief that books a quartet for two dates has said the players are live.
    Asking the operator to confirm it again is noise, and noise teaches people to
    stop reading the warnings that matter."""
    q = _est(FEATURE, "Feature film score. 45 minutes across 28 cues, live string "
                      "quartet over 2 recording dates.")
    assert not any("live or sampled" in a for a in q.assumptions)


def test_an_unstated_session_is_flagged_as_the_guess_it_is():
    """The session is routinely half the cost of a scored engagement, so an assumed
    thirty players is the biggest single guess in the estimate."""
    vague = _est(FEATURE, "Feature film score. Orchestral. National.")
    flagged = next(a for a in vague.assumptions if a.startswith("ASSUMED"))
    assert "player count" in flagged and "recording dates" in flagged


def test_recording_dates_scale_with_the_minutes_recorded():
    """A 45-minute score is a booking schedule, not one session. Pretending otherwise
    is what let a feature carry the same session line as a :30."""
    short = _est(FEATURE, "Feature film score. 6 minutes of score. Full orchestra.")
    long = _est(FEATURE, "Feature film score. 60 minutes of score. Full orchestra.")
    assert short.session_dates == 1
    assert long.session_dates > short.session_dates
    assert long.session_cost > short.session_cost


def test_a_quartet_covers_more_ground_per_date_than_an_orchestra():
    """More players to fix, more takes to comp — so the same minutes need more dates."""
    orch = _est(FEATURE, "Feature film score. 60 minutes of score. Full orchestra.")
    small = _est(FEATURE, "Feature film score. 60 minutes of score. Small ensemble strings.")
    assert orch.session_dates > small.session_dates


def test_spot_length_is_not_applied_on_top_of_the_minutes():
    """":30" in a feature brief (a teaser deliverable, say) must not multiply a score
    already priced by the minute — that counts the same music twice."""
    est = _est(FEATURE, "Feature film score. 45 minutes of score. Also a :30 teaser cut.")
    assert not any(m.name in ("Duration", "Cutdowns") for m in est.multipliers)


def test_the_estimate_is_deterministic():
    """No LLM, no clock, no randomness — the same brief prices the same way twice."""
    a = _price(FEATURE, "Feature film score. 45 minutes across 28 cues. Orchestral.")
    b = _price(FEATURE, "Feature film score. 45 minutes across 28 cues. Orchestral.")
    assert a == b


def test_the_web_layer_prices_a_feature_through_the_one_call_path():
    """ADR-0033: `estimate_for` is the only way the web layer prices anything, and it
    has to carry the scope through or the console shows a number the engine disowns."""
    from chordential_oia.web.estimate import estimate_for
    opp = Opportunity(client="X", need=FEATURE,
                      description="Feature film score. 45 minutes across 28 cues. Orchestral.")
    est = estimate_for(opp)
    assert est.scope is not None and est.scope.minutes == 45.0
