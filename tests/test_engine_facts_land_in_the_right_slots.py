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
    ("Production Budget", "budget_band"),
    ("production_budget", "budget_band"),
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
    """End to end, with the shape the live call actually produced."""
    from chordential_oia.web import campaign_intake

    live_shape = [
        {"facet": "engagement", "key": "Production Budget", "kind": "fact",
         "value": "$45,000 all-in incl. licensing", "confidence": 90},
        {"facet": "engagement", "key": "Seasonality", "kind": "fact",
         "value": "Early spring, contingent on the board meeting", "confidence": 85},
        {"facet": "engagement", "key": "Legal Contacts", "kind": "fact",
         "value": "clearance took 11 weeks last cycle", "confidence": 80},
    ]
    got = {c["key"]: c["value"] for c in campaign_intake._canonicalise(live_shape)}
    assert "budget_band" in got and "45,000" in got["budget_band"]
    assert "deadline" in got and "spring" in got["deadline"]
    assert "legal_contacts" in got, "an invented field must survive canonicalisation"


def test_canonicalising_does_not_lose_or_merge_candidates():
    from chordential_oia.web import campaign_intake
    src = [{"facet": "engagement", "key": "Budget", "kind": "fact", "value": "a"},
           {"facet": "buyer", "key": "Whatever", "kind": "fact", "value": "b"}]
    out = campaign_intake._canonicalise(src)
    assert len(out) == 2
    assert src[0]["key"] == "Budget", "the caller's list must not be mutated"
