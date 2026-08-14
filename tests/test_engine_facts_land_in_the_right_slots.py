"""A perfect read filed under the wrong name is worth nothing.

The live comprehension call, 2026-08-14. The ten-agent engine passed every trap in the
script — the spoken correction ($45,000 not $40,000), the $2.1M media-spend distractor,
the conditional board-meeting deadline, the vocal negation, the disavowed Hans Zimmer
reference, three separate people correctly attributed, the eleven-week legal risk, the
weekly cadence. Genuinely hard comprehension, all of it right.

And then it filed the answers under names of its own choosing:

    $45,000                       -> "Production Budget"     (Budget: EMPTY)
    conditional launch window     -> "Seasonality"           (Timeline: EMPTY)
    :90 / :60 / :30 / 9:16 / stems-> "Production Budget"     (Deliverables: EMPTY)
    "Business Objective"          -> a DUPLICATE of "Business objective", by case alone

The estimate, the Campaign Brief and the proposal all read the canonical slots. Empty
canonical fields mean the whole downstream chain has nothing to work with, however good
the read was. The workers are already steered toward the canonical keys by a prompt
guide; a model that ignores the guide is not a bug you fix by asking louder.
"""
import pytest


def _ck(k):
    from chordential_oia.web.campaign_intelligence import canonical_key
    return canonical_key(k)


@pytest.mark.parametrize("proposed,expected", [
    ("Budget", "budget_band"),
    ("music_budget", "budget_band"),
    ("Seasonality", "deadline"),
    ("Timeline", "deadline"),
    ("launch_window", "deadline"),
    ("air_date", "deadline"),
    ("Assets", "deliverables"),
    ("spot_lengths", "deliverables"),
    ("References", "reference_playlist"),
    ("reference_tracks", "reference_playlist"),
    ("final_approver", "decision_makers"),
    ("Mood", "emotional_arc"),
    ("music_fee", "budget_band"),
])
def test_a_proposed_name_snaps_to_the_slot_it_means(proposed, expected):
    assert _ck(proposed) == expected


def test_case_alone_never_makes_a_second_field():
    """"Business Objective" rendered beside "Business objective" on the live call."""
    assert _ck("Business Objective") == _ck("business_objective") == "business_objective"


def test_a_canonical_key_is_left_exactly_as_it_is():
    for k in ("budget_band", "deadline", "deliverables", "decision_makers",
              "brand_notes", "agency_notes", "campaign_objective", "emotional_arc",
              "reference_playlist", "business_objective"):
        assert _ck(k) == k


def test_a_genuinely_new_field_still_passes_through():
    """The dynamic field must keep working — this is 'and also', not 'instead of'.
    'Legal contacts' and 'Campaign type' were real, useful fields the engine invented."""
    assert _ck("Legal Contacts") == "legal_contacts"
    assert _ck("Campaign Type") == "campaign_type"
    assert _ck("check_in_cadence") == "check_in_cadence"


def test_the_engines_answers_reach_the_canonical_slots(monkeypatch):
    """End to end, with the shape the live calls actually produced.

    Note what "Production Budget" now does, and why it is a deliberate trade. On call one
    the model used that name FOR the music fee, and aliasing it onto Budget filled the
    field correctly. On call two a speaker used the same words for the film's $900,000 and
    the alias put that in front of a client. The name is genuinely ambiguous, so it is no
    longer resolved by us: the extraction guide offers `budget_band` for the music figure
    explicitly, and a model that picks a different name is taken at its word. Budget stays
    empty and asks; it does not answer with the wrong number."""
    from chordential_oia.web import campaign_intake

    live_shape = [
        {"facet": "engagement", "key": "budget_band", "kind": "fact",
         "value": "$55,000-$65,000 all-in incl. licensing", "confidence": 90},
        {"facet": "engagement", "key": "Production Budget", "kind": "fact",
         "value": "Total production on the film is ~$900,000 (not the music)",
         "confidence": 90},
        {"facet": "engagement", "key": "Seasonality", "kind": "fact",
         "value": "Early spring, contingent on the board meeting", "confidence": 85},
        {"facet": "engagement", "key": "Legal Contacts", "kind": "fact",
         "value": "clearance took 11 weeks last cycle", "confidence": 80},
    ]
    got = {c["key"]: c["value"] for c in campaign_intake._canonicalise(live_shape)}
    assert "budget_band" in got and "55,000" in got["budget_band"]
    assert "900,000" not in got["budget_band"], "the distractor must never take the slot"
    assert "production_budget" in got, "and it must not be lost either"
    assert "deadline" in got and "spring" in got["deadline"]
    assert "legal_contacts" in got, "an invented field must survive canonicalisation"


def test_canonicalising_does_not_lose_or_merge_candidates():
    from chordential_oia.web import campaign_intake
    src = [{"facet": "engagement", "key": "Budget", "kind": "fact", "value": "a"},
           {"facet": "buyer", "key": "Whatever", "kind": "fact", "value": "b"}]
    out = campaign_intake._canonicalise(src)
    assert len(out) == 2
    assert src[0]["key"] == "Budget", "the caller's list must not be mutated"


@pytest.mark.parametrize("proposed", ["Production Budget", "production_budget"])
def test_a_production_budget_is_not_the_music_budget(proposed):
    """A belief this file used to hold, disproved on a live call.

    "Production Budget" was aliased onto the music slot because on the FIRST comprehension
    call that is what the model chose to call the music fee. On the second, a speaker used
    the words for what they ordinarily mean — "total production on the film is about nine
    hundred thousand" — and the alias walked that $900,000 into the Budget field, over the
    real figure, carrying "(not the music)" in its own text.

    An alias asserts two names mean the same thing. This pair does not, and a Budget field
    reading $900,000 is worse than an empty one: an empty field asks a question."""
    assert _ck(proposed) != "budget_band"
    assert _ck(proposed) == "production_budget"
